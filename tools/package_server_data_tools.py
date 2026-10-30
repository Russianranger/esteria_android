#!/usr/bin/env python3
"""Compose four data tools from two ordered derivatives and two unchanged tools.

Actual ordered source output pins are mandatory. Only the new ordered pair is
stripped; its debug companion stays outside the runtime archive. Native CLI,
custom data conversion and Android execution remain separate qualifications.
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

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import package_server_engine as engine, package_server_content as transaction
from tools import prepare_runtime as archives, provider_server_extractors as stock
from tools import provider_server_data_tools as provider, seal_ordered_extractor_sources as sources
from tools import verify_server_build as files

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = ('map_extractor', 'vmap4_extractor', 'vmap4_assembler', 'mmaps_generator')
ORDERED = PROGRAMS[:2]
STOCK = PROGRAMS[2:]
CONFIG = 'etc/mmaps-config.yaml'
RUNTIME = 'server-data-tools-runtime-arm64.tar.gz'
DEBUG = 'ordered-extractors-debug-arm64.tar.gz'
STRIP_RECEIPT = 'ordered-strip-receipt.json'
PACKAGE_RECEIPT = 'package-receipt.json'
SOURCE_ARCHIVE = sources.SOURCE_ARCHIVE
SOURCE_RECEIPT = sources.RECEIPT
INTEGRATION_LICENSE = dict(bytes=35149, sha256='3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986')
FALSE_FLAGS = ('clientMpqConversionQualified', 'customEsteriaDataLoadOrderQualified',
               'androidRuntimeQualified', 'gameLoginQualified', 'gameplayQualified')
require = files.require
identity = engine.identity


def verify_ordered_sources(directory, selected, measured, qualified, qualified_identity):
    """Authenticate the real source output before interpreting its positive flags."""
    anchor = selected['actualOrderedSourceQualification']
    require(set(anchor) == {'archive', 'receipt', 'nativeBuild', 'dependencyObservation'} and
            anchor['nativeBuild'] == qualified_identity == measured['nativeBuild']['receipt'] and
            anchor['dependencyObservation'] == measured['nativeBuild']['dependencyObservation'],
            'data-tools-immutable-source-output-anchor-required')
    require({p.relative_to(directory).as_posix() for p in files.installed_files(directory)} ==
            {SOURCE_ARCHIVE, SOURCE_RECEIPT}, 'data-tools-ordered-source-file-set')
    for name, row in ((SOURCE_ARCHIVE, anchor['archive']), (SOURCE_RECEIPT, anchor['receipt'])):
        require(files.identity(directory/name) == identity(row), 'data-tools-ordered-source-anchor-changed')
    sealed, sealed_identity = sources.read_json(directory/SOURCE_RECEIPT)
    require(sealed.get('formatVersion') == 1 and
            sealed.get('scope') == 'complete-ordered-extractor-corresponding-source-companion' and
            all(sealed.get(k) is True for k in ('archiveReadbackVerified', 'orderedSourceCompanionComplete',
                'originalNativeReceiptUnchanged', 'fullBaseAndApprovedOverlayVerified',
                'actualTargetDependencyObservationVerified', 'integrationRecipesAllReadFromNativeGitBlobs')) and
            all(sealed.get(k) is False for k in ('newNativeCompilationPerformed', 'globalServerPatchListChanged',
                'serverProgramsReplaced', 'worldQualified', 'androidRuntimeQualified', 'clientMpqConversionQualified',
                'customEsteriaDataLoadOrderQualified', 'gameplayQualified', 'originalNativeSourceCompanionComplete')),
            'data-tools-real-ordered-source-seal-required')
    require(sealed.get('inputLock') == files.identity(sources.LOCK) and sealed.get('nativeBuild') == measured['nativeBuild'] and
            sealed.get('nativeReceipt') == anchor['nativeBuild'] and
            sealed.get('dependencyObservation') == anchor['dependencyObservation'] and
            sealed.get('serverBuildSourceLock') == measured['serverBuildSourceLock'] == selected['serverBuildSourceLock'] and
            sealed.get('originalSourceQualification') == measured['originalSourceQualification'] == selected['originalServerSourceQualification'] and
            sealed.get('adaptationLock') == measured['adaptationLock'] and
            sealed.get('sourceInputArchive') == qualified['sourceInputArchive'] and
            sealed.get('sourceInputReceipt') == qualified['sourceInputReceipt'] and
            sealed.get('archive') == dict(file=SOURCE_ARCHIVE, **identity(anchor['archive'])),
            'data-tools-ordered-source-native-or-original-binding')
    rows = sealed['archiveFiles']
    stock.shared.validate_inventory(rows, sources.MAX_FILES, sources.MAX_MEMBER, sources.MAX_EXPANDED)
    require(all(row['mode'] == 0o444 for row in rows.values()), 'data-tools-source-member-mode')
    critical = {'ordered/ordered-build.json': qualified_identity,
        'ordered/build/dependency-observation/observation.json': anchor['dependencyObservation'],
        'original/'+sources.ORIGINAL_ARCHIVE: measured['originalSourceQualification']['archive'],
        'original/qualification.json': measured['originalSourceQualification']['qualification'],
        'original/sealed-source-receipt.json': measured['originalSourceQualification']['receipt'],
        'source-coverage.json': sealed['sourceCoverage'], 'replay-plan.json': sealed['replayPlan'],
        'prepare-replay.py': sealed['replayPreparationScript']}
    critical.update({'ordered/'+name: identity(row) for name, row in qualified['payloadFiles'].items()
                     if not name.startswith('bin/')})
    critical.update(sealed['sealingRecipes']['files'])
    require(all(name in rows and identity(rows[name]) == identity(row) for name, row in critical.items()) and
            not any(name.startswith('ordered/bin/') for name in rows), 'data-tools-source-archive-retained-bindings')
    engine.verify_archive(directory/SOURCE_ARCHIVE, rows)
    return sealed, sealed_identity


def verify_stock_package(directory, selected):
    require(files.identity(directory/PACKAGE_RECEIPT) == selected['packageReceipt'],
            'data-tools-stock-package-receipt-changed')
    receipt, receipt_identity = sources.read_json(directory/PACKAGE_RECEIPT)
    derivative = stock.validate_package(receipt, selected)
    archive = directory/selected['archive']['file']
    stock.verify_archive(archive, selected, derivative)
    require(len(receipt['notices']) == 66 and all(identity(selected['files'][name]) == identity(row)
                for name, row in receipt['notices'].items()), 'data-tools-all-original-notices-required')
    return receipt, receipt_identity, archive


def extract_stock(archive, directory, selected):
    """Extract already authenticated stock files; never use legacy app-lock checks."""
    rows = selected['files']; seen = set()
    with files.plain_file(archive) as raw, archives.bounded_tar(raw, stock.LIMITS) as incoming:
        for member in incoming:
            require(member.isfile() and member.name in rows and member.name not in seen,
                    'data-tools-stock-member-set')
            row = rows[member.name]
            require(member.size == row['bytes'] and member.mode == row['mode'] and
                    member.uid == member.gid == member.mtime == 0 and not member.uname and not member.gname,
                    'data-tools-stock-member-metadata')
            target = directory/member.name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with incoming.extractfile(member) as source, target.open('xb') as output:
                require(archives.hash_stream(source, member.size, output) == row['sha256'], 'data-tools-stock-member-sha256')
                output.flush(); os.fsync(output.fileno())
            target.chmod(row['mode']); seen.add(member.name); incoming.members.clear()
    require(seen == set(rows), 'data-tools-stock-members-missing')


def recipe_files(root=ROOT):
    """Retain current public Python closure and input JSON; no repository metadata."""
    raw = subprocess.check_output(['git', 'ls-files', '-z', '--', 'tools', 'runtime'], cwd=root,
        env=dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_OPTIONAL_LOCKS='0'), stderr=subprocess.PIPE, timeout=30)
    require(len(raw) <= 4 << 20, 'data-tools-creation-recipe-list-bound')
    names = {name for name in raw.decode().split('\0') if name and
             not name.startswith('runtime/evidence/') and Path(name).suffix in ('.py', '.json')}
    names.update(('tools/package_server_data_tools.py', 'tests/test_package_server_data_tools.py',
        'tools/provider_server_data_tools.py', 'tools/seal_ordered_extractor_sources.py',
        'tools/prepare_ordered_extractor_sources.py', 'tools/verify_target_dependency_observation.py',
        'tests/test_server_engine_elf.py', 'tests/test_ordered_extractor_sources.py',
        'tests/test_target_dependency_observation.py', 'runtime/server/ordered-tools-inputs.lock.json',
        'runtime/server/data-tools-provider.lock.json', 'sources.lock.json', 'LICENSE'))
    require(0 < len(names) <= 3000, 'data-tools-creation-recipe-count-bound')
    result = {}
    for name in sorted(names):
        engine.content.safe_path(name); path = Path(root)/name
        row = files.identity(path); require(row['bytes'] <= 16 << 20, 'data-tools-creation-recipe-file-bound')
        result[name] = (path, row)
    return result


def tool_selection(selected, runtime, source_identity):
    names = {'bin/'+name for name in PROGRAMS} | {CONFIG, 'provenance/'+SOURCE_RECEIPT}
    require(all((runtime/name).is_file() for name in names), 'data-tools-fixed-six-file-selection-missing')
    rows = {name: files.identity(runtime/name) for name in sorted(names)}
    require(rows['provenance/'+SOURCE_RECEIPT] == source_identity and
            rows[CONFIG] == identity(selected['configuration']), 'data-tools-source-receipt-or-yaml-selection')
    return dict(formatVersion=1, serverRevision=selected['serverRevision'], clientRevision=selected['clientRevision'],
                orderedSourceReceipt=source_identity, files=rows)


def copy_stock_runtime(stock_tree, runtime, debug, selected):
    names = {'bin/'+name for name in STOCK} | {CONFIG} | set(selected['noticeFiles']) | stock.PROVENANCE
    require(len(selected['noticeFiles']) == 66 and {n for n in selected['files'] if n.startswith('notices/')} ==
            set(selected['noticeFiles']), 'data-tools-stock-notice-file-set')
    for name in sorted(names):
        row = identity(selected['files'][name]); source = stock_tree/name
        if name in stock.PROVENANCE:
            target = 'provenance/stock/'+name[len('provenance/'):]
            engine.copy_verified(source, runtime/target, row)
            engine.copy_verified(source, debug/target, row)
        else:
            engine.copy_verified(source, runtime/name, row, 0o555 if name.startswith('bin/') else 0o444)
            if name.startswith('notices/'):
                engine.copy_verified(source, debug/name, row)


def derive_ordered(payload, runtime, debug, objcopy, tool, expected_programs):
    require(set(expected_programs) == set(ORDERED) and all(files.identity(payload/'bin'/name) == identity(expected_programs[name])
                for name in ORDERED), 'data-tools-exact-ordered-pair-selection')
    pairs = {}
    for name in ORDERED:
        pair = engine.elf.derive(payload/'bin'/name, runtime/'bin'/name, debug/'symbols'/(name+'.debug'), objcopy, tool)
        require(pair['original'] == identity(expected_programs[name]), 'data-tools-ordered-original-changed-during-derivation')
        pairs[name] = pair
    return pairs


def build(ordered_payload, ordered_sources, stock_package, ndk_archive, objcopy, output):
    # The provider source-only intermediate state is an immutable output anchor;
    # it still refuses a production provider until the later native CLI gate.
    selected = provider.load_source_qualification()
    measured = sources.load_pin(); original = stock.load_pin(sealed=True)
    roots = [archives.directory(Path(os.path.abspath(path))) for path in (ordered_payload, ordered_sources, stock_package)]
    payload, complete_sources, stock_package = roots
    output = Path(os.path.abspath(output)); ndk_archive = Path(os.path.abspath(ndk_archive)); objcopy = Path(os.path.abspath(objcopy))
    require(not os.path.lexists(output) and all(output != p and p not in output.parents and output not in p.parents
                for p in roots) and not any(output in p.parents for p in (ndk_archive, objcopy)),
            'data-tools-output-exists-or-overlaps-input')
    archives.directory(output.parent, create=True)
    q, qid, payload_rows = sources.verify_native(payload, measured)
    sealed, sid = verify_ordered_sources(complete_sources, selected, measured, q, qid)
    stock_receipt, stock_id, stock_archive = verify_stock_package(stock_package, original)
    strip_lock, _ = sources.read_json(engine.elf.TOOL_LOCK)
    tool = engine.elf.verify_tool(ndk_archive, objcopy, strip_lock['ndkArchive'])
    recipe_inputs = recipe_files(ROOT)
    require(files.identity(ROOT/'LICENSE') == INTEGRATION_LICENSE, 'data-tools-integration-license-changed')
    stage = Path(tempfile.mkdtemp(prefix='.'+output.name+'.stage-', dir=output.parent))
    try:
        runtime, debug, stock_tree = stage/'runtime', stage/'debug', stage/'stock'
        (runtime/'bin').mkdir(parents=True, mode=0o700); (debug/'symbols').mkdir(parents=True, mode=0o700)
        extract_stock(stock_archive, stock_tree, original)
        copy_stock_runtime(stock_tree, runtime, debug, original)
        for directory in (runtime, debug):
            engine.copy_verified(ROOT/'LICENSE', directory/'notices/integration/LICENSE', INTEGRATION_LICENSE)
        pairs = derive_ordered(payload, runtime, debug, objcopy, tool, measured['nativeBuild']['programs'])
        program_pairs = {name: {key: pair[key] for key in ('original', 'stripped', 'debug')} for name, pair in pairs.items()}
        program_pairs.update({name: original['programPairs'][name] for name in STOCK})
        retained = {'native-ordered-build.json': (payload/'ordered-build.json', qid),
            SOURCE_RECEIPT: (complete_sources/SOURCE_RECEIPT, sid),
            'dependency-observation.json': (payload/'build/dependency-observation/observation.json', measured['nativeBuild']['dependencyObservation']),
            'stock-package-receipt.json': (stock_package/PACKAGE_RECEIPT, stock_id)}
        for name, (path, row) in retained.items():
            directories = (stage, debug/'provenance') if name == 'dependency-observation.json' else \
                (stage, runtime/'provenance', debug/'provenance')
            for directory in directories:
                engine.copy_verified(path, directory/name, row)
        engine.copy_verified(complete_sources/SOURCE_ARCHIVE, stage/SOURCE_ARCHIVE, selected['actualOrderedSourceQualification']['archive'])
        recipe_inventory = {}
        for name, (path, row) in recipe_inputs.items():
            engine.copy_verified(path, debug/'recipes'/name, row); recipe_inventory[name] = row
        creation_revision = os.environ.get('GITHUB_SHA')
        require(creation_revision is None or re.fullmatch('[0-9a-f]{40}', creation_revision),
                'data-tools-creation-integration-revision')
        creation = dict(formatVersion=1, scope='current-data-tools-packaging-recipes', files=recipe_inventory,
            creationIntegrationRevision=creation_revision, claimedToBeNativeBuildGitRecipes=False)
        engine.put_metadata(debug/'provenance/packaging-recipes.json', creation)
        # This archive has no strip receipt: that receipt inventories this
        # completed archive and is retained outside it, avoiding self-reference.
        debug_inventory = engine.write_archive(debug, stage/DEBUG)
        require({name for name in debug_inventory if name.startswith('symbols/')} ==
                {'symbols/'+name+'.debug' for name in ORDERED} and all(
                    identity(debug_inventory['symbols/'+name+'.debug']) == pair['debug'] for name, pair in pairs.items()) and
                'provenance/'+STRIP_RECEIPT not in debug_inventory and
                all(debug_inventory[name] == original['files'][name] for name in original['noticeFiles']) and
                identity(debug_inventory['notices/integration/LICENSE']) == INTEGRATION_LICENSE,
                'data-tools-debug-pair-notices-or-receipt-cycle')
        strip = dict(formatVersion=1, scope='paired-linux-arm64-ordered-extractor-derivative',
            originalNativeBuild=qid, dependencyObservation=measured['nativeBuild']['dependencyObservation'],
            orderedSourceReceipt=sid, originalSourceQualification=measured['originalSourceQualification'],
            sourceLock=measured['serverBuildSourceLock'], programs=pairs, stripTool=tool,
            debugArchive=dict(file=DEBUG, **files.identity(stage/DEBUG)), debugInventory=debug_inventory,
            archiveReadbackVerified=True, originalNativeReceiptsPreserved=True,
            derivedProgramsExecuted=False, nativeArgumentConfigQualified=False, sourceCompanionComplete=False,
            **{key: False for key in FALSE_FLAGS})
        engine.put_metadata(stage/STRIP_RECEIPT, strip)
        engine.copy_verified(stage/STRIP_RECEIPT, runtime/'provenance'/STRIP_RECEIPT, files.identity(stage/STRIP_RECEIPT))
        selection = tool_selection(selected, runtime, sid)
        runtime_inventory = engine.write_archive(runtime, stage/RUNTIME)
        require({name for name in runtime_inventory if name.startswith('bin/')} == {'bin/'+name for name in PROGRAMS} and
                all(identity(runtime_inventory['bin/'+name]) == program_pairs[name]['stripped'] for name in PROGRAMS) and
                all(runtime_inventory[name] == original['files'][name] for name in original['noticeFiles']) and
                identity(runtime_inventory['notices/integration/LICENSE']) == INTEGRATION_LICENSE and
                identity(runtime_inventory[CONFIG]) == identity(original['configuration']),
                'data-tools-composed-runtime-program-notice-or-yaml-binding')
        provider.shared.validate_inventory(runtime_inventory, provider.LIMITS['entries'],
            provider.LIMITS['memberBytes'], provider.LIMITS['fileBytes'])
        # Final input checks use the original immutable anchors, never identities
        # re-derived from changed inputs at the end of the transaction.
        sources.check_inventory(payload, q['payloadFiles'], extra=('ordered-build.json',))
        require(files.identity(payload/'ordered-build.json') == qid and
                files.identity(complete_sources/SOURCE_RECEIPT) == sid and
                files.identity(complete_sources/SOURCE_ARCHIVE) == identity(selected['actualOrderedSourceQualification']['archive']) and
                files.identity(stock_package/PACKAGE_RECEIPT) == stock_id and
                files.identity(stock_archive) == identity(original['archive']) and
                all(files.identity(path) == row for path, row in recipe_inputs.values()) and
                files.identity(objcopy) == tool['executable'] and files.identity(ndk_archive) == tool['ndkArchive'],
                'data-tools-input-changed-before-publication')
        engine.verify_archive(stage/DEBUG, debug_inventory); engine.verify_archive(stage/RUNTIME, runtime_inventory)
        receipt = dict(formatVersion=1, scope='composed-linux-arm64-server-data-tools-runtime',
            archive=dict(file=RUNTIME, **files.identity(stage/RUNTIME)), archiveFiles=runtime_inventory,
            archiveEntries=len(runtime_inventory), archiveFileBytes=sum(r['bytes'] for r in runtime_inventory.values()),
            toolSelection=selection, programPairs=program_pairs, orderedSourceReceipt=sid,
            actualOrderedSourceQualification=selected['actualOrderedSourceQualification'],
            originalStockPackageReceipt=stock_id, originalStockRuntimeArchive=original['archive'],
            originalServerSourceQualification=original['sourceQualification'],
            orderedStripReceipt=files.identity(stage/STRIP_RECEIPT), orderedDebugArchive=strip['debugArchive'],
            stockDebugArchiveRequired=original['debugArchive'], stockDebugArchiveReadbackPerformed=False,
            originalNoticesPreserved=True, originalNoticeFiles=66, originalStockProgramsUnchanged=True,
            integrationNoticeFiles={'notices/integration/LICENSE': INTEGRATION_LICENSE},
            originalDefaultMmapsConfigurationUnchanged=True, archiveReadbackVerified=True,
            packagingRecipes=creation, orderedSourceCompanionVerified=True,
            sourceCompanionComplete=False, nativeArgumentConfigQualified=False, derivedProgramsExecuted=False,
            androidProviderCreated=False, **{key: False for key in FALSE_FLAGS})
        engine.put_metadata(stage/PACKAGE_RECEIPT, receipt)
        for directory in (runtime, debug, stock_tree): shutil.rmtree(directory)
        archives.sync_directory(stage); transaction.publish_directory(stage, output); archives.sync_directory(output.parent)
        return receipt
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('ordered-payload', 'ordered-sources', 'stock-package', 'ndk-archive', 'objcopy', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.ordered_payload, args.ordered_sources, args.stock_package,
                           args.ndk_archive, args.objcopy, args.output), sort_keys=True, indent=2))


if __name__ == '__main__': main()
