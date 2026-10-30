#!/usr/bin/env python3
"""Run filesystem/update contracts only on a disposable Android 13 x64 emulator."""
from __future__ import annotations
import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import time
import threading

PACKAGE = 'io.github.russianranger.esteria'
TEST = PACKAGE + '.core.runtime.install.RuntimeInstallationInstrumentedTest'
HELPER_TEST = PACKAGE + '.runtime.DatabaseServiceAssetsTest'
SCHEMA_HELPER_TEST = PACKAGE + '.runtime.ServerSchemaAssetsTest'
INSTALLATION_HELPER_TEST = PACKAGE + '.runtime.ServerInstallationAssetsTest'
DATA_HELPER_TEST = PACKAGE + '.runtime.ServerDataAssetsTest'
SCHEMA_HELPER_METHODS = ('nestedOriginalSourcesInstallAndResumeWithoutRewriting',
    'unexpectedNestedModuleIsPreservedAndRefused',
    'linkedResourceDirectoryIsPreservedAndRefused')
HELPER_METHODS = ('actualBundledHelpersInstallAndRepeatWithoutRewriting',
    'changedExistingHelperIsPreservedAndRefused',
    'partialGenerationResumesAndRetainsHarmlessInterruptedWrite',
    'extraModulesNativeExtensionsAndCachesCannotEnterImportPath',
    'expectedHelperSymlinkNeverReplacesOrWritesItsTarget',
    'temporarySymlinkDoesNotBypassClosure')

def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(131072), b''):
            value.update(chunk)
    return value.hexdigest()

def instrument_passed(output):
    return bool(re.search(r'^OK \(1 test\)\s*$', output, re.M) and
                re.search(r'^INSTRUMENTATION_CODE: -1\s*$', output, re.M) and
                not re.search(r'FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed|INSTRUMENTATION_STATUS_CODE: -[12]', output))

def run_bounded(words, destination, timeout, limit=2 * 1024 * 1024):
    """Drain the child continuously while retaining at most limit bytes."""
    errors = []
    retained = 0
    truncated = False
    with destination.open('xb') as log:
        process = subprocess.Popen(words, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        def drain():
            nonlocal retained, truncated
            try:
                while True:
                    chunk = process.stdout.read(65536)
                    if not chunk:
                        break
                    keep = min(len(chunk), limit - retained)
                    log.write(chunk[:keep])
                    retained += keep
                    truncated = truncated or keep != len(chunk)
            except Exception as error:
                errors.append(error)
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        timed_out = False
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            code = process.wait()
        reader.join(timeout=5)
        if reader.is_alive():
            raise RuntimeError('Diagnostic pipe did not close after process exit')
        process.stdout.close()
        if errors:
            raise RuntimeError('Diagnostic drain failed') from errors[0]
        if timed_out:
            raise RuntimeError('Command timed out; bounded log retained')
    if truncated:
        raise RuntimeError('Command exceeded diagnostic limit; bounded log retained')
    return code, destination.read_text(errors='replace')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--initial-apk', type=pathlib.Path, required=True)
    parser.add_argument('--update-apk', type=pathlib.Path, required=True)
    parser.add_argument('--test-apk', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    def command(label, words, timeout=180, allow_failure=False):
        destination = args.output / (label + '.log')
        result, text = run_bounded([args.adb, *words], destination, timeout)
        if result and not allow_failure:
            raise RuntimeError(label + ' failed; see retained log')
        return result, text
    _, serial = command('serial', ['get-serialno'])
    if not re.fullmatch(r'emulator-[0-9]+', serial.strip()):
        raise RuntimeError('Qualification refuses physical/remote devices')
    properties = {}
    for name in ('ro.kernel.qemu', 'ro.build.version.sdk', 'ro.product.cpu.abi', 'ro.build.fingerprint'):
        _, value = command(name, ['shell', 'getprop', name])
        properties[name] = value.strip()
    if (properties['ro.kernel.qemu'], properties['ro.build.version.sdk'], properties['ro.product.cpu.abi']) != ('1', '33', 'x86_64'):
        raise RuntimeError('Requires a disposable Android 13 x86_64 emulator')
    _, existing = command('preexisting-package', ['shell', 'pm', 'path', PACKAGE], allow_failure=True)
    if 'package:' in existing:
        raise RuntimeError('Refusing to overwrite a preexisting application installation')
    artifacts = {name: {'bytes': path.stat().st_size, 'sha256': digest(path)} for name, path in (
        ('initialApk', args.initial_apk), ('updateApk', args.update_apk), ('testApk', args.test_apk))}
    command('install-initial', ['install', str(args.initial_apk)])
    command('install-tests', ['install', str(args.test_apk)])
    def test(method, test_class=TEST):
        _, output = command(method, ['shell', 'am', 'instrument', '-w', '-r', '-e', 'class',
            test_class + '#' + method, PACKAGE + '.test/androidx.test.runner.AndroidJUnitRunner'], timeout=600)
        if not instrument_passed(output):
            raise RuntimeError(method + ' did not report one successful test')
        return output
    for method in HELPER_METHODS:
        test(method, HELPER_TEST)
    for method in SCHEMA_HELPER_METHODS:
        test(method, SCHEMA_HELPER_TEST)
    test('completeInstallationHelperClosureInstallsAndReusesExactBytes', INSTALLATION_HELPER_TEST)
    test('completeDataHelperClosureInstallsAndReusesExactBytes', DATA_HELPER_TEST)
    runtime_contracts = test('runtimeContracts')
    groups = re.findall(r'^INSTRUMENTATION_STATUS: esteriaRuntimeContractGroups=([1-9][0-9]?)\s*$', runtime_contracts, re.M)
    if len(groups) != 1:raise RuntimeError('Missing completed runtime filesystem group count')
    handoff = test('privateLocalLoginHandoffContracts')
    link_policy = re.findall(r'^INSTRUMENTATION_STATUS: esteriaHandoffHardLinksCreated=(true|false)\s*$', handoff, re.M)
    if len(link_policy) != 1:raise RuntimeError('Missing handoff filesystem link-policy observation')
    test('seedBeforeUpdate')
    command('install-update-preserving-data', ['install', '-r', str(args.update_apk)])
    test('verifyAfterUpdate')
    receipt = dict(formatVersion=1, scope='android-13-x86_64-installer-and-apk-update',
        emulatorProperties=properties, artifacts=artifacts, runtimeContractGroups=int(groups[0]),
        databaseHelperAssetContractGroups=len(HELPER_METHODS), databaseHelperAssetsQualified=True,
        schemaHelperAssetContractGroups=len(SCHEMA_HELPER_METHODS), schemaHelperAssetsQualified=True, schemaSqlExecuted=False,
        installationHelperAssetFiles=18, installationHelperAssetsQualified=True, installationSetupExecuted=False,
        dataHelperAssetFiles=5, dataHelperAssetsQualified=True, dataPreparationExecuted=False,
        databaseServiceExecuted=False,
        runtimeFilesystemQualified=True, sameJobDebugKeyUpdatePreservedRuntimeAndSentinel=True,
        privateLocalLoginHandoffFilesystemQualified=True, clientLoginExecuted=False,
        handoffHardLinkCreationPermitted=link_policy[0] == 'true',
        handoffMultiLinkNegativeExecuted=link_policy[0] == 'true',
        userSigningIdentityQualified=False, arm64GuestExecuted=False, gameplayQualified=False,
        completedAtUnix=int(time.time()))
    (args.output / 'qualification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))

if __name__ == '__main__':
    main()
