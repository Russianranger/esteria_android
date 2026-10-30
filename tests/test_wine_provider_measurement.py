"""Small synthetic archives exercise measurement; they do not qualify execution."""
import copy
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import measure_wine_provider_candidates as measure


class ProviderMeasurement(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.at = Path(temporary.name); self.source = self.at / 'source'; self.output = self.at / 'measured'
        self.old_bridge = json.loads(measure.bridge.LOCK.read_bytes())
        self.old_turnip = json.loads(measure.turnip.LOCK.read_bytes())
        self.catalog = {}
        def source(name): self.catalog[name] = (measure.ROOT / name).read_bytes()
        for kind, template in (('bridges', self.old_bridge), ('turnip', self.old_turnip)):
            source('runtime/' + kind + '/android-provider.lock.json')
            for logical in template['files']:
                prefix = (measure.bridge.SHARE + 'corresponding-source/build-recipe/' if kind == 'bridges' else
                          'provenance/build-recipe/')
                if logical.startswith(prefix): source('runtime/' + kind + '/' + logical.removeprefix(prefix))
        for name in self.old_bridge['repositoryInputs']: source(name)
        self.originals = {'libxtst_1.2.3-1.1.diff.gz': b'original Debian changes fixture',
            'libxtst_1.2.3-1.1.dsc': b'original source descriptor fixture',
            'libxtst_1.2.3.orig.tar.gz': b'original source tar fixture'}
        bridge_source = dict(runtimeArchiveSha256=measure.OLD_RUNTIME, packages=[dict(package='compiler', version='1.0')],
            sources=[dict(package='libxtst', version='1.2.3-1.1', archives=[dict(file=name, **measure.byte_identity(raw))
                for name, raw in self.originals.items()])])
        self.turnip_original = b'complete synthetic upstream original'
        turnip_source = dict(runtimeArchiveSha256=measure.OLD_RUNTIME, packages=[dict(package='compiler', version='1.0')],
            upstream={'mesa': dict(file='mesa-fixture.tar.gz', **measure.byte_identity(self.turnip_original))}, sources=[])
        self.catalog['runtime/bridges/sources.lock.json'] = measure.encoded(bridge_source)
        self.catalog['runtime/turnip/sources.lock.json'] = measure.encoded(turnip_source)
        for name, raw in self.catalog.items():
            path = self.source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        self.patches = [patch.object(measure, 'ROOT', self.source), patch.object(measure.bridge, 'ROOT', self.source),
            patch.object(measure.client, 'source_blob', side_effect=lambda root, revision, name: self.catalog[name]),
            patch.object(measure.bridge, 'elf', side_effect=self.elf), patch.object(measure.turnip, 'elf', side_effect=self.elf)]
        for item in self.patches: item.start(); self.addCleanup(item.stop)
        self.bridge_raw = {name: ('synthetic ' + name).encode() for name in self.old_bridge['files']}
        for name, row in self.old_bridge['repositoryInputs'].items():
            self.bridge_raw[row['installedPath']] = (measure.rebound_source('bridge') if name.endswith('/sources.lock.json') else self.catalog[name])
        for name in self.bridge_raw:
            prefix = measure.bridge.SHARE + 'corresponding-source/build-recipe/'
            if name.startswith(prefix):
                path = 'runtime/bridges/' + name.removeprefix(prefix)
                self.bridge_raw[name] = measure.rebound_source('bridge') if path.endswith('/sources.lock.json') else self.catalog[path]
        self.bridge_raw[measure.bridge.SHARE + 'notices/AUDIO-LICENSE'] = self.catalog['native/guest-bridges/AUDIO-LICENSE']
        for name, raw in self.originals.items(): self.bridge_raw[measure.bridge.SHARE + 'corresponding-source/original-archives/' + name] = raw
        static = json.loads(measure.rebound_source('bridge'))['sources']
        self.bridge_raw[measure.bridge.SHARE + 'corresponding-source/original-archives/SOURCE-MANIFEST.json'] = measure.encoded(dict(
            formatVersion=1, scope='original-archives-for-locked-direct-build-and-static-link-inputs', completeGuestRootfsSourceClosure=False,
            files=[dict(package=row['package'], version=row['version'], **item) for row in static for item in row['archives']]))
        receipt = dict(formatVersion=1, scope='linux-arm64-guest-bridge-build-only', integrationRevision=measure.PRODUCER,
            inputLockSha256=measure.byte_identity(self.bridge_raw[measure.bridge.SOURCE_LOCK])['sha256'], runtimeArchiveSha256=measure.RUNTIME,
            binaries={name: self.elf_bytes(self.bridge_raw[path]) for name, path in measure.bridge.BINARY_PATHS.items()},
            sources={name.removeprefix('native/'): measure.byte_identity(raw) for name, raw in self.catalog.items() if name.startswith('native/')},
            selectedPackages={'compiler': '1.0'}, compiled=True, guestExecutionQualified=False, androidQualified=False,
            gameAudioQualified=False, presentationQualified=False, inputQualified=False)
        self.bridge_raw[measure.bridge.RECEIPT] = measure.encoded(receipt)
        self.turnip_raw = {name: ('synthetic ' + name).encode() for name in self.old_turnip['files']}
        for name in self.turnip_raw:
            if name.startswith('provenance/build-recipe/'):
                path = 'runtime/turnip/' + name.removeprefix('provenance/build-recipe/')
                self.turnip_raw[name] = measure.rebound_source('turnip') if path.endswith('/sources.lock.json') else self.catalog[path]
        self.turnip_raw['notices/ESTERIA-GPL-3.0'] = self.catalog['LICENSE']
        lock = json.loads(measure.rebound_source('turnip'))
        self.turnip_raw['provenance/source-manifest.json'] = measure.encoded(dict(formatVersion=1,
            scope='exact-upstream-and-direct-build-input-sources', completeGuestRootfsSourceClosure=False,
            files={'mesa-fixture.tar.gz': measure.byte_identity(self.turnip_original)}))
        binaries = {name: self.elf_bytes(self.turnip_raw[name]) for name in measure.turnip.BINARIES}
        build = dict(formatVersion=1, scope='linux-arm64-turnip-kgsl-build-only', compiled=True,
            integrationRevision=measure.PRODUCER, runtimeArchiveSha256=measure.RUNTIME,
            inputLockSha256=measure.byte_identity(measure.rebound_source('turnip'))['sha256'], upstream=lock['upstream'],
            selectedPackages={'compiler': '1.0'}, binaries=binaries,
            recipeSources={name.removeprefix('provenance/build-recipe/'): measure.byte_identity(raw)
                for name, raw in self.turnip_raw.items() if name.startswith('provenance/build-recipe/')},
            notices={name: measure.byte_identity(raw) for name, raw in self.turnip_raw.items() if name.startswith('notices/')},
            mesonOptions={'vulkan-drivers': ['freedreno'], 'freedreno-kmds': ['kgsl'], 'platforms': ['x11'],
                'gallium-drivers': [], 'llvm': 'disabled', 'glx': 'disabled', 'egl': 'disabled'},
            **{key: False for key in measure.turnip.FALSE_FLAGS})
        self.turnip_raw['provenance/turnip-build.json'] = measure.encoded(build)
        probe = dict(formatVersion=2, scope='linux-arm64-turnip-kgsl-component-probe', icdLoaded=True,
            directIcdNoDevicesVerified=True, noKgslHostVerified=True, turnip740ShaderReadbackQualified=False,
            pixelsVerified=0, vendorId=0, deviceId=0, deviceName='', x11PresentationQualified=False, androidQualified=False,
            gameplayQualified=False, loaderEnumerationResult=-3)
        self.turnip_raw['provenance/no-gpu-probe.json'] = measure.encoded(probe)
        self.turnip_raw['provenance/no-gpu-check.json'] = measure.encoded(dict(formatVersion=1,
            scope='pinned-linux-arm64-turnip-probe', qualified=True, receipt=probe, sourceRevision=measure.PRODUCER,
            buildReceiptSha256=measure.byte_identity(self.turnip_raw['provenance/turnip-build.json'])['sha256'],
            driver=binaries['lib/libvulkan_freedreno.so'], probe=binaries['bin/esteria-turnip-probe'],
            **{key: False for key in measure.turnip.FALSE_FLAGS}))
        self.shader = measure.encoded(dict(formatVersion=1, scope='native-linux-arm64-shader-tools-only', qualified=True,
            validGlslCompiled=True, spirvValidated=True, spirvDisassembled=True, invalidGlslRejected=True,
            invalidSpirvRejected=True, androidQualified=False, gameAssetShadersQualified=False, gameplayQualified=False,
            validSpirvSha256='f' * 64))
        self.run = dict(id=measure.RUN, head_sha=measure.PRODUCER, head_branch='android/client-server', path=measure.WORKFLOW,
            status='completed', conclusion='success', event='push', repository={'full_name': measure.REPOSITORY},
            head_repository={'full_name': measure.REPOSITORY})
        self.run_path = self.at / 'run.json'; self.run_path.write_bytes(measure.encoded(self.run))
        self.zips = {}; self.metadata = {}
        self.write_zip('bridge'); self.write_zip('turnip')

    def elf_bytes(self, raw):
        return dict(measure.byte_identity(raw), architecture='arm64', needed=['libc.so.6'], interpreter=None,
                    maxGlibc='2.36', maxGlibcxx=None)

    def elf(self, path, *args): return self.elf_bytes(path.read_bytes())

    def write_zip(self, kind):
        path = self.at / (kind + '.zip'); raw = self.bridge_raw if kind == 'bridge' else self.turnip_raw
        old = self.old_bridge if kind == 'bridge' else self.old_turnip
        entries = {kind + '/' + (old['files'][name]['payloadPath'] if kind == 'bridge' else
                   old['files'][name]['zipEntry'].removeprefix(measure.turnip.PREFIX)): data for name, data in raw.items()}
        if kind == 'turnip':
            entries['turnip/corresponding-source/original-archives/mesa-fixture.tar.gz'] = self.turnip_original
            entries['turnip/shader-runtime-check/qualification.json'] = self.shader
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in entries.items():
                item = zipfile.ZipInfo(name); item.create_system = 3; item.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(item, data)
        self.zips[kind] = path
        identity = measure.client.identity(path)
        name = 'unqualified-native-arm64-new-wine-' + ('guest-bridges-' if kind == 'bridge' else 'turnip-') + measure.PRODUCER
        metadata = dict(id=1 if kind == 'bridge' else 2, name=name, expired=False, size_in_bytes=identity['bytes'],
            digest='sha256:' + identity['sha256'], workflow_run=dict(id=measure.RUN, head_sha=measure.PRODUCER, head_branch='android/client-server'))
        meta_path = self.at / (kind + '-metadata.json'); meta_path.write_bytes(measure.encoded(metadata)); self.metadata[kind] = meta_path

    def measure(self):
        return measure.measure(self.run_path, self.metadata['bridge'], self.zips['bridge'],
                               self.metadata['turnip'], self.zips['turnip'], self.output)

    def test_full_rosters_sources_and_existing_provider_validators_produce_only_review_outputs(self):
        original = {name: raw for name, raw in self.catalog.items() if name.endswith('android-provider.lock.json')}
        result = self.measure()
        self.assertEqual({path.name for path in self.output.iterdir()}, measure.OUTPUTS)
        bridge = json.loads((self.output / 'guest-bridges.proposed.lock.json').read_bytes())
        turnip = json.loads((self.output / 'turnip.proposed.lock.json').read_bytes())
        self.assertEqual((len(bridge['files']), len(turnip['files'])), (28, 68))
        self.assertTrue(all(row['zipEntry'].startswith('bridge/') for row in bridge['files'].values()))
        self.assertTrue(all(row['zipEntry'].startswith('turnip/') for row in turnip['files'].values()))
        self.assertEqual((self.output / 'bridge-sources.lock.json').read_bytes(), measure.rebound_source('bridge'))
        self.assertEqual((self.output / 'turnip-sources.lock.json').read_bytes(), measure.rebound_source('turnip'))
        self.assertTrue(result['completeOriginalZipsHashedBeforeParsing'] and result['actualProviderPayloadsValidated'])
        self.assertTrue(result['turnipOriginalSources']['allLockedOriginalSourcesVerified'])
        self.assertFalse(result['productionPinsChanged'] or result['androidQualified'] or result['hardwareQualified'])
        for name, raw in original.items(): self.assertEqual((self.source / name).read_bytes(), raw)

    def test_run_metadata_rejects_failed_foreign_or_different_producer_before_archive_use(self):
        for key, wrong in (('id', True), ('head_sha', 'a' * 40), ('head_branch', 'main'), ('path', 'other.yml'),
                           ('status', 'in_progress'), ('conclusion', 'failure'), ('event', 'pull_request'),
                           ('head_repository', {'full_name': 'foreign/repo'})):
            self.run_path.write_bytes(measure.encoded(dict(self.run, **{key: wrong})))
            with self.subTest(key=key), patch.object(measure.client, 'checked_zip', side_effect=AssertionError('must not parse')):
                with self.assertRaisesRegex(ValueError, 'successful-owned-run'): self.measure()

    def test_both_entire_zip_identities_must_match_api_before_either_zip_is_parsed(self):
        original = json.loads(self.metadata['turnip'].read_bytes())
        for key, wrong in (('id', True), ('expired', True), ('name', 'other'), ('size_in_bytes', 1),
                           ('digest', 'sha256:' + '0' * 64), ('workflow_run', {'id': measure.RUN, 'head_sha': 'a' * 40})):
            self.metadata['turnip'].write_bytes(measure.encoded(dict(original, **{key: wrong})))
            with self.subTest(key=key), patch.object(measure.client, 'checked_zip', side_effect=AssertionError('must not parse')):
                with self.assertRaisesRegex(ValueError, 'artifact-(provenance|size|digest)'): self.measure()
        self.metadata['turnip'].write_bytes(measure.encoded(original)); self.zips['turnip'].write_bytes(b'changed')
        with patch.object(measure.client, 'checked_zip', side_effect=AssertionError('must not parse')):
            with self.assertRaisesRegex(ValueError, 'artifact-size'): self.measure()

    def test_truthfully_remeasured_source_change_is_not_accepted_as_new_build_input(self):
        path = measure.bridge.SHARE + 'corresponding-source/guest-bridges/x11_input.c'
        self.bridge_raw[path] += b'changed'; self.write_zip('bridge')
        with self.assertRaisesRegex(ValueError, 'retained-source-differs'): self.measure()
        self.bridge_raw[path] = self.catalog['native/guest-bridges/x11_input.c']; self.write_zip('bridge')
        (self.source / 'native/guest-bridges/x11_input.c').write_bytes(b'changed current source')
        with self.assertRaisesRegex(ValueError, 'current-source-differs'): self.measure()
        self.assertFalse(self.output.exists())

    def test_source_lock_can_only_change_runtime_archive_binding(self):
        value = json.loads(self.bridge_raw[measure.bridge.SOURCE_LOCK]); value['packages'][0]['version'] = '2.0'
        self.bridge_raw[measure.bridge.SOURCE_LOCK] = measure.encoded(value); self.write_zip('bridge')
        with self.assertRaisesRegex(ValueError, 'retained-source-differs'): self.measure()
        self.assertFalse(self.output.exists())

    def test_actual_elf_receipt_or_no_gpu_qualification_rejection_prevents_publication(self):
        with patch.object(measure.turnip, 'elf', return_value={'architecture': 'x64'}):
            with self.assertRaisesRegex(ValueError, 'actual-elf-differs'): self.measure()
        value = json.loads(self.turnip_raw['provenance/no-gpu-check.json']); value['qualified'] = False
        self.turnip_raw['provenance/no-gpu-check.json'] = measure.encoded(value); self.write_zip('turnip')
        with self.assertRaisesRegex(ValueError, 'no-gpu-evidence-differs'): self.measure()
        self.assertFalse(self.output.exists())

    def test_original_sources_still_verified_when_outer_zip_digest_is_truthful(self):
        self.turnip_original = b'corrupt original with truthful outer digest'; self.write_zip('turnip')
        with self.assertRaisesRegex(ValueError, 'source-type-or-size|source-bytes-differ'): self.measure()
        self.assertFalse(self.output.exists())

    def test_existing_output_is_preserved_before_reading_metadata(self):
        self.output.mkdir(); (self.output / 'saved').write_bytes(b'preserve')
        with patch.object(measure, 'read_metadata', side_effect=AssertionError('must not read')):
            with self.assertRaisesRegex(ValueError, 'output-exists'): self.measure()
        self.assertEqual((self.output / 'saved').read_bytes(), b'preserve')


if __name__ == '__main__': unittest.main()
