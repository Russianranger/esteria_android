import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from runtime import mysql_bootstrap as db, server_schema_baseline as baseline
from runtime import server_schema_setup as schema, server_schema_adaptations as adaptations
from runtime import server_update_setup as setup, server_updater as updater
from tests import test_runtime_server_content as content_fixture


class Connection:
    def __init__(self, owner):
        self.owner = owner
        self.tables = {name: [] for name in baseline.DB_ORDER}
        self.ledgers = {name: [] for name in updater.DATABASES}
        self.accounts = self.characters = 0
        self.locked = False
        self.queries = []

    def query(self, sql):
        self.queries.append(sql)
        if sql == setup.STOCK_OVERLAYS_SQL: return ['0\t0\t0\t0']
        if sql == setup.STOCK_START_SQL: return ['1']
        if sql == 'SELECT VERSION(), @@version_comment, @@server_uuid, @@datadir':
            return ['8.0.46\tMySQL Community\t' + self.owner.uuid + '\t' + str(self.owner.state / 'database')]
        if sql == 'SELECT @@port, @@bind_address': return ['13306\t127.0.0.1']
        if sql == 'SELECT CURRENT_USER()': return ['esteria@127.0.0.1']
        if sql == "SELECT IS_USED_LOCK('esteria-local-bootstrap') = CONNECTION_ID()": return ['1' if self.locked else '0']
        if sql.startswith('SELECT GET_LOCK('): self.locked = True; return ['1']
        if sql.startswith('SELECT RELEASE_LOCK('): self.locked = False; return ['1']
        if sql.startswith('SHOW TABLES FROM `acore_'):
            return sorted(self.tables[sql[len('SHOW TABLES FROM `acore_'):-1]])
        if sql == 'SELECT COUNT(*) FROM `acore_auth`.`account`': return [str(self.accounts)]
        if sql == 'SELECT COUNT(*) FROM `acore_characters`.`characters`': return [str(self.characters)]
        if sql.startswith('SELECT COUNT(*) FROM `acore_characters`.`character_'): return ['0']
        if sql.startswith('SELECT name,hash,state FROM `acore_'):
            name = sql.split('`acore_', 1)[1].split('`', 1)[0]
            return self.ledgers[name]
        raise AssertionError('Unexpected SQL; fixture does not execute source or credential DDL')

    def apply_baseline(self, database, path):
        if path == adaptations.SQL_PATH:
            self.tables[database].extend(adaptations.TABLES)
        elif path.name == Path(baseline.CUSTOM_RACE_DDL).name:
            self.tables[database].extend(baseline.CUSTOM_RACE_TABLES)
        else:
            self.tables[database].append(path.stem)


