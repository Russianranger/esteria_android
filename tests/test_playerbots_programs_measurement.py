"""Archive construction/refusal fixtures; no provider or executable admission."""
import copy
import gzip
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import measure_playerbots_programs as measure


class ProgramsMeasurement(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='optional-helper-measure-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)
        self.original = self.root / 'original'; self.original.mkdir()
        for name, raw in {'bin/authserver': b'FIXTURE_ONLY_ORIGINAL_BYTES',
                          'etc/authserver.conf.dist': b'exact original template\n',
                          'provenance/original.json': b'{}\n'}.items():
            path = self.original / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        self.archive = self.root / 'original.tar.gz'
        self.rows = measure.engine.write_archive(self.original, self.archive)
        self.extra_file = self.root / 'helper-fixture'; self.extra_file.write_bytes(b'FIXTURE_ONLY_NEVER_EXECUTED')
        self.extra = {'helpers/playerbots-schema': (self.extra_file, dict(measure.files.identity(self.extra_file), mode=0o555))}

    def test_normalized_candidate_keeps_every_original_byte_and_the_closed_delta(self):
        before = measure.files.identity(self.archive)
        first, second = self.root / 'first.tar.gz', self.root / 'second.tar.gz'
        rows = measure.assemble_runtime(self.archive, self.rows, self.extra, first)
        measure.assemble_runtime(self.archive, self.rows, self.extra, second)
        self.assertEqual(measure.files.identity(first), measure.files.identity(second))
        self.assertEqual(measure.files.identity(self.archive), before)
        self.assertEqual(set(rows), set(self.rows) | set(self.extra))
        for name, row in self.rows.items(): self.assertEqual(rows[name], row)
        self.assertEqual(rows['helpers/playerbots-schema']['mode'], 0o555)
        measure.engine.verify_archive(first, rows)

    def test_existing_output_collision_changed_helper_and_unrecorded_original_refuse(self):
        output = self.root / 'existing'; output.write_bytes(b'retain')
        with self.assertRaisesRegex(ValueError, 'existing-output-or-member-collision'):
            measure.assemble_runtime(self.archive, self.rows, self.extra, output)
        self.assertEqual(output.read_bytes(), b'retain')
        collision = {'bin/authserver': next(iter(self.extra.values()))}
        with self.assertRaisesRegex(ValueError, 'member-collision'):
            measure.assemble_runtime(self.archive, self.rows, collision, self.root / 'collision.tar.gz')
        self.extra_file.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'addition-bytes-or-mode'):
            measure.assemble_runtime(self.archive, self.rows, self.extra, self.root / 'changed.tar.gz')
        reduced = copy.deepcopy(self.rows); reduced.pop('etc/authserver.conf.dist')
        with self.assertRaisesRegex(ValueError, 'original-runtime-member-set'):
            measure.assemble_runtime(self.archive, reduced, {}, self.root / 'unrecorded.tar.gz')

    def test_original_changed_member_digest_or_header_metadata_refuse(self):
        wrong = copy.deepcopy(self.rows); wrong['bin/authserver']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'SHA|hash'):
            measure.assemble_runtime(self.archive, wrong, {}, self.root / 'wrong-digest.tar.gz')
        bad = self.root / 'bad.tar.gz'
        with gzip.open(bad, 'wb') as compressed, tarfile.open(fileobj=compressed, mode='w|') as out:
            for name, row in self.rows.items():
                info = tarfile.TarInfo(name); info.size = row['bytes']; info.mode = row['mode']; info.uid = 42
                with (self.original / name).open('rb') as body: out.addfile(info, body)
        with self.assertRaisesRegex(ValueError, 'original-runtime-member-metadata'):
            measure.assemble_runtime(bad, self.rows, {}, self.root / 'bad-header.tar.gz')

    def test_full_expansion_limit_remains_the_existing_stock_96_mib_policy(self):
        wrong = copy.deepcopy(self.rows)
        wrong['etc/authserver.conf.dist']['bytes'] = measure.stock.LIMITS['fileBytes']
        with self.assertRaisesRegex(ValueError, 'file-size-or-mode|total-byte-bound'):
            measure.assemble_runtime(self.archive, wrong, self.extra, self.root / 'oversized.tar.gz')

    def test_unqualified_anchor_fails_before_creating_candidate_parent(self):
        pending = dict(formatVersion=1, scope='actual-playerbots-helper-corresponding-source-anchor', state='pending')
        with patch.object(measure.modules, 'read_json', return_value=(pending, {})):
            with self.assertRaisesRegex(ValueError, 'qualified-source-anchor-required'):
                measure.measure(self.root / 'absent', self.root / 'absent2', self.root / 'absent3', self.root / 'new/output')
        self.assertFalse((self.root / 'new').exists())

    def test_current_actual_anchor_is_separate_from_the_new_sql_unqualified_executable(self):
        pin, _, original = measure.load_anchor()
        self.assertEqual(pin['originalProgramsArchive'], original['archive'])
        self.assertEqual(pin['originalThreeProgramSourceQualification'], original['sourceQualification'])
        self.assertNotEqual(pin['helperRuntime']['executable'], pin['sourceObservation']['executable'])
        self.assertFalse(pin['sourceObservation']['sqlQualificationTransferred'])


if __name__ == '__main__': unittest.main()
