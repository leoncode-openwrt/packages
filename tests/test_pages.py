import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('pages', Path(__file__).resolve().parents[1] / 'scripts/pages.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class Pages(unittest.TestCase):
    def test_all_versions_retained_and_revisions_sorted_numerically(self):
        releases = [dict(tag_name=tag, draft=False, prerelease=False) for tag in
                    ['openwrt-25.12.7-r1', 'openwrt-25.12.6-r10', 'openwrt-25.12.6-r2', 'unrelated']]
        releases += [dict(tag_name='openwrt-25.12.8-r1', draft=True, prerelease=False),
                     dict(tag_name='openwrt-25.12.9-r1', draft=False, prerelease=True)]
        self.assertEqual([(v, r) for v, r, _ in p.inventory(releases)],
                         [('25.12.6', 2), ('25.12.6', 10), ('25.12.7', 1)])

    def test_rejects_tampered_bytes(self):
        with self.assertRaises(ValueError):
            p.checked(b'tampered', '0' * 64)

    def test_rejects_ambiguous_or_unsafe_checksums(self):
        for names in [('one', 'one'), ('../outside',), ('dir/file',)]:
            data = ''.join('0' * 64 + '  ' + name + '\n' for name in names).encode()
            with self.assertRaises(ValueError):
                p.checksums(data)

    def test_rejects_archive_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'unsafe.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                entry = tarfile.TarInfo('x86_64/packages.adb')
                entry.type = tarfile.SYMTYPE
                entry.linkname = '/etc/passwd'
                tar.addfile(entry)
            with self.assertRaises(ValueError):
                p.unpack(archive, 'x86_64', Path(tmp) / 'output')

    def test_real_release_archives_preserve_integrity(self):
        # Optional local fixture; CI independently verifies downloaded release assets.
        fixture = p.ROOT.parents[1] / 'work/leoncode-packages-20261029/release-r2'
        if not fixture.exists():
            self.skipTest('Local release fixture is unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            for arch in p.ARCHES:
                packages = p.unpack(fixture / f'LeonCode-openwrt-25.12.6-{arch}.tar.gz',
                                    arch, Path(tmp) / arch)
                self.assertEqual(len(packages), 2)


if __name__ == '__main__':
    unittest.main()
