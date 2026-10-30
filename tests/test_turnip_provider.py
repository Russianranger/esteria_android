"""Bounded packaging/source guards; synthetic files never qualify a GPU."""
import copy
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import provider_turnip as provider


class TurnipProvider(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='turnip-provider-test-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name).resolve()
        self.artifact = self.root / 'original.zip'; self.output = self.root / 'provider'
        original = b'synthetic original archive, not a compiler or game asset'
        lock = dict(upstream={'mesa': dict(file='mesa-source.tar', **provider.identity_bytes(original))}, sources=[])
        manifest = dict(formatVersion=1, scope='exact-upstream-and-direct-build-input-sources',
                        completeGuestRootfsSourceClosure=False, files={'mesa-source.tar': provider.identity_bytes(original)})
        self.data = {'lib/libvulkan_freedreno.so': b'explicit synthetic driver', 'bin/esteria-turnip-probe': b'explicit synthetic probe',
            'provenance/build-recipe/sources.lock.json': provider.encoded(lock),
            'provenance/source-manifest.json': provider.encoded(manifest)}
        self.entries = {name: provider.PREFIX + name for name in self.data}
        self.entries['provenance/build-recipe/sources.lock.json'] = provider.PREFIX + 'corresponding-source/build-recipe/sources.lock.json'
        self.entries['provenance/source-manifest.json'] = provider.PREFIX + 'corresponding-source/original-archives/SOURCE-MANIFEST.json'
        self.original_name = provider.PREFIX + 'corresponding-source/original-archives/mesa-source.tar'
        self.original = original
        self.pin = dict(integrationRevision='1'*40, requiredWineArchiveSha256='2'*64, buildReceiptSha256='3'*64,
            artifact=dict(runId=1, id=2), files={name: dict(provider.identity_bytes(raw), zipEntry=self.entries[name]) for name, raw in self.data.items()})
        self.write_zip()

    def write_zip(self, original=None):
        with zipfile.ZipFile(self.artifact, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in {**{self.entries[k]: v for k, v in self.data.items()}, self.original_name: self.original if original is None else original}.items():
                entry = zipfile.ZipInfo(name); entry.create_system = 3; entry.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(entry, raw)
        self.pin['artifact'].update(provider.files.identity(self.artifact))

    def test_all_original_sources_required_even_when_outer_artifact_pin_changes(self):
        receipt = provider.verify_sources(self.artifact, self.pin)
        self.assertTrue(receipt['allLockedOriginalSourcesVerified']); self.assertEqual(receipt['originalArchives'], 1)
        self.assertFalse(receipt['completeGuestRootfsSourceClosure'] or receipt['hardwareQualified'])
        self.write_zip(original=b'changed original but outer hash was remeasured')
        with self.assertRaisesRegex(ValueError, 'source-type-or-size|source-bytes'):
            provider.verify_sources(self.artifact, self.pin)

    def test_deterministic_readback_companion_and_existing_destination_preserved(self):
        with patch.object(provider, 'load_pin', return_value=self.pin), patch.object(provider, 'validate_metadata') as metadata:
            first = provider.build(self.artifact, self.output)
            self.assertTrue(provider.verify(self.output)['sourceCompanionVerified']); self.assertTrue(metadata.called)
            second = self.root / 'second'; other = provider.build(self.artifact, second)
            self.assertEqual(first, other)
            self.assertEqual((self.output/'assets/turnip'/provider.ARCHIVE).read_bytes(), (second/'assets/turnip'/provider.ARCHIVE).read_bytes())
            with self.assertRaisesRegex(ValueError, 'output-exists'): provider.build(self.artifact, self.output)
            extra = self.output / 'assets' / 'unrelated-private.txt'; extra.write_bytes(b'preserve unexpected input')
            with self.assertRaisesRegex(ValueError, 'assets-closure'): provider.verify(self.output)
            self.assertEqual(extra.read_bytes(), b'preserve unexpected input'); extra.unlink()
            (self.output/'sources'/provider.SOURCE).unlink()
            with self.assertRaisesRegex(ValueError, 'file-set'): provider.verify(self.output)

    def test_archive_mutation_and_unsupported_binary_are_rejected(self):
        archive = self.root / 'payload.archive'; provider.write_archive(archive, self.artifact, self.pin)
        with patch.object(provider, 'validate_metadata'):
            provider.verify_archive(archive, self.pin)
            with archive.open('ab') as output: output.write(b'trailing mutation')
            with self.assertRaises((ValueError, OSError, EOFError)): provider.verify_archive(archive, self.pin)
        with self.assertRaises(ValueError): provider.elf(self.artifact, True)

    def test_apk_requires_exact_stored_archive_and_source_companion(self):
        with patch.object(provider, 'load_pin', return_value=self.pin), patch.object(provider, 'validate_metadata'):
            provider.build(self.artifact, self.output)
            for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                apk = self.root / ('apk-'+str(method)+'.zip')
                with zipfile.ZipFile(apk, 'w', compression=method) as archive:
                    for path in (self.output/'assets/turnip').iterdir(): archive.write(path, 'assets/turnip/'+path.name)
                if method == zipfile.ZIP_STORED: self.assertTrue(provider.verify(self.output, apk)['apkBytesVerified'])
                else:
                    with self.assertRaisesRegex(ValueError, 'compression'): provider.verify(self.output, apk)

    def test_source_paths_and_unbounded_metadata_are_refused(self):
        for name in ('../escape', '/absolute', 'nested/source.tar', 'same'):
            lock = dict(upstream={'a': dict(file=name, bytes=1, sha256='1'*64)}, sources=[])
            if name == 'same': lock['upstream']['b'] = copy.deepcopy(lock['upstream']['a'])
            with self.subTest(name=name), self.assertRaises(ValueError): provider.source_pins(lock)
        with zipfile.ZipFile(self.artifact) as archive:
            row = dict(self.pin['files']['provenance/source-manifest.json'], bytes=2<<20)
            with self.assertRaisesRegex(ValueError, 'metadata-bound'): provider.zip_metadata(archive, row)


class MeasuredTurnipPin(unittest.TestCase):
    def test_successful_no_gpu_build_has_no_hardware_or_android_claim(self):
        pin = provider.load_pin()
        self.assertEqual(pin['integrationRevision'], '46a54a223720cdc230074aa6a43f10370718af71')
        self.assertTrue(pin['nativeNoGpuQualified'])
        self.assertTrue(all(pin[name] is False for name in provider.FALSE_FLAGS))
        self.assertEqual(json.loads(provider.ICD)['ICD']['library_path'], '/esteria-turnip/lib/libvulkan_freedreno.so')


if __name__ == '__main__': unittest.main()
