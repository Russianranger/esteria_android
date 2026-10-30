"""Service guards locally; exact MySQL engine/lifecycle only in an isolated CI fixture."""
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from runtime import mysql_service as service
from runtime import mysql_bootstrap as db
from tools.owned_process_group import OwnedGroup

ROOT = Path(__file__).resolve().parents[1]
VERSION = '8.0.46-fixture'
UUID = 'f28dc207-e269-11ed-bc2a-0242ac120002'


class ServiceGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='est-service-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'; self.state.mkdir()
        self.session = self.root / 'session'; self.session.mkdir()

    def identity(self):
        (self.state / 'database').mkdir()
        (self.state / 'accounts').mkdir()
        (self.state / 'database/auto.cnf').write_text('[auto]\nserver-uuid=' + UUID + '\n')
        secret = self.state / 'accounts/database-secret'; secret.write_text('a' * 64 + '\n'); secret.chmod(0o600)
        expected = dict(format=db.FORMAT, engine='mysql', version=VERSION, uuid=UUID,
                        datadir=str(self.state / 'database'), databases=list(db.DATABASES))
        db.atomic_json(self.state / 'database-bootstrap.json', expected)
        return expected

    def pipe(self):
        read, write = os.pipe()
        self.addCleanup(os.close, read); self.addCleanup(os.close, write)
        return read, write

    def test_snapshot_releases_bootstrap_lock_and_refuses_changed_uuid(self):
        expected = self.identity()
        actual, _ = service.captured_identity(self.state, VERSION)
        self.assertEqual(actual, expected)
        with db.state_lock(self.state): pass  # independently opened descriptor must acquire
        (self.state / 'database/auto.cnf').write_text('[auto]\nserver-uuid=00000000-0000-0000-0000-000000000000\n')
        with self.assertRaises(db.BootstrapError): service.captured_identity(self.state, VERSION)

    def test_exclusive_service_owner_preserves_lock_and_releases_on_error(self):
        with service.ownership(self.state):
            with self.assertRaisesRegex(service.ServiceError, 'another owner'):
                with service.ownership(self.state): pass
            with db.state_lock(self.state): pass  # provisioning lock is independent
        with service.ownership(self.state): pass
        self.assertEqual((self.state / '.mysql-service.lock').stat().st_mode & 0o777, 0o600)

    def test_bounded_metadata_rejects_links_hardlinks_and_special_files(self):
        target = self.root / 'plain'; target.write_bytes(b'1234')
        self.assertEqual(service.read_plain(target, 4), b'1234')
        with self.assertRaises(service.ServiceError): service.read_plain(target, 3)
        linked = self.root / 'link'; linked.symlink_to(target)
        with self.assertRaises(OSError): service.read_plain(linked, 4)
        linked.unlink(); os.link(target, linked)
        with self.assertRaises(service.ServiceError): service.read_plain(target, 4)
        fifo = self.root / 'fifo'; os.mkfifo(fifo)
        with self.assertRaises(service.ServiceError): service.read_plain(fifo, 4)

    def test_control_partial_command_limits_and_fd_restoration(self):
        read, write = self.pipe(); control = service.Control(read)
        try:
            self.assertFalse(os.get_blocking(read))
            os.write(write, b'shut'); self.assertIsNone(control.read(0))
            os.write(write, b'down\r\n'); self.assertEqual(control.read(0), 'command')
        finally: control.close()
        self.assertTrue(os.get_blocking(read))
        for data in (b'quit\n', b'shutdown\nextra', b'x' * 65):
            read, write = self.pipe(); control = service.Control(read)
            try:
                os.write(write, data)
                with self.assertRaises(service.ServiceError): control.read(0)
            finally: control.close()
        path = self.root / 'regular'; path.write_bytes(b'shutdown\n')
        with path.open('rb') as stream:
            with self.assertRaises(PermissionError): service.Control(stream.fileno())
            self.assertTrue(os.get_blocking(stream.fileno()))

    def test_control_eof_and_incomplete_eof_are_distinct(self):
        for partial in (b'', b'shut'):
            read, write = os.pipe(); control = service.Control(read)
            try:
                if partial:
                    os.write(write, partial); self.assertIsNone(control.read(0))
                os.close(write)
                if partial:
                    with self.assertRaises(service.ServiceError): control.read(0)
                else: self.assertEqual(control.read(0), 'owner-eof')
            finally: control.close(); os.close(read)

    def test_version_preflight_rejects_wrong_engine_before_existing_datadir_start(self):
        self.identity(); read, _ = self.pipe()
        executable = self.root / 'mysqld'
        executable.write_text('#!/usr/bin/python3\nimport pathlib,sys\n'
            'if sys.argv[1:]==["--no-defaults","--version"]:print("mysqld Ver 8.0.99-fixture")\n'
            f'else:pathlib.Path({str(self.root / "unsafe-start")!r}).write_text("started")\n')
        executable.chmod(0o700)
        with patch.object(db, 'EngineCapture') as capture, self.assertRaisesRegex(service.ServiceError, 'executable differs'):
            service.serve(self.state, self.session, Path('/usr/bin/mysql'), executable, VERSION, '1'*32, read)
        capture.assert_not_called()
        self.assertFalse((self.root / 'unsafe-start').exists())
        self.assertEqual(db.datadir_uuid(self.state / 'database'), UUID)
        executable.write_text('#!/usr/bin/python3\nprint("x"*20000)\n')
        with self.assertRaisesRegex(service.ServiceError, 'output exceeded bound'):
            service.preflight_engine(executable, VERSION)

    def test_engine_arguments_cannot_enable_defaults_upgrade_or_remote_listener(self):
        command = service.engine_command(Path('/usr/sbin/mysqld'), self.state, self.session, self.root / 's-fixture0/m.sock')
        for item in ('--no-defaults', '--persisted-globals-load=OFF', '--upgrade=NONE',
                     '--bind-address=127.0.0.1', '--port=13306', '--mysqlx=OFF'):
            self.assertIn(item, command)
        self.assertFalse(any(x.startswith(('--initialize', '--defaults-file', '--password')) for x in command))

    def test_short_socket_is_exclusive_private_and_keeps_operation_pid_identity(self):
        with service.short_socket(self.root) as first:
            self.assertEqual(first.name, 'm.sock')
            self.assertEqual(first.parent.stat().st_mode & 0o777, 0o700)
            with service.short_socket(self.root) as second:
                self.assertNotEqual(first.parent, second.parent)
            self.assertFalse(second.parent.exists())
            command = service.engine_command(Path('/usr/sbin/mysqld'), self.state, self.session, first)
            self.assertIn('--socket=' + str(first), command)
            self.assertIn('--pid-file=' + str(self.session / 'mysql.pid'), command)
        self.assertFalse(first.parent.exists())
        # Physical Android expansion, rather than only the shorter PRoot name.
        physical = Path('/data/user/0/io.github.russianranger.esteria/files/state/server-work')
        self.assertGreater(len(os.fsencode(physical / 'mysql-sessions' / ('1'*32) / 'mysql.sock')), 108)
        self.assertLessEqual(len(os.fsencode(physical / first.parent.name / first.name)), 100)

    def test_short_socket_preserves_nonempty_crash_leftovers_and_never_reuses_them(self):
        with service.short_socket(self.root) as first:
            first.write_bytes(b'owned interruption fixture')
        self.assertEqual(first.read_bytes(), b'owned interruption fixture')
        with service.short_socket(self.root) as second:
            self.assertNotEqual(first.parent, second.parent)
        self.assertEqual(first.read_bytes(), b'owned interruption fixture')
        link = self.root / 'linked-work'; link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(service.ServiceError):
            with service.short_socket(link): pass

    def test_short_socket_refuses_cleanup_of_replaced_directory(self):
        with self.assertRaisesRegex(service.ServiceError, 'identity changed'):
            with service.short_socket(self.root) as socket:
                socket.parent.rename(self.root / 'original-owned-directory')
                socket.parent.mkdir()
                (socket.parent / 'unrelated').write_bytes(b'preserve')
        self.assertEqual((socket.parent / 'unrelated').read_bytes(), b'preserve')

    def test_query_deadline_and_cancellation_precede_sql(self):
        inner = Mock(); check = Mock()
        with patch.object(db, 'Mysql', return_value=inner), patch.object(service.time, 'monotonic', return_value=10):
            connection = service.LiveConnection(Path('/mysql'), Path('/options'), 10.5, check)
            connection.query('SELECT 1', timeout=30)
            inner.query.assert_called_once_with('SELECT 1', timeout=.5)
            check.assert_called_once()
        with patch.object(service.time, 'monotonic', return_value=11), self.assertRaisesRegex(service.ServiceError, 'timed out'):
            connection.query('SELECT 1')
        inner.query.reset_mock(); check.side_effect = service.StopRequested('owner-signal')
        with self.assertRaises(service.StopRequested): connection.query('SELECT 1')
        inner.query.assert_not_called()

    def test_cancellation_before_or_during_preflight_never_starts_engine(self):
        self.identity()
        for during in (False, True):
            session=self.root/('cancel-'+str(during));session.mkdir()
            read,write=self.pipe()
            if not during: os.write(write,b'shutdown\n')
            def preflight(*_): os.write(write,b'shutdown\n')
            with patch.object(service,'preflight_engine',side_effect=preflight) as probe, \
                 patch.object(db,'EngineCapture') as capture:
                result=service.serve(self.state,session,Path('/mysql'),Path('/mysqld'),VERSION,'3'*32,read)
                self.assertEqual(probe.call_count,int(during));capture.assert_not_called()
            self.assertEqual(result['stopReason'],'command')
            self.assertFalse(result['engineStarted'] or result['cleanEngineExit'] or result['readyBeforeStop'])
            self.assertFalse((session/'ready.json').exists())
            self.assertEqual(json.loads((session/'stopped.json').read_text()),result)

    def test_owner_eof_during_readiness_cleans_engine_without_ready_receipt(self):
        self.identity();read,write=os.pipe();writers=[write]
        connection=Mock();capture=Mock();capture.process.poll.return_value=None
        def lost_owner(*_): os.close(writers.pop())
        try:
            with patch.object(service,'preflight_engine'),patch.object(db,'EngineCapture',return_value=capture), \
                 patch.object(service,'LiveConnection',return_value=connection), \
                 patch.object(service,'verify_live',side_effect=lost_owner),patch.object(service,'stop_engine') as stop:
                result=service.serve(self.state,self.session,Path('/mysql'),Path('/mysqld'),VERSION,'4'*32,read)
                stop.assert_called_once_with(capture);connection.close.assert_called_once()
            self.assertEqual(result['stopReason'],'owner-eof')
            self.assertTrue(result['engineStarted'] and result['cleanEngineExit'])
            self.assertFalse(result['readyBeforeStop']);self.assertFalse((self.session/'ready.json').exists())
        finally:
            os.close(read)
            for descriptor in writers:os.close(descriptor)

    def test_late_successful_query_cannot_publish_readiness(self):
        self.identity();read,_=self.pipe()
        connection=Mock();capture=Mock();capture.process.poll.return_value=None
        with patch.object(service.time,'monotonic',return_value=1) as clock, \
             patch.object(service,'preflight_engine'),patch.object(db,'EngineCapture',return_value=capture), \
             patch.object(service,'LiveConnection',return_value=connection), \
             patch.object(service,'verify_live',side_effect=lambda *_:setattr(clock,'return_value',2)), \
             patch.object(service,'stop_engine') as stop:
            with self.assertRaisesRegex(service.ServiceError,'readiness timed out'):
                service.serve(self.state,self.session,Path('/mysql'),Path('/mysqld'),VERSION,'5'*32,read,startup_timeout=.5)
            stop.assert_called_once_with(capture)
        self.assertFalse((self.session/'ready.json').exists());self.assertFalse((self.session/'stopped.json').exists())

    def test_sql_close_failure_cannot_skip_owned_engine_cleanup(self):
        self.identity(); read, write = self.pipe()
        connection = Mock(); connection.close.side_effect = db.BootstrapError('synthetic close failure')
        capture = Mock(); capture.process.poll.return_value = None
        def reached_ready(*_): os.write(write, b'shutdown\n')
        with patch.object(service, 'preflight_engine'), patch.object(db, 'EngineCapture', return_value=capture), \
             patch.object(service, 'LiveConnection', return_value=connection), \
             patch.object(service, 'verify_live', side_effect=reached_ready), \
             patch.object(service, 'stop_engine') as stop:
            with self.assertRaisesRegex(db.BootstrapError, 'synthetic close failure'):
                service.serve(self.state, self.session, Path('/mysql'), Path('/mysqld'), VERSION, '2'*32, read)
            stop.assert_called_once_with(capture)
        self.assertFalse((self.session / 'ready.json').exists())
        self.assertFalse((self.session / 'stopped.json').exists())

    def test_real_child_graceful_and_forced_shutdown_have_different_results(self):
        for ignore in (False, True):
            ready = self.root / ('ready-' + str(ignore)); log = self.root / ('log-' + str(ignore))
            code = ('import signal,pathlib,time,sys\n'
                + ('signal.signal(signal.SIGTERM,signal.SIG_IGN)\n' if ignore else
                   'signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))\n')
                + f'pathlib.Path({str(ready)!r}).write_text("ready")\n'
                + 'while True:time.sleep(.05)\n')
            capture = db.EngineCapture([sys.executable, '-c', code], log)
            try:
                deadline = time.monotonic()+5
                while not ready.exists():
                    self.assertLess(time.monotonic(), deadline); time.sleep(.01)
                if ignore:
                    with self.assertRaisesRegex(service.ServiceError, 'recovery required'):
                        service.stop_engine(capture, timeout=.05)
                    self.assertEqual(capture.process.returncode, -signal.SIGKILL)
                else:
                    service.stop_engine(capture, timeout=1)
                    self.assertEqual(capture.process.returncode, 0)
            finally:
                if capture.process.poll() is None: capture.process.kill(); capture.process.wait(timeout=5)
                capture.finish()


