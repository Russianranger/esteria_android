import hashlib
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


if __name__ == '__main__':
    unittest.main()
