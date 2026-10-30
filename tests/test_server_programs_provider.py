"""Pending production gate and bounded provider guards; fixtures execute no server."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import provider_server_programs as provider


class ServerProgramsProvider(unittest.TestCase):
    def setUp(self):
        self.pin = provider.load_pin()
        temporary = tempfile.TemporaryDirectory(prefix='server-programs-test-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name).resolve()

    def test_measured_pin_keeps_complete_real_payload_and_pending_source_gate(self):
        pin = self.pin
        self.assertEqual(pin['state'], 'pending-sealed-source-rebuild')
        self.assertEqual(pin['archiveEntries'], 126); self.assertEqual(pin['archiveFileBytes'], 66025007)
        self.assertEqual(len(pin['noticeFiles']), 66)
        self.assertEqual(pin['archive']['bytes'], 21996594)
        self.assertEqual(pin['archive']['sha256'], 'df7e0b33e4048daf780ebf31c0a7f9a10b1f74ea42f4de100ca18ed1a65b673e')
        self.assertIsNone(pin['sourceQualification']); self.assertFalse(pin['sourceCompanionComplete'])
        for flags in ('androidRuntimeQualified', 'gameplayQualified'): self.assertFalse(pin[flags])
        self.assertEqual(set(pin['programPairs']), {'authserver', 'worldserver', 'dbimport'})
        self.assertEqual(provider.descriptor(pin)['guestMount'], '/esteria-server-programs')

    def test_production_build_and_verify_refuse_pending_before_touching_outputs(self):
        output = self.root / 'preserved'; output.mkdir(); marker = output / 'save'; marker.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'real-sealed-source-receipt-required'):
            provider.build(*([self.root] * 5), output)
        with self.assertRaisesRegex(ValueError, 'real-sealed-source-receipt-required'): provider.verify(output)
        self.assertEqual(marker.read_bytes(), b'keep'); self.assertEqual(list(self.root.iterdir()), [output])

    def test_fake_source_boolean_and_missing_receipt_never_enable_provider(self):
        pin = copy.deepcopy(self.pin); pin['sourceCompanionComplete'] = True
        lock = self.root / 'pin.json'; lock.write_bytes(provider.encoded(pin))
        with patch.object(provider, 'LOCK', lock), self.assertRaisesRegex(ValueError, 'sealing-state-inconsistent'): provider.load_pin()
        pin['state'] = 'sealed-source-and-native-loader'; lock.write_bytes(provider.encoded(pin))
        with patch.object(provider, 'LOCK', lock), self.assertRaisesRegex(ValueError, 'real-sealed-source-receipt-required'): provider.load_pin(sealed=True)

    def test_source_lock_and_dependency_drift_refused(self):
        for field in ('appSourceLock', 'requiredServerRuntimeArchive'):
            pin = copy.deepcopy(self.pin); pin[field]['sha256'] = '0' * 64
            lock = self.root / 'pin.json'; lock.write_bytes(provider.encoded(pin))
            with self.subTest(field=field), patch.object(provider, 'LOCK', lock), self.assertRaisesRegex(ValueError, 'source-pin|dependency-selection'):
                provider.load_pin()

    def test_no_arbitrary_executable_or_omitted_notice_can_be_relabelled(self):
        for name in ('bin/other', 'notices/source/LICENSE'):
            pin = copy.deepcopy(self.pin)
            if name.startswith('bin/'):
                pin['files'][name] = pin['files'].pop('bin/dbimport')
            else:
                del pin['files'][name]; pin['archiveEntries'] -= 1; pin['archiveFileBytes'] = sum(r['bytes'] for r in pin['files'].values())
            lock = self.root / 'pin.json'; lock.write_bytes(provider.encoded(pin))
            with self.subTest(name=name), patch.object(provider, 'LOCK', lock), self.assertRaisesRegex(ValueError, 'selected-file-set'):
                provider.load_pin()

    def test_bounded_paths_sizes_modes_and_symlinks(self):
        for path in ('../escape', '/absolute', 'bin/../escape', 'x' * 513):
            with self.subTest(path=path), self.assertRaises(ValueError): provider.safe(path)
        valid = dict(bytes=1, sha256='1'*64, mode=0o444)
        for row in (dict(valid, bytes=65 << 20), dict(valid, mode=0o777)):
            with self.assertRaises(ValueError): provider.validate_inventory({'notice': row}, 2, 64 << 20, 96 << 20)
        plain = self.root / 'plain'; plain.write_bytes(b'real bytes'); alias = self.root / 'alias'; alias.symlink_to(plain)
        with self.assertRaisesRegex(ValueError, 'symlink'): provider.require_file(alias, dict(bytes=10, sha256='1'*64))

    def test_true_loader_flag_cannot_replace_real_binary_and_original_pair_bindings(self):
        pin = self.pin; programs = {n: row['stripped'] for n, row in pin['programPairs'].items()}
        original = dict(scope='unsealed-server-engine-packaging', archiveReadbackVerified=True,
            packages={'runtime': dict(archive=pin['originalRuntimeArchive']),
                      'debug': dict(archive=provider.identity(pin['debugArchive']))})
        selection = dict(programs=programs, packageReceipt=provider.identity(pin['originalPackageReceipt']),
            originalBuild=pin['originalBuild'], originalModules=pin['originalModules'],
            runtimeArchive=pin['originalRuntimeArchive'], debugArchiveIdentified=provider.identity(pin['debugArchive']))
        fixture = dict(formatVersion=1, scope='native-arm64-derived-auth-world-version-only',
            qualificationSucceeded=True, authWorldVersionExecuted=True, dbimportExecuted=False, sqlExecuted=False,
            androidRuntimeQualified=False, gameplayQualified=False, programs=programs, selection=selection,
            outputs={n: pin['serverRevision'][:7] + ' Unix synthetic validation fixture' for n in ('authserver', 'worldserver')})
        provider.validate_loader(fixture, original, pin)
        for mutation in ('program', 'original', 'scope', 'gameplay'):
            loader = copy.deepcopy(fixture)
            if mutation == 'program': loader['programs']['authserver']['sha256'] = '0' * 64
            elif mutation == 'original': loader['selection']['originalModules']['sha256'] = '0' * 64
            elif mutation == 'scope': loader['scope'] = 'fixture'
            else: loader['gameplayQualified'] = True
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'real-derived-native-loader'):
                provider.validate_loader(loader, original, pin)

    def test_final_apk_archive_must_be_exact_stored_and_asset_set_closed(self):
        assets = self.root / 'assets'; assets.mkdir()
        (assets / provider.ARCHIVE).write_bytes(b'explicit synthetic asset bytes, not an executable')
        (assets / 'provider.json').write_bytes(b'{"synthetic":true}\n')
        for method, extra, mutation in ((zipfile.ZIP_STORED, False, False), (zipfile.ZIP_DEFLATED, False, False),
                                        (zipfile.ZIP_STORED, True, False), (zipfile.ZIP_STORED, False, True)):
            apk = self.root / 'app.zip'
            with zipfile.ZipFile(apk, 'w', compression=method) as archive:
                for path in assets.iterdir():
                    data = path.read_bytes()
                    if mutation and path.name == provider.ARCHIVE: data = b'x' * len(data)
                    archive.writestr('assets/server-programs/' + path.name, data)
                if extra: archive.writestr('assets/server-programs/private-state', b'refused')
            if method == zipfile.ZIP_STORED and not extra and not mutation: provider.verify_apk(assets, apk)
            else:
                with self.subTest(method=method, extra=extra, mutation=mutation), self.assertRaises(ValueError): provider.verify_apk(assets, apk)


if __name__ == '__main__': unittest.main()
