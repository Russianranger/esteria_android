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

NAMESPACE = 'io.github.russianranger.esteria'
PACKAGE = NAMESPACE + '.stock'
TEST = NAMESPACE + '.core.runtime.install.RuntimeInstallationInstrumentedTest'
HELPER_TEST = NAMESPACE + '.runtime.DatabaseServiceAssetsTest'
SCHEMA_HELPER_TEST = NAMESPACE + '.runtime.ServerSchemaAssetsTest'
INSTALLATION_HELPER_TEST = NAMESPACE + '.runtime.ServerInstallationAssetsTest'
DATA_HELPER_TEST = NAMESPACE + '.runtime.ServerDataAssetsTest'
SESSION_HELPER_TEST = NAMESPACE + '.runtime.ServerSessionAssetsTest'
HELPER_ASSET_FILES = {'server-installation': 18, 'server-data': 6, 'server-session': 24}
PREPARATION_TEST = NAMESPACE + '.PreparationControlsTest'
PREPARATION_METHODS = (
    'selectedSpeedSurvivesActivityRecreationWithoutStartingPreparation',
    'criticalTrimBacksOffWithHeadroomAndActualLowMemoryStillPauses',
    'workerPolicyScopeCarriesOnlySelectedSpeed',
    'storagePreviewAndTrimPreserveCurrentImportsSavesAndWorldWork',
)
PREPARATION_SOURCES = (
    'app/src/androidTest/java/io/github/russianranger/esteria/PreparationControlsTest.java',
    'app/src/main/java/io/github/russianranger/esteria/MainActivity.java',
    'app/src/main/java/io/github/russianranger/esteria/SessionService.java',
    'app/src/main/java/io/github/russianranger/esteria/ImportIoController.java',
    'app/src/main/java/io/github/russianranger/esteria/WorldPreparationDiagnostics.java',
    'app/src/main/java/io/github/russianranger/esteria/runtime/ProotProcess.java',
    'app/src/main/res/values/ids.xml',
    'core/src/main/java/io/github/russianranger/esteria/core/runtime/install/PreparationSpeed.java',
    'core/src/main/java/io/github/russianranger/esteria/core/runtime/install/RuntimeReadPolicy.java',
    'core/src/main/java/io/github/russianranger/esteria/core/runtime/install/RuntimeStorageMaintenance.java',
    'core/src/main/java/io/github/russianranger/esteria/core/runtime/install/RuntimeInstaller.java',
    'core/src/main/java/io/github/russianranger/esteria/core/runtime/install/RuntimeFiles.java',
    'core/src/main/java/io/github/russianranger/esteria/core/runtime/ExclusiveFileLease.java',
    'tools/qualify_android_installer.py',
    '.github/workflows/android-instrumentation.yml',
)
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

def named_instrumentation_passed(output, test_class, methods):
    """Require one start and success for every exact method, not an aggregate OK."""
    if (not methods or len(set(methods)) != len(methods) or
        not re.search(r'^OK \(' + str(len(methods)) + r' tests\)\s*$', output, re.M) or
        re.findall(r'^INSTRUMENTATION_CODE: (-?[0-9]+)\s*$', output, re.M) != ['-1'] or
        re.search(r'FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed', output)):
        return False
    starts, finished, bundle, active = [], [], {}, None
    for line in output.splitlines():
        if line.startswith('INSTRUMENTATION_STATUS: '):
            key, separator, value = line[24:].partition('=')
            if separator and key in ('class', 'test', 'current', 'numtests'):
                if key in bundle:
                    return False
                bundle[key] = value
        elif line.startswith('INSTRUMENTATION_STATUS_CODE: '):
            try:
                code = int(line[29:])
            except ValueError:
                return False
            if code == 2 and not bundle:
                continue  # Bounded sendStatus observation, not a test outcome.
            if (set(bundle) != {'class', 'test', 'current', 'numtests'} or
                bundle['class'] != test_class or bundle['test'] not in methods or
                bundle['numtests'] != str(len(methods)) or
                bundle['current'] != str(len(finished) + 1)):
                return False
            name = bundle['test']
            if code == 1 and active is None and name not in starts:
                starts.append(name)
                active = name
            elif code == 0 and active == name and name not in finished:
                finished.append(name)
                active = None
            else:
                return False
            bundle = {}
    return not bundle and active is None and set(starts) == set(methods) and set(finished) == set(methods)

