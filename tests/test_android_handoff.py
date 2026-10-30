"""Bounded compiled-manifest, receipt and emulator-admission behavior."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import qualify_android_handoff as handoff


def axml(enabled=True, *, utf8=True, exported=False, process=':handoffProbe', debug=True,
        resource_override=None, target_sdk=35):
    """Small actual binary-XML chunks; never an installable application."""
    strings = ['manifest', 'package', handoff.PACKAGE, 'uses-sdk', handoff.ANDROID, 'targetSdkVersion',
        'application', 'debuggable', 'service', 'name', handoff.SERVICE, 'exported', 'process', process, 'A\U0001f409']
    index = {name: i for i, name in enumerate(strings)}
    def length8(value): return bytes([value]) if value < 128 else bytes([(value >> 8) | 0x80, value & 255])
    blob = b''; offsets = []
    for text in strings:
        offsets.append(len(blob)); raw = text.encode('utf-8' if utf8 else 'utf-16-le')
        units = len(text.encode('utf-16-le')) // 2
        blob += length8(units) + length8(len(raw)) + raw + b'\0' if utf8 else struct.pack('<H', units) + raw + b'\0\0'
    blob += b'\0' * (-len(blob) % 4)
    start = 28 + len(strings) * 4
    pool = struct.pack('<HHI5I', 1, 28, start + len(blob), len(strings), 0, 0x100 if utf8 else 0, start, 0)
    pool += struct.pack('<' + 'I' * len(offsets), *offsets) + blob
    resources = [0] * len(strings)
    for name, resource in dict(handoff.ANDROID_ATTRS, **(resource_override or {})).items():
        if name in index: resources[index[name]] = resource
    resource_map = struct.pack('<HHI', 0x180, 8, 8 + 4 * len(resources)) + struct.pack('<' + 'I' * len(resources), *resources)
    def element(name, attributes):
        values = b''
        for namespace, key, value in attributes:
            typ = 0x12 if type(value) is bool else 0x10 if type(value) is int else 3
            data = (0xffffffff if value else 0) if typ == 0x12 else value if typ == 0x10 else index[value]
            values += struct.pack('<IIIHBBI', index[namespace] if namespace else 0xffffffff,
                index[key], 0xffffffff, 8, 0, typ, data)
        size = 36 + len(values)
        return struct.pack('<HHIII', 0x102, 16, size, 1, 0xffffffff) + struct.pack('<II6H',
            0xffffffff, index[name], 20, 20, len(attributes), 0, 0, 0) + values
    def end(name): return struct.pack('<HHIIIII', 0x103, 16, 24, 1, 0xffffffff, 0xffffffff, index[name])
    body = element('manifest', [(None, 'package', handoff.PACKAGE)])
    body += element('uses-sdk', [(handoff.ANDROID, 'targetSdkVersion', target_sdk)]) + end('uses-sdk')
    body += element('application', [(handoff.ANDROID, 'debuggable', debug)])
    if enabled:
        body += element('service', [(handoff.ANDROID, 'name', handoff.SERVICE),
            (handoff.ANDROID, 'exported', exported), (handoff.ANDROID, 'process', process)]) + end('service')
    body += end('application') + end('manifest')
    return struct.pack('<HHI', 3, 8, 8 + len(pool) + len(resource_map) + len(body)) + pool + resource_map + body


def build():
    return dict(formatVersion=1, scope=handoff.BUILD_SCOPE, sourceRevision='a'*40, sourceSnapshotExact=True,
        sourceInputs={name: dict(bytes=1, sha256='b'*64) for name in handoff.INPUTS},
        productionRuntimeQualified=False, androidExecutionQualified=False, arm64Qualified=False, gameplayQualified=False)


def receipt():
    return dict(formatVersion=1, scope=handoff.SCOPE, sourceRevision='a'*40, fingerprint='emulator-fixture',
        api=33, targetSdk=35, abi='x86_64', buildEvidence=build(),
        cases=[dict(phase=phase, clientRecordBefore=before[0], ownerReceiptBefore=before[1],
            **{flag: True for flag in handoff.CASE_FLAGS}) for phase, before in zip(handoff.PHASES, handoff.BEFORE)],
        activeOwner={flag: True for flag in handoff.ACTIVE_FLAGS}, remoteOwnerProcessesKilled=5,
        remoteOwnerProcessesRecreated=5, syntheticClientExecutableNotRun=True,
        **{name: False for name in handoff.FALSE_FLAGS})


class AndroidHandoff(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)

    def apk(self, name='probe.apk', *, enabled=True, metadata=None, manifest=None, extra=None):
        path = self.root / name
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('AndroidManifest.xml', manifest if manifest is not None else axml(enabled))
            marker = ('L' + handoff.SERVICE.replace('.', '/') + ';').encode() if enabled else b'ordinary-profile-only'
            archive.writestr('classes.dex', b'dex\n035\0' + marker)
            if enabled: archive.writestr(handoff.BUILD_ASSET, json.dumps(metadata if metadata is not None else build()))
            for member, raw in (extra or {}).items(): archive.writestr(member, raw)
        return path

    def test_actual_binary_xml_utf8_utf16_and_framework_attribute_ids(self):
        for utf8 in (True, False):
            nodes = handoff.manifest_nodes(axml(utf8=utf8))
            service = next(row for row in nodes if row['name'] == 'service')
            self.assertFalse(service['attributes'][(handoff.ANDROID, 'exported')])
            self.assertEqual(service['attributes'][(handoff.ANDROID, 'process')], ':handoffProbe')
        with self.assertRaisesRegex(ValueError, 'framework-attribute-id'):
            handoff.manifest_nodes(axml(resource_override={'exported': handoff.ANDROID_ATTRS['name']}))
        malformed = bytearray(axml()); struct.pack_into('<I', malformed, 12, len(malformed) + 4)
        with self.assertRaises(ValueError): handoff.manifest_nodes(malformed)
        with self.assertRaisesRegex(ValueError, 'binary-xml-required'): handoff.manifest_nodes(b'<manifest/>')

    def test_explicit_debug_service_build_source_and_ordinary_exclusion_are_distinct(self):
        with patch.object(handoff, 'source_exact', return_value=True) as source:
            value = handoff.verify_apk(self.apk(), revision='a'*40)
        self.assertTrue(value['fixtureEnabled']); source.assert_called_once_with('a'*40, build()['sourceInputs'])
        ordinary = self.apk('ordinary.apk', enabled=False)
        self.assertTrue(handoff.verify_apk(ordinary, enabled=False)['fixtureExcluded'])
        with self.assertRaisesRegex(ValueError, 'fixture-leaked'):
            handoff.verify_apk(self.root / 'probe.apk', enabled=False)

    def test_exported_main_process_release_or_wrong_sdk_manifest_is_refused(self):
        changes = [dict(exported=True), dict(process='main'), dict(debug=False), dict(target_sdk=34)]
        for i, change in enumerate(changes):
            with self.subTest(change=change), patch.object(handoff, 'source_exact', return_value=True), self.assertRaises(ValueError):
                handoff.verify_apk(self.apk(str(i)+'.apk', manifest=axml(**change)), revision='a'*40)

    def test_native_runtime_or_additional_fixture_assets_cannot_enter_profile(self):
        for i, member in enumerate(('lib/x86_64/injected.so', 'assets/server-runtime/provider.json',
                'assets/handoff-probe/credentials.bin', '../outside')):
            with self.subTest(member=member), patch.object(handoff, 'source_exact', return_value=True), self.assertRaises(ValueError):
                handoff.verify_apk(self.apk(str(i)+'.apk', extra={member: b'not admitted'}), revision='a'*40)

    def test_build_scope_exact_snapshot_and_each_source_pin_are_required(self):
        original = build()
        for change in (dict(formatVersion=True), dict(sourceSnapshotExact=False), dict(androidExecutionQualified=True),
                dict(sourceRevision='floating'), dict(extra='unlisted')):
            with self.subTest(change=change), patch.object(handoff, 'source_exact', return_value=True), self.assertRaises(ValueError):
                handoff.validate_build(dict(original, **change), 'a'*40)
        bad = copy.deepcopy(original); bad['sourceInputs'][handoff.INPUTS[0]]['bytes'] = True
        with self.assertRaisesRegex(ValueError, 'source-identity'): handoff.validate_build(bad, 'a'*40)
        with patch.object(handoff, 'source_exact', return_value=False), self.assertRaisesRegex(ValueError, 'exact-source-required'):
            handoff.validate_build(original, 'a'*40)
        self.assertFalse(handoff.source_exact('uncommitted', original['sourceInputs']))

    def test_all_five_real_death_phases_active_owner_and_false_scope_are_required(self):
        value = receipt(); result = handoff.validate_receipt(value, 'a'*40, 'emulator-fixture', build())
        self.assertEqual(result['remoteDeathPhasesVerified'], 5)
        for i in range(5):
            for key in ('binderDeathObserved', 'ownerInstanceChanged', 'recovered', 'unknownStagesPreserved', 'siblingsPreserved'):
                bad = copy.deepcopy(value); bad['cases'][i][key] = False
                with self.subTest(phase=i, key=key), self.assertRaisesRegex(ValueError, 'process-death-phase'):
                    handoff.validate_receipt(bad, 'a'*40, 'emulator-fixture', build())
        bad = copy.deepcopy(value); bad['cases'][0]['ownerReceiptBefore'] = True
        with self.assertRaises(ValueError): handoff.validate_receipt(bad, 'a'*40, 'emulator-fixture', build())
        for key in handoff.ACTIVE_FLAGS:
            bad = copy.deepcopy(value); bad['activeOwner'][key] = False
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'active-owner-and-release'):
                handoff.validate_receipt(bad, 'a'*40, 'emulator-fixture', build())
        for key in handoff.FALSE_FLAGS:
            bad = copy.deepcopy(value); bad[key] = True
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'overclaim'):
                handoff.validate_receipt(bad, 'a'*40, 'emulator-fixture', build())

    def test_receipt_rejects_missing_extra_fields_boolean_counts_and_foreign_source(self):
        for changed in (dict(api=True), dict(remoteOwnerProcessesKilled=4), dict(sourceRevision='b'*40),
                dict(fingerprint='foreign'), dict(buildEvidence={}), dict(pid=1234)):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                handoff.validate_receipt(dict(receipt(), **changed), 'a'*40, 'emulator-fixture', build())
        bad = receipt(); bad['cases'] = list(reversed(bad['cases']))
        with self.assertRaisesRegex(ValueError, 'process-death-phase'):
            handoff.validate_receipt(bad, 'a'*40, 'emulator-fixture', build())

    def fake_transport(self, serial='emulator-5554', preexisting=None, fail_stop=False, fail_test=False, bad_receipt=False):
        calls = []
        def run(words, path, timeout, limit):
            calls.append(words); args = words[1:]; code = 0
            if args == ['get-serialno']: raw = serial
            elif args[:2] == ['shell', 'getprop']:
                raw = {'ro.kernel.qemu':'1', 'ro.build.version.sdk':'33', 'ro.product.cpu.abi':'x86_64',
                    'ro.build.fingerprint':'emulator-fixture'}[args[2]]
            elif args[:3] == ['shell', 'pm', 'path']:
                raw = 'package:/existing/private.apk' if args[3] == preexisting else ''
            elif args[:3] == ['shell', 'am', 'instrument']:
                if fail_test: raise RuntimeError('private-record-and-password-must-not-be-exported')
                raw = 'OK (1 test)\nINSTRUMENTATION_CODE: -1\n'
            elif args[:2] == ['exec-out', 'run-as']:
                value = receipt()
                if bad_receipt: value['recordContents'] = 'private-record-must-never-enter-artifacts'
                raw = json.dumps(value)
            elif args[:3] == ['shell', 'am', 'force-stop']:
                raw = ''; code = 1 if fail_stop else 0
            else: raw = ''
            path.write_text(raw); return code, raw
        return calls, run

    def run_transport(self, runner):
        apk = self.apk(); test_apk = self.root / 'tests.apk'
        with zipfile.ZipFile(test_apk, 'w') as archive:
            archive.writestr('classes.dex', ('L'+handoff.TEST_CLASS.replace('.', '/')+';').encode())
        with patch.object(handoff, 'verify_apk', return_value=dict(fixtureEnabled=True, buildEvidence=build())), \
                patch.object(handoff, 'run_bounded', side_effect=runner):
            return handoff.qualify(apk, test_apk, 'a'*40, self.root / 'evidence', adb='fixture-adb')

    def test_physical_and_preexisting_app_or_test_package_are_preserved_before_install(self):
        for serial, existing in (('physical-device', None), ('emulator-5554', handoff.PACKAGE),
                ('emulator-5554', handoff.PACKAGE+'.test')):
            with self.subTest(serial=serial, existing=existing):
                case = tempfile.TemporaryDirectory(); self.addCleanup(case.cleanup); self.root = Path(case.name)
                calls, runner = self.fake_transport(serial=serial, preexisting=existing)
                with self.assertRaises(RuntimeError): self.run_transport(runner)
                self.assertFalse(any(words[1] == 'install' for words in calls))
                value = json.loads((self.root/'evidence/qualification.json').read_bytes())
                self.assertFalse(value['androidX64HandoffRecoveryQualified'])

    def test_cleanup_is_mandatory_and_failure_receipt_never_exports_exception_body(self):
        calls, runner = self.fake_transport(fail_test=True)
        with self.assertRaises(RuntimeError): self.run_transport(runner)
        raw = (self.root/'evidence/qualification.json').read_text()
        self.assertNotIn('private-record-and-password', raw)
        self.assertTrue(any(words[1:4] == ['shell','am','force-stop'] for words in calls))
        case = tempfile.TemporaryDirectory(); self.addCleanup(case.cleanup); self.root = Path(case.name)
        calls, runner = self.fake_transport(fail_stop=True)
        with self.assertRaises(RuntimeError): self.run_transport(runner)
        self.assertFalse(json.loads((self.root/'evidence/qualification.json').read_bytes())['androidX64HandoffRecoveryQualified'])

    def test_unvalidated_app_receipt_is_private_and_never_exported(self):
        calls, runner = self.fake_transport(bad_receipt=True)
        with self.assertRaises(RuntimeError): self.run_transport(runner)
        output = self.root / 'evidence'
        self.assertFalse((output / 'app-receipt.log').exists())
        self.assertFalse((output / 'app-receipt.json').exists())
        for path in output.iterdir():
            self.assertNotIn(b'private-record-must-never-enter-artifacts', path.read_bytes())


if __name__ == '__main__': unittest.main()
