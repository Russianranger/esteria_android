import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import qualify_dbimport as qualify


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


class QualificationGuards(unittest.TestCase):
    def test_existing_state_never_calls_engine(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            saved = root / 'character'; saved.write_text('keep')
            with patch.object(qualify.platform, 'machine', return_value='aarch64'), \
                 patch.object(qualify.db, 'initialize') as initialize, \
                 self.assertRaisesRegex(ValueError, 'existing fixture preserved'):
                qualify.run(root, root, '0' * 64, root / 'lock', Path('/mysql'), Path('/mysqld'), '8.0.46', root)
            initialize.assert_not_called()
            self.assertEqual(saved.read_text(), 'keep')
            self.assertEqual(list(root.iterdir()), [saved])

    def test_compiled_tool_called_without_mutating_dry_run_or_version_flags(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / 'updater'; configuration = root / 'config.cnf'
            configuration.write_text('private fixture configuration')
            executable.write_text('#!/usr/bin/python3\nimport json,os,sys\nprint(json.dumps(dict(args=sys.argv[1:], '
                'secret=os.environ.get("MYSQL_PWD"), reconnect=os.environ.get("AC_DISABLE_INTERACTIVE"))))\n')
            executable.chmod(0o700)
            with patch.dict(os.environ, {'MYSQL_PWD': 'must-not-leak'}):
                result = qualify.run_importer(executable, configuration, root / 'run.log')
            observed = json.loads((root / 'run.log').read_text())
            self.assertEqual(observed['args'], ['--config', str(configuration)])
            self.assertIsNone(observed['secret'])
            self.assertEqual(observed['reconnect'], '1')
            self.assertEqual(result['exitCode'], 0)
            self.assertEqual((root / 'run.log').stat().st_mode & 0o777, 0o600)

    def test_failed_real_process_is_not_qualified_and_output_is_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / 'updater'
            executable.write_text('#!/usr/bin/python3\nimport sys\nsys.stdout.write("x"*400000)\nsys.exit(7)\n')
            executable.chmod(0o700)
            with self.assertRaisesRegex(ValueError, 'exit 7'):
                qualify.run_importer(executable, root / 'config.cnf', root / 'run.log')
            self.assertEqual((root / 'run.log').stat().st_size, qualify.LOG_LIMIT)

    def test_update_ledgers_require_every_selected_nonarchived_hash(self):
        expected = {name: {'source.sql': ('a' * 40, 'MODULE')} for name in qualify.DATABASES}
        connection = Mock()
        connection.query.side_effect = [['updates', 'updates_include'], ['source.sql\t' + 'b' * 40 + '\tMODULE']]
        with self.assertRaisesRegex(ValueError, 'ledger/hash differs'):
            qualify.schema_snapshot(connection, expected)
        connection.query.side_effect = [['updates', 'updates_include'], []]
        with self.assertRaisesRegex(ValueError, 'missing from applied ledger'):
            qualify.schema_snapshot(connection, expected)

    def test_archived_hash_skip_matches_upstream_but_playerbots_must_stay_empty(self):
        expected = {name: {'old.sql': ('a' * 40, 'ARCHIVED')} for name in qualify.DATABASES}
        connection = Mock()
        connection.query.side_effect = [value for name in qualify.DATABASES for value in
            (['updates', 'updates_include'], ['old.sql\t\tARCHIVED'])] + [[]]
        snapshot = qualify.schema_snapshot(connection, expected)
        self.assertEqual(set(snapshot), set(qualify.DATABASES))
        self.assertTrue(all(row['sourceUpdateNamesVerified'] == 1 for row in snapshot.values()))
        connection.query.side_effect = [value for name in qualify.DATABASES for value in
            (['updates', 'updates_include'], ['old.sql\t\tARCHIVED'])] + [['unexpected_bot_table']]
        with self.assertRaisesRegex(ValueError, 'unregistered playerbots'):
            qualify.schema_snapshot(connection, expected)

    def test_export_redacts_both_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); state = root / 'state'; output = root / 'export'
            (state / 'accounts').mkdir(parents=True); (state / 'logs').mkdir(); output.mkdir()
            for name, value in [('database-secret', 'a' * 64), ('database-root-secret', 'b' * 64)]:
                (state / 'accounts' / name).write_text(value + '\n')
            (state / 'logs/dbimport-first.log').write_text('a' * 64 + ' ' + 'b' * 64)
            qualify.redact_importer_logs(state, output)
            self.assertEqual((output / 'dbimport-first.log').read_text(), '[redacted] [redacted]')


class ContentExtraction(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name); self.package = self.root / 'package'; self.package.mkdir()
        self.pin = {'commit': '1' * 40, 'submodules': {qualify.base.content.ELUNA: qualify.base.content.SUPPORTED_ELUNA}}
        self.lock = self.root / 'lock'
        self.lock_mock = patch.object(qualify.base, 'locked_source', return_value=(self.pin, '2' * 64))
        self.lock_mock.start(); self.addCleanup(self.lock_mock.stop)
        self.manifest = dict(source=self.pin, sourceLockSha256='2' * 64, contentSha256Complete=True,
            enabledModules=[], modules=[], elunaFiles={}, databases={}, files={})
        self.payload = {}
        for database in qualify.DATABASES:
            path = qualify.base.content.DATABASES[database][1] + '/updates.sql'
            data = b'CREATE TABLE updates (name VARCHAR(255));\n'
            self.manifest['databases'][database] = dict(base=[path], updateOrder=[], executionOrderQualified=True)
            self.manifest['files'][path] = identity(data)
            self.payload['source/' + path] = data
        self.compiled = dict(formatVersion=1, scope='compiled-server-module-selection',
            generatedListsMatchInstalledBinaries=True, source=self.pin, sourceLockSha256='2' * 64,
            enabledModules=[], configFiles=[], binaries={'dbimport': {}, 'worldserver': {}})
        lua = dict(formatVersion=1, mode='disabled', serverRevision=self.pin['commit'],
            elunaRevision=qualify.base.content.SUPPORTED_ELUNA, files=[])
        self.payload.update({'metadata/content-manifest.json': json.dumps(self.manifest).encode(),
            'metadata/compiled-modules.json': json.dumps(self.compiled).encode(),
            'metadata/lua-map.json': json.dumps(lua).encode()})

    def write(self, *, extra=None, wrong_hash=False, unqualified=False):
        payload = dict(self.payload)
        payload.update(extra or {})
        archive = self.package / 'server-content.tar.gz'
        with tarfile.open(archive, 'w:gz', format=tarfile.GNU_FORMAT) as output:
            for name, data in sorted(payload.items()):
                info = tarfile.TarInfo(name); info.mode = 0o644; info.size = len(data)
                output.addfile(info, io.BytesIO(data))
        receipt = dict(formatVersion=1, scope='immutable-server-source-content-package', source=self.pin,
            sourceLockSha256='2' * 64, moduleSelectionVerified=not unqualified, archiveReadBackVerified=True,
            archive=qualify.files.identity(archive), archiveFiles={name: identity(data) for name, data in payload.items()})
        if wrong_hash:
            next(iter(receipt['archiveFiles'].values()))['sha256'] = '0' * 64
        path = self.package / 'package-receipt.json'; path.write_text(json.dumps(receipt))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_extracts_only_complete_verified_source_payload(self):
        digest = self.write()
        destination = self.root / 'source'
        receipt, manifest, compiled = qualify.unpack_content(self.package, digest, self.lock, destination)
        self.assertEqual(manifest, self.manifest)
        self.assertEqual(compiled, self.compiled)
        self.assertTrue(receipt['moduleSelectionVerified'])
        for path, data in self.payload.items():
            self.assertEqual((destination / path).read_bytes(), data)
            self.assertEqual((destination / path).stat().st_mode & 0o777, 0o400)

    def test_hash_failure_preserves_partial_fixture_without_engine(self):
        digest = self.write(wrong_hash=True)
        with self.assertRaisesRegex(ValueError, 'member digest mismatch'):
            qualify.unpack_content(self.package, digest, self.lock, self.root / 'partial')
        self.assertTrue((self.root / 'partial').exists())

    def test_manual_sql_cannot_enter_source_payload(self):
        digest = self.write(extra={'source/modules/manual/uninstall.sql': b'DROP TABLE characters;'})
        with self.assertRaisesRegex(ValueError, 'payload differs'):
            qualify.unpack_content(self.package, digest, self.lock, self.root / 'extra')

    def test_missing_compiled_selection_rejected_before_extracting(self):
        digest = self.write(unqualified=True)
        with self.assertRaisesRegex(ValueError, 'compiled-module verified'):
            qualify.unpack_content(self.package, digest, self.lock, self.root / 'unqualified')
        self.assertFalse((self.root / 'unqualified').exists())

    def test_archive_and_external_receipt_hashes_must_match(self):
        digest = self.write()
        with self.assertRaisesRegex(ValueError, 'receipt digest mismatch'):
            qualify.unpack_content(self.package, '0' * 64, self.lock, self.root / 'bad-receipt')
        with (self.package / 'server-content.tar.gz').open('ab') as output:
            output.write(b'extra')
        with self.assertRaisesRegex(ValueError, 'archive differs'):
            qualify.unpack_content(self.package, digest, self.lock, self.root / 'bad-archive')


if __name__ == '__main__':
    unittest.main()
