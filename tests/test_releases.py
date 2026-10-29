import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch
import json

spec = importlib.util.spec_from_file_location('releases', Path(__file__).resolve().parents[1] / 'scripts/releases.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

class Releases(unittest.TestCase):
    def test_rejects_non_release_and_old_package_formats(self):
        for value in ['SNAPSHOT', '25.12.7-rc1', '../25.12.6', '25.12.6; id', '24.10.8', '25.12.5', '']:
            with self.assertRaises(ValueError):
                r.version(value)

    def test_discovers_missing_release_numerically(self):
        inventory = {'versions_list': ['25.12.10', '25.12.7-rc1', '25.12.6', '25.12.9', 'SNAPSHOT']}
        existing = [[{'tag_name': r.tag('25.12.6'), 'draft': False}]]
        with patch.object(r, 'fetch', return_value=json.dumps(inventory).encode()), patch.object(r.subprocess, 'check_output', return_value=json.dumps(existing)):
            self.assertEqual(r.choose(''), '25.12.9')

    def test_draft_is_retried(self):
        with patch.object(r, 'fetch', return_value=b'{"versions_list":["25.12.6"]}'), patch.object(r.subprocess, 'check_output', return_value=json.dumps([[{'tag_name': r.tag('25.12.6'), 'draft': True}]])):
            self.assertEqual(r.choose(''), '25.12.6')

    def test_complete_release_is_skipped(self):
        with patch.object(r, 'fetch', return_value=b'{"versions_list":["25.12.6"]}'), patch.object(r.subprocess, 'check_output', return_value=json.dumps([[{'tag_name': r.tag('25.12.6'), 'draft': False}]])):
            self.assertEqual(r.choose(''), '')

if __name__ == '__main__':
    unittest.main()
