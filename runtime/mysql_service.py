#!/usr/bin/env python3
"""Own one persistent local MySQL process; authenticate before reporting readiness.

This starts an already initialized instance. It never initializes, imports,
repairs, migrates or deletes database contents. The outer Android process owner
must retain this helper and its PRoot tracer for the complete service lifetime.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time

if __package__:
    from . import mysql_bootstrap as db
else:
    import mysql_bootstrap as db


class ServiceError(RuntimeError):
    pass


class StopRequested(Exception):
    def __init__(self, reason):
        self.reason = reason


def require(value, reason):
    if not value:
        raise ServiceError(reason)


def plain_directory(path: Path):
    require(path.is_absolute() and path == Path(os.path.normpath(path)), 'noncanonical service directory')
    for current in (path, *path.parents):
        require(stat.S_ISDIR(current.lstat().st_mode), 'service path contains a link or non-directory')
    return path


def read_plain(path: Path, maximum: int):
    plain_directory(path.parent)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= maximum,
                'invalid bounded service file')
        raw = stream.read(maximum + 1)
        require(len(raw) <= maximum, 'service file exceeded its bound')
        return raw


@contextmanager
def ownership(state: Path):
    plain_directory(state)
    descriptor = os.open(state / '.mysql-service.lock',
                         os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), 'service lock is not a regular file')
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ServiceError('another owner is running this database') from error
        yield
    finally:
        os.close(descriptor)


def captured_identity(state: Path, version: str):
    # Bootstrap locks protect this snapshot, then are released: account/realm
    # provisioning needs those same locks while the service is running.
    with db.state_lock(state):
        receipt = json.loads(read_plain(state / 'database-bootstrap.json', 16384))
        require(type(receipt) is dict and type(receipt.get('uuid')) is str,
                'missing initialized database identity')
        expected = {'format': db.FORMAT, 'engine': 'mysql', 'version': version,
                    'uuid': db.datadir_uuid(plain_directory(state / 'database')),
                    'datadir': str(state / 'database'), 'databases': list(db.DATABASES)}
        db.check_receipt(receipt, expected)
        credential = read_plain(state / 'accounts/database-secret', 66).strip()
        require(re.fullmatch(b'[a-f0-9]{64}', credential), 'invalid existing application credential')
        return expected, credential.decode('ascii')


def engine_command(mysqld: Path, state: Path, session: Path):
    socket = session / 'mysql.sock'
    require(len(os.fsencode(socket)) <= 100, 'database socket path is too long')
    # No defaults file or persisted server-variable overrides can change this
    # listener, datadir or log destination. All engine output goes to a bounded
    # private capture. InnoDB's ordinary recovery preserves existing saves.
    command = [str(mysqld), '--no-defaults', '--persisted-globals-load=OFF', '--upgrade=NONE',
               '--datadir=' + str(state / 'database'), '--bind-address=127.0.0.1',
               '--port=' + str(db.PORT), '--mysqlx=OFF', '--skip-name-resolve',
               '--secure-file-priv=NULL', '--socket=' + str(socket),
               '--pid-file=' + str(session / 'mysql.pid'), '--max-connections=24',
               '--innodb-buffer-pool-size=128M', '--innodb-log-buffer-size=8M',
               '--innodb-flush-log-at-trx-commit=1', '--max-allowed-packet=64M',
               '--tmp-table-size=16M', '--max-heap-table-size=16M', '--performance-schema=OFF']
    if os.geteuid() == 0:
        command.append('--user=root')  # Only the isolated native build fixture is root.
    return command


def preflight_engine(mysqld: Path, version: str):
    """Reject a different binary version before it can touch existing storage."""
    process = subprocess.Popen([str(mysqld), '--no-defaults', '--version'],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    raw = bytearray()
    deadline = time.monotonic() + 10
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'engine version preflight timed out')
                for key, _ in selector.select(min(remaining, .1)):
                    block = os.read(key.fd, 4096)
                    if not block:
                        selector.unregister(key.fileobj)
                    raw.extend(block)
                    require(len(raw) <= 16384, 'engine version preflight output exceeded bound')
            code = process.wait(timeout=max(.01, deadline - time.monotonic()))
        text = raw.decode('utf-8', errors='strict')
        matches = re.findall(r'\bVer ([^\s]+)', text)
        require(code == 0 and matches == [version] and 'mariadb' not in text.lower(),
                'server executable differs from the persistent database version')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()


def verify_live(connection, expected, session, process):
    require(process.poll() is None, 'owned engine exited before readiness')
    db.check_receipt(expected, db.identity(connection, expected['version']))
    db.check_listener(connection, None)
    require(connection.query('SELECT CURRENT_USER()') in [['esteria@127.0.0.1'], ['esteria@localhost']],
            'unexpected authenticated application account')
    pid_file = session / 'mysql.pid'
    require(connection.query('SELECT @@pid_file') == [str(pid_file)], 'connected engine is not this service instance')
    require(read_plain(pid_file, 32).strip() == str(process.pid).encode('ascii'),
            'connected engine process identity differs')
    for database in db.DATABASES:
        require(connection.query('USE `' + database + '`; SELECT 1') == ['1'],
                'authenticated schema access failed')
    require(process.poll() is None, 'owned engine exited during readiness')


class LiveConnection:
    """Bound every readiness query to the remaining overall startup deadline."""
    def __init__(self, executable, options, deadline, check_stop):
        self.inner = db.Mysql(executable, options)
        self.deadline = deadline
        self.check_stop = check_stop

    def query(self, sql, timeout=3):
        self.check_stop()
        remaining = 3 if self.deadline is None else self.deadline - time.monotonic()
        require(remaining > 0, 'authenticated database readiness timed out')
        return self.inner.query(sql, timeout=min(timeout, 3, remaining))

    def close(self):
        self.inner.close()


class Control:
    """An explicit bounded command or owner EOF; never a shell or SQL channel."""
    def __init__(self, descriptor):
        self.descriptor = descriptor
        self.original_blocking = os.get_blocking(descriptor)
        os.set_blocking(descriptor, False)
        self.selector = selectors.DefaultSelector()
        try:
            self.selector.register(descriptor, selectors.EVENT_READ)
        except BaseException:
            self.selector.close()
            os.set_blocking(descriptor, self.original_blocking)
            raise
        self.buffer = b''

    def read(self, timeout=.1):
        if not self.selector.select(timeout):
            return None
        block = os.read(self.descriptor, 65)
        if not block:
            require(not self.buffer, 'incomplete service control command')
            return 'owner-eof'
        self.buffer += block
        require(len(self.buffer) <= 16, 'oversized service control command')
        if b'\n' not in self.buffer:
            return None
        require(self.buffer in (b'shutdown\n', b'shutdown\r\n'), 'invalid service control command')
        return 'command'

    def close(self):
        self.selector.close()
        os.set_blocking(self.descriptor, self.original_blocking)


def stop_engine(capture, timeout=20):
    process = capture.process
    try:
        if process.poll() is None:
            # MySQL handles SIGTERM as its orderly shutdown request. The actual
            # child handle is retained; no pid file or discovered PID is signaled.
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as error:
                process.kill()
                process.wait(timeout=5)
                raise ServiceError('database exceeded graceful shutdown deadline; recovery required') from error
        require(process.returncode == 0, 'database did not exit cleanly; recovery required')
    finally:
        capture.finish()
    require(capture.error is None, 'database diagnostic capture failed')


def stopped_receipt(session, expected, operation, ready, reason, engine_started):
    result = dict(formatVersion=1, scope='owned-local-mysql-stopped', operationId=operation,
                  version=expected['version'], uuid=expected['uuid'], readyBeforeStop=ready,
                  stopReason=reason, engineStarted=engine_started, cleanEngineExit=engine_started,
                  dataRemoved=False, characterPersistenceQualified=False, gameplayQualified=False)
    db.atomic_json(session / 'stopped.json', result)
    return result


def serve(state: Path, session: Path, mysql: Path, mysqld: Path, version: str,
          operation: str, control_fd: int, interrupted=lambda: False, startup_timeout=90):
    db.exact_version(version)
    require(re.fullmatch('[a-f0-9]{32}', operation), 'invalid service operation identity')
    state, session = plain_directory(state), plain_directory(session)
    require(session != state and not state.is_relative_to(session) and
            not session.is_relative_to(state / 'database'), 'service session overlaps database storage')
    require(not any(session.iterdir()), 'service session must be fresh')
    require(mysql.is_absolute() and mysqld.is_absolute(), 'absolute installed executables required')
    require(0 < startup_timeout <= 180, 'invalid service readiness deadline')
    control = Control(control_fd)
    capture = None
    connection = None
    ready = False
    reason = None
    def check_stop():
        pending = 'owner-signal' if interrupted() else control.read(0)
        if pending:
            raise StopRequested(pending)
    try:
        with ownership(state):
            expected, password = captured_identity(state, version)
            command = engine_command(mysqld, state, session)
            try:
                check_stop()
            except StopRequested as stop:
                return stopped_receipt(session, expected, operation, False, stop.reason, False)
            preflight_engine(mysqld, version)
            try:
                check_stop()
            except StopRequested as stop:
                return stopped_receipt(session, expected, operation, False, stop.reason, False)
            with db.option_file(session, 'esteria', password) as options:
                password = None
                capture = db.EngineCapture(command, session / 'engine-private.log')
                try:
                    deadline = time.monotonic() + startup_timeout
                    while True:
                        require(capture.process.poll() is None, 'owned engine exited during startup')
                        if interrupted():
                            reason = 'owner-signal'
                            break
                        reason = control.read()
                        if reason:
                            break
                        try:
                            connection = LiveConnection(mysql, options, deadline, check_stop)
                            verify_live(connection, expected, session, capture.process)
                            check_stop()
                            break
                        except StopRequested as stop:
                            reason = stop.reason
                            break
                        except (db.BootstrapError, OSError):
                            if connection:
                                connection.close()
                                connection = None
                            require(time.monotonic() < deadline, 'authenticated database readiness timed out')
                    if reason is None:
                        require(time.monotonic() < deadline, 'authenticated database readiness timed out')
                        connection.deadline = None
                        connection.check_stop = lambda: None
                        db.atomic_json(session / 'ready.json', dict(formatVersion=1,
                            scope='owned-local-mysql-live-service', operationId=operation,
                            version=version, uuid=expected['uuid'], datadir=expected['datadir'],
                            databases=list(db.DATABASES), bindAddress='127.0.0.1', port=db.PORT,
                            liveSqlAuthenticated=True, ownedEngineIdentityVerified=True,
                            applicationSchemaUpdatesQualified=False, gameplayQualified=False))
                        ready = True
                        next_probe = time.monotonic() + 2
                        while reason is None:
                            require(capture.process.poll() is None, 'owned engine exited during session')
                            require(capture.error is None, 'database diagnostic capture failed')
                            reason = 'owner-signal' if interrupted() else control.read()
                            if reason is None and time.monotonic() >= next_probe:
                                require(connection.query('SELECT 1', timeout=3) == ['1'], 'live database probe failed')
                                next_probe = time.monotonic() + 2
                finally:
                    try:
                        if connection:
                            connection.close()
                            connection = None
                    finally:
                        stop_engine(capture)
                        capture = None
            return stopped_receipt(session, expected, operation, ready, reason, True)
    finally:
        control.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--operation-id', required=True)
    args = parser.parse_args()
    stopped = [False]
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.__setitem__(0, True))
    try:
        require(re.fullmatch('[a-f0-9]{32}', args.operation_id), 'invalid service operation identity')
        sessions = plain_directory(Path('/work/mysql-sessions'))
        session = sessions / args.operation_id
        session.mkdir(mode=0o700)
        report = serve(Path('/work/state'), session, Path('/usr/bin/mysql'), Path('/usr/sbin/mysqld'),
                       args.expected_version, args.operation_id, sys.stdin.fileno(), lambda: stopped[0])
        print('Esteria local database service stopped; game schema updates and character saves are not qualified')
        return 0 if report['stopReason'] == 'command' else 1
    except Exception as error:
        # Never emit exception text or SQL/client diagnostics: they may contain
        # private credentials, paths or data. The owned engine log stays private.
        kind = type(error).__name__
        if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', kind):
            kind = 'Exception'
        print('Local database service failed (' + kind + '); persistent data retained', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
