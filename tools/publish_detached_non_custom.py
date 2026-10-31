#!/usr/bin/env python3
"""Publish an exact stock APK update with a public, detached APK signature.

The private key never enters this workflow. The selected successful package and
native SQL runs, their immutable artifact digests, the source pins, the original
signing receipt and actual SDK verification all precede any release mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
from urllib.parse import quote
import zipfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime.server_update_setup import STOCK_SQL_POLICY


try:
    from . import release_server_dependencies as github
    from . import sign_android_apk as signing
    from . import prepare_non_custom_release as release
except ImportError:
    import release_server_dependencies as github
    import sign_android_apk as signing
    import prepare_non_custom_release as release

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'Russianranger/esteria_android'
BRANCH = 'non-custom'
FAILED_SQL_RUN = 41211067232  # Retained failure; never reused as success.
PACKAGE_WORKFLOW = '.github/workflows/android-local-game-profile.yml'
SQL_WORKFLOW = '.github/workflows/server-installation-native.yml'
PUBLICATION_DIRECTORY = 'runtime/releases/non-custom/update-3'
SELECTION = ROOT / PUBLICATION_DIRECTORY / 'publication-inputs.json'
RECIPE = PUBLICATION_DIRECTORY + '/signature-recipe.json'
RECEIPT = PUBLICATION_DIRECTORY + '/signing-receipt.json'
SCOPE = 'exact-non-custom-detached-signature-publication'
MAX_JSON = 4 << 20
MAX_ARTIFACT = 500_000_000
HEX = re.compile('[0-9a-f]{64}')
require = signing.require


def unique(rows):
    value = {}
    for key, item in rows:
        require(key not in value, 'duplicate-json-field')
        value[key] = item
    return value


def read_json(path, maximum=MAX_JSON):
    path = signing.plain(path)
    require(path.stat().st_size <= maximum, 'publication-json-bound')
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def pin(value, maximum=MAX_ARTIFACT):
    require(type(value) is dict and set(value) == {'bytes', 'sha256'} and
        type(value['bytes']) is int and 0 < value['bytes'] <= maximum and
        type(value['sha256']) is str and HEX.fullmatch(value['sha256']), 'publication-file-pin')
    return value


def identity(path):
    path = signing.plain(path)
    return dict(bytes=path.stat().st_size, sha256=signing.digest(path))


def checked_local(name, value, maximum=MAX_JSON):
    pin(value, maximum)
    path = ROOT / name
    require(identity(path) == value, 'publication-local-file-identity')
    return path


def artifact_pin(value, name):
    require(type(value) is dict and set(value) == {'id', 'name', 'bytes', 'sha256'} and
        type(value['id']) is int and value['id'] > 0 and value['name'] == name,
        'publication-artifact-selection')
    pin({key: value[key] for key in ('bytes', 'sha256')})
    return value


def schema():
    """Canonical requirements, deliberately containing no made-up run/artifact IDs."""
    file_pin = dict(type='object', required=['bytes', 'sha256'], additionalProperties=False,
        properties=dict(bytes=dict(type='integer', minimum=1, maximum=MAX_ARTIFACT),
            sha256=dict(type='string', pattern='^[0-9a-f]{64}$')))
    artifact = copy_json(file_pin)
    artifact['required'] += ['id', 'name']
    artifact['properties'].update(id=dict(type='integer', minimum=1), name=dict(type='string'))
    properties = dict(formatVersion=dict(const=1), scope=dict(const=SCOPE), repository=dict(const=REPOSITORY),
        branch=dict(const=BRANCH), appRevision=dict(type='string', pattern='^[0-9a-f]{40}$'),
        packageRunId=dict(type='integer', minimum=1), packageJobId=dict(type='integer', minimum=1),
        packageWorkflow=dict(const=PACKAGE_WORKFLOW), packageArtifact=artifact,
        nativeSqlRunId=dict(type='integer', minimum=1), nativeSqlJobId=dict(type='integer', minimum=1),
        nativeSqlRevision=dict(type='string', pattern='^[0-9a-f]{40}$'),
        nativeSqlWorkflow=dict(const=SQL_WORKFLOW), nativeSqlArtifact=copy_json(artifact),
        signatureRecipe=copy_json(file_pin), signingReceipt=copy_json(file_pin),
        sourceLock=copy_json(file_pin), stockSigningLock=copy_json(file_pin))
    return dict(type='object', additionalProperties=False, required=list(properties), properties=properties,
        applicationPolicy=dict(packageId=signing.STOCK_PACKAGE,
            versionCode='strictly greater than the pinned lastPublished versionCode',
            versionName='0.1.0-non-custom.<versionCode>',
            previousPublished='exact pinned stock signing baseline'),
        localInputPaths=dict(signatureRecipe=RECIPE, signingReceipt=RECEIPT,
            sourceLock='sources.lock.json', stockSigningLock='app/stock-signing.lock.json'))


def copy_json(value):
    return json.loads(json.dumps(value))


def inspect_metadata(package_metadata, native_metadata, package_job_id, native_job_id):
    """Build actual selection pins from unmodified GitHub artifact metadata reads.

    This is preparation only: the final stage independently fetches live run,
    job, artifact, ZIP, native SQL and SDK proof before permitting publication.
    """
    rows = [read_json(package_metadata), read_json(native_metadata)]
    require(type(package_job_id) is int and package_job_id > 0 and type(native_job_id) is int and native_job_id > 0,
        'publication-inspection-actual-job-ids-required')
    artifacts = []
    for row, prefix in zip(rows, ('unsigned-local-game-profile-release-arm64-', 'server-installation-native-evidence-')):
        workflow = row.get('workflow_run', {})
        revision, run_id = workflow.get('head_sha'), workflow.get('id')
        require(type(revision) is str and re.fullmatch('[0-9a-f]{40}', revision) and type(run_id) is int and run_id > 0 and
            workflow.get('head_branch') == BRANCH and type(row.get('digest')) is str and
            row['digest'].startswith('sha256:'), 'publication-inspection-artifact-metadata')
        selected = dict(id=row.get('id'), name=row.get('name'), bytes=row.get('size_in_bytes'), sha256=row['digest'][7:])
        artifact_pin(selected, prefix + revision)
        verify_artifact_record(row, selected, run_id, revision)
        artifacts.append((selected, run_id, revision))
    package, package_run, app_revision = artifacts[0]
    native, native_run, native_revision = artifacts[1]
    require(native_run != FAILED_SQL_RUN, 'publication-failed-native-run-preserved')
    value = dict(formatVersion=1, scope=SCOPE, repository=REPOSITORY, branch=BRANCH,
        appRevision=app_revision, packageRunId=package_run, packageJobId=package_job_id,
        packageWorkflow=PACKAGE_WORKFLOW, packageArtifact=package,
        nativeSqlRunId=native_run, nativeSqlJobId=native_job_id, nativeSqlRevision=native_revision,
        nativeSqlWorkflow=SQL_WORKFLOW, nativeSqlArtifact=native)
    missing = []
    for name, key in ((RECIPE, 'signatureRecipe'), (RECEIPT, 'signingReceipt'),
            ('sources.lock.json', 'sourceLock'), ('app/stock-signing.lock.json', 'stockSigningLock')):
        if (ROOT / name).is_file():
            value[key] = identity(ROOT / name)
        else:
            missing.append(name)
    return dict(selection=value, missingLocalInputs=missing, selectionComplete=not missing,
        liveWorkflowAndSdkQualificationPerformed=False)


def selection(path=SELECTION):
    value = read_json(path)
    require(type(value) is dict and set(value) == {'formatVersion', 'scope', 'repository', 'branch',
        'appRevision', 'packageRunId', 'packageJobId', 'packageWorkflow', 'packageArtifact',
        'nativeSqlRunId', 'nativeSqlJobId', 'nativeSqlRevision', 'nativeSqlWorkflow', 'nativeSqlArtifact',
        'signatureRecipe', 'signingReceipt', 'sourceLock', 'stockSigningLock'}, 'publication-selection-schema')
    require(type(value['formatVersion']) is int and value['formatVersion'] == 1 and value['scope'] == SCOPE and
        value['repository'] == REPOSITORY and value['branch'] == BRANCH and
        type(value['appRevision']) is str and re.fullmatch('[0-9a-f]{40}', value['appRevision']) and
        type(value['packageRunId']) is int and value['packageRunId'] > 0 and
        type(value['packageJobId']) is int and value['packageJobId'] > 0 and
        value['packageWorkflow'] == PACKAGE_WORKFLOW and type(value['nativeSqlRunId']) is int and
        value['nativeSqlRunId'] > 0 and value['nativeSqlRunId'] != FAILED_SQL_RUN and
        type(value['nativeSqlJobId']) is int and value['nativeSqlJobId'] > 0 and
        type(value['nativeSqlRevision']) is str and re.fullmatch('[0-9a-f]{40}', value['nativeSqlRevision']) and
        value['nativeSqlWorkflow'] == SQL_WORKFLOW, 'publication-fixed-producer-boundary')
    artifact_pin(value['packageArtifact'], 'unsigned-local-game-profile-release-arm64-' + value['appRevision'])
    artifact_pin(value['nativeSqlArtifact'], 'server-installation-native-evidence-' + value['nativeSqlRevision'])
    for name, key, maximum in ((RECIPE, 'signatureRecipe', 2 << 20), (RECEIPT, 'signingReceipt', 128 << 10),
            ('sources.lock.json', 'sourceLock', 2 << 20), ('app/stock-signing.lock.json', 'stockSigningLock', 16384)):
        checked_local(name, value[key], maximum)
    lock = signing.load_lock(ROOT / 'app/stock-signing.lock.json')
    application_identity(read_json(ROOT / RECEIPT), lock)
    return value


def application_identity(receipt, lock):
    """Bind an increasing stock update to the exact previous signing baseline.

    The signer already verified the previous APK with the SDK. Its receipt pins
    that result to this unchanged public lock; final SDK verification below
    independently verifies the new certificate, package, version and payload.
    """
    require(type(receipt) is dict and lock['packageId'] == signing.STOCK_PACKAGE,
        'publication-stock-identity-required')
    signed = receipt.get('signedApk', {})
    require(type(signed) is dict and signed.get('packageId') == signing.STOCK_PACKAGE and
        signed.get('certificateSha256') == lock['certificateSha256'] and
        type(signed.get('versionCode')) is int and
        0 < signed['versionCode'] <= 2_100_000_000 and signed.get('debuggable') is False and
        signed.get('versionName') == '0.1.0-non-custom.' + str(signed['versionCode']),
        'publication-stock-update-identity')
    baseline = lock['lastPublished']
    previous = receipt.get('previousPublished')
    require((previous is None if baseline is None else type(previous) is dict and
        set(previous) == {'versionCode', 'apkSha256'} and type(previous.get('versionCode')) is int) and
        previous == baseline and
        (signed['versionCode'] == 1 if baseline is None else signed['versionCode'] > baseline['versionCode']),
        'publication-stock-update-baseline')
    return dict(packageId=signing.STOCK_PACKAGE, versionCode=signed['versionCode'], versionName=signed['versionName'])


SQL_DIAGNOSTIC_ONLY_PATHS = frozenset((
    'tools/qualify_server_installation.py', 'tests/test_server_installation_qualification.py',
    'tools/export_apk_signature.py', 'tools/publish_detached_non_custom.py',
    'tests/test_detached_non_custom_publication.py', 'tests/test_apk_detached_signature.py',
    '.github/workflows/publish-non-custom-detached.yml', 'STATUS.md', 'HANDOFF.md',
    'BUILDING.md', 'NON-CUSTOM-TESTING.md', 'runtime/releases/non-custom/README.md'))


def verify_sql_source_equivalence(api, app_revision, revision):
    """A diagnostic rerun may differ while all packaged production bytes stay exact.

    The first native run failed and is retained. Only explicit observation/tests
    and public publication metadata may change between the APK producer and the
    successful SQL runner. Any runtime/profile/pin/workflow change requires a
    newly built APK and deliberate producer repin, rather than inherited proof.
    """
    require(type(revision) is str and re.fullmatch('[0-9a-f]{40}', revision) and
        type(app_revision) is str and re.fullmatch('[0-9a-f]{40}', app_revision), 'publication-native-sql-revision')
    if revision == app_revision:
        return dict(appRevision=app_revision, nativeSqlRevision=revision, identicalSourceRevision=True,
            productionRuntimeProfileAndProviderInputsUnchanged=True, diagnosticOnlyChangedPaths=[])
    value = api.json('/compare/' + app_revision + '...' + revision)
    rows = value.get('files', [])
    require(value.get('status') == 'ahead' and value.get('merge_base_commit', {}).get('sha') == app_revision and
        type(value.get('ahead_by')) is int and 0 < value['ahead_by'] <= 64 and
        type(rows) is list and 0 < len(rows) < 300, 'publication-native-sql-source-ancestry')
    names = []
    for row in rows:
        name = row.get('filename', '')
        allowed = name in SQL_DIAGNOSTIC_ONLY_PATHS or bool(re.fullmatch(
            r'runtime/releases/non-custom/[A-Za-z0-9_.-]+\.json', name))
        require(allowed and row.get('status') in ('added', 'modified') and
            'previous_filename' not in row, 'publication-native-sql-production-source-changed')
        names.append(name)
    require(len(names) == len(set(names)), 'publication-native-sql-duplicate-diff-path')
    return dict(appRevision=app_revision, nativeSqlRevision=revision, identicalSourceRevision=False,
        productionRuntimeProfileAndProviderInputsUnchanged=True, diagnosticOnlyChangedPaths=sorted(names))


def verify_run(api, run_id, job_id, workflow, job_name, mandatory_steps, revision):
    run = api.json('/actions/runs/' + str(run_id))
    require(run.get('id') == run_id and run.get('repository', {}).get('full_name') == REPOSITORY and
        run.get('head_repository', {}).get('full_name') == REPOSITORY and run.get('head_sha') == revision and
        run.get('head_branch') == BRANCH and run.get('path') == workflow and
        run.get('status') == 'completed' and run.get('conclusion') == 'success' and
        run.get('event') in ('push', 'workflow_dispatch'), 'publication-required-run-not-successful')
    jobs = api.json('/actions/runs/' + str(run_id) + '/jobs?per_page=100')
    rows = [item for item in jobs.get('jobs', []) if item.get('id') == job_id]
    require(len(rows) == 1 and rows[0].get('run_id') == run_id and rows[0].get('name') == job_name and
        rows[0].get('head_sha') == revision and rows[0].get('status') == 'completed' and
        rows[0].get('conclusion') == 'success', 'publication-required-job-not-successful')
    steps = rows[0].get('steps', [])
    for name in mandatory_steps:
        matches = [step for step in steps if step.get('name') == name]
        require(len(matches) == 1 and matches[0].get('status') == 'completed' and
            matches[0].get('conclusion') == 'success', 'publication-required-step-not-executed')
    return dict(runId=run_id, jobId=job_id, workflow=workflow, sourceRevision=revision,
        runAttempt=run.get('run_attempt'), requiredJobAndStepsSucceeded=True)


def verify_artifact(api, selected, run_id, revision):
    row = api.json('/actions/artifacts/' + str(selected['id']))
    verify_artifact_record(row, selected, run_id, revision)
    return row


def verify_artifact_record(row, selected, run_id, revision):
    require(row.get('id') == selected['id'] and row.get('name') == selected['name'] and
        row.get('size_in_bytes') == selected['bytes'] and row.get('digest') == 'sha256:' + selected['sha256'] and
        row.get('expired') is False and row.get('workflow_run', {}).get('id') == run_id and
        row['workflow_run'].get('head_sha') == revision and row['workflow_run'].get('head_branch') == BRANCH,
        'publication-artifact-provenance')


def download(api, selected, run_id, path, revision):
    verify_artifact(api, selected, run_id, revision)
    api.download(github.API + '/actions/artifacts/' + str(selected['id']) + '/zip', path,
        {key: selected[key] for key in ('bytes', 'sha256')})


def safe_entries(archive, maximum_bytes):
    rows = {}
    total = 0
    for item in archive.infolist():
        path = PurePosixPath(item.filename)
        require(not path.is_absolute() and '\\' not in item.filename and
            not any(part in ('', '.', '..') for part in item.filename.rstrip('/').split('/')),
            'publication-artifact-member-path')
        require(item.filename not in rows and not item.flag_bits & 1 and
            stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR),
            'publication-artifact-member-type')
        require(0 <= item.file_size <= maximum_bytes, 'publication-artifact-member-bound')
        total += item.file_size
        require(total <= maximum_bytes and len(rows) < 256, 'publication-artifact-expanded-bound')
        rows[item.filename] = item
    return rows


def extract_package(path, output):
    expected = {'app-release-unsigned.apk', 'coherent-release-apk.json', 'release-manifest.json', 'unsigned-release-package.json'}
    require(not output.exists(), 'publication-extraction-output-exists')
    with zipfile.ZipFile(signing.plain(path)) as archive:
        rows = safe_entries(archive, MAX_ARTIFACT)
        selected = {PurePosixPath(name).name: item for name, item in rows.items() if not item.is_dir()}
        require(len(selected) == len([item for item in rows.values() if not item.is_dir()]) and
            set(selected) == expected, 'publication-package-artifact-roster')
        output.mkdir()
        for name, item in selected.items():
            require(name.endswith('.apk') or item.file_size <= 2 << 20, 'publication-package-metadata-bound')
            with archive.open(item) as source, (output / name).open('xb') as destination:
                shutil.copyfileobj(source, destination, 256 << 10)
    return output


def verify_unsigned(directory, selected, tools, application):
    apk = directory / 'app-release-unsigned.apk'
    package = read_json(directory / 'unsigned-release-package.json')
    cohort = read_json(directory / 'coherent-release-apk.json')
    manifest = read_json(directory / 'release-manifest.json')
    unsigned = identity(apk)
    require(type(package.get('formatVersion')) is int and package['formatVersion'] == 1 and package.get('scope') ==
        'unsigned-nondebug-local-game-profile-release-packaging-only' and package.get('integrationRevision') == selected['appRevision'] and
        package.get('apk') == unsigned and package.get('manifest') == manifest and
        all(package.get(name) is True for name in ('completeProviderAndSourceBytesVerified', 'unsignedSignatureStructureVerified',
            'debugReferenceArtifactRetainedSeparately', 'sourceAndPairedDebugCompanionsRetainedSeparately')) and
        all(package.get(name) is False for name in ('privateSigningPerformed', 'persistentSigningQualified',
            'releaseInstallationQualified', 'androidExecutionQualified', 'hardwareQualified', 'commonMainQualified',
            'gameLoginQualified', 'localWorldReadinessQualified', 'playerbotsAiQualified', 'gameplayQualified', 'deviceTestCandidate')),
        'publication-unsigned-package-proof')
    require(type(cohort.get('formatVersion')) is int and cohort['formatVersion'] == 1 and
        cohort.get('scope') == 'source-and-paired-debug-verified-local-game-profile-apk-bytes' and
        cohort.get('apk') == unsigned and cohort.get('serverProfile') == 'local-game' and
        cohort.get('completeAssetInventoryVerified') is True and cohort.get('exactCurrentHelperClosureVerified') is True and
        cohort.get('deviceTestCandidate') is False and cohort.get('selectedInputs', {}).get('sources.lock.json') == selected['sourceLock'],
        'publication-complete-cohort-proof')
    require(manifest == signing.manifest(apk, tools, application['versionCode'], signing.STOCK_PACKAGE) and manifest['debuggable'] is False and
        manifest['versionCode'] == application['versionCode'] and type(manifest['versionCode']) is int and
        manifest['versionName'] == application['versionName'], 'publication-stock-apk-manifest')
    with zipfile.ZipFile(apk) as archive:
        item = archive.getinfo('assets/sources.lock.json')
        require(item.file_size == selected['sourceLock']['bytes'] and item.file_size <= 2 << 20 and
            archive.read(item) == (ROOT / 'sources.lock.json').read_bytes(), 'publication-apk-exact-engine-pins')
        require(not any(re.fullmatch(r'META-INF/[^/]+\.(?:SF|RSA|DSA|EC)', name, re.I) for name in archive.namelist()),
            'publication-unsigned-apk-v1-signature')
    return unsigned


def verify_native_sql(path, revision):
    with zipfile.ZipFile(signing.plain(path)) as archive:
        rows = safe_entries(archive, 32 << 20)
        selected = {}
        for name, item in rows.items():
            if PurePosixPath(name).name in ('environment-receipt.json', 'native-installation-qualification.json'):
                require(not item.is_dir() and item.file_size <= 512 << 10 and PurePosixPath(name).name not in selected,
                    'publication-native-sql-metadata-bound')
                selected[PurePosixPath(name).name] = archive.read(item)
        require(set(selected) == {'environment-receipt.json', 'native-installation-qualification.json'},
            'publication-native-sql-required-receipts')
    environment = json.loads(selected['environment-receipt.json'], object_pairs_hook=unique)
    raw = selected['native-installation-qualification.json']
    value = json.loads(raw, object_pairs_hook=unique)
    require(type(environment.get('formatVersion')) is int and environment['formatVersion'] == 1 and
        environment.get('scope') == 'native-installation-finish-and-clean-stop-environment' and
        environment.get('integrationRevision') == revision and
        environment.get('files', {}).get('native-installation-qualification.json') ==
            dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) and
        environment.get('privateSqlLogsExported') is False, 'publication-native-sql-source-binding')
    require(type(value.get('formatVersion')) is int and value['formatVersion'] == 1 and
        value.get('scope') == 'disposable-native-arm64-owned-installation-finish-and-stop' and
        value.get('phase') == 'complete' and value.get('contentProfile') == 'stock-3.3.5a' and
        value.get('sqlSelectionPolicy') == STOCK_SQL_POLICY and
        all(value.get(name) is True for name in ('qualificationSucceeded', 'initializedNewInstance',
            'productionCoreCompositionCompleted', 'productionFinishPlayerbotsExecuted', 'nestedDataDirectoryConfigurationVerified',
            'completedFinishReentryWithoutExecution', 'restartPersistenceVerified', 'restartedFinishReentryWithoutExecution',
            'productionReadyAndStoppedAcknowledgmentsVerified', 'sourcePrivateJournalsAccountCredentialsPreserved',
            'nativeSqlSetupReceiptVerified', 'cleanShutdownVerified')) and
        all(value.get(name) is False for name in ('compilerExecuted', 'javaCoordinatorExecuted', 'authserverExecuted',
            'worldserverExecuted', 'serverDataQualified', 'playerbotsAiQualified', 'androidRuntimeQualified', 'gameplayQualified')),
        'publication-native-sql-not-qualified')
    stock = value.get('stockWorldSql', {})
    require(stock.get('contentProfile') == 'stock-3.3.5a' and stock.get('stockRaceClassMapOutfitSqlOverlaysEmpty') is True and
        stock.get('humanWarriorNorthshireStartVerified') is True and stock.get('actualFileDbcRowsLoaded') is False and
        stock.get('worldStartupExecuted') is False and stock.get('gameplayQualified') is False,
        'publication-native-stock-sql-closure')
    return dict(actualNativeSqlSetupAndRestartVerified=True, stockSqlPolicyAndHumanStartVerified=True,
        sourceRevision=revision, sqlSelectionPolicy=STOCK_SQL_POLICY, worldserverExecuted=False, gameplayQualified=False)


def verify_signing_receipt(receipt, selected, unsigned, lock):
    require(type(receipt) is dict and set(receipt) == {'formatVersion', 'scope', 'qualificationOnly',
        'persistentSigningIdentityVerified', 'inputApkSha256', 'publicSigningLockSha256', 'previousPublished',
        'signedApk', 'payloadPreserved', 'sdkBuildToolsVersion', 'actualInstallOverQualified', 'gameplayQualified',
        'deviceCandidateQualified'} and type(receipt['formatVersion']) is int and receipt['formatVersion'] == 1 and
        receipt['scope'] == 'apk-signature-and-update-identity' and receipt['qualificationOnly'] is False and
        receipt['persistentSigningIdentityVerified'] is True and receipt['payloadPreserved'] is True and
        receipt['actualInstallOverQualified'] is False and receipt['gameplayQualified'] is False and
        receipt['deviceCandidateQualified'] is False and receipt['sdkBuildToolsVersion'] == '35.0.0' and
        receipt['inputApkSha256'] == unsigned['sha256'] and
        receipt['publicSigningLockSha256'] == selected['stockSigningLock']['sha256'],
        'publication-original-signing-receipt')
    application_identity(receipt, lock)
    return receipt


def stage(api, output, tools):
    selected = selection()
    require(not output.exists() and not output.is_symlink(), 'publication-output-already-exists')
    package_run = verify_run(api, selected['packageRunId'], selected['packageJobId'], PACKAGE_WORKFLOW, 'package', (
        'Build and lint an unsigned release from the same complete provider profile',
        'Verify release provider bytes and nondebug unsigned APK identity without a key'), selected['appRevision'])
    equivalent = verify_sql_source_equivalence(api, selected['appRevision'], selected['nativeSqlRevision'])
    sql_run = verify_run(api, selected['nativeSqlRunId'], selected['nativeSqlJobId'], SQL_WORKFLOW, 'owned-installation', (
        'Run actual portable finish, nested DataDir, reentry, service restart and bound clean-stop receipt',), selected['nativeSqlRevision'])
    output.mkdir(parents=True)
    download(api, selected['packageArtifact'], selected['packageRunId'], output / 'unsigned-artifact.zip', selected['appRevision'])
    download(api, selected['nativeSqlArtifact'], selected['nativeSqlRunId'], output / 'native-sql-artifact.zip', selected['nativeSqlRevision'])
    native = verify_native_sql(output / 'native-sql-artifact.zip', selected['nativeSqlRevision'])
    directory = extract_package(output / 'unsigned-artifact.zip', output / 'unsigned')
    unsigned_apk = directory / 'app-release-unsigned.apk'
    lock = signing.load_lock(ROOT / 'app/stock-signing.lock.json')
    original_receipt = read_json(ROOT / RECEIPT)
    application = application_identity(original_receipt, lock)
    unsigned = verify_unsigned(directory, selected, tools, application)
    receipt = verify_signing_receipt(original_receipt, selected, unsigned, lock)
    # The generic reconstructor accepts no private material and admits only the
    # original prefix, an inserted signature block, unchanged CD and offset patch.
    try:
        from . import export_apk_signature as detached
    except ImportError:
        import export_apk_signature as detached
    signed_directory = output / 'signed'; signed_directory.mkdir()
    signed_apk = signed_directory / 'esteria-development.apk'
    detached.apply(unsigned_apk, ROOT / RECIPE, signed_apk)
    checked = signing.verify(signed_apk, tools, lock, application['versionCode'])
    require(checked == receipt['signedApk'] and signing.payload(unsigned_apk) == signing.payload(signed_apk),
        'publication-sdk-signature-or-payload-mismatch')
    shutil.copyfile(ROOT / RECEIPT, signed_directory / 'signing-receipt.json')
    result = release.stage(argparse.Namespace(signed=signed_directory,
        cohort_proof=directory / 'coherent-release-apk.json', app_revision=selected['appRevision'],
        run_id=str(selected['packageRunId']), output=output / 'release'))
    evidence = dict(formatVersion=1, scope=SCOPE, appRevision=selected['appRevision'],
        packageRun=package_run, nativeSqlRun=sql_run, nativeSql=native, nativeSqlSourceEquivalence=equivalent, selectedInputs=selected,
        publicSignatureReconstructed=True, sdkSignatureAndManifestVerified=True,
        completeApkPayloadPreserved=True, persistentCertificateSha256=checked['certificateSha256'],
        previousPublished=lock['lastPublished'], application=application,
        signedApk=dict(bytes=checked['apkBytes'], sha256=checked['apkSha256']),
        privateKeyPresentInWorkflow=False, androidExecutionQualified=False, thorQualified=False, gameplayQualified=False)
    (output / 'publication-evidence.json').write_text(json.dumps(evidence, sort_keys=True, indent=2) + '\n')
    return result


def publish(api, directory, result):
    tag = result['tag']
    app_revision = result['appRevision']
    require(type(app_revision) is str and re.fullmatch('[0-9a-f]{40}', app_revision), 'publication-exact-app-revision')
    require(re.fullmatch(r'non-custom-v[0-9A-Za-z._-]+', tag), 'publication-tag-format')
    require(api.json('/git/ref/tags/' + quote(tag, safe=''), missing=True) is None and
        api.json('/releases/tags/' + quote(tag, safe=''), missing=True) is None,
        'publication-existing-tag-or-release-preserved')
    body = (directory / 'release/RELEASE-NOTES.md').read_text()
    created = api.json('/releases', method='POST', value=dict(tag_name=tag, target_commitish=app_revision,
        name='Esteria Stock 3.3.5a / non-custom', body=body, draft=True, prerelease=True))
    require(type(created.get('id')) is int and created.get('draft') is True and created.get('prerelease') is True and
        created.get('tag_name') == tag, 'publication-draft-creation-failed')
    (directory / 'publication-draft.json').write_text(json.dumps(dict(formatVersion=1, releaseId=created['id'],
        tag=tag, appRevision=app_revision, draft=True, prerelease=True, published=False), sort_keys=True, indent=2) + '\n')
    paths = [directory / 'release/Esteria-Stock-3.3.5a-arm64.apk', directory / 'release/SHA256SUMS',
        directory / 'release/release.json', directory / 'signed/signing-receipt.json',
        directory / 'publication-evidence.json', ROOT / 'NON-CUSTOM-TESTING.md']
    assets = {}
    for path in paths:
        expected = identity(path)
        row = api.upload(created['id'], path.name, path, expected)
        require(row.get('state') == 'uploaded' and row.get('name') == path.name and
            row.get('size') == expected['bytes'] and row.get('digest') == 'sha256:' + expected['sha256'],
            'publication-asset-readback-identity')
        assets[path.name] = expected
    final = api.json('/releases/' + str(created['id']), method='PATCH', value=dict(draft=False))
    require(final.get('draft') is False and final.get('prerelease') is True and final.get('tag_name') == tag and
        final.get('html_url') == 'https://github.com/' + REPOSITORY + '/releases/tag/' + tag,
        'publication-final-prerelease-identity')
    reference = api.json('/git/ref/tags/' + quote(tag, safe=''))
    require(reference.get('object', {}).get('type') == 'commit' and reference['object'].get('sha') == app_revision,
        'publication-exact-app-tag-target')
    proof = dict(formatVersion=1, scope='additive-detached-stock-apk-prerelease',
        releaseId=created['id'], url=final['html_url'], tag=tag, appRevision=app_revision,
        publisherNeverOverwrites=True, assets=assets)
    (directory / 'published-release.json').write_text(json.dumps(proof, sort_keys=True, indent=2) + '\n')
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('schema', 'inspect', 'stage'), nargs='?', default='stage')
    parser.add_argument('--build-tools', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--package-artifact-metadata', type=Path)
    parser.add_argument('--native-sql-artifact-metadata', type=Path)
    parser.add_argument('--package-job-id', type=int)
    parser.add_argument('--native-sql-job-id', type=int)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'schema':
            print(json.dumps(schema(), sort_keys=True, indent=2))
            return
        if args.action == 'inspect':
            require(args.package_artifact_metadata and args.native_sql_artifact_metadata,
                'publication-inspection-artifact-metadata-required')
            result = inspect_metadata(args.package_artifact_metadata, args.native_sql_artifact_metadata,
                args.package_job_id, args.native_sql_job_id)
            if args.output:
                require(result['selectionComplete'] and not args.output.exists(), 'publication-complete-new-selection-required')
                with args.output.open('x') as stream:
                    stream.write(json.dumps(result['selection'], sort_keys=True, indent=2) + '\n')
            print(json.dumps(result, sort_keys=True, indent=2))
            return
        require(args.build_tools and args.output, 'publication-build-tools-and-output-required')
        require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and os.environ.get('GITHUB_REF') == 'refs/heads/non-custom',
            'publication-repository-branch-environment')
        api = github.Github(os.environ.get('GITHUB_TOKEN'))
        result = stage(api, args.output, signing.sdk_tools(args.build_tools))
        if args.publish:
            result = publish(api, args.output, result)
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        message = str(error) if type(error) is ValueError and re.fullmatch('[a-z0-9-]+', str(error)) else 'detached-publication-validation-failed'
        parser.exit(1, message + '\n')


if __name__ == '__main__':
    main()
