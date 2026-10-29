#!/usr/bin/env python3
"""Validate the reviewed 25.12.6 build inputs without building or extracting them."""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

RELEASE = "25.12.6"
# Deliberate source changes require review of these pins, the manifests and tests.
EXPECTED_PINS = {
    "odhcpd-stable": ("openwrt/odhcpd", "5d7be43f8b9dec0eb47e245cfab81108bb131273"),
    "ustp-router": ("JxnLexn/openwrt-ustp", "64752fd2a3725665733169e6914082aac0d7d625"),
    "ustp-ap": ("JxnLexn/openwrt-ustp", "8d50cbac0c54f936dbcc47985957827d6e03a6de"),
    "usteer": ("JxnLexn/usteer", "947969722087281b874fe7b4dbfe36c5b462c1fc"),
}
EXPECTED_PATCHES = {
    "odhcpd-stable": {
        "999-dns-rewrite-relay-search-domains.patch":
            "92909f8647ff8f53ee13185452ce5070b0df4a5246c7c4ab486f60e2e82e92d7",
    },
    "ustp-router": {
        "100-assign-destination-single-evaluation.patch":
            "f67765d8de42e031e9c0824e16f055d4210a74ae7c2f3246f7b811b5c61057b5",
    },
    "ustp-ap": {},
    "usteer": {},
}
EXPECTED_GROUPS = {
    "x86_64": ("x86_64", "x86/64", {"odhcpd": "odhcpd-stable", "ustp": "ustp-router"}),
    "aarch64_cortex-a53": ("aarch64_cortex-a53", "mediatek/filogic", {"ustp": "ustp-ap", "usteer": "usteer"}),
    "mipsel_24kc": ("mipsel_24kc", "ramips/mt7621", {"ustp": "ustp-ap", "usteer": "usteer"}),
}
BINARIES = {"odhcpd-ipv6only": "usr/sbin/odhcpd", "ustp": "sbin/ustpd", "usteer": "sbin/usteerd"}
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
MAX_MEMBER = 16 * 1024 * 1024
MAX_SOURCE = 64 * 1024 * 1024
LOCAL_DIFF = {
    "path": "sources/provenance/ustp-ap-from-public-base.patch",
    "sha256": "894c21d2656f12711932c0bc781c922bbe0aea00a5284d0f7d9120b4a55a1bce",
}


class ValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_relative(value):
    require(isinstance(value, str) and value, "Empty or non-string relative path")
    require("\\" not in value and not any(ord(c) < 32 for c in value), "Unsafe path characters")
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(p not in (".", "..") for p in value.split("/")), "Unsafe relative path")
    require(str(path) == value, "Non-canonical relative path")
    return path


def project_file(root, relative):
    safe_relative(relative)
    path = root / relative
    require(path.is_file() and not path.is_symlink(), f"Missing or symlinked file: {relative}")
    require(path.resolve().is_relative_to(root.resolve()), f"File escapes repository: {relative}")
    return path


