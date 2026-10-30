import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import initialize_server_schema as baseline


class Database:
    def __init__(self):
        self.tables = {name: [] for name in baseline.base.DB_ORDER}
        self.applied = []

    def query(self, sql):
        prefix = 'SHOW TABLES FROM `acore_'
        if not sql.startswith(prefix) or not sql.endswith('`'):
            raise AssertionError('baseline must not write invented SQL or updater ledger')
        return list(self.tables[sql[len(prefix):-1]])

    def apply(self, database, path):
        self.applied.append((database, str(path)))
        if path.name == Path(baseline.NEMESIS_BASE).name:
            self.tables[database].extend(baseline.NEMESIS_TABLES)
        else:
            self.tables[database].append(path.stem)


class BaselineGuards(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = Database()
        self.manifest = dict(source={'commit': baseline.base.content.SUPPORTED_SERVER},
            contentSha256Complete=True, files={}, databases={}, enabledModules=[baseline.NEMESIS_MODULE])
        self.counts = patch.dict(baseline.base.BASE_COUNTS, {name: 2 for name in baseline.DATABASES})
        self.counts.start(); self.addCleanup(self.counts.stop)
        for name in baseline.DATABASES:
            paths = []
            for table in ('first_table', 'updates'):
                path = baseline.base.content.DATABASES[name][1] + '/' + table + '.sql'
                self.add_source(path, b'-- synthetic fixture, never SQL qualified\n')
                paths.append(path)
            self.manifest['databases'][name] = dict(base=paths, updateOrder=[])
        self.nemesis = self.add_source(baseline.NEMESIS_BASE, b'-- synthetic prerequisite\n')
        self.identity = patch.object(baseline, 'NEMESIS_IDENTITY', self.nemesis)
        self.identity.start(); self.addCleanup(self.identity.stop)
        self.manifest['databases']['characters']['updateOrder'].append(
            dict(path=baseline.NEMESIS_BASE, state='MODULE', origin=baseline.NEMESIS_MODULE))

    def add_source(self, path, raw):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        identity = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
            gitBlob=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest())
        self.manifest['files'][path] = dict(identity, gitMode='100644')
        return identity

    def run_baseline(self):
        return baseline.initialize(self.db, self.root, self.manifest, self.db.apply)

    def test_all_core_bases_precede_only_documented_prerequisite_and_no_ledger_writes(self):
        receipt = self.run_baseline()
        expected = [(database, str(self.root / path)) for database in baseline.DATABASES
                    for path in self.manifest['databases'][database]['base']]
        self.assertEqual(self.db.applied, expected + [('characters', str(self.root / baseline.NEMESIS_BASE))])
        self.assertFalse(receipt['syntheticUpdaterLedgerRowsWritten'])
        self.assertFalse(receipt['compiledAutoPopulationQualified'])
        self.assertTrue(receipt['baselineImportCompleted'])
        self.assertEqual(self.db.tables['playerbots'], [])

    def test_every_nonempty_database_blocks_before_any_sql(self):
        for name in baseline.base.DB_ORDER:
            with self.subTest(database=name):
                self.db = Database(); self.db.tables[name] = ['keep_existing_character']
                with self.assertRaisesRegex(ValueError, 'nonempty database preserved'):
                    self.run_baseline()
                self.assertEqual(self.db.applied, [])
                self.assertEqual(self.db.tables[name], ['keep_existing_character'])

    def test_completed_or_interrupted_baseline_is_not_adopted_or_replayed(self):
        self.run_baseline()
        before = copy.deepcopy(self.db.tables)
        count = len(self.db.applied)
        with self.assertRaisesRegex(ValueError, 'nonempty database preserved'):
            self.run_baseline()
        self.assertEqual(self.db.tables, before)
        self.assertEqual(len(self.db.applied), count)
        self.db = Database()
        apply = self.db.apply
        def fail(database, path):
            apply(database, path)
            raise RuntimeError('private fixture interrupted')
        with self.assertRaises(RuntimeError):
            baseline.initialize(self.db, self.root, self.manifest, fail)
        with self.assertRaisesRegex(ValueError, 'nonempty database preserved'):
            self.run_baseline()
        self.assertEqual(len(self.db.applied), 1)

    def test_changed_last_file_is_detected_before_any_sql(self):
        (self.root / baseline.NEMESIS_BASE).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'source bytes differ'):
            self.run_baseline()
        self.assertEqual(self.db.applied, [])

    def test_ambiguous_or_reordered_core_inventory_never_executes(self):
        self.manifest['databases']['world']['base'].reverse()
        with self.assertRaisesRegex(ValueError, 'exact pinned immediate core base order'):
            self.run_baseline()
        self.assertEqual(self.db.applied, [])

    def test_missing_canonical_module_discovery_or_changed_contract_blocks(self):
        self.manifest['databases']['characters']['updateOrder'] = []
        with self.assertRaisesRegex(ValueError, 'actual updater selection'):
            self.run_baseline()
        self.assertEqual(self.db.applied, [])
        self.manifest['files'][baseline.NEMESIS_BASE]['gitBlob'] = 'f' * 40
        with self.assertRaisesRegex(ValueError, 'source prerequisite changed'):
            self.run_baseline()
        self.assertEqual(self.db.applied, [])

    def test_module_not_selected_never_receives_its_prerequisite(self):
        self.manifest['enabledModules'] = []
        receipt = self.run_baseline()
        self.assertEqual(receipt['documentedModulePrerequisites'], [])
        self.assertEqual(len(self.db.applied), 6)

    def test_wrong_table_set_stops_before_later_database_or_module(self):
        def wrong(database, path):
            self.db.applied.append((database, str(path)))
        with self.assertRaisesRegex(ValueError, 'core baseline table set differs'):
            baseline.initialize(self.db, self.root, self.manifest, wrong)
        self.assertEqual([name for name, _ in self.db.applied], ['auth', 'auth'])


class ActualPinnedSource(unittest.TestCase):
    def test_audited_nemesis_base_bytes_and_idempotent_creation_are_unchanged(self):
        roots = (Path(__file__).resolve().parents[1] / 'sources/server',
                 Path(__file__).resolve().parents[2] / 'server-src')
        source = next((root for root in roots if (root / baseline.NEMESIS_BASE).is_file()), None)
        if source is None:
            self.skipTest('pinned source checkout unavailable; actual SQL gate verifies bytes before import')
        raw = (source / baseline.NEMESIS_BASE).read_bytes()
        identity = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
            gitBlob=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest())
        self.assertEqual(identity, baseline.NEMESIS_IDENTITY)
        self.assertEqual(raw.count(b'CREATE TABLE IF NOT EXISTS'), 2)
        self.assertNotIn(b'DROP ', raw.upper())
        self.assertNotIn(b'ALTER ', raw.upper())
        for required in (b'`zone_id`', b'`last_seen_at`', b'`idx_character_nemesis_last_seen`'):
            self.assertIn(required, raw)
