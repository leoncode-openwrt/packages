#!/usr/bin/env python3
"""Publish verified release assets as a versioned, signed APK repository."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = 'leoncode-openwrt/packages'
BASE = 'https://leoncode-openwrt.github.io/packages/'
ARCHES = ('x86_64', 'aarch64_cortex-a53', 'mipsel_24kc')

def run(*args):
    return subprocess.check_output(list(map(str, args)), text=True)

def inventory(releases):
    result = []
    for release in releases:
        match = re.fullmatch(r'openwrt-(\d{2}\.\d{2}\.\d+)-r([1-9]\d*)', release['tag_name'])
        if match and not release['draft'] and not release['prerelease']:
            result.append((match[1], int(match[2]), release['tag_name']))
    return sorted(result, key=lambda item: (tuple(map(int, item[0].split('.'))), item[1]))

def checksums(data):
    result = {}
    for line in data.decode().splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.removeprefix('*').removeprefix('./')
        if not re.fullmatch(r'[0-9a-f]{64}', digest) or '/' in name or name in result:
            raise ValueError('Invalid checksum manifest')
        result[name] = digest
    return result

def checked(data, digest):
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('Checksum mismatch')
    return data

def unpack(archive, arch, target):
    """Read only regular immediate children; never extract archive paths."""
    with tarfile.open(archive) as tar:
        files = {}
        for member in tar.getmembers():
            if member.isdir():
                continue
            if member.name.startswith(arch + '/') and member.name.count('/') == 1 and member.name != arch + '/':
                if not member.isfile() or member.size > 32 * 1024 * 1024:
                    raise ValueError('Unexpected archive member')
                name = member.name.split('/')[1]
                if name in files or name in ('.', '..'):
                    raise ValueError('Duplicate or invalid archive member')
                files[name] = tar.extractfile(member).read()
        sums = checksums(files['SHA256SUMS'])
        packages = sorted(name for name in files if name.endswith('.apk'))
        if len(packages) != 2:
            raise ValueError('Incomplete architecture release')
        target.mkdir(parents=True)
        for name in packages + ['packages.adb', 'leoncode-packages.pem']:
            (target / name).write_bytes(checked(files[name], sums[name]))
        if files['leoncode-packages.pem'] != (ROOT / 'keys/leoncode-packages.pem').read_bytes():
            raise ValueError('Unexpected release signing key')
    return packages

def prepare(output, apk, key):
    if output.exists():
        raise ValueError('Output must be a fresh directory')
    output.mkdir(parents=True)
    pages = json.loads(run('gh', 'api', '--paginate', '--slurp', f'repos/{REPO}/releases?per_page=100'))
    releases = inventory([r for page in pages for r in page])
    if not releases:
        raise ValueError('No published releases')
    latest = {}
    with tempfile.TemporaryDirectory() as tmp:
        for version, revision, tag in releases:
            download = Path(tmp) / tag
            download.mkdir()
            run('gh', 'release', 'download', tag, '--repo', REPO, '--dir', download,
                '--pattern', 'SHA256SUMS', '--pattern', f'LeonCode-openwrt-{version}-*.tar.gz')
            sums = checksums((download / 'SHA256SUMS').read_bytes())
            for arch in ARCHES:
                archive = download / f'LeonCode-openwrt-{version}-{arch}.tar.gz'
                checked(archive.read_bytes(), sums[archive.name])
                directory = output / version / arch / f'r{revision}'
                packages = unpack(archive, arch, directory)
                for name in packages + ['packages.adb']:
                    run(apk, 'verify', '--keys-dir', ROOT / 'keys', directory / name)
                for name in packages:
                    metadata = json.loads(run(apk, 'adbdump', '--format', 'json', directory / name))
                    if metadata['info']['arch'] != arch:
                        raise ValueError('Package architecture mismatch')
                latest[version, arch] = (revision, packages)
    links = []
    for (version, arch), (revision, packages) in latest.items():
        directory = output / version / arch
        # Revision-qualified package URLs remain valid for cached older indices.
        run(apk, 'mkndx', '--keys-dir', ROOT / 'keys', '--sign-key', key,
            '--pkgname-spec', f'r{revision}/${{name}}-${{version}}.apk',
            '--output', directory / 'packages.adb',
            *(directory / f'r{revision}' / name for name in packages))
        run(apk, 'verify', '--keys-dir', ROOT / 'keys', directory / 'packages.adb')
        links.append(f'<li><a href="{version}/{arch}/packages.adb">{version} / {arch}</a> (r{revision})</li>')
    for name in ('leoncode-packages.pem', 'LEONCODE_KEY_SHA256'):
        shutil.copyfile(ROOT / 'keys' / name, output / name)
    (output / '.nojekyll').touch()
    (output / 'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8">'
        '<title>LeonCode OpenWrt APK feed</title><h1>LeonCode OpenWrt APK feed</h1>'
        '<p>Use the feed matching your exact OpenWrt release and APK architecture.</p>'
        '<p><a href="leoncode-packages.pem">Public signing key</a> · '
        '<a href="LEONCODE_KEY_SHA256">Public key DER SHA-256</a> · '
        '<a href="https://github.com/leoncode-openwrt/packages#using-the-apk-feed">Instructions</a></p>'
        '<ul>' + ''.join(links) + '</ul></html>')
    manifest = {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(output.rglob('*')) if p.is_file()}
    try:
        with urllib.request.urlopen(BASE + 'feed-manifest.json', timeout=30) as response:
            previous = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        previous = {}  # First deployment only.
    for name, digest in previous.items():
        if name not in manifest:
            raise ValueError(f'Refusing to remove a published path: {name}')
        if name.endswith('.apk') and manifest[name] != digest:
            raise ValueError(f'Refusing to replace published package bytes: {name}')
    (output / 'feed-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Prepared {len(releases)} releases, {len(latest)} active feeds')

def verify_live(output, apk):
    manifest = json.loads((output / 'feed-manifest.json').read_text())
    with tempfile.TemporaryDirectory() as tmp:
        for name, digest in manifest.items():
            for attempt in range(6):
                try:
                    with urllib.request.urlopen(BASE + name, timeout=30) as response:
                        data = checked(response.read(), digest)
                    break
                except Exception:
                    if attempt == 5:
                        raise
                    time.sleep(10)
            if name.endswith(('.adb', '.apk')):
                path = Path(tmp) / Path(name).name
                path.write_bytes(data)
                run(apk, 'verify', '--keys-dir', ROOT / 'keys', path)
        # Exercise the real repository parser, relative package URLs and signatures.
        for index in sorted(output.glob('*/*/packages.adb')):
            relative = index.relative_to(output)
            arch = relative.parts[1]
            root = Path(tmp) / relative.parts[0] / arch
            root.mkdir(parents=True)
            run(apk, '--root', root, '--arch', arch, '--initdb', '--keys-dir', ROOT / 'keys',
                '--repositories-file', '/dev/null', '--repository', BASE + str(relative), 'update')
            metadata = json.loads(run(apk, 'adbdump', '--format', 'json', index))
            dest = root / 'downloads'
            dest.mkdir()
            run(apk, '--root', root, '--arch', arch, '--keys-dir', ROOT / 'keys',
                '--repositories-file', '/dev/null', '--repository', BASE + str(relative),
                'fetch', '--output', dest, *(p['name'] for p in metadata['packages']))
    print(f'HTTPS hashes and APK signatures verified for {len(manifest)} published files')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'verify-live'])
    parser.add_argument('--output', type=Path, default=Path('_site'))
    parser.add_argument('--apk', required=True)
    parser.add_argument('--key')
    args = parser.parse_args()
    if args.command == 'prepare':
        if not args.key:
            parser.error('--key is required for prepare')
        prepare(args.output.resolve(), args.apk, args.key)
    else:
        verify_live(args.output.resolve(), args.apk)
