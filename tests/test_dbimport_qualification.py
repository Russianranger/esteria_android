import hashlib
import io
import json
import os
from pathlib import Path
import select
import subprocess
import tarfile
import tempfile
import unittest
import types
from unittest.mock import Mock, patch

from tools import qualify_dbimport as qualify


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def source_identity(data):
    return identity(data) | {'gitBlob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


class QualificationGuards(unittest.TestCase):
    def test_phone_content_consumer_gets_complete_installed_bound_source_and_module_object(self):
        source = dict(commit='f' * 40, patches=[dict(path='reviewed')])
        manifest = dict(source=source); compiled = dict(enabledModules=['actual'], serverBuild={'sha256': 'a' * 64})
        verified = types.SimpleNamespace(manifest=manifest, compiled=compiled)
        with patch.object(qualify.base, 'locked_source', return_value=(source, 'b' * 64)), \
                patch.object(qualify.product_content, 'verify', return_value=verified) as verify:
            observed = qualify.verify_runtime_content(Path('/extracted'), Path('/package'), 'c' * 64,
                Path('/lock'), manifest, compiled)
        self.assertIs(observed, verified)
        verify.assert_called_once_with(Path('/extracted'), Path('/package/package-receipt.json'), 'c' * 64,
                                       source, 'b' * 64, compiled)

    def test_runtime_consumer_mismatch_cannot_reach_native_sql(self):
        with patch.object(qualify.base, 'locked_source', return_value=({}, 'b' * 64)), \
                patch.object(qualify.product_content, 'verify', return_value=types.SimpleNamespace(
                    manifest={'changed': True}, compiled={})), self.assertRaisesRegex(ValueError, 'differs from verified native'):
            qualify.verify_runtime_content(Path('/extracted'), Path('/package'), 'c' * 64, Path('/lock'), {}, {})

    def test_execution_evidence_requires_real_process_creation_and_records_nonzero_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); started = Mock()
            with self.assertRaises(OSError):
                qualify.run_importer(root / 'missing', root / 'config', root / 'failed-open.log', on_started=started)
            started.assert_not_called()
            executable = root / 'updater'
            executable.write_text('#!/usr/bin/python3\nraise SystemExit(7)\n')
            executable.chmod(0o700)
            with self.assertRaisesRegex(ValueError, 'exit 7'):
                qualify.run_importer(executable, root / 'config', root / 'failed-exit.log', on_started=started)
            started.assert_called_once_with()

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

    @unittest.skipUnless(hasattr(os, 'pidfd_open'), 'Linux descendant observation')
    def test_timeout_cleans_descendant_that_retains_output_after_leader_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); executable = root / 'updater'
            executable.write_text('#!/usr/bin/python3\nimport os,time,pathlib\n'
                'if os.fork()==0:\n'
                ' pathlib.Path("descendant").write_text(str(os.getpid()))\n'
                ' print("retained",flush=True)\n'
                ' while True:time.sleep(.05)\n')
            executable.chmod(0o700)
            watched = []
            original = qualify.OwnedGroup.stop
            def stop(group, *args, **kwargs):
                descriptor = os.pidfd_open(int((root / 'descendant').read_text()))
                watched.append(descriptor)
                self.assertIsNone(group.process.returncode)
                return original(group, *args, **kwargs)
            try:
                with patch.object(qualify.OwnedGroup, 'stop', stop), self.assertRaisesRegex(ValueError, 'timed out'):
                    qualify.run_importer(executable, root / 'config.cnf', root / 'run.log', timeout=.2)
                self.assertEqual(len(watched), 1)
                self.assertEqual(select.select(watched, [], [], 5)[0], watched)
                self.assertIn(b'retained', (root / 'run.log').read_bytes())
            finally:
                for descriptor in watched: os.close(descriptor)

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


class PackagedUpdaterHook(unittest.TestCase):
    def private_log(self, root, raw=b'private child output\x00\xff'):
        state = root / 'state'
        operation = state / 'run' / ('updater-' + 'a' * 32)
        (operation / 'logs').mkdir(parents=True)
        (state / 'logs').mkdir()
        path = operation / 'logs/updater-private.log'; path.write_bytes(raw); path.chmod(0o600)
        journal = dict(invocation=str(operation), run=dict(exitCode=0, diagnosticBytes=len(raw),
            diagnosticSha256=hashlib.sha256(raw).hexdigest()))
        return state, path, journal

    def test_product_log_is_exact_private_and_cannot_overwrite_previous_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            state, source, journal = self.private_log(Path(temporary))
            qualify.packaged_updater_log(state, journal)
            target = state / 'logs/dbimport-first.log'
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):qualify.packaged_updater_log(state, journal)

    def test_changed_shared_or_foreign_product_log_never_reaches_export_path(self):
        for change in ('bytes', 'shared', 'public-mode', 'foreign-operation'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                state, source, journal = self.private_log(Path(temporary))
                if change == 'bytes':source.write_bytes(b'changed private child output')
                elif change == 'shared':os.link(source, source.with_name('linked'))
                elif change == 'public-mode':source.chmod(0o644)
                else:journal['invocation'] = str(Path(temporary) / ('updater-' + 'a' * 32))
                with self.assertRaises(ValueError):qualify.packaged_updater_log(state, journal)
                self.assertFalse((state / 'logs/dbimport-first.log').exists())

    def test_native_hook_cannot_invent_or_reuse_a_baseline_proof(self):
        # A real first import must invoke the callback. A historical or missing
        # proof cannot reach the updater, even if an ordinary receipt is true.
        for operation in ('initialized-source-baseline', 'already-prepared'):
            with self.subTest(operation=operation), \
                    patch.object(qualify.product_schema, 'initialize', return_value=dict(operation=operation)), \
                    patch.object(qualify.product_setup, 'prepare') as prepare, \
                    self.assertRaisesRegex(ValueError, 'actual first-import proof'):
                qualify.run_packaged_updater(object(), Path('/install'), Path('/template'), identity(b'template'),
                    {'dbimport': identity(b'program')}, Path('/mysql'), '8.0.46', Path('/state'),
                    object(), Path('/options'), object(), lambda: None, {})
            prepare.assert_not_called()


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
            self.manifest['files'][path] = source_identity(data)
            self.payload['source/' + path] = data
        for path in qualify.base.content.MAIN_CONFIG_TEMPLATES:
            data = b'# Synthetic source configuration template\n'
            self.manifest['files'][path] = source_identity(data)
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
        for name, row in receipt['archiveFiles'].items():
            if name.startswith('source/') and name[7:] in self.manifest['files']:
                row.update(origin='server', source=name[7:], gitBlob=self.manifest['files'][name[7:]]['gitBlob'])
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

    def test_source_provenance_cannot_be_missing_rebound_or_extended_even_with_valid_bytes(self):
        self.write()
        path = self.package / 'package-receipt.json'
        original = json.loads(path.read_text())
        selected = next(name for name in original['archiveFiles'] if name.startswith('source/'))
        for index, change in enumerate(('missing', 'origin', 'source', 'gitBlob', 'extra')):
            receipt = json.loads(json.dumps(original))
            row = receipt['archiveFiles'][selected]
            if change == 'missing':
                del row['gitBlob']
            else:
                row[change] = '0' * 40 if change == 'gitBlob' else 'different-source'
            path.write_text(json.dumps(receipt))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'payload identity differs'):
                qualify.unpack_content(self.package, digest, self.lock, self.root / ('changed-' + str(index)))

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
