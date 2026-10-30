#!/usr/bin/env python3
"""Prepare verified source inputs for an offline, Git-free isolated rebuild.

This replays the selected source patches and separates a provenance-bound build
metadata adaptation. Preparation does not qualify source closure or a rebuild.
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
from tools import fetch_sources, manifest_server_content as content, manifest_server_modules as modules
from tools import package_server_content as package, package_server_engine_source_inputs as inputs
from tools import prepare_runtime as archives, verify_server_build as files
from tools import prepare_server_isolated_build as build_inputs

ROOT = Path(__file__).resolve().parents[1]
CURRENT_LOCK = ROOT / 'sources.lock.json'
MAX_ARCHIVE = 64 * 1024**2
MAX_PAYLOAD = 256 * 1024**2
MAX_FILES = 10000
ASSET_SUFFIXES = {'.mpq', '.dbc', '.blp', '.m2', '.wmo', '.wdt', '.adt', '.vmap', '.vmtree', '.vmtile', '.mmap', '.mmtile'}
require = files.require


def identity(row):
    require(type(row.get('bytes')) is int and 0 <= row['bytes'] <= MAX_PAYLOAD and
            re.fullmatch('[a-f0-9]{64}', row.get('sha256', '')), 'isolated-source-identity-contract')
    return {key: row[key] for key in ('bytes', 'sha256')}


def write_new(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    path.chmod(mode)


def extract_verified(archive, inventory, stage):
    """Extract only the hash-listed plain files; the generic tar parser is bounded."""
    require(isinstance(inventory, dict) and 1 <= len(inventory) <= MAX_FILES,
            'isolated-source-inventory-count-bound')
    total = 0
    for name, row in inventory.items():
        content.safe_path(name); identity(row); total += row['bytes']
        require(not any(part == '.git' for part in Path(name).parts), 'git-metadata-not-allowed')
        require(Path(name).suffix.lower() not in ASSET_SUFFIXES, 'game-asset-not-allowed')
        require(name.startswith(('source/', 'integration/', 'adapted-source/', 'external/', 'metadata/', 'packaging-recipes/')),
                'unknown-isolated-source-archive-root')
    require(total <= MAX_PAYLOAD, 'isolated-source-payload-bound')
    seen = set()
    with files.plain_file(archive) as raw, archives.bounded_tar(raw,
            dict(entries=MAX_FILES, pathBytes=4096, fileBytes=MAX_PAYLOAD)) as tar:
        for item in tar:
            require(item.isfile() and item.name in inventory and item.name not in seen,
                    'isolated-source-member-set')
            row = inventory[item.name]
            require(item.mode == 0o644 and item.uid == item.gid == item.mtime == 0 and
                    not item.uname and not item.gname and item.size == row['bytes'],
                    'isolated-source-member-metadata')
            name = item.name if item.name.startswith(('source/', 'integration/')) else 'provenance/' + item.name
            target = stage / name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tar.extractfile(item) as source, target.open('xb') as output:
                digest = archives.hash_stream(source, item.size, output)
                output.flush(); os.fsync(output.fileno())
            require(digest == row['sha256'], 'isolated-source-member-sha256')
            seen.add(item.name)
    require(seen == set(inventory), 'isolated-source-archive-incomplete')


def check_blob(path, expected):
    actual = inputs.local_identity(path, MAX_PAYLOAD)
    require(all(actual[key] == expected[key] for key in ('bytes', 'sha256', 'gitBlob')),
            'isolated-source-git-blob-mismatch')
    return actual


def validate_tree(stage, receipt):
    manifest, manifest_identity = modules.read_json(stage / 'provenance/metadata/source-inputs.json', limit=8*1024**2)
    require(manifest_identity == receipt.get('manifest') and manifest.get('formatVersion') == 1 and
            manifest.get('scope') == 'unsealed-engine-source-input-preservation', 'isolated-source-manifest-mismatch')
    lock = fetch_sources.load_lock(CURRENT_LOCK); current_identity = files.identity(CURRENT_LOCK)
    require(manifest.get('sourceLock') == receipt.get('sourceLock') == current_identity and
            manifest.get('source') == lock['sources']['server'],
            'isolated-source-current-lock-mismatch')
    require(files.identity(stage / 'integration/sources.lock.json') == current_identity,
            'isolated-source-original-integration-lock-mismatch')
    for flag in ('sourceCompanionComplete', 'isolatedSourceRebuildQualified', 'transitiveIncludeClosureProved',
                 'androidRuntimeQualified', 'gameplayQualified'):
        require(manifest.get(flag) is False and receipt.get(flag) is False, 'unsealed-source-flags-required:' + flag)
    build, build_identity = modules.read_json(stage / 'provenance/metadata/server-build.json')
    compiled, compiled_identity = modules.read_json(stage / 'provenance/metadata/server-modules.json')
    require(build_identity == manifest.get('originalBuild') == receipt.get('originalBuild') and
            compiled_identity == manifest.get('originalCompiledModules') == receipt.get('originalCompiledModules') and
            build.get('sourcesLock') == current_identity and build.get('serverSource') == manifest['source'] and
            build.get('integrationRevision') == manifest.get('originalIntegrationRevision') and
            build.get('sourceCheckoutAndPatchesVerified') is True and
            compiled.get('scope') == 'compiled-server-module-selection' and
            compiled.get('generatedListsMatchInstalledBinaries') is True and
            compiled.get('enabledModules') == manifest.get('enabledModules') and
            compiled.get('serverBuild') == build_identity and compiled.get('source') == manifest['source'] and
            compiled.get('sourceLockSha256') == current_identity['sha256'], 'isolated-source-build-provenance-mismatch')
    require(files.identity(stage / 'provenance/metadata/compile_commands.json') == manifest.get('compileCommands') ==
            compiled.get('compileCommands'), 'isolated-source-compile-commands-mismatch')
    require(manifest.get('sourceAdaptations') == content.adaptation_records(manifest['source']),
            'isolated-source-semantic-patch-records-mismatch')
    selection, selection_identity = inputs.rules()
    require(manifest.get('selectionRules') == selection and manifest.get('sourceSelectionAudit') == selection_identity,
            'isolated-source-reviewed-selection-rules-changed')
    objects = {}
    for origin, rows in manifest['pristineGitFiles'].items():
        objects[origin] = type('RecordedGitFiles', (), {'files': {
            name: dict(kind='blob', mode=row['gitMode']) for name, row in rows.items()}})()
    require(set(inputs.select_server(objects['server'], manifest['enabledModules'], selection)) ==
            set(manifest['pristineGitFiles']['server']), 'isolated-source-unselected-server-file')
    require(set(inputs.select_integration(objects['integration'], [row['path'] for row in manifest['source']['patches']])) ==
            set(manifest['pristineGitFiles']['integration']), 'isolated-source-unselected-integration-file')
    selected = set(); counts = {}
    for origin, rows in manifest['pristineGitFiles'].items():
        require(origin in ('server', 'eluna', 'integration') and isinstance(rows, dict), 'isolated-source-git-origin')
        counts[origin] = dict(files=len(rows), bytes=0, executableFiles=0)
        for name, row in rows.items():
            content.safe_path(name)
            require(row.get('gitMode') in ('100644', '100755'), 'isolated-source-git-mode')
            relative = ('integration/' if origin == 'integration' else 'source/' +
                (content.ELUNA + '/' if origin == 'eluna' else '')) + name
            check_blob(stage / relative, row)
            mode = 0o755 if row['gitMode'] == '100755' else 0o644
            (stage / relative).chmod(mode)
            counts[origin]['bytes'] += row['bytes']; counts[origin]['executableFiles'] += mode == 0o755
            if origin != 'integration': selected.add((content.ELUNA + '/' if origin == 'eluna' else '') + name)
    require(set(manifest['pristineGitFiles']) == {'server', 'eluna', 'integration'}, 'isolated-source-origins-incomplete')
    for name, row in manifest['localInputs'].items():
        content.safe_path(name)
        require(files.identity(stage / 'provenance' / name) == identity(row), 'isolated-source-local-input-mismatch')
    coverage = inputs.compiler_coverage(stage / 'provenance/metadata/compile_commands.json', selected)
    require(coverage == manifest.get('compilerCoverage'), 'isolated-source-compiler-coverage-changed')
    return manifest, build, counts, selected


def replay_patches(stage, manifest, selected):
    """Use real patch text, without a Git repository or an index, then compare copies."""
    expected = {}
    for row in manifest['adaptedFiles']:
        name = row['path']; content.safe_path(name)
        require(name in selected and name not in expected and row['origin'] in ('server', 'eluna'),
                'isolated-source-adapted-path-contract')
        original_name = name[len(content.ELUNA)+1:] if row['origin'] == 'eluna' else name
        require(row['pristine'] == manifest['pristineGitFiles'][row['origin']][original_name],
                'isolated-source-pristine-adapted-association')
        check_blob(stage / 'source' / name, row['pristine'])
        check_blob(stage / 'provenance/adapted-source' / name, row['adapted'])
        expected[name] = row['adapted']
    executed = []
    environment = dict(os.environ, GIT_CEILING_DIRECTORIES=str(stage), GIT_OPTIONAL_LOCKS='0')
    for row in manifest['source']['patches']:
        path = stage / 'integration' / row['path']
        require(files.identity(path)['sha256'] == row['sha256'], 'isolated-source-patch-identity')
        scope = row.get('submodule')
        require(scope in (None, content.ELUNA), 'isolated-source-patch-scope')
        cwd = stage / 'source' / scope if scope else stage / 'source'
        for check in (True, False):
            args = ['git', 'apply', '--no-index'] + (['--check'] if check else []) + [str(path)]
            result = subprocess.run(args, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
            require(len(result.stdout) <= 65536 and result.returncode == 0, 'isolated-source-semantic-patch-replay-failed:' + path.name)
        executed.append(dict(path=row['path'], sha256=row['sha256'], submodule=scope, appliedWithoutGitIndex=True))
    for origin in ('server', 'eluna'):
        for name, row in manifest['pristineGitFiles'][origin].items():
            relative = (content.ELUNA + '/' if origin == 'eluna' else '') + name
            check_blob(stage / 'source' / relative, expected.get(relative, row))
    actual = {path.relative_to(stage / 'source').as_posix() for path in files.installed_files(stage / 'source')}
    require(actual == selected, 'isolated-source-patch-created-unlisted-file')
    require(not any(path.name == '.git' for path in stage.rglob('.git')), 'isolated-source-git-metadata-created')
    return dict(patches=executed, exactAdaptedCopiesReproduced=True, adaptedFiles=len(expected),
                pristineUnadaptedFilesPreserved=True, gitMetadataCreated=False)


def extract_lua(stage):
    archive = stage / 'provenance/external/lua-5.2.4.tar.gz'
    pin = files.identity(archive)
    require(pin['sha256'] == inputs.LUA_SHA256 and pin['bytes'] <= inputs.LUA_MAX_BYTES,
            'isolated-source-original-lua-required')
    seen = set(); total = 0
    with files.plain_file(archive) as raw, archives.bounded_tar(raw,
            dict(entries=512, pathBytes=512, fileBytes=8*1024**2)) as tar:
        for item in tar:
            content.safe_path(item.name.rstrip('/'))
            require(item.name.split('/')[0] == 'lua-5.2.4' and item.name not in seen,
                    'isolated-lua-path-contract')
            seen.add(item.name)
            target = stage / 'external' / item.name
            if item.isdir(): target.mkdir(parents=True, exist_ok=True, mode=0o700); continue
            require(item.isfile() and item.size <= 2*1024**2, 'isolated-lua-regular-file-required')
            total += item.size; require(total <= 8*1024**2, 'isolated-lua-payload-bound')
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tar.extractfile(item) as incoming, target.open('xb') as outgoing:
                archives.hash_stream(incoming, item.size, outgoing)
            target.chmod(0o755 if item.mode & 0o111 else 0o644)
    require((stage / 'external/lua-5.2.4/src/lua.h').is_file() and
            (stage / 'external/lua-5.2.4/README').is_file(), 'isolated-lua-source-incomplete')
    return dict(originalArchive=pin, root='external/lua-5.2.4', entries=len(seen), fileBytes=total, fetched=False)


def archival_revision(build):
    smoke = build.get('hostLoaderSmoke', {})
    outputs = smoke.get('outputs', {})
    require(smoke.get('qualified') is True and set(outputs) == {'authserver', 'worldserver'} and
            outputs['authserver'] == outputs['worldserver'], 'recorded-engine-version-output-required')
    pattern = (r'AzerothCore rev\. ([0-9a-f]{12}\+?) (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4}) '
               r'\(([^()\r\n]+) branch\) \(Unix, RelWithDebInfo, Static\)')
    match = re.fullmatch(pattern, outputs['authserver'])
    require(match is not None and build['serverSource']['commit'].startswith(match[1].rstrip('+')),
            'recorded-engine-version-source-mismatch')
    return dict(hash=match[1], date=match[2], branch='Archived source package', year=match[2][:4],
                originalRecordedBranch=match[3], derivedFrom='original-server-build-hostLoaderSmoke')


def adapt_revision(stage, build):
    revision = archival_revision(build)
    revision_file = stage / 'provenance/archival-revision.txt'
    write_new(revision_file, ('\n'.join(revision[key] for key in ('hash', 'date', 'branch', 'year')) + '\n').encode())
    guard = '''# Isolated source-export metadata only; original Git recipe follows unchanged.
if(DEFINED ESTERIA_ARCHIVAL_REVISION_FILE AND NOT "${ESTERIA_ARCHIVAL_REVISION_FILE}" STREQUAL "")
  if(NOT EXISTS "${ESTERIA_ARCHIVAL_REVISION_FILE}")
    message(FATAL_ERROR "Recorded archival revision file is missing")
  endif()
  file(STRINGS "${ESTERIA_ARCHIVAL_REVISION_FILE}" _esteria_archival ENCODING UTF-8)
  list(LENGTH _esteria_archival _esteria_archival_length)
  if(NOT _esteria_archival_length EQUAL 4)
    message(FATAL_ERROR "Invalid recorded archival revision")
  endif()
  list(GET _esteria_archival 0 rev_hash)
  list(GET _esteria_archival 1 rev_date)
  list(GET _esteria_archival 2 rev_branch)
  list(GET _esteria_archival 3 rev_year)
  if(NOT "${rev_hash}" STREQUAL "@HASH@" OR NOT "${rev_date}" STREQUAL "@DATE@" OR
     NOT "${rev_branch}" STREQUAL "Archived source package" OR NOT "${rev_year}" STREQUAL "@YEAR@")
    message(FATAL_ERROR "Archival revision differs from original build provenance")
  endif()
  if(NOT BUILDDIR)
    set(BUILDDIR "${CMAKE_BINARY_DIR}")
  endif()
  configure_file("${CMAKE_SOURCE_DIR}/src/cmake/revision.h.in.cmake" "${BUILDDIR}/revision.h" @ONLY)
  set(rev_hash_cached "${rev_hash}" CACHE INTERNAL "Cached commit-hash")
  set(rev_branch_cached "${rev_branch}" CACHE INTERNAL "Cached branch name")
  return()
endif()

'''.replace('@HASH@', revision['hash']).replace('@DATE@', revision['date']).replace('@YEAR@', revision['year'])
    names = ('src/cmake/genrev.cmake', 'src/genrev/CMakeLists.txt')
    changed = []
    for name in names:
        path = stage / 'source' / name; original = path.read_bytes()
        write_new(stage / 'provenance/source-export-adaptations' / name, original)
        if name == names[0]:
            require(b'ESTERIA_ARCHIVAL_REVISION_FILE' not in original and b'configure_file(' in original,
                    'original-genrev-contract-changed')
            updated = guard.encode() + original
        else:
            old = b'COMMAND "${CMAKE_COMMAND}" -DBUILDDIR="${CMAKE_BINARY_DIR}" -P '
            require(original.count(old) == 1, 'original-genrev-build-target-contract-changed')
            updated = original.replace(old, b'COMMAND "${CMAKE_COMMAND}" -DBUILDDIR="${CMAKE_BINARY_DIR}" '
                b'-DESTERIA_ARCHIVAL_REVISION_FILE="${ESTERIA_ARCHIVAL_REVISION_FILE}" -P ')
        path.write_bytes(updated)
        changed.append(dict(path=name, original=dict(bytes=len(original), sha256=hashlib.sha256(original).hexdigest()),
            prepared=files.identity(path), purpose='source-export-revision-metadata-only'))
    return dict(recordedRevision=revision, file='provenance/archival-revision.txt', identity=files.identity(revision_file),
                buildMetadataAdaptations=changed, semanticPatchSetChanged=False, fabricatedGitMetadata=False)


def add_supplements(stage, directory, manifest):
    expected=build_inputs.load_pin()['sourceSupplements']
    directory=archives.directory(Path(os.path.abspath(directory)))
    require({p.relative_to(directory).as_posix() for p in files.installed_files(directory)}==set(expected),
            'isolated-source-supplement-file-set')
    for name,row in expected.items():
        require(row['sourceCommit']==manifest['source']['commit'] and name.endswith('.h'),
                'isolated-source-supplement-source')
        source=directory/name;check_blob(source,row)
        require(not os.path.lexists(stage/'source'/name),'isolated-source-supplement-overwrite')
        raw=source.read_bytes()
        write_new(stage/'source'/name,raw)
        write_new(stage/'provenance/source-supplements'/name,raw,0o444)
    return expected


def prepare(source_inputs, output, supplements=None):
    source_inputs = archives.directory(Path(os.path.abspath(source_inputs)))
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and source_inputs not in output.parents and output not in source_inputs.parents,
            'isolated-source-output-exists-or-overlaps-input')
    receipt, receipt_identity = modules.read_json(source_inputs / 'source-inputs-receipt.json', limit=8*1024**2)
    require(receipt.get('formatVersion') == 1 and receipt.get('scope') == 'unsealed-engine-source-input-package' and
            receipt.get('completeArchiveReadbackVerified') is True and
            receipt.get('archive', {}).get('file') == 'server-engine-source-inputs.tar.gz',
            'verified-unsealed-source-input-receipt-required')
    archive = source_inputs / 'server-engine-source-inputs.tar.gz'
    archive_identity = files.identity(archive)
    require(archive_identity == identity(receipt['archive']) and archive_identity['bytes'] <= MAX_ARCHIVE,
            'isolated-source-archive-identity-mismatch')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        extract_verified(archive, receipt['archiveFiles'], stage)
        manifest, build, counts, selected = validate_tree(stage, receipt)
        patches = replay_patches(stage, manifest, selected)
        supplemental=add_supplements(stage,supplements,manifest) if supplements is not None else {}
        lua = extract_lua(stage); revision = adapt_revision(stage, build)
        require(files.identity(source_inputs / 'source-inputs-receipt.json') == receipt_identity and
                files.identity(archive) == archive_identity, 'isolated-source-input-changed-during-preparation')
        result = dict(formatVersion=1, scope='isolated-server-source-preparation-only',
            sourceInputReceipt=receipt_identity, sourceInputArchive=archive_identity, sourceManifest=receipt['manifest'],
            sourceLock=manifest['sourceLock'], originalBuild=manifest['originalBuild'],
            originalCompiledModules=manifest['originalCompiledModules'], compileCommands=manifest['compileCommands'],
            pristineInputCounts=counts, selectedSourceFiles=len(selected)+len(supplemental),sourceSupplements=supplemental,
            observedSourceFiles=len(manifest['compilerCoverage']['observedServerSources']),
            observedIncludeDirectories=len(manifest['compilerCoverage']['observedServerIncludeDirectories']),
            semanticPatchReplay=patches, originalLua=lua, archivalRevision=revision,
            gitMetadataPresent=False, assetTreesIncluded=False, sourcesFetched=False,
            sourceCompanionComplete=False, isolatedSourceRebuildQualified=False, transitiveIncludeClosureProved=False,
            serverExecuted=False, androidRuntimeQualified=False, gameplayQualified=False)
        write_new(stage / 'preparation-receipt.json', package.canonical(result))
        archives.sync_directory(stage); package.publish_directory(stage, output); archives.sync_directory(output.parent)
        return result
    except BaseException:
        if stage.exists(): print('Unpublished isolated-source stage retained at ' + str(stage), file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--supplements',type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source_inputs, args.output,args.supplements), indent=2))


if __name__ == '__main__': main()