@unittest.skipUnless(os.environ.get('ESTERIA_MYSQL_SERVICE_INTEGRATION') == '1', 'isolated real MySQL fixture not enabled')
class RealMysqlService(unittest.TestCase):
    def test_fresh_instance_live_identity_exclusion_control_and_restart_persistence(self):
        self.assertIn(platform.machine(), ('aarch64','arm64'), 'this receipt qualifies native ARM64 only')
        expected = os.environ['ESTERIA_MYSQL_SERVICE_VERSION']; db.exact_version(expected)
        state = Path('/work/state'); sessions = Path('/work/mysql-sessions')
        self.assertFalse(state.exists(), 'existing state is never a disposable test fixture')
        self.assertFalse(sessions.exists(), 'existing service sessions preserved')
        state.mkdir(mode=0o700); sessions.mkdir(mode=0o700)
        db.read_secret(state / 'accounts/database-secret', create=True)
        with db.state_lock(state):
            initialized = db.initialize(Path('/usr/sbin/mysqld'), Path('/usr/bin/mysql'), state, expected)
        protected = [state/'database-bootstrap.json',state/'accounts/database-secret',state/'accounts/database-root-secret']
        before = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
        active = []
        def start():
            operation = secrets.token_hex(16); session = sessions/operation
            log = (Path('/work')/('helper-'+operation+'.log')).open('xb')
            process = subprocess.Popen([sys.executable, str(ROOT/'runtime/mysql_service.py'),
                '--expected-version',expected,'--operation-id',operation], stdin=subprocess.PIPE,
                stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            group = OwnedGroup(process); active.append((group,log))
            return group, session
        def ready(group, session):
            deadline=time.monotonic()+110
            while not (session/'ready.json').exists():
                self.assertIsNone(group.observe(), 'helper exited before authenticated readiness')
                self.assertLess(time.monotonic(),deadline,'service readiness deadline exceeded')
                time.sleep(.05)
            value=json.loads(service.read_plain(session/'ready.json',16384))
            self.assertEqual(value['uuid'],initialized['uuid'])
            self.assertTrue(value['liveSqlAuthenticated'] and value['ownedEngineIdentityVerified'])
            self.assertFalse(value['applicationSchemaUpdatesQualified'] or value['gameplayQualified'])
            return value
        def finish(group, session, reason):
            if reason == 'command': group.process.stdin.write(b'shutdown\n'); group.process.stdin.flush()
            elif reason == 'owner-eof': group.process.stdin.close()
            else:
                # Signal only the retained helper, so its handler must itself
                # stop the engine. Popen.send_signal() would poll/reap first.
                self.assertIsNone(group.observe())
                descriptor=os.pidfd_open(group.process.pid)
                try:signal.pidfd_send_signal(descriptor,signal.SIGTERM)
                finally:os.close(descriptor)
            self.assertEqual(group.wait(35),0 if reason=='command' else 1)
            group.stop(graceful_timeout=0)
            stopped=json.loads(service.read_plain(session/'stopped.json',16384))
            self.assertEqual(stopped['stopReason'],reason)
            self.assertTrue(stopped['engineStarted'] and stopped['cleanEngineExit'] and stopped['readyBeforeStop'])
            self.assertFalse(stopped['dataRemoved'] or stopped['characterPersistenceQualified'] or stopped['gameplayQualified'])
        try:
            for index, reason in enumerate(('command','owner-eof','owner-signal')):
                group, session=start(); ready(group,session)
                with db.state_lock(state):
                    observed=db.verify(Path('/usr/bin/mysql'),state,expected)
                    self.assertEqual(observed['uuid'],initialized['uuid'])
                with db.option_file(Path('/work'),'esteria',db.read_secret(state/'accounts/database-secret')) as options, \
                     db.Mysql(Path('/usr/bin/mysql'),options) as connection:
                    for database in db.DATABASES:
                        if index==0:
                            connection.query('CREATE TABLE `'+database+'`.`service_fixture` (id INT PRIMARY KEY, value VARCHAR(32)) ENGINE=InnoDB')
                            connection.query('INSERT INTO `'+database+'`.`service_fixture` VALUES (1,\'fixture-persisted\')')
                        self.assertEqual(connection.query('SELECT value FROM `'+database+'`.`service_fixture` WHERE id=1'),['fixture-persisted'])
                    if index==0:
                        duplicate, duplicate_session=start()
                        self.assertEqual(duplicate.wait(10),1)
                        duplicate.stop(graceful_timeout=0)
                        self.assertFalse((duplicate_session/'ready.json').exists())
                        self.assertFalse((duplicate_session/'stopped.json').exists())
                        self.assertEqual(connection.query('SELECT 1'),['1'])
                finish(group,session,reason)
                self.assertEqual({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in protected},before)
                self.assertEqual(db.datadir_uuid(state/'database'),initialized['uuid'])
            result=dict(formatVersion=1,scope='native-arm64-persistent-mysql-service-fixture',
                expectedVersion=expected,initializedFreshFixture=True,authenticatedReadyCycles=3,
                exactPidFileAndUuidVerified=True,concurrentOwnerRejected=True,bootstrapLockReleased=True,
                commandShutdownVerified=True,ownerEofShutdownVerified=True,ownerSignalShutdownVerified=True,
                persistentMarkerDatabases=4,restartsPreservedMarkers=True,credentialsAndReceiptUnchanged=True,
                applicationSchemaUpdatesQualified=False,characterPersistenceQualified=False,
                androidQualified=False,gameplayQualified=False)
            destination=Path(os.environ['ESTERIA_MYSQL_SERVICE_EVIDENCE'])/'qualification.json'
            self.assertFalse(destination.exists());db.atomic_json(destination,result)
        finally:
            for group,log in reversed(active):
                try: group.stop(graceful_timeout=25)
                finally:
                    if not group.process.stdin.closed: group.process.stdin.close()
                    log.close()


if __name__ == '__main__': unittest.main()
