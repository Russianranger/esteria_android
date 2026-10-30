#!/usr/bin/env python3
"""Observe a fresh native helper's actual closed Ninja source dependencies.

Only the playerbots DatabaseLoader reference is requested. The prior measured
helper/SQL receipts remain separate historical inputs; this new executable is
not assigned their SQL qualification or a complete corresponding-source seal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import build_playerbots_component as component, prepare_playerbots_helper as measured
from tools import capture_ordered_extractor_dependencies as capture, verify_target_dependency_observation as readback
from tools import verify_server_build as files, prepare_runtime as archives

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (component.TARGET,)
SCOPE = 'native-arm64-playerbots-helper-source-observation'
HEADER = 'source/src/server/database/Database/Implementation/PlayerbotsDatabase.h'
REQUIRED_SOURCES = tuple('source/' + name for name in component.reference.DATABASE_INPUTS) + (
    'integration/' + component.reference.INPUTS[0],)
RECIPES = ('tools/qualify_playerbots_helper_sources.py', 'tools/capture_ordered_extractor_dependencies.py',
    'tools/verify_target_dependency_observation.py', 'tests/test_playerbots_helper_sources.py',
    '.github/workflows/playerbots-helper-sources.yml', 'runtime/server/playerbots-helper-candidate.lock.json')
require = files.require


def prepared_inventory(prepared):
    rows = {}
    for prefix in ('source', 'external', 'integration'):
        for path in files.installed_files(prepared / prefix):
            rows[prefix + '/' + path.relative_to(prepared / prefix).as_posix()] = files.identity(path)
    require(0 < len(rows) <= 40000, 'playerbots-observed-prepared-file-count-bound')
    return rows


def target_builds(commands, build):
    require(type(commands) is list and len([row for row in commands if row.get('phase') == 'configure']) == 1,
            'playerbots-observation-one-configure-required')
    builds = []
    for row in commands:
        argv = row.get('argv')
        require(type(argv) is list and all(type(item) is str for item in argv), 'playerbots-observation-command-argv-required')
        if '--build' not in argv: continue
        require(argv.count('--build') == argv.count('--target') == 1 and
                argv[argv.index('--build') + 1] == str(build) and
                argv[argv.index('--target') + 1:] == list(TARGETS),
                'playerbots-observation-unrequested-build-target')
        builds.append(row)
    require(len(builds) == 2, 'playerbots-observation-exactly-two-target-builds-required')


def committed_recipes(revision):
    environment = dict(PATH='/usr/bin:/bin', GIT_NO_LAZY_FETCH='1', GIT_OPTIONAL_LOCKS='0',
        GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0')
    command = ['git', '-c', 'safe.directory=' + str(ROOT)]
    actual = subprocess.run(command + ['rev-parse', 'HEAD'], cwd=ROOT, env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True).stdout
    require(actual.strip().decode('ascii') == revision, 'playerbots-observation-integration-head-differs')
    result = {}
    for name in sorted(set(component.RECIPES) | set(RECIPES)):
        expected = files.identity(ROOT / name)
        require(0 < expected['bytes'] <= 2 << 20, 'playerbots-observation-recipe-byte-bound')
        raw = subprocess.run(command + ['show', revision + ':' + name], cwd=ROOT, env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True).stdout
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'],
                'playerbots-observation-recipe-not-committed-at-integration-revision')
        result[name] = expected
    return result


def retain(payload, component_root, acquired, original_lock, output, observation, final_identity):
    payload.mkdir(mode=0o700)
    original_payload = component_root / 'payload'
    initial, initial_identity = component.modules.read_json(original_payload / 'helper-build.json')
    require(initial_identity == files.identity(component_root / 'qualification.json'),
            'playerbots-initial-source-build-receipt-changed')
    selected = {}
    # Preserve the initial receipt and its binary rather than relabel either
    # after the metadata-stabilization build.
    for path in files.installed_files(original_payload):
        name = path.relative_to(original_payload).as_posix()
        if name == 'helper-build.json': name = 'provenance/helper-source-build.json'
        elif name == 'bin/playerbots-schema': name = 'provenance/first-pass-playerbots-schema'
        elif name in ('build/commands.json', 'build/compile_commands.json'): continue
        selected[name] = path
    selected.update({'bin/playerbots-schema': component_root / 'build' / component.TARGET,
        'build/compile_commands.json': component_root / 'build/compile_commands.json',
        'build/commands.json': output / 'diagnostics/commands.json',
        'build/observation-environment-before.json': output / 'diagnostics/environment-before.json',
        'build/observation-environment-after.json': output / 'diagnostics/environment-after.json',
        'original-inputs/sources.lock.json': original_lock})
    for path in files.installed_files(acquired): selected['acquired/' + path.relative_to(acquired).as_posix()] = path
    observed = output / 'dependency-observation'
    require({path.relative_to(observed).as_posix() for path in files.installed_files(observed)} == set(observation['outputFiles']),
            'playerbots-observation-output-file-set-changed')
    for name in observation['outputFiles']: selected['build/dependency-observation/' + name] = observed / name
    for name in RECIPES: selected['recipes/' + name] = ROOT / name
    inventory = {}
    for name, source in selected.items():
        expected = files.identity(source)
        if name.startswith('build/dependency-observation/'):
            require(expected == observation['outputFiles'][name.removeprefix('build/dependency-observation/')],
                    'playerbots-captured-output-changed-before-retention')
        inventory[name] = component.copy_exact(source, payload / name, expected, executable=name == 'bin/playerbots-schema')
    require(inventory['bin/playerbots-schema'] == final_identity and
            inventory['provenance/helper-source-build.json'] == initial_identity and
            inventory['provenance/first-pass-playerbots-schema'] == initial['executable'],
            'playerbots-original-or-final-helper-receipt-relabelled')
    return inventory, initial_identity


def build(prepared, acquired, original_lock, environment, output, *, integration_revision):
    require(platform.system() == 'Linux' and platform.machine() == 'aarch64',
            'native-arm64-playerbots-source-observation-required')
    require(isinstance(integration_revision, str) and re.fullmatch('[0-9a-f]{40}', integration_revision),
            'playerbots-observation-full-integration-revision-required')
    prepared, acquired = [archives.directory(Path(os.path.abspath(path))) for path in (prepared, acquired)]
    original_lock, environment = [Path(os.path.abspath(path)) for path in (original_lock, environment)]
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and all(output != root and output not in root.parents and root not in output.parents
            for root in (prepared, acquired)), 'existing-or-overlapping-playerbots-source-output-preserved')
    network = component.isolated.require_offline()
    output.mkdir(mode=0o700)
    for name in ('diagnostics', 'tmp'): (output / name).mkdir(mode=0o700)
    proof = dict(formatVersion=1, scope=SCOPE, phase='verify-inputs', integrationRevision=integration_revision,
        targets=list(TARGETS), network=network, qualificationSucceeded=False, actualTargetCompileSucceeded=False,
        actualDatabaseSourcesAndDefinitionVerified=False, actualTargetSourceDependencyObservation=False,
        preparedStatementCountDeclared=52, sourceCompanionComplete=False, transitiveIncludeClosureSealed=False,
        originalObjectBytesIndependentlyReadback=False, systemHeaderSourcesCopied=False,
        originalLinkInputBytesIndependentlyReadback=False, linkInputsCopied=False, systemLinkSourcesCopied=False,
        unknownOriginalSystemHashesCompared=False, originalServerProgramsRebuilt=False,
        originalServerProgramsReplaced=False, originalMeasuredHelperReplaced=False,
        originalHelperNativeSqlQualificationTransferred=False, selectedNewHelperSqlQualified=False,
        helperExecuted=False, databaseExecuted=False, sqlExecuted=False, fullServerCompileSucceeded=False,
        playerbotsAiQualified=False, worldserverQualified=False, androidRuntimeQualified=False, gameplayQualified=False)
    component.isolated.write_json(output / 'qualification.json', proof)
    try:
        proof['recipeInputs'] = committed_recipes(integration_revision)
        original, original_pin = measured.load_pin()
        proof.update(measuredHelperInputLock=original_pin, measuredHelperExecutable=original['executable'],
            measuredHelperBuildReceipt=original['helperBuildReceipt'], measuredHelperNativeSqlReceipt=original['nativeSqlReceipt'])
        proof['phase'] = 'initial-native-helper-build'; component.isolated.write_json(output / 'qualification.json', proof)
        component_root = output / 'component'
        initial = component.build(prepared, acquired, original_lock, environment, component_root,
                                  integration_revision=integration_revision)
        initial_identity = files.identity(component_root / 'qualification.json')
        require(initial.get('actualCompileSucceeded') is True and initial.get('actualDatabaseSourcesAndDefinitionVerified') is True and
                initial.get('scope') == 'source-built-playerbots-schema-helper' and initial.get('phase') == 'built-component' and
                initial.get('databaseExecuted') is False and initial.get('preparedStatementCountDeclared') == 52 and
                initial.get('originalBuild') == original['originalBuild'] and initial.get('originalModules') == original['originalModules'] and
                initial.get('sourceLock') == original['sourceLock'] and initial.get('serverSource') == original['serverSource'],
                'playerbots-initial-source-built-component-binding-differs')
        prep, prep_identity, manifest = component.isolated.verify_prepared(prepared, acquired, original_lock=original_lock)
        before = prepared_inventory(prepared)
        acquired_before = {path.relative_to(acquired).as_posix(): files.identity(path) for path in files.installed_files(acquired)}
        require(component.declared_statement_count(prepared / HEADER) == 52 and HEADER in before,
                'playerbots-original-prepared-statement-header-required')
        proof.update(originalBuild=initial['originalBuild'], originalModules=initial['originalModules'],
            sourceLock=initial['sourceLock'], serverSource=initial['serverSource'],
            sourceInputArchive=initial['sourceInputArchive'], sourceInputReceipt=initial['sourceInputReceipt'],
            sourceSupplements=initial['sourceSupplements'], originalCompileCommands=initial['originalCompileCommands'],
            acquisitionReceipt=acquired_before['acquisition.json'],
            preparationReceipt=prep_identity, helperSourceBuildReceipt=initial_identity,
            initialExecutable=initial['executable'], referenceInputs=initial['referenceInputs'],
            cmakeOptions=initial['cmakeOptions'], compilerExecutables=initial['compilerExecutables'],
            cmakeExecutable=initial['cmakeExecutable'],
            playerbotsStatementHeader=before[HEADER])
        proof['environmentBefore'] = component.inputs.verify_environment(acquired, output / 'diagnostics/environment-before.json',
                                                                         original_lock=original_lock)
        require(proof['environmentBefore'].get('relevantBuildEnvironmentMatched') is True,
                'playerbots-observation-build-environment-differs')
        commands, _ = component.modules.read_json(component_root / 'diagnostics/commands.json', limit=64 << 20)
        require(type(commands) is list, 'playerbots-initial-build-command-list-required')
        build_environment = component.isolated.build_environment(output)
        def run(argv, label, timeout):
            commands.append(dict(phase=label, argv=[str(value) for value in argv], environment=build_environment))
            component.isolated.write_json(output / 'diagnostics/commands.json', commands)
            return component.isolated.run_owned(argv, output / ('diagnostics/' + label + '.log'),
                build_environment, cwd=ROOT, timeout=timeout)
        cmake = Path(initial['cmakeExecutable']['path'])
        require(files.identity(cmake) == {key: initial['cmakeExecutable'][key] for key in ('bytes', 'sha256')},
                'playerbots-observation-cmake-executable-changed')
        proof['phase'] = 'target-metadata-stabilization'; component.isolated.write_json(output / 'qualification.json', proof)
        proof['generatedMetadataStabilizationBuild'] = run([cmake, '--build', component_root / 'build', '--parallel', '2',
                                                           '--target', *TARGETS], 'target-metadata-stabilization', 600)
        proof['compilerLaunchers'] = component.verify_cache_launchers(component_root / 'build/CMakeCache.txt')
        compile_commands = component.reference.commands(component_root / 'build/compile_commands.json', prepared / 'source', prepared / 'integration')
        require(compile_commands == initial['newCompileCommands'], 'playerbots-new-compile-command-selection-changed')
        proof['compileCommands'] = proof['newCompileCommands'] = compile_commands
        executable = component_root / 'build' / component.TARGET
        proof['executable'] = files.identity(executable); proof['elf'] = files.elf_header(executable, executable=True)
        proof['elf'].update(files.dynamic_metadata(files.bounded_command(['readelf', '--wide', '--dynamic', '--version-info', str(executable)])))
        component.modules.verify_literals(executable, proof['executable'], ['ESTERIA_PLAYERBOTS_DATABASE_REFERENCE_COMPLETE statements='])
        proof['finalExecutableMatchesMeasuredHelper'] = proof['executable'] == original['executable']
        proof['phase'] = 'observe-actual-helper-source-dependencies'; component.isolated.write_json(output / 'qualification.json', proof)
        ninja = shutil.which('ninja'); require(ninja is not None, 'playerbots-source-observation-ninja-required')
        def capture_run(argv, label, timeout):
            run(argv, label, timeout)
            return output / ('diagnostics/' + label + '.log')
        observed = capture.capture(component_root / 'build', prepared, component_root / 'build/compile_commands.json',
            Path(ninja).resolve(strict=True), capture_run, output / 'dependency-observation', targets=TARGETS)
        require(observed.get('objectElfMachines') == [183] and observed.get('observedObjects', 0) >= len(REQUIRED_SOURCES) and
                observed.get('compileCommands') == compile_commands and observed.get('dependenciesNotNewerThanObject') is True and
                type(observed.get('observedLinks')) is int and observed['observedLinks'] == 1 and
                observed.get('linkElfMachines') == [183] and observed.get('linkDependenciesNotNewerThanOutput') is True,
                'playerbots-actual-native-object-observation-required')
        observation, _ = component.modules.read_json(output / 'dependency-observation/observation.json', limit=64 << 20)
        require(all(before.get(name) == row for name, row in observation['projectFiles'].items()) and
                observation['projectFiles'].get(HEADER) == before[HEADER] and
                {str(prepared / name) for name in REQUIRED_SOURCES} <= {row['source'] for row in observation['objects'].values()},
                'playerbots-observed-reference-database-unit-or-source-binding-differs')
        proof['targetSourceDependencies'] = observed
        target_builds(commands, component_root / 'build')
        require(all(not (component_root / 'build' / name).exists() and not (component_root / 'build/bin' / name).exists()
                    for name in ('authserver', 'worldserver', 'dbimport', 'map_extractor', 'vmap4_extractor', 'mmaps_generator')),
                'playerbots-observation-produced-unrequested-server-or-tool')
        final, final_identity, _ = component.isolated.verify_prepared(prepared, acquired, original_lock=original_lock)
        require(final == prep and final_identity == prep_identity and prepared_inventory(prepared) == before and
                files.identity(component_root / 'qualification.json') == initial_identity and
                component.reference.commands(component_root / 'build/compile_commands.json', prepared / 'source', prepared / 'integration') == compile_commands and
                committed_recipes(integration_revision) == proof['recipeInputs'],
                'playerbots-observation-source-original-receipt-or-command-input-changed')
        proof['environmentAfter'] = component.inputs.verify_environment(acquired, output / 'diagnostics/environment-after.json',
                                                                        original_lock=original_lock)
        require(proof['environmentAfter'].get('relevantBuildEnvironmentMatched') is True,
                'playerbots-source-observation-environment-changed')
        payload = output / 'payload'
        inventory, retained_initial = retain(payload, component_root, acquired, original_lock, output, observed, proof['executable'])
        require(retained_initial == initial_identity, 'playerbots-retained-initial-build-receipt-differs')
        require(all(inventory.get('recipes/' + name) == row for name, row in proof['recipeInputs'].items()) and
                {name.removeprefix('acquired/'): row for name, row in inventory.items() if name.startswith('acquired/')} == acquired_before,
                'playerbots-retained-committed-recipes-or-acquired-inputs-changed')
        replay = readback.verify(payload, observed, before, compile_commands, targets=TARGETS, machines=(183,),
            observation_identity=observed['outputFiles']['observation.json'], required_sources=REQUIRED_SOURCES,
            expected_links=1, required_link_programs={component.TARGET: proof['executable']})
        require(replay['observedObjectMetadataReadback'] is True and replay['originalObjectBytesIndependentlyReadback'] is False and
                replay['observedLinkMetadataReadback'] is True and replay['originalLinkInputBytesIndependentlyReadback'] is False,
                'playerbots-retained-observation-readback-required')
        proof.update(phase='complete', qualificationSucceeded=True, actualTargetCompileSucceeded=True,
            actualDatabaseSourcesAndDefinitionVerified=True, actualTargetSourceDependencyObservation=True,
            observedObjectMetadataReadback=True, onlyRequestedHelperBuilt=True, compilerCacheDisabled=True,
            observedLinkMetadataReadback=True,
            originalInputsUnchanged=True, payloadFiles=inventory)
        component.isolated.write_json(payload / 'source-build.json', proof)
        component.isolated.write_json(output / 'qualification.json', proof)
        return proof
    except BaseException as error:
        proof.update(failurePhase=proof['phase'], failureClass=type(error).__name__, phase='failed', qualificationSucceeded=False,
            actualTargetCompileSucceeded=False, actualDatabaseSourcesAndDefinitionVerified=False,
            actualTargetSourceDependencyObservation=False)
        component.isolated.write_json(output / 'qualification.json', proof)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    make = sub.add_parser('build')
    for name in ('prepared', 'inputs', 'original-lock', 'environment', 'output'): make.add_argument('--' + name, type=Path, required=True)
    make.add_argument('--integration-revision', default=os.environ.get('GITHUB_SHA'))
    args = parser.parse_args()
    print(json.dumps(build(args.prepared, args.inputs, args.original_lock, args.environment, args.output,
                           integration_revision=args.integration_revision), sort_keys=True, indent=2))


if __name__ == '__main__': main()
