"""Synthetic staging guards; no artifact download, server execution or source gate."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from tools import prepare_server_engine_inputs as stage


def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class EngineInputGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pin, self.pin_identity = stage.load_pin()

    def archive(self, name, members):
        path = self.root / name
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for filename, raw in members.items():
                archive.writestr(filename, raw)
        return path

    def remote(self, pin=None):
        pin = pin or self.pin
        run = dict(id=pin['workflowRun'], head_sha=pin['integrationRevision'], status='completed', conclusion='failure')
        job = dict(id=pin['job'], run_id=pin['workflowRun'], status='completed', conclusion='failure',
            steps=[dict(number=n, conclusion='failure' if n == 21 else 'success')
                   for n in (12, 15, 16, 17, 18, 19, 20, 21, 24, 25)])
        artifacts = {row['id']: dict(id=row['id'], expired=False, size_in_bytes=row['bytes'],
            digest='sha256:' + row['sha256'], workflow_run={'id': pin['workflowRun'], 'head_sha': pin['integrationRevision']})
            for row in pin['artifacts'].values()}
        api = Mock()
        def request(path):
            if path.startswith('/actions/runs/'): return run
            if path.startswith('/actions/jobs/'): return job
            return artifacts[int(path.rsplit('/', 1)[1])]
        api.json.side_effect = request
        return api, run, job, artifacts

    def fake_disk(self, free=stage.MINIMUM_FREE_BYTES):
        return shutil._ntuple_diskusage(32 * 1024**3, 32 * 1024**3 - free, free)

    def inputs(self):
        _, lock = stage.source_selection(self.pin)
        binary = b'synthetic binary; never executable or qualified\0'
        source = stage.fetch_sources.load_lock(stage.SOURCE_LOCK)['sources']['server']
        installed = {'sources.lock.json': lock, 'bin/authserver': binary, 'bin/worldserver': binary,
                     'bin/dbimport': binary, 'etc/dbimport.conf.dist': b'# synthetic template\n'}
        build = dict(schemaVersion=1, architecture='Linux-ARM64', sourceCheckoutAndPatchesVerified=True,
            hostLoaderSmoke={'qualified': True}, integrationRevision=self.pin['integrationRevision'],
            buildId=self.pin['buildId'], sourcesLock=identity(lock), serverSource=source,
            files=[dict(path=name, **identity(raw), **({'elf': {'machine': 'AArch64'}} if name.startswith('bin/') else {}))
                   for name, raw in installed.items()])
        build_raw = stage.reference.encoded(build)
        installed['server-build.json'] = build_raw
        commands = b'[]\n'
        compiled = dict(formatVersion=1, scope='compiled-server-module-selection', source=source,
            sourceLockSha256=self.pin['sourceLockSha256'], serverBuild=identity(build_raw),
            compileCommands=identity(commands), enabledModules=['synthetic-module'], configFiles=[],
            generatedListsMatchInstalledBinaries=True)
        compiled_raw = stage.reference.encoded(compiled)
        manifest_raw = b'{"fixture":"synthetic content manifest"}\n'
        content_raw = b'synthetic archive bytes, not SQL or a tar archive\n'
        original = dict(source=source, sourceLockSha256=self.pin['sourceLockSha256'],
            contentManifest=identity(manifest_raw), compiledModules=identity(compiled_raw),
            moduleSelectionVerified=True, archiveReadBackVerified=True, archive=identity(content_raw))
        diagnostic = {'sources.lock.json': lock, 'compile_commands.json': commands}
        for row in source['patches']:
            diagnostic[row['path']] = (stage.ROOT / row['path']).read_bytes()
        archives = dict(install=self.archive('fixture-install.zip', installed),
            diagnostics=self.archive('fixture-diagnostics.zip', diagnostic),
            content=self.archive('fixture-content.zip', {'server-modules.json': compiled_raw,
                'server-content-manifest.json': manifest_raw, 'server-content.tar.gz': content_raw,
                'package-receipt.json': stage.reference.encoded(original)}))
        pin = copy.deepcopy(self.pin)
        for name, path in archives.items():
            pin['artifacts'][name].update(stage.files.identity(path))
        return pin, archives, compiled, compiled_raw

    def test_reference_is_current_seven_patch_build_and_not_six_patch_alias(self):
        self.assertEqual(self.pin['workflowRun'], 41019374697)
        self.assertEqual(self.pin['artifacts']['install']['id'], 12966255548)
        current, archived = stage.source_selection(self.pin)
        self.assertEqual(self.pin['sourceLockSha256'], identity(archived)['sha256'])
        self.assertTrue(stage.sources.same(current['sources']['server'], json.loads(archived)['sources']['server']))
        self.assertEqual(len(stage.fetch_sources.load_lock(stage.SOURCE_LOCK)['sources']['server']['patches']), 7)
        old, _ = stage.reference.load_pin()
        self.assertNotEqual(self.pin['integrationRevision'], old['integrationRevision'])
        self.assertNotEqual(self.pin['sourceLockSha256'], old['sourceLockSha256'])

    def test_changed_current_source_lock_or_reduced_disk_floor_refused(self):
        source = self.root / 'changed-source-lock.json'; source.write_text(stage.SOURCE_LOCK.read_text()+'\n')
        with patch.object(stage, 'SOURCE_LOCK', source), self.assertRaisesRegex(ValueError, 'current-app-source-lock'):
            stage.load_pin()
        pin = copy.deepcopy(self.pin); pin['minimumFreeBytes'] = 1
        with patch.object(stage.modules, 'read_json', return_value=(pin, self.pin_identity)), \
                self.assertRaisesRegex(ValueError, 'reference-identity'):
            stage.load_pin()

    def test_client_only_app_advance_preserves_archived_server_identity_but_server_or_profile_drift_refuses(self):
        current=json.loads(stage.SOURCE_LOCK.read_text())
        provider=json.loads(stage.PROVIDER_LOCK.read_text())
        source=self.root/'current.lock.json';provider_path=self.root/'provider.lock.json'
        def select(document):
            raw=stage.reference.encoded(document);source.write_bytes(raw)
            provider['appSourceLock']=identity(raw);provider_path.write_bytes(stage.reference.encoded(provider))
        current['sources']['client']['commit']='a'*40;select(current)
        with patch.object(stage,'SOURCE_LOCK',source),patch.object(stage,'PROVIDER_LOCK',provider_path):
            selected,archived=stage.source_selection(self.pin)
            self.assertEqual(selected['sources']['client']['commit'],'a'*40)
            self.assertEqual(identity(archived)['sha256'],self.pin['sourceLockSha256'])
            self.assertEqual(stage.load_pin(),(self.pin,self.pin_identity))
            mutations=(lambda row:row['sources']['server']['patches'][0].update(sha256='0'*64),
                       lambda row:row['sources']['server']['submodules'].update({'src/server/game/LuaEngine':'b'*40}),
                       lambda row:row['compatibility'].update(base_client_build=12341),
                       lambda row:row['compatibility'].update(extended_limits=1))
            for mutate in mutations:
                changed=copy.deepcopy(current);mutate(changed);select(changed)
                with self.assertRaisesRegex(ValueError,'selection-differs|compatibility-profile-differs'):
                    stage.load_pin()

    def test_disk_preflight_writes_typed_failure_before_any_network(self):
        output = self.root / 'insufficient'; api = Mock()
        with patch.object(stage.shutil, 'disk_usage', return_value=self.fake_disk(stage.MINIMUM_FREE_BYTES - 1)), \
                self.assertRaisesRegex(ValueError, '12-GiB'):
            stage.prepare(output, api)
        receipt = json.loads((output / 'disk-preflight.json').read_bytes())
        self.assertEqual(receipt['scope'], 'server-engine-input-disk-preflight')
        self.assertIs(receipt['sufficientFreeSpace'], False)
        self.assertIs(receipt['downloadsStarted'], False)
        self.assertEqual(receipt['minimumFreeBytes'], 12 * 1024**3)
        api.json.assert_not_called(); api.download.assert_not_called()
        self.assertFalse((output / 'preparation.json').exists())

    def test_exact_disk_floor_passes_and_existing_output_preserves_saved_bytes(self):
        output = self.root / 'disk'; output.mkdir()
        with patch.object(stage.shutil, 'disk_usage', return_value=self.fake_disk()):
            self.assertTrue(stage.disk_preflight(output)['sufficientFreeSpace'])
        marker = output / 'saved'; marker.write_bytes(b'preserve')
        api = Mock()
        with patch.object(stage, 'load_pin') as load, self.assertRaisesRegex(ValueError, 'staging-preserved'):
            stage.prepare(output, api)
        load.assert_not_called(); api.json.assert_not_called(); api.download.assert_not_called()
        self.assertEqual(marker.read_bytes(), b'preserve')

    def test_wrong_artifact_or_runtime_failure_scope_refused_before_download(self):
        api, run, job, artifacts = self.remote()
        stage.reference.verify_remote(api, self.pin)
        artifacts[self.pin['artifacts']['install']['id']]['digest'] = 'sha256:' + '0' * 64
        with self.assertRaisesRegex(ValueError, 'GitHub identity changed'):
            stage.reference.verify_remote(api, self.pin)
        api.download.assert_not_called()
        api, run, job, artifacts = self.remote()
        next(row for row in job['steps'] if row['number'] == 21)['conclusion'] = 'success'
        with self.assertRaisesRegex(ValueError, 'runtime failure scope changed'):
            stage.reference.verify_remote(api, self.pin)

    def test_download_identity_is_rechecked_before_any_zip_extraction(self):
        pin, archives, compiled, raw = self.inputs()
        api, _, _, _ = self.remote(pin)
        def changed_download(url, target, row): target.write_bytes(b'changed after API metadata verification')
        api.download.side_effect = changed_download
        output = self.root / 'partial'
        with patch.object(stage, 'load_pin', return_value=(pin, self.pin_identity)), \
             patch.object(stage.shutil, 'disk_usage', return_value=self.fake_disk()), \
             patch.object(stage.reference, 'extract_install') as extract, \
             self.assertRaisesRegex(ValueError, 'artifact-identity-mismatch'):
            stage.prepare(output, api)
        extract.assert_not_called()
        self.assertTrue((output / 'downloads/install.zip').is_file())
        self.assertFalse((output / 'preparation.json').exists())

    def test_synthetic_complete_staging_retains_exact_receipts_and_false_runtime_flags(self):
        pin, archives, compiled, compiled_raw = self.inputs()
        api, _, _, _ = self.remote(pin)
        def download(url, target, row):
            name = next(name for name, value in pin['artifacts'].items() if value['id'] == row['id'])
            shutil.copyfile(archives[name], target)
        api.download.side_effect = download
        def repack(output, observed_pin, build, observed_modules, original):
            self.assertEqual(observed_pin, pin); self.assertEqual(observed_modules, compiled)
            content = output / 'content'; content.mkdir()
            stage.reference.write_new(content / 'package-receipt.json', b'{"synthetic":true}\n')
            (output / 'sources/server').mkdir(parents=True)
        output = self.root / 'prepared'
        with patch.object(stage, 'load_pin', return_value=(pin, self.pin_identity)), \
             patch.object(stage.shutil, 'disk_usage', return_value=self.fake_disk()), \
             patch.object(stage.modules, 'verify', return_value=compiled), \
             patch.object(stage.importer, 'verify_install'), \
             patch.object(stage.package, 'validate_modules'), \
             patch.object(stage, 'repack_content', side_effect=repack):
            receipt = stage.prepare(output, api)
        self.assertEqual(api.download.call_count, 3)
        self.assertEqual((output / 'server-modules.json').read_bytes(), compiled_raw)
        self.assertEqual((output / 'locked/sources.lock.json').read_bytes(), stage.source_selection(pin)[1])
        self.assertEqual(receipt['currentAppSourceLock'],stage.files.identity(stage.SOURCE_LOCK))
        self.assertTrue(receipt['currentServerAndCompatibilityMatchArchivedBuild'])
        self.assertEqual(list((output / 'downloads').iterdir()), [])
        self.assertEqual(json.loads((output / 'preparation.json').read_bytes()), receipt)
        for flag in ('sourceCompanionComplete', 'strippedDerivativeCreated', 'sqlExecuted',
                     'androidProviderCreated', 'androidRuntimeQualified', 'gameplayQualified'):
            self.assertIs(receipt[flag], False)

    def test_current_source_repack_rejects_a_stale_lock_before_fetch(self):
        output = self.root / 'repack'; (output / 'locked').mkdir(parents=True)
        (output / 'locked/sources.lock.json').write_bytes(b'old lock')
        with patch.object(stage.fetch_sources, 'fetch') as fetch, \
                self.assertRaisesRegex(ValueError, 'selection-is-not-current'):
            stage.repack_content(output, self.pin, {}, {}, {})
        fetch.assert_not_called()


if __name__ == '__main__': unittest.main()
