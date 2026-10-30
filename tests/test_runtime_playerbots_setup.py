"""Host process/journal fixtures only; no native C++ or MySQL qualification."""
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

from runtime import mysql_bootstrap as db, server_schema_setup as schema
from runtime import server_schema_baseline as baseline, server_update_setup as core
from runtime import server_playerbots_setup as setup, server_updater as updater, server_config as config
from runtime import provision_local_account as account, provision_local_realm as realm
from tests import test_runtime_server_update_setup as core_fixture
from tests import test_runtime_server_content as content_fixture, test_server_config as config_fixture


class Connection(core_fixture.Connection):
    """Bounded row/metadata emulator; it does not parse or execute source SQL."""
    def __init__(self, owner):
        super().__init__(owner)
        self.ledgers['playerbots'] = []
        self.columns = ['75706461746573\t1\t6E616D65\t766172636861722832303029\tNO\t1\t\t\t']
        self.indexes = ['75706461746573\t5052494D415259\t0\t1\t6E616D65\t0\t4254524545']
        self.locks = {}
        self.intent = None
        self.numchars = '0'

    def query(self, sql):
        if sql.startswith('SELECT GET_LOCK('):
            self.queries.append(sql); name = re.search("'([^']+)'", sql)[1]
            self.locks[name] = self.locks.get(name, 0) + 1
            self.locked = bool(self.locks.get('esteria-local-bootstrap')); return ['1']
        if sql.startswith('SELECT RELEASE_LOCK('):
            self.queries.append(sql); name = re.search("'([^']+)'", sql)[1]
            if not self.locks.get(name): return ['<NULL>']
            self.locks[name] -= 1
            if not self.locks[name]: del self.locks[name]
            self.locked = bool(self.locks.get('esteria-local-bootstrap')); return ['1']
        if sql.startswith('SELECT * FROM `acore_'):
            self.queries.append(sql); name = sql.split('`acore_', 1)[1].split('`', 1)[0]
            return list(self.ledgers[name])
        if sql.startswith('SELECT HEX(') and 'FROM acore_auth.account ORDER BY id' in sql:
            self.queries.append(sql); return ['private binary-safe account fixture'] if self.accounts else []
        if sql == 'SELECT * FROM acore_auth.realmcharacters ORDER BY realmid,acctid':
            self.queries.append(sql); return ['1\t7\t' + self.numchars]
        if sql == realm.ROW_SQL:
            self.queries.append(sql); return [realm.EXPECTED_ROW]
        if sql.startswith('SELECT id,username,LOWER(HEX(salt)),LOWER(HEX(verifier)) '):
            self.queries.append(sql)
            return ['7\t' + self.intent['username'] + '\t' + self.intent['saltHex'] + '\t' + self.intent['verifierHex']]
        if sql.startswith('SELECT numchars FROM acore_auth.realmcharacters '):
            self.queries.append(sql); return [self.numchars]
        if "WHERE TABLE_SCHEMA='acore_playerbots'" in sql:
            self.queries.append(sql)
            if 'information_schema.COLUMNS' in sql: return list(self.columns)
            if 'information_schema.STATISTICS' in sql: return list(self.indexes)
        return super().query(sql)


