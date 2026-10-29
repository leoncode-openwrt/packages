#!/usr/bin/env python3
"""Bind prepared builds to a checked SDK, staged inputs and completed output bytes."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("prepared_validation", Path(__file__).with_name("validate-prepared.py"))
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
IDENTITY = ".sdk-provenance.json"
RECEIPT = ".custom-build-receipt.json"
IMMUTABLE = {"include/version.mk", "rules.mk", "include/target.mk", "Config.in", "Config-build.in", "feeds.conf.default"}


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalized(relative, data):
    if relative == "feeds.conf.default":
        data = data.replace(b"https://git.openwrt.org/openwrt/openwrt.git", b"https://github.com/openwrt/openwrt.git")
    return data


def write_new(path, data):
    encoded = json.dumps(data, sort_keys=True, indent=2) + "\n"
    if path.exists():
        v.require(v.load_json(path) == data, f"Refusing to replace a different receipt: {path.name}")
        return
    with path.open("x") as stream:
        stream.write(encoded)


def archive_identity(archive, group):
    v.require(archive.is_file() and sha(archive) == group["sdk_sha256"], "Original SDK archive hash differs from the build matrix")
    prefix = group["sdk_file"].removesuffix(".tar.zst") + "/"
    found = {}
    process = subprocess.Popen(["zstd", "-dc", str(archive)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as tf:
            for member in tf:
                if not member.name.startswith(prefix):
                    continue
                relative = member.name[len(prefix):]
                if relative not in IMMUTABLE and not re.fullmatch(r"staging_dir/toolchain-[^/]+/info.mk", relative):
                    continue
                v.require(member.isfile() and member.size < 1024 * 1024, "Invalid SDK identity member")
                v.require(relative not in found, "Duplicate SDK identity member")
                found[relative] = normalized(relative, tf.extractfile(member).read())
        v.require(process.wait() == 0, "Unable to decompress original SDK archive")
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.terminate()
            process.wait()
    v.require(IMMUTABLE <= set(found) and len(found) == len(IMMUTABLE) + 1, "SDK archive lacks its expected identity files")
    version = found["include/version.mk"].decode()
    v.require("VERSION_NUMBER:=$(if $(VERSION_NUMBER),$(VERSION_NUMBER),25.12.6)" in version, "SDK archive is not release 25.12.6")
    return {"release": v.RELEASE, "arch": group["arch"], "target": group["target"], "sdk_file": group["sdk_file"], "sdk_sha256": group["sdk_sha256"], "identity_files": {p: v.digest(data) for p, data in sorted(found.items())}}


def check_identity(sdk, group, identity):
    for name in ("release", "arch", "target", "sdk_file", "sdk_sha256"):
        expected = v.RELEASE if name == "release" else group[name]
        v.require(identity.get(name) == expected, f"SDK identity mismatch: {name}")
    paths = identity.get("identity_files", {})
    v.require(IMMUTABLE <= set(paths) and len(paths) == len(IMMUTABLE) + 1, "Incomplete SDK identity receipt")
    for relative, expected in paths.items():
        path = v.project_file(sdk, relative)
        v.require(v.digest(normalized(relative, path.read_bytes())) == expected, f"SDK identity file changed: {relative}")
    v.require("VERSION_NUMBER:=$(if $(VERSION_NUMBER),$(VERSION_NUMBER),25.12.6)" in (sdk / "include/version.mk").read_text(), "SDK runtime release mismatch")


def files(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        v.require(not path.is_symlink(), "Symlink in build input")
        if path.is_file():
            result[str(path.relative_to(directory))] = {"sha256": sha(path), "executable": bool(path.stat().st_mode & 0o111)}
    return result


def inputs(repo, sdk, group, checked):
    result = {"group": group, "source_manifest": checked["source_manifest"], "source_files": files(repo / "sources"), "recipes": {}}
    for package, recipe in group["recipes"].items():
        expected = files(repo / "packages" / recipe)
        v.require(files(sdk / "package/custom" / package) == expected, f"Staged recipe differs from reviewed inputs: {recipe}")
        result["recipes"][recipe] = expected
        source = checked["source_manifest"]["recipes"][recipe]
        for subdir in ("dl", "custom-distfiles"):
            path = v.project_file(sdk, subdir + "/" + source["archive"])
            v.require(sha(path) == source["sha256"], f"Staged source archive changed: {recipe}/{subdir}")
    return result


def config_check(sdk, group):
    config = (sdk / ".config").read_text()
    values = dict(re.findall(r'^([A-Za-z0-9_-]+)=(.*)$', config, re.M))
    v.require(values.get("CONFIG_VERSION_NUMBER", '""').strip('"') in ("", v.RELEASE), "SDK release override differs from 25.12.6")
    board, subtarget = group["target"].split("/")
    for name, expected in (("CONFIG_TARGET_BOARD", board), ("CONFIG_TARGET_SUBTARGET", subtarget), ("CONFIG_TARGET_ARCH_PACKAGES", group["apk_arch"])):
        v.require(values.get(name, "").strip('"') == expected, f"SDK target mismatch: {name}")
    for package in group["packages"]:
        v.require(values.get("CONFIG_PACKAGE_" + package) in ("y", "m"), f"Required package not selected: {package}")
    v.require(values.get("CONFIG_IPV6") == "y", "IPv6 support is not selected")
    return sha(sdk / ".config")


def prepared_sources(repo, sdk, group, checked):
    result = {}
    with tempfile.TemporaryDirectory(prefix="prepared-build-source-check-") as temporary:
        for package, recipe in group["recipes"].items():
            entry = checked["source_manifest"]["recipes"][recipe]
            destination = Path(temporary) / recipe
            destination.mkdir()
            # The offline validator has already checked archive paths/types/hashes.
            with tarfile.open(repo / "sources" / entry["archive"], "r:*") as tf:
                tf.extractall(destination, filter="data")
            expected = destination / entry["source_root"]
            for patch in entry["patches"]:
                process = subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn", str(repo / patch["path"])], cwd=expected, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                v.require(process.returncode == 0, "Unable to reconstruct patched build source")
            # The IPv6-only package has its own variant directory; do not inspect
            # a historical generic odhcpd source tree from an unselected build.
            pattern = "target-*/" + ("odhcpd-ipv6only/" if package == "odhcpd" else "") + entry["source_root"]
            matches = [p for p in (sdk / "build_dir").glob(pattern) if p.is_dir()]
            v.require(len(matches) == 1, f"Expected one actual prepared source directory: {recipe}, found {len(matches)}")
            actual = matches[0]
            expected_files = files(expected)
            for relative, record in expected_files.items():
                path = v.project_file(actual, relative)
                v.require(sha(path) == record["sha256"] and bool(path.stat().st_mode & 0o111) == record["executable"], f"Actually used source differs from reviewed source: {recipe}/{relative}")
            result[recipe] = {"directory": str(actual.relative_to(sdk)), "files": expected_files}
    return result


def outputs(sdk, group):
    hashes, by_name = {}, {}
    for path in sorted((sdk / "bin").rglob("*.apk")):
        value = sha(path)
        v.require(path.name not in by_name or by_name[path.name] == value, "Different APK bytes under the same filename")
        by_name[path.name] = value
        hashes[str(path.relative_to(sdk))] = value
    for artifact in group["artifacts"]:
        name = artifact["name"] + "-" + artifact["version"] + ".apk"
        v.require(name in by_name, f"Expected completed APK missing: {name}")
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "check-sdk", "begin", "finish", "verify", "adopt-retrospective"))
    parser.add_argument("arch")
    parser.add_argument("sdk", type=Path)
    parser.add_argument("--archive", type=Path, help="Original checksum-pinned SDK archive, required by register/adopt-retrospective")
    args = parser.parse_args()
    try:
        repo = Path(__file__).resolve().parents[1]
        checked = v.validate_repo(repo)
        groups = [g for g in checked["groups"] if g["arch"] == args.arch]
        v.require(len(groups) == 1, "Unknown build architecture")
        group, sdk = groups[0], args.sdk.resolve()
        if args.command in ("register", "adopt-retrospective"):
            v.require(args.archive is not None, "Original SDK archive is required")
            identity = archive_identity(args.archive, group)
            check_identity(sdk, group, identity)
            write_new(sdk / IDENTITY, identity)
        else:
            identity = v.load_json(v.project_file(sdk, IDENTITY))
            check_identity(sdk, group, identity)
        if args.command in ("register", "check-sdk"):
            print("Verified SDK archive identity: " + group["target"] + " / " + v.RELEASE)
            return 0
        current = inputs(repo, sdk, group, checked)
        config_hash = config_check(sdk, group)
        receipt_path = sdk / RECEIPT
        if args.command == "begin":
            v.require(not receipt_path.exists(), "Build receipt already exists; use a fresh SDK")
            write_new(receipt_path, {"schema": 1, "mode": "recorded_before_build", "completed": False, "sdk_identity": identity, "inputs": current, "sdk_config_sha256": config_hash})
            print("Recorded reviewed inputs before compilation")
            return 0
        if args.command == "adopt-retrospective":
            receipt = {"schema": 1, "mode": "retrospective_checked_completed_build", "completed": True, "sdk_identity": identity, "inputs": current, "sdk_config_sha256": config_hash, "prepared_sources": prepared_sources(repo, sdk, group, checked), "built_apks_sha256": outputs(sdk, group), "limitation": "Attests checked original SDK archive, current staged/compiled source files and completed APK bytes; did not observe compilation from a pre-build receipt."}
            write_new(receipt_path, receipt)
        else:
            receipt = v.load_json(v.project_file(sdk, RECEIPT))
            v.require(receipt.get("schema") == 1 and receipt.get("sdk_identity") == identity and receipt.get("inputs") == current and receipt.get("sdk_config_sha256") == config_hash, "Build inputs, SDK or configuration changed since receipt")
            actual_sources, actual_outputs = prepared_sources(repo, sdk, group, checked), outputs(sdk, group)
            if args.command == "finish":
                v.require(receipt.get("mode") == "recorded_before_build" and receipt.get("completed") is False, "Only an unfinished normal build can be completed")
                receipt.update(completed=True, prepared_sources=actual_sources, built_apks_sha256=actual_outputs)
                # Atomic transition of this SDK's own unfinished build receipt.
                temporary = receipt_path.with_suffix(".json.tmp")
                with temporary.open("x") as stream:
                    json.dump(receipt, stream, indent=2, sort_keys=True)
                    stream.write("\n")
                temporary.replace(receipt_path)
            else:
                v.require(receipt.get("completed") is True and receipt.get("mode") in ("recorded_before_build", "retrospective_checked_completed_build"), "Completed build receipt required")
                v.require(receipt.get("prepared_sources") == actual_sources and receipt.get("built_apks_sha256") == actual_outputs, "Prepared source or APK bytes changed after completion")
        print("Verified completed build: " + args.arch + " (" + receipt["mode"] + ")")
        return 0
    except (v.ValidationError, OSError, ValueError, KeyError, TypeError, tarfile.TarError) as error:
        print("SDK provenance check failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
