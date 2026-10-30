import copy
import hashlib
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from runtime import mysql_bootstrap as db, provision_local_realm as realm, provision_local_account as account
from runtime import server_config, server_update_setup as updates
from tests import test_runtime_server_config as config_fixture
from tests.test_runtime_server_content import source_identity
from tests.test_local_account import Transaction


class OwnedConnection(Transaction):
    """Row/metadata fixture only; does not execute a SQL engine."""
    def __init__(self, fixture):
        super().__init__(fixture.intent)
        self.fixture = fixture
        self.realm_row = realm.EXPECTED_ROW
        self.locks = {}
        self.busy = None

    def query(self, sql):
        if sql.startswith('SELECT GET_LOCK('):
            self.calls.append(sql); name = re.search("'([^']+)'", sql)[1]
            if name == self.busy: return ['0']
            self.locks[name] = self.locks.get(name, 0) + 1; return ['1']
        if sql.startswith('SELECT RELEASE_LOCK('):
            self.calls.append(sql); name = re.search("'([^']+)'", sql)[1]
            if not self.locks.get(name): return ['<NULL>']
            self.locks[name] -= 1
            if not self.locks[name]: del self.locks[name]
            return ['1']
        if sql == "SELECT IS_USED_LOCK('esteria-local-bootstrap') = CONNECTION_ID()":
            self.calls.append(sql); return ['1'] if self.locks.get('esteria-local-bootstrap') else ['0']
        if sql == 'SELECT VERSION(), @@version_comment, @@server_uuid, @@datadir':
            self.calls.append(sql)
            return ['8.0.46\tMySQL Community\t' + self.fixture.uuid + '\t' + str(self.fixture.state / 'database')]
        if sql == 'SELECT @@port, @@bind_address': self.calls.append(sql); return ['13306\t127.0.0.1']
        if sql == 'SELECT CURRENT_USER()': self.calls.append(sql); return ['esteria@127.0.0.1']
        if sql.startswith(realm.ROW_SQL): self.calls.append(sql); return [self.realm_row] if self.realm_row else []
        if sql.startswith(('UPDATE `acore_auth`.`realmlist`', 'INSERT INTO `acore_auth`.`realmlist`')):
            self.calls.append(sql); self.realm_row = realm.EXPECTED_ROW; return []
        if 'information_schema' in sql:
            self.calls.append(sql)
            table = re.search("TABLE_NAME='([^']+)'", sql)
            table = table[1] if table else None
            if 'FROM information_schema.TRIGGERS' in sql or 'REFERENTIAL_CONSTRAINTS' in sql: return ['0']
            if table == 'realmlist':
                if sql.startswith('SELECT ENGINE FROM'): return ['InnoDB']
                if 'information_schema.COLUMNS' in sql: return ['\t'.join(row) for row in realm.COLUMNS]
                if 'information_schema.STATISTICS' in sql: return ['PRIMARY\t0\t1\tid', 'idx_name\t0\t1\tname']
            if table in account.COLUMNS:
                if sql.startswith('SELECT ENGINE,TABLE_COLLATION'): return ['InnoDB\tutf8mb4_unicode_ci']
                if 'information_schema.COLUMNS' in sql:
                    return ['\t'.join(row) + '\t' + ('utf8mb4_unicode_ci' if row[1].startswith('varchar(') else '<NULL>')
                            for row in account.COLUMNS[table]]
                if 'information_schema.STATISTICS' in sql: return [row + '\t<NULL>' for row in account.INDEXES[table]]
            return []
        return super().query(sql)


