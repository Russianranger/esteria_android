#!/usr/bin/env python3
"""Qualify private handoff recovery only on a fresh Android13 x64 emulator.

No native runtime, credentials, client executable or SQL is imported. The APK
fixture is explicit/debug-only; ordinary APK exclusion is verified separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import tempfile
import time
import zipfile

try:
    from .qualify_android_installer import digest, instrument_passed, run_bounded
except ImportError:
    from qualify_android_installer import digest, instrument_passed, run_bounded

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = 'io.github.russianranger.esteria'
PACKAGE = NAMESPACE + '.stock'
SERVICE = NAMESPACE + '.core.runtime.install.HandoffProbeService'
TEST_CLASS = NAMESPACE + '.core.runtime.install.LocalHandoffRecoveryInstrumentedTest'
TEST = TEST_CLASS + '#remoteOwnerDeathRecoversOnlyKnownHandoffs'
BUILD_ASSET = 'assets/handoff-probe/build-evidence.json'
BUILD_SCOPE = 'android-x64-handoff-fixture-build-only'
SCOPE = 'android-13-x86_64-local-handoff-remote-owner-process-death'
ANDROID = 'http://schemas.android.com/apk/res/android'
# Public framework resource IDs, checked against the installed API35 android.R
# constants. A matching string alone cannot establish a compiled AXML attribute.
ANDROID_ATTRS = {'name': 16842755, 'debuggable': 16842767, 'exported': 16842768,
    'process': 16842769, 'targetSdkVersion': 16843376}
INPUTS = (
    'app/build.gradle', 'app/handoff-probe.gradle', 'app/src/handoffProbe/AndroidManifest.xml',
    'app/src/handoffProbe/java/io/github/russianranger/esteria/core/runtime/install/HandoffProbeService.java',
    'app/src/androidTest/java/io/github/russianranger/esteria/core/runtime/install/LocalHandoffRecoveryInstrumentedTest.java',
    'core/src/main/java/io/github/russianranger/esteria/core/runtime/install/LocalAccountHandoff.java',
    'core/src/main/java/io/github/russianranger/esteria/core/runtime/install/LocalHandoffRecovery.java',
    'core/src/main/java/io/github/russianranger/esteria/core/runtime/install/ClientLaunchView.java',
    'core/src/main/java/io/github/russianranger/esteria/core/runtime/install/RuntimeFiles.java',
    'core/src/main/java/io/github/russianranger/esteria/core/runtime/install/RuntimeWork.java',
    'core/src/main/java/io/github/russianranger/esteria/core/runtime/ExclusiveFileLease.java',
    'sources.lock.json', 'tools/qualify_android_handoff.py', 'tests/test_android_handoff.py',
    '.github/workflows/android-handoff-recovery.yml')
BUILD_KEYS = {'formatVersion', 'scope', 'sourceRevision', 'sourceSnapshotExact', 'sourceInputs',
    'productionRuntimeQualified', 'androidExecutionQualified', 'arm64Qualified', 'gameplayQualified'}
FALSE_FLAGS = ('productionAppProcessRestartQualified', 'physicalDeviceQualified', 'clientExecuted',
    'sqlExecuted', 'arm64Qualified', 'gameplayQualified')
CASE_KEYS = {'phase', 'binderDeathObserved', 'ownerInstanceChanged', 'recovered', 'clientRecordBefore',
    'ownerReceiptBefore', 'knownStateMatched', 'unknownStagesPreserved', 'siblingsPreserved',
    'recordAbsentAfterClose', 'receiptAbsentAfterClose'}
CASE_FLAGS = CASE_KEYS - {'phase', 'clientRecordBefore', 'ownerReceiptBefore'}
PHASES = ('created', 'written', 'proof-synced', 'synced', 'consumed')
BEFORE = ((False, False), (False, False), (False, True), (True, True), (False, True))
ACTIVE_FLAGS = {'sameJvmDuplicateRefused', 'crossProcessRefused', 'recordUnchanged', 'released',
    'relaunchAfterRelease', 'siblingsPreserved'}
EXCLUSIVE_FLAGS = {'sameJvmDuplicateRefused', 'crossProcessRefusedAfterDuplicates', 'binderDeathObserved',
    'ownerInstanceChanged', 'leaseReacquiredAfterDeath', 'sameJvmDuplicateRefusedAfterReacquire',
    'crossProcessRefusedAfterReacquire', 'releasedAfterClose', 'siblingPreserved'}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def identity(path):
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 64 << 20, 'handoff-file-bound')
    return dict(bytes=path.stat().st_size, sha256=digest(path))


def source_exact(revision, inputs):
    """Check actual committed blobs and working files; never trust a Boolean."""
    if re.fullmatch('[0-9a-f]{40}', revision or '') is None or set(inputs) != set(INPUTS):
        return False
    environment = dict(os.environ, GIT_OPTIONAL_LOCKS='0', GIT_NO_LAZY_FETCH='1')
    git = ['git', '-C', str(ROOT)]
    try:
        if subprocess.check_output([*git, 'rev-parse', 'HEAD'], env=environment, stderr=subprocess.DEVNULL).decode().strip() != revision:
            return False
        for arguments in (['diff', '--exit-code', '--quiet'], ['diff', '--cached', '--exit-code', '--quiet']):
            if subprocess.run([*git, *arguments], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
                return False
        if subprocess.check_output([*git, 'ls-files', '--others', '--exclude-standard', '-z'],
                env=environment, stderr=subprocess.DEVNULL):
            return False
        for name, row in inputs.items():
            path = ROOT / name
            if not path.is_file() or path.is_symlink() or path.stat().st_size > 1 << 20:
                return False
            raw = subprocess.check_output([*git, 'cat-file', 'blob', revision + ':' + name],
                env=environment, stderr=subprocess.DEVNULL, timeout=20)
            actual = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            if len(raw) > 1 << 20 or actual != row or identity(path) != row:
                return False
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def validate_build(value, revision):
    require(type(value) is dict and set(value) == BUILD_KEYS and type(value.get('formatVersion')) is int and
        value['formatVersion'] == 1 and value.get('scope') == BUILD_SCOPE and value.get('sourceRevision') == revision and
        value.get('sourceSnapshotExact') is True, 'handoff-build-scope-or-snapshot')
    require(all(value.get(key) is False for key in ('productionRuntimeQualified', 'androidExecutionQualified',
        'arm64Qualified', 'gameplayQualified')), 'handoff-build-overclaim')
    rows = value.get('sourceInputs')
    require(type(rows) is dict and set(rows) == set(INPUTS), 'handoff-build-source-input-set')
    for row in rows.values():
        require(type(row) is dict and set(row) == {'bytes', 'sha256'} and type(row.get('bytes')) is int and
            0 < row['bytes'] <= 1 << 20 and re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')) is not None,
            'handoff-build-source-identity')
    require(source_exact(revision, rows), 'handoff-build-exact-source-required')


def manifest_nodes(raw):
    """Read bounded compiled AXML string/element attributes without SDK tools."""
    require(8 <= len(raw) <= 1 << 20, 'handoff-manifest-bound')
    def u16(position):
        require(0 <= position <= len(raw) - 2, 'handoff-manifest-short-u16')
        return struct.unpack_from('<H', raw, position)[0]
    def u32(position):
        require(0 <= position <= len(raw) - 4, 'handoff-manifest-short-u32')
        return struct.unpack_from('<I', raw, position)[0]
    require((u16(0), u16(2), u32(4)) == (3, 8, len(raw)), 'handoff-manifest-binary-xml-required')
    strings = None; resources = None; result = []; stack = []; position = 8; roots = 0
    def text(index):
        require(strings is not None and 0 <= index < len(strings), 'handoff-manifest-string-index')
        return strings[index]
    while position < len(raw):
        require(position + 8 <= len(raw), 'handoff-manifest-chunk-header')
        kind, header, size = u16(position), u16(position + 2), u32(position + 4)
        require(8 <= header <= size and size >= 8 and size % 4 == 0 and size <= len(raw) - position,
            'handoff-manifest-chunk-bound')
        end = position + size
        if kind == 1:
            require(strings is None and header >= 28 and size >= header, 'handoff-manifest-string-pool-header')
            count, styles, flags, start, style_start = (u32(position + offset) for offset in (8, 12, 16, 20, 24))
            require(0 < count <= 65536 and styles == 0 and style_start == 0 and flags & ~0x101 == 0 and
                header + count * 4 <= start <= size, 'handoff-manifest-string-pool-bound')
            strings = []
            for i in range(count):
                cursor = position + start + u32(position + header + i * 4)
                require(position + start <= cursor < end, 'handoff-manifest-string-offset')
                if flags & 0x100:
                    def length8():
                        nonlocal cursor
                        require(cursor < end, 'handoff-manifest-utf8-length')
                        value = raw[cursor]; cursor += 1
                        if value & 0x80:
                            require(cursor < end, 'handoff-manifest-utf8-length')
                            value = ((value & 0x7f) << 8) | raw[cursor]; cursor += 1
                        return value
                    utf16_length, byte_length = length8(), length8()
                    require(byte_length <= end - cursor - 1 and raw[cursor + byte_length] == 0,
                        'handoff-manifest-utf8-bound')
                    value = raw[cursor:cursor + byte_length].decode('utf-8')
                    require(len(value.encode('utf-16-le')) // 2 == utf16_length, 'handoff-manifest-utf8-character-count')
                else:
                    require(cursor + 2 <= end, 'handoff-manifest-utf16-length')
                    length = u16(cursor); cursor += 2
                    if length & 0x8000:
                        require(cursor + 2 <= end, 'handoff-manifest-utf16-length')
                        length = ((length & 0x7fff) << 16) | u16(cursor); cursor += 2
                    require(length <= (end - cursor - 2) // 2 and u16(cursor + length * 2) == 0,
                        'handoff-manifest-utf16-bound')
                    value = raw[cursor:cursor + length * 2].decode('utf-16-le')
                strings.append(value)
        elif kind == 0x180:
            require(strings is not None and resources is None and not result and header == 8 and
                (size - 8) % 4 == 0 and (size - 8) // 4 <= len(strings),
                'handoff-manifest-resource-map')
            resources = {index: u32(position + 8 + index * 4) for index in range((size - 8) // 4)}
        elif kind in (0x100, 0x101):
            require(strings is not None and header == 16 and size == 24, 'handoff-manifest-namespace')
            for index in (u32(position + 16), u32(position + 20)):
                if index != 0xffffffff: text(index)
        elif kind == 0x102:
            require(strings is not None and header == 16 and size >= 36, 'handoff-manifest-element-header')
            namespace, name = u32(position + 16), text(u32(position + 20))
            if namespace != 0xffffffff: text(namespace)
            offset, stride, count = u16(position + 24), u16(position + 26), u16(position + 28)
            require(offset >= 20 and stride >= 20 and count <= 1024 and 16 + offset <= size and
                count * stride <= size - 16 - offset, 'handoff-manifest-attribute-bound')
            attributes = {}
            for i in range(count):
                at = position + 16 + offset + i * stride
                namespace, attribute_index, original = u32(at), u32(at + 4), u32(at + 8)
                attribute = text(attribute_index)
                namespace = None if namespace == 0xffffffff else text(namespace)
                if namespace == ANDROID and attribute in ANDROID_ATTRS:
                    require(resources is not None and resources.get(attribute_index) == ANDROID_ATTRS[attribute],
                        'handoff-manifest-framework-attribute-id')
                require(u16(at + 12) == 8 and raw[at + 14] == 0, 'handoff-manifest-value-header')
                typ, value = raw[at + 15], u32(at + 16)
                key = (namespace, attribute); require(key not in attributes, 'handoff-manifest-duplicate-attribute')
                if typ == 3: value = text(value)
                elif typ == 0x12:
                    require(value in (0, 0xffffffff, 1), 'handoff-manifest-boolean-value'); value = value != 0
                elif typ in (0x10, 0x11): pass
                else: value = ('typed-resource', typ, value)
                if original != 0xffffffff: text(original)
                attributes[key] = value
            if not stack: roots += 1; require(name == 'manifest' and roots == 1, 'handoff-manifest-root')
            result.append(dict(name=name, parents=tuple(stack), attributes=attributes)); stack.append(name)
        elif kind == 0x103:
            require(header == 16 and size == 24 and stack and stack.pop() == text(u32(position + 20)),
                'handoff-manifest-end-element')
        else: raise ValueError('handoff-manifest-unsupported-chunk')
        position = end
    require(position == len(raw) and not stack and roots == 1, 'handoff-manifest-unclosed-tree')
    return result


def class_name(value, package):
    require(type(value) is str and 0 < len(value) <= 256, 'handoff-manifest-class-name')
    return package + value if value.startswith('.') else value if '.' in value else package + '.' + value


def verify_apk(path, enabled=True, revision=None):
    result = identity(path)
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist(); names = [item.filename for item in members]
        require(0 < len(names) <= 10000 and len(names) == len(set(names)), 'handoff-apk-entry-count')
        total = 0
        for item in members:
            name = item.filename; mode = stat.S_IFMT(item.external_attr >> 16)
            require(not name.startswith('/') and chr(92) not in name and not any(x in ('', '..', '.') for x in name.rstrip('/').split('/')) and
                mode in (0, stat.S_IFREG, stat.S_IFDIR) and not item.flag_bits & 1 and 0 <= item.file_size <= 32 << 20,
                'handoff-apk-member-bound')
            total += item.file_size; require(total <= 64 << 20, 'handoff-apk-expanded-bound')
        require(not any(name.startswith('lib/') or name.endswith(('.archive', '.so', '.exe', '.dll')) for name in names),
            'handoff-apk-native-or-runtime-provider')
        require(not any(name.startswith(('assets/proot-', 'assets/wine-', 'assets/client-runtime/', 'assets/server-runtime/',
            'assets/server-programs/', 'assets/server-data-tools/', 'assets/server-content/', 'assets/guest-bridges/',
            'assets/shader-tools/', 'assets/turnip/')) for name in names), 'handoff-apk-runtime-assets')
        manifest = archive.getinfo('AndroidManifest.xml'); require(manifest.file_size <= 1 << 20, 'handoff-manifest-bound')
        nodes = manifest_nodes(archive.read(manifest))
        package = next(row['attributes'].get((None, 'package')) for row in nodes if row['name'] == 'manifest')
        require(package == PACKAGE, 'handoff-apk-package')
        applications = [row for row in nodes if row['name'] == 'application' and row['parents'] == ('manifest',)]
        require(len(applications) == 1, 'handoff-apk-application')
        services = [row for row in nodes if row['name'] == 'service' and row['parents'] == ('manifest', 'application') and
            class_name(row['attributes'].get((ANDROID, 'name')), package) == SERVICE]
        dex_names = [name for name in names if re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex', name)]
        require(0 < len(dex_names) <= 16, 'handoff-apk-dex-set')
        marker = ('L' + SERVICE.replace('.', '/') + ';').encode()
        fixture_class = any(marker in archive.read(name) for name in dex_names)
        assets = {name for name in names if name.startswith('assets/handoff-probe/') and not name.endswith('/')}
        if enabled:
            require(re.fullmatch('[0-9a-f]{40}', revision or '') is not None, 'handoff-full-source-revision-required')
            require(applications[0]['attributes'].get((ANDROID, 'debuggable')) is True and len(services) == 1 and fixture_class,
                'handoff-explicit-debug-service-required')
            sdk = [row for row in nodes if row['name'] == 'uses-sdk' and row['parents'] == ('manifest',)]
            require(len(sdk) == 1 and type(sdk[0]['attributes'].get((ANDROID, 'targetSdkVersion'))) is int and
                sdk[0]['attributes'][(ANDROID, 'targetSdkVersion')] == 35, 'handoff-apk-target-sdk')
            require(services[0]['attributes'].get((ANDROID, 'exported')) is False and
                services[0]['attributes'].get((ANDROID, 'process')) == ':handoffProbe', 'handoff-private-remote-service-required')
            require(assets == {BUILD_ASSET}, 'handoff-apk-build-asset-set')
            info = archive.getinfo(BUILD_ASSET); require(0 < info.file_size <= 65536, 'handoff-build-metadata-bound')
            build = json.loads(archive.read(info)); validate_build(build, revision)
            return dict(result, fixtureEnabled=True, explicitPrivateRemoteServiceVerified=True,
                noNativeOrRuntimeProviderPackaged=True, buildEvidence=build)
        require(not services and not fixture_class and not assets, 'handoff-fixture-leaked-into-ordinary-apk')
        return dict(result, fixtureEnabled=False, fixtureExcluded=True, noNativeOrRuntimeProviderPackaged=True)


def validate_receipt(value, revision, fingerprint, build):
    keys = {'formatVersion', 'scope', 'sourceRevision', 'fingerprint', 'api', 'targetSdk', 'abi', 'buildEvidence',
        'cases', 'activeOwner', 'exclusiveFileLease', 'remoteOwnerProcessesKilled', 'remoteOwnerProcessesRecreated',
        'syntheticClientExecutableNotRun', *FALSE_FLAGS}
    require(type(value) is dict and set(value) == keys and type(value.get('formatVersion')) is int and value['formatVersion'] == 1 and
        value.get('scope') == SCOPE and value.get('sourceRevision') == revision and value.get('fingerprint') == fingerprint and
        value.get('abi') == 'x86_64' and value.get('buildEvidence') == build, 'handoff-receipt-identity')
    for name, expected in (('api', 33), ('targetSdk', 35), ('remoteOwnerProcessesKilled', 6), ('remoteOwnerProcessesRecreated', 6)):
        require(type(value.get(name)) is int and value[name] == expected, 'handoff-receipt-count')
    require(value.get('syntheticClientExecutableNotRun') is True and all(value.get(name) is False for name in FALSE_FLAGS),
        'handoff-receipt-overclaim')
    require(type(value.get('cases')) is list and len(value['cases']) == 5, 'handoff-receipt-five-phases-required')
    for row, phase, before in zip(value['cases'], PHASES, BEFORE):
        require(type(row) is dict and set(row) == CASE_KEYS and row.get('phase') == phase and
            row.get('clientRecordBefore') is before[0] and row.get('ownerReceiptBefore') is before[1] and
            all(row.get(name) is True for name in CASE_FLAGS), 'handoff-receipt-process-death-phase')
    active = value.get('activeOwner')
    require(type(active) is dict and set(active) == ACTIVE_FLAGS and all(active[name] is True for name in ACTIVE_FLAGS),
        'handoff-receipt-active-owner-and-release')
    exclusive = value.get('exclusiveFileLease')
    require(type(exclusive) is dict and set(exclusive) == EXCLUSIVE_FLAGS and
        all(exclusive[name] is True for name in EXCLUSIVE_FLAGS), 'handoff-receipt-exclusive-file-lease')
    return dict(remoteDeathPhasesVerified=5, binderDeathsObserved=True, ownerInstancesChanged=True,
        recognizedRecordsRecovered=True, unknownStagesAndSiblingsPreserved=True,
        sameJvmAndCrossProcessDuplicatesRefused=True, leasesReleasedAndRelaunchPreserved=True,
        exclusiveFileLeaseDeathRecoveryVerified=True, remoteOwnerProcessDeathsVerified=6)


def qualify(apk, test_apk, revision, output, adb='adb'):
    require(re.fullmatch('[0-9a-f]{40}', revision or '') is not None, 'handoff-full-source-revision-required')
    verified = verify_apk(apk, enabled=True, revision=revision)
    test_identity = identity(test_apk)
    with zipfile.ZipFile(test_apk) as archive:
        names = archive.namelist(); require(len(names) == len(set(names)) and len(names) <= 10000, 'handoff-test-apk-inventory')
        require(not any(name.startswith('lib/') or name.endswith(('.archive', '.so', '.exe', '.dll')) for name in names),
            'handoff-test-apk-native-or-runtime-provider')
        dex = [archive.getinfo(name) for name in names if re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex', name)]
        require(0 < len(dex) <= 16 and all(info.file_size <= 32 << 20 for info in dex), 'handoff-test-apk-dex-bound')
        marker = ('L' + TEST_CLASS.replace('.', '/') + ';').encode()
        require(any(marker in archive.read(info) for info in dex), 'handoff-test-class-required')
    output.mkdir(parents=True, exist_ok=False)
    report = dict(formatVersion=1, scope=SCOPE, sourceRevision=revision, apk=verified, testApk=test_identity,
        androidX64HandoffRecoveryQualified=False, **{name: False for name in FALSE_FLAGS})
    installed = False; failure = None; phase = 'emulator-admission'; passed = False
    def command(label, words, timeout=180, allow_failure=False, private=False):
        if private:
            # Validate before exporting. A malformed receipt must not turn an
            # unexpected record, credential, nonce or PID into an artifact.
            with tempfile.TemporaryDirectory(prefix='esteria-handoff-receipt-') as temporary:
                code, raw = run_bounded([adb, *words], Path(temporary) / 'receipt.log', timeout, limit=65536)
        else:
            code, raw = run_bounded([adb, *words], output / (label + '.log'), timeout, limit=256 << 10)
        require(code == 0 or allow_failure, 'handoff-command-' + label); return raw
    try:
        require(re.fullmatch(r'emulator-[0-9]+', command('serial', ['get-serialno']).strip()) is not None,
            'handoff-physical-or-remote-device-refused')
        properties = {name: command(name, ['shell', 'getprop', name]).strip() for name in
            ('ro.kernel.qemu', 'ro.build.version.sdk', 'ro.product.cpu.abi', 'ro.build.fingerprint')}
        report['emulatorProperties'] = properties
        require(tuple(properties[name] for name in ('ro.kernel.qemu', 'ro.build.version.sdk', 'ro.product.cpu.abi')) ==
            ('1', '33', 'x86_64'), 'handoff-disposable-android13-x64-required')
        for name, package in (('app', PACKAGE), ('tests', PACKAGE + '.test')):
            require('package:' not in command('preexisting-' + name, ['shell', 'pm', 'path', package], allow_failure=True),
                'handoff-preexisting-package-refused')
        phase = 'install-owned-fixture'; command('install-app', ['install', str(apk)]); installed = True
        command('install-tests', ['install', str(test_apk)])
        phase = 'remote-owner-death-instrumentation'
        result = command('instrument', ['shell', 'am', 'instrument', '-w', '-r', '-e', 'class', TEST,
            PACKAGE + '.test/androidx.test.runner.AndroidJUnitRunner'], timeout=300)
        require(instrument_passed(result), 'handoff-instrumentation-did-not-pass')
        phase = 'source-bound-receipt-readback'
        raw = command('app-receipt', ['exec-out', 'run-as', PACKAGE, 'cat', 'files/handoff-recovery-qualification.json'], private=True)
        require(0 < len(raw.encode()) <= 65536, 'handoff-app-receipt-bound')
        value = json.loads(raw)
        report['checks'] = validate_receipt(value, revision, properties['ro.build.fingerprint'], verified['buildEvidence'])
        (output / 'app-receipt.json').write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
        report['appEvidence'] = value; passed = True
    except Exception as error:
        failure = error; report['failurePhase'] = phase; report['failureClass'] = type(error).__name__
        token = str(error)
        if re.fullmatch('handoff-[a-z0-9-]{1,120}', token): report['failureGuard'] = token
    finally:
        cleanup = False
        if installed:
            try: command('filtered-logcat', ['logcat', '-d', '-t', '600', 'TestRunner:I', 'AndroidRuntime:E', '*:S'], allow_failure=True)
            except Exception: report['filteredDiagnosticsUnavailable'] = True
            try: command('stop-owned-test-app', ['shell', 'am', 'force-stop', PACKAGE]); cleanup = True
            except Exception as error:
                report['cleanupFailureClass'] = type(error).__name__; failure = failure or error
        report['ownedFixtureStopAcknowledged'] = cleanup
        report['androidX64HandoffRecoveryQualified'] = passed and cleanup and failure is None
        report['completedAtUnix'] = int(time.time())
        (output / 'qualification.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    if failure is not None: raise RuntimeError('handoff-qualification-failed-' + type(failure).__name__) from None
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb')
    for name in ('apk', 'test-apk', 'output'): parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-revision', required=True); args = parser.parse_args()
    report = qualify(args.apk, args.test_apk, args.source_revision, args.output, args.adb)
    print(json.dumps({name: report[name] for name in ('scope', 'androidX64HandoffRecoveryQualified', *FALSE_FLAGS)}, sort_keys=True))


if __name__ == '__main__': main()
