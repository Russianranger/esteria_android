#!/usr/bin/env python3
"""Stage an optional measured PB helper delta, never an enabled Android provider.

Only separately pinned actual build and native SQL receipts can create a
candidate. Original three-program identities remain distinct and unchanged.
Complete source sealing, provider integration and phone promotion are later gates.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import provider_server_programs as programs, server_provider_sources as sources
from tools import manifest_server_modules as modules, verify_server_build as files
from runtime import mysql_bootstrap as db
from tools import package_server_content as transaction, prepare_runtime as archives

ROOT = Path(__file__).resolve().parents[1]
CONTENT_PIN = ROOT / 'runtime/server/content-provider.lock.json'
SCOPE = 'measured-playerbots-helper-provider-candidate'
HELPER = 'helpers/playerbots-schema'
BUILD = 'provenance/playerbots-helper-build.json'
NATIVE = 'provenance/playerbots-native-sql.json'
MAX_FILES, MAX_BYTES, MAX_MEMBER = 256, 256 << 20, 128 << 20
SQL_TRUE = ('initializedNewInstance', 'productionCoreCompositionCompleted',
    'playerbotsDatabaseAndStatementsQualified', 'exactSourceUpdateLedgerVerified',
    'completedJournalReentryWithoutExecution', 'actualLoaderReentryVerified',
    'restartPersistenceVerified', 'fixtureProbeRemoved', 'finalFourSchemaProductVerification',
    'coreSchemasLedgersCredentialsAccountPreserved', 'cleanShutdownVerified')
FALSE = ('playerbotsAiQualified', 'botCharactersCreated', 'authserverExecuted', 'worldserverExecuted',
    'completeSetupQualified', 'slotPromoted', 'existingStateModified', 'schemaUpgradeQualified',
    'androidRuntimeQualified', 'gameplayQualified')
require = files.require


def identity(value):
    require(type(value) is dict and type(value.get('bytes')) is int and 0 < value['bytes'] <= MAX_BYTES and
            isinstance(value.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', value['sha256']),
            'playerbots-candidate-invalid-identity')
    return {name: value[name] for name in ('bytes', 'sha256')}


def read_pinned(path, expected_sha256, maximum):
    require(isinstance(expected_sha256, str) and re.fullmatch('[0-9a-f]{64}', expected_sha256),
            'playerbots-candidate-explicit-receipt-digest-required')
    document, pin = modules.read_json(path, limit=maximum)
    require(pin['sha256'] == expected_sha256, 'playerbots-candidate-receipt-digest-differs')
    return document, pin


def selection():
    pin = programs.load_pin()  # Auditing a pending source seal cannot enable it.
    content, _ = programs.read_json(CONTENT_PIN, 128 << 10)
    sources.validate_current(content, ROOT / 'sources.lock.json')
    require(content['originalBuild'] == pin['originalBuild'] and content['compiledModules'] == pin['originalModules'] and
            content['serverBuildSourceLock'] == pin['serverBuildSourceLock'] and
            sources.same(content['serverSource'], pin['serverSource']), 'playerbots-candidate-content-selection-differs')
    return pin, content


def validate_build(payload, build, build_identity, pin):
    require(type(build.get('formatVersion')) is int and build['formatVersion'] == 1 and
            build.get('scope') == 'source-built-playerbots-schema-helper' and build.get('phase') == 'built-component' and
            build.get('buildTarget') == 'esteria_playerbots_database_reference' and
            build.get('actualCompileSucceeded') is True and build.get('actualDatabaseSourcesAndDefinitionVerified') is True and
            build.get('compilerCacheDisabled') is True and build.get('databaseExecuted') is False and
            build.get('sqlExecuted') is False and build.get('fullServerCompileSucceeded') is False and
            build.get('originalServerProgramsReplaced') is False and build.get('sourceCompanionComplete') is False and
            all(build.get(name) is False for name in ('playerbotsAiQualified', 'worldserverQualified', 'androidRuntimeQualified', 'gameplayQualified')) and
            type(build.get('preparedStatementCountDeclared')) is int and build['preparedStatementCountDeclared'] == 52 and
            build.get('originalBuild') == pin['originalBuild'] and build.get('originalModules') == pin['originalModules'] and
            build.get('sourceLock') == pin['serverBuildSourceLock'] and sources.same(build.get('serverSource'), pin['serverSource']),
            'playerbots-candidate-actual-build-source-binding-required')
    require(build.get('compilerLaunchers') == dict(CMAKE_C_COMPILER_LAUNCHER='', CMAKE_CXX_COMPILER_LAUNCHER=''),
            'playerbots-candidate-real-empty-launcher-proof-required')
    inventory = build.get('payloadFiles')
    require(type(inventory) is dict and 1 <= len(inventory) < MAX_FILES and
            sum(identity(row)['bytes'] for row in inventory.values()) <= MAX_BYTES,
            'playerbots-candidate-source-payload-bound')
    names = {path.relative_to(payload).as_posix() for path in files.installed_files(payload)}
    require(names == set(inventory) | {'helper-build.json'}, 'playerbots-candidate-exact-source-payload-required')
    for name, row in inventory.items():
        archives.require(len(name.encode()) <= 512, 'playerbots-candidate-path-byte-bound')
        transaction.content.safe_path(name)
        require(identity(row)['bytes'] <= MAX_MEMBER and files.identity(payload / name) == identity(row),
                'playerbots-candidate-source-payload-changed')
    required = {'bin/playerbots-schema', 'source-inputs/server-engine-source-inputs.tar.gz',
        'source-inputs/source-inputs-receipt.json', 'source-inputs/original-sources.lock.json',
        'provenance/original-build.json', 'provenance/original-modules.json',
        'build/compile_commands.json', 'build/CMakeCache.txt', 'build/commands.json'}
    require(required <= inventory.keys() and inventory['bin/playerbots-schema'] == build['executable'] and
            inventory['provenance/original-build.json'] == pin['originalBuild'] and
            inventory['provenance/original-modules.json'] == pin['originalModules'] and
            inventory['source-inputs/original-sources.lock.json'] == pin['serverBuildSourceLock'] and
            inventory['source-inputs/server-engine-source-inputs.tar.gz'] == identity(build['sourceInputArchive']) ==
                identity(pin['originalSourceInputs']['archive']) and
            inventory['source-inputs/source-inputs-receipt.json'] == identity(build['sourceInputReceipt']) ==
                identity(pin['originalSourceInputs']['receipt']) and
            files.identity(payload / 'helper-build.json') == build_identity,
            'playerbots-candidate-original-and-new-payload-identities-differ')
    sources.validate_archived((payload / 'source-inputs/original-sources.lock.json').read_bytes(), pin)
    observed = files.elf_header(payload / 'bin/playerbots-schema', executable=True)
    require(all(build.get('elf', {}).get(name) == value for name, value in observed.items()),
            'playerbots-candidate-actual-elf-differs')
    return inventory


def validate_native(native, build, build_identity, pin, content):
    require(type(native.get('formatVersion')) is int and native['formatVersion'] == 1 and
            native.get('scope') == 'disposable-native-arm64-product-playerbots-schema' and
            native.get('phase') == 'complete' and native.get('qualificationSucceeded') is True and
            all(native.get(name) is True for name in SQL_TRUE) and all(native.get(name) is False for name in FALSE) and
            not any(name.startswith(('failure', 'cleanupFailure')) for name in native) and
            native.get('originalBuild') == pin['originalBuild'] and native.get('compiledModules') == pin['originalModules'] and
            native.get('sourceLockSha256') == pin['serverBuildSourceLock']['sha256'] and
            sources.same(native.get('source'), pin['serverSource']) and native.get('contentReceipt') == content['receipt'] and
            native.get('helperBuildReceipt') == build_identity and native.get('helperExecutable') == build['executable'] and
            type(native.get('preparedStatementCount')) is int and native['preparedStatementCount'] == 52 and
            type(native.get('selectedSourceBaseFiles')) is int and native['selectedSourceBaseFiles'] == 29 and
            type(native.get('selectedSourceUpdates')) is int and native['selectedSourceUpdates'] == 31,
            'playerbots-candidate-actual-native-schema-proof-required')
    uuid = native.get('mysqlUuid')
    require(isinstance(uuid, str) and re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', uuid),
            'playerbots-candidate-native-instance-required')
    derivative = native.get('engineDerivative', {})
    require(derivative.get('scope') == 'verified-engine-derivative-program-selection' and
            derivative.get('originalReceiptsUnchanged') is True and derivative.get('originalBuild') == pin['originalBuild'] and
            derivative.get('originalModules') == pin['originalModules'] and
            derivative.get('packageReceipt') == identity(pin['originalPackageReceipt']) and
            derivative.get('runtimeArchive') == pin['originalRuntimeArchive'] and
            derivative.get('programs') == {name: row['stripped'] for name, row in pin['programPairs'].items()},
            'playerbots-candidate-original-three-programs-changed')
    first, repeat = native.get('playerbotsFirst', {}), native.get('playerbotsCompletedReentry', {})
    records = [first, repeat]
    db.exact_version(native.get('mysqlVersion', ''))
    for phase in ('productBeforeNativeProbe', 'productAfterRestart'):
        stage = native.get(phase, {})
        require(stage.get('updater', {}).get('compiledUpdaterCompleted') is True and
                stage.get('updater', {}).get('compiledUpdaterExecuted') is False and
                stage.get('updater', {}).get('sourceLedgersVerified') is True and
                stage.get('updater', {}).get('playerbots') == stage.get('playerbots') and
                all(stage.get(name, {}).get('completedUpdaterVerified') is True and stage[name].get('mysqlUuid') == uuid
                    for name in ('realm', 'account')), 'playerbots-candidate-final-product-proof-required')
        records.append(stage.get('playerbots', {}))
    for index, row in enumerate(records):
        require(row.get('scope') == 'owned-packaged-content-playerbots-schema-only' and row.get('mysqlUuid') == uuid and
                row.get('mysqlVersion') == native['mysqlVersion'] and row.get('originalBuild') == pin['originalBuild'] and
                row.get('compiledModules') == pin['originalModules'] and row.get('contentReceipt') == content['receipt'] and
                row.get('sourceLockSha256') == pin['serverBuildSourceLock']['sha256'] and
                type(row.get('preparedStatementCount')) is int and row['preparedStatementCount'] == 52 and
                isinstance(row.get('playerbotsPlanSha256'), str) and re.fullmatch('[0-9a-f]{64}', row['playerbotsPlanSha256']) and
                row['playerbotsPlanSha256'] == first.get('playerbotsPlanSha256') and
                row.get('helperBuildReceipt') == build_identity and row.get('helperExecutable') == build['executable'] and
                row.get('playerbotsSchemaInitialized') is True and row.get('exactSourceLedgerVerified') is True and
                row.get('coreSchemasLedgersCredentialsAccountPreserved') is True and
                row.get('compiledPlayerbotsLoaderExecuted') is (index == 0) and
                row.get('databaseSnapshot') == native.get('databaseSnapshot') and
                all(row.get(name) is False for name in ('playerbotsAiQualified', 'botCharactersCreated',
                    'worldserverExecuted', 'schemaUpgradeQualified', 'androidRuntimeQualified', 'gameplayQualified')),
                'playerbots-candidate-same-instance-completed-proof-required')
    require(type(native.get('actualLoaderReentry', {}).get('exitCode')) is int and
            native['actualLoaderReentry']['exitCode'] == 0 and
            type(native['actualLoaderReentry'].get('preparedStatementCount')) is int and
            native['actualLoaderReentry']['preparedStatementCount'] == 52,
            'playerbots-candidate-real-loader-reentry-required')


def copy_file(source, target, expected, mode=0o444):
    require(files.identity(source) == identity(expected), 'playerbots-candidate-input-changed-before-copy')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with files.plain_file(source) as incoming, target.open('xb') as outgoing:
        require(archives.hash_stream(incoming, expected['bytes'], outgoing) == expected['sha256'],
                'playerbots-candidate-copy-differs')
        outgoing.flush(); os.fsync(outgoing.fileno())
    target.chmod(mode)


def build(payload, build_receipt_sha256, native_receipt, native_receipt_sha256, output):
    payload = archives.directory(Path(os.path.abspath(payload)))
    native_receipt = Path(os.path.abspath(native_receipt)); output = Path(os.path.abspath(output))
    archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and payload != output and payload not in output.parents and output not in payload.parents,
            'playerbots-candidate-existing-or-overlapping-output-preserved')
    pin, content = selection()
    compiled, compiled_identity = read_pinned(payload / 'helper-build.json', build_receipt_sha256, 2 << 20)
    native, native_identity = read_pinned(native_receipt, native_receipt_sha256, 4 << 20)
    inventory = validate_build(payload, compiled, compiled_identity, pin)
    validate_native(native, compiled, compiled_identity, pin, content)
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        runtime = {HELPER: (payload / 'bin/playerbots-schema', compiled['executable'], 0o555),
            BUILD: (payload / 'helper-build.json', compiled_identity, 0o444),
            NATIVE: (native_receipt, native_identity, 0o444)}
        for name, (source, expected, mode) in runtime.items(): copy_file(source, stage / 'runtime' / name, expected, mode)
        retained = dict(inventory, **{'helper-build.json': compiled_identity})
        for name, expected in retained.items():
            copy_file(payload / name, stage / 'companion/build-payload' / name, expected,
                      0o555 if name == 'bin/playerbots-schema' else 0o444)
        copy_file(native_receipt, stage / 'companion/native-sql-qualification.json', native_identity)
        proof = dict(formatVersion=1, scope=SCOPE, state='candidate-only-pending-provider-integration',
            helper=dict(name='playerbots-schema', guestPath='/esteria-server-programs/' + HELPER,
                executable=compiled['executable'], buildReceipt=compiled_identity, nativeSqlReceipt=native_identity),
            sourceLock=pin['serverBuildSourceLock'], serverSource=copy.deepcopy(pin['serverSource']),
            appSourceLock=pin['appSourceLock'], originalBuild=pin['originalBuild'], originalModules=pin['originalModules'],
            originalProgramsArchive=pin['archive'], originalProgramPairs=copy.deepcopy(pin['programPairs']),
            requiredServerRuntimeArchive=pin['requiredServerRuntimeArchive'], contentReceipt=content['receipt'],
            runtimeFiles={name: dict(identity(expected), mode=mode, **({'elfMachine': 183} if name == HELPER else {}))
                for name, (_, expected, mode) in runtime.items()},
            companionFiles={path.relative_to(stage / 'companion').as_posix(): dict(files.identity(path), mode=path.stat().st_mode & 0o777)
                for path in files.installed_files(stage / 'companion')},
            helperBuildAndNativeSchemaProofVerified=True, originalThreeProgramsUnchanged=True,
            helperOrServerExecutedHere=False, sourceCompanionComplete=False, androidProviderCreated=False,
            productionActivated=False, completeSetupQualified=False, slotPromoted=False,
            playerbotsAiQualified=False, worldserverQualified=False, androidRuntimeQualified=False, gameplayQualified=False)
        with (stage / 'candidate-pin.json').open('xb') as stream:
            stream.write(programs.encoded(proof)); stream.flush(); os.fsync(stream.fileno())
        verify(stage, files.identity(stage / 'candidate-pin.json')['sha256'])
        for directory, _, _ in os.walk(stage, topdown=False): archives.sync_directory(Path(directory))
        transaction.publish_directory(stage, output); archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists(): shutil.rmtree(stage)


def verify(candidate, expected_sha256):
    """Reverify an externally pinned, complete candidate; enable nothing."""
    candidate = archives.directory(Path(os.path.abspath(candidate)))
    proof, _ = read_pinned(candidate / 'candidate-pin.json', expected_sha256, 2 << 20)
    require(type(proof.get('formatVersion')) is int and proof['formatVersion'] == 1 and proof.get('scope') == SCOPE and
            proof.get('state') == 'candidate-only-pending-provider-integration' and
            proof.get('helperBuildAndNativeSchemaProofVerified') is True and proof.get('originalThreeProgramsUnchanged') is True and
            all(proof.get(key) is False for key in ('helperOrServerExecutedHere', 'sourceCompanionComplete',
                'androidProviderCreated', 'productionActivated', 'completeSetupQualified', 'slotPromoted',
                'playerbotsAiQualified', 'worldserverQualified', 'androidRuntimeQualified', 'gameplayQualified')),
            'playerbots-candidate-scope-or-activation-differs')
    pin, content = selection()
    require(proof.get('originalBuild') == pin['originalBuild'] and proof.get('originalModules') == pin['originalModules'] and
            proof.get('originalProgramsArchive') == pin['archive'] and proof.get('originalProgramPairs') == pin['programPairs'] and
            proof.get('sourceLock') == pin['serverBuildSourceLock'] and proof.get('appSourceLock') == pin['appSourceLock'] and
            sources.same(proof.get('serverSource'), pin['serverSource']) and proof.get('contentReceipt') == content['receipt'] and
            proof.get('requiredServerRuntimeArchive') == pin['requiredServerRuntimeArchive'],
            'playerbots-candidate-original-provider-selection-differs')
    helper = proof.get('helper', {})
    require(helper.get('name') == 'playerbots-schema' and helper.get('guestPath') == '/esteria-server-programs/' + HELPER,
            'playerbots-candidate-fixed-helper-path-required')
    payload = candidate / 'companion/build-payload'
    compiled, compiled_identity = read_pinned(payload / 'helper-build.json', identity(helper['buildReceipt'])['sha256'], 2 << 20)
    native_path = candidate / 'companion/native-sql-qualification.json'
    native, native_identity = read_pinned(native_path, identity(helper['nativeSqlReceipt'])['sha256'], 4 << 20)
    validate_build(payload, compiled, compiled_identity, pin); validate_native(native, compiled, compiled_identity, pin, content)
    expected_runtime = {HELPER: dict(identity(compiled['executable']), mode=0o555, elfMachine=183),
        BUILD: dict(compiled_identity, mode=0o444), NATIVE: dict(native_identity, mode=0o444)}
    require(proof.get('runtimeFiles') == expected_runtime and helper.get('executable') == compiled['executable'],
            'playerbots-candidate-runtime-selection-differs')
    companion = proof.get('companionFiles')
    require(type(companion) is dict and 0 < len(companion) <= MAX_FILES and
            set(companion) == {'build-payload/' + name for name in compiled['payloadFiles']} |
                {'build-payload/helper-build.json', 'native-sql-qualification.json'},
            'playerbots-candidate-companion-selection-differs')
    expected = {'runtime/' + name: row for name, row in expected_runtime.items()}
    for name, row in companion.items():
        transaction.content.safe_path(name); identity(row)
        require(row.get('mode') == (0o555 if name == 'build-payload/bin/playerbots-schema' else 0o444),
                'playerbots-candidate-companion-mode-differs')
        expected['companion/' + name] = row
    require({path.relative_to(candidate).as_posix() for path in files.installed_files(candidate)} == set(expected) | {'candidate-pin.json'},
            'playerbots-candidate-member-set-differs')
    for name, row in expected.items():
        path = candidate / name
        require(files.identity(path) == identity(row) and path.stat().st_mode & 0o777 == row['mode'],
                'playerbots-candidate-runtime-or-companion-changed')
    files.elf_header(candidate / 'runtime' / HELPER, executable=True)
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    make = sub.add_parser('build')
    for name in ('payload', 'native-receipt', 'output'): make.add_argument('--' + name, type=Path, required=True)
    for name in ('build-receipt-sha256', 'native-receipt-sha256'): make.add_argument('--' + name, required=True)
    check = sub.add_parser('verify'); check.add_argument('--candidate', type=Path, required=True)
    check.add_argument('--candidate-pin-sha256', required=True)
    args = parser.parse_args()
    result = (build(args.payload, args.build_receipt_sha256, args.native_receipt, args.native_receipt_sha256, args.output)
              if args.operation == 'build' else verify(args.candidate, args.candidate_pin_sha256))
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__': main()
