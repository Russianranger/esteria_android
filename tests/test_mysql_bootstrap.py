"""Filesystem guards locally; engine behavior against a real disposable MySQL 8.

Set ESTERIA_MYSQL_INTEGRATION=1, ESTERIA_MYSQL_ADMIN_OPTIONS, and
ESTERIA_MYSQL_VERSION to require the dedicated service test. The test owns only
the four Esteria databases/account on this disposable instance; never point it
at a user installation.
"""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
import re

from runtime.mysql_bootstrap import (BootstrapError, DATABASES, FORMAT, Mysql,
                                     atomic_json, identity, initialize, option_file,
                                     private_path, provision, read_secret, state_lock,
                                     verify, exact_version, EngineCapture, ENGINE_LOG_LIMIT,
                                     run_engine, initialization_command)


def preserve_engine_diagnostics(state: Path):
    """Export only bounded engine tails; never copy accounts, option files or datadirs."""
    destination = os.environ.get('ESTERIA_MYSQL_DIAGNOSTICS_DIR')
    if not destination:
        return
    target = private_path(Path(destination))
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ('mysql-initialize-engine.log', 'mysql-bootstrap-engine.log',
                 'mysql-restart-engine.log', 'mysql-container-engine.log'):
        source = private_path(state / 'logs' / name)
        if not source.is_file():
            continue
        with source.open('rb') as stream:
            stream.seek(max(0, source.stat().st_size - ENGINE_LOG_LIMIT))
            content = stream.read(ENGINE_LOG_LIMIT)
        if len(content) == ENGINE_LOG_LIMIT:
            # A truncated first line could contain only part of a credential.
            newline = content.find(b'\n')
            content = content[newline + 1:] if newline >= 0 else b''
        # Bootstrap secrets are exactly 64 hexadecimal characters. Preserve no
        # such value even if an exceptional engine diagnostic includes SQL text.
        content = re.sub(rb'[0-9a-fA-F]{64}', b'[redacted-64-hex-value]', content)
        output = private_path(target / name)
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)


@contextmanager
def initialization_state():
    with tempfile.TemporaryDirectory(prefix='est-db-') as name:
        state = Path(name)
        try:
            yield state
        except BaseException:
            preserve_engine_diagnostics(state)
            raise


