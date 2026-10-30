"""Android wrapper persistence boundaries; actual MySQL is qualified separately."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

RUNTIME = Path(__file__).resolve().parents[1] / 'runtime'
sys.path.insert(0, str(RUNTIME))
import android_database_setup as adapter
import mysql_bootstrap as bootstrap

VERSION = '8.0.46-0ubuntu0.24.04.4'
UUID = '12345678-1234-4234-8234-123456789abc'


class AndroidDatabaseSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state'
        self.state.mkdir(mode=0o700)

    def call(self):
        return adapter.setup(self.state, Path('/usr/bin/mysql'), Path('/usr/sbin/mysqld'), VERSION)

    def receipt(self):
        accounts = self.state / 'accounts'
        accounts.mkdir(mode=0o700, exist_ok=True)
        bootstrap.read_secret(accounts / 'database-secret', create=True)
        bootstrap.read_secret(accounts / 'database-root-secret', create=True)
        database = self.state / 'database'
        database.mkdir(mode=0o700)
        (database / 'auto.cnf').write_text('[auto]\nserver-uuid=' + UUID + '\n')
        value = {'format': 1, 'engine': 'mysql', 'version': VERSION, 'uuid': UUID,
                 'datadir': str(database), 'databases': list(bootstrap.DATABASES),
                 'application_schemas_populated': False}
        bootstrap.atomic_json(self.state / 'database-bootstrap.json', value)
        return value

    def test_completed_setup_reuses_actual_filesystem_receipt_without_starting_engine(self):
        self.receipt()
        before = {p: p.read_bytes() for p in (self.state / 'accounts').iterdir()}
        with mock.patch.object(bootstrap.subprocess, 'Popen', side_effect=AssertionError('No engine on completed path')):
            result = self.call()
        self.assertEqual(result['operation'], 'already-initialized')
        self.assertFalse(result['liveSqlAuthenticated'])
        self.assertFalse(result['persistentServiceStarted'])
        self.assertEqual(result['uuid'], UUID)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertEqual(set(result), {'formatVersion', 'scope', 'operation', 'version', 'uuid', 'datadir',
                                      'databases', 'persistentServiceStarted', 'liveServiceStateVerified', 'liveSqlAuthenticated', 'bootstrapPopulatedApplicationSchemas'})

    def test_missing_application_secret_is_never_regenerated_over_existing_database(self):
        self.receipt()
        secret = self.state / 'accounts/database-secret'
        secret.unlink()
        with self.assertRaises(bootstrap.BootstrapError): self.call()
        self.assertFalse(secret.exists())

    def test_missing_root_secret_is_not_hidden_by_completed_receipt(self):
        self.receipt()
        (self.state / 'accounts/database-root-secret').unlink()
        with self.assertRaises(bootstrap.BootstrapError): self.call()

    def test_partial_data_without_secret_is_preserved_without_adoption(self):
        data = self.state / 'database-initializing'
        data.mkdir()
        sentinel = data / 'preserve'
        sentinel.write_bytes(b'existing-partial-data')
        with self.assertRaises(bootstrap.BootstrapError): self.call()
        self.assertEqual(sentinel.read_bytes(), b'existing-partial-data')
        self.assertFalse((self.state / 'accounts/database-secret').exists())

    def test_symlinked_state_is_rejected(self):
        original = self.state
        link = original.parent / 'link'
        link.symlink_to(original, target_is_directory=True)
        self.state = link
        with self.assertRaises(bootstrap.BootstrapError): self.call()
        self.assertFalse((original / 'accounts').exists())

    def test_receipt_uuid_disagreement_is_rejected(self):
        self.receipt()
        (self.state / 'database/auto.cnf').write_text('server-uuid=22345678-1234-4234-8234-123456789abc\n')
        with self.assertRaises(bootstrap.BootstrapError): self.call()

    def test_failure_diagnostics_preserve_errno_without_exception_contents(self):
        private = 'private-credential-and-query-text'
        error = OSError(38, private, '/private/path/' + private)
        with mock.patch.object(bootstrap, 'private_path', side_effect=error):
            try:
                self.call()
            except OSError as caught:
                message = adapter.failure_diagnostic(caught)
        self.assertIn('OSError; errno=38', message)
        self.assertIn('setup:', message)
        self.assertNotIn(private, message)
        self.assertNotIn('/private/path', message)
        self.assertNotIn('test_failure_', message)
        self.assertEqual(adapter.failure_diagnostic(bootstrap.BootstrapError(private)), 'BootstrapError')


if __name__ == '__main__':
    unittest.main()
