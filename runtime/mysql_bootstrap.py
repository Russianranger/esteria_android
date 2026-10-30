#!/usr/bin/env python3
"""Initialize/provision a private MySQL 8 instance without importing game schemas.

Passwords travel in private option files or stdin, never process arguments.
Existing data is never initialized, cleared, or reseeded. `verify` performs real
SQL authentication and checks the pinned MySQL version and instance UUID.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import subprocess
import tempfile
import threading
import time
import uuid as uuid_module

DATABASES = ('acore_auth', 'acore_world', 'acore_characters', 'acore_playerbots')
HOSTS = ('127.0.0.1', 'localhost')
PORT = 13306
FORMAT = 1
ENGINE_LOG_LIMIT = 64 * 1024


class BootstrapError(RuntimeError):
    pass


class EngineCapture:
    """Capture only mysqld diagnostics, never SQL-client stderr, in a private bounded tail."""
    def __init__(self, command: list[str], path: Path):
        path = private_path(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(descriptor, 0o600)
        self.output = os.fdopen(descriptor, 'wb', buffering=0)
        self.error = None
        try:
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
        except BaseException:
            self.output.close()
            raise
        self.reader = threading.Thread(target=self._drain, name='esteria-mysqld-log', daemon=True)
        self.reader.start()

    def _drain(self):
        tail = bytearray()
        try:
            while True:
                block = self.process.stdout.read(8192)
                if not block:
                    break
                tail.extend(block)
                if len(tail) > ENGINE_LOG_LIMIT:
                    del tail[:-ENGINE_LOG_LIMIT]
                # Keep a readable bounded tail even if the owner is interrupted.
                if self.error is None:
                    try:
                        self.output.seek(0)
                        self.output.write(tail)
                        self.output.truncate()
                    except OSError as error:
                        self.error = error  # Continue draining to prevent a blocked daemon.
        except OSError as error:
            self.error = error
        finally:
            try:
                self.output.flush()
                os.fsync(self.output.fileno())
            except OSError as error:
                self.error = error
            self.output.close()
            self.process.stdout.close()

    def finish(self):
        if self.process.poll() is None:
            raise BootstrapError('Engine diagnostic capture must finish after process shutdown')
        self.reader.join(timeout=5)
        if self.reader.is_alive():
            raise BootstrapError('Engine diagnostic reader did not finish after shutdown')


def run_engine(command: list[str], path: Path, timeout: float) -> int:
    capture = EngineCapture(command, path)
    try:
        return capture.process.wait(timeout=timeout)
    finally:
        if capture.process.poll() is None:
            capture.process.kill()
            capture.process.wait(timeout=5)
        capture.finish()


def exact_version(value: str) -> None:
    if (not re.fullmatch(r'8\.\d+\.\d+(?:[-+~][A-Za-z0-9][A-Za-z0-9.+~_-]*)?', value)
            or 'mariadb' in value.lower()):
        raise BootstrapError('Expected version must pin an exact MySQL 8 release')


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path: Path, value: dict) -> None:
    private_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.bootstrap-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def private_path(path: Path) -> Path:
    path = path.absolute()
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise BootstrapError('Symlink paths are not permitted for bootstrap state or credentials')
    return path


def read_secret(path: Path, *, create: bool = False) -> str:
    private_path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.exists() and create:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(secrets.token_hex(32) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(path.parent)
    if not path.is_file():
        raise BootstrapError('Missing persistent database credential; run the configuration renderer first')
    secret = path.read_text().strip()
    if not re.fullmatch('[a-f0-9]{64}', secret):
        raise BootstrapError('Invalid persistent database credential; refusing to replace it')
    os.chmod(path, 0o600)
    return secret


@contextmanager
def state_lock(state: Path):
    private_path(state)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = private_path(state / '.mysql-bootstrap.lock')
    with lock_path.open('a') as stream:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BootstrapError('Another bootstrap operation owns this installation') from error
        yield


@contextmanager
def option_file(directory: Path, user: str, password: str):
    fd, name = tempfile.mkstemp(prefix='.mysql-auth-', suffix='.cnf', dir=directory)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            # Internally generated hex passwords cannot inject MySQL option syntax.
            stream.write(f'[client]\nuser={user}\npassword={password}\n')
            stream.flush()
        yield Path(name)
    finally:
        Path(name).unlink(missing_ok=True)


class Mysql:
    """One persistent mysql CLI connection, including session-scoped GET_LOCK."""
    def __init__(self, executable: Path, options: Path, socket: Path | None = None):
        private_path(options)
        if not options.is_file() or options.stat().st_mode & 0o077:
            raise BootstrapError('MySQL option file must exist and be private (mode 0600)')
        command = [str(executable), f'--defaults-file={options}', '--batch', '--raw',
                   '--skip-column-names', '--unbuffered', '--skip-reconnect', '--connect-timeout=3']
        command += ['--protocol=SOCKET', f'--socket={socket}'] if socket else [
            '--protocol=TCP', '--host=127.0.0.1', f'--port={PORT}']
        # mysql can include SQL fragments in errors. Keep stderr out of logs.
        environment = dict(os.environ)
        environment.pop('MYSQL_PWD', None)
        # MySQL 8.0 does not support the newer --no-login-paths option. Its own
        # my_default_get_login_file() honors this override, so do not inherit a
        # user's encrypted .mylogin.cnf alongside our explicit private options.
        environment['MYSQL_TEST_LOGIN_FILE'] = os.devnull
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0, env=environment)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = b''

    def query(self, sql: str, timeout: float = 30) -> list[str]:
        marker = '__esteria_' + secrets.token_hex(16)
        try:
            data = memoryview((sql.rstrip(';\n') + f";\nSELECT '{marker}';\n").encode())
            while data:
                written = self.process.stdin.write(data)
                if not written:
                    raise OSError('Closed MySQL input pipe')
                data = data[written:]
        except (BrokenPipeError, OSError) as error:
            raise BootstrapError('MySQL connection failed; verify the private credentials and endpoint') from error
        deadline = time.monotonic() + timeout
        rows = []
        total = 0
        while True:
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                decoded = line.decode('utf-8', errors='strict').rstrip('\r')
                if decoded == marker:
                    return rows
                rows.append(decoded)
            if time.monotonic() >= deadline:
                raise BootstrapError('MySQL operation timed out')
            if not self.selector.select(min(0.2, max(0, deadline - time.monotonic()))):
                continue
            block = os.read(self.process.stdout.fileno(), 8192)
            if not block:
                raise BootstrapError('MySQL query failed; no credentials or SQL text were logged')
            total += len(block)
            if total > 1_048_576:
                raise BootstrapError('Unexpectedly large bootstrap response')
            self.buffer += block

    def close(self):
        self.selector.close()
        if self.process.poll() is None:
            try:
                self.process.stdin.write(b'quit\n')
                self.process.stdin.flush()
                self.process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def identity(connection: Mysql, expected_version: str) -> dict:
    exact_version(expected_version)
    rows = connection.query('SELECT VERSION(), @@version_comment, @@server_uuid, @@datadir')
    if len(rows) != 1 or len(rows[0].split('\t')) != 4:
        raise BootstrapError('Malformed MySQL identity response')
    version, comment, uuid, datadir = rows[0].split('\t')
    if version != expected_version or 'mariadb' in comment.lower():
        raise BootstrapError(f'MySQL version mismatch: required {expected_version}, observed {version}')
    if str(uuid_module.UUID(uuid)) != uuid:
        raise BootstrapError('Invalid MySQL instance UUID')
    if not Path(datadir).is_absolute():
        raise BootstrapError('MySQL datadir must be absolute')
    return {'format': FORMAT, 'engine': 'mysql', 'version': version, 'uuid': uuid,
            'datadir': str(Path(datadir).resolve()),
            'databases': list(DATABASES), 'application_schemas_populated': False}


def check_receipt(receipt: dict, observed: dict) -> None:
    for key in ('format', 'engine', 'version', 'uuid', 'datadir', 'databases'):
        if receipt.get(key) != observed[key]:
            raise BootstrapError(f'Bootstrap receipt mismatch for {key}; refusing another instance or version')


def read_receipt(path: Path, expected_version: str) -> dict:
    receipt = json.loads(private_path(path).read_text())
    if (not isinstance(receipt, dict) or not isinstance(receipt.get('uuid'), str)
            or not isinstance(receipt.get('datadir'), str)
            or not Path(receipt['datadir']).is_absolute()):
        raise BootstrapError('Invalid bootstrap receipt')
    if str(uuid_module.UUID(receipt['uuid'])) != receipt['uuid']:
        raise BootstrapError('Invalid bootstrap receipt UUID')
    expected = {'format': FORMAT, 'engine': 'mysql', 'version': expected_version,
                'datadir': str(Path(receipt['datadir']).resolve()),
                'uuid': receipt['uuid'], 'databases': list(DATABASES)}
    check_receipt(receipt, expected)
    return receipt


def datadir_uuid(datadir: Path) -> str:
    auto = private_path(datadir / 'auto.cnf')
    if not auto.is_file():
        raise BootstrapError('Datadir UUID file is missing')
    values = [line.removeprefix('server-uuid=') for line in auto.read_text().splitlines()
              if line.startswith('server-uuid=')]
    if len(values) != 1 or str(uuid_module.UUID(values[0])) != values[0]:
        raise BootstrapError('Invalid datadir UUID')
    return values[0]


def check_listener(connection: Mysql, socket: Path | None) -> None:
    if socket is None and connection.query('SELECT @@port, @@bind_address') != [f'{PORT}\t127.0.0.1']:
        raise BootstrapError('Database must bind exclusively to 127.0.0.1:13306')


def verify_application(mysql: Path, state: Path, expected_version: str, expected: dict,
                       socket: Path | None = None) -> None:
    password = read_secret(state / 'accounts/database-secret')
    with option_file(state, 'esteria', password) as options, Mysql(mysql, options, socket) as application:
        check_receipt(expected, identity(application, expected_version))
        check_listener(application, socket)
        user = application.query('SELECT CURRENT_USER()')
        if user not in [['esteria@127.0.0.1'], ['esteria@localhost']]:
            raise BootstrapError('Authenticated as an unexpected database account')
        for database in DATABASES:
            if application.query(f'USE `{database}`; SELECT 1') != ['1']:
                raise BootstrapError('Authenticated database readiness check failed')


def provision(mysql: Path, state: Path, expected_version: str, admin_options: Path,
              socket: Path | None = None, receipt_name: str = 'database-bootstrap.json') -> dict:
    """Called under state_lock; only bootstrap-owned pending state permits recovery."""
    password = read_secret(state / 'accounts/database-secret')
    receipt_path = private_path(state / receipt_name)
    pending_path = private_path(state / (receipt_name + '.pending'))
    with Mysql(mysql, admin_options, socket) as admin:
        observed = identity(admin, expected_version)
        check_listener(admin, socket)
        if admin.query("SELECT GET_LOCK('esteria-local-bootstrap', 0)") != ['1']:
            raise BootstrapError('Another bootstrap connection owns this MySQL instance')
        if receipt_path.exists():
            check_receipt(json.loads(receipt_path.read_text()), observed)
            verify_application(mysql, state, expected_version, observed, socket)
            return observed | {'operation': 'verified-existing', 'sql_authenticated': True}
        if pending_path.exists():
            pending = json.loads(pending_path.read_text())
            check_receipt(pending, observed)
            if pending.get('credential_sha256') != hashlib.sha256(password.encode()).hexdigest():
                raise BootstrapError('Persistent credential changed during interrupted provisioning; refusing modification')
        else:
            dbs = ','.join(f"'{name}'" for name in DATABASES)
            existing = admin.query(f'SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME IN ({dbs})')
            users = admin.query("SELECT Host FROM mysql.user WHERE User='esteria'")
            if existing or users:
                raise BootstrapError('Existing unowned Esteria databases/account found; refusing adoption or reseeding')
            atomic_json(pending_path, observed | {'credential_sha256': hashlib.sha256(password.encode()).hexdigest()})
        # CREATE IF NOT EXISTS resumes only this instance's recorded bootstrap.
        # It never changes a preexisting account password.
        for host in HOSTS:
            admin.query(f"CREATE USER IF NOT EXISTS 'esteria'@'{host}' IDENTIFIED BY '{password}'")
        # A wrong changed password must fail before grants/database modifications.
        with option_file(state, 'esteria', password) as options, Mysql(mysql, options, socket) as check:
            check_receipt(observed, identity(check, expected_version))
        for database in DATABASES:
            admin.query(f'CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci')
            for host in HOSTS:
                admin.query(f"GRANT ALL PRIVILEGES ON `{database}`.* TO 'esteria'@'{host}'")
        verify_application(mysql, state, expected_version, observed, socket)
        atomic_json(receipt_path, observed)
        pending_path.unlink(missing_ok=True)
        sync_directory(state)
        return observed | {'operation': 'provisioned', 'sql_authenticated': True}


def verify(mysql: Path, state: Path, expected_version: str) -> dict:
    path = private_path(state / 'database-bootstrap.json')
    if not path.is_file():
        raise BootstrapError('No completed bootstrap receipt; provisioning is required')
    receipt = json.loads(path.read_text())
    verify_application(mysql, state, expected_version, receipt)
    return receipt | {'operation': 'verified-existing', 'sql_authenticated': True}


def _cnf_path(path: Path) -> str:
    text = str(path)
    if any(c in text for c in ('\x00', '\n', '\r', '"', '\\')):
        raise BootstrapError('Unsupported configuration path')
    return '"' + text + '"'


def initialization_command(mysqld: Path, stage: Path, run: Path) -> list[str]:
    """Keep fresh-engine temporary writes in a new, owned private directory."""
    temporary = private_path(run / 'initialize-tmp')
    if ':' in str(temporary):
        raise BootstrapError('Initialization temporary path must not select multiple directories')
    # A leftover is recovery state, even if empty. Never adopt or clear it.
    temporary.mkdir(mode=0o700)
    sync_directory(run)
    command = [str(mysqld), '--no-defaults', '--initialize-insecure', f'--datadir={stage}',
               f'--tmpdir={temporary}', '--skip-networking', '--secure-file-priv=NULL']
    if os.geteuid() == 0:
        command.append('--user=root')
    return command


def initialize(mysqld: Path, mysql: Path, state: Path, expected_version: str) -> dict:
    """Stage a brand-new instance. Never call --initialize over existing storage."""
    exact_version(expected_version)
    target = private_path(state / 'database')
    # MySQL 8.0 InnoDB discovery skips dot-prefixed datadirs: a newly initialized
    # hidden directory fails restart with MY-013039 (undo_001 already exists).
    # Keep the private staging directory visible; privacy comes from mode 0700.
    stage = private_path(state / 'database-initializing')
    legacy_stage = private_path(state / '.database-initializing')
    journal = private_path(state / '.database-initialization.json')
    receipt_path = private_path(state / 'database-bootstrap.json')
    if receipt_path.exists():
        receipt = read_receipt(receipt_path, expected_version)
        if receipt['datadir'] != str(target.resolve()) or datadir_uuid(target) != receipt['uuid']:
            raise BootstrapError('Existing datadir UUID disagrees with its receipt')
        return receipt | {'operation': 'already-initialized', 'sql_authenticated': False,
                          'next': 'Start the owned instance, then run verify'}
    if legacy_stage.exists():
        raise BootstrapError('Legacy hidden staging datadir is preserved; inspect recovery before starting a new initialization')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        # The data rename is durable before the receipt rename. A crash between
        # them may finish only this already-provisioned, exactly identified move.
        if journal.is_file() and not stage.exists():
            progress = json.loads(journal.read_text())
            if (progress.get('format') == FORMAT and progress.get('version') == expected_version
                    and progress.get('phase') == 'ready-to-promote'):
                staged = read_receipt(state / '.database-staged-bootstrap.json', expected_version)
                if (staged['datadir'] == str(stage.resolve())
                        and staged['uuid'] == progress.get('uuid') == datadir_uuid(target)):
                    staged['datadir'] = str(target.resolve())
                    atomic_json(receipt_path, staged)
                    journal.unlink()
                    (state / '.database-staged-bootstrap.json').unlink()
                    sync_directory(state)
                    return staged | {'operation': 'recovered-promotion', 'sql_authenticated': False,
                                     'next': 'Start the owned instance, then run verify'}
        raise BootstrapError('Nonempty datadir has no completed receipt; preserve it for recovery, never initialize it')
    # Fail before touching a datadir when the executable is not the pinned engine.
    result = subprocess.run([str(mysqld), '--no-defaults', '--version'], check=True,
                            capture_output=True, text=True, timeout=10)
    match = re.search(r'\bVer ([^\s]+)', result.stdout)
    if not match or match[1] != expected_version or 'mariadb' in result.stdout.lower():
        raise BootstrapError('MySQL server executable does not match the pinned version')
    read_secret(state / 'accounts/database-secret')
    root_password = read_secret(state / 'accounts/database-root-secret', create=True)
    run = private_path(state / 'run')
    run.mkdir(mode=0o700, exist_ok=True)
    socket = private_path(run / 'bootstrap.sock')
    if len(os.fsencode(socket)) > 100:
        raise BootstrapError('Bootstrap socket path is too long; use a shorter runtime mount')
    if journal.exists():
        progress = json.loads(journal.read_text())
        if progress.get('format') != FORMAT or progress.get('version') != expected_version:
            raise BootstrapError('Interrupted initialization belongs to a different format/version')
        if progress.get('phase') == 'initializing':
            raise BootstrapError('MySQL initialization was interrupted; preserve staging for inspection; it will not be reinitialized')
        if progress.get('phase') not in ('initialized', 'ready-to-promote'):
            raise BootstrapError('Unknown initialization phase; preserving staging')
        if not private_path(stage / 'auto.cnf').is_file():
            raise BootstrapError('Interrupted staging datadir is incomplete; refusing reinitialization')
    else:
        if stage.exists():
            raise BootstrapError('Unowned staging datadir exists; refusing replacement')
        stage.mkdir(mode=0o700)
        progress = {'format': FORMAT, 'version': expected_version, 'phase': 'initializing'}
        atomic_json(journal, progress)
        command = initialization_command(mysqld, stage, run)
        returncode = run_engine(command, state / 'logs/mysql-initialize-engine.log', timeout=180)
        if returncode:
            raise BootstrapError(f'Fresh MySQL initialization failed (exit {returncode}); staging and logs/mysql-initialize-engine.log were preserved')
        progress['phase'] = 'initialized'
        atomic_json(journal, progress)
    owned_uuid = datadir_uuid(stage)
    if progress.get('uuid', owned_uuid) != owned_uuid:
        raise BootstrapError('Staged datadir UUID disagrees with the initialization journal')
    if socket.exists():
        raise BootstrapError('Existing bootstrap socket requires ownership/recovery inspection before starting another server')
    pid_file = private_path(run / 'bootstrap.pid')
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            if pid <= 1:
                raise ValueError('Invalid PID')
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        except (ValueError, PermissionError):
            raise BootstrapError('Cannot establish ownership of previous bootstrap PID; refusing another server')
        else:
            raise BootstrapError('Previous bootstrap process may still be running; stop it through its owner before resuming')
    config = run / 'bootstrap.cnf'
    fd = os.open(private_path(config), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write('[mysqld]\nskip-networking\nmysqlx=OFF\nsecure-file-priv=NULL\n'
                     f'datadir={_cnf_path(stage)}\nsocket={_cnf_path(socket)}\npid-file={_cnf_path(pid_file)}\n'
                     'innodb-buffer-pool-size=128M\nperformance-schema=OFF\ngeneral-log=OFF\nslow-query-log=OFF\n')
    command = [str(mysqld), f'--defaults-file={config}']
    if os.geteuid() == 0:
        command.append('--user=root')
    capture = EngineCapture(command, state / 'logs/mysql-bootstrap-engine.log')
    process = capture.process
    try:
        deadline = time.monotonic() + 90
        admin_options = None
        # Credentials are stable across interruption. Blank root is attempted only
        # on owned, staged, network-disabled fresh initialization.
        with option_file(state, 'root', root_password) as secured, option_file(state, 'root', '') as initial:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise BootstrapError(f'Staged MySQL server exited before SQL readiness (exit {process.returncode}); see logs/mysql-bootstrap-engine.log')
                for candidate in (secured, initial):
                    try:
                        with Mysql(mysql, candidate, socket) as admin:
                            observed = identity(admin, expected_version)
                            if (observed['uuid'] != owned_uuid
                                    or observed['datadir'] != str(stage.resolve())):
                                raise BootstrapError('SQL instance does not match owned staging datadir')
                            if process.poll() is not None:
                                raise BootstrapError('Owned MySQL process exited before provisioning')
                            if candidate == initial:
                                admin.query(f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{root_password}'")
                        admin_options = secured
                        break
                    except BootstrapError:
                        continue
                if admin_options:
                    break
                time.sleep(0.1)
            if not admin_options:
                raise BootstrapError('Staged MySQL authentication did not become ready')
            report = provision(mysql, state, expected_version, admin_options, socket,
                               receipt_name='.database-staged-bootstrap.json')
        progress |= {'phase': 'ready-to-promote', 'uuid': report['uuid']}
        atomic_json(journal, progress)
    finally:
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired as error:
                    process.kill()
                    process.wait(timeout=5)
                    raise BootstrapError('Staged MySQL did not stop cleanly; staging preserved') from error
        finally:
            capture.finish()
    if process.returncode != 0:
        raise BootstrapError('Staged MySQL shutdown failed; staging preserved')
    if target.exists():
        target.rmdir()  # Succeeds only for the renderer-created empty directory.
    os.rename(stage, target)
    sync_directory(state)
    report['datadir'] = str(target.resolve())
    atomic_json(receipt_path, {key: report[key] for key in ('format', 'engine', 'version', 'uuid', 'datadir', 'databases', 'application_schemas_populated')})
    journal.unlink(missing_ok=True)
    (state / '.database-staged-bootstrap.json').unlink(missing_ok=True)
    sync_directory(state)
    return report | {'operation': 'initialized', 'server_running': False,
                     'next': 'Start the owned instance, then run verify'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('initialize', 'provision', 'verify'))
    parser.add_argument('--state-root', type=Path, required=True)
    parser.add_argument('--mysql', type=Path, required=True)
    parser.add_argument('--mysqld', type=Path)
    parser.add_argument('--admin-options', type=Path)
    parser.add_argument('--expected-version', required=True)
    args = parser.parse_args()
    try:
        exact_version(args.expected_version)
        state = private_path(args.state_root)
        if not args.mysql.is_absolute() or (args.mysqld and not args.mysqld.is_absolute()):
            raise BootstrapError('Executable paths must be absolute')
        with state_lock(state):
            if args.operation == 'initialize':
                if not args.mysqld:
                    raise BootstrapError('initialize requires --mysqld')
                result = initialize(args.mysqld, args.mysql, state, args.expected_version)
            elif args.operation == 'provision':
                if not args.admin_options:
                    raise BootstrapError('provision requires a private --admin-options file')
                result = provision(args.mysql, state, args.expected_version, args.admin_options)
            else:
                result = verify(args.mysql, state, args.expected_version)
        print(json.dumps(result, indent=2))
        return 0
    except (BootstrapError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Bootstrap failed: {error}', file=__import__('sys').stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
