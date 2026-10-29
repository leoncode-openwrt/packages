#!/usr/bin/env python3
"""Discover final OpenWrt releases and lock authenticated SDK inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://downloads.openwrt.org'
RECIPE_REVISION = 1

def fetch(url):
    assert url.startswith(BASE + '/')
    with urllib.request.urlopen(url, timeout=60) as response:
        assert response.url.startswith(BASE + '/')
        return response.read()

def version(value):
    if not re.fullmatch(r'[0-9]{2}\.[0-9]{2}\.[0-9]+', value):
        raise ValueError('Only final OpenWrt releases are supported')
    parts = tuple(map(int, value.split('.')))
    if parts < (25, 12, 6):
        raise ValueError('The initial support boundary is OpenWrt 25.12.6')
    return parts

def tag(release):
    version(release)
    return f'openwrt-{release}-r{RECIPE_REVISION}'

def choose(requested):
    if requested:
        version(requested)
        return requested
    inventory = json.loads(fetch(BASE + '/.versions.json'))
    eligible = []
    for item in inventory['versions_list']:
        try:
            version(item)
            eligible.append(item)
        except ValueError:
            pass
    published = json.loads(subprocess.check_output([
        'gh', 'api', '--paginate', '--slurp',
        'repos/leoncode-openwrt/packages/releases?per_page=100'], text=True))
    existing = {r['tag_name'] for page in published for r in page if not r['draft']}
    return next((r for r in sorted(eligible, key=version) if tag(r) not in existing), '')

def verify_signature(checksums, signature):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / 'sha256sums').write_bytes(checksums)
        (home / 'sha256sums.asc').write_bytes(signature)
        subprocess.run(['gpg', '--batch', '--homedir', tmp, '--import',
                        str(ROOT / 'keys/openwrt-build-system.asc')], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        subprocess.run(['gpg', '--batch', '--homedir', tmp, '--verify',
                        str(home / 'sha256sums.asc'), str(home / 'sha256sums')],
                       check=True, stdout=subprocess.DEVNULL)

def resolve(release):
    version(release)
    matrix = json.loads((ROOT / 'build-matrix-25.12.6.json').read_text())
    matrix['release'] = release
    for group in matrix['groups']:
        base = f'{BASE}/releases/{release}/targets/{group["target"]}/'
        sums, sig = fetch(base + 'sha256sums'), fetch(base + 'sha256sums.asc')
        verify_signature(sums, sig)
        prefix = f'openwrt-sdk-{release}-{group["target"].replace("/", "-")}_'
        matches = []
        for line in sums.decode().splitlines():
            fields = line.split()
            if len(fields) != 2:
                continue
            digest, name = fields[0], fields[1].lstrip('*')
            if name.startswith(prefix) and name.endswith('_musl.Linux-x86_64.tar.zst'):
                if re.fullmatch(r'[a-zA-Z0-9_.~+-]+', name) and re.fullmatch(r'[0-9a-f]{64}', digest):
                    matches.append((name, digest))
        if len(matches) != 1:
            raise ValueError(f'Expected exactly one SDK for {group["target"]}')
        group['sdk_file'], group['sdk_sha256'] = matches[0]
        group['checksums'] = sums.decode()
        group['checksums_signature'] = sig.decode()
    matrix['recipe_revision'] = RECIPE_REVISION
    matrix['source_revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    return matrix

def materialize(lock):
    release = lock['release']
    version(release)
    expected = json.loads((ROOT / 'build-matrix-25.12.6.json').read_text())
    if len(lock['groups']) != len(expected['groups']):
        raise ValueError('Incomplete SDK matrix')
    for group, original in zip(lock['groups'], expected['groups']):
        for field in ('arch', 'apk_arch', 'target', 'recipes', 'packages', 'artifacts'):
            if group[field] != original[field]:
                raise ValueError(f'Unexpected matrix field: {field}')
        verify_signature(group['checksums'].encode(), group['checksums_signature'].encode())
        entries = {parts[1].lstrip('*'): parts[0] for line in group['checksums'].splitlines()
                   if len(parts := line.split()) == 2}
        if entries.get(group['sdk_file']) != group['sdk_sha256']:
            raise ValueError('SDK hash is not in the authenticated checksum list')
    # Preserve the archived 25.12.6 input bundle; modify only the disposable CI checkout.
    for name in ('validate-prepared.py', 'sdk-provenance.py', 'build-prepared.sh', 'collect-prepared.sh'):
        path = ROOT / 'scripts' / name
        path.write_text(path.read_text().replace('25.12.6', release))
    pins = ROOT / 'sources/prepared-pins.json'
    data = json.loads(pins.read_text())
    data['release'] = release
    pins.write_text(json.dumps(data, indent=2) + '\n')
    (ROOT / f'build-matrix-{release}.json').write_text(json.dumps(lock, indent=2) + '\n')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'materialize'])
    parser.add_argument('--release', default='')
    parser.add_argument('--lock', default='release-lock.json')
    args = parser.parse_args()
    if args.command == 'materialize':
        materialize(json.loads(Path(args.lock).read_text()))
        return
    release = choose(args.release)
    outputs = {'release': release, 'tag': tag(release) if release else '', 'build': str(bool(release)).lower()}
    if release:
        lock = resolve(release)
        Path(args.lock).write_text(json.dumps(lock, indent=2) + '\n')
        outputs['matrix'] = json.dumps({'include': [{k: g[k] for k in ('arch', 'target', 'sdk_file', 'sdk_sha256')} for g in lock['groups']]}, separators=(',', ':'))
    else:
        outputs['matrix'] = '{"include":[]}'
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            for key, value in outputs.items():
                stream.write(f'{key}={value}\n')
    print(json.dumps(outputs))

if __name__ == '__main__':
    main()
