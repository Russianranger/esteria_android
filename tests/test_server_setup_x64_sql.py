"""Real loader/template guards; host success is never SQL qualification."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_server_setup_x64_sql as sql
from tools import build_server_setup_x64_probe as builder


class ServerSetupX64Sql(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_pending_selection_refuses_all_execution_and_download_before_output(self):
        output = self.root / 'absent'
        pending = dict(formatVersion=1, scope='x64-server-setup-sql-input-selection',
            repository='Russianranger/esteria_android', enabled=False, state='pending-x64-compile-source-measurement',
            minimumFreeBytes=16 << 30, build=None, mysql=None, serverContent=None,
            **{name: False for name in sql.selection.FALSE_FLAGS})
        pending_path = self.root / 'pending.json'; pending_path.write_bytes(sql.encode(pending))
        with patch.object(sql.selection, 'LOCK', pending_path), patch.object(sql.db, 'initialize') as initialize, \
                patch.object(sql.remote, 'Github') as api, \
                self.assertRaisesRegex(ValueError, 'measured-build-required'):
            sql.acquire(output)
        api.assert_not_called(); initialize.assert_not_called(); self.assertFalse(output.exists())
        with patch.object(sql.selection, 'LOCK', pending_path), patch.object(sql.platform, 'machine', return_value='x86_64'), \
                patch.object(sql.db, 'initialize') as initialize, \
                self.assertRaisesRegex(ValueError, 'measured-build-required'):
            sql.run(self.root, output, Path('/usr/bin/mysql'), Path('/usr/sbin/mysqld'), '8.0.46')
        initialize.assert_not_called(); self.assertFalse(output.exists())

    def test_non_x64_host_refuses_before_selection_or_sql(self):
        with patch.object(sql.platform, 'machine', return_value='aarch64'), \
                patch.object(sql, 'load_selection') as selection, \
                patch.object(sql.db, 'initialize') as initialize, \
                self.assertRaisesRegex(ValueError, 'native-linux-x86-64'):
            sql.run(self.root, self.root / 'absent', self.root, self.root, '8.0.46')
        selection.assert_not_called(); initialize.assert_not_called()

    def test_enabled_acquisition_requires_explicit_frozen_source_before_output_or_network(self):
        with patch.object(sql, 'load_selection', return_value={'enabled': True}), \
                patch.object(sql.remote, 'Github') as api, \
                self.assertRaisesRegex(ValueError, 'explicit-frozen-mysql-consumer'):
            sql.acquire(self.root / 'absent')
        api.assert_not_called(); self.assertFalse((self.root / 'absent').exists())

    def test_current_caller_snapshot_cannot_transfer_historical_runtime_scope(self):
        inputs = sql.caller_files()
        snapshot = dict(scope='current-native-x64-sql-caller-source-only', integrationRevision='a'*40,
            sourceInputs=inputs, sourceSnapshotExact=True, historicalRuntimeQualificationTransferred=False)
        self.assertEqual(sql.verify_caller(snapshot), snapshot)
        for changed in (dict(sourceSnapshotExact=False), dict(historicalRuntimeQualificationTransferred=True),
                dict(sourceInputs={}), dict(integrationRevision='floating')):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'current-caller-source-differs'):
                sql.verify_caller(dict(snapshot, **changed))

    def test_restored_mysql_descriptor_and_archive_are_bound_to_original_measured_selection(self):
        assets = self.root / 'mysql/provider/assets/mysql-probe'; assets.mkdir(parents=True)
        archive = dict(bytes=1234, sha256='a'*64)
        raw = sql.encode(dict(archive=archive, expectedMysqlSqlVersion='8.0.46-fixture'))
        path = assets / 'provider.json'; path.write_bytes(raw)
        selected = dict(files={'provider/assets/mysql-probe/provider.json': sql.selection.files.identity(path),
            'provider/assets/mysql-probe/' + sql.mysql_inputs.retained.builder.ARCHIVE: archive})
        with patch.object(sql.frozen_mysql, 'input_selection', return_value=selected):
            self.assertEqual(sql.mysql_descriptor(self.root)['archive'], archive)
            changed = json.loads(raw); changed['archive']['sha256'] = 'b'*64; path.write_bytes(sql.encode(changed))
            with self.assertRaisesRegex(ValueError, 'file-changed'): sql.mysql_descriptor(self.root)
            selected['files']['provider/assets/mysql-probe/provider.json'] = sql.selection.files.identity(path)
            with self.assertRaisesRegex(ValueError, 'original-mysql-archive-selection'):
                sql.mysql_descriptor(self.root)

    def component(self):
        if platform.machine() != 'x86_64' or not shutil.which('dpkg-query') or not shutil.which('readelf'):
            self.skipTest('Actual native x64 ELF inspection tools required')
        payload = self.root / 'payload'; (payload / 'bin').mkdir(parents=True)
        source = Path(shutil.which('true')).resolve()
        for name in ('dbimport', 'playerbots-schema'): shutil.copyfile(source, payload / 'bin' / name)
        libraries, packages = builder.closure([source], payload / 'libraries')
        executable = dict(**sql.selection.files.identity(source), elf=builder.elf64_x64(source))
        admitted = dict(allRuntimeOriginalDebugLibraryNoticeAndSourceFilesVerified=True,
            build=dict(libraries=libraries, executables={name: executable for name in ('dbimport', 'playerbots-schema')}))
        return payload, admitted

    def configuration(self):
        target = self.root / 'private.conf'; target.write_bytes(b'Host loader fixture; no credentials or SQL')
        target.chmod(0o600); return target

    def test_actual_captured_loader_executes_native_fixture_without_modifying_original_elf(self):
        payload, admitted = self.component(); configuration = self.configuration()
        before = sql.selection.files.identity(payload / 'bin/dbimport')
        result = sql.launchers(payload, admitted, self.root / 'invocations')
        invocation = result['dbimport']; path = Path(invocation['path'])
        completed = subprocess.run([str(path), '--config', str(configuration)], env={'PATH': '/usr/bin:/bin'},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.assertFalse(invocation['invocationIsOriginalElf']); self.assertFalse(invocation['originalElfBytesChanged'])
        self.assertEqual(sql.selection.files.identity(payload / 'bin/dbimport'), before)
        self.assertEqual(result['dbimport']['actualExecutable'], before)

    def test_checked_loader_refuses_changed_actual_elf_library_and_nonprivate_configuration(self):
        payload, admitted = self.component(); configuration = self.configuration()
        invocations = sql.launchers(payload, admitted, self.root / 'invocations')
        command = [invocations['dbimport']['path'], '--config', str(configuration)]
        def refused():
            completed = subprocess.run(command, env={'PATH': '/usr/bin:/bin'}, capture_output=True, timeout=15)
            self.assertEqual(completed.returncode, 98)
            self.assertEqual(completed.stderr, b'x64-sql-checked-loader-refused\n')
        configuration.chmod(0o644); refused(); configuration.chmod(0o600)
        target = payload / 'bin/dbimport'; original = target.read_bytes()
        changed = bytearray(original); changed[-1] ^= 1; target.write_bytes(changed); refused(); target.write_bytes(original)
        target = payload / 'libraries/usr/lib/x86_64-linux-gnu/libc.so.6'; target.chmod(0o600)
        original = target.read_bytes(); changed = bytearray(original); changed[-1] ^= 1; target.write_bytes(changed); refused()

    def test_checked_loader_rejects_arguments_environment_and_missing_full_source_admission(self):
        payload, admitted = self.component(); configuration = self.configuration()
        invocations = sql.launchers(payload, admitted, self.root / 'invocations')
        path = invocations['dbimport']['path']
        for args, environment in [(['--help'], {'PATH': '/usr/bin:/bin'}),
                (['--config', str(configuration)], {'PATH': '/usr/bin:/bin', 'LD_LIBRARY_PATH': '/untrusted'})]:
            result = subprocess.run([path, *args], env=environment, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 98)
        changed = copy.deepcopy(admitted); changed['allRuntimeOriginalDebugLibraryNoticeAndSourceFilesVerified'] = False
        with self.assertRaisesRegex(ValueError, 'complete-component-admission'):
            sql.launchers(payload, changed, self.root / 'never-created')
        self.assertFalse((self.root / 'never-created').exists())

    def test_original_source_template_is_extracted_by_exact_member_and_digest(self):
        source = self.root / 'payload/corresponding-source/source-inputs'; source.mkdir(parents=True)
        body = b'[dbimport]\nFixtureSourceOnly = 1\n'
        archive = source / 'server-engine-source-inputs.tar.gz'
        with tarfile.open(archive, 'w:gz', format=tarfile.GNU_FORMAT) as bundle:
            item = tarfile.TarInfo(sql.TEMPLATE); item.size = len(body); item.mode = 0o644
            bundle.addfile(item, io.BytesIO(body))
        row = dict(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        receipt = dict(archive=sql.selection.files.identity(archive), archiveFiles={sql.TEMPLATE: row})
        (source / 'source-inputs-receipt.json').write_bytes(sql.encode(receipt))
        target = self.root / 'dbimport.conf.dist'
        self.assertEqual(sql.template(self.root / 'payload', target), row); self.assertEqual(target.read_bytes(), body)
        with self.assertRaisesRegex(ValueError, 'existing-template'):
            sql.template(self.root / 'payload', target)
        receipt['archiveFiles'][sql.TEMPLATE]['sha256'] = '0' * 64
        (source / 'source-inputs-receipt.json').write_bytes(sql.encode(receipt))
        with self.assertRaisesRegex(ValueError, 'original-template-bytes'):
            sql.template(self.root / 'payload', self.root / 'changed-template')

    def test_x64_adapter_refuses_forged_helper_before_product_sql_or_plan_creation(self):
        admitted = dict(allRuntimeOriginalDebugLibraryNoticeAndSourceFilesVerified=True,
            build=dict(statementsDeclared=52, executables={'playerbots-schema': dict(bytes=64, sha256='a'*64, elf=dict(machine=183))}))
        with patch.object(sql.playerbots, '_selected_content') as selected, \
                self.assertRaisesRegex(ValueError, 'source-built-52-statement-helper'):
            sql.x64_playerbots_plan(None, admitted, {}, self.root / 'mysql')
        selected.assert_not_called()


if __name__ == '__main__': unittest.main()
