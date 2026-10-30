#!/usr/bin/env python3
"""Run real Surface/AudioTrack protocol fixtures on a disposable Android13 x64 emulator."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import time
import zipfile

try:
    from .qualify_android_installer import digest, instrument_passed, run_bounded
except ImportError:
    from qualify_android_installer import digest, instrument_passed, run_bounded

PACKAGE = 'io.github.russianranger.esteria'
TEST = PACKAGE + '.presentation.PresentationAudioTest#actualSurfaceAndAudioTrackContracts'
SCOPE = 'android-13-x86_64-surface-audiotrack-protocol-fixtures'
FLAGS = ('nativeSurfaceExecuted', 'rgbaReadbackVerified', 'surfaceRecreationVerified', 'invalidFrameRejected',
         'audioResetVerified', 'audioInvalidHandshakeRecovered', 'privateSocketCleanupVerified',
         'privateRootAliasVerified', 'privateChildSymlinkRejected')
UNQUALIFIED = ('arm64GuestExecuted', 'androidWineExecuted', 'x11GuestExecuted', 'audibleOutputQualified',
               'adrenoQualified', 'gameplayQualified')


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def apk_identity(path):
    require(0 < path.stat().st_size <= 64 * 1024**2, 'apk-size-limit')
    native = {}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), 'duplicate-apk-member')
        expected = {'lib/x86_64/libesteria_process.so', 'lib/x86_64/libesteria-presentation.so'}
        require({name for name in names if name.startswith('lib/')} == expected, 'explicit-x64-bridge-apk-required')
        for name in sorted(expected):
            entry = archive.getinfo(name)
            require(64 <= entry.file_size <= 16 * 1024**2, 'jni-size-limit')
            with archive.open(entry) as stream:
                header = stream.read(64)
                require(header[:7] == b'\x7fELF\x02\x01\x01' and struct.unpack_from('<HH', header, 16) == (3, 62) and
                        struct.unpack_from('<Q', header, 24)[0] == 0, 'jni-is-not-x64-shared-library')
                checksum = hashlib.sha256(header)
                while block := stream.read(131072):
                    checksum.update(block)
            native[name] = dict(bytes=entry.file_size, sha256=checksum.hexdigest())
    return dict(bytes=path.stat().st_size, sha256=digest(path), native=native)


def validate_receipt(value, revision, fingerprint):
    require(type(value.get('formatVersion')) is int and value['formatVersion'] == 1 and value.get('scope') == SCOPE and
            value.get('sourceRevision') == revision and value.get('fingerprint') == fingerprint and value.get('abi') == 'x86_64',
            'presentation-receipt-identity')
    for key, expected in (('api', 33), ('targetSdk', 35), ('groupsPassed', 5)):
        require(type(value.get(key)) is int and value[key] == expected, 'presentation-receipt-count-' + key)
    accepted, played = value.get('audioTrackAcceptedFrames'), value.get('audioTrackPlayedFrames')
    require(type(accepted) is int and type(played) is int and 4800 <= accepted <= played <= 96000,
            'real-audiotrack-clock-did-not-consume-fixture')
    require(all(value.get(flag) is True for flag in FLAGS), 'presentation-receipt-missing-check')
    require(all(value.get(flag) is False for flag in UNQUALIFIED), 'presentation-receipt-overclaims-scope')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--test-apk', type=Path, required=True)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(re.fullmatch('[0-9a-f]{40}', args.source_revision) is not None, 'full-source-revision-required')
    identity = apk_identity(args.apk)
    require(0 < args.test_apk.stat().st_size <= 64 * 1024**2, 'test-apk-size-limit')
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(formatVersion=1, scope=SCOPE, sourceRevision=args.source_revision, apk=identity,
                  testApk=dict(bytes=args.test_apk.stat().st_size, sha256=digest(args.test_apk)),
                  androidEmulatorSurfaceAudioQualified=False, **{key: False for key in UNQUALIFIED})
    installed = False
    failure = None

    def command(label, words, timeout=180, allow_failure=False):
        code, text = run_bounded([args.adb, *words], args.output / (label + '.log'), timeout)
        require(code == 0 or allow_failure, label + '-command-failed')
        return code, text

    try:
        _, serial = command('serial', ['get-serialno'])
        require(re.fullmatch('emulator-[0-9]+', serial.strip()) is not None, 'physical-or-remote-device-refused')
        properties = {}
        for name in ('ro.kernel.qemu', 'ro.build.version.sdk', 'ro.product.cpu.abi', 'ro.build.fingerprint'):
            _, text = command(name, ['shell', 'getprop', name]); properties[name] = text.strip()
        report['emulatorProperties'] = properties
        require(tuple(properties[name] for name in ('ro.kernel.qemu', 'ro.build.version.sdk', 'ro.product.cpu.abi')) ==
                ('1', '33', 'x86_64'), 'android13-x64-emulator-required')
        _, existing = command('preexisting', ['shell', 'pm', 'path', PACKAGE], allow_failure=True)
        require('package:' not in existing, 'preexisting-installation-refused')
        command('install-app', ['install', str(args.apk)]); installed = True
        command('grant-fixture-notification-permission', ['shell', 'pm', 'grant', PACKAGE, 'android.permission.POST_NOTIFICATIONS'])
        command('install-tests', ['install', str(args.test_apk)])
        _, result = command('presentation-audio-contracts', ['shell', 'am', 'instrument', '-w', '-r', '-e', 'class', TEST,
                            PACKAGE + '.test/androidx.test.runner.AndroidJUnitRunner'], timeout=180)
        require(instrument_passed(result), 'android-presentation-test-did-not-pass')
        _, raw = command('app-receipt', ['exec-out', 'run-as', PACKAGE, 'cat', 'files/presentation-audio-qualification.json'])
        require(len(raw.encode()) <= 65536, 'oversized-app-receipt')
        evidence = json.loads(raw)
        validate_receipt(evidence, args.source_revision, properties['ro.build.fingerprint'])
        report['appEvidence'] = evidence
        report['androidEmulatorSurfaceAudioQualified'] = True
    except Exception as error:
        failure = error; report['error'] = str(error)
    finally:
        if installed:
            for label, words in [('bounded-logcat', ['logcat', '-d', '-t', '1500']),
                                 ('stop-owned-test-app', ['shell', 'am', 'force-stop', PACKAGE])]:
                try:
                    command(label, words, allow_failure=label == 'bounded-logcat')
                except Exception as error:
                    report['androidEmulatorSurfaceAudioQualified'] = False
                    report.setdefault('cleanupErrors', []).append(str(error)); failure = failure or error
        report['completedAtUnix'] = int(time.time())
        (args.output / 'qualification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if failure:
        raise failure


if __name__ == '__main__':
    main()