class RuntimeUpdaterSetup(unittest.TestCase):
    def setUp(self):
        fixture = content_fixture.RuntimeContent(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.fixture = fixture; self.root = fixture.base
        lock = json.loads(adaptations.LOCK_PATH.read_bytes())
        digest = '5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1'
        fixture.source = copy.deepcopy(lock['supportedSourceSelections'][digest]); fixture.lock = digest
        for document in (fixture.manifest, fixture.compiled):
            document['source'] = copy.deepcopy(fixture.source); document['sourceLockSha256'] = digest
        fixture.lua['serverRevision'] = fixture.source['commit']
        fixture.lua['elunaRevision'] = fixture.source['submodules'][content_fixture.content.ELUNA]
        fixture.receipt.update(source=copy.deepcopy(fixture.source), sourceLockSha256=digest)
        for database in updater.DATABASES:
            path = baseline.BASE_ROOTS[database] + '/updates_include.sql'; raw = b'-- fixture include table\n'
            fixture.payload['source/' + path] = raw
            fixture.manifest['files'][path] = content_fixture.source_identity(raw)
            fixture.manifest['databases'][database]['base'].append(path)
        path = baseline.CUSTOM_RACE_DDL; raw = b'-- fixture canonical prerequisite\n'
        fixture.payload['source/' + path] = raw
        identity = content_fixture.source_identity(raw)
        fixture.manifest['files'][path] = identity
        fixture.manifest['databases']['world']['updateOrder'].append(
            dict(path=path, state='PENDING', origin='base-updates_include'))
        for context in (patch.dict(baseline.BASE_COUNTS, {name: 2 for name in updater.DATABASES}),
                        patch.object(baseline, 'CUSTOM_RACE_IDENTITY',
                                     {key: identity[key] for key in ('bytes', 'sha256', 'gitBlob')})):
            context.start(); self.addCleanup(context.stop)
        fixture.write(); self.content = fixture.verify()
        self.state = self.root / 'state'
        for name in ('accounts', 'database', 'run', 'logs'):
            (self.state / name).mkdir(parents=True)
        self.uuid = '01234567-89ab-4cde-8fab-0123456789ab'
        (self.state / 'database/auto.cnf').write_text('[auto]\nserver-uuid=' + self.uuid + '\n')
        for name, secret in (('database-secret', 'a'), ('database-root-secret', 'b')):
            path = self.state / 'accounts' / name; path.write_text(secret * 64 + '\n'); path.chmod(0o600)
        db.atomic_json(self.state / 'database-bootstrap.json', dict(format=1, engine='mysql', version='8.0.46',
            uuid=self.uuid, datadir=str(self.state / 'database'), databases=list(db.DATABASES)))
        self.connection = Connection(self)
        # Obtain a real completed journal through the product initializer. The
        # SQL connection is a fixture; no journal/proof is manually manufactured.
        schema.initialize(self.content, self.connection, self.state, '8.0.46', self.connection.apply_baseline)
        self.executable = self.root / 'fixture-updater'
        self.executable.write_text('#!' + str(Path(sys.executable).resolve()) + '\nprint("fixture updater process complete")\n')
        self.executable.chmod(0o700)
        self.template = self.root / 'dbimport.conf.dist'
        keys = ('SourceDirectory MySQLExecutable LogsDir TempDir Updates.EnableDatabases Updates.AllowedModules '
            'Updates.AutoSetup Updates.Redundancy Updates.AllowRehash Updates.ArchivedRedundancy '
            'Updates.CleanDeadRefMaxCount Database.Reconnect.Attempts Database.Reconnect.Seconds Logger.root '
            'LoginDatabaseInfo LoginDatabase.WorkerThreads LoginDatabase.SynchThreads CharacterDatabaseInfo '
            'CharacterDatabase.WorkerThreads CharacterDatabase.SynchThreads WorldDatabaseInfo '
            'WorldDatabase.WorkerThreads WorldDatabase.SynchThreads').split()
        self.template.write_text('[dbimport]\n' + '\n'.join(key + ' = 0' for key in keys) + '\n')
        self.program_pin = baseline.file_identity(self.executable)
        self.template_pin = baseline.file_identity(self.template)
        self.mysql = Path(sys.executable).resolve()
        self.plan = self.prepare()
        self.runs = []

    def prepare(self, **kwargs):
        return setup.prepare(self.content, self.executable, self.program_pin, self.template, self.template_pin,
            self.mysql, original_build_identity=kwargs.pop('original_build_identity', self.content.compiled['serverBuild']),
            **kwargs)

    def runner(self, executable, configuration, log, **kwargs):
        # Check durable intent before the real child can begin. This executable
        # is explicitly a host fixture, never a compiled-server qualification.
        journal = schema.private_journal(self.state / setup.JOURNAL)
        self.assertEqual(journal['phase'], 'in-flight')
        self.runs.append(configuration)
        result = self.real_runner(executable, configuration, log, **kwargs)
        for database, rows in self.plan.expected.items():
            self.connection.ledgers[database] = [name + '\t' + digest + '\t' + state
                for name, (digest, state) in sorted(rows.items())]
        return result

    def run_updater(self, **kwargs):
        self.real_runner = updater.run_importer
        with patch.object(updater, 'run_importer', side_effect=self.runner):
            return setup.apply(self.plan, self.connection, self.state, '8.0.46', **kwargs)

    def test_real_completed_baseline_and_pinned_child_complete_then_repeat_without_replay(self):
        baseline_bytes = (self.state / schema.JOURNAL).read_bytes()
        first = self.run_updater()
        self.assertTrue(first['compiledUpdaterExecuted']); self.assertTrue(first['sourceLedgersVerified'])
        self.assertFalse(first['gameSchemasQualified']); self.assertFalse(first['worldserverExecuted'])
        self.assertEqual((self.state / schema.JOURNAL).read_bytes(), baseline_bytes)
        self.assertEqual(len(self.runs), 1); self.assertFalse(self.connection.locked)
        # Later owned account provisioning is compatible with validation-only
        # repeat; neither it nor game rows authorize another updater execution.
        account = self.state / schema.ACCOUNT; account.write_bytes(b'preserved later private account intent')
        self.connection.accounts = self.connection.characters = 1
        second = self.run_updater()
        self.assertFalse(second['compiledUpdaterExecuted']); self.assertEqual(len(self.runs), 1)
        self.assertEqual(account.read_bytes(), b'preserved later private account intent')
        self.assertNotIn('credentials', second); self.assertNotIn('invocation', second)

    def test_stock_sql_view_uses_only_selected_exact_source_bytes_and_rejects_tampering(self):
        # These are explicit fixture bytes. This checks real projection IO and
        # policy admission, and makes no SQL/world execution claim.
        rows = [
            ('data/sql/updates/pending_db_world/rev_20261005010000000.sql', False),
            ('modules/mod-classless-wildcard/data/sql/db-world/cw_world_item_classes.sql', False),
            ('modules/mod-battlemon/data/sql/world/base/2026_08_21_00_battlemon_overworld.sql', False),
            ('modules/mod-battlemon/data/sql/db-world/base/2026_08_20_catalog.sql', True),
            ('data/sql/updates/db_world/2024_01_01_stock.sql', True),
        ]
        for index, (path, selected) in enumerate(rows):
            raw = ('-- SOURCE FIXTURE ' + str(index) + '\n').encode()
            self.fixture.payload['source/' + path] = raw
            self.fixture.manifest['files'][path] = content_fixture.source_identity(raw)
            self.fixture.manifest['databases']['world']['updateOrder'].append(
                dict(path=path, state='PENDING' if '/pending_' in path else 'MODULE',
                     origin='base-updates_include' if path.startswith('data/') else path.split('/')[1]))
        # Reverify metadata through the actual archive verifier. Keep the
        # unrelated preexisting completed DB fixture out of this IO-only test.
        self.fixture.write(); self.content = self.fixture.verify()
        plan = self.prepare()
        operation = self.root / 'stock-operation'; operation.mkdir()
        destination, inventory = setup._project_stock_sql(plan, operation)
        setup._verify_stock_sql(destination, inventory)
        self.assertEqual(plan.binding['contentProfile'], 'stock-3.3.5a')
        self.assertEqual(plan.binding['sqlSelectionPolicy'], setup.STOCK_SQL_POLICY)
        for path, selected in rows:
            self.assertEqual((destination / path).exists(), selected)
            if selected:
                self.assertEqual((destination / path).read_bytes(), (self.content.source / path).read_bytes())
            self.assertTrue((self.content.source / path).is_file())
        self.assertIn(baseline.CUSTOM_RACE_DDL, inventory)
        extra = destination / 'data/sql/updates/db_world/injected.sql'
        extra.write_bytes(b'-- unexpected SQL\n')
        with self.assertRaisesRegex(db.BootstrapError, 'file set changed'):
            setup._verify_stock_sql(destination, inventory)
        extra.unlink()
        selected = destination / rows[-1][0]
        selected.write_bytes(b'-- substituted SQL\n')
        with self.assertRaisesRegex(db.BootstrapError, 'artifact'):
            setup._verify_stock_sql(destination, inventory)

    def test_stock_sql_gate_rejects_custom_overlay_or_missing_human_start(self):
        # A fixture connection exercises error boundaries only. Real MySQL
        # qualification is separate and must execute these same queries.
        original = self.connection.query
        for query, response, message in ((setup.STOCK_OVERLAYS_SQL, ['1\t0\t0\t0'], 'overlays must be empty'),
                                         (setup.STOCK_START_SQL, ['0'], 'Human Warrior start')):
            def changed(sql):
                return response if sql == query else original(sql)
            with self.subTest(query=query), patch.object(self.connection, 'query', side_effect=changed), \
                    self.assertRaisesRegex(db.BootstrapError, message):
                setup.stock_world_sql_snapshot(self.connection)

    def test_real_outer_lease_is_forwarded_to_baseline_validation_and_update_scope(self):
        with db.state_lock(self.state) as lease:
            with patch.object(db, 'state_lock', side_effect=AssertionError('must reuse the real outer lease')):
                first = self.run_updater(state_lease=lease)
                second = self.run_updater(state_lease=lease)
            with self.assertRaisesRegex(db.BootstrapError, 'Another bootstrap operation'):
                with db.state_lock(self.state): self.fail('updater released outer file lock')
        self.assertTrue(first['compiledUpdaterExecuted']); self.assertFalse(second['compiledUpdaterExecuted'])
        self.assertEqual(len(self.runs), 1)

    def test_expected_sha1_matches_shared_primitive_and_changed_payload_fails_prepare(self):
        for name in updater.DATABASES:
            self.assertEqual(self.plan.expected[name], updater.expected_updates(self.content.source, self.content.manifest, name))
        path = self.content.source / 'modules/mod-one/data/sql/db-auth/update.sql'
        path.write_bytes(b'changed selected update')
        with self.assertRaisesRegex(db.BootstrapError, 'artifact'):
            self.prepare()
        self.assertFalse((self.state / setup.JOURNAL).exists())

    def test_wrong_original_build_metadata_program_or_template_pins_fail_before_update_journal(self):
        with self.assertRaisesRegex(db.BootstrapError, 'original build'):
            self.prepare(original_build_identity=dict(bytes=123, sha256='0' * 64))
        metadata = self.content.root / 'metadata/compiled-modules.json'
        raw = metadata.read_bytes(); metadata.write_bytes(raw + b' ')
        with self.assertRaisesRegex(db.BootstrapError, 'artifact'):
            self.prepare()
        metadata.write_bytes(raw)
        for path in (self.executable, self.template):
            raw = path.read_bytes(); path.write_bytes(raw + b'changed')
            with self.subTest(path=path.name), self.assertRaisesRegex(db.BootstrapError, 'artifact'):
                self.prepare()
            path.write_bytes(raw)
        self.assertFalse((self.state / setup.JOURNAL).exists())

    def test_missing_or_partial_baseline_is_never_initialized_or_replayed(self):
        path = self.state / schema.JOURNAL; raw = path.read_bytes(); path.unlink()
        with patch.object(schema, 'initialize') as initialize, self.assertRaises(OSError):
            self.run_updater()
        initialize.assert_not_called(); self.assertFalse((self.state / setup.JOURNAL).exists())
        path.write_bytes(raw); path.chmod(0o600)
        journal = json.loads(raw); journal['phase'] = 'importing'; db.atomic_json(path, journal)
        with patch.object(schema, 'initialize') as initialize, self.assertRaisesRegex(db.BootstrapError, 'Completed source baseline'):
            self.run_updater()
        initialize.assert_not_called(); self.assertFalse(self.runs)

    def test_existing_accounts_characters_or_account_journal_prevent_first_adoption(self):
        for kind in ('account', 'character', 'journal'):
            self.connection.accounts = int(kind == 'account'); self.connection.characters = int(kind == 'character')
            path = self.state / schema.ACCOUNT
            if kind == 'journal': path.write_bytes(b'existing private intent')
            with self.subTest(kind=kind), self.assertRaisesRegex(db.BootstrapError, 'adoption refused'):
                self.run_updater()
            self.assertFalse((self.state / setup.JOURNAL).exists()); self.assertFalse(self.runs)

    def test_cancel_before_work_or_during_hashing_creates_no_update_journal(self):
        with self.assertRaises(setup.UpdateCancelled): self.run_updater(cancelled=lambda: True)
        stopped = False
        def progress(_event):
            nonlocal stopped
            stopped = True
        with self.assertRaises(setup.UpdateCancelled): self.prepare(progress=progress, cancelled=lambda: stopped)
        self.assertFalse((self.state / setup.JOURNAL).exists()); self.assertFalse(self.runs)

    def test_cancel_requested_after_durable_intent_finishes_one_bounded_updater(self):
        stopped = False
        def progress(event):
            nonlocal stopped
            if event['phase'] == 'compiled-updater-intent-committed': stopped = True
        result = self.run_updater(progress=progress, cancelled=lambda: stopped)
        self.assertTrue(stopped); self.assertTrue(result['compiledUpdaterExecuted'])
        self.assertEqual(schema.private_journal(self.state / setup.JOURNAL)['phase'], 'complete')
        self.assertEqual(len(self.runs), 1)

    def test_prepared_cancel_retries_only_an_untouched_baseline(self):
        path = self.state / setup.JOURNAL
        with self.assertRaises(setup.UpdateCancelled):
            self.run_updater(cancelled=lambda: path.exists())
        self.assertEqual(schema.private_journal(path)['phase'], 'prepared')
        self.assertFalse(self.runs)
        result = self.run_updater()
        self.assertTrue(result['compiledUpdaterExecuted']); self.assertEqual(len(self.runs), 1)

    def test_prepared_retry_refuses_changed_table_set(self):
        path = self.state / setup.JOURNAL
        with self.assertRaises(setup.UpdateCancelled): self.run_updater(cancelled=lambda: path.exists())
        before = path.read_bytes()
        self.connection.tables['world'].append('unexpected_existing_table')
        with self.assertRaisesRegex(db.BootstrapError, 'Prepared updater state changed'):
            self.run_updater()
        self.assertEqual(path.read_bytes(), before); self.assertFalse(self.runs)

    def test_failed_or_inflight_updater_is_preserved_and_refused(self):
        with patch.object(updater, 'run_importer', side_effect=RuntimeError('private failure')):
            with self.assertRaises(RuntimeError): setup.apply(self.plan, self.connection, self.state, '8.0.46')
        path = self.state / setup.JOURNAL; before = path.read_bytes()
        self.assertEqual(json.loads(before)['phase'], 'failed')
        with self.assertRaisesRegex(db.BootstrapError, 'replay refused'): self.run_updater()
        self.assertEqual(path.read_bytes(), before); self.assertFalse(self.runs)
        journal = json.loads(before); journal['phase'] = 'in-flight'; db.atomic_json(path, journal)
        with self.assertRaisesRegex(db.BootstrapError, 'replay refused'): self.run_updater()

    def test_changed_credential_baseline_or_service_identity_never_launches(self):
        with self.assertRaisesRegex(db.BootstrapError, 'service identity changed'):
            self.run_updater(verify_service=lambda: False)
        self.assertFalse(self.runs); self.assertFalse((self.state / setup.JOURNAL).exists())
        self.run_updater(); before = (self.state / setup.JOURNAL).read_bytes()
        secret = self.state / 'accounts/database-secret'; secret.write_text('c' * 64 + '\n')
        with self.assertRaisesRegex(db.BootstrapError, 'identity changed|credentials or instance changed'):
            self.run_updater()
        self.assertEqual((self.state / setup.JOURNAL).read_bytes(), before)
        self.assertEqual(len(self.runs), 1)

    def test_service_owner_change_after_child_cannot_complete_a_journal(self):
        def owner():
            return not self.runs
        with self.assertRaisesRegex(db.BootstrapError, 'service identity changed'):
            self.run_updater(verify_service=owner)
        journal = schema.private_journal(self.state / setup.JOURNAL)
        self.assertEqual(journal['phase'], 'failed'); self.assertTrue(journal['compiledUpdaterExecuted'])
        self.assertEqual(len(self.runs), 1); self.assertFalse(self.connection.locked)

    def test_program_changed_by_started_observer_never_reaches_process_creation(self):
        def progress(event):
            if event['phase'] == 'compiled-updater-intent-committed': self.executable.write_bytes(b'changed before Popen')
        with self.assertRaisesRegex(db.BootstrapError, 'artifact'):
            self.run_updater(progress=progress)
        journal = schema.private_journal(self.state / setup.JOURNAL)
        self.assertEqual(journal['phase'], 'failed'); self.assertFalse(journal['compiledUpdaterExecuted'])
        self.assertFalse(self.runs)

    def test_completed_repeat_refuses_live_ledger_drift_without_running_again(self):
        self.run_updater(); path = self.state / setup.JOURNAL; before = path.read_bytes()
        row = self.connection.ledgers['auth'][0]
        self.connection.ledgers['auth'][0] = row.replace(self.plan.expected['auth'][row.split('\t')[0]][0], '0' * 40)
        with self.assertRaisesRegex(ValueError, 'ledger/hash differs'):
            self.run_updater()
        self.assertEqual(path.read_bytes(), before); self.assertEqual(len(self.runs), 1)

    def test_public_completed_verifier_is_read_only_under_caller_locks_and_never_reads_binaries(self):
        self.run_updater()
        self.connection.query("SELECT GET_LOCK('esteria-local-bootstrap',0)")
        self.connection.queries.clear()
        self.executable.unlink(); self.template.unlink()
        journal = self.state / setup.JOURNAL; before = journal.read_bytes()
        secret = self.state / 'accounts/database-secret'; secret_stamp = secret.stat().st_ctime_ns
        with patch.object(db, 'state_lock', side_effect=AssertionError('must retain caller lock')), \
             patch.object(db, 'atomic_json', side_effect=AssertionError('must not rewrite journal')), \
             patch.object(schema, 'initialize', side_effect=AssertionError('must not invoke baseline')), \
             patch.object(updater, 'run_importer', side_effect=AssertionError('must not execute')):
            result = setup.verify_completed_update(self.content, self.connection, self.state, '8.0.46',
                expected_uuid=self.uuid, verify_service=lambda: True)
        self.assertFalse(result['compiledUpdaterExecuted']); self.assertTrue(result['sourceLedgersVerified'])
        self.assertEqual(result['journalIdentity'], baseline.file_identity(journal))
        self.assertEqual(journal.read_bytes(), before); self.assertEqual(secret.stat().st_ctime_ns, secret_stamp)
        self.assertTrue(self.connection.locked)
        self.assertFalse(any('GET_LOCK' in sql or 'RELEASE_LOCK' in sql for sql in self.connection.queries))
        self.assertTrue(all(sql.startswith(('SELECT ', 'SHOW TABLES ')) for sql in self.connection.queries))

    def test_public_completed_verifier_requires_owned_sql_lock_exact_uuid_and_complete_journal(self):
        self.run_updater()
        with self.assertRaisesRegex(db.BootstrapError, 'Caller must own'):
            setup.verify_completed_update(self.content, self.connection, self.state, '8.0.46',
                expected_uuid=self.uuid, verify_service=lambda: True)
        self.connection.query("SELECT GET_LOCK('esteria-local-bootstrap',0)")
        with self.assertRaisesRegex(db.BootstrapError, 'service UUID differs'):
            setup.verify_completed_update(self.content, self.connection, self.state, '8.0.46',
                expected_uuid='11234567-89ab-4cde-8fab-0123456789ab', verify_service=lambda: True)
        path = self.state / setup.JOURNAL; original = json.loads(path.read_bytes())
        for phase in ('prepared', 'in-flight', 'failed'):
            changed = dict(original, phase=phase); db.atomic_json(path, changed)
            with self.subTest(phase=phase), self.assertRaisesRegex(db.BootstrapError, 'completed compiled updater journal'):
                setup.verify_completed_update(self.content, self.connection, self.state, '8.0.46',
                    expected_uuid=self.uuid, verify_service=lambda: True)
        self.assertTrue(self.connection.locked); self.assertEqual(len(self.runs), 1)


if __name__ == '__main__':
    unittest.main()