class FilesystemGuards(unittest.TestCase):
    def test_fresh_initializer_uses_exclusive_private_temporary_storage(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); run=root/'run';run.mkdir(mode=0o700)
            stage=root/'database-initializing'
            command=initialization_command(Path('/exact/mysqld'),stage,run)
            temporary=run/'initialize-tmp'
            self.assertIn('--tmpdir='+str(temporary),command)
            self.assertIn('--datadir='+str(stage),command)
            self.assertIn('--no-defaults',command);self.assertIn('--skip-networking',command)
            self.assertEqual(temporary.stat().st_mode&0o777,0o700)
            marker=temporary/'preserve';marker.write_bytes(b'uncertain prior temporary state')
            with self.assertRaises(FileExistsError):initialization_command(Path('/exact/mysqld'),stage,run)
            self.assertEqual(marker.read_bytes(),b'uncertain prior temporary state')

    def test_initializer_temporary_path_cannot_follow_links_or_select_multiple_directories(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);run=root/'run';run.mkdir();outside=root/'outside';outside.mkdir()
            (run/'initialize-tmp').symlink_to(outside,target_is_directory=True)
            with self.assertRaisesRegex(BootstrapError,'Symlink'):
                initialization_command(Path('/mysqld'),root/'stage',run)
            self.assertEqual(list(outside.iterdir()),[])
            other=root/'multiple:paths';other.mkdir()
            with self.assertRaisesRegex(BootstrapError,'multiple directories'):
                initialization_command(Path('/mysqld'),root/'stage',other)
            self.assertFalse((other/'initialize-tmp').exists())

    def test_legacy_hidden_staging_is_preserved_not_reinitialized(self):
        with tempfile.TemporaryDirectory() as name:
            state = Path(name)
            legacy = state / '.database-initializing'
            legacy.mkdir()
            sentinel = legacy / 'undo_001'
            sentinel.write_bytes(b'preserve failed initialization')
            with self.assertRaisesRegex(BootstrapError, 'Legacy hidden staging datadir is preserved'):
                initialize(Path('/missing/mysqld'), Path('/missing/mysql'), state, '8.0.44')
            self.assertEqual(sentinel.read_bytes(), b'preserve failed initialization')
            self.assertFalse((state / 'database-initializing').exists())

    def test_engine_diagnostics_are_bounded_private_and_redacted_for_export(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            log = root / 'state/logs/mysql-bootstrap-engine.log'
            secret = 'a' * 64
            code = "import sys;sys.stderr.write('x' * 200000 + '\\nengine-secret=" + secret + "\\nfinal diagnostic\\n')"
            self.assertEqual(run_engine([sys.executable, '-c', code], log, timeout=10), 0)
            self.assertLessEqual(log.stat().st_size, ENGINE_LOG_LIMIT)
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)
            previous = os.environ.get('ESTERIA_MYSQL_DIAGNOSTICS_DIR')
            os.environ['ESTERIA_MYSQL_DIAGNOSTICS_DIR'] = str(root / 'export')
            try:
                preserve_engine_diagnostics(root / 'state')
            finally:
                if previous is None:
                    os.environ.pop('ESTERIA_MYSQL_DIAGNOSTICS_DIR')
                else:
                    os.environ['ESTERIA_MYSQL_DIAGNOSTICS_DIR'] = previous
            exported = (root / 'export/mysql-bootstrap-engine.log').read_text()
            self.assertNotIn(secret, exported)
            self.assertTrue(exported.endswith('final diagnostic\n'))
            self.assertNotIn('x' * 100, exported)

    def test_version_pin_accepts_full_distro_suffix_without_wildcards(self):
        for value in ('8.0.44', '8.0.44-0ubuntu0.24.04.2', '8.4.7-1ubuntu24.04', '8.0.44+vendor.1'):
            exact_version(value)
        for value in ('8', '8.0', '8.0.*', '8.0.44 anything', '8.0.44;SELECT 1',
                      '10.11.8-MariaDB', '8.0.44-MariaDB', '8.0.44\n'):
            with self.assertRaises(BootstrapError):
                exact_version(value)

    def test_credential_is_stable_private_and_never_replaces_corrupt_data(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'accounts/database-root-secret'
            first = read_secret(path, create=True)
            self.assertEqual(first, read_secret(path, create=True))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            path.write_text('existing-invalid-credential')
            with self.assertRaisesRegex(BootstrapError, 'refusing to replace'):
                read_secret(path, create=True)
            self.assertEqual(path.read_text(), 'existing-invalid-credential')

    def test_nonempty_unowned_datadir_is_never_initialized(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            marker = root / 'database/player-data'
            marker.parent.mkdir()
            marker.write_bytes(b'preserve me')
            # Nonexistent executables prove rejection precedes engine execution.
            with self.assertRaisesRegex(BootstrapError, 'Nonempty datadir'):
                initialize(Path('/missing/mysqld'), Path('/missing/mysql'), root, '8.0.44')
            self.assertEqual(marker.read_bytes(), b'preserve me')
            self.assertFalse((root / 'database-initializing').exists())

    def test_symlinked_datadir_and_credentials_fail_closed(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            outside = root / 'outside'
            outside.mkdir()
            state = root / 'state'
            state.mkdir()
            (state / 'database').symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(BootstrapError, 'Symlink'):
                initialize(Path('/missing/mysqld'), Path('/missing/mysql'), state, '8.0.44')
            (state / 'accounts').symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(BootstrapError, 'Symlink'):
                read_secret(state / 'accounts/database-secret', create=True)
            self.assertEqual(list(outside.iterdir()), [])

    def test_stored_receipt_requires_uuid_and_reports_no_sql_readiness(self):
        with tempfile.TemporaryDirectory() as name:
            state = Path(name)
            datadir = state / 'database'
            datadir.mkdir()
            receipt = {'format': FORMAT, 'engine': 'mysql', 'version': '8.0.44',
                       'uuid': 'f28dc207-e269-11ed-bc2a-0242ac120002',
                       'datadir': str(datadir),
                       'databases': list(DATABASES), 'application_schemas_populated': False}
            atomic_json(state / 'database-bootstrap.json', receipt)
            (datadir / 'auto.cnf').write_text('[auto]\nserver-uuid=' + receipt['uuid'] + '\n')
            report = initialize(Path('/missing/mysqld'), Path('/missing/mysql'), state, '8.0.44')
            self.assertFalse(report['sql_authenticated'])
            with self.assertRaisesRegex(BootstrapError, 'receipt mismatch for version'):
                initialize(Path('/missing/mysqld'), Path('/missing/mysql'), state, '8.0.45')
            (datadir / 'auto.cnf').write_text('[auto]\nserver-uuid=00000000-0000-0000-0000-000000000000\n')
            with self.assertRaisesRegex(BootstrapError, 'UUID'):
                initialize(Path('/missing/mysqld'), Path('/missing/mysql'), state, '8.0.44')

    def test_interrupted_owned_promotion_finishes_receipt_without_engine_or_reseed(self):
        with tempfile.TemporaryDirectory() as name:
            state = Path(name)
            datadir = state / 'database'
            datadir.mkdir()
            marker = datadir / 'persistent-marker'
            marker.write_bytes(b'preserved after rename')
            receipt = {'format': FORMAT, 'engine': 'mysql', 'version': '8.0.44',
                       'uuid': 'f28dc207-e269-11ed-bc2a-0242ac120002',
                       'datadir': str(state / 'database-initializing'),
                       'databases': list(DATABASES), 'application_schemas_populated': False}
            atomic_json(state / '.database-staged-bootstrap.json', receipt)
            atomic_json(state / '.database-initialization.json',
                        {'format': FORMAT, 'version': '8.0.44', 'phase': 'ready-to-promote',
                         'uuid': receipt['uuid']})
            auto = datadir / 'auto.cnf'
            auto.write_text('[auto]\nserver-uuid=00000000-0000-0000-0000-000000000000\n')
            with self.assertRaisesRegex(BootstrapError, 'Nonempty datadir'):
                initialize(Path('/missing/mysqld'), Path('/missing/mysql'), state, '8.0.44')
            self.assertFalse((state / 'database-bootstrap.json').exists())
            auto.write_text('[auto]\nserver-uuid=' + receipt['uuid'] + '\n')
            report = initialize(Path('/missing/mysqld'), Path('/missing/mysql'), state, '8.0.44')
            self.assertEqual(report['operation'], 'recovered-promotion')
            self.assertFalse(report['sql_authenticated'])
            self.assertEqual(json.loads((state / 'database-bootstrap.json').read_text()),
                             receipt | {'datadir': str(datadir)})
            self.assertEqual(marker.read_bytes(), b'preserved after rename')
            self.assertFalse((state / '.database-initialization.json').exists())

    def test_another_process_cannot_enter_bootstrap(self):
        with tempfile.TemporaryDirectory() as name:
            state = Path(name)
            with state_lock(state):
                code = ('from pathlib import Path; from runtime.mysql_bootstrap import state_lock; '
                        f'context = state_lock(Path({name!r})); context.__enter__()')
                result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Another bootstrap operation', result.stderr)

    def test_option_file_is_private_and_removed_even_on_failure(self):
        with tempfile.TemporaryDirectory() as name:
            path = None
            with self.assertRaises(RuntimeError):
                with option_file(Path(name), 'esteria', 'a' * 64) as path:
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    raise RuntimeError('interrupted')
            self.assertFalse(path.exists())


@unittest.skipUnless(os.environ.get('ESTERIA_MYSQL_INTEGRATION') == '1',
                     'requires explicit disposable real MySQL 8 service')
class RealMysqlIntegration(unittest.TestCase):
    def test_authentication_provision_recovery_and_preservation(self):
        executable = shutil.which('mysql')
        self.assertIsNotNone(executable, 'integration was requested but mysql is unavailable')
        mysql = Path(executable)
        admin = private_path(Path(os.environ['ESTERIA_MYSQL_ADMIN_OPTIONS']))
        version = os.environ['ESTERIA_MYSQL_VERSION']
        # Wait by authenticating/querying, never by observing an open TCP port.
        deadline = time.monotonic() + 180
        while True:
            try:
                with Mysql(mysql, admin) as connection:
                    identity(connection, version)
                break
            except BootstrapError:
                if time.monotonic() >= deadline:
                    self.fail('real MySQL service did not become SQL-ready')
                time.sleep(1)
        with tempfile.TemporaryDirectory(prefix='esteria-mysql-test-') as name:
            state = Path(name)
            secret = state / 'accounts/database-secret'
            original = read_secret(secret, create=True)
            with state_lock(state), Mysql(mysql, admin) as connection:
                # A mistaken existing installation is rejected, never adopted.
                connection.query('CREATE DATABASE acore_auth')
                with self.assertRaisesRegex(BootstrapError, 'Existing unowned'):
                    provision(mysql, state, version, admin)
                connection.query('DROP DATABASE acore_auth')  # Disposable test fixture only.
                # Recover a durable ownership receipt interrupted before DDL.
                atomic_json(state / 'database-bootstrap.json.pending', identity(connection, version)
                            | {'credential_sha256': hashlib.sha256(original.encode()).hexdigest()})
                first = provision(mysql, state, version, admin)
                self.assertEqual(first['operation'], 'provisioned')
                self.assertTrue(first['sql_authenticated'])
                self.assertFalse(first['application_schemas_populated'])
                for database in DATABASES:
                    self.assertEqual(connection.query(
                        f"SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='{database}'"), ['0'])
                connection.query('CREATE TABLE acore_characters.persistence_probe '
                                 '(id INT PRIMARY KEY, value VARCHAR(32) NOT NULL)')
                connection.query("INSERT INTO acore_characters.persistence_probe VALUES (1, 'character-sentinel')")
                again = provision(mysql, state, version, admin)
                self.assertEqual(again['operation'], 'verified-existing')
                self.assertTrue(verify(mysql, state, version)['sql_authenticated'])
                # A global SQL lock prevents a second installation touching DBs.
                connection.query("SELECT GET_LOCK('esteria-local-bootstrap', 0)")
                with self.assertRaisesRegex(BootstrapError, 'Another bootstrap connection'):
                    provision(mysql, state, version, admin)
                connection.query("SELECT RELEASE_LOCK('esteria-local-bootstrap')")
                secret.write_text('b' * 64 + '\n')
                with self.assertRaises(BootstrapError):
                    provision(mysql, state, version, admin)
                with self.assertRaises(BootstrapError):
                    verify(mysql, state, version)
                secret.write_text(original + '\n')
                with self.assertRaisesRegex(BootstrapError, 'version mismatch'):
                    provision(mysql, state, '8.99.99', admin)
                receipt = state / 'database-bootstrap.json'
                saved = receipt.read_bytes()
                changed = json.loads(saved)
                changed['uuid'] = '00000000-0000-0000-0000-000000000000'
                atomic_json(receipt, changed)
                with self.assertRaisesRegex(BootstrapError, 'receipt mismatch for uuid'):
                    verify(mysql, state, version)
                receipt.write_bytes(saved)
                self.assertEqual(connection.query('SELECT value FROM acore_characters.persistence_probe'),
                                 ['character-sentinel'])
                with option_file(state, 'esteria', original) as app_options, Mysql(mysql, app_options) as app:
                    app.query("UPDATE acore_characters.persistence_probe SET value='saved-again' WHERE id=1")
                    self.assertEqual(app.query('SELECT value FROM acore_characters.persistence_probe'), ['saved-again'])
                    # No server-wide or credential-table privileges granted.
                    with self.assertRaises(BootstrapError):
                        app.query('SELECT authentication_string FROM mysql.user')
                receipt.unlink()
                with self.assertRaisesRegex(BootstrapError, 'Existing unowned'):
                    provision(mysql, state, version, admin)
                self.assertEqual(connection.query('SELECT value FROM acore_characters.persistence_probe'), ['saved-again'])


@unittest.skipUnless(os.environ.get('ESTERIA_MYSQL_INITIALIZE') == '1',
                     'requires explicit disposable real MySQL 8 binaries')
class RealMysqlInitialization(unittest.TestCase):
    def test_initialize_promote_restart_and_persist(self):
        mysql = Path(shutil.which('mysql') or '/missing/mysql')
        mysqld = Path(os.environ['ESTERIA_MYSQLD_PATH'])
        version = os.environ['ESTERIA_MYSQL_INITIALIZE_VERSION']
        with initialization_state() as state:
            password = read_secret(state / 'accounts/database-secret', create=True)
            with state_lock(state):
                report = initialize(mysqld, mysql, state, version)
                self.assertEqual(report['operation'], 'initialized')
                self.assertFalse(report['server_running'])
                self.assertEqual(report['datadir'], str(state / 'database'))
                again = initialize(mysqld, mysql, state, version)
                self.assertEqual(again['operation'], 'already-initialized')
                self.assertFalse(again['sql_authenticated'])
                self.assertEqual(read_secret(state / 'accounts/database-secret'), password)
            # Reconstruct the durable crash window: successful datadir rename,
            # staged receipt and journal durable, final receipt not yet written.
            receipt = state / 'database-bootstrap.json'
            staged = json.loads(receipt.read_text())
            staged['datadir'] = str(state / 'database-initializing')
            atomic_json(state / '.database-staged-bootstrap.json', staged)
            atomic_json(state / '.database-initialization.json',
                        {'format': FORMAT, 'version': version, 'phase': 'ready-to-promote', 'uuid': staged['uuid']})
            receipt.unlink()
            with state_lock(state):
                self.assertEqual(initialize(mysqld, mysql, state, version)['operation'], 'recovered-promotion')
            command = [str(mysqld), '--no-defaults', f'--datadir={state / "database"}',
                       '--port=13306', '--bind-address=127.0.0.1', '--mysqlx=OFF',
                       '--secure-file-priv=NULL',
                       f'--socket={state / "run/mysql.sock"}', f'--pid-file={state / "run/mysql.pid"}',
                       '--innodb-buffer-pool-size=128M', '--performance-schema=OFF']
            if os.geteuid() == 0:
                command.append('--user=root')
            for iteration in range(2):
                capture = EngineCapture(command, state / 'logs/mysql-restart-engine.log')
                process = capture.process
                try:
                    deadline = time.monotonic() + 90
                    while True:
                        self.assertIsNone(process.poll(), 'owned MySQL exited during startup')
                        try:
                            with state_lock(state):
                                verify(mysql, state, version)
                            break
                        except BootstrapError:
                            if time.monotonic() >= deadline:
                                self.fail('owned MySQL did not become SQL-ready')
                            time.sleep(.2)
                    with option_file(state, 'esteria', password) as options, Mysql(mysql, options) as app:
                        if iteration == 0:
                            app.query('CREATE TABLE acore_characters.persistence_probe (id INT PRIMARY KEY, value INT)')
                            app.query('INSERT INTO acore_characters.persistence_probe VALUES (1, 12340)')
                        self.assertEqual(app.query('SELECT value FROM acore_characters.persistence_probe WHERE id=1'), ['12340'])
                finally:
                    try:
                        if process.poll() is None:
                            process.terminate()
                            try:
                                process.wait(timeout=60)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait(timeout=5)
                                self.fail('owned MySQL did not stop cleanly')
                    finally:
                        capture.finish()
                self.assertEqual(process.returncode, 0)


if __name__ == '__main__':
    unittest.main()
