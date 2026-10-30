import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from runtime import android_server_schema_setup as setup, mysql_bootstrap as db, mysql_service as service
from runtime import server_schema_setup as schema


class AndroidSchemaEntrypoint(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.session = self.root / 'operation'; self.session.mkdir(mode=0o700)

    def pin(self):
        return dict(formatVersion=1, scope='android-owned-server-schema-selection',
                    source={'commit': 'a' * 40}, sourceLockSha256='b' * 64,
                    contentReceipt=dict(bytes=100, sha256='c' * 64),
                    compiledModules=dict(bytes=200, sha256='d' * 64))

    def test_selection_rejects_extra_paths_duplicates_and_unbounded_pins(self):
        path = self.session / 'selection.json'
        value = self.pin(); path.write_text(json.dumps(value))
        self.assertEqual(setup.selection(path), value)
        for changed in (dict(value, contentRoot='/tmp/unowned'), dict(value, formatVersion=True),
                        dict(value, compiledModules=dict(bytes=20 << 20, sha256='a' * 64))):
            path.write_text(json.dumps(changed))
            with self.subTest(value=changed), self.assertRaises(service.ServiceError): setup.selection(path)
        path.write_text('{"formatVersion":1,"formatVersion":1}')
        with self.assertRaisesRegex(service.ServiceError, 'duplicate'): setup.selection(path)

    def mysql(self):
        executable = self.root / 'mysql-fixture'
        executable.write_text('''#!/usr/bin/python3
import hashlib,json,os,sys
raw=sys.stdin.buffer.readline()
if raw == b'FAIL\\n':
    print('private SQL credential fragment',file=sys.stderr);sys.exit(3)
if raw == b'EXCESS\\n':
    sys.stdout.buffer.write(b'x'*(2*1024*1024));sys.stdout.buffer.flush();sys.exit(0)
digest=hashlib.sha256(raw); count=len(raw)
while True:
    block=sys.stdin.buffer.read(65536)
    if not block:break
    count+=len(block);digest.update(block)
print(json.dumps(dict(bytes=count,sha256=digest.hexdigest(),arguments=sys.argv[1:],login=os.environ.get('MYSQL_TEST_LOGIN_FILE'),hasPassword='MYSQL_PWD' in os.environ)))
''')
        executable.chmod(0o700)
        return executable

    def test_actual_child_streams_sql_without_secret_in_argv_or_environment(self):
        mysql = self.mysql(); sql = self.root / 'large.sql'
        with sql.open('wb') as stream:
            for _ in range(128): stream.write(b'-- streamed source data\n' * 1024)
        options = self.root / 'private.cnf'; options.write_text('[client]\nuser=esteria\npassword=private-test-secret\n'); options.chmod(0o600)
        os.environ['MYSQL_PWD'] = 'inherited-private-test-secret'
        try: setup.apply_file(mysql, options, 'world', sql, self.session, 0)
        finally: del os.environ['MYSQL_PWD']
        log = self.session / 'sql-0-private.log'
        proof = json.loads(log.read_bytes())
        self.assertEqual(proof['bytes'], sql.stat().st_size)
        self.assertEqual(proof['sha256'], hashlib.sha256(sql.read_bytes()).hexdigest())
        self.assertIn('--defaults-file=' + str(options), proof['arguments'])
        self.assertEqual(proof['arguments'][-1], 'acore_world')
        self.assertFalse(proof['hasPassword']); self.assertEqual(proof['login'], os.devnull)
        self.assertNotIn('private-test-secret', str(proof))
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_sql_failure_preserves_private_diagnostics_and_never_reuses_log(self):
        mysql = self.mysql(); sql = self.root / 'source.sql'; sql.write_bytes(b'FAIL\n')
        options = self.root / 'private.cnf'; options.write_text('[client]\n')
        with self.assertRaisesRegex(service.ServiceError, 'partial state'): setup.apply_file(mysql, options, 'auth', sql, self.session, 0)
        private = self.session / 'sql-0-private.log'; before = private.read_bytes()
        self.assertIn(b'private SQL credential fragment', before)
        with self.assertRaises(FileExistsError): setup.apply_file(mysql, options, 'auth', sql, self.session, 0)
        self.assertEqual(private.read_bytes(), before)

    def test_real_child_diagnostic_growth_is_bounded(self):
        mysql = self.mysql(); sql = self.root / 'source.sql'; sql.write_bytes(b'EXCESS\n')
        options = self.root / 'private.cnf'; options.write_text('[client]\n')
        with self.assertRaises(service.ServiceError): setup.apply_file(mysql, options, 'characters', sql, self.session, 0)
        self.assertLessEqual((self.session / 'sql-0-private.log').stat().st_size, setup.MAX_LOG)

    def test_cancel_before_work_creates_no_process_or_private_log(self):
        state = self.root / 'state'; state.mkdir()
        service_session = self.root / 'service'; service_session.mkdir()
        with self.assertRaises(schema.SchemaCancelled):
            setup.run(state, self.session, self.root / 'content', self.root / 'receipt', self.root / 'compiled',
                service_session, self.root / 'nonexistent', '8.0.46', 'a' * 32, 'b' * 32,
                '01234567-89ab-4cde-8fab-0123456789ab', interrupted=lambda: True)
        self.assertEqual(list(self.session.iterdir()), [])

    def test_linked_or_unknown_database_source_is_refused_before_process(self):
        sql = self.root / 'source.sql'; sql.write_bytes(b'SELECT 1;\n')
        linked = self.root / 'linked.sql'; linked.symlink_to(sql)
        for database, path in [('mysql', sql), ('world', linked)]:
            with self.subTest(database=database), self.assertRaises((service.ServiceError, db.BootstrapError, OSError)):
                setup.apply_file(self.root / 'nonexistent', self.root / 'options', database, path, self.session, 0)
        self.assertEqual(list(self.session.iterdir()), [])

    def test_wrong_live_service_identity_fails_before_any_sql(self):
        state = self.root / 'state'; state.mkdir()
        service_session = self.root / 'mysql-service'; service_session.mkdir()
        (service_session / 'ready.json').write_text(json.dumps(dict(formatVersion=1, scope='owned-local-mysql-live-service',
            operationId='a' * 32, uuid='01234567-89ab-4cde-8fab-0123456789ab', version='8.0.46',
            datadir=str(state / 'database'), bindAddress='127.0.0.1', port=13306, databases=list(db.DATABASES),
            liveSqlAuthenticated=True, ownedEngineIdentityVerified=True,
            applicationSchemaUpdatesQualified=False, gameplayQualified=False)))
        class NoConnection:
            def query(self, sql): raise AssertionError('wrong instance must not execute SQL')
        with self.assertRaisesRegex(service.ServiceError, 'receipt differs'):
            setup.live_service(NoConnection(), state, service_session, '8.0.46', 'a' * 32,
                               '11234567-89ab-4cde-8fab-0123456789ab')

    def test_receipt_reader_refuses_link_and_nonregular_input(self):
        original = self.root / 'source.json'; original.write_text('{}')
        path = self.session / 'selection.json'; path.symlink_to(original)
        with self.assertRaises(OSError): setup.read_json(path, 1024)
        path.unlink(); path.mkdir()
        with self.assertRaises((OSError, service.ServiceError)): setup.read_json(path, 1024)


if __name__ == '__main__': unittest.main()
