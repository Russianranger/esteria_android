import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import qualify_appearance_schema as qualify


def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class AppearanceStorageGuards(unittest.TestCase):
    def test_existing_fixture_is_preserved_before_content_or_engine_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); saved = root / 'character'; saved.write_bytes(b'keep')
            with patch.object(qualify.platform, 'machine', return_value='aarch64'), \
                    patch.object(qualify, 'selected_manifest') as source, \
                    patch.object(qualify.db, 'initialize') as initialize, \
                    self.assertRaisesRegex(ValueError, 'existing appearance qualification preserved'):
                qualify.qualify(root, 'a' * 64, root, Path('/mysql'), Path('/mysqld'), '8.0.46', root)
            source.assert_not_called(); initialize.assert_not_called()
            self.assertEqual(saved.read_bytes(), b'keep')

    def test_non_native_host_cannot_create_state_or_select_sql(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'state'
            with patch.object(qualify.platform, 'machine', return_value='x86_64'), \
                    patch.object(qualify.adaptation, 'prepare') as prepare, self.assertRaisesRegex(ValueError, 'native Linux ARM64'):
                qualify.qualify(root, 'a' * 64, root, Path('/mysql'), Path('/mysqld'), '8.0.46', root)
            prepare.assert_not_called(); self.assertFalse(root.exists())

    def test_fixture_values_exercise_exact_lengths_nul_high_bytes_and_replace_change(self):
        for length in (49, 132):
            a, b = qualify.payload(length), qualify.payload(length, True)
            self.assertEqual(len(a), length); self.assertEqual(len(b), length)
            self.assertNotEqual(a, b)
            for value in (a, b):
                self.assertIn(0, value); self.assertIn(255, value); self.assertIn(128, value)

    def test_binary_transport_never_accepts_truncation_padding_or_missing_row(self):
        value = qualify.payload(49); connection = Mock()
        good = str(qualify.GUID) + '\t49\t' + value.hex().upper()
        connection.query.return_value = [good]
        qualify.rows(connection, 'character_body_shape', {qualify.GUID: value})
        for wrong in ([], [good.replace('\t49\t', '\t48\t')], [good + '00']):
            connection.query.return_value = wrong
            with self.subTest(rows=wrong), self.assertRaisesRegex(ValueError, 'binary rows differ'):
                qualify.rows(connection, 'character_body_shape', {qualify.GUID: value})

    def test_manifest_comes_from_pinned_complete_archive_and_source_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); pin = dict(commit='f' * 40)
            document = dict(source=pin, sourceLockSha256='b' * 64, contentSha256Complete=True)
            raw = json.dumps(document).encode(); name = 'metadata/content-manifest.json'
            archive = root / 'server-content.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                member = tarfile.TarInfo(name); member.size = len(raw); tar.addfile(member, io.BytesIO(raw))
            receipt = dict(formatVersion=1, scope='immutable-server-source-content-package', source=pin,
                sourceLockSha256='b' * 64, moduleSelectionVerified=True, archiveReadBackVerified=True,
                archive=identity(archive.read_bytes()), archiveFiles={name: identity(raw)})
            path = root / 'package-receipt.json'; path.write_text(json.dumps(receipt))
            digest = identity(path.read_bytes())['sha256']
            with patch.object(qualify.base, 'locked_source', return_value=(pin, 'b' * 64)):
                observed, _ = qualify.selected_manifest(root, digest, root / 'lock')
                self.assertEqual(observed, document)
                with self.assertRaisesRegex(ValueError, 'verified content receipt'):
                    qualify.selected_manifest(root, '0' * 64, root / 'lock')
                archive.write_bytes(archive.read_bytes() + b'changed')
                with self.assertRaisesRegex(ValueError, 'source-content archive changed'):
                    qualify.selected_manifest(root, digest, root / 'lock')


if __name__ == '__main__': unittest.main()
