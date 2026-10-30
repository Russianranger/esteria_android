#!/usr/bin/env python3
"""Compose measured helper sources without relabeling the three-program seal.

The initial helper and its real SQL proof remain immutable. A separate native
single-target observation supplies source/dependency coverage; this source-only
composer authenticates and reconstructs both inputs before publishing a new seal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import build_playerbots_component as component, manifest_server_content as content
from tools import manifest_server_modules as modules, package_playerbots_helper as helper
from tools import package_server_content as transaction, package_server_engine as engine
from tools import prepare_runtime as archives, prepare_server_installation_inputs as registered
from tools import prepare_server_isolated_sources as preparation, provider_server_programs as programs
from tools import qualify_server_isolated_build as isolated, server_provider_sources as sources
from tools import verify_playerbots_reference as reference, verify_server_build as files
from tools import verify_target_dependency_observation as observation

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/server/playerbots-sources-inputs.lock.json'
SOURCE_ARCHIVE = 'playerbots-helper-complete-sources.tar.gz'
RECEIPT = 'playerbots-source-receipt.json'
NATIVE_SCOPE = 'native-arm64-playerbots-helper-source-observation'
TARGETS = (component.TARGET,)
FALSE_FLAGS = ('sourceCompanionComplete', 'originalThreeProgramsReplaced', 'androidProviderCreated',
               'productionActivated', 'androidRuntimeQualified', 'gameplayQualified')
require = files.require


def identity(row):
    require(type(row) is dict and type(row.get('bytes')) is int and 0 <= row['bytes'] <= 512 << 20 and
            isinstance(row.get('sha256'), str) and re.fullmatch('[a-f0-9]{64}', row['sha256']),
            'helper-source-invalid-identity')
    return {key: row[key] for key in ('bytes', 'sha256')}


def inventory(root):
    return {p.relative_to(root).as_posix(): files.identity(p) for p in files.installed_files(root)}


def check_inventory(root, expected, *, extra=()):
    require(type(expected) is dict and 0 < len(expected) <= 20000, 'helper-source-inventory-bound')
    for name, row in expected.items(): content.safe_path(name); identity(row)
    actual = inventory(root)
    require(set(actual) == set(expected) | set(extra) and
            all(actual[name] == identity(row) for name, row in expected.items()),
            'helper-source-input-file-set-or-bytes-differ')
    return actual


def load_pin():
    pin, pid = modules.read_json(LOCK, limit=512 << 10)
    require(type(pin.get('formatVersion')) is int and pin['formatVersion'] == 1 and
            pin.get('scope') == 'playerbots-helper-corresponding-source-inputs' and
            pin.get('state') == 'measured-native-helper-dependency-capture' and
            all(pin.get(k) is False for k in FALSE_FLAGS), 'helper-source-measured-input-pin-required')
    provider = programs.load_pin(sealed=True)
    for name in ('serverBuildSourceLock', 'originalBuild', 'originalModules', 'originalSourceQualification'):
        require(pin.get(name) == provider['sourceQualification' if name == 'originalSourceQualification' else name],
                'helper-source-original-provider-binding-differs')
    require(sources.same(pin.get('serverSource'), provider['serverSource']), 'helper-source-server-source-differs')
    registration, _, _ = registered.load_pin()
    expected = dict(producer=registration['producer'], artifact=registration['artifact'],
        candidatePin=registration['members']['candidate/candidate-pin.json'],
        candidateArchive=registration['members']['candidate.tar.gz'], helperInputLock=registration['helperInputLock'])
    require(pin.get('candidateRegistration') == expected, 'helper-source-registered-candidate-differs')
    native = pin.get('nativeCapture')
    require(type(native) is dict and type(native.get('workflowRun')) is int and native['workflowRun'] > 0 and
            type(native.get('job')) is int and native['job'] > 0 and
            re.fullmatch('[a-f0-9]{40}', native.get('integrationRevision', '')) and
            type(native.get('observedObjects')) is int and 0 < native['observedObjects'] <= 5000 and
            type(native.get('observedLinks')) is int and native['observedLinks'] == 1,
            'helper-source-native-capture-pin-required')
    for name in ('receipt', 'dependencyObservation', 'executable'):
        require(identity(native[name])['bytes'] > 0, 'helper-source-native-artifact-must-not-be-empty')
    return pin, pid, provider


def verify_original(root, pin):
    names = {'archive': isolated.SOURCE_ARCHIVE, 'qualification': 'qualification.json', 'receipt': 'sealed-source-receipt.json'}
    for key, name in names.items():
        require(files.identity(root / name) == pin['originalSourceQualification'][key],
                'helper-source-original-three-program-seal-changed')
    sealed, _ = modules.read_json(root / names['receipt'])
    q, _ = modules.read_json(root / names['qualification'])
    require(sealed.get('scope') == 'complete-isolated-server-source-rebuild-companion' and
            all(sealed.get(k) is True for k in ('archiveReadbackVerified', 'sourceCompanionComplete',
                'isolatedSourceRebuildQualified', 'originalUnsealedReceiptsUnchanged')) and
            sealed.get('archive') == dict(file=isolated.SOURCE_ARCHIVE, **pin['originalSourceQualification']['archive']) and
            sealed.get('qualification') == pin['originalSourceQualification']['qualification'] and
            sealed.get('sourceLock') == pin['serverBuildSourceLock'] and
            sealed.get('originalBuild') == pin['originalBuild'] and sealed.get('originalCompiledModules') == pin['originalModules'],
            'helper-source-original-seal-bindings-differ')
    require(q.get('scope') == 'actual-native-arm64-isolated-server-source-rebuild' and q.get('phase') == 'complete' and
            all(q.get(k) is True for k in ('sourceCompanionComplete', 'isolatedSourceRebuildQualified',
                'transitiveIncludeClosureProved', 'fullCompileObserved', 'noCompilerCacheUsed',
                'fullBuildAndReferencesPassed', 'originalSelectionPreserved')) and
            q.get('sourceLock') == pin['serverBuildSourceLock'] and q.get('originalBuild') == pin['originalBuild'] and
            q.get('originalCompiledModules') == pin['originalModules'] and
            all(q.get(k, {}).get('exitCode') == 0 for k in ('configure', 'fullBuild', 'referenceBuild', 'install')),
            'helper-source-original-full-build-required')
    require(all(doc.get(k) is False for doc in (sealed, q) for k in ('androidRuntimeQualified', 'gameplayQualified')),
            'helper-source-original-native-scope-differs')
    rows = sealed['archiveFiles']
    require(identity(rows['qualification/qualification.json']) == pin['originalSourceQualification']['qualification'],
            'helper-source-original-embedded-qualification-differs')
    engine.verify_archive(root / isolated.SOURCE_ARCHIVE, rows)
    return sealed


def verify_native(payload, pin):
    q, qid = modules.read_json(payload / 'source-build.json', limit=4 << 20)
    native = pin['nativeCapture']
    require(qid == native['receipt'] and q.get('scope') == NATIVE_SCOPE and q.get('phase') == 'complete' and
            q.get('integrationRevision') == native['integrationRevision'] and q.get('targets') == list(TARGETS),
            'helper-source-exact-native-observation-required')
    # A native observation never retroactively seals the initial compilation.
    require(all(q.get(k) is True for k in ('actualTargetCompileSucceeded', 'actualDatabaseSourcesAndDefinitionVerified',
                'qualificationSucceeded', 'actualTargetSourceDependencyObservation', 'observedObjectMetadataReadback',
                'onlyRequestedHelperBuilt', 'compilerCacheDisabled', 'originalInputsUnchanged')) and
            all(q.get(k) is False for k in ('sourceCompanionComplete', 'sqlExecuted', 'databaseExecuted',
                'originalServerProgramsReplaced', 'fullServerCompileSucceeded', 'playerbotsAiQualified',
                'originalServerProgramsRebuilt', 'originalMeasuredHelperReplaced',
                'originalHelperNativeSqlQualificationTransferred', 'selectedNewHelperSqlQualified',
                'worldserverQualified', 'androidRuntimeQualified', 'gameplayQualified')) and
            q.get('network') == dict(interfaces=['lo'], externalNetworkingAvailable=False) and
            q.get('generatedMetadataStabilizationBuild', {}).get('exitCode') == 0,
            'helper-source-native-scope-or-gates-differ')
    for name in ('originalBuild', 'originalModules', 'sourceLock'):
        expected = pin['serverBuildSourceLock' if name == 'sourceLock' else name]
        require(q.get(name) == expected, 'helper-source-native-original-binding-differs')
    require(sources.same(q.get('serverSource'), pin['serverSource']) and
            q.get('executable') == native['executable'] and type(q.get('preparedStatementCountDeclared')) is int and
            q['preparedStatementCountDeclared'] == 52, 'helper-source-native-source-or-statement-binding-differs')
    rows = check_inventory(payload, q['payloadFiles'], extra=('source-build.json',))
    initial, iid = modules.read_json(payload / 'provenance/helper-source-build.json', limit=4 << 20)
    require(iid == q.get('helperSourceBuildReceipt') and initial.get('scope') == 'source-built-playerbots-schema-helper' and
            initial.get('phase') == 'built-component' and initial.get('actualCompileSucceeded') is True and
            initial.get('actualDatabaseSourcesAndDefinitionVerified') is True and
            initial.get('configure', {}).get('exitCode') == initial.get('compile', {}).get('exitCode') == 0 and
            initial.get('executable') == q.get('initialExecutable') == rows['provenance/first-pass-playerbots-schema'] and
            all(initial.get(k) == q.get(k) for k in ('originalBuild', 'originalModules', 'sourceLock', 'serverSource',
                'preparationReceipt', 'sourceInputArchive', 'sourceInputReceipt', 'sourceSupplements',
                'referenceInputs', 'cmakeOptions', 'compilerExecutables')),
            'helper-source-initial-compilation-receipt-relabelled-or-changed')
    require(rows['bin/playerbots-schema'] == native['executable'] and
            files.elf_header(payload / 'bin/playerbots-schema', executable=True).get('machine') == 'AArch64',
            'helper-source-native-final-executable-differs')
    return q, qid, rows


def source_files(root, *, excluded=()):
    """Copy source records only; excluded native programs stay in runtime proof."""
    result = {}
    for path in files.installed_files(root):
        name = path.relative_to(root).as_posix()
        if name in excluded: continue
        require('.git' not in Path(name).parts and Path(name).suffix.lower() not in
                ('.o', '.obj', '.a', '.so', '.exe', '.dll', '.debug', '.pdb'), 'helper-source-binary-or-git-member')
        with files.plain_file(path) as stream:
            require(stream.read(4) != b'\x7fELF', 'helper-source-undeclared-native-program')
        result[name] = path
    return result


def export_recipes(git_root, revision, supplied, destination):
    """Export committed build glue and notices, with no working-tree reads."""
    source = content.GitObjects(git_root, revision, allow_fetch=False)
    names = {'LICENSE', 'sources.lock.json'}
    for name, row in source.files.items():
        path = Path(name)
        if ((path.parts[0] in ('tools', 'runtime', 'tests') and path.suffix == '.py') or
            (path.parts[0] == 'tests' and path.suffix in ('.c', '.cpp', '.h', '.hpp', '.cmake')) or
            (name.startswith(('runtime/server/', 'config/')) and path.suffix in ('.json', '.md')) or
            (name.startswith('patches/server/') and path.suffix == '.patch')) and not name.startswith('runtime/evidence/'):
            names.add(name)
    names.update(supplied)
    require(0 < len(names) <= 4000 and all(n in source.files and source.files[n]['kind'] == 'blob' and
            source.files[n]['mode'] in ('100644', '100755') for n in names), 'helper-source-committed-recipe-set-invalid')
    rows = source.identities(names, True)
    require(sum(identity(row)['bytes'] for row in rows.values()) <= 128 << 20, 'helper-source-recipe-byte-bound')
    for name, path in supplied.items():
        require(files.identity(path) == identity(rows[name]), 'helper-source-supplied-recipe-not-exact-git-blob')
    batch = transaction.GitBatch(source)
    try:
        for name, row in sorted(rows.items()):
            target = destination / name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            incoming = batch.blob(row)
            with target.open('xb') as outgoing:
                while block := incoming.read(files.BUFFER): outgoing.write(block)
                outgoing.flush(); os.fsync(outgoing.fileno())
            batch.finish_blob(incoming); target.chmod(0o444)
    finally: batch.close()
    return dict(integrationRevision=revision, integrationTree=source.tree, files=rows,
        suppliedRecipesMatchCommittedGitBlobs=True, gitNetworkFetchAllowed=False, gitMetadataIncluded=False)


def sealing_recipes(git_root, destination):
    """Retain the current sealer separately from earlier native build recipes."""
    require(git_root.resolve(strict=True) == ROOT.resolve(strict=True), 'helper-source-sealing-code-root-differs')
    environment = dict(PATH='/usr/bin:/bin', GIT_NO_LAZY_FETCH='1', GIT_OPTIONAL_LOCKS='0',
        GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0')
    revision = subprocess.run(['git', '-c', 'safe.directory=' + str(git_root), 'rev-parse', 'HEAD'],
        cwd=git_root, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, check=True, timeout=10).stdout.strip().decode('ascii')
    require(re.fullmatch('[a-f0-9]{40}', revision), 'helper-source-sealing-head-invalid')
    names = ('tools/seal_playerbots_helper_sources.py', 'tools/verify_target_dependency_observation.py',
             'tools/prepare_playerbots_source_companion.py', 'tests/test_playerbots_source_inputs.py',
             'runtime/server/playerbots-sources-inputs.lock.json', 'tests/test_playerbots_source_companion.py')
    return export_recipes(git_root, revision, {name: ROOT / name for name in names}, destination)


def correspondence(old, new, provider):
    """Keep old runtime provenance distinct from the new coverage compilation."""
    for key in ('originalBuild', 'originalModules', 'sourceLock', 'preparationReceipt', 'sourceInputArchive',
                'sourceInputReceipt', 'sourceSupplements', 'referenceInputs', 'cmakeOptions', 'compilerExecutables'):
        require(old.get(key) == new.get(key) and old.get(key) is not None,
                'helper-source-original-and-observation-source-contract-differs:' + key)
    require(old['originalBuild'] == provider['originalBuild'] and old['originalModules'] == provider['originalModules'] and
            old['sourceLock'] == provider['serverBuildSourceLock'] and
            sources.same(old.get('serverSource'), new.get('serverSource')) and
            old.get('preparedStatementCountDeclared') == new.get('preparedStatementCountDeclared') == 52,
            'helper-source-original-and-observation-reference-binding-differs')
    return dict(originalRuntimeExecutable=old['executable'], sourceObservationExecutable=new['executable'],
        exactOriginalPreparedSourceAndReferenceInputs=True, exactCompilerIdentitiesAndCmakeOptions=True,
        bitIdenticalExecutableClaimed=False, originalNativeObjectsObserved=False,
        separatelyBuiltDependencyObservation=True)


def seal(payload, candidate, original_sealed, git_root, output):
    pin, pid, provider = load_pin()  # Pending/missing measurements refuse before filesystem mutation.
    roots = [archives.directory(Path(os.path.abspath(p))) for p in (payload, candidate, original_sealed, git_root)]
    payload, candidate, original_sealed, git_root = roots
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and all(not observation.dependencies.inside(output, p) and
            not observation.dependencies.inside(p, output) for p in roots), 'helper-source-existing-or-overlapping-output')
    selected = helper.verify(candidate, pin['candidateRegistration']['candidatePin']['sha256'])
    q, qid, payload_rows = verify_native(payload, pin)
    old_root = candidate / 'companion/build-payload'
    old, old_id = modules.read_json(old_root / 'helper-build.json')
    binding = correspondence(old, q, provider)
    original = verify_original(original_sealed, pin)
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        work = stage / 'work'; public = stage / 'public'; work.mkdir(); public.mkdir()
        acquired = payload / 'acquired'; lock = payload / 'source-inputs/original-sources.lock.json'
        require(files.identity(lock) == pin['serverBuildSourceLock'], 'helper-source-archived-lock-changed')
        prepared = work / 'prepared'
        preparation.prepare(acquired / 'source-inputs', prepared, acquired / 'supplements', original_lock=lock)
        prep, prep_id, manifest = isolated.verify_prepared(prepared, acquired, original_lock=lock)
        require(prep_id == old['preparationReceipt'] == q['preparationReceipt'] and
                prep['originalBuild'] == pin['originalBuild'] and prep['originalCompiledModules'] == pin['originalModules'],
                'helper-source-original-preparation-replay-differs')
        prepared_rows = inventory(prepared)
        required = tuple('source/' + n for n in reference.DATABASE_INPUTS) + ('integration/' + reference.INPUTS[0],)
        graph = observation.verify(payload, q['targetSourceDependencies'], prepared_rows, q['compileCommands'],
            targets=TARGETS, machines=(183,), observation_identity=pin['nativeCapture']['dependencyObservation'],
            required_sources=required, expected_objects=pin['nativeCapture']['observedObjects'],
            expected_links=1, required_link_programs={component.TARGET: q['executable']})
        native_prepared = Path(graph['nativePreparedRoot'])
        require(reference.commands(payload / 'build/compile_commands.json', native_prepared / 'source',
                native_prepared / 'integration') == q['compileCommands'],
                'helper-source-actual-database-playerbots-definition-differs')
        require(component.verify_reference_inputs(prepared, manifest) == old['referenceInputs'] and
                component.declared_statement_count(prepared / 'source/src/server/database/Database/Implementation/PlayerbotsDatabase.h') == 52,
                'helper-source-original-reference-inputs-differ')
        recipe_proofs = {}
        for label, root, revision in (('initial-helper', old_root, old['integrationRevision']),
                                      ('source-observation', payload, q['integrationRevision'])):
            supplied = {p.relative_to(root / 'recipes').as_posix(): p for p in files.installed_files(root / 'recipes')}
            recipe_proofs[label] = export_recipes(git_root, revision, supplied, work / 'recipes' / label)
        recipe_proofs['source-sealing'] = sealing_recipes(git_root, work / 'recipes/source-sealing')
        coverage = dict(formatVersion=1, scope='playerbots-helper-composed-corresponding-source-coverage',
            inputLock=pid, originalThreeProgramSourceQualification=pin['originalSourceQualification'],
            helperRuntime=selected['helper'], originalHelperBuildReceipt=old_id, nativeObservationReceipt=qid,
            originalAndObservationCorrespondence=binding, dependencyObservation=graph, integrationRecipes=recipe_proofs,
            nativeProgramsExcludedFromSourceArchive={
                'initial-helper/build-payload/bin/playerbots-schema': old['executable'],
                'observation/bin/playerbots-schema': q['executable'],
                'observation/provenance/first-pass-playerbots-schema': q['initialExecutable']},
            originalUnsealedReceiptsUnchanged=True, newCompilationPerformedHere=False)
        engine.put_metadata(work / 'source-coverage.json', coverage)
        plan = dict(formatVersion=1, scope='offline-single-helper-source-replay-plan', targets=list(TARGETS),
            originalRuntimeHelperUnchanged=True, originalThreeProgramSourceQualification=pin['originalSourceQualification'],
            preparation=['python3', 'recipes/source-observation/tools/prepare_server_isolated_sources.py',
                '--source-inputs', 'observation/acquired/source-inputs', '--supplements', 'observation/acquired/supplements',
                '--original-lock', 'observation/source-inputs/original-sources.lock.json', '--output', 'replay/prepared'],
            build=['python3', 'recipes/source-observation/tools/build_playerbots_component.py',
                '--prepared', 'replay/prepared', '--inputs', 'observation/acquired', '--original-lock',
                'observation/source-inputs/original-sources.lock.json', '--environment', 'observation/build/input-environment.json',
                '--integration-revision', q['integrationRevision'], '--output', 'replay/native'],
            generatedMetadataStabilization=['cmake', '--build', 'replay/native/build', '--parallel', '2',
                '--target', component.TARGET],
            archivedBuildDriverRequiresGitMetadata=False,
            nativeObservationDriverRetainedAsProducerEvidenceOnly=True,
            nativeProducerCommitGuardRelaxed=False,
            requiresMatchingNativeArm64Toolchain=True, requiresLoopbackOnlyNetworkNamespace=True,
            requiresGameAssets=False, requiresOriginalThreeProgramBuild=False, bitIdenticalExecutableClaimed=False,
            nativeSystemHeaderSourcesCopied=False)
        engine.put_metadata(work / 'replay-plan.json', plan)
        retained = {'source-coverage.json': work / 'source-coverage.json', 'replay-plan.json': work / 'replay-plan.json',
            'initial-helper/native-sql-qualification.json': candidate / 'companion/native-sql-qualification.json',
            'initial-helper/candidate-pin.json': candidate / 'candidate-pin.json'}
        for name in (isolated.SOURCE_ARCHIVE, 'qualification.json', 'sealed-source-receipt.json'):
            retained['original-three-programs/' + name] = original_sealed / name
        for prefix, directory, excluded in (('initial-helper/build-payload', old_root, ('bin/playerbots-schema',)),
            ('observation', payload, ('bin/playerbots-schema', 'provenance/first-pass-playerbots-schema')),
            ('prepared', prepared, ()), ('recipes', work / 'recipes', ())):
            for name, path in source_files(directory, excluded=excluded).items(): retained[prefix + '/' + name] = path
        selected_rows = {name: files.identity(path) for name, path in retained.items()}
        archive = public / SOURCE_ARCHIVE
        rows = isolated.write_source_archive(archive, retained)
        require(all(identity(rows[n]) == row for n, row in selected_rows.items()), 'helper-source-input-changed-during-archive')
        # Revalidate every immutable producer and reconstructed source before
        # the only positive helper-source receipt becomes visible.
        require(load_pin()[1] == pid and inventory(prepared) == prepared_rows and
                files.identity(payload / 'source-build.json') == qid and
                check_inventory(payload, q['payloadFiles'], extra=('source-build.json',)) == payload_rows and
                helper.verify(candidate, pin['candidateRegistration']['candidatePin']['sha256']) == selected and
                all(files.identity(path) == selected_rows[name] for name, path in retained.items()),
                'helper-source-input-changed-before-publication')
        verify_original(original_sealed, pin); engine.verify_archive(archive, rows)
        sealed = dict(formatVersion=1, scope='complete-playerbots-helper-corresponding-source-companion',
            inputLock=pid, archive=dict(file=SOURCE_ARCHIVE, **files.identity(archive)), archiveFiles=rows,
            originalThreeProgramSourceQualification=pin['originalSourceQualification'],
            helperRuntime=selected['helper'], originalHelperBuildReceipt=old_id, nativeObservationReceipt=qid,
            serverBuildSourceLock=pin['serverBuildSourceLock'], originalBuild=pin['originalBuild'], originalModules=pin['originalModules'],
            sourceCoverage=files.identity(work / 'source-coverage.json'), replayPlan=files.identity(work / 'replay-plan.json'),
            sourceCompanionComplete=True, helperSourceCompanionComplete=True, archiveReadbackVerified=True,
            originalThreeProgramsAndReceiptsUnchanged=True, originalHelperAndNativeReceiptsUnchanged=True,
            newCompilationPerformedHere=False, originalNativeObjectsObserved=False, bitIdenticalExecutableClaimed=False,
            sqlExecuted=False, androidProviderCreated=False, productionActivated=False,
            androidRuntimeQualified=False, worldserverQualified=False, playerbotsAiQualified=False, gameplayQualified=False)
        engine.put_metadata(public / RECEIPT, sealed); archives.sync_directory(public)
        transaction.publish_directory(public, output); archives.sync_directory(output.parent)
        return sealed
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('payload', 'candidate', 'original-sealed', 'integration-git-root', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = seal(args.payload, args.candidate, args.original_sealed, args.integration_git_root, args.output)
    print(json.dumps({k: result[k] for k in ('scope', 'archive', 'helperSourceCompanionComplete',
                                           'productionActivated', 'androidRuntimeQualified')}, sort_keys=True))


if __name__ == '__main__': main()