def unique_json(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json(path):
    return json.loads(path.read_text(), object_pairs_hook=unique_json)


def git_object(kind, content):
    return hashlib.sha1(kind.encode() + b" " + str(len(content)).encode() + b"\0" + content).digest()


def hash_directory(directory):
    entries = []
    for name, child in directory.items():
        encoded = name.encode("utf-8")
        if isinstance(child, dict):
            entries.append((encoded + b"/", b"40000 " + encoded + b"\0" + hash_directory(child)))
        else:
            mode, blob = child
            entries.append((encoded, mode + b" " + encoded + b"\0" + blob))
    return git_object("tree", b"".join(item[1] for item in sorted(entries)))


def directory_tree(directory):
    tree, total = {}, 0
    for path in sorted(directory.rglob("*")):
        require(not path.is_symlink(), "Reconstruction produced a symbolic link")
        if path.is_dir():
            continue
        require(path.is_file() and path.stat().st_size <= MAX_MEMBER, "Invalid reconstructed file")
        data = path.read_bytes()
        total += len(data)
        require(total <= MAX_SOURCE, "Reconstructed source exceeds size limit")
        parts = path.relative_to(directory).parts
        cursor = tree
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = (b"100755" if path.stat().st_mode & 0o111 else b"100644", git_object("blob", data))
    return hash_directory(tree).hex()


def source_tree(archive, source_root):
    """Reject unsafe archives and reconstruct the Git tree from file bytes/modes."""
    safe_relative(source_root)
    require("/" not in source_root, "Source root must be a single directory")
    tree, seen, kinds = {}, set(), {}
    total = 0
    with tarfile.open(archive, "r:*") as tf:
        for member in tf:
            name = member.name.rstrip("/") if member.isdir() else member.name
            safe_relative(name)
            require(name not in seen, f"Duplicate archive member: {name}")
            seen.add(name)
            require(len(seen) <= 10000, "Source archive has too many members")
            require(name == source_root or name.startswith(source_root + "/"), "Archive escapes expected source root")
            require(member.isdir() or member.isfile(), f"Links and special archive members are forbidden: {name}")
            require(not member.mode & 0o7000, f"Special permission bits in archive: {name}")
            parts = PurePosixPath(name).parts
            for index in range(1, len(parts)):
                ancestor = "/".join(parts[:index])
                require(kinds.get(ancestor) != "file", "Archive path traverses a file")
            require(not (member.isfile() and any(p.startswith(name + "/") for p in kinds)), "Archive file replaces a directory")
            kinds[name] = "dir" if member.isdir() else "file"
            if member.isdir():
                continue
            require(name != source_root, "Source root is a file")
            require(0 <= member.size <= MAX_MEMBER, "Archive member exceeds size limit")
            total += member.size
            require(total <= MAX_SOURCE, "Expanded source archive exceeds size limit")
            data = tf.extractfile(member).read(MAX_MEMBER + 1)
            require(len(data) == member.size, "Truncated archive member")
            cursor = tree
            inner = parts[1:]
            for part in inner[:-1]:
                cursor = cursor.setdefault(part, {})
                require(isinstance(cursor, dict), "Conflicting source tree path")
            require(inner[-1] not in cursor, "Conflicting source tree leaf")
            cursor[inner[-1]] = (b"100755" if member.mode & 0o111 else b"100644", git_object("blob", data))
    require(tree, "Source archive has no files")

    return hash_directory(tree).hex()


def check_patch_paths(path):
    for line in path.read_text().splitlines():
        require(line not in ("new file mode 120000", "new mode 120000", "new file mode 160000", "new mode 160000"), "Patch introduces a symlink or submodule")
        if line.startswith(("--- ", "+++ ")):
            target = line[4:].split("\t", 1)[0].split(" ", 1)[0]
            if target != "/dev/null":
                require(target.startswith(("a/", "b/")), "Unexpected patch path prefix")
                relative = safe_relative(target[2:])
                require(".git" not in relative.parts, "Patch targets Git metadata")


def verify_archived_local(root, entries):
    local = entries["ustp-ap"]
    provenance = local.get("provenance", {})
    require(provenance.get("type") == "archived_local", "AP source must be identified as locally archived")
    base = entries["ustp-router"]
    require(provenance.get("public_base") == {
        "recipe": "ustp-router", "repository": base["repository"],
        "commit": base["commit"], "git_tree": base["git_tree"],
    }, "Local source has an unreviewed public base")
    require(provenance.get("diff") == LOCAL_DIFF, "Local source reconstruction diff is unreviewed")
    patch = project_file(root, LOCAL_DIFF["path"])
    require(digest(patch.read_bytes()) == LOCAL_DIFF["sha256"], "Local reconstruction diff hash mismatch")
    check_patch_paths(patch)
    actual = {str(p.relative_to(root)) for p in (root / "sources/provenance").glob("*.patch")}
    require(actual == {LOCAL_DIFF["path"]}, "Unlisted source reconstruction diff")
    # source_tree() already validated every archive path, type, size and digest.
    with tempfile.TemporaryDirectory(prefix="prepared-source-reconstruction-") as temporary:
        destination = Path(temporary)
        with tarfile.open(root / "sources" / base["archive"], "r:*") as archive:
            archive.extractall(destination, filter="data")
        source = destination / base["source_root"]
        command = ["git", "-c", "core.autocrlf=false", "-c", "core.filemode=true", "apply", "--whitespace=nowarn"]
        for options in (["--check", str(patch)], [str(patch)]):
            run = subprocess.run(command + options, cwd=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            require(run.returncode == 0, "Local reconstruction diff does not apply cleanly to the public base")
        require(directory_tree(source) == local["git_tree"], "Reconstructed local source differs from the pinned AP archive")


def recipe_values(makefile):
    text = makefile.read_text()
    values = {}
    needed = {"PKG_NAME", "PKG_VERSION", "PKG_RELEASE", "PKG_SOURCE", "PKG_SOURCE_URL", "PKG_HASH", "PKG_SOURCE_VERSION", "USTEER_SOURCE_COMMIT"}
    for line in text.splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)\s*:?=\s*(.*?)\s*$", line)
        if match and match[1] in needed:
            require(match[1] not in values, f"Repeated recipe assignment: {match[1]}")
            values[match[1]] = match[2]
    for name in ("PKG_NAME", "PKG_VERSION", "PKG_RELEASE", "PKG_SOURCE", "PKG_SOURCE_URL", "PKG_HASH"):
        require(name in values, f"Missing recipe field {name}")
    require(values["PKG_SOURCE_URL"] == "file://$(TOPDIR)/custom-distfiles", "Prepared recipes must use the local pinned source archive")
    require(HEX64.fullmatch(values["PKG_HASH"]), "PKG_HASH must be a full SHA-256")
    require(re.fullmatch(r"[1-9][0-9]*", values["PKG_RELEASE"]), "Invalid package revision")
    require(re.fullmatch(r"[a-z0-9][a-z0-9+-]*", values["PKG_NAME"]), "Invalid package name")
    require(re.fullmatch(r"[0-9][0-9a-z.~+-]*", values["PKG_VERSION"]), "Invalid package version")
    source = values["PKG_SOURCE"]
    for name in ("PKG_NAME", "PKG_VERSION", "USTEER_SOURCE_COMMIT"):
        if name in values:
            source = source.replace("$(" + name + ")", values[name])
    safe_relative(source)
    require("/" not in source and "$" not in source, "Unresolved or unsafe source archive name")
    packages = re.findall(r"^\$\(eval \$\(call BuildPackage,([a-z0-9+-]+)\)\)\s*$", text, re.M)
    require(len(packages) == 1, "Each prepared recipe must produce exactly one declared package")
    values.update(archive=source, package=packages[0], version=values["PKG_VERSION"] + "-r" + values["PKG_RELEASE"])
    return values


def validate_matrix(matrix, recipes):
    require(matrix.get("release") == RELEASE, "Wrong matrix release")
    groups = matrix.get("groups")
    require(isinstance(groups, list) and len(groups) == 3, "Expected three architecture groups")
    seen_arch, output_names = set(), set()
    for group in groups:
        arch = group.get("arch")
        require(arch in EXPECTED_GROUPS and arch not in seen_arch, "Unknown or duplicate architecture group")
        seen_arch.add(arch)
        apk_arch, target, mapping = EXPECTED_GROUPS[arch]
        require(group.get("apk_arch") == apk_arch and group.get("target") == target, "Target/APK architecture mismatch")
        require(group.get("recipes") == mapping, "Wrong recipe selection for target")
        sdk = re.escape("openwrt-sdk-" + RELEASE + "-" + target.replace("/", "-")) + r"_gcc-[0-9.]+_musl\.Linux-x86_64\.tar\.zst"
        require(isinstance(group.get("sdk_file"), str) and re.fullmatch(sdk, group["sdk_file"]), "Unexpected SDK filename")
        require(isinstance(group.get("sdk_sha256"), str) and HEX64.fullmatch(group["sdk_sha256"]), "SDK hash must be a full SHA-256")
        expected = {recipes[name]["package"]: recipes[name] for name in mapping.values()}
        require(len(expected) == len(mapping), "Two recipes produce the same package in one architecture")
        require(isinstance(group.get("packages"), list) and len(group["packages"]) == len(set(group["packages"])), "Duplicate package selection")
        require(set(group["packages"]) == set(expected), "Package selection differs from recipes")
        artifacts = group.get("artifacts")
        require(isinstance(artifacts, list) and len(artifacts) == len(expected), "Wrong artifact count")
        names = set()
        for artifact in artifacts:
            name = artifact.get("name")
            require(name in expected and name not in names, "Unknown or duplicate artifact name")
            names.add(name)
            require(artifact.get("version") == expected[name]["version"], "Artifact version differs from recipe")
            require(artifact.get("binary") == BINARIES[name], "Unexpected package binary path")
            key = (RELEASE, arch, name, artifact["version"])
            require(key not in output_names, "Duplicate output artifact identity")
            output_names.add(key)
    require(seen_arch == set(EXPECTED_GROUPS), "Missing architecture group")
    require(len(output_names) == 6, "Expected six architecture-specific APK artifacts")
    return groups


def validate_repo(root):
    root = root.resolve()
    pins = load_json(project_file(root, "sources/prepared-pins.json"))
    require(pins.get("schema") == 1 and pins.get("release") == RELEASE, "Wrong source manifest schema/release")
    entries = pins.get("recipes", {})
    require(set(entries) == set(EXPECTED_PINS), "Expected exactly four prepared source records")
    recipes, archives = {}, set()
    for name, expected in EXPECTED_PINS.items():
        entry = entries[name]
        require((entry.get("repository"), entry.get("commit")) == expected, f"Unreviewed or incomplete source pin: {name}")
        provenance_type = "archived_local" if name == "ustp-ap" else "public_commit"
        require(entry.get("provenance", {}).get("type") == provenance_type, f"Wrong source provenance classification: {name}")
        require(HEX40.fullmatch(entry.get("git_tree", "")), f"Missing full Git tree pin: {name}")
        require(HEX64.fullmatch(entry.get("sha256", "")), f"Missing archive SHA-256: {name}")
        values = recipe_values(project_file(root, f"packages/{name}/Makefile"))
        recipes[name] = values
        require(values["archive"] == entry.get("archive"), f"Recipe/source archive mismatch: {name}")
        require(entry["archive"] not in archives, "Source archive name reused by multiple recipes")
        archives.add(entry["archive"])
        require(values["PKG_HASH"] == entry["sha256"], f"Recipe/source hash mismatch: {name}")
        source_commit = values.get("PKG_SOURCE_VERSION", values.get("USTEER_SOURCE_COMMIT"))
        if name != "odhcpd-stable":
            require(source_commit == entry["commit"], f"Recipe commit differs from source manifest: {name}")
        if name != "usteer":
            require(values["PKG_VERSION"].endswith("~" + entry["commit"][:8]), f"Version does not identify selected source: {name}")
        archive = project_file(root, "sources/" + entry["archive"])
        require(archive.stat().st_size <= MAX_SOURCE, "Compressed source archive exceeds size limit")
        require(digest(archive.read_bytes()) == entry["sha256"], f"Source archive bytes differ from pin: {name}")
        require(source_tree(archive, entry.get("source_root", "")) == entry["git_tree"], f"Archive content differs from Git tree pin: {name}")
        patches = entry.get("patches")
        require(isinstance(patches, list), f"Missing patch manifest: {name}")
        declared = {}
        for patch in patches:
            relative = patch.get("path", "")
            path = project_file(root, relative)
            require(relative.startswith(f"packages/{name}/patches/") and path.suffix == ".patch", "Patch outside its recipe")
            require(path.name not in declared, "Duplicate patch name")
            require(HEX64.fullmatch(patch.get("sha256", "")), "Missing patch SHA-256")
            require(digest(path.read_bytes()) == patch["sha256"], f"Patch content differs from manifest: {relative}")
            declared[path.name] = patch["sha256"]
            if "source_commit" in patch or "source_repository" in patch:
                require(patch.get("source_repository") == "JxnLexn/openwrt-ustp" and patch.get("source_commit") == EXPECTED_PINS["ustp-ap"][1], "Unreviewed patch source pin")
                require(patch.get("source_provenance") == "archived_local" and patch.get("source_recipe") == "ustp-ap", "Macro backport must identify its local archived source")
            else:
                require(isinstance(patch.get("provenance"), str) and patch["provenance"].strip(), "Patch lacks provenance")
            check_patch_paths(path)
        require(declared == EXPECTED_PATCHES[name], f"Reviewed patch set missing or changed: {name}")
        actual = {p.name for p in (root / "packages" / name / "patches").glob("*.patch")}
        require(actual == set(declared), f"Unlisted patch in recipe: {name}")
    actual_archives = {p.name for p in (root / "sources").glob("*.tar.*")}
    require(actual_archives == archives, "Unlisted or missing source archive")
    verify_archived_local(root, entries)
    matrix = load_json(project_file(root, "build-matrix-25.12.6.json"))
    groups = validate_matrix(matrix, recipes)
    return {"release": RELEASE, "source_manifest": pins, "groups": groups, "recipes": recipes, "artifact_count": 6}


def self_test(root):
    """Negative cases model archive attacks and accidental artifact overwrites."""
    def make_tar(path, entries):
        with tarfile.open(path, "w:gz") as tf:
            for name, kind in entries:
                item = tarfile.TarInfo(name)
                item.mode = 0o644
                if kind == "symlink":
                    item.type, item.linkname = tarfile.SYMTYPE, "/etc/passwd"
                    tf.addfile(item)
                elif kind == "file":
                    item.size = 1
                    tf.addfile(item, io.BytesIO(b"x"))
                else:
                    item.type = tarfile.DIRTYPE
                    tf.addfile(item)

    cases = [
        [("src/../escape", "file")],
        [("/src/absolute", "file")],
        [("src/link", "symlink")],
        [("src/file", "file"), ("src/file", "file")],
        [("src/file", "file"), ("src/file/child", "file")],
        [("src/file/child", "file"), ("src/file", "file")],
        [("other/file", "file")],
    ]
    with tempfile.TemporaryDirectory(prefix="prepared-input-test-") as directory:
        path = Path(directory) / "source.tar.gz"
        make_tar(path, [("src/a", "file")])
        require(HEX40.fullmatch(source_tree(path, "src")), "Valid test archive rejected")
        for entries in cases:
            make_tar(path, entries)
            try:
                source_tree(path, "src")
            except ValidationError:
                pass
            else:
                raise ValidationError("Unsafe test archive was accepted")
    try:
        json.loads('{"a":1,"a":2}', object_pairs_hook=unique_json)
    except ValidationError:
        pass
    else:
        raise ValidationError("Duplicate JSON keys accepted")
    validated = validate_repo(root)

    def rejected(operation, label):
        try:
            operation()
        except ValidationError:
            return
        raise ValidationError("Negative test accepted: " + label)

    matrix = load_json(root / "build-matrix-25.12.6.json")
    bad = copy.deepcopy(matrix)
    bad["groups"][0]["artifacts"][1] = copy.deepcopy(bad["groups"][0]["artifacts"][0])
    rejected(lambda: validate_matrix(bad, validated["recipes"]), "two APKs with the same output identity")
    bad = copy.deepcopy(matrix)
    bad["groups"][1]["apk_arch"] = "aarch64"
    rejected(lambda: validate_matrix(bad, validated["recipes"]), "runtime architecture alias mistaken for APK metadata")
    with tempfile.TemporaryDirectory(prefix="prepared-manifest-test-") as directory:
        fixture = Path(directory)
        shutil.copy2(root / "build-matrix-25.12.6.json", fixture)
        shutil.copytree(root / "sources", fixture / "sources")
        for name in EXPECTED_PINS:
            shutil.copytree(root / "packages" / name, fixture / "packages" / name)
        pins_path = fixture / "sources/prepared-pins.json"
        original = load_json(pins_path)
        archive = fixture / "sources" / original["recipes"]["odhcpd-stable"]["archive"]
        saved_bytes = archive.read_bytes()
        archive.write_bytes(saved_bytes + b"changed after review")
        rejected(lambda: validate_repo(fixture), "changed archive under its original filename")
        archive.write_bytes(saved_bytes)
        for label, recipe, field, value in [
            ("missing required macro backport", "ustp-router", "patches", []),
            ("incorrect source tree attestation", "odhcpd-stable", "git_tree", "a" * 40),
            ("abbreviated source pin", "usteer", "commit", "94796972"),
        ]:
            changed = copy.deepcopy(original)
            changed["recipes"][recipe][field] = value
            pins_path.write_text(json.dumps(changed))
            rejected(lambda: validate_repo(fixture), label)
        pins_path.write_text(json.dumps(original))
        validate_repo(fixture)
    print("Self-test: 14 unsafe archives, ambiguous metadata and corrupted build-input cases rejected.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--self-test", action="store_true", help="Run negative cases before validating the repository")
    parser.add_argument("--matrix", action="store_true", help="Print only the validated GitHub Actions matrix")
    parser.add_argument("--json", action="store_true", help="Print the complete validation result")
    args = parser.parse_args()
    try:
        if args.self_test:
            require(not args.matrix and not args.json, "Self-test output cannot be combined with JSON output")
            self_test(args.root.resolve())
        result = validate_repo(args.root)
        if args.matrix:
            print(json.dumps({"include": result["groups"]}, separators=(",", ":")))
        elif args.json:
            print(json.dumps(result, indent=2))
        else:
            print("Validated 4 pinned source trees and patch sets, 3 SDK groups and 6 distinct APK artifacts.")
    except (ValidationError, OSError, json.JSONDecodeError, tarfile.TarError, KeyError, TypeError) as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
