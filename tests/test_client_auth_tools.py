import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare_client_auth_tools as prepare
from tools import verify_client_auth_tools as verify


class AuthToolTests(unittest.TestCase):
    def row(self, content=b'exact package'):
        return dict(filename='pool/main/p/package/package_1_arm64.deb', bytes=len(content),
                    sha256=hashlib.sha256(content).hexdigest())

    def test_reviewed_signed_selection_has_complete_sources_and_exact_base(self):
        lock = prepare.load_lock()
        self.assertEqual(len(lock['packages']), 32)
        self.assertEqual(sum(r['bytes'] for r in lock['packages']), 21178262)
        self.assertEqual(sum(len(r['files']) for r in lock['sources']), 64)
        self.assertEqual(lock['solver']['logSha256'],
                         '44cdd4317e1f80246d024d6bc7641943fa6240e4b01d463f11535df815602554')
        self.assertEqual(lock['base']['dpkgStatus']['sha256'],
                         '1f26d7efff59a8d6ac8b399ca9ab49ce560959bf79401656a8a8afb98fb195c7')
        recipe = prepare.recipe()
        self.assertNotIn(b'apt-get', recipe)
        self.assertIn(b'RUN --network=none', recipe)

    def test_pool_paths_cannot_escape_or_select_other_origin(self):
        for value in ('../package.deb', '/pool/main/p/p.deb', 'pool/main/../p.deb',
                      'https://example.com/a.deb', 'pool/main/p/%2e%2e.deb'):
            row = self.row(); row['filename'] = value
            with self.assertRaises(ValueError): prepare.file_record(row)

    def test_corrupt_or_linked_cache_is_rejected_without_replacing_it(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Path(root); row = self.row()
            target = cache / (row['sha256'] + '-' + Path(row['filename']).name)
            target.write_bytes(b'preserve this')
            with self.assertRaises(ValueError): prepare.fetch(row, cache, True)
            self.assertEqual(target.read_bytes(), b'preserve this')
            target.unlink(); other = cache / 'other'; other.write_bytes(b'exact package'); target.symlink_to(other)
            with self.assertRaises(ValueError): prepare.fetch(row, cache, False)
            self.assertEqual(other.read_bytes(), b'exact package')

    def test_download_is_bounded_and_wrong_bytes_are_not_published(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Path(root); row = self.row()
            with patch.object(prepare.urllib.request, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(b'x' * 1000)):
                with self.assertRaisesRegex(ValueError, 'exact-tool-input-unavailable'):
                    prepare.fetch(row, cache, True)
            self.assertEqual(list(cache.iterdir()), [])
            with patch.object(prepare.urllib.request, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(b'exact package')):
                target = prepare.fetch(row, cache, True)
            self.assertEqual(target.read_bytes(), b'exact package')
            self.assertEqual(prepare.fetch(row, cache, False), target)

    def test_transition_rejects_base_updates_unexpected_packages_and_missing_dependencies(self):
        before = {'base': dict(version='1', architecture='arm64')}
        lock = {'packages': [dict(name='tool', version='2', architecture='arm64')]}
        after = {**before, 'tool': dict(version='2', architecture='arm64')}
        verify.verify_transition(before, after, lock)
        for mutation in ({'base': dict(version='3', architecture='arm64'), 'tool': after['tool']},
                         {**after, 'surprise': after['tool']}, before,
                         {**before, 'tool': dict(version='wrong', architecture='arm64')}):
            with self.assertRaises(ValueError): verify.verify_transition(before, mutation, lock)
        with self.assertRaises(ValueError): verify.verify_transition(after, after, lock)

    def test_failed_staging_preserves_existing_output_and_no_partial_promotion(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); cache = root / 'cache'; cache.mkdir()
            existing = root / 'existing'; existing.mkdir(); marker = existing / 'saved'; marker.write_text('retain')
            with self.assertRaises(ValueError): prepare.prepare(cache, existing)
            self.assertEqual(marker.read_text(), 'retain')
            with self.assertRaisesRegex(ValueError, 'missing-tool-input'):
                prepare.prepare(cache, root / 'new')
            self.assertFalse((root / 'new').exists())
            self.assertFalse(any(p.name.startswith('.new-') for p in root.iterdir()))


if __name__ == '__main__':
    unittest.main()