def validate_preparation_observations(observations):
    if (not isinstance(observations, list) or len(observations) != len(PREPARATION_METHODS) or
        any(not isinstance(row, dict) for row in observations) or
        {row.get('case') for row in observations} != set(PREPARATION_METHODS)):
        raise RuntimeError('Expected four distinct measured preparation control observations')
    if any(row.get('scope') != 'android13-x64-preparation-controls-fixture' or
        any(row.get(key) is not False for key in ('ownerGameData', 'thorQualified', 'gameplayQualified'))
        for row in observations):
        raise RuntimeError('Preparation component observation has a changed qualification boundary')
    rows = {row['case']: row for row in observations}
    ui = rows[PREPARATION_METHODS[0]]
    if (type(ui.get('visibleLevels')) is not int or ui['visibleLevels'] != 3 or ui.get('defaultSpeed') != 'balanced' or
        ui.get('reopenedSpeed') != 'fast' or ui.get('operationUnchanged') is not True or
        ui.get('rates') != dict(gentle=8 << 20, balanced=32 << 20, fast=64 << 20)):
        raise RuntimeError('Preparation control selection observation differs')
    pressure = rows[PREPARATION_METHODS[1]]
    if (any(type(pressure.get(key)) is not int for key in ('healthyCriticalTrimLevel', 'realLowMemoryLevel',
            'unknownMemoryCriticalTrimLevel', 'selectedNormalBytesPerSecond', 'pressureBytesPerSecond')) or
        pressure.get('healthyCriticalTrimLevel') != 1 or pressure.get('realLowMemoryLevel') != 2 or
        pressure.get('unknownMemoryCriticalTrimLevel') != 2 or pressure.get('actualTrimRecorded') is not True or
        pressure.get('selectedNormalBytesPerSecond') != 32 << 20 or pressure.get('pressureBytesPerSecond') != 2 << 20):
        raise RuntimeError('Preparation pressure/backoff observation differs')
    scope = rows[PREPARATION_METHODS[2]]
    if any(scope.get(key) is not True for key in ('workerScoped', 'nestedSelectionRestored',
        'unrelatedWorkerUnaffected', 'inputEnvironmentUnchanged', 'afterCloseUnselected')):
        raise RuntimeError('Preparation worker scope observation differs')
    storage = rows[PREPARATION_METHODS[3]]
    if (type(storage.get('previewBytes')) is not int or storage['previewBytes'] <= 0 or
        type(storage.get('removedBytes')) is not int or storage['removedBytes'] != storage['previewBytes'] or
        type(storage.get('afterReclaimableBytes')) is not int or storage['afterReclaimableBytes'] != 0 or
        any(storage.get(key) is not True for key in ('currentAndExpectedPreserved',
            'importSavesAndPartialWorldPreserved', 'outsideSymlinkTargetPreserved', 'busyRefused'))):
        raise RuntimeError('Preparation storage maintenance observation differs')
    return rows

def qualify_preparation_components(root, destination, properties, artifacts, revision, adb='adb'):
    """Run the separate v9 UI/policy/storage fixture on the same emulator only."""
    if (properties.get('ro.kernel.qemu'), properties.get('ro.build.version.sdk'),
        properties.get('ro.product.cpu.abi')) != ('1', '33', 'x86_64'):
        raise RuntimeError('Preparation controls require the same disposable Android13 x64 emulator')
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise RuntimeError('Preparation component needs the exact application source revision')
    receipt = dict(formatVersion=1,
        scope='android13-x64-preparation-controls-pressure-and-owned-storage-components',
        appSourceRevision=revision, contentProfile='stock-3.3.5a',
        testClass=PREPARATION_TEST, namedTests=list(PREPARATION_METHODS),
        expectedTests=len(PREPARATION_METHODS), emulatorProperties=properties, artifacts=artifacts,
        sources={name: dict(bytes=(root / name).stat().st_size, sha256=digest(root / name))
            for name in PREPARATION_SOURCES},
        componentTestsExecuted=False, componentTestsPassed=False,
        exactNamedTestSuccessStatusesVerified=False,
        ownerGameDataImported=False, realLowMemoryKillReproduced=False,
        nativeExtractorExecuted=False, androidArm64Qualified=False,
        thorQualified=False, gameplayQualified=False)
    log = destination / 'preparation-controls-component.log'
    try:
        code, output = run_bounded([adb, 'shell', 'am', 'instrument', '-w', '-r', '-e', 'class',
            PREPARATION_TEST, PACKAGE + '.test/androidx.test.runner.AndroidJUnitRunner'], log, 600, 256 * 1024)
        receipt.update(componentTestsExecuted=True, processExitCode=code)
        passed = code == 0 and named_instrumentation_passed(output, PREPARATION_TEST, PREPARATION_METHODS)
        observations = [json.loads(line.split('PREPARATION_CONTROLS=', 1)[1].strip())
            for line in output.splitlines() if 'PREPARATION_CONTROLS=' in line]
        validate_preparation_observations(observations)
        receipt['observations'] = observations
        receipt.update(componentTestsPassed=passed, exactNamedTestSuccessStatusesVerified=passed)
        if not passed:
            raise RuntimeError('Preparation controls did not report exactly four named successful tests')
    except Exception as error:
        receipt['failure'] = type(error).__name__ + ': ' + str(error)[:1024]
        raise
    finally:
        if log.exists():
            receipt['stdout'] = dict(bytes=log.stat().st_size, sha256=digest(log))
        (destination / 'preparation-controls-component.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return receipt

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
    test('completeSessionHelperClosureInstallsAndReusesExactBytes', SESSION_HELPER_TEST)
    test('privateDataMetadataBindingRejectsChangedAncestryAndQualificationClaims', SESSION_HELPER_TEST)
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
        installationHelperAssetFiles=HELPER_ASSET_FILES['server-installation'], installationHelperAssetsQualified=True, installationSetupExecuted=False,
        dataHelperAssetFiles=HELPER_ASSET_FILES['server-data'], dataHelperAssetsQualified=True, dataPreparationExecuted=False,
        sessionHelperAssetFiles=HELPER_ASSET_FILES['server-session'], sessionHelperAssetsQualified=True, privateDataMetadataBindingQualified=True,
        authWorldSessionExecuted=False,
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
