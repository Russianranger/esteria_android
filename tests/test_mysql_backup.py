from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from tools import qualify_mysql_backup as backup


class BackupGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    @contextmanager
    def admin(self, connection):
        yield connection, self.root / 'private-options.cnf'

    def test_existing_output_preserves_saves_before_any_tool_or_engine(self):
        saved = self.root / 'saved-character'; saved.write_bytes(b'keep this')
        with patch.object(backup, 'verify_tools') as tools, patch.object(backup.base, 'run') as engine:
            with self.assertRaisesRegex(ValueError, 'existing backup qualification preserved'):
                backup.run(Path('/mysql'), Path('/mysqld'), Path('/dump'), self.root, '0' * 64,
                           self.root / 'lock', self.root, '8.0.46',
                           account_fixture=self.root, account_fixture_sha256='0' * 64)
        tools.assert_not_called(); engine.assert_not_called()
        self.assertEqual(saved.read_bytes(), b'keep this')

    def test_account_fixture_digest_gate_precedes_source_database_creation(self):
        fixture = self.root / 'account-fixture'; fixture.mkdir()
        (fixture / 'account-fixture.json').write_text('{}\n')
        output = self.root / 'new-run'
        with (patch.object(backup, 'verify_tools', return_value={}),
              patch.object(backup, 'verify_dump_options'), patch.object(backup.base, 'run') as engine):
            with self.assertRaisesRegex(ValueError, 'account fixture manifest digest mismatch'):
                backup.run(Path('/mysql'), Path('/mysqld'), Path('/dump'), self.root, '0' * 64,
                           self.root / 'lock', output, '8.0.46',
                           account_fixture=fixture, account_fixture_sha256='0' * 64)
        engine.assert_not_called()
        report = json.loads((output / 'qualification.json').read_text())
        self.assertFalse(report['accountSourceVerified'])
        self.assertFalse(report['sourceBaseSqlQualified'])

    def test_verified_templates_render_before_realm_and_account_without_sql_reimport(self):
        output = self.root / 'new-run'; events = []
        provenance = dict(source={'commit': 'source-fixture'}, sourceLockSha256='b' * 64)
        def source(*args):
            events.append('bases')
            secret = output / 'source/private-state/accounts/database-secret'
            secret.parent.mkdir(parents=True); secret.write_bytes(b'a' * 64 + b'\n')
            return dict(provenance, qualificationSucceeded=True)
        def render(templates, state, data, sql, mysql):
            events.append('render')
            self.assertEqual(templates, output / 'verified-account-source')
            self.assertEqual(sql, output / 'source/verified-source')
            self.assertEqual((state / 'accounts/database-secret').read_bytes(), b'a' * 64 + b'\n')
        def realm(*args):
            events.append('realm')
            raise ValueError('intentional stop after configuration ordering check')
        with (patch.object(backup, 'verify_tools', return_value={}),
              patch.object(backup, 'verify_dump_options'),
              patch.object(backup.account_fixture_tools, 'copy_fixture', return_value=provenance) as copied,
              patch.object(backup.base, 'run', side_effect=source),
              patch.object(backup, 'render', side_effect=render),
              patch.object(backup.db, 'EngineCapture', side_effect=lambda *a: events.append('engine') or Mock()),
              patch.object(backup.base, 'wait_owned'), patch.object(backup.base, 'stop_owned'),
              patch.object(backup.realm, 'provision', side_effect=realm),
              patch.object(backup.account, 'provision') as provision):
            with self.assertRaisesRegex(ValueError, 'intentional stop'):
                backup.run(Path('/mysql'), Path('/mysqld'), Path('/dump'), self.root, '0' * 64,
                           self.root / 'lock', output, '8.0.46',
                           account_fixture=self.root / 'fixture', account_fixture_sha256='c' * 64)
        copied.assert_called_once_with(self.root / 'fixture', 'c' * 64, self.root / 'lock', output / 'verified-account-source')
        self.assertEqual(events, ['bases', 'render', 'engine', 'realm'])
        provision.assert_not_called()
        report = json.loads((output / 'qualification.json').read_text())
        self.assertTrue(report['accountSourceVerified'] and report['sourceConfigurationRendered'])
        self.assertFalse(report['sourceAccountProvisioned'])
        self.assertEqual(report['phase'], 'provision-source-local-realm')

    def test_digest_failure_happens_before_restore_connection_or_sql(self):
        sql = self.root / 'private.sql'; sql.write_bytes(b'private original account rows')
        expected = backup.identity_file(sql)
        sql.write_bytes(b'tampered SQL')
        with patch.object(backup, 'owned_admin') as admin, patch.object(backup, 'run_private') as execute:
            with self.assertRaisesRegex(ValueError, 'backup digest mismatch'):
                backup.restore(Path('/mysql'), self.root, '8.0.46', sql, expected)
        admin.assert_not_called(); execute.assert_not_called()

    def test_nonempty_fourth_database_blocks_all_restore_sql(self):
        sql = self.root / 'private.sql'; sql.write_bytes(b'not executed')
        connection = Mock(); connection.query.side_effect = [[], [], [], ['owned_bot']]
        with patch.object(backup, 'owned_admin', return_value=self.admin(connection)), \
                patch.object(backup, 'run_private') as execute:
            with self.assertRaisesRegex(ValueError, 'nonempty database preserved'):
                backup.restore(Path('/mysql'), self.root, '8.0.46', sql, backup.identity_file(sql))
        execute.assert_not_called()
        self.assertEqual(connection.query.call_count, 4)

    def test_link_fifo_and_oversized_inputs_are_rejected(self):
        sql = self.root / 'private.sql'; sql.write_bytes(b'private')
        link = self.root / 'link'; link.symlink_to(sql)
        with self.assertRaises(backup.db.BootstrapError):
            backup.identity_file(link)
        fifo = self.root / 'fifo'; os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, 'type/size'):
            backup.identity_file(fifo)
        with self.assertRaisesRegex(ValueError, 'type/size'):
            backup.identity_file(sql, 3)
        hardlink = self.root / 'hardlink'; os.link(sql, hardlink)
        with self.assertRaisesRegex(ValueError, 'type/size'):
            backup.identity_file(sql)

    def test_dump_failure_keeps_partial_and_unlocks_without_publishing(self):
        target = self.root / 'dump.sql'
        connection = Mock()
        def fail(command, incoming, outgoing, log):
            outgoing.write(b'partial private account rows')
            raise ValueError('simulated SQL client failure')
        with patch.object(backup, 'owned_admin', return_value=self.admin(connection)), \
                patch.object(backup, 'run_private', side_effect=fail):
            with self.assertRaisesRegex(ValueError, 'simulated'):
                backup.dump(Path('/mysql'), Path('/dump'), self.root, '8.0.46', target)
        self.assertFalse(target.exists())
        self.assertEqual(target.with_name('dump.sql.partial').read_bytes(), b'partial private account rows')
        self.assertEqual(connection.query.call_args_list[-1].args, ('UNLOCK TABLES',))

    def test_dump_never_replaces_newly_appeared_completed_name(self):
        target = self.root / 'dump.sql'; connection = Mock()
        def collision(command, incoming, outgoing, log):
            outgoing.write(b'new backup'); target.write_bytes(b'preserve earlier backup')
        with patch.object(backup, 'owned_admin', return_value=self.admin(connection)), \
                patch.object(backup, 'run_private', side_effect=collision):
            with self.assertRaises(FileExistsError):
                backup.dump(Path('/mysql'), Path('/dump'), self.root, '8.0.46', target)
        self.assertEqual(target.read_bytes(), b'preserve earlier backup')
        self.assertEqual(connection.query.call_args_list[-1].args, ('UNLOCK TABLES',))

    def test_dump_publication_is_private_and_hashes_all_bytes(self):
        target = self.root / 'dump.sql'; connection = Mock()
        payload = bytes(range(256)) * 1000
        def complete(command, incoming, outgoing, log):
            outgoing.write(payload)
        with patch.object(backup, 'owned_admin', return_value=self.admin(connection)), \
                patch.object(backup, 'run_private', side_effect=complete):
            result = backup.dump(Path('/mysql'), Path('/dump'), self.root, '8.0.46', target)
        self.assertEqual(result, dict(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()))
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertFalse(target.with_name('dump.sql.partial').exists())

    def test_fixed_dump_contract_has_four_databases_and_no_credentials(self):
        args = backup.dump_arguments(Path('/usr/bin/mysqldump'), self.root / 'private.cnf', self.root)
        self.assertEqual(args[-4:], list(backup.db.DATABASES))
        self.assertEqual(args[1], '--defaults-file=' + str(self.root / 'private.cnf'))
        self.assertIn('--protocol=SOCKET', args)
        self.assertIn('--single-transaction', args)
        self.assertIn('--hex-blob', args)
        self.assertTrue(all(arg in args for arg in ('--routines', '--events', '--triggers', '--set-gtid-purged=OFF')))
        self.assertFalse(any(arg.startswith(('--password', '-p')) for arg in args if arg != '--protocol=SOCKET'))
        self.assertNotIn('--all-databases', args)
        self.assertNotIn('--connect-timeout=3', args)  # mysql accepts this; mysqldump does not.

    def test_dump_option_preflight_runs_before_any_source_or_engine(self):
        output = self.root / 'new-run'
        with (patch.object(backup, 'verify_tools', return_value={}),
              patch.object(backup, 'verify_dump_options', side_effect=backup.PrivateSqlFailure(
                  2, b"unknown variable 'secret-value'")),
              patch.object(backup.base, 'run') as engine,
              patch.object(backup.account_fixture_tools, 'copy_fixture') as fixture):
            with self.assertRaises(backup.PrivateSqlFailure):
                backup.run(Path('/mysql'), Path('/mysqld'), Path('/dump'), self.root, '0' * 64,
                           self.root / 'lock', output, '8.0.46',
                           account_fixture=self.root, account_fixture_sha256='0' * 64)
        engine.assert_not_called(); fixture.assert_not_called()
        report = json.loads((output / 'qualification.json').read_text())
        self.assertEqual(report['failure'], dict(kind='unsupported-command-option', exitCode=2))
        self.assertFalse(report['dumpOptionsVerified'])
        self.assertNotIn('secret-value', json.dumps(report))

    def test_dump_option_preflight_uses_exact_flags_without_option_or_login_files(self):
        def execute(command, incoming, outgoing, log, timeout):
            self.assertEqual(command[1], '--no-defaults')
            self.assertEqual(command[-1], '--help')
            self.assertEqual(command[2:-1], backup.dump_arguments(Path('/dump'), Path('/x'), Path('/unused-state'))[2:])
            self.assertEqual(backup.ENVIRONMENT['MYSQL_TEST_LOGIN_FILE'], os.devnull)
            self.assertEqual(timeout, 15)
            outgoing.write(b'mysqldump 8.0.46\nUsage: mysqldump [OPTIONS] database\n')
        with patch.object(backup, 'run_private', side_effect=execute):
            backup.verify_dump_options(Path('/dump'), self.root)

    def test_failed_child_exports_only_classification_and_numeric_error(self):
        command = [sys.executable, '-c', 'import os,sys; os.write(2,b"ERROR 1045 private-SQL-secret");sys.exit(2)']
        with self.assertRaises(backup.PrivateSqlFailure) as error:
            backup.run_private(command, subprocess.DEVNULL, subprocess.DEVNULL, self.root / 'failed.private-log')
        self.assertEqual(error.exception.public, dict(kind='sql-process-exit', exitCode=2, mysqlErrorCode=1045))
        self.assertNotIn('private-SQL-secret', str(error.exception))

    def test_canonical_diagnostic_reveals_structure_but_never_private_row_data(self):
        left, right = self.root / 'left.sql', self.root / 'right.sql'
        header = b'USE `acore_auth`;\nCREATE TABLE `account` (\n  `id` int\n) ENGINE=InnoDB;\n'
        left.write_bytes(header + b"INSERT INTO `account` VALUES (1,'private-salt-secret');\n")
        right.write_bytes(header + b"INSERT INTO `account` VALUES (1,'changed-private-session');\n")
        result = backup.dump_difference(left, right)
        self.assertEqual(result['line'], 5)
        self.assertEqual(result['expected']['statementKind'], 'insert')
        self.assertEqual(result['expected']['table'], 'account')
        self.assertNotIn('private', json.dumps(result)); self.assertNotIn('session', json.dumps(result))
        evidence = {}
        with self.assertRaisesRegex(ValueError, 'full logical SQL differs'):
            backup.require_same_dump(evidence, left, right, backup.identity_file(left), backup.identity_file(right))
        self.assertEqual(evidence['canonicalDifference'], result)

    def test_canonical_diagnostic_handles_large_lines_without_exporting_bytes_or_hashes(self):
        left, right = self.root / 'left.sql', self.root / 'right.sql'
        left.write_bytes(b"INSERT INTO `fixture` VALUES ('" + b'x'*100000 + b"');\n")
        right.write_bytes(b"INSERT INTO `fixture` VALUES ('" + b'y'*100000 + b"');\n")
        result = backup.dump_difference(left, right)
        self.assertEqual(result['expected']['table'], 'fixture')
        self.assertEqual(result['expected']['lineBytes'], left.stat().st_size)
        self.assertLess(len(json.dumps(result)), 512)
        self.assertNotIn('sha', json.dumps(result))

    def test_auto_increment_only_diagnostic_does_not_relax_canonical_gate(self):
        left, right = self.root / 'left.sql', self.root / 'right.sql'
        left.write_bytes(b') ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4;\n')
        right.write_bytes(b') ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4;\n')
        evidence = {}
        with self.assertRaises(ValueError):
            backup.require_same_dump(evidence, left, right, backup.identity_file(left), backup.identity_file(right))
        self.assertTrue(evidence['canonicalDifference']['onlyAutoIncrementCounterDiffers'])

    def test_actual_child_stderr_is_drained_and_bounded_privately(self):
        log = self.root / 'private.log'
        command = [sys.executable, '-c', "import os; os.write(2,b'private-SQL-'*20000)"]
        backup.run_private(command, subprocess.DEVNULL, subprocess.DEVNULL, log, timeout=5)
        self.assertEqual(log.stat().st_size, backup.MAX_LOG)
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)
        self.assertTrue(log.read_bytes().endswith(b'private-SQL-'))

    def test_actual_child_deadline_stops_only_owned_process_and_preserves_tail(self):
        log = self.root / 'timeout.private-log'
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            backup.run_private([sys.executable, '-c', 'import time; time.sleep(30)'],
                               subprocess.DEVNULL, subprocess.DEVNULL, log, timeout=0.1)
        self.assertLess(time.monotonic() - started, 5)
        self.assertTrue(log.is_file())

    def test_isolated_size_limiter_enforces_file_bound_without_preexec(self):
        target = self.root / 'limited-output'
        command = backup.base.bounded_file_command(
            [sys.executable, '-c', 'import os; os.write(1,b"X"*65536)'], 1024)
        with target.open('wb') as output:
            result = subprocess.run(command, stdout=output, stderr=subprocess.DEVNULL, timeout=5)
        # Even a program that ignores the short-write result cannot exceed the
        # kernel cap; the caller also validates length/hash before publication.
        self.assertLessEqual(target.stat().st_size, 1024)
        self.assertGreater(target.stat().st_size, 0)


if __name__ == '__main__':
    unittest.main()