class PortableLocalProvisioning(unittest.TestCase):
    def setUp(self):
        configuration = config_fixture.RuntimeServerConfiguration(); configuration.setUp(); self.addCleanup(configuration.doCleanups)
        self.configuration = configuration; self.fixture = configuration.fixture
        # Explicit synthetic source SQL is metadata-verified, never executed.
        schemas = {}
        for name in ('realmlist', 'account', 'realmcharacters'):
            relative = 'data/sql/base/db_auth/' + name + '.sql'
            raw = ('-- SYNTHETIC SOURCE FIXTURE, NEVER EXECUTED: ' + name + '\n').encode()
            self.fixture.payload['source/' + relative] = raw
            self.fixture.manifest['files'][relative] = source_identity(raw)
            if relative not in self.fixture.manifest['databases']['auth']['base']:
                self.fixture.manifest['databases']['auth']['base'].append(relative)
            schemas[name] = hashlib.sha256(raw).hexdigest()
        self.fixture.manifest['databases']['auth']['base'].sort()
        world = 'src/server/apps/worldserver/worldserver.conf.dist'
        raw = self.fixture.payload['source/' + world]
        if not re.search(rb'^\s*Expansion\s*=', raw, re.M): raw += b'\nExpansion = 2\n'
        self.fixture.payload['source/' + world] = raw
        self.fixture.manifest['files'][world] = source_identity(raw)
        self.fixture.write(); self.content = self.fixture.verify()
        for target, name in ((patch.object(realm, 'SERVER_REVISION', self.fixture.source['commit']), 'source'),
                             (patch.object(realm, 'SCHEMA_SHA256', schemas['realmlist']), 'realm'),
                             (patch.object(account, 'ACCOUNT_SCHEMA_SHA256', schemas['account']), 'account'),
                             (patch.object(account, 'TRACKER_SCHEMA_SHA256', schemas['realmcharacters']), 'tracker')):
            target.start(); self.addCleanup(target.stop)
        self.state = configuration.state; self.profile = configuration.profile
        server_config.render_verified(self.content, self.state, configuration.data, configuration.mysql, profile=self.profile)
        (self.state / 'accounts/database-root-secret').write_text('b' * 64 + '\n')
        self.uuid = '01234567-89ab-4cde-8fab-0123456789ab'
        (self.state / 'database/auto.cnf').write_text('[auto]\nserver-uuid=' + self.uuid + '\n')
        self.receipt = dict(format=1, engine='mysql', version='8.0.46', uuid=self.uuid,
            datadir=str(self.state / 'database'), databases=list(db.DATABASES), application_schemas_populated=False)
        db.atomic_json(self.state / 'database-bootstrap.json', self.receipt)
        db.atomic_json(self.state / updates.JOURNAL, dict(phase='complete', testFixture=True))
        self.intent = account.new_intent(self.receipt); self.connection = OwnedConnection(self)
        self.gate_calls = 0; self.service_calls = 0
        self.gate_patch = patch.object(updates, 'verify_completed_update', side_effect=self.completed_gate)
        self.gate_patch.start(); self.addCleanup(self.gate_patch.stop)

    def completed_gate(self, content, connection, state, version, **kwargs):
        self.assertIs(content, self.content); self.assertIs(connection, self.connection)
        self.assertEqual(state, self.state); self.assertEqual(version, '8.0.46')
        self.assertEqual(kwargs['expected_uuid'], self.uuid)
        self.assertTrue(connection.locks.get('esteria-local-bootstrap'))
        self.gate_calls += 1
        return dict(compiledUpdaterCompleted=True, scope=updates.SCOPE, gameplayQualified=False)

    def service(self): self.service_calls += 1; return True

    def run_realm(self, **kwargs):
        return realm.provision_verified(self.content, self.connection, self.state, '8.0.46', profile=kwargs.pop('profile', self.profile),
            data=self.configuration.data, mysql=self.configuration.mysql, expected_uuid=kwargs.pop('expected_uuid', self.uuid), verify_service=kwargs.pop('verify_service', self.service), **kwargs)

    def run_account(self, **kwargs):
        with patch.object(account, 'new_intent', return_value=self.intent):
            return account.provision_verified(self.content, self.connection, self.state, '8.0.46', profile=self.profile,
                data=self.configuration.data, mysql=self.configuration.mysql, expected_uuid=self.uuid, verify_service=self.service, **kwargs)

    def writes(self): return [sql for sql in self.connection.calls if sql.startswith(('INSERT', 'UPDATE', 'REPLACE', 'DELETE'))]

    def test_runtime_apis_never_read_root_and_preserve_private_credentials_on_repeat(self):
        secret = (self.state / 'accounts/database-secret').read_bytes()
        self.connection.realm_row = '1\t203.0.113.4\t127.0.0.1\t255.255.255.0\t9001\t99999'
        with patch.object(realm, 'ROOT', self.state / 'nonexistent-host-checkout'):
            first = self.run_realm(); self.assertEqual(first['operation'], 'reasserted-local-row')
            result = self.run_account(); self.assertEqual(result['operation'], 'created-owned-account')
            intent = (self.state / account.JOURNAL).read_bytes()
            self.connection.calls.clear()
            self.assertEqual(self.run_realm(verify_only=True)['operation'], 'verified')
            self.assertEqual(self.run_account(verify_only=True)['operation'], 'verified-owned-account')
        self.assertEqual(self.writes(), []); self.assertEqual(self.connection.locks, {})
        self.assertEqual((self.state / account.JOURNAL).read_bytes(), intent)
        self.assertEqual((self.state / 'accounts/database-secret').read_bytes(), secret)
        for report in (first, result):
            self.assertFalse(report['gameplayQualified']); self.assertFalse(report['androidRuntimeQualified'])
            for private in ('username', 'password', 'saltHex', 'verifierHex'): self.assertNotIn(self.intent[private], json.dumps(report))
        self.assertGreaterEqual(self.gate_calls, 4); self.assertGreaterEqual(self.service_calls, 8)

    def test_profile_or_instance_rejected_before_mutation(self):
        profiles = [dict(self.profile, world_port=9000), dict(self.profile, database_port=True)]
        bots = copy.deepcopy(self.profile); bots['playerbots']['AiPlayerbot.MaxAddedBots'] = 40; profiles.append(bots)
        for profile in profiles:
            with self.subTest(profile=profile), self.assertRaises((ValueError, db.BootstrapError)): self.run_realm(profile=profile)
        with self.assertRaises(db.BootstrapError): self.run_realm(expected_uuid='11234567-89ab-4cde-8fab-0123456789ab')
        with self.assertRaises(db.BootstrapError): self.run_realm(verify_service=None)
        self.assertEqual(self.writes(), []); self.assertEqual(self.gate_calls, 0)
        self.assertFalse((self.state / account.JOURNAL).exists())

    def test_completed_updater_is_required_before_any_row_mutation(self):
        self.gate_patch.stop()
        with self.assertRaises((db.BootstrapError, KeyError, ValueError, OSError)): self.run_realm()
        self.assertEqual(self.writes(), []); self.assertEqual(self.connection.locks, {})
        self.assertFalse((self.state / 'realm-loopback.json').exists())

    def test_real_caller_state_lease_is_reused_preserved_and_rejected_after_release(self):
        with db.state_lock(self.state) as lease:
            self.assertEqual(self.run_realm(state_lease=lease)['operation'], 'already-local')
            self.assertEqual(self.run_account(state_lease=lease)['operation'], 'created-owned-account')
            self.assertEqual(self.connection.locks, {})
            with self.assertRaisesRegex(db.BootstrapError, 'Another bootstrap operation'):
                with db.state_lock(self.state): pass
        self.connection.calls.clear()
        for invalid in (lease, True, object()):
            with self.subTest(lease=type(invalid).__name__), self.assertRaisesRegex(db.BootstrapError, 'State lease'):
                self.run_realm(state_lease=invalid)
        self.assertEqual(self.writes(), [])

    def test_partial_lock_acquisition_releases_only_its_own_counts(self):
        self.connection.busy = 'esteria-local-realm'
        self.connection.locks['esteria-local-bootstrap'] = 1  # Caller already owns one recursive acquisition.
        with self.assertRaisesRegex(db.BootstrapError, 'Another operation'): self.run_realm()
        self.assertEqual(self.connection.locks, {'esteria-local-bootstrap': 1})
        self.assertEqual(self.writes(), []); self.assertEqual(self.gate_calls, 0)

    def test_failed_completed_gate_releases_all_locks_without_new_account_intent(self):
        self.gate_patch.stop()
        with patch.object(updates, 'verify_completed_update', side_effect=db.BootstrapError('fixture incomplete updater')):
            with self.assertRaises(db.BootstrapError): self.run_account()
        self.assertEqual(self.connection.locks, {}); self.assertEqual(self.writes(), [])
        self.assertFalse((self.state / account.JOURNAL).exists())

    def test_source_or_config_tamper_retains_old_activation_and_private_files(self):
        current = self.state / 'config/current'; pointer = current.readlink()
        source = self.content.source / 'data/sql/base/db_auth/realmlist.sql'; original = source.read_bytes()
        source.write_bytes(original + b'changed')
        with self.assertRaises((db.BootstrapError, ValueError)): self.run_realm()
        source.write_bytes(original)
        world = current / 'worldserver.conf'; before = world.read_bytes(); world.write_bytes(before + b'Changed = 1\n')
        with self.assertRaisesRegex(db.BootstrapError, 'generation has changed'): self.run_realm()
        self.assertEqual(current.readlink(), pointer); self.assertEqual(world.read_bytes(), before + b'Changed = 1\n')
        self.assertEqual(self.writes(), []); self.assertEqual(self.connection.locks, {})

    def test_valid_generation_hash_with_wrong_module_source_binding_is_refused(self):
        current = self.state / 'config/current'
        source = current.resolve()
        files = {path.relative_to(source).as_posix(): path.read_text() for path in source.rglob('*') if path.is_file()}
        proof = json.loads(files['module-configuration.json']); proof['compiledSelectionSha256'] = '0' * 64
        files['module-configuration.json'] = json.dumps(proof, sort_keys=True, indent=2) + '\n'
        digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        replacement = source.parent / digest; replacement.mkdir()
        for name, text in files.items():
            path = replacement / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        current.unlink(); current.symlink_to(Path('generations') / digest)
        with self.assertRaisesRegex(db.BootstrapError, 'differs from verified source and local policy'): self.run_realm()
        self.assertEqual(current.readlink(), Path('generations') / digest)
        self.assertEqual(self.writes(), []); self.assertEqual(self.connection.locks, {})

    def test_rehashed_remote_admin_or_module_policy_changes_fail_with_original_proof(self):
        current = self.state / 'config/current'; original_pointer = current.readlink(); source = current.resolve()
        original = {path.relative_to(source).as_posix(): path.read_text() for path in source.rglob('*') if path.is_file()}
        for changed in ('module', 'Ra.Enable', 'SOAP.Enabled'):
            files = dict(original)
            if changed == 'module': files['modules/parity_14.conf'] += '\nChanged = 1\n'
            else:
                files['worldserver.conf'], count = re.subn(r'(?m)^' + re.escape(changed) + r' = 0$', changed + ' = 1', files['worldserver.conf'])
                self.assertEqual(count, 1)
            digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
            replacement = source.parent / digest; replacement.mkdir()
            for name, text in files.items():
                path = replacement / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
            current.unlink(); current.symlink_to(Path('generations') / digest)
            with self.subTest(change=changed), self.assertRaisesRegex(db.BootstrapError, 'differs from verified source and local policy'):
                self.run_realm()
            self.assertEqual(self.writes(), []); self.assertEqual(self.connection.locks, {})
            current.unlink(); current.symlink_to(original_pointer)

    def test_private_credential_change_during_provisioning_is_not_repaired(self):
        original = self.connection.query
        secret = self.state / 'accounts/database-secret'
        def query(sql):
            result = original(sql)
            if sql == 'COMMIT': secret.write_text('c' * 64 + '\n')
            return result
        self.connection.query = query
        with self.assertRaisesRegex(db.BootstrapError, 'credentials or configuration changed'): self.run_realm()
        self.assertEqual(secret.read_text(), 'c' * 64 + '\n')
        self.assertEqual(self.connection.locks, {})
        self.assertFalse((self.state / 'realm-loopback.json').exists())

    def test_account_verify_never_adopts_or_recreates_completed_missing_account(self):
        self.run_account(); before = (self.state / account.JOURNAL).read_bytes()
        self.connection.present = False; self.connection.calls.clear()
        with self.assertRaisesRegex(db.BootstrapError, 'refusing recreation'): self.run_account()
        self.assertEqual(self.writes(), []); self.assertEqual(self.connection.locks, {})
        self.assertEqual((self.state / account.JOURNAL).read_bytes(), before)


if __name__ == '__main__': unittest.main()
