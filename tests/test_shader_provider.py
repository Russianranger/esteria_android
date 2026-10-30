"""Provider guards using explicit synthetic compiler bytes; no compiler is executed."""
import json
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch
import zipfile

from tests import test_shader_tools_package as bundle_fixtures
from tools import provider_shader_tools as provider


class ShaderProvider(unittest.TestCase):
    def setUp(self):
        self.fixture = bundle_fixtures.ShaderToolsPackage('test_git_blobs_readback_exact_closure_and_fresh_publication')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        report = self.fixture.build(); self.root = self.fixture.root
        self.output = self.root / 'provider'; self.bundle = self.fixture.output
        source = self.root / 'repository/runtime/shader_generation.py'
        source.parent.mkdir(parents=True); source.write_bytes(b'# Synthetic helper fixture; not executed\n')
        pin = dict(formatVersion=1, scope='measured-offline-shader-provider-inputs',
            nativeCompilerFixtureQualified=True, androidQualified=False, gameAssetShadersQualified=False, gameplayQualified=False,
            clientRevision=report['clientRevision'], compilerIntegrationRevision=report['integrationRevision'],
            compilerBuildSha256=report['buildReceiptSha256'], toolManifestSha256=report['toolManifestSha256'],
            requiredWineArchiveSha256=report['wineRuntimeArchiveSha256'],
            bundleReceiptSha256=provider.bundle.identity(self.bundle / 'provenance/bundle.json')['sha256'],
            helper=dict(provider.bundle.identity(source), source='runtime/shader_generation.py',
                        installedPath='helpers/shader_generation.py', revision=self.fixture.integration_revision),
            files={p.relative_to(self.bundle).as_posix(): provider.bundle.identity(p) for p in self.bundle.rglob('*') if p.is_file()})
        self.lock = self.root / 'pin.json'; self.lock.write_bytes(provider.encoded(pin))
        for item in (patch.object(provider, 'ROOT', source.parent.parent), patch.object(provider, 'LOCK', self.lock),
                     patch.object(provider.bundle, 'measure_elf', return_value=self.fixture.measured)):
            item.start(); self.addCleanup(item.stop)

    def test_deterministic_archive_full_readback_and_no_replace(self):
        first = provider.build(self.bundle, self.output)
        second = provider.build(self.bundle, self.root / 'second')
        self.assertEqual(first, second)
        self.assertEqual(first['archiveEntries'], len(first['requiredFiles']))
        self.assertEqual(first['requiredFiles'][provider.COMPILER]['elfMachine'], 183)
        self.assertFalse(first['androidRuntimeQualified']); self.assertFalse(first['gameAssetShadersQualified'])
        self.assertTrue(provider.verify(self.output)['providerVerified'])
        with self.assertRaisesRegex(ValueError, 'output-exists'): provider.build(self.bundle, self.output)

    def test_helper_or_bundle_mutation_prevents_publication(self):
        selected = self.bundle / 'tools/bls/archive.py'; selected.write_bytes(b'tampered\n')
        with self.assertRaisesRegex(ValueError, 'file-mismatch'): provider.build(self.bundle, self.output)
        self.assertFalse(self.output.exists())
        helper = provider.ROOT / 'runtime/shader_generation.py'; helper.write_bytes(b'changed helper\n')
        with self.assertRaisesRegex(ValueError, 'helper-source-changed'): provider.load_pin()

    def test_unknown_files_and_links_cannot_enter_provider(self):
        extra = self.bundle / 'tools/unlisted.py'; extra.write_text('no execution')
        with self.assertRaisesRegex(ValueError, 'file-set-mismatch'): provider.build(self.bundle, self.output)
        extra.unlink()
        target = self.bundle / 'tools/bls/archive.py'; moved = self.root / 'outside'; target.rename(moved); target.symlink_to(moved)
        with self.assertRaisesRegex(ValueError, 'symlink'): provider.build(self.bundle, self.output)

    def test_archive_rejects_special_files_and_wrong_file_order(self):
        pin = provider.load_pin()
        for index, kind in enumerate((tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE)):
            path = self.root / ('invalid-%d.tar.gz' % index)
            with tarfile.open(path, 'w:gz', format=tarfile.GNU_FORMAT) as archive:
                entry = tarfile.TarInfo(next(iter(pin['files']))); entry.type = kind; entry.linkname = '/outside'
                archive.addfile(entry)
            with self.assertRaises(ValueError): provider.verify_archive(path, pin)
        files = provider.selected_files(self.bundle, pin); pins = provider.inventory(pin)
        path = self.root / 'reversed.tar.gz'
        with tarfile.open(path, 'w:gz', format=tarfile.GNU_FORMAT) as archive:
            for name in sorted(files, reverse=True):
                entry = tarfile.TarInfo(name); entry.size = pins[name]['bytes']
                entry.mode = 0o755 if name == provider.COMPILER else 0o644
                with files[name].open('rb') as source: archive.addfile(entry, source)
        with self.assertRaisesRegex(ValueError, 'file-set-or-order'): provider.verify_archive(path, pin)

    def test_apk_requires_exact_assets_and_uncompressed_archive(self):
        provider.build(self.bundle, self.output); assets = self.output / 'assets' / provider.ASSETS
        for compressed in (False, True):
            path = self.root / ('compressed.apk' if compressed else 'stored.apk')
            with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED) as apk:
                for name in provider.NAMES: apk.write(assets / name, 'assets/' + provider.ASSETS + '/' + name)
            if compressed:
                with self.assertRaisesRegex(ValueError, 'must-be-stored'): provider.verify(self.output, path)
            else: self.assertTrue(provider.verify(self.output, path)['apkBytesVerified'])

    def test_unlisted_provider_asset_sibling_is_rejected_without_removal(self):
        provider.build(self.bundle, self.output)
        for relative in ('unlisted.txt', 'assets/private.txt', 'assets/other-provider/input.txt'):
            extra = self.output / relative; extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_bytes(b'explicit synthetic unrelated file')
            with self.assertRaisesRegex(ValueError, 'root-set-mismatch'):
                provider.verify(self.output)
            self.assertEqual(extra.read_bytes(), b'explicit synthetic unrelated file')
            extra.unlink()
            if relative.startswith('assets/other-provider/'):
                extra.parent.rmdir()
        self.assertTrue(provider.verify(self.output)['providerVerified'])


if __name__ == '__main__': unittest.main()
