import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import qualify_playerbots_database as qualify


class PlayerbotsQualificationGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(self, output):
        return qualify.run(Path('/install'), Path('/content'), 'a'*64, Path('/lock'), Path('/mysql'),
                           Path('/mysqld'), '8.0.46', output, Path('/reference'), Path('/receipt'), 'b'*64)

    def test_existing_state_never_verifies_or_executes_any_component(self):
        saved = self.root / 'saved-character'; saved.write_text('preserve')
        with patch.object(qualify, 'verify_reference') as reference, patch.object(qualify.auth, 'run') as create:
            with self.assertRaisesRegex(ValueError, 'existing fixture preserved'):
                self.invoke(self.root)
        reference.assert_not_called(); create.assert_not_called()
        self.assertEqual(saved.read_text(), 'preserve')

    def test_invalid_reference_rejected_before_fresh_sql_or_authentication(self):
        with (patch.object(qualify, 'verify_reference', side_effect=ValueError('reference rejected')),
              patch.object(qualify.auth, 'run') as create):
            with self.assertRaisesRegex(ValueError, 'reference rejected'):
                self.invoke(self.root / 'new')
        create.assert_not_called()
        self.assertFalse((self.root / 'new').exists())

    def test_reference_receipt_digest_is_independent_and_checked_before_elf(self):
        with (patch.object(qualify.modules, 'read_json', return_value=({}, {'sha256': 'a'*64})),
              patch.object(qualify.base, 'locked_source', return_value=({}, 'c'*64)),
              patch.object(qualify.files, 'identity') as executable):
            with self.assertRaisesRegex(ValueError, 'receipt digest mismatch'):
                qualify.verify_reference(Path('/reference'), Path('/receipt'), 'b'*64, Path('/install'), Path('/lock'))
        executable.assert_not_called()

    def test_update_ledger_rejects_missing_extra_and_rehashed_sql(self):
        connection = Mock(); digest = 'a'*40
        expected = {'source.sql': (digest, 'RELEASED')}
        valid = 'source.sql\t' + digest + '\tRELEASED'
        connection.query.side_effect = [['updates','updates_include'], [valid]]
        self.assertEqual(qualify.playerbots_snapshot(connection, expected)['updateCount'], 1)
        for rows in ([], [valid, 'extra.sql\t' + digest + '\tRELEASED'],
                     ['source.sql\t' + 'b'*40 + '\tRELEASED'], [valid, valid]):
            connection.query.side_effect = [['updates','updates_include'], rows]
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                qualify.playerbots_snapshot(connection, expected)

    def test_account_comparison_hex_encodes_binary_and_text_fields_privately(self):
        connection = Mock(); connection.query.return_value = []
        snapshot = qualify.preserved_core(connection)
        queries = [call.args[0] for call in connection.query.call_args_list if 'FROM acore_auth.account ' in call.args[0]]
        self.assertEqual(len(queries), 1)
        for column in qualify.account.COLUMNS['account']:
            self.assertIn('HEX(`' + column[0] + '`)', queries[0])
        self.assertEqual(snapshot['accounts'], [])

    def test_successful_process_requires_the_actual_loader_completion_marker(self):
        executable = self.root / 'reference'; config = self.root / 'worldserver.conf'
        config.write_text('private fixture')
        executable.write_text('#!/usr/bin/python3\nprint("loaded nothing")\n'); executable.chmod(0o700)
        with self.assertRaisesRegex(ValueError, 'completion marker missing'):
            qualify.run_reference(executable, config, self.root / 'first.log')
        executable.write_text('#!/usr/bin/python3\nprint("ESTERIA_PLAYERBOTS_DATABASE_REFERENCE_COMPLETE '
                              'statements=52 mysqlClientLibrary=8.0.46")\n')
        self.assertEqual(qualify.run_reference(executable, config, self.root / 'second.log'),
                         dict(exitCode=0, preparedStatementCount=52))
        self.assertEqual((self.root / 'second.log').stat().st_mode & 0o777, 0o600)

    def test_probe_can_only_create_its_fixed_disposable_table(self):
        connection = Mock(); connection.query.side_effect = [[], [], ['a'*64]]
        qualify.marker(connection, 'a'*64, create=True)
        self.assertEqual(connection.query.call_count, 3)
        self.assertTrue(all('acore_playerbots.esteria_reference_probe' in call.args[0]
                            for call in connection.query.call_args_list))
        connection.query.side_effect = [['wrong']]
        with self.assertRaisesRegex(ValueError, 'persistence marker changed'):
            qualify.marker(connection, 'a'*64)

    def test_actual_pinned_configuration_keys_render_without_mutating_generation(self):
        server = Path(os.environ.get('ESTERIA_SERVER_SOURCE', qualify.reference.ROOT / 'sources/server'))
        if not (server / '.git').exists():
            server = qualify.reference.ROOT.parent / 'server-src'
        if not (server / '.git').exists():
            self.skipTest('requires pinned server Git objects')
        inputs = {'worldserver.conf': 'src/server/apps/worldserver/worldserver.conf.dist',
                  'modules/playerbots.conf': 'modules/mod-playerbots/conf/playerbots.conf.dist'}
        generation = self.root / 'config/generations/fixture'
        original = {}
        for destination, source in inputs.items():
            data = subprocess.check_output(['git', 'show', qualify.base.content.SUPPORTED_SERVER + ':' + source], cwd=server)
            path = generation / destination; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            original[destination] = data
        (self.root / 'run').mkdir()
        configuration = qualify.render_configuration(self.root, 'fixture')
        self.assertIn('Updates.AutoSetup = 0', configuration.read_text())
        self.assertIn('Playerbots.Updates.EnableDatabases = 1',
                      (configuration.parent / 'modules/playerbots.conf').read_text())
        for name, data in original.items():
            self.assertEqual((generation / name).read_bytes(), data)
        with self.assertRaises(FileExistsError):
            qualify.render_configuration(self.root, 'fixture')


if __name__ == '__main__':
    unittest.main()
