"""Guard checks; optional isolated MySQL fixture never targets a user instance."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime import mysql_bootstrap as db
from runtime import provision_local_realm as realm
from tools.render_server_config import render
from tests.test_server_config import fixture

FIXTURE = Path(__file__).parent / 'fixtures/realmlist-f35f04d.sql'
FIXTURE_SHA256 = 'e3743af73bd7cf4b75f2cd49a0269a31a5fc842cd78682f58ea0c4021d2d191f'


def rendered(root, mysql=Path('/usr/bin/mysql')):
    server = fixture(root)
    world = server / 'src/server/apps/worldserver/worldserver.conf.dist'
    with world.open('a') as output:
        output.write('\nRealmID = 1\n')
    state = root / 'state'
    render(server, state, root / 'data', root / 'sql', mysql)
    return state


def publish_config(state, change):
    current = state / 'config/current'
    files = {name: (current / name).read_text() for name in realm.CONFIG_FILES}
    change(files)
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    target = state / 'config/generations' / digest
    target.mkdir()
    for name, text in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    current.unlink()
    current.symlink_to('generations/' + digest)
    return digest


class RealmGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = rendered(self.root)
        self.secret = db.read_secret(self.state / 'accounts/database-secret')

    def test_intact_configuration_has_exact_local_endpoints(self):
        generation = realm.active_config(self.state, self.secret)
        self.assertEqual(generation, (self.state / 'config/current').resolve().name)
        for key, old, new in (('worldserver.conf', 'RealmID = 1', 'RealmID = 2'),
                              ('authserver.conf', 'RealmServerPort = 3724', 'RealmServerPort = 9000')):
            with self.subTest(key=key):
                original = os.readlink(self.state / 'config/current')
                publish_config(self.state, lambda files: files.update({key: files[key].replace(old, new)}))
                with self.assertRaises(db.BootstrapError):
                    realm.active_config(self.state, self.secret)
                (self.state / 'config/current').unlink()
                (self.state / 'config/current').symlink_to(original)

    def test_changed_generation_duplicate_keys_and_escaping_pointer_fail(self):
        current = self.state / 'config/current'
        with (current / 'worldserver.conf').open('a') as output:
            output.write('\nWorldServerPort = 9000\n')
        with self.assertRaisesRegex(db.BootstrapError, 'generation has changed'):
            realm.active_config(self.state, self.secret)
        with self.assertRaisesRegex(db.BootstrapError, 'Duplicate'):
            realm.settings('RealmID = 1\nRealmID = 2', ('RealmID',))
        current.unlink()
        current.symlink_to('../../outside')
        with self.assertRaisesRegex(db.BootstrapError, 'Invalid active'):
            realm.active_config(self.state, self.secret)

    def test_missing_ownership_receipt_never_starts_sql_client(self):
        with patch.object(db, 'Mysql', side_effect=AssertionError('must not connect')):
            with self.assertRaises(FileNotFoundError):
                realm.provision(Path('/usr/bin/mysql'), self.state, '8.0.44')

    def test_configuration_lock_conflicts_are_visible(self):
        with realm.config_lock(self.state):
            with self.assertRaisesRegex(db.BootstrapError, 'rendering is in progress'):
                with realm.config_lock(self.state):
                    self.fail('conflicting lock acquired')

    def test_schema_missing_or_drift_rejects_before_row_operations(self):
        class Connection:
            def __init__(self, responses):
                self.responses = iter(responses)
                self.calls = []
            def query(self, sql):
                self.calls.append(sql)
                return next(self.responses)
        for responses in ([[]], [['InnoDB'], []],
                          [['InnoDB'], ['\t'.join(c) for c in realm.COLUMNS], []],
                          [['InnoDB'], ['\t'.join(c) for c in realm.COLUMNS],
                           ['PRIMARY\t0\t1\tid', 'idx_name\t0\t1\tname'], ['1']]):
            connection = Connection(responses)
            with self.subTest(responses=len(responses)), self.assertRaises(db.BootstrapError):
                realm.check_schema(connection)
            self.assertTrue(all(sql.startswith('SELECT ') for sql in connection.calls))

    def test_verify_only_never_repairs_or_commits_wrong_endpoint(self):
        calls = []
        class Connection:
            def query(self, sql):
                calls.append(sql)
                return ['1\t203.0.113.4\t127.0.0.1\t255.255.255.0\t8085\t12340'] if 'FOR UPDATE' in sql else []
        with self.assertRaisesRegex(db.BootstrapError, 'endpoint changed'):
            realm.configure_row(Connection(), verify_only=True)
        self.assertEqual(calls[-1], 'ROLLBACK')
        self.assertFalse(any(sql.startswith(('INSERT', 'UPDATE', 'REPLACE', 'DELETE', 'COMMIT')) for sql in calls))

    def test_fixture_is_source_exact_create_only(self):
        raw = FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), FIXTURE_SHA256)
        text = raw.decode()
        self.assertIn(realm.SERVER_REVISION, text)
        self.assertIn(realm.SCHEMA_SHA256, text)
        statements = '\n'.join(line for line in text.splitlines() if not line.startswith('--'))
        self.assertTrue(statements.startswith('CREATE TABLE `realmlist`'))
        self.assertNotIn('DROP TABLE', statements)
        self.assertNotIn('INSERT INTO', statements)


@unittest.skipUnless(os.environ.get('ESTERIA_REALM_INTEGRATION') == '1',
                     'requires explicit disposable real MySQL 8 realm fixture')
class RealMysqlRealm(unittest.TestCase):
    def test_local_reassertion_identity_guards_and_other_data_preservation(self):
        executable = shutil.which('mysql')
        self.assertIsNotNone(executable)
        mysql = Path(executable)
        admin = db.private_path(Path(os.environ['ESTERIA_MYSQL_ADMIN_OPTIONS']))
        version = os.environ['ESTERIA_MYSQL_VERSION']
        deadline = time.monotonic() + 180
        while True:
            try:
                with db.Mysql(mysql, admin) as connection:
                    db.identity(connection, version)
                break
            except db.BootstrapError:
                if time.monotonic() >= deadline:
                    self.fail('dedicated MySQL realm fixture failed authentication readiness')
                time.sleep(1)
        with tempfile.TemporaryDirectory(prefix='esteria-realm-test-') as name:
            state = rendered(Path(name), mysql)
            with db.state_lock(state):
                db.provision(mysql, state, version, admin)
            with self.assertRaisesRegex(db.BootstrapError, 'table must be loaded'):
                realm.provision(mysql, state, version)
            with db.Mysql(mysql, admin) as connection:
                schema = FIXTURE.read_text()
                self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), FIXTURE_SHA256)
                connection.query('USE acore_auth;\n' + schema)
                first = realm.provision(mysql, state, version)
                self.assertEqual(first['operation'], 'inserted-local-row')
                self.assertFalse(first['serverStarted'])
                self.assertFalse(first['gameSchemaSetQualified'])
                connection.query("UPDATE acore_auth.realmlist SET name='Custom local label',icon=4,flag=2,timezone=8,"
                                 "allowedSecurityLevel=1,population=0.5,address='203.0.113.4',"
                                 "localAddress='198.51.100.8',port=9001,gamebuild=99999 WHERE id=1")
                connection.query("INSERT INTO acore_auth.realmlist (id,name,address,port) "
                                 "VALUES(2,'Other realm','203.0.113.9',9002)")
                connection.query('CREATE TABLE acore_characters.realm_persistence_probe '
                                 '(id INT PRIMARY KEY,value VARCHAR(32))')
                connection.query("INSERT INTO acore_characters.realm_persistence_probe VALUES(1,'preserve-character')")
                preserved_sql = 'SELECT name,icon,flag,timezone,allowedSecurityLevel,population FROM acore_auth.realmlist WHERE id=1'
                other_sql = 'SELECT * FROM acore_auth.realmlist WHERE id=2'
                before, other = connection.query(preserved_sql), connection.query(other_sql)
                with self.assertRaisesRegex(db.BootstrapError, 'endpoint changed'):
                    realm.provision(mysql, state, version, verify_only=True)
                self.assertEqual(connection.query('SELECT address FROM acore_auth.realmlist WHERE id=1'), ['203.0.113.4'])
                repaired = realm.provision(mysql, state, version)
                self.assertEqual(repaired['operation'], 'reasserted-local-row')
                self.assertEqual(connection.query(realm.ROW_SQL), [realm.EXPECTED_ROW])
                self.assertEqual(connection.query(preserved_sql), before)
                self.assertEqual(connection.query(other_sql), other)
                self.assertEqual(connection.query('SELECT value FROM acore_characters.realm_persistence_probe'), ['preserve-character'])
                self.assertEqual(realm.provision(mysql, state, version)['operation'], 'already-local')
                self.assertEqual(realm.provision(mysql, state, version, verify_only=True)['operation'], 'verified')
                connection.query("SELECT GET_LOCK('esteria-local-realm',0)")
                with self.assertRaisesRegex(db.BootstrapError, 'Another operation'):
                    realm.provision(mysql, state, version)
                connection.query("SELECT RELEASE_LOCK('esteria-local-realm')")
                receipt_path = state / 'database-bootstrap.json'
                original_receipt = json.loads(receipt_path.read_text())
                db.atomic_json(receipt_path, original_receipt | {'uuid': '00000000-0000-0000-0000-000000000000'})
                with self.assertRaisesRegex(db.BootstrapError, 'receipt mismatch for uuid'):
                    realm.provision(mysql, state, version)
                db.atomic_json(receipt_path, original_receipt)
                with self.assertRaisesRegex(db.BootstrapError, 'receipt mismatch for version'):
                    realm.provision(mysql, state, '8.99.99')
                secret_path = state / 'accounts/database-secret'
                original_secret = secret_path.read_text()
                secret_path.write_text('b' * 64 + '\n')
                with self.assertRaises(db.BootstrapError):
                    realm.provision(mysql, state, version)
                secret_path.write_text(original_secret)
                connection.query('ALTER TABLE acore_auth.realmlist ADD unexpected INT')
                with self.assertRaisesRegex(db.BootstrapError, 'Unexpected realmlist schema'):
                    realm.provision(mysql, state, version)
                connection.query('ALTER TABLE acore_auth.realmlist DROP COLUMN unexpected')
                # Disposable fixture only: a name collision must fail without
                # UPSERT touching another row or recreating unrelated state.
                connection.query('DELETE FROM acore_auth.realmlist WHERE id=1')
                connection.query("UPDATE acore_auth.realmlist SET name='Esteria' WHERE id=2")
                with self.assertRaises(db.BootstrapError):
                    realm.provision(mysql, state, version)
                self.assertEqual(connection.query('SELECT COUNT(*) FROM acore_auth.realmlist WHERE id=1'), ['0'])
                self.assertEqual(connection.query('SELECT name,address,port FROM acore_auth.realmlist WHERE id=2'),
                                 ['Esteria\t203.0.113.9\t9002'])
                connection.query("UPDATE acore_auth.realmlist SET name='Other realm' WHERE id=2")
                self.assertEqual(realm.provision(mysql, state, version)['operation'], 'inserted-local-row')
                self.assertEqual(connection.query('SELECT value FROM acore_characters.realm_persistence_probe'), ['preserve-character'])


if __name__ == '__main__':
    unittest.main()
