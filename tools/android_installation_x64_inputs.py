#!/usr/bin/env python3
"""Read-only admission of measured native x64 SQL and Android fixture inputs.

The committed selection is disabled. No function here downloads, builds, creates
output, initializes SQL or grants Android execution qualification. The future APK
descriptor has an independent exact byte pin; it must not embed this selection's
hash, which would make the provider/selection identities recursive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import server_setup_x64_sql_inputs as native
from tools import qualify_server_setup_x64_sql as sql
from tools import fetch_android_mysql_fixture_frozen as frozen_mysql

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/mysql-probe/android-installation-x64-inputs.lock.json'
NATIVE_SELECTION = 'runtime/mysql-probe/server-setup-x64-sql-inputs.lock.json'
CONTENT_SELECTION = 'runtime/server/content-provider.lock.json'
SCOPE = 'android-x64-installation-coordinator-input-selection'
PENDING = 'pending-native-x64-sql-and-provider-measurement'
MEASURED = 'native-x64-sql-and-provider-measured'
FALSE_FLAGS = ('sqlExecuted', 'androidRuntimeQualified', 'productionArm64ProviderQualified',
    'fourSchemaCoordinatorQualified', 'worldserverQualified', 'playerbotsAiQualified', 'gameplayQualified',
    'slotPromoted', 'serverDataQualified')
POSITIVE_SQL_FLAGS = ('qualificationSucceeded', 'selectedX64ToolsSqlQualified', 'sqlExecuted',
    'initializedNewInstance', 'actualCoreCompositionCompleted', 'completedJournalReentryWithoutExecution',
    'actualLoaderReentryVerified', 'restartPersistenceVerified', 'fixtureProbeRemoved',
    'exactSourceUpdateLedgerVerified', 'finalFourSchemaProductVerification',
    'coreSchemasLedgersCredentialsAccountPreserved', 'cleanShutdownVerified',
    'capturedLoaderAndLibraryCompatibilityQualified')
require = native.require


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'android-installation-x64-duplicate-field')
        result[key] = value
    return result


def small(path, maximum=2 << 20):
    return json.loads(_raw(path, maximum), object_pairs_hook=_unique)


def _raw(path, maximum):
    with native.files.plain_file(path) as stream:
        before = os.fstat(stream.fileno())
        require(0 < before.st_size <= maximum, 'android-installation-x64-metadata-bound')
        raw = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    stamp = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    require(len(raw) == before.st_size and stamp(before) == stamp(after) == stamp(Path(path).lstat()),
        'android-installation-x64-metadata-changed')
    return raw


def identity(row, maximum=2 << 20):
    require(type(row) is dict and set(row) == {'bytes', 'sha256'} and type(row['bytes']) is int and
        0 < row['bytes'] <= maximum and type(row['sha256']) is str and
        re.fullmatch('[a-f0-9]{64}', row['sha256']), 'android-installation-x64-exact-identity-required')
    return dict(row)


def record(row, expected_path=None):
    require(type(row) is dict and set(row) == {'path', 'bytes', 'sha256'},
        'android-installation-x64-record-schema')
    name = row['path']
    require(type(name) is str and name.startswith('runtime/') and name.endswith('.json') and
        '\\' not in name and all(part not in ('', '.', '..') for part in name.split('/')) and
        (expected_path is None or name == expected_path), 'android-installation-x64-record-path')
    wanted = identity({key: row[key] for key in ('bytes', 'sha256')})
    raw = _raw(ROOT / name, 2 << 20)
    require(dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) == wanted,
        'android-installation-x64-record-changed')
    return json.loads(raw, object_pairs_hook=_unique)


def _context(pin):
    """Underlying measured admission remains authoritative and unchanged."""
    require(pin.get('enabled') is True, 'android-installation-x64-native-selection-not-enabled')
    observed = native.record(pin['build']['actualEvidence'])
    build = native.validate_build(observed.get('actualBuildReceipt'), pin)
    native.validate_source_readback(observed.get('actualLibrarySourceReadback'), pin)
    mysql_pin = frozen_mysql.input_selection()
    mysql_readback = native.record(pin['mysql']['fullReadbackEvidence'])
    mysql_proof = mysql_readback['actualCiEvidence']['providerVerification']
    release = native.record(pin['serverContent']['releaseSelection'])
    content = record(dict(path=CONTENT_SELECTION, **release['selectedInputs'][CONTENT_SELECTION]), CONTENT_SELECTION)
    return build, mysql_pin, mysql_proof, content


def validate_native_sql(report, pin):
    """Require new native SQL evidence for the exact original ELF/source set.

    Invocation scripts retain distinct identities from their actual compiled
    ELFs. This admission neither reuses an ARM64 native receipt nor claims that
    Android executed those scripts, libraries or SQL.
    """
    build, mysql_pin, mysql_proof, content = _context(pin)
    require(type(report) is dict and type(report.get('formatVersion')) is int and report['formatVersion'] == 1 and
        report.get('scope') == sql.SCOPE and report.get('phase') == 'complete' and
        all(report.get(name) is True for name in POSITIVE_SQL_FLAGS) and
        all(report.get(name) is False for name in sql.FALSE_FLAGS) and
        not any(name.startswith(('failure', 'cleanupFailure')) for name in report),
        'android-installation-x64-positive-native-sql-required')
    for name in ('authserverExecuted', 'worldserverExecuted', 'botCharactersCreated', 'characterPersistenceQualified'):
        require(name not in report or report[name] is False, 'android-installation-x64-unexpected-native-runtime-claim')
    require(report.get('inputSelection') == native.files.identity(native.LOCK) and
        report.get('buildProducer') == pin['build']['producer'] and
        report.get('actualX64BuildReceipt') == pin['build']['buildReceipt'] and
        report.get('actualX64LibrarySourceReadback') == pin['build']['librarySourceReadback'],
        'android-installation-x64-native-build-source-selection-differs')
    require(report.get('originalMysqlArchive') == mysql_pin['files']['provider/assets/mysql-probe/mysql-x86-64.archive'] and
        report.get('mysqlVersion') == mysql_proof['expectedMysqlSqlVersion'] and
        report.get('contentReceipt') == content['receipt'] and report.get('compiledModules') == content['compiledModules'] and
        report.get('contentOriginBuild') == content['originalBuild'] and report.get('source') == content['serverSource'] and
        report.get('sourceLockSha256') == content['serverBuildSourceLock']['sha256'] and
        report.get('contentOriginIsOriginalArm64Packaging') is True and
        report.get('originalArm64ReceiptReusedForX64Qualification') is False,
        'android-installation-x64-mysql-or-original-content-differs')
    for name, expected in (('selectedSourceBaseFiles', 29), ('selectedSourceUpdates', 31), ('preparedStatementCount', 52)):
        require(type(report.get(name)) is int and report[name] == expected,
            'android-installation-x64-original-sql-plan-differs')
    uuid = report.get('mysqlUuid')
    require(type(uuid) is str and re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', uuid),
        'android-installation-x64-native-instance-required')
    libraries = build.get('libraries')
    require(type(libraries) is dict and {'lib64/ld-linux-x86-64.so.2', 'usr/lib/x86_64-linux-gnu/libc.so.6'} <= set(libraries) and
        all(type(row.get('elf', {}).get('machine')) is int and row['elf']['machine'] == 62 for row in libraries.values()),
        'android-installation-x64-captured-elf62-loader-closure-required')
    for row in libraries.values(): native.identity(row, 512 << 20)
    loader = {key: libraries['lib64/ld-linux-x86-64.so.2'][key] for key in ('bytes', 'sha256')}
    invocations = report.get('checkedInvocations')
    require(type(invocations) is dict and set(invocations) == {'dbimport', 'playerbots-schema'},
        'android-installation-x64-original-invocations-required')
    for name, row in invocations.items():
        executable = build['executables'][name]
        require(type(row) is dict and set(row) == {'path', 'invocation', 'actualExecutable', 'loader',
            'invocationIsOriginalElf', 'originalElfBytesChanged'} and
            type(executable.get('elf', {}).get('machine')) is int and executable['elf']['machine'] == 62 and
            row.get('actualExecutable') == {key: executable[key] for key in ('bytes', 'sha256')} and row.get('loader') == loader and
            row.get('invocationIsOriginalElf') is False and row.get('originalElfBytesChanged') is False,
            'android-installation-x64-invocation-not-original-elf62')
        identity(row['invocation'])
        require(type(row['path']) is str and len(row['path']) <= 4096 and row['path'].startswith('/') and
            Path(row['path']).name == name and str(Path(row['path'])) == row['path'] and
            all(part not in ('.', '..') for part in Path(row['path']).parts),
            'android-installation-x64-native-invocation-path')
        for field in ('original', 'pairedDebug'): native.identity(executable.get(field), 2 << 30)
    first = report.get('playerbotsFirst', {})
    require(type(first) is dict and first.get('scope') == sql.playerbots.SCOPE and first.get('mysqlUuid') == uuid and
        first.get('mysqlVersion') == report['mysqlVersion'] and first.get('helperBuildReceipt') == pin['build']['buildReceipt'] and
        first.get('helperExecutable') == invocations['playerbots-schema']['invocation'] and
        first.get('originalBuild') == content['originalBuild'] and first.get('compiledModules') == content['compiledModules'] and
        first.get('sourceLockSha256') == content['serverBuildSourceLock']['sha256'] and first.get('contentReceipt') == content['receipt'] and
        type(first.get('preparedStatementCount')) is int and first['preparedStatementCount'] == 52 and
        all(first.get(name) is True for name in ('compiledPlayerbotsLoaderExecuted', 'playerbotsSchemaInitialized',
            'exactSourceLedgerVerified', 'coreSchemasLedgersCredentialsAccountPreserved')) and
        type(report.get('databaseSnapshot')) is dict and report['databaseSnapshot'] == first.get('databaseSnapshot'),
        'android-installation-x64-original-helper-sql-binding-differs')
    reentry = report.get('actualLoaderReentry', {})
    require(type(reentry) is dict and type(reentry.get('exitCode')) is int and reentry['exitCode'] == 0 and
        type(reentry.get('preparedStatementCount')) is int and reentry['preparedStatementCount'] == 52,
        'android-installation-x64-actual-loader-reentry-required')
    return report


def _readback(value, selected, qualification):
    producer = selected['producer']
    workflow = value.get('workflow', {}) if type(value) is dict else {}
    require(type(value) is dict and type(workflow) is dict and type(value.get('formatVersion')) is int and value['formatVersion'] == 1 and
        value.get('scope') == 'independent-native-x64-four-schema-sql-readback' and
        type(workflow.get('id')) is int and workflow['id'] == producer['workflowRun'] and
        type(workflow.get('job')) is int and workflow['job'] == producer['job'] and
        workflow.get('headSha') == producer['integrationRevision'] and workflow.get('status') == 'completed' and
        workflow.get('conclusion') == 'success' and value.get('artifactMetadataOnly') == selected['evidenceArtifact'] and
        value.get('qualificationIdentity') == {key: selected['qualification'][key] for key in ('bytes', 'sha256')} and
        value.get('inputSelection') == {key: selected['inputSelection'][key] for key in ('bytes', 'sha256')} and
        value.get('actualQualification') == qualification and
        all(value.get(name) is True for name in ('allArtifactZipBytesReadBack', 'everyArtifactMemberCrcAndSha256Verified',
            'qualificationSourceInputsMatchExactGitBlobs')) and
        all(value.get(name) is False for name in ('androidRuntimeQualified', 'productionArm64ProviderQualified',
            'worldserverQualified', 'playerbotsAiQualified', 'gameplayQualified')),
        'android-installation-x64-independent-native-readback-required')


def load_pin(*, require_enabled=False):
    pin = small(LOCK, 128 << 10)
    require(type(pin) is dict and set(pin) == {'formatVersion', 'scope', 'repository', 'enabled', 'state',
        'nativeSql', 'provider', *FALSE_FLAGS} and type(pin['formatVersion']) is int and pin['formatVersion'] == 1 and
        pin['scope'] == SCOPE and pin['repository'] == 'Russianranger/esteria_android' and type(pin['enabled']) is bool and
        all(pin[name] is False for name in FALSE_FLAGS), 'android-installation-x64-selection-schema')
    if not pin['enabled']:
        require(pin['state'] == PENDING and pin['nativeSql'] is None and pin['provider'] is None,
            'android-installation-x64-pending-measurements-required')
        require(not require_enabled, 'android-installation-x64-measured-native-sql-and-provider-required')
        return pin
    require(pin['state'] == MEASURED, 'android-installation-x64-measured-state-required')
    identity(pin['provider'], 128 << 10)
    selected = pin['nativeSql']
    require(type(selected) is dict and set(selected) == {'inputSelection', 'producer', 'evidenceArtifact',
        'qualification', 'readback'}, 'android-installation-x64-native-selection-schema')
    record(selected['inputSelection'], NATIVE_SELECTION)
    producer = selected['producer']
    require(type(producer) is dict and set(producer) == {'workflowRun', 'job', 'integrationRevision'} and
        all(type(producer.get(name)) is int and producer[name] > 0 for name in ('workflowRun', 'job')) and
        type(producer.get('integrationRevision')) is str and re.fullmatch('[a-f0-9]{40}', producer['integrationRevision']),
        'android-installation-x64-exact-native-producer-required')
    artifact = selected['evidenceArtifact']
    require(type(artifact) is dict and set(artifact) == {'id', 'bytes', 'sha256'} and
        type(artifact['id']) is int and artifact['id'] > 0, 'android-installation-x64-exact-native-artifact-required')
    identity({key: artifact[key] for key in ('bytes', 'sha256')}, 16 << 20)
    native_pin = native.load_pin(require_enabled=True)
    qualification = record(selected['qualification'])
    validate_native_sql(qualification, native_pin)
    _readback(record(selected['readback']), selected, qualification)
    return pin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-enabled', action='store_true')
    arguments = parser.parse_args()
    pin = load_pin(require_enabled=arguments.require_enabled)
    print(json.dumps(dict(formatVersion=1, scope='android-x64-installation-selection-check-only',
        enabled=pin['enabled'], state=pin['state'], provider=pin['provider'],
        inputSelection=native.files.identity(LOCK), **{name: False for name in FALSE_FLAGS}), sort_keys=True))


if __name__ == '__main__': main()
