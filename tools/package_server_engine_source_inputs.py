#!/usr/bin/env python3
"""Retain unsealed, source-selected inputs for an exact Linux ARM64 engine build.

Pristine Git blobs, verified adapted copies and original external archives remain
separate. This is input preservation, never a complete source/rebuild claim.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shlex
import subprocess
import sys
import tempfile

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import fetch_sources, manifest_server_content as content
from tools import manifest_server_modules as modules, package_server_content as package
from tools import prepare_runtime as archives, verify_server_build as files

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'runtime/server/engine-source-audit.json'
RULE_FIELDS = ('rootFiles', 'wholeTrees', 'excludedSubtrees', 'moduleCodeSuffixes',
               'moduleRootBuildFiles', 'moduleConfigurationPattern', 'moduleNoticeBasenames',
               'includeWholeElunaTree')
LUA_SHA256 = 'b9e2e4aad6789b3b63a056d442f7b39f0ecfca3ae0f1fc0ae4e9614401b69f4b'
LUA_MAX_BYTES = 2 * 1024**2
INTEGRATION_SUFFIXES = {'.py', '.cpp', '.c', '.h', '.hpp', '.cmake'}
require = files.require
INTEGRATION_URL = 'https://github.com/Russianranger/esteria_android.git'


def rules():
    audit, audit_identity = modules.read_json(AUDIT)
    require(audit.get('formatVersion') == 1 and isinstance(audit.get('selection'), dict),
            'engine-source-selection-audit-required')
    selected = {key: audit['selection'][key] for key in RULE_FIELDS}
    require(selected['includeWholeElunaTree'] is True, 'complete-eluna-source-selection-required')
    return selected, audit_identity


def regular(source, name):
    row = source.files[name]
    require(row.get('kind') == 'blob' and row.get('mode') in ('100644', '100755'),
            'nonregular-engine-source-input:' + name)
    return True


def select_server(source, enabled_modules, selection):
    require(isinstance(enabled_modules, list) and enabled_modules and
            len(enabled_modules) == len(set(enabled_modules)) and
            all(re.fullmatch('[A-Za-z0-9_-]+', name) for name in enabled_modules),
            'invalid-compiled-engine-module-selection')
    roots = set(selection['rootFiles'])
    require(roots <= set(source.files), 'engine-source-root-file-missing')
    selected = set()
    for name, row in source.files.items():
        if any(name == path or content.below(name, path) for path in selection['excludedSubtrees']):
            continue
        wanted = name in roots or any(content.below(name, path) for path in selection['wholeTrees'])
        parts = PurePosixPath(name).parts
        if len(parts) == 2 and parts[0] == 'modules':
            wanted |= any(fnmatch.fnmatchcase(parts[-1], pattern) for pattern in selection['moduleRootBuildFiles'])
        if len(parts) >= 3 and parts[0] == 'modules' and parts[1] in enabled_modules:
            relative = PurePosixPath(*parts[2:])
            wanted |= (relative.suffix in selection['moduleCodeSuffixes'] or
                relative.name == 'CMakeLists.txt' or
                (relative.parts[0] == 'conf' and name.endswith('.conf.dist')) or
                any(fnmatch.fnmatchcase(relative.name.upper(), pattern.upper())
                    for pattern in selection['moduleNoticeBasenames']))
        if wanted and row.get('kind') != 'commit':
            regular(source, name); selected.add(name)
    require(all(any(name.startswith('modules/' + module + '/') for name in selected)
                for module in enabled_modules), 'compiled-module-source-not-selected')
    return sorted(selected)


def server_prefixes(server, revision, enabled_modules, selection):
    """Do not enumerate unrelated Harvested/assets trees into GitObjects' bound."""
    raw = subprocess.check_output(['git', 'ls-tree', '-z', revision + ':modules'], cwd=server,
        env=dict(os.environ, GIT_NO_LAZY_FETCH='1'), stderr=subprocess.PIPE)
    require(len(raw) <= content.MAX_METADATA_BYTES, 'root-module-build-list-bound')
    root_build = []
    for record in raw.split(b'\0'):
        if not record: continue
        header, name = record.split(b'\t', 1)
        name = name.decode(); content.safe_path(name)
        _, kind, _ = header.decode().split()
        if kind == 'blob' and any(fnmatch.fnmatchcase(name, pattern) for pattern in selection['moduleRootBuildFiles']):
            root_build.append('modules/' + name)
    return (selection['rootFiles'] + selection['wholeTrees'] + root_build +
            ['modules/' + module for module in enabled_modules])


