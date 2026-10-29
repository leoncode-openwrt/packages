#!/usr/bin/env python3
"""Reconstruct pinned sources, verify organization trees and run Linux tests."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('validation', ROOT / 'scripts/validate-prepared.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

def run(*cmd, **kwargs):
    subprocess.run(cmd, check=True, **kwargs)

def main():
    checked = v.validate_repo(ROOT)
    organization = json.loads((ROOT / 'sources/organization-pins.json').read_text())
    with tempfile.TemporaryDirectory() as temporary:
        tmp = Path(temporary)
        sources = {}
        for recipe, entry in checked['source_manifest']['recipes'].items():
            target = tmp / recipe
            target.mkdir()
            with tarfile.open(ROOT / 'sources' / entry['archive']) as archive:
                archive.extractall(target, filter='data')
            source = target / entry['source_root']
            for patch in entry['patches']:
                run('git', 'apply', str(ROOT / patch['path']), cwd=source)
            run('git', 'init', '-q', cwd=source)
            run('git', 'add', '-A', cwd=source)
            tree = subprocess.check_output(['git', 'write-tree'], cwd=source, text=True).strip()
            pin = organization[recipe]
            assert tree == pin['tree'], f'{recipe}: patched source differs from organization commit'
            remote = json.loads(subprocess.check_output(['gh', 'api', f'repos/{pin["repository"]}/git/commits/{pin["commit"]}'], text=True))
            assert remote['tree']['sha'] == tree
            comparison = json.loads(subprocess.check_output([
                'gh', 'api', f'repos/{pin["repository"]}/compare/{pin["commit"]}...main'], text=True))
            assert comparison['status'] in ('ahead', 'identical'), f'{recipe}: source pin is not on main'
            sources[recipe] = source
        deps = ROOT / 'tests/dependencies'
        for dep in json.loads((deps / 'lock.json').read_text()):
            assert hashlib.sha256((deps / dep['archive']).read_bytes()).hexdigest() == dep['sha256']
            run('tar', '--zstd', '-xf', str(deps / dep['archive']), '-C', temporary)
        for mode in ('normal', 'sanitizer'):
            prefix = tmp / mode / 'prefix'
            flags = '-O1 -g -UNDEBUG'
            if mode == 'sanitizer':
                flags += ' -fsanitize=address,undefined -fno-omit-frame-pointer'
            # Build dependency libraries with the same sanitizer instrumentation.
            for name in ('libubox', 'ubus', 'libnl-tiny'):
                source = next(tmp.glob(name + '-*'))
                build = tmp / mode / ('dep-' + name)
                run('cmake', '-S', str(source), '-B', str(build), '-DBUILD_LUA=OFF', '-DBUILD_EXAMPLES=OFF',
                    '-DCMAKE_INSTALL_PREFIX=' + str(prefix), '-DCMAKE_PREFIX_PATH=' + str(prefix),
                    '-DCMAKE_C_FLAGS=' + flags + ' -I' + str(prefix / 'include'),
                    '-DCMAKE_SHARED_LINKER_FLAGS=' + flags + ' -L' + str(prefix / 'lib'),
                    '-DCMAKE_EXE_LINKER_FLAGS=' + flags + ' -L' + str(prefix / 'lib'))
                run('cmake', '--build', str(build), '--parallel', '2')
                run('cmake', '--install', str(build))
            env = os.environ.copy()
            env.update(ASAN_OPTIONS='detect_leaks=1:abort_on_error=1', UBSAN_OPTIONS='halt_on_error=1',
                       LD_LIBRARY_PATH=str(prefix / 'lib'), PKG_CONFIG_PATH=str(prefix / 'lib/pkgconfig'))
            for recipe, source in sources.items():
                build = tmp / mode / recipe
                if recipe == 'odhcpd-stable':
                    # This standalone parser test needs no daemon/UCI runtime.
                    build.mkdir()
                    binary = build / 'test_dns_rewrite'
                    run('cc', *flags.split(), '-D_GNU_SOURCE', '-std=gnu11',
                        '-Wall', '-Wextra', '-Werror', '-I' + str(source / 'src'),
                        str(source / 'src/dns_rewrite.c'),
                        str(source / 'tests/test_dns_rewrite.c'), '-o', str(binary))
                    run(str(binary), env=env)
                    continue
                run('cmake', '-S', str(source), '-B', str(build), '-DBUILD_TESTING=ON',
                    '-DUSTP_BUILD_DAEMON=OFF', '-DCMAKE_PREFIX_PATH=' + str(prefix),
                    '-DCMAKE_C_FLAGS=' + flags + ' -I' + str(prefix / 'include'),
                    '-DCMAKE_EXE_LINKER_FLAGS=' + flags + ' -L' + str(prefix / 'lib'), env=env)
                targets = ['test_dns_rewrite'] if recipe == 'odhcpd-stable' else (
                    ['test-remote-message', 'test-remote-socket'] if recipe == 'usteer' else [])
                args = ['cmake', '--build', str(build), '--parallel', '2']
                if targets:
                    args += ['--target'] + targets
                run(*args, env=env)
                run('ctest', '--test-dir', str(build), '--output-on-failure', env=env)

if __name__ == '__main__':
    main()
