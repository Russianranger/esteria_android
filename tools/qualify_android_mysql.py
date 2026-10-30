#!/usr/bin/env python3
"""Execute real MySQL bootstrap/restart only in a disposable Android13 x64 emulator."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
try:
    from .qualify_android_installer import digest, instrument_passed, run_bounded
    from .verify_android_mysql_probe import verify, require
except ImportError:
    from qualify_android_installer import digest, instrument_passed, run_bounded
    from verify_android_mysql_probe import verify, require

PACKAGE = 'io.github.russianranger.esteria'
SCOPE = 'android-13-x86_64-mysql-bootstrap-and-restart'
FLAGS = ('exactBootstrapHelpersVerified', 'runtimeInstalledByProductionInstaller', 'databaseInitialized',
         'rootSqlAuthenticated', 'applicationSqlAuthenticated', 'socketOnly', 'instanceIdentityVerified',
         'persistentMarkerRestored', 'credentialsPreserved', 'cleanShutdown', 'repeatBootstrapPreserved')
FALSE_FLAGS = ('productionAdapterQualified', 'arm64Qualified', 'serverSchemasQualified', 'worldserverQualified', 'gameplayQualified')


def validate_receipt(value, revision, fingerprint, proof_raw, proot):
    proof = json.loads(proof_raw)
    require(type(value.get('formatVersion')) is int and value['formatVersion'] == 1 and value.get('scope') == SCOPE and
            value.get('sourceRevision') == revision and value.get('fingerprint') == fingerprint and value.get('abi') == 'x86_64', 'mysql-receipt-identity')
    for name, expected in (('api', 33), ('targetSdk', 35), ('guestLaunches', 4)):
        require(type(value.get(name)) is int and value[name] == expected, 'mysql-receipt-count-' + name)
    require(value.get('mysqlVersion') == proof['expectedMysqlSqlVersion'] and
            value.get('runtimeProviderSha256') == hashlib.sha256(proof_raw).hexdigest() and
            value.get('runtimeArchiveSha256') == proof['archive']['sha256'] and
            re.fullmatch('[a-f0-9]{64}', value.get('runtimeGeneration', '')) and value.get('prootBuildEvidence') == proot, 'mysql-receipt-build-identity')
    require(all(value.get(flag) is True for flag in FLAGS), 'mysql-receipt-missing-behavior')
    require(all(value.get(flag) is False for flag in FALSE_FLAGS), 'mysql-receipt-overclaim')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb')
    for name in ('apk', 'test-apk', 'provider', 'proot-provider', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-revision', required=True)
    args = parser.parse_args()
    require(re.fullmatch('[a-f0-9]{40}', args.source_revision), 'full-source-revision-required')
    verify(args.provider, args.proot_provider, args.apk)
    require(0 < args.test_apk.stat().st_size <= 64 * 1024**2, 'mysql-test-apk-size-limit')
    proof_raw = (args.provider / 'assets/mysql-probe/provider.json').read_bytes()
    proot = json.loads((args.proot_provider / 'assets/proot-probe/build-evidence.json').read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(formatVersion=1, scope=SCOPE, sourceRevision=args.source_revision,
                  apk=dict(bytes=args.apk.stat().st_size, sha256=digest(args.apk)),
                  testApk=dict(bytes=args.test_apk.stat().st_size, sha256=digest(args.test_apk)),
                  androidMysqlBootstrapQualified=False, **{key: False for key in FALSE_FLAGS})
    installed = False; failure = None
    def command(label, words, timeout=180, allow_failure=False):
        code, text = run_bounded([args.adb, *words], args.output / (label + '.log'), timeout)
        require(code == 0 or allow_failure, label + '-command-failed')
        return code, text
    try:
        _, serial = command('serial', ['get-serialno'])
        require(re.fullmatch('emulator-[0-9]+', serial.strip()), 'physical-or-remote-device-refused')
        properties = {}
        for name in ('ro.kernel.qemu', 'ro.build.version.sdk', 'ro.product.cpu.abi', 'ro.build.fingerprint'):
            _, raw = command(name, ['shell', 'getprop', name]); properties[name] = raw.strip()
        report['emulatorProperties'] = properties
        require(tuple(properties[name] for name in ('ro.kernel.qemu', 'ro.build.version.sdk', 'ro.product.cpu.abi')) == ('1', '33', 'x86_64'), 'android13-x64-emulator-required')
        _, current = command('preexisting', ['shell', 'pm', 'path', PACKAGE], allow_failure=True)
        require('package:' not in current, 'preexisting-installation-refused')
        command('install-app', ['install', str(args.apk)]); installed = True
        command('install-tests', ['install', str(args.test_apk)])
        _, result = command('mysql-test', ['shell', 'am', 'instrument', '-w', '-r', '-e', 'class',
            PACKAGE + '.runtime.MySqlExecutionTest#actualMysqlInitializesAuthenticatesAndRestarts',
            PACKAGE + '.test/androidx.test.runner.AndroidJUnitRunner'], timeout=1800)
        require(instrument_passed(result), 'mysql-instrumentation-did-not-pass')
        _, raw = command('app-receipt', ['exec-out', 'run-as', PACKAGE, 'cat', 'files/mysql-probe-qualification.json'])
        require(len(raw.encode()) <= 65536, 'mysql-receipt-size-limit')
        evidence = json.loads(raw)
        validate_receipt(evidence, args.source_revision, properties['ro.build.fingerprint'], proof_raw, proot)
        report['appEvidence'] = evidence; report['androidMysqlBootstrapQualified'] = True
    except Exception as error:
        failure = error; report['error'] = str(error)
    finally:
        if installed:
            for phase in ('initialize', 'seed', 'verify', 'repeat'):
                for stream in ('stdout', 'stderr'):
                    try:
                        command(phase + '-' + stream, ['exec-out', 'run-as', PACKAGE, 'cat',
                            'files/mysql-probe-session/sessions/' + phase + '/logs/' + stream + '.log'], allow_failure=True)
                    except Exception as error:
                        report.setdefault('diagnosticErrors', []).append(str(error))
                # Only Java-sanitized engine diagnostics are read; never state/config/SQL.
                try:
                    _, listing = command(phase + '-engine-files', ['exec-out', 'run-as', PACKAGE, 'ls',
                        'files/mysql-probe-session/sessions/' + phase + '/logs'], allow_failure=True)
                    files = [name for name in listing.splitlines() if name.startswith('engine-')]
                    require(len(files) <= 16 and all(re.fullmatch('engine-[a-z0-9.-]{1,80}', name) for name in files), 'engine-log-inventory')
                    for name in files:
                        command(phase + '-' + name, ['exec-out', 'run-as', PACKAGE, 'cat',
                            'files/mysql-probe-session/sessions/' + phase + '/logs/' + name], allow_failure=True)
                except Exception as error:
                    report.setdefault('diagnosticErrors', []).append(str(error))
            for label, words in [('bounded-logcat', ['logcat', '-d', '-t', '1200']),
                                 ('stop-owned-test-app', ['shell', 'am', 'force-stop', PACKAGE])]:
                try:
                    command(label, words, allow_failure=label != 'stop-owned-test-app')
                except Exception as error:
                    report['androidMysqlBootstrapQualified'] = False; report.setdefault('cleanupErrors', []).append(str(error))
                    if failure is None: failure = error
        report['completedAtUnix'] = int(time.time())
        (args.output / 'qualification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if failure is not None: raise failure


if __name__ == '__main__': main()
