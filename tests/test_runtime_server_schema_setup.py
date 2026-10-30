import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime import mysql_bootstrap as db, server_content as content, server_schema_baseline as baseline
from runtime import server_schema_setup as setup


class Connection:
    def __init__(self, fixture):
        self.fixture = fixture
        self.tables = {name: [] for name in baseline.DB_ORDER}
        self.applied = []
        self.locked = False

    def query(self, sql):
        if sql.startswith('SHOW TABLES FROM `acore_'):
            return list(self.tables[sql.removeprefix('SHOW TABLES FROM `acore_')[:-1]])
        if sql == 'SELECT VERSION(), @@version_comment, @@server_uuid, @@datadir':
            return ['8.0.46\tMySQL Community\t' + self.fixture.uuid + '\t' + str(self.fixture.state / 'database')]
        if sql == 'SELECT @@port, @@bind_address': return ['13306\t127.0.0.1']
        if sql == 'SELECT CURRENT_USER()': return ['esteria@127.0.0.1']
        if sql.startswith('SELECT GET_LOCK('): self.locked = True; return ['1']
        if sql.startswith('SELECT RELEASE_LOCK('): self.locked = False; return ['1']
        if sql.startswith('SELECT COUNT(*) FROM `acore_characters`.`character_'):
            return ['0']
        raise AssertionError('Unexpected SQL; no source DDL or ledger may be invented')

    def apply(self, database, path):
        self.applied.append((database, path))
        if path.name == Path(baseline.NEMESIS_BASE).name: self.tables[database] += list(baseline.NEMESIS_TABLES)
        elif path.name == Path(baseline.CUSTOM_RACE_DDL).name: self.tables[database] += list(baseline.CUSTOM_RACE_TABLES)
        elif path.name == 'appearance-schema-v1.sql': self.tables[database] += list(setup.adaptations.TABLES)
        else: self.tables[database].append(path.stem)


