#!/usr/bin/env python3
"""Build only the real playerbots DatabaseLoader reference from retained sources.

Full CMake configuration retains the original module definitions, but the only
requested build target is the database reference. No SQL or helper is executed.
Original server program/module receipts remain unchanged and separately named.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import manifest_server_modules as modules, prepare_runtime as archives
from tools import prepare_server_isolated_build as inputs, qualify_server_isolated_build as isolated
from tools import server_provider_sources as sources, verify_playerbots_reference as reference
from tools import verify_server_build as files

ROOT = Path(__file__).resolve().parents[1]
TARGET = 'esteria_playerbots_database_reference'
PROVIDER = ROOT / 'runtime/server/programs-provider.lock.json'
ORIGINAL_BUILD = dict(bytes=32521, sha256='cdfd2ea0361f7dbb54b6f820a4cb295eb6b87fdcda32fe5cf4206ac3fe919d31')
ORIGINAL_MODULES = dict(bytes=5348, sha256='6459b6a1acab2c62c474e4c6ab3eb651daa21f697ccd628e93a38bad298bbdd1')
REFERENCE_INPUTS = {
    'tests/playerbots_database_reference.cpp': dict(bytes=2552, sha256='75c54da4fcae709d23723a0c8dfa7c0affc7d97ecf310a47f293e0071dae7da0'),
    'tests/playerbots_database_reference.cmake': dict(bytes=1075, sha256='254a8946088c364bff34a901acc546b747e2cf5fe1cda4a61e5b11d3d26fc61a')}
RECIPES = ('tools/build_playerbots_component.py', 'tools/prepare_server_isolated_build.py',
    'tools/prepare_server_isolated_sources.py', 'tools/qualify_server_isolated_build.py',
    'tools/verify_playerbots_reference.py', 'tools/verify_server_build.py', 'tools/owned_process_group.py',
    'tools/server_provider_sources.py', 'runtime/server/server-build-sources.lock.json',
    '.github/workflows/playerbots-schema.yml')
require = files.require


def verify_reference_inputs(prepared, manifest):
    rows = manifest['pristineGitFiles']['integration']
    result = {}
    for name in reference.INPUTS:
        expected = {key: rows[name][key] for key in ('bytes', 'sha256')}
        require(name not in REFERENCE_INPUTS or expected == REFERENCE_INPUTS[name],
                'playerbots-reference-original-input-pin-differs')
        require(files.identity(prepared / 'integration' / name) == expected,
                'playerbots-reference-prepared-input-changed')
        result[name] = expected
    return result


def declared_statement_count(header):
    with files.plain_file(header) as stream:
        raw = stream.read(128 * 1024 + 1)
    require(len(raw) <= 128 * 1024, 'playerbots-statement-header-bound')
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', raw.decode('utf-8'), flags=re.DOTALL)
    match = re.search(r'enum\s+PlayerbotsDatabaseStatements\s*:\s*uint32\s*\{([^{}]*)\}', text)
    require(match is not None, 'playerbots-statement-enum-required')
    values = [row.strip() for row in match[1].split(',')]
    require(values[-1] == 'MAX_PLAYERBOTS_STATEMENTS' and len(values) == 53 and
            len(set(values)) == 53 and all(re.fullmatch('PLAYERBOTS_[A-Z0-9_]+', row) for row in values[:-1]),
            'playerbots-original-52-statement-enum-differs')
    return len(values) - 1


def verify_cache_launchers(path):
    # cmake_options intentionally returns only the original eight build options.
    # Inspect the actual cache rows; absent, duplicated or nonempty is a failure.
    with files.plain_file(path) as stream:
        raw = stream.read(files.MAX_METADATA + 1)
    require(len(raw) <= files.MAX_METADATA, 'playerbots-cmake-cache-byte-bound')
    text = raw.decode('utf-8')
    result = {}
    for name in ('CMAKE_C_COMPILER_LAUNCHER', 'CMAKE_CXX_COMPILER_LAUNCHER'):
        require(re.findall(r'^' + name + r':[^=]+=(.*)$', text, re.MULTILINE) == [''],
                'playerbots-compiler-cache-launcher-enabled-or-absent')
        result[name] = ''
    return result


def copy_exact(source, target, expected=None, *, executable=False):
    identity = files.identity(source)
    require(expected is None or identity == expected, 'playerbots-payload-input-changed')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with files.plain_file(source) as incoming, target.open('xb') as output:
        shutil.copyfileobj(incoming, output, 128 * 1024)
        output.flush(); os.fsync(output.fileno())
    target.chmod(0o755 if executable else 0o444)
    require(files.identity(target) == identity, 'playerbots-payload-copy-changed')
    return identity


def retain_payload(payload, prepared, acquired, output, original_lock, environment, receipt):
    selected = {
        'bin/playerbots-schema': output / 'build' / TARGET,
        'source-inputs/server-engine-source-inputs.tar.gz': acquired / 'source-inputs/server-engine-source-inputs.tar.gz',
        'source-inputs/source-inputs-receipt.json': acquired / 'source-inputs/source-inputs-receipt.json',
        'source-inputs/original-sources.lock.json': original_lock,
        'provenance/preparation-receipt.json': prepared / 'preparation-receipt.json',
        'provenance/archival-revision.txt': prepared / 'provenance/archival-revision.txt',
        'provenance/original-build.json': prepared / 'provenance/metadata/server-build.json',
        'provenance/original-modules.json': prepared / 'provenance/metadata/server-modules.json',
        'provenance/original-compile_commands.json': prepared / 'provenance/metadata/compile_commands.json',
        'build/compile_commands.json': output / 'build/compile_commands.json',
        'build/CMakeCache.txt': output / 'build/CMakeCache.txt',
        'build/commands.json': output / 'diagnostics/commands.json',
        'build/environment-before.json': output / 'diagnostics/environment-before.json',
        'build/environment-after.json': output / 'diagnostics/environment-after.json',
        'build/input-environment.json': environment,
        'provenance/programs-provider.lock.json': PROVIDER,
        'provenance/isolated-build.lock.json': inputs.LOCK,
    }
    for name in ('cache-environment.json', 'build-packages.txt', 'build-host.txt', 'CMakeCache.txt'):
        selected['original-environment/' + name] = acquired / 'environment' / name
    for name in receipt['sourceSupplements']:
        selected['supplements/' + name] = acquired / 'supplements' / name
    for name in RECIPES:
        selected['recipes/' + name] = ROOT / name
    for name in reference.INPUTS:
        selected['reference-inputs/' + name] = prepared / 'integration' / name
    for name in ('src/cmake/genrev.cmake', 'src/genrev/CMakeLists.txt'):
        selected['revision-adaptations/original/' + name] = prepared / 'provenance/source-export-adaptations' / name
        selected['revision-adaptations/prepared/' + name] = prepared / 'source' / name
    payload.mkdir(mode=0o700)
    inventory = {name: copy_exact(source, payload / name, executable=name == 'bin/playerbots-schema')
                 for name, source in selected.items()}
    require(inventory['bin/playerbots-schema'] == receipt['executable'] and
            inventory['provenance/original-build.json'] == receipt['originalBuild'] and
            inventory['provenance/original-modules.json'] == receipt['originalModules'] and
            inventory['source-inputs/original-sources.lock.json'] == receipt['sourceLock'],
            'playerbots-payload-original-or-new-identity-mismatch')
    return inventory


def build(prepared, acquired, original_lock, environment, output, *, integration_revision):
    require(platform.system() == 'Linux' and platform.machine() == 'aarch64',
            'native-arm64-playerbots-component-build-required')
    require(re.fullmatch('[0-9a-f]{40}', integration_revision or ''), 'playerbots-build-integration-revision-required')
    prepared = archives.directory(prepared); acquired = archives.directory(acquired)
    original_lock = Path(os.path.abspath(original_lock)); environment = Path(os.path.abspath(environment))
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and all(root != output and root not in output.parents and output not in root.parents
            for root in (prepared, acquired)), 'existing-or-overlapping-playerbots-build-output-preserved')
    network = isolated.require_offline()
    output.mkdir(mode=0o700); (output / 'diagnostics').mkdir(mode=0o700); (output / 'tmp').mkdir(mode=0o700)
    proof = dict(formatVersion=1, scope='source-built-playerbots-schema-helper', phase='verify-inputs',
        integrationRevision=integration_revision, network=network, buildTarget=TARGET,
        actualCompileSucceeded=False, actualDatabaseSourcesAndDefinitionVerified=False,
        databaseExecuted=False, sqlExecuted=False, sourceCompanionComplete=False,
        isolatedSourceRebuildQualified=False, fullServerCompileSucceeded=False,
        originalServerProgramsReplaced=False, playerbotsAiQualified=False,
        worldserverQualified=False, androidRuntimeQualified=False, gameplayQualified=False)
    isolated.write_json(output / 'qualification.json', proof)
    commands = []
    try:
        provider, provider_identity = modules.read_json(PROVIDER)
        sources.validate_current(provider, ROOT / 'sources.lock.json')
        prep, prep_identity, manifest = isolated.verify_prepared(prepared, acquired, original_lock=original_lock)
        require(prep['originalBuild'] == provider['originalBuild'] == ORIGINAL_BUILD and
                prep['originalCompiledModules'] == provider['originalModules'] == ORIGINAL_MODULES and
                prep['sourceLock'] == provider['serverBuildSourceLock'] == files.identity(original_lock) and
                sources.same(manifest['source'], provider['serverSource']), 'playerbots-original-server-binding-differs')
        original, original_identity = modules.read_json(prepared / 'provenance/metadata/server-modules.json')
        require(original_identity == ORIGINAL_MODULES and 'mod-playerbots' in original['enabledModules'] and
                'playerbots.conf' in original['configFiles'], 'playerbots-original-module-selection-required')
        proof.update(originalBuild=prep['originalBuild'], originalModules=prep['originalCompiledModules'],
            originalCompileCommands=manifest['compileCommands'], sourceLock=prep['sourceLock'],
            serverSource=manifest['source'], preparationReceipt=prep_identity,
            sourceInputArchive=prep['sourceInputArchive'], sourceInputReceipt=prep['sourceInputReceipt'],
            sourceSupplements=prep['sourceSupplements'], programsProviderPin=provider_identity,
            referenceInputs=verify_reference_inputs(prepared, manifest),
            preparedStatementCountDeclared=declared_statement_count(prepared / 'source/src/server/database/Database/Implementation/PlayerbotsDatabase.h'))
        supplied, supplied_identity = modules.read_json(environment)
        require(supplied.get('scope') == 'measured-original-relevant-native-build-environment-comparison' and
                supplied.get('relevantBuildEnvironmentMatched') is True, 'playerbots-input-environment-comparison-required')
        proof['inputEnvironment'] = supplied_identity
        observed = inputs.verify_environment(acquired, output / 'diagnostics/environment-before.json', original_lock=original_lock)
        require(observed['relevantBuildEnvironmentMatched'] is True, 'playerbots-relevant-build-environment-differs')
        proof['environmentBefore'] = observed
        cmake = shutil.which('cmake'); compilers = {name: shutil.which(name) for name in ('gcc', 'g++')}
        require(cmake is not None and all(compilers.values()), 'playerbots-actual-build-tools-missing')
        cmake = Path(cmake).resolve(strict=True)
        compilers = {name: Path(path).resolve(strict=True) for name, path in compilers.items()}
        proof['compilerExecutables'] = {name: dict(path=str(path), **files.identity(path)) for name, path in compilers.items()}
        proof['cmakeExecutable'] = dict(path=str(cmake), **files.identity(cmake))
        build_environment = isolated.build_environment(output)
        def run(arguments, name, timeout):
            commands.append(dict(phase=name, argv=[str(row) for row in arguments], environment=build_environment))
            isolated.write_json(output / 'diagnostics/commands.json', commands)
            return isolated.run_owned(arguments, output / ('diagnostics/' + name + '.log'), build_environment,
                                      cwd=ROOT, timeout=timeout)
        proof['phase'] = 'configure'; isolated.write_json(output / 'qualification.json', proof)
        arguments = isolated.configure_arguments(cmake, prepared, output) + [
            '-DCMAKE_C_COMPILER=' + str(compilers['gcc']), '-DCMAKE_CXX_COMPILER=' + str(compilers['g++'])]
        proof['configure'] = run(arguments, 'configure', 900)
        proof['cmakeOptions'] = files.cmake_options(output / 'build/CMakeCache.txt')
        proof['compilerLaunchers'] = verify_cache_launchers(output / 'build/CMakeCache.txt')
        command_identity = reference.commands(output / 'build/compile_commands.json', prepared / 'source', prepared / 'integration')
        proof['newCompileCommands'] = command_identity
        proof['phase'] = 'build-component'; isolated.write_json(output / 'qualification.json', proof)
        proof['compile'] = run([cmake, '--build', output / 'build', '--parallel', '2', '--target', TARGET], 'component-build', 3600)
        executable = output / 'build' / TARGET
        proof['executable'] = files.identity(executable)
        proof['elf'] = files.elf_header(executable, executable=True)
        dynamic = files.bounded_command(['readelf', '--wide', '--dynamic', '--version-info', str(executable)])
        proof['elf'].update(files.dynamic_metadata(dynamic))
        modules.verify_literals(executable, proof['executable'], ['ESTERIA_PLAYERBOTS_DATABASE_REFERENCE_COMPLETE statements='])
        proof['environmentAfter'] = inputs.verify_environment(acquired, output / 'diagnostics/environment-after.json', original_lock=original_lock)
        require(proof['environmentAfter']['relevantBuildEnvironmentMatched'] is True, 'playerbots-build-environment-changed')
        final, final_identity, _ = isolated.verify_prepared(prepared, acquired, original_lock=original_lock)
        require(final == prep and final_identity == prep_identity and
                reference.commands(output / 'build/compile_commands.json', prepared / 'source', prepared / 'integration') == command_identity,
                'playerbots-prepared-source-or-new-commands-changed-during-build')
        require(all(not (output / 'build' / name).exists() and not (output / 'build/bin' / name).exists()
                    for name in ('authserver', 'worldserver', 'dbimport')), 'playerbots-build-produced-unrequested-server-program')
        proof.update(actualCompileSucceeded=True, actualDatabaseSourcesAndDefinitionVerified=True, phase='built-component',
                     compilerCacheDisabled=True, sourceRepositoryFetched=False, assetTreesFetched=False)
        proof['payloadFiles'] = retain_payload(output / 'payload', prepared, acquired, output, original_lock, environment, proof)
        isolated.write_json(output / 'payload/helper-build.json', proof)
        isolated.write_json(output / 'qualification.json', proof)
        return proof
    except BaseException as error:
        proof.update(actualCompileSucceeded=False, actualDatabaseSourcesAndDefinitionVerified=False,
                     failurePhase=proof['phase'], failureClass=type(error).__name__, phase='failed')
        isolated.write_json(output / 'qualification.json', proof)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('prepared', 'inputs', 'original-lock', 'environment', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--integration-revision', default=os.environ.get('GITHUB_SHA'))
    args = parser.parse_args()
    proof = build(args.prepared, args.inputs, args.original_lock, args.environment, args.output,
                  integration_revision=args.integration_revision)
    print(json.dumps(proof, sort_keys=True, indent=2))


if __name__ == '__main__': main()
