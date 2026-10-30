import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import qualify_base_sql as base


class BaseGuardTests(unittest.TestCase):
    def test_existing_fixture_never_calls_engine_or_changes_saved_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            saved = output / 'saved-character'
            saved.write_bytes(b'keep this save')
            with patch.object(base.db, 'initialize') as initialize, self.assertRaisesRegex(ValueError, 'existing fixture'):
                base.run(Path('/mysql'), Path('/mysqld'), output, '0' * 64, output / 'lock', output, '8.0.46')
            initialize.assert_not_called()
            self.assertEqual(saved.read_bytes(), b'keep this save')
            self.assertEqual(list(output.iterdir()), [saved])

    def test_all_four_databases_must_be_empty_before_any_import(self):
        connection = Mock()
        connection.query.side_effect = [[], [], [], ['character_owned_bot_data']]
        apply = Mock()
        with self.assertRaisesRegex(ValueError, 'nonempty database preserved'):
            base.load_bases(connection, {name: ['base.sql'] for name in base.DB_ORDER}, apply)
        apply.assert_not_called()
        self.assertEqual(connection.query.call_count, 4)

    def test_database_change_before_its_phase_stops_without_reseeding_it(self):
        connection = Mock()
        connection.query.side_effect = [[], [], [], [], [], ['changed_after_initial_check']]
        apply = Mock()
        with self.assertRaisesRegex(ValueError, 'changed before base phase'):
            base.load_bases(connection, {name: ['base.sql'] for name in base.DB_ORDER}, apply)
        apply.assert_called_once_with('auth', 'base.sql')

    def test_sql_failure_stops_before_next_file(self):
        connection = Mock()
        connection.query.return_value = []
        apply = Mock(side_effect=ValueError('real SQL error'))
        with self.assertRaisesRegex(ValueError, 'real SQL error'):
            base.load_bases(connection, {name: ['first.sql', 'second.sql'] for name in base.DB_ORDER}, apply)
        apply.assert_called_once_with('auth', 'first.sql')

    def test_client_uses_private_options_without_password_or_reconnection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sql, options, log = root / 'a.sql', root / 'private.cnf', root / 'sql.log'
            sql.write_text('SELECT 1;')
            options.write_text('[client]\npassword=private-secret\n')
            with patch.object(base.subprocess, 'run', return_value=Mock(returncode=0)) as execute:
                base.apply_base(Path('/usr/bin/mysql'), options, 'acore_auth', sql, log)
            args, kwargs = execute.call_args
            command = args[0]
            self.assertIn('--defaults-file=' + str(options), command)
            self.assertIn('--skip-reconnect', command)
            self.assertIn('--local-infile=0', command)
            self.assertNotIn('private-secret', ' '.join(command))
            self.assertEqual(kwargs['env']['MYSQL_TEST_LOGIN_FILE'], os.devnull)
            self.assertNotIn('MYSQL_PWD', kwargs['env'])
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_table_set_check_rejects_unexpected_extra_or_missing_tables(self):
        connection = Mock()
        connection.query.return_value = ['owned_character', 'unexpected']
        plan = {name: ['owned_character.sql'] for name in base.DB_ORDER}
        with self.assertRaisesRegex(ValueError, 'table set differs'):
            base.schema_tables(connection, plan)


class SourceFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'repository'
        self.source.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture Test')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.paths = []
        for name in base.DB_ORDER:
            path = self.source / base.content.DATABASES[name][1] / 'example.sql'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'CREATE TABLE `example` (id INT PRIMARY KEY);\n')
            self.paths.append(path)
        self.git('add', '.')
        self.git('commit', '-qm', 'SQL fixture')
        self.pin = {'commit': self.git('rev-parse', 'HEAD')}
        self.lock_hash = '1' * 64
        self.lock = self.root / 'lock.json'
        self.counts = patch.object(base, 'BASE_COUNTS', dict.fromkeys(base.DB_ORDER, 1))
        self.locked = patch.object(base, 'locked_source', return_value=(self.pin, self.lock_hash))
        self.counts.start()
        self.locked.start()
        self.fixture = self.root / 'fixture'

    def tearDown(self):
        self.locked.stop()
        self.counts.stop()
        self.temporary.cleanup()

    def git(self, *arguments):
        return subprocess.check_output(['git', *arguments], cwd=self.source, stderr=subprocess.PIPE).decode().strip()

    def prepare(self):
        return base.prepare(self.source, self.lock, self.fixture)

    def edit_manifest(self, transform):
        path = self.fixture / 'base-fixture.json'
        value = json.loads(path.read_text())
        transform(value)
        path.write_text(json.dumps(value))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_exact_git_bytes_ignore_modified_or_untracked_work(self):
        self.paths[0].write_text('local edits must remain untouched')
        self.paths[0].with_name('untracked.sql').write_text('private scratch')
        digest = self.prepare()
        receipt = base.copy_fixture(self.fixture, digest, self.lock, self.root / 'verified')
        self.assertEqual(sum(len(v) for v in receipt['baseOrder'].values()), 4)
        for rows in receipt['baseOrder'].values():
            self.assertEqual((self.root / 'verified' / rows[0]).read_bytes(),
                             b'CREATE TABLE `example` (id INT PRIMARY KEY);\n')
        self.assertEqual(self.paths[0].read_text(), 'local edits must remain untouched')
        with self.assertRaisesRegex(ValueError, 'existing SQL fixture preserved'):
            self.prepare()

    def test_modified_source_fails_before_mysql_initialization_and_preserves_evidence(self):
        digest = self.prepare()
        path = next((self.fixture / 'source').rglob('example.sql'))
        os.chmod(path, 0o600)
        content = path.read_bytes()
        path.write_bytes(content.replace(b'example', b'changed'))
        output = self.root / 'qualification'
        with patch.object(base.db, 'initialize') as initialize, self.assertRaisesRegex(ValueError, 'hash mismatch'):
            base.run(Path('/mysql'), Path('/mysqld'), self.fixture, digest, self.lock, output, '8.0.46')
        initialize.assert_not_called()
        receipt = json.loads((output / 'qualification.json').read_text())
        self.assertFalse(receipt['qualificationSucceeded'])
        self.assertFalse(receipt['initializedNewInstance'])
        self.assertFalse(receipt['existingStateModified'])
        self.assertIn('hash mismatch', receipt['failure'])
        self.assertTrue((output / 'verified-source').is_dir())

    def test_untrusted_manifest_hash_or_source_revision_rejected(self):
        digest = self.prepare()
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            base.copy_fixture(self.fixture, '0' * 64, self.lock, self.root / 'bad-hash')
        changed = self.edit_manifest(lambda value: value['source'].update(commit='2' * 40))
        with self.assertRaisesRegex(ValueError, 'provenance mismatch'):
            base.copy_fixture(self.fixture, changed, self.lock, self.root / 'bad-source')
        self.assertNotEqual(changed, digest)

    def test_symlink_and_fifo_payloads_are_rejected_without_reading_them(self):
        digest = self.prepare()
        source = next((self.fixture / 'source').rglob('example.sql'))
        source.unlink()
        source.symlink_to(self.paths[0])
        with self.assertRaisesRegex(base.db.BootstrapError, 'Symlink'):
            base.copy_fixture(self.fixture, digest, self.lock, self.root / 'symlink')
        source.unlink()
        os.mkfifo(source)
        with self.assertRaisesRegex(ValueError, 'type/size mismatch'):
            base.copy_fixture(self.fixture, digest, self.lock, self.root / 'fifo')

    def test_path_traversal_and_extra_source_identities_are_rejected(self):
        self.prepare()
        digest = self.edit_manifest(lambda value: value['baseOrder']['auth'].__setitem__(0,
            base.content.DATABASES['auth'][1] + '/../outside.sql'))
        with self.assertRaisesRegex(ValueError, 'unsafe base SQL'):
            base.copy_fixture(self.fixture, digest, self.lock, self.root / 'escape')

    def test_git_blob_identity_is_checked_independently_of_sha256(self):
        self.prepare()
        def tamper(value):
            next(iter(value['baseSources'].values()))['gitBlob'] = '0' * 40
        digest = self.edit_manifest(tamper)
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            base.copy_fixture(self.fixture, digest, self.lock, self.root / 'blob')


if __name__ == '__main__':
    unittest.main()
