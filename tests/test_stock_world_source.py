import hashlib
import json
import os
from types import SimpleNamespace
import zipfile
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_stock_world as world


class StockWorldSource(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.spool = Path(self.temp.name)
        self.zip = self.spool / 'client-texture-input.zip'
        self.zip.write_bytes(b'ABCDEFG')
        self.piece = 4
        self.hashes = hashlib.sha1(b'ABCD').digest() + hashlib.sha1(b'EFG').digest()
        (self.spool / 'official.torrent').write_bytes(b'test metadata')
        self.journal = self.spool / 'verified-pieces'
        self.events = []

    def test_next_stock_release_selects_the_ledger_apk_before_acquisition(self):
        root = self.spool
        (root / 'app').mkdir()
        (root / 'runtime/evidence').mkdir(parents=True)
        ledger = {'lastPublished': {'versionCode': 21, 'apkSha256': 'a' * 64}, 'certificateSha256': 'c' * 64}
        (root / 'app/stock-signing.lock.json').write_text(json.dumps(ledger))
        path = root / 'runtime/evidence/non-custom-v21-public-apk-readback.json'
        proof = {'assets': [{'name': 'stock.apk', 'sha256': 'a' * 64, 'completeAnonymousReadback': True}],
                 'persistentCertificateSha256': 'c' * 64, 'sdkV2AndV3SignatureVerified': True}
        path.write_text(json.dumps(proof))
        self.assertEqual(world.last_published_readback(root), path)
        proof['assets'][0]['sha256'] = 'b' * 64
        path.write_text(json.dumps(proof))
        with self.assertRaisesRegex(ValueError, 'differs from signing ledger'):
            world.last_published_readback(root)

    def progress(self, phase, **details):
        self.events.append((phase, details))

    def collect(self):
        with patch.object(world.corpus, 'checked_torrent_pieces', return_value=self.hashes):
            return world.collector_archive(self.spool, self.progress)

    def test_pending_collector_never_initializes_import_or_fetches(self):
        self.journal.write_bytes(b'1\n')
        work = self.spool / 'work'
        with patch.object(world.corpus, 'checked_torrent_pieces', return_value=self.hashes), \
                patch.object(world, 'download', side_effect=AssertionError), \
                self.assertRaisesRegex(world.corpus.Invalid, 'incomplete stock ZIP'):
            world.import_source(work, None, self.progress, spool=self.spool)
        self.assertFalse(work.exists())
        self.assertEqual(self.events, [('verified-collector-pending', dict(verifiedPieces=1, requiredPieces=2))])

    def test_journal_must_contain_complete_unique_indices_and_pinned_metadata(self):
        for journal in (b'1\n1\n', b'2\n', b'00\n', b'0\n1', b'-1\n'):
            self.journal.write_bytes(journal)
            with self.subTest(journal=journal), self.assertRaises(world.corpus.Invalid):
                self.collect()
        self.journal.write_bytes(b'1\n0\n')
        with self.assertRaisesRegex(world.corpus.Invalid, 'torrent digest'):
            world.collector_archive(self.spool, self.progress)
        self.assertEqual(self.collect(), (self.zip, self.hashes))

    def test_complete_journal_cannot_bless_changed_truncated_or_indirect_source(self):
        self.assertEqual(world.verify_archive(self.zip, self.hashes, 7, self.piece), world.archive_identity(self.zip))
        self.zip.write_bytes(b'ABCDEF?')
        with self.assertRaisesRegex(world.corpus.Invalid, 'hash mismatch'):
            world.verify_archive(self.zip, self.hashes, 7, self.piece)
        self.zip.write_bytes(b'ABCD')
        with self.assertRaisesRegex(world.corpus.Invalid, 'incomplete official ZIP'):
            world.verify_archive(self.zip, self.hashes, 7, self.piece)
        self.zip.rename(self.spool / 'other')
        self.zip.symlink_to(self.spool / 'other')
        with self.assertRaisesRegex(world.corpus.Invalid, 'regular file'):
            world.verify_archive(self.zip, self.hashes, 7, self.piece)

    def test_private_import_checks_allocated_space_before_writing_and_reuses_the_same_store(self):
        with zipfile.ZipFile(self.zip, 'w') as src:
            src.writestr('Data/a.MPQ', b'A' * 4097)
            src.writestr('Data/b.MPQ', b'B')
            src.writestr('Data/enUS/', b'')
        work = self.spool / 'fixture'
        unit = os.statvfs(work.parent).f_frsize
        required = ((4097 + unit - 1) // unit + 1) * unit + (64 << 20)
        with patch.object(world.shutil, 'disk_usage', return_value=SimpleNamespace(free=required - 1)), \
                self.assertRaisesRegex(world.corpus.Invalid, 'insufficient private disk'):
            world.private_import(work, self.zip, self.progress)
        self.assertFalse(work.exists())
        self.assertEqual(self.events[-1][1]['requiredBytes'], required)
        with patch.object(world.shutil, 'disk_usage', return_value=SimpleNamespace(free=required)):
            world.private_import(work, self.zip, self.progress)
        saved = work / 'game/retained'
        saved.write_bytes(b'retained')
        with patch.object(world.shutil, 'disk_usage', side_effect=AssertionError('warm import needs its actual remaining quota')):
            world.private_import(work, self.zip, self.progress)
        self.assertEqual(saved.read_bytes(), b'retained')
        self.assertEqual(self.events[-1][0], 'resume-source-bound-java-import')
        os.utime(self.zip, ns=(self.zip.stat().st_atime_ns, self.zip.stat().st_mtime_ns + 1_000_000))
        with self.assertRaisesRegex(world.corpus.Invalid, 'different or unknown source'):
            world.private_import(work, self.zip, self.progress)
        self.assertEqual(saved.read_bytes(), b'retained')

    def test_reject_unknown_store_or_link_before_modification(self):
        unrelated = self.spool / 'unrelated'
        unrelated.mkdir(mode=0o700)
        (unrelated / 'save').write_bytes(b'keep')
        with self.assertRaisesRegex(world.corpus.Invalid, 'unknown source'):
            world.private_import(unrelated, self.zip, self.progress)
        link = self.spool / 'link'
        link.symlink_to(unrelated, target_is_directory=True)
        with self.assertRaisesRegex(world.corpus.Invalid, 'private owned directory'):
            world.private_import(link, self.zip, self.progress)
        self.assertEqual((unrelated / 'save').read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