class RuntimePlayerbotsSetup(unittest.TestCase):
    def setUp(self):
        owner = core_fixture.RuntimeUpdaterSetup(); owner.setUp(); self.addCleanup(owner.doCleanups)
        self.owner, self.fixture, self.root, self.state = owner, owner.fixture, owner.root, owner.state
        source_templates = config_fixture.fixture(self.root)
        world = source_templates / 'src/server/apps/worldserver/worldserver.conf.dist'
        keys = ('Updates.AutoSetup Updates.EnableDatabases Updates.Redundancy Updates.AllowRehash '
                'Updates.ArchivedRedundancy Updates.CleanDeadRefMaxCount Database.Reconnect.Attempts '
                'Database.Reconnect.Seconds Logger.root').split()
        world.write_text(world.read_text() + '\nRealmID = 1\nExpansion = 2\n' +
                         '\n'.join(key + ' = 0' for key in keys) + '\n')
        bot = source_templates / 'modules/mod-playerbots/conf/playerbots.conf.dist'
        bot.write_text(bot.read_text() + '\nPlayerbots.Updates.EnableDatabases = 0\n'
                       'PlayerbotsDatabase.WorkerThreads = 1\nPlayerbotsDatabase.SynchThreads = 1\n')
        for name in (*config.MAIN_CONFIG_TEMPLATES, 'modules/mod-playerbots/conf/playerbots.conf.dist'):
            raw = (source_templates / name).read_bytes()
            self.fixture.payload['source/' + name] = raw
            self.fixture.manifest['files'][name] = content_fixture.source_identity(raw)
        self.fixture.manifest['modules'].append(dict(name='mod-playerbots',
            configTemplates=['modules/mod-playerbots/conf/playerbots.conf.dist'], notices=[], luaCandidates=[]))
        self.fixture.manifest['modules'].sort(key=lambda row: row['name'])
        self.fixture.manifest['enabledModules'] = [row['name'] for row in self.fixture.manifest['modules']]
        self.fixture.compiled['enabledModules'] = list(self.fixture.manifest['enabledModules'])
        self.fixture.compiled['configFiles'] = ['one.conf', 'playerbots.conf']
        bases, updates = [], []
        for name in ['updates', 'updates_include'] + ['fixture_' + str(index).zfill(2) for index in range(27)]:
            path = setup.ROOT + 'base/' + name + '.sql'; bases.append(path)
            raw = ('-- SYNTHETIC BASE, NEVER EXECUTED: ' + name + '\n').encode()
            self.fixture.payload['source/' + path] = raw
            self.fixture.manifest['files'][path] = content_fixture.source_identity(raw)
        for index in range(31):
            path = setup.ROOT + 'updates/fixture_' + str(index).zfill(2) + '.sql'
            raw = ('-- SYNTHETIC UPDATE, NEVER EXECUTED: ' + str(index) + '\n').encode()
            self.fixture.payload['source/' + path] = raw
            self.fixture.manifest['files'][path] = content_fixture.source_identity(raw)
            updates.append(dict(path=path, state='RELEASED', origin='base-updates_include'))
        self.fixture.manifest['databases']['playerbots'] = dict(base=sorted(bases), updateOrder=updates,
                                                              executionOrderQualified=True)
        self.fixture.write(); self.content = self.fixture.verify(); owner.content = self.content
        # The composed fixture originally created its core journal before PB
        # metadata existed. Recreate it through the actual product initializer
        # on a fresh row emulator, rather than fabricate a completion receipt.
        (self.state / schema.JOURNAL).unlink()
        self.connection = Connection(owner); owner.connection = self.connection
        schema.initialize(self.content, self.connection, self.state, '8.0.46', self.connection.apply_baseline)
        owner.plan = owner.prepare(); owner.run_updater()
        self.uuid, self.mysql = owner.uuid, owner.mysql
        self.profile = json.loads((Path(__file__).parents[1] / 'config/local-server.json').read_text())
        self.data = self.root / 'data'
        config.render_verified(self.content, self.state, self.data, self.mysql, profile=self.profile)
        bootstrap = db.read_receipt(self.state / 'database-bootstrap.json', '8.0.46')
        # A generated, private ready owner plus matching emulator row tests the
        # read-only ready-account gate. This is not SQL/account qualification.
        self.intent = account.new_intent(bootstrap) | dict(phase='ready', accountId=7)
        self.connection.intent = self.intent; self.connection.accounts = 1
        db.atomic_json(self.state / account.JOURNAL, self.intent)
        self.helper = self.root / 'host-playerbots-fixture'
        self.helper_receipt = self.root / 'fixture-helper-build.json'
        self.runs = []
        self.set_helper()

    def set_helper(self, *, count=52, exit_code=0):
        self.helper.write_text('#!' + str(Path(sys.executable).resolve()) + '\n' +
            'print("ESTERIA_PLAYERBOTS_DATABASE_REFERENCE_COMPLETE statements=' + str(count) +
            ' mysqlClientLibrary=host-fixture")\nraise SystemExit(' + str(exit_code) + ')\n')
        self.helper.chmod(0o700)
        # Deliberately pinned host provenance fixture. Actual native helper ELF,
        # build and SQL execution are separate CI gates, never claimed here.
        self.helper_document = dict(formatVersion=1, scope='source-built-playerbots-schema-helper',
            actualCompileSucceeded=True, actualDatabaseSourcesAndDefinitionVerified=True,
            databaseExecuted=False, elf=dict(machine='AArch64'), preparedStatementCountDeclared=52,
            originalBuild=self.content.compiled['serverBuild'], originalModules=self.content.receipt['compiledModules'],
            serverSource=self.content.manifest['source'], sourceLock=dict(bytes=2170, sha256=self.fixture.lock),
            executable=baseline.file_identity(self.helper))
        self.write_helper_receipt()

    def write_helper_receipt(self):
        raw = content_fixture.encoded(self.helper_document); self.helper_receipt.write_bytes(raw)
        self.helper_receipt_sha256 = hashlib.sha256(raw).hexdigest()
        self.plan = setup.prepare(self.content, self.helper, self.helper_receipt, self.helper_receipt_sha256, self.mysql)

    def runner(self, executable, configuration, log, **kwargs):
        journal = schema.private_journal(self.state / setup.JOURNAL)
        self.assertEqual(journal['phase'], 'in-flight')
        self.assertIs(journal['compiledPlayerbotsLoaderExecuted'], False)
        self.runs.append(configuration)
        result = self.real_runner(executable, configuration, log, **kwargs)
        self.connection.tables['playerbots'] = [Path(path).stem for path in
            self.content.manifest['databases']['playerbots']['base']]
        self.connection.ledgers['playerbots'] = [name + '\t' + digest + '\t' + state
            for name, (digest, state) in sorted(self.plan.expected.items())]
        return result

    def apply(self, **kwargs):
        self.real_runner = updater.run_importer
        with patch.object(updater, 'run_importer', side_effect=self.runner):
            return setup.apply(self.plan, self.connection, self.state, '8.0.46', profile=self.profile,
                data=self.data, expected_uuid=self.uuid, verify_service=kwargs.pop('verify_service', lambda: True), **kwargs)

    def verify(self, **kwargs):
        with db.state_lock(self.state), realm.config_lock(self.state), realm.named_locks(self.connection,
                ('esteria-local-bootstrap', 'esteria-local-realm', 'esteria-local-account')):
            return setup.verify_completed(self.content, self.connection, self.state, '8.0.46',
                expected_uuid=self.uuid, verify_service=lambda: True, **kwargs)

    def test_actual_host_child_observes_durable_intent_and_completed_repeat_is_read_only(self):
        baseline_bytes = (self.state / schema.JOURNAL).read_bytes(); core_bytes = (self.state / core.JOURNAL).read_bytes()
        account_bytes = (self.state / account.JOURNAL).read_bytes()
        first = self.apply()
        self.assertTrue(first['compiledPlayerbotsLoaderExecuted']); self.assertEqual(first['preparedStatementCount'], 52)
        self.assertFalse(first['playerbotsAiQualified']); self.assertFalse(first['worldserverExecuted'])
        self.assertEqual(len(self.runs), 1)
        private = (self.state / setup.JOURNAL).read_bytes()
        self.helper.unlink(); self.helper_receipt.unlink()
        before_queries = len(self.connection.queries)
        with patch.object(db, 'atomic_json', side_effect=AssertionError('read-only verifier wrote a journal')), \
                patch.object(schema, 'initialize', side_effect=AssertionError('verifier replayed baseline')), \
                patch.object(setup, 'run_loader', side_effect=AssertionError('verifier launched helper')):
            second = self.verify()
        self.assertTrue(all(query.startswith(('SELECT ', 'SHOW TABLES '))
                            for query in self.connection.queries[before_queries:]))
        self.assertFalse(second['compiledPlayerbotsLoaderExecuted']); self.assertTrue(second['preparedStatementsPreviouslyVerified'])
        self.assertEqual((self.state / setup.JOURNAL).read_bytes(), private)
        self.assertEqual((self.state / schema.JOURNAL).read_bytes(), baseline_bytes)
        self.assertEqual((self.state / core.JOURNAL).read_bytes(), core_bytes)
        self.assertEqual((self.state / account.JOURNAL).read_bytes(), account_bytes)
        for secret in (self.intent['password'], self.intent['username'], self.intent['saltHex'], self.intent['verifierHex']):
            self.assertNotIn(secret, json.dumps(second))
        self.assertFalse(self.connection.locks)
        repeated = self.apply(); self.assertFalse(repeated['compiledPlayerbotsLoaderExecuted']); self.assertEqual(len(self.runs), 1)

    def test_cancel_before_intent_does_nothing_but_cancel_after_intent_finishes_one_unit(self):
        with self.assertRaises(core.UpdateCancelled): self.apply(cancelled=lambda: True)
        self.assertFalse((self.state / setup.JOURNAL).exists()); self.assertFalse(self.runs)
        stopped = False
        def progress(event):
            nonlocal stopped
            if event['phase'] == 'playerbots-schema-intent-committed': stopped = True
        result = self.apply(progress=progress, cancelled=lambda: stopped)
        self.assertTrue(stopped); self.assertTrue(result['compiledPlayerbotsLoaderExecuted'])
        self.assertEqual(schema.private_journal(self.state / setup.JOURNAL)['phase'], 'complete')
        self.assertEqual(len(self.runs), 1)

    def test_failed_and_inflight_intents_are_preserved_without_replay(self):
        with patch.object(setup, 'run_loader', side_effect=RuntimeError('private fixture failure')):
            with self.assertRaises(RuntimeError): self.apply()
        path = self.state / setup.JOURNAL; failed = path.read_bytes()
        self.assertEqual(json.loads(failed)['phase'], 'failed')
        self.assertEqual(self.connection.tables['playerbots'], [])
        with self.assertRaises(db.BootstrapError): self.apply()
        self.assertEqual(path.read_bytes(), failed); self.assertFalse(self.runs)
        value = json.loads(failed); value['phase'] = 'in-flight'; db.atomic_json(path, value)
        before = path.read_bytes()
        with self.assertRaises(db.BootstrapError): self.apply()
        self.assertEqual(path.read_bytes(), before); self.assertFalse(self.runs)

    def test_nonempty_fourth_pool_cannot_bypass_private_execution_proof(self):
        self.connection.tables['playerbots'] = ['updates', 'updates_include']
        with self.assertRaises((db.BootstrapError, OSError)): self.apply()
        self.assertFalse(self.runs); self.assertFalse((self.state / setup.JOURNAL).exists())
        with self.assertRaisesRegex(ValueError, 'unregistered playerbots'):
            updater.schema_snapshot(self.connection, self.owner.plan.expected)

    def test_completed_journal_with_dropped_all_tables_or_nonprivate_mode_cannot_qualify(self):
        self.apply(); path = self.state / setup.JOURNAL; before = path.read_bytes()
        tables = list(self.connection.tables['playerbots']); self.connection.tables['playerbots'] = []
        with self.assertRaisesRegex(db.BootstrapError, 'source ledger is absent'): self.verify()
        self.assertEqual(path.read_bytes(), before)
        self.connection.tables['playerbots'] = tables; path.chmod(0o644)
        with self.assertRaisesRegex(db.BootstrapError, 'private file'): self.verify()
        self.assertEqual(path.read_bytes(), before); self.assertEqual(len(self.runs), 1)

    def test_live_columns_indexes_ledger_and_core_journal_changes_are_refused(self):
        self.apply(); path = self.state / setup.JOURNAL; before = path.read_bytes()
        for kind in ('columns', 'indexes', 'ledger', 'core-journal', 'core-tables'):
            columns, indexes = list(self.connection.columns), list(self.connection.indexes)
            ledger = list(self.connection.ledgers['playerbots']); tables = list(self.connection.tables['auth'])
            core_path = self.state / core.JOURNAL; core_bytes = core_path.read_bytes()
            if kind == 'columns': self.connection.columns.append('different column')
            elif kind == 'indexes': self.connection.indexes.append('different index')
            elif kind == 'ledger': self.connection.ledgers['playerbots'][0] += 'changed'
            elif kind == 'core-journal': core_path.write_bytes(core_bytes + b' ')
            else: self.connection.tables['auth'].append('unqualified_table')
            with self.subTest(kind=kind), self.assertRaises(db.BootstrapError): self.verify()
            self.assertEqual(path.read_bytes(), before); self.assertEqual(len(self.runs), 1)
            self.connection.columns, self.connection.indexes = columns, indexes
            self.connection.ledgers['playerbots'], self.connection.tables['auth'] = ledger, tables
            core_path.write_bytes(core_bytes)

    def test_pending_account_is_refused_and_completed_owner_journal_is_bound(self):
        account_path = self.state / account.JOURNAL
        ready = account_path.read_bytes()
        pending = dict(self.intent, phase='pending', accountId=None); db.atomic_json(account_path, pending)
        with self.assertRaisesRegex(db.BootstrapError, 'complete recovery'): self.apply()
        self.assertFalse(self.runs); self.assertFalse((self.state / setup.JOURNAL).exists())
        account_path.write_bytes(ready); self.apply()
        account_path.write_bytes(ready + b' ')
        with self.assertRaisesRegex(db.BootstrapError, 'account journal changed'): self.verify()

    def test_wrong_actual_completion_count_cannot_complete_or_replay(self):
        self.set_helper(count=51)
        with self.assertRaisesRegex(db.BootstrapError, 'completion missing'): self.apply()
        journal = schema.private_journal(self.state / setup.JOURNAL)
        self.assertEqual(journal['phase'], 'failed'); self.assertTrue(journal['compiledPlayerbotsLoaderExecuted'])
        self.assertEqual(len(self.runs), 1)
        with self.assertRaises(db.BootstrapError): self.apply()
        self.assertEqual(len(self.runs), 1)

    def test_source_helper_pin_and_service_changes_fail_before_launch(self):
        with self.assertRaisesRegex(db.BootstrapError, 'receipt digest differs'):
            setup.prepare(self.content, self.helper, self.helper_receipt, '0' * 64, self.mysql)
        self.helper_document['originalBuild'] = dict(bytes=1, sha256='0' * 64)
        with self.assertRaisesRegex(db.BootstrapError, 'source/build/module binding'):
            self.write_helper_receipt()
        self.assertFalse((self.state / setup.JOURNAL).exists()); self.assertFalse(self.runs)
        with self.assertRaisesRegex(db.BootstrapError, 'service identity changed'):
            self.apply(verify_service=lambda: False)
        self.assertFalse((self.state / setup.JOURNAL).exists()); self.assertFalse(self.runs)

    def test_real_outer_state_lease_survives_first_and_completed_calls(self):
        with db.state_lock(self.state) as lease:
            with patch.object(db, 'state_lock', side_effect=AssertionError('must reuse actual outer lease')):
                first = self.apply(state_lease=lease); second = self.apply(state_lease=lease)
            with self.assertRaisesRegex(db.BootstrapError, 'Another bootstrap operation'):
                with db.state_lock(self.state): self.fail('PB setup released outer state lock')
        self.assertTrue(first['compiledPlayerbotsLoaderExecuted']); self.assertFalse(second['compiledPlayerbotsLoaderExecuted'])
        self.assertEqual(len(self.runs), 1)


if __name__ == '__main__': unittest.main()