def select_integration(source, patch_paths):
    required = {'LICENSE', 'sources.lock.json', '.github/workflows/server.yml',
        'config/local-server.json', 'runtime/server-lua-map.json', 'runtime/server/Dockerfile',
        'runtime/server/sources.lock.json', 'runtime/server/ubuntu.sources',
        'runtime/server/inrelease.SHA256SUMS', 'runtime/server/mysql-binaries.SHA256SUMS'} | set(patch_paths)
    require(required <= set(source.files), 'original-integration-build-input-missing')
    selected = set(required)
    for name in source.files:
        path = PurePosixPath(name)
        if ((name.startswith(('tools/', 'tests/')) and path.suffix in INTEGRATION_SUFFIXES) or
            (name.startswith('runtime/') and path.suffix == '.py')):
            selected.add(name)
    for name in selected: regular(source, name)
    return sorted(selected)


def local_identity(path, maximum=files.MAX_FILE):
    """Record a content address; gitBlob does not imply an object was committed."""
    with files.plain_file(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        require(0 <= size <= maximum, 'engine-source-local-input-bound')
        sha256 = hashlib.sha256(); blob = hashlib.sha1(('blob ' + str(size) + '\0').encode())
        remaining = size
        while remaining:
            block = stream.read(min(files.BUFFER, remaining))
            require(block, 'engine-source-local-input-short-read')
            sha256.update(block); blob.update(block); remaining -= len(block)
        require(not stream.read(1), 'engine-source-local-input-changed-size')
    return dict(bytes=size, sha256=sha256.hexdigest(), gitBlob=blob.hexdigest(), gitMode='100644')


def validate_inputs(server, build_path, compiled_path, commands, lock_path, lua_archive):
    lock = fetch_sources.load_lock(lock_path); pin = lock['sources']['server']
    content.validate_patch_contract(pin, lock_path.parent)
    fetch_sources.verify_checkout(server, pin, fetch_sources.patch_inputs(pin, lock_path.parent))
    build, build_identity = modules.read_json(build_path)
    lock_identity = files.identity(lock_path)
    require(build.get('schemaVersion') == 1 and build.get('architecture') == 'Linux-ARM64' and
            build.get('sourceCheckoutAndPatchesVerified') is True and build.get('serverSource') == pin and
            build.get('sourcesLock') == lock_identity and
            re.fullmatch('[a-f0-9]{40}', build.get('integrationRevision', '')) and
            re.fullmatch('[A-Za-z0-9_.-]{1,128}', build.get('buildId', '')),
            'engine-source-build-selection-mismatch')
    compiled, compiled_identity = modules.read_json(compiled_path)
    require(compiled.get('formatVersion') == 1 and compiled.get('scope') == 'compiled-server-module-selection' and
            compiled.get('generatedListsMatchInstalledBinaries') is True and
            compiled.get('source') == pin and compiled.get('sourceLockSha256') == lock_identity['sha256'] and
            compiled.get('serverBuild') == build_identity, 'engine-source-module-build-mismatch')
    selection, command_identity = modules.extract_commands(commands)
    require(compiled.get('compileCommands') == command_identity and
            compiled.get('enabledModules') == selection['modules'] and
            compiled.get('configFiles') == selection['configFiles'], 'engine-source-compile-selection-mismatch')
    lua = local_identity(lua_archive, LUA_MAX_BYTES)
    require(lua['sha256'] == LUA_SHA256, 'original-lua-5.2.4-archive-required')
    return dict(build=build, buildIdentity=build_identity, compiled=compiled,
                compiledIdentity=compiled_identity, commands=command_identity, source=pin,
                sourceLock=lock_identity, lua=lua)


def compiler_coverage(commands, selected):
    """Cover observed sources/includes; this deliberately proves no transitive closure."""
    source_paths, include_paths, prefixes = set(), set(), set()
    identity = {}
    with files.plain_file(commands) as stream:
        for row in modules.json_array(stream, identity):
            directory = row.get('directory')
            require(isinstance(directory, str) and len(directory) <= 4096, 'compile-directory-contract')
            def absolute(value):
                require(isinstance(value, str) and len(value) <= 4096, 'compile-path-contract')
                return posixpath.normpath(value if value.startswith('/') else posixpath.join(directory, value))
            filename = absolute(row.get('file'))
            source_paths.add(filename)
            for suffix in modules.TARGETS.values():
                if filename.endswith(suffix): prefixes.add(filename[:-len(suffix)])
            arguments = row.get('arguments')
            if arguments is None:
                require(isinstance(row.get('command'), str), 'compile-command-arguments-required')
                arguments = shlex.split(row['command'], posix=True)
            require(isinstance(arguments, list) and all(isinstance(arg, str) for arg in arguments),
                    'compile-command-arguments-contract')
            index = 0
            while index < len(arguments):
                arg = arguments[index]; value = None
                if arg in ('-I', '-isystem', '-iquote', '-idirafter'):
                    index += 1; require(index < len(arguments), 'compile-include-value-missing')
                    value = arguments[index]
                else:
                    for flag in ('-isystem', '-iquote', '-idirafter', '-I'):
                        if arg.startswith(flag) and len(arg) > len(flag): value = arg[len(flag):]; break
                if value is not None: include_paths.add(absolute(value))
                index += 1
    require(len(prefixes) == 1, 'unambiguous-original-server-source-prefix-required')
    prefix = prefixes.pop()
    observed = sorted(path[len(prefix)+1:] for path in source_paths if path.startswith(prefix + '/'))
    missing = sorted(set(observed) - set(selected))
    require(not missing, 'observed-compiled-server-source-not-selected:' + ','.join(missing[:8]))
    source_includes = sorted(path[len(prefix)+1:] if path != prefix else '' for path in include_paths
                             if path == prefix or path.startswith(prefix + '/'))
    absent = [path for path in source_includes if not any(not path or name.startswith(path + '/') for name in selected)]
    require(not absent, 'observed-server-include-directory-empty:' + ','.join(absent[:8]))
    return dict(compileCommands=identity, observedServerSources=observed,
        observedServerIncludeDirectories=source_includes,
        externalOrGeneratedSources=sorted(source_paths - {prefix + '/' + name for name in observed}),
        observedSourceFilesCovered=True, observedIncludeDirectoriesCovered=True,
        transitiveIncludeClosureProved=False)


def adapted_inputs(sources, selected):
    result, local = [], {}
    for origin in ('server', 'eluna'):
        source = sources[origin]
        changed = source.command('diff', '--cached', '--name-only', '-z', source.commit, '--').split(b'\0')
        for raw in changed:
            if not raw: continue
            name = raw.decode(); content.safe_path(name)
            require(name in selected[origin], 'adapted-file-outside-source-selection:' + name)
            actual = source.path / name; row = local_identity(actual)
            index_blob = source.command('rev-parse', ':' + name).decode().strip()
            require(row['gitBlob'] == index_blob, 'adapted-file-differs-from-verified-index')
            relative = (content.ELUNA + '/' if origin == 'eluna' else '') + name
            target = 'adapted-source/' + relative
            local[target] = actual
            result.append(dict(path=relative, origin=origin,
                pristine=sources[origin].identities([name], True)[name], adapted=row,
                role='separate-applied-copy-not-a-pristine-git-blob'))
    return sorted(result, key=lambda row: row['path']), local


class LocalBatch:
    def __init__(self): self.context = self.reader = None
    def blob(self, expected):
        require(self.context is None, 'unfinished-source-local-reader')
        self.context = files.plain_file(expected['_path'])
        self.reader = package.HashReader(self.context.__enter__(), expected)
        return self.reader
    def finish_blob(self, reader):
        require(reader is self.reader, 'source-local-reader-mismatch')
        try: reader.finish()
        finally: self.close()
    def close(self):
        if self.context is not None:
            context = self.context; self.context = self.reader = None
            context.__exit__(None, None, None)


@contextmanager
def integration_objects(revision, allow_fetch=False):
    """A shallow CI checkout may omit the build commit; never alter its checkout."""
    available = subprocess.run(['git', 'cat-file', '-e', revision + '^{commit}'], cwd=ROOT,
        env=dict(os.environ, GIT_NO_LAZY_FETCH='1'), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if available.returncode == 0:
        yield content.GitObjects(ROOT, revision, allow_fetch)
        return
    with tempfile.TemporaryDirectory(prefix='.engine-original-integration-') as directory:
        original = Path(directory)
        subprocess.run(['git', 'init', '--quiet', str(original)], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
        # Only the fixed public integration repository and exact build commit are
        # fetched. No credentials/configuration or .git metadata enter the archive.
        subprocess.run(['git', 'fetch', '--depth', '1', '--no-tags', INTEGRATION_URL, revision], cwd=original,
            env=dict(os.environ, GIT_TERMINAL_PROMPT='0'), check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180)
        yield content.GitObjects(original, revision, False)


def build(output, server, build_path, compiled_path, commands, lock_path, lua_archive, *, allow_fetch=False):
    server = archives.directory(Path(os.path.abspath(server)))
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and server not in output.parents and output not in server.parents,
            'source-input-output-exists-or-overlaps-server')
    proof = validate_inputs(server, build_path, compiled_path, commands, lock_path, lua_archive)
    with integration_objects(proof['build']['integrationRevision'], allow_fetch) as integration:
        return build_selected(output, server, build_path, compiled_path, commands, lock_path, lua_archive,
                              proof, integration, allow_fetch)


def build_selected(output, server, build_path, compiled_path, commands, lock_path, lua_archive,
                   proof, integration, allow_fetch):
    selection, audit_identity = rules()
    sources = {'server': content.GitObjects(server, proof['source']['commit'], allow_fetch,
            prefixes=server_prefixes(server, proof['source']['commit'], proof['compiled']['enabledModules'], selection)),
        'eluna': content.GitObjects(server / content.ELUNA, proof['source']['submodules'][content.ELUNA], allow_fetch),
        'integration': integration}
    require(sources['server'].files.get(content.ELUNA, {}).get('gitBlob') == sources['eluna'].commit,
            'source-input-eluna-gitlink-mismatch')
    selected = {'server': select_server(sources['server'], proof['compiled']['enabledModules'], selection),
        'eluna': sorted(name for name in sources['eluna'].files if regular(sources['eluna'], name)),
        'integration': select_integration(sources['integration'], [row['path'] for row in proof['source']['patches']])}
    identities = {origin: source.identities(selected[origin], True) for origin, source in sources.items()}
    require(identities['integration']['sources.lock.json']['sha256'] == proof['sourceLock']['sha256'],
            'original-integration-source-lock-differs')
    for row in proof['source']['patches']:
        require(identities['integration'][row['path']]['sha256'] == row['sha256'],
                'original-integration-patch-differs')
    all_server = set(selected['server']) | {content.ELUNA + '/' + name for name in selected['eluna']}
    coverage = compiler_coverage(commands, all_server)
    require(coverage['compileCommands'] == proof['commands'], 'compile-commands-changed-after-source-selection')
    adapted, local = adapted_inputs(sources, selected)
    local.update({'external/lua-5.2.4.tar.gz': lua_archive,
        'metadata/server-build.json': build_path, 'metadata/server-modules.json': compiled_path,
        'metadata/compile_commands.json': commands, 'metadata/source-selection-audit.json': AUDIT,
        'packaging-recipes/package_server_engine_source_inputs.py': Path(__file__).resolve()})
    local_rows = {target: local_identity(path) for target, path in local.items()}
    for target, expected in (('metadata/server-build.json', proof['buildIdentity']),
                            ('metadata/server-modules.json', proof['compiledIdentity']),
                            ('metadata/compile_commands.json', proof['commands']),
                            ('metadata/source-selection-audit.json', audit_identity),
                            ('external/lua-5.2.4.tar.gz', proof['lua'])):
        require(all(local_rows[target][key] == expected[key] for key in ('bytes', 'sha256')),
                'source-input-changed-after-validation:' + target)
    manifest = dict(formatVersion=1, scope='unsealed-engine-source-input-preservation',
        source=proof['source'], sourceLock=proof['sourceLock'], buildId=proof['build']['buildId'],
        originalIntegrationRevision=proof['build']['integrationRevision'],
        originalBuild=proof['buildIdentity'], originalCompiledModules=proof['compiledIdentity'],
        compileCommands=proof['commands'], sourceTrees={origin: source.tree for origin, source in sources.items()},
        sourceSelectionAudit=audit_identity, selectionRules=selection, enabledModules=proof['compiled']['enabledModules'],
        pristineGitFiles=identities, sourceAdaptations=content.adaptation_records(proof['source']),
        adaptedFiles=adapted, localInputs=local_rows, compilerCoverage=coverage,
        luaOriginalArchiveRetained=True, luaArchiveExpanded=False,
        selectedSourceNoticesRetained=True, originalBuildReceiptsPreserved=True,
        sourceCompanionComplete=False, isolatedSourceRebuildQualified=False,
        transitiveIncludeClosureProved=False, serverExecuted=False,
        androidRuntimeQualified=False, gameplayQualified=False)
    metadata = {'metadata/source-inputs.json': package.canonical(manifest)}
    writer_manifest = {'files': identities['server'], 'elunaFiles': dict(identities['eluna'])}
    payload = [('server', name, 'source/' + name) for name in selected['server']]
    payload += [('eluna', name, 'source/' + content.ELUNA + '/' + name) for name in selected['eluna']]
    for name in selected['integration']:
        key = 'integration/' + name
        writer_manifest['elunaFiles'][key] = identities['integration'][name]
        payload.append(('integration', key, key))
    for target, row in local_rows.items():
        key = 'local/' + target
        writer_manifest['elunaFiles'][key] = dict(row, _path=local[target])
        payload.append(('local', key, target))
    targets = [row[2] for row in payload] + list(metadata)
    require(len(targets) == len(set(name.casefold() for name in targets)), 'source-input-archive-path-collision')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    readers = {}
    try:
        for origin, source in sources.items(): readers[origin] = package.GitBatch(source)
        readers['local'] = LocalBatch()
        archive = stage / 'server-engine-source-inputs.tar.gz'
        inventory = package.write_archive(archive, payload, writer_manifest, readers, metadata)
        package.verify_archive(archive, inventory)
        for name, row in local_rows.items():
            require(files.identity(local[name]) == {key: row[key] for key in ('bytes', 'sha256')},
                    'source-input-changed-during-packaging:' + name)
        receipt = dict(formatVersion=1, scope='unsealed-engine-source-input-package',
            archive=dict(file=archive.name, **files.identity(archive)), archiveFiles=inventory,
            manifest=dict(bytes=len(metadata['metadata/source-inputs.json']),
                sha256=hashlib.sha256(metadata['metadata/source-inputs.json']).hexdigest()),
            originalBuild=proof['buildIdentity'], originalCompiledModules=proof['compiledIdentity'],
            sourceLock=proof['sourceLock'], completeArchiveReadbackVerified=True,
            sourceCompanionComplete=False, isolatedSourceRebuildQualified=False,
            transitiveIncludeClosureProved=False, androidRuntimeQualified=False, gameplayQualified=False)
        with (stage / 'source-inputs-receipt.json').open('xb') as stream:
            stream.write(package.canonical(receipt)); stream.flush(); os.fsync(stream.fileno())
        with files.plain_file(archive) as stream: os.fsync(stream.fileno())
        archives.sync_directory(stage); package.publish_directory(stage, output); archives.sync_directory(output.parent)
        return receipt
    except BaseException:
        if stage.exists(): print('Unpublished source-input stage retained at ' + str(stage), file=sys.stderr)
        raise
    finally:
        for reader in readers.values(): reader.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'server', 'server-build', 'compiled-modules', 'compile-commands', 'lock', 'lua-archive'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--allow-source-fetch', action='store_true')
    args = parser.parse_args()
    receipt = build(args.output, args.server, args.server_build, args.compiled_modules,
        args.compile_commands, args.lock, args.lua_archive, allow_fetch=args.allow_source_fetch)
    print(json.dumps({key: receipt[key] for key in ('scope', 'archive', 'completeArchiveReadbackVerified',
                                                  'sourceCompanionComplete', 'isolatedSourceRebuildQualified')}))


if __name__ == '__main__': main()
