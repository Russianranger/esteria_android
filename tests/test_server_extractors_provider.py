"""Measured extractor provider guards; no fixture establishes source/Android gates."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import provider_server_extractors as provider


class ExtractorProvider(unittest.TestCase):
    def setUp(self):
        self.pin = provider.load_pin()
        temporary = tempfile.TemporaryDirectory(prefix='extractor-provider-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)

    def locked(self, pin):
        path = self.root / 'pin.json'; path.write_bytes(provider.encoded(pin))
        return patch.object(provider, 'LOCK', path)

    def test_actual_measured_inventory_and_exact_retained_source_contract(self):
        pin = self.pin
        self.assertEqual(pin['state'], 'sealed-source-and-native-cli')
        self.assertEqual((pin['archive']['bytes'], pin['archiveEntries'], pin['archiveFileBytes']), (2495044, 76, 7423422))
        self.assertEqual(pin['archive']['sha256'], '2bce13256ac609a7bcb01fd2a7e5352fde29fa19e18a5d269c566acb22f86515')
        self.assertEqual(set(pin['programPairs']), set(provider.PROGRAMS))
        self.assertEqual(len(pin['noticeFiles']), 66)
        self.assertEqual(pin['configuration']['installedPath'], 'etc/mmaps-config.yaml')
        self.assertEqual(provider.identity(pin['files']['etc/mmaps-config.yaml']), provider.identity(pin['configuration']))
        descriptor = provider.descriptor(pin)
        self.assertEqual(descriptor['guestMount'], '/esteria-server-extractors')
        self.assertEqual(len(descriptor['requiredFiles']), 76)
        self.assertEqual({n for n,r in descriptor['requiredFiles'].items() if r.get('elfMachine') == 183},
                         {'bin/' + n for n in provider.PROGRAMS})
        self.assertTrue(descriptor['sourceCompanionVerified'])
        self.assertEqual(pin['sourceQualification']['archive'],dict(bytes=24619647,
            sha256='9f76881f06a7c998e0dba9d4a226c623021ed6ad8b87074aa7a861eafbb96d80'))
        for flag in provider.FALSE_FLAGS: self.assertFalse(pin[flag])

    def test_pending_build_and_verify_refuse_before_output_changes(self):
        output = self.root / 'existing'; output.mkdir(); marker = output / 'saved'; marker.write_bytes(b'keep')
        pending=copy.deepcopy(self.pin);pending.update(state='pending-sealed-source-rebuild',sourceCompanionComplete=False,sourceQualification=None)
        with self.locked(pending):
            with self.assertRaisesRegex(ValueError, 'real-sealed-source-receipt-required'):
                provider.build(self.root, self.root, self.root, self.root, output)
            with self.assertRaisesRegex(ValueError, 'real-sealed-source-receipt-required'): provider.verify(output)
        (self.root/'pin.json').unlink()
        self.assertEqual(marker.read_bytes(), b'keep'); self.assertEqual(list(self.root.iterdir()), [output])

    def test_source_boolean_without_real_pinned_receipts_never_enables_provider(self):
        pin = copy.deepcopy(self.pin); pin.update(state='pending-sealed-source-rebuild',sourceCompanionComplete=True,sourceQualification=None)
        with self.locked(pin), self.assertRaisesRegex(ValueError, 'sealing-state-inconsistent'): provider.load_pin()
        pin['state'] = 'sealed-source-and-native-cli'
        with self.locked(pin), self.assertRaisesRegex(ValueError, 'real-sealed-source-receipt-required'):
            provider.load_pin(sealed=True)

    def test_current_source_packaging_and_dependency_drift_are_refused(self):
        for name in ('appSourceLock', 'packagingPin', 'originalBuild', 'originalModules', 'requiredServerRuntimeArchive'):
            pin = copy.deepcopy(self.pin); pin[name]['sha256'] = '0'*64
            with self.subTest(pin=name), self.locked(pin), self.assertRaises(ValueError): provider.load_pin()

    def test_no_extra_program_omitted_notice_changed_yaml_or_bad_mode(self):
        for kind in ('program', 'notice', 'yaml', 'mode'):
            pin = copy.deepcopy(self.pin)
            if kind == 'program': pin['files']['bin/other'] = pin['files'].pop('bin/map_extractor')
            elif kind == 'notice':
                del pin['files'][pin['noticeFiles'][0]]; pin['archiveEntries'] -= 1
                pin['archiveFileBytes'] = sum(r['bytes'] for r in pin['files'].values())
            elif kind == 'yaml': pin['configuration']['sha256'] = '0'*64
            else: pin['files']['bin/map_extractor']['mode'] = 0o777
            with self.subTest(mutation=kind), self.locked(pin), self.assertRaises(ValueError): provider.load_pin()

    def test_native_flag_cannot_replace_exact_program_source_yaml_and_case_binding(self):
        pin = self.pin; original, _ = provider.package.load_pin()
        cli = dict(formatVersion=1, scope='native-arm64-derived-extractor-argument-config-validation-only',
            qualificationSucceeded=True, originalDefaultMmapsConfigParsed=True, emptyWorkingDirectoriesUnchanged=True,
            clientMpqsSupplied=False, sourceCompanionComplete=False, packageReceipt=pin['packageReceipt'],
            packagingPin=pin['packagingPin'], originalBuild=pin['originalBuild'], runtimeArchive=provider.identity(pin['archive']),
            programs={n: pin['programPairs'][n]['stripped'] for n in provider.PROGRAMS},
            cases={c['name']:dict(exitCode=c['exitCode'],output='\n'.join(c['contains'])) for c in original['cliCases']},
            **{k:False for k in provider.FALSE_FLAGS})
        provider.validate_native(cli, pin)
        for mutation in ('program', 'source', 'yaml', 'case', 'conversion'):
            changed = copy.deepcopy(cli)
            if mutation == 'program': changed['programs']['map_extractor']['sha256'] = '0'*64
            elif mutation == 'source': changed['packagingPin']['sha256'] = '0'*64
            elif mutation == 'yaml': changed['originalDefaultMmapsConfigParsed'] = False
            elif mutation == 'case': changed['cases']['map-usage']['exitCode'] = 0
            else: changed['customEsteriaDataLoadOrderQualified'] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): provider.validate_native(changed,pin)

    def test_archive_asset_must_be_stored_exact_and_closed(self):
        assets = self.root / 'assets'; assets.mkdir()
        (assets / provider.ARCHIVE).write_bytes(b'fixture, no actual ELF')
        (assets / 'provider.json').write_bytes(b'{"fixture":true}\n')
        for method, extra, changed in ((zipfile.ZIP_STORED,False,False), (zipfile.ZIP_DEFLATED,False,False),
                                       (zipfile.ZIP_STORED,True,False), (zipfile.ZIP_STORED,False,True)):
            apk = self.root / 'app.zip'
            with zipfile.ZipFile(apk,'w',compression=method) as archive:
                for path in assets.iterdir():
                    raw = path.read_bytes()
                    if changed and path.name == provider.ARCHIVE: raw = b'x'*len(raw)
                    archive.writestr('assets/server-extractors/'+path.name,raw)
                if extra: archive.writestr('assets/server-extractors/private-state',b'refused')
            if method == zipfile.ZIP_STORED and not extra and not changed: provider.verify_apk(assets,apk)
            else:
                with self.subTest(method=method,extra=extra,changed=changed), self.assertRaises(ValueError):
                    provider.verify_apk(assets,apk)


@unittest.skipUnless(os.environ.get('ESTERIA_EXTRACTOR_REAL_INPUTS'), 'exact retained extractor inputs not supplied')
class ActualRetainedInputs(unittest.TestCase):
    def test_full_actual_runtime_and_native_receipt_readback_without_execution(self):
        root = Path(os.environ['ESTERIA_EXTRACTOR_REAL_INPUTS']).resolve(strict=True)
        proof = provider.audit(root / 'package', root / 'native/extractor-cli.json')
        self.assertTrue(proof['payloadVerified']); self.assertTrue(proof['nativeArgumentConfigReceiptVerified'])
        self.assertFalse(proof['sourceCompanionComplete']); self.assertFalse(proof['productionProviderCreated'])
        self.assertFalse(proof['clientMpqConversionQualified'])

    def test_flagged_synthetic_source_receipt_cannot_replace_actual_complete_rebuild(self):
        root = Path(os.environ['ESTERIA_EXTRACTOR_REAL_INPUTS']).resolve(strict=True)
        pin = provider.load_pin()
        with tempfile.TemporaryDirectory() as temporary:
            companion = Path(temporary)
            for dest, source in (('package-receipt.json',root/'package/package-receipt.json'),
                ('native-cli.json',root/'native/extractor-cli.json'),
                (pin['debugArchive']['file'],root/'package'/pin['debugArchive']['file'])):
                os.link(source,companion/dest)
            # A fabricated success flag lacks observed full configure/build/install
            # and references. It is never accepted as production source qualification.
            qualified = dict(formatVersion=1,scope='actual-native-arm64-isolated-server-source-rebuild',
                phase='complete',sourceCompanionComplete=True)
            (companion/'qualification.json').write_bytes(provider.encoded(qualified))
            (companion/provider.SOURCE_ARCHIVE).write_bytes(b'fixture source archive, not actual qualification')
            pin['sourceQualification'] = dict(qualification=provider.files.identity(companion/'qualification.json'),
                archive=provider.files.identity(companion/provider.SOURCE_ARCHIVE))
            q = pin['sourceQualification']
            sealed = dict(formatVersion=1,scope='complete-isolated-server-source-rebuild-companion',
                archiveReadbackVerified=True,sourceCompanionComplete=True,isolatedSourceRebuildQualified=True,
                originalUnsealedReceiptsUnchanged=True,bitIdenticalOriginalBinariesClaimed=False,sqlExecuted=False,
                androidRuntimeQualified=False,gameplayQualified=False,
                archive=dict(file=provider.SOURCE_ARCHIVE,**q['archive']),qualification=q['qualification'],
                sourceInputArchive=provider.identity(pin['originalSourceInputs']['archive']),
                sourceInputReceipt=pin['originalSourceInputs']['receipt'],originalBuild=pin['originalBuild'],
                originalCompiledModules=pin['originalModules'],sourceLock=pin['serverBuildSourceLock'])
            (companion/'sealed-source-receipt.json').write_bytes(provider.encoded(sealed))
            q['receipt'] = provider.files.identity(companion/'sealed-source-receipt.json')
            with self.assertRaisesRegex(ValueError,'actual-full-source-rebuild-required'): provider.verify_sources(companion,pin)


if __name__ == '__main__': unittest.main()