class PackagedSchemaGuards(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.state = self.root / 'state'; self.source = self.root / 'content/source'
        (self.state / 'database').mkdir(parents=True); (self.state / 'accounts').mkdir()
        self.uuid = '01234567-89ab-4cde-8fab-0123456789ab'
        (self.state / 'database/auto.cnf').write_text('[auto]\nserver-uuid=' + self.uuid + '\n')
        for name in ('database-secret', 'database-root-secret'):
            (self.state / 'accounts' / name).write_text('a' * 64 + '\n')
        db.atomic_json(self.state / 'database-bootstrap.json', dict(format=1, engine='mysql', version='8.0.46',
            uuid=self.uuid, datadir=str(self.state / 'database'), databases=list(db.DATABASES), application_schemas_populated=False))
        self.manifest = dict(source={'commit': baseline.SUPPORTED_SERVER}, contentSha256Complete=True,
            enabledModules=[baseline.NEMESIS_MODULE], files={}, databases={})
        for database in baseline.DATABASES:
            paths = [baseline.BASE_ROOTS[database] + '/' + name + '.sql' for name in ('first_table', 'updates')]
            for path in paths: self.file(path)
            self.manifest['databases'][database] = dict(base=paths, updateOrder=[])
        nemesis = self.file(baseline.NEMESIS_BASE); custom = self.file(baseline.CUSTOM_RACE_DDL)
        self.manifest['databases']['characters']['updateOrder'] = [dict(path=baseline.NEMESIS_BASE,
            state='MODULE', origin=baseline.NEMESIS_MODULE)]
        self.manifest['databases']['world']['updateOrder'] = [dict(path=baseline.CUSTOM_RACE_DDL,
            state='PENDING', origin='base-updates_include')]
        for target, value in ((patch.dict(baseline.BASE_COUNTS, {name: 2 for name in baseline.DATABASES}), None),
                              (patch.object(baseline, 'NEMESIS_IDENTITY', nemesis), None),
                              (patch.object(baseline, 'CUSTOM_RACE_IDENTITY', custom), None)):
            target.start(); self.addCleanup(target.stop)
        receipt = dict(sourceLockSha256='b' * 64, compiledModules=dict(bytes=50, sha256='c' * 64))
        self.content = content.VerifiedContent(self.source.parent, self.source, self.manifest, {}, receipt,
            dict(receipt=dict(bytes=100, sha256='d' * 64), files={}))
        sql = self.root / 'integration/appearance-schema-v1.sql'; sql.parent.mkdir()
        sql.write_bytes(b'-- synthetic source-derived appearance DDL fixture\n')
        proof = dict(adaptationId='test-appearance-v1', sqlIdentity=baseline.file_identity(sql),
            metadataIdentity=dict(bytes=12, sha256='e' * 64), sourceLockSha256='b' * 64,
            sourceDerived=True, canonicalOriginal=False, sqlExecuted=False, exactEmptyTableAdditionVerified=False)
        prepared = setup.adaptations.Preparation(sql, setup.adaptations.TABLES, proof)
        adaptation = patch.object(setup.adaptations, 'prepare', return_value=prepared)
        adaptation.start(); self.addCleanup(adaptation.stop)
        self.connection = Connection(self)

    def file(self, relative):
        path = self.source / relative; path.parent.mkdir(parents=True, exist_ok=True)
        raw = b'-- synthetic schema fixture; never executed as real SQL\n'; path.write_bytes(raw)
        identity = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
            gitBlob=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest())
        self.manifest['files'][relative] = identity
        return identity

    def run_setup(self, **kwargs):
        return setup.initialize(self.content, self.connection, self.state, '8.0.46', self.connection.apply, **kwargs)

    def test_source_baseline_journal_completes_and_repeat_never_replays_sql(self):
        progress = []; first = self.run_setup(progress=progress.append)
        self.assertEqual(first['operation'], 'initialized-source-baseline'); self.assertEqual(len(self.connection.applied), 9)
        self.assertTrue(first['sourceDerivedAdaptations'][0]['sourceDerived'])
        self.assertFalse(first['sourceDerivedAdaptations'][0]['canonicalOriginal'])
        self.assertFalse(first['gameSchemasQualified']); self.assertFalse(first['compiledUpdaterExecuted'])
        self.assertFalse(first['liveSchemaReadinessVerified']); self.assertFalse(self.connection.locked)
        self.assertEqual(len(progress), 18)
        journal = self.state / setup.JOURNAL; before = journal.read_bytes()
        second = self.run_setup(); self.assertEqual(second['operation'], 'already-prepared')
        self.assertEqual(journal.read_bytes(), before); self.assertEqual(len(self.connection.applied), 9)
        self.assertEqual(journal.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('credentials', first)

    def test_all_four_nonempty_databases_block_before_journal_or_sql(self):
        for name in baseline.DB_ORDER:
            self.connection = Connection(self); self.connection.tables[name] = ['saved_character']
            with self.subTest(database=name), self.assertRaisesRegex(ValueError, 'nonempty database preserved'):
                self.run_setup()
            self.assertEqual(self.connection.applied, []); self.assertFalse((self.state / setup.JOURNAL).exists())

    def test_cancel_before_work_is_immediate_and_creates_no_journal(self):
        with self.assertRaises(setup.SchemaCancelled): self.run_setup(cancelled=lambda: True)
        self.assertFalse((self.state / setup.JOURNAL).exists()); self.assertEqual(self.connection.applied, [])

    def test_cancel_after_one_file_preserves_partial_journal_and_refuses_replay(self):
        with self.assertRaises(setup.SchemaCancelled): self.run_setup(cancelled=lambda: bool(self.connection.applied))
        self.assertEqual(len(self.connection.applied), 1)
        before = (self.state / setup.JOURNAL).read_bytes()
        with self.assertRaisesRegex(db.BootstrapError, 'Partial schema setup'): self.run_setup()
        self.assertEqual((self.state / setup.JOURNAL).read_bytes(), before)
        self.assertEqual(len(self.connection.applied), 1)

    def test_cancellation_from_started_progress_never_executes_sql(self):
        cancelled = False
        def progress(update):
            nonlocal cancelled
            if update['phase'] == 'schema-file-started': cancelled = True
        with self.assertRaises(setup.SchemaCancelled):
            self.run_setup(progress=progress, cancelled=lambda: cancelled)
        self.assertEqual(self.connection.applied, [])
        journal = json.loads((self.state / setup.JOURNAL).read_text())
        self.assertEqual(journal['phase'], 'importing'); self.assertIsNotNone(journal['pending'])
        with self.assertRaisesRegex(db.BootstrapError, 'Partial schema setup'): self.run_setup()

    def test_prepared_retry_refuses_account_journal_appearing_after_safe_cancellation(self):
        journal = self.state / setup.JOURNAL
        with self.assertRaises(setup.SchemaCancelled): self.run_setup(cancelled=journal.exists)
        self.assertEqual(json.loads(journal.read_text())['phase'], 'prepared')
        path = self.state / setup.ACCOUNT; path.write_bytes(b'new private account intent')
        before = journal.read_bytes()
        with self.assertRaisesRegex(db.BootstrapError, 'Existing account journal preserved'): self.run_setup()
        self.assertEqual(self.connection.applied, []); self.assertEqual(journal.read_bytes(), before)
        self.assertEqual(path.read_bytes(), b'new private account intent')

    def test_cancellation_before_separate_appearance_sql_preserves_original_baseline_without_replay(self):
        cancelled = False
        def progress(update):
            nonlocal cancelled
            if update['phase'] == 'schema-file-started' and update['path'] == setup.APPEARANCE_PATH:
                cancelled = True
        with self.assertRaises(setup.SchemaCancelled):
            self.run_setup(progress=progress, cancelled=lambda: cancelled)
        self.assertEqual(len(self.connection.applied), 8)
        self.assertFalse(set(setup.adaptations.TABLES).intersection(self.connection.tables['characters']))
        journal = json.loads((self.state / setup.JOURNAL).read_text())
        self.assertEqual(journal['pending']['path'], setup.APPEARANCE_PATH)
        with self.assertRaisesRegex(db.BootstrapError, 'Partial schema setup'): self.run_setup()
        self.assertEqual(len(self.connection.applied), 8)

    def test_changed_adaptation_metadata_is_not_adopted_on_completed_reentry(self):
        self.run_setup(); before = (self.state / setup.JOURNAL).read_bytes()
        previous = setup.adaptations.prepare.return_value
        changed = setup.adaptations.Preparation(previous.sql_path, previous.tables,
            dict(previous.proof, metadataIdentity=dict(bytes=13, sha256='f' * 64)))
        setup.adaptations.prepare.return_value = changed
        with self.assertRaisesRegex(db.BootstrapError, 'identity changed'): self.run_setup()
        self.assertEqual((self.state / setup.JOURNAL).read_bytes(), before)
        self.assertEqual(len(self.connection.applied), 9)

    def test_sql_failure_keeps_in_flight_intent_and_never_retries(self):
        def failure(database, path): self.connection.apply(database, path); raise RuntimeError('private SQL failure')
        with self.assertRaises(RuntimeError):
            setup.initialize(self.content, self.connection, self.state, '8.0.46', failure)
        journal = json.loads((self.state / setup.JOURNAL).read_text())
        self.assertEqual(journal['phase'], 'importing'); self.assertIsNotNone(journal['pending'])
        with self.assertRaisesRegex(db.BootstrapError, 'Partial schema setup'): self.run_setup()
        self.assertEqual(len(self.connection.applied), 1)

    def test_completed_content_or_credential_change_never_adopts_or_upgrades(self):
        self.run_setup(); before = (self.state / setup.JOURNAL).read_bytes()
        self.content.receipt['sourceLockSha256'] = 'e' * 64
        with self.assertRaisesRegex(db.BootstrapError, 'identity changed'): self.run_setup()
        self.assertEqual((self.state / setup.JOURNAL).read_bytes(), before)
        self.assertEqual(len(self.connection.applied), 9)

    def test_existing_account_journal_is_preserved_before_any_sql(self):
        path = self.state / setup.ACCOUNT; path.write_bytes(b'private prior account intent')
        with self.assertRaisesRegex(db.BootstrapError, 'Existing account journal preserved'): self.run_setup()
        self.assertEqual(path.read_bytes(), b'private prior account intent')
        self.assertEqual(self.connection.applied, []); self.assertFalse((self.state / setup.JOURNAL).exists())

    def test_missing_existing_credential_does_not_create_one(self):
        path = self.state / 'accounts/database-secret'; path.unlink()
        with self.assertRaises(db.BootstrapError): self.run_setup()
        self.assertFalse(path.exists()); self.assertEqual(self.connection.applied, [])

    def test_instance_identity_failure_never_writes_schema_journal(self):
        (self.state / 'database/auto.cnf').write_text('server-uuid=11234567-89ab-4cde-8fab-0123456789ab\n')
        with self.assertRaisesRegex(db.BootstrapError, 'identity changed'): self.run_setup()
        self.assertEqual(self.connection.applied, []); self.assertFalse((self.state / setup.JOURNAL).exists())


if __name__ == '__main__': unittest.main()
