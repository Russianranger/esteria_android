#!/usr/bin/env python3
"""Inventory pinned server SQL/config/Lua inputs without executing any of them.

Reads Git objects, not working-tree files. A sparse checkout is supported; untracked
or modified working files are never included. Full manifests stream SHA-256 over
content; --metadata-only retains exact Git blob identities and marks that limit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

try:
    from . import fetch_sources
except ImportError:
    import fetch_sources

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_SERVER = 'f35f04d01689f034778e3474b3c820092f51e461'
SUPPORTED_ELUNA = '58d7652138887783228b9727bd1fa4e08f00342b'
ELUNA = 'src/server/game/LuaEngine'
SUPPORTED_PATCHES = {
    '0001-eluna-declare-area-trigger.patch': 'c26b145188c5f97bf30d032e1fe3bd7fe17aa1f8f0daa6793e51f5d830fe7aa6',
    '0002-eluna-include-map-manager.patch': '4e277dbe56c31ae30640c8e9ad4dee12e944e0f051d9bdc8d62aaa239c50433f',
}
MAX_TREE_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_FILES = 40000
CHUNK = 128 * 1024
LATE = {'PENDING', 'CUSTOM', 'MODULE'}
DATABASES = {
    'auth': ('', 'data/sql/base/db_auth', 'auth'),
    'characters': ('', 'data/sql/base/db_characters', 'characters'),
    'world': ('', 'data/sql/base/db_world', 'world'),
    'playerbots': ('modules/mod-playerbots', 'modules/mod-playerbots/data/sql/playerbots/base', 'db_playerbot'),
}
EVIDENCE = (
    'src/server/database/Database/DatabaseLoader.cpp',
    'src/server/database/Updater/DBUpdater.cpp',
    'src/server/database/Updater/UpdateFetcher.cpp',
    'src/server/database/Updater/UpdateFetcher.h',
    'src/cmake/macros/ConfigureModules.cmake', 'modules/CMakeLists.txt',
    'src/server/apps/worldserver/Main.cpp', 'src/tools/dbimport/Main.cpp',
    'modules/mod-playerbots/src/Script/Playerbots.cpp',
)
SERVER_PREFIXES = ('data/sql', 'modules', 'src/server/database', 'src/cmake/macros/ConfigureModules.cmake',
                   'src/tools/dbimport', 'src/server/apps', ELUNA, 'AUTHORS', 'COPYING', 'LICENSE')


def require(value, message):
    if not value:
        raise ValueError(message)


def safe_path(value):
    path = PurePosixPath(value)
    require(value and not path.is_absolute() and '..' not in path.parts and
            str(path) == value and '\\' not in value and '\x00' not in value and
            all(ord(char) >= 32 for char in value), f'unsafe source path: {value!r}')
    return path


class GitObjects:
    """Read exact objects with an explicit opt-in for partial-clone network fetches."""
    def __init__(self, path, commit, allow_fetch=False, prefixes=()):
        require(re.fullmatch('[0-9a-f]{40}', commit), 'full source commit required')
        self.path, self.commit = Path(path), commit
        self.allow_fetch = allow_fetch
        self.env = dict(os.environ, GIT_NO_LAZY_FETCH='0' if allow_fetch else '1')
        actual = self.command('rev-parse', commit + '^{commit}').decode().strip()
        require(actual == commit, 'source commit mismatch')
        self.tree = self.command('rev-parse', commit + '^{tree}').decode().strip()
        # ls-tree without -l reads tree objects, never every blob just to get sizes.
        data = self.command('ls-tree', '-rz', '--full-tree', commit, '--', *prefixes)
        require(len(data) <= MAX_TREE_BYTES, 'source tree metadata exceeds bound')
        self.files = {}
        for row in data.split(b'\0'):
            if not row:
                continue
            header, name = row.split(b'\t', 1)
            mode, kind, oid = header.decode().split()
            name = name.decode('utf-8')
            safe_path(name)
            require(name not in self.files, 'duplicate source path')
            self.files[name] = {'mode': mode, 'kind': kind, 'gitBlob': oid}
            require(len(self.files) <= MAX_FILES, 'source file inventory exceeds bound')

    def command(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.path, env=self.env,
                                       stderr=subprocess.PIPE)

    def read(self, name):
        item = self.files.get(name)
        require(item and item['kind'] == 'blob' and item['mode'] in ('100644', '100755'),
                f'missing or nonregular source input: {name}')
        size = int(self.command('cat-file', '-s', item['gitBlob']))
        require(size <= MAX_METADATA_BYTES, f'metadata source is too large: {name}')
        data = self.command('cat-file', 'blob', item['gitBlob'])
        require(len(data) == size, 'source blob length changed')
        return data

    def identities(self, names, content_hashes):
        result = {}
        ordered = sorted(set(names))
        for name in ordered:
            item = self.files[name]
            require(item['kind'] == 'blob' and item['mode'] in ('100644', '100755'),
                    f'nonregular runtime input: {name}')
            result[name] = {'gitBlob': item['gitBlob'], 'gitMode': item['mode']}
        if not content_hashes:
            return result
        # Fetch an explicit batch of missing object IDs once when requested, not
        # thousands of serialized partial-clone network operations while hashing.
        missing = []
        no_fetch_env = dict(self.env, GIT_NO_LAZY_FETCH='1')
        for offset in range(0, len(ordered), 256):
            group = [result[name]['gitBlob'] for name in ordered[offset:offset + 256]]
            rows = subprocess.check_output(['git', 'cat-file', '--batch-check'], cwd=self.path,
                env=no_fetch_env, input=('\n'.join(group) + '\n').encode('ascii'), stderr=subprocess.PIPE)
            rows = [row.split() for row in rows.decode('ascii').splitlines()]
            require(len(rows) == len(group), 'invalid Git availability response')
            for oid, row in zip(group, rows):
                require(row[0] == oid, 'Git availability identity mismatch')
                if row == [oid, 'missing']:
                    missing.append(oid)
                else:
                    require(len(row) == 3 and row[1] == 'blob' and row[2].isdigit(), 'invalid source blob')
        if missing:
            require(self.allow_fetch, f'{len(set(missing))} content blobs unavailable offline; explicitly fetch source inputs')
            subprocess.run(['git', '-c', 'fetch.negotiationAlgorithm=noop', 'fetch', '--no-tags',
                            '--no-write-fetch-head', '--recurse-submodules=no', '--filter=blob:none',
                            'origin', '--stdin'], cwd=self.path, env=self.env,
                           input=('\n'.join(sorted(set(missing))) + '\n').encode('ascii'),
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        # One process, bounded reads; a large SQL dump never becomes one Python string.
        with tempfile.TemporaryFile() as errors, subprocess.Popen(
                ['git', 'cat-file', '--batch'], cwd=self.path, env=no_fetch_env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors) as child:
            try:
                for name in ordered:
                    oid = result[name]['gitBlob']
                    child.stdin.write((oid + '\n').encode('ascii'))
                    child.stdin.flush()
                    header = child.stdout.readline(256).decode('ascii').strip().split()
                    require(len(header) == 3 and header[:2] == [oid, 'blob'],
                            f'missing source blob; explicitly fetch inputs first: {name}')
                    size = int(header[2])
                    digest = hashlib.sha256()
                    remaining = size
                    while remaining:
                        data = child.stdout.read(min(CHUNK, remaining))
                        require(data, f'truncated source blob: {name}')
                        digest.update(data)
                        remaining -= len(data)
                    require(child.stdout.read(1) == b'\n', 'invalid Git batch delimiter')
                    result[name].update(bytes=size, sha256=digest.hexdigest())
                child.stdin.close()
                require(child.wait(timeout=20) == 0, 'Git content read failed')
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
        return result


def parse_includes(data):
    """Parse only this pinned dump's literal INSERT; never evaluate SQL."""
    text = data.decode('utf-8-sig')
    statements = re.findall(r'INSERT\s+INTO\s+`updates_include`\s*(?:\(`path`,\s*`state`\)\s*)?VALUES\s*(.*?);',
                            text, re.DOTALL | re.IGNORECASE)
    require(len(statements) == 1, 'unsupported updates_include initialization')
    literal = statements[0]
    pattern = re.compile(r"\s*\('([^'\\]+)'\s*,\s*'(RELEASED|ARCHIVED|CUSTOM|PENDING)'\)\s*(?:,|$)")
    entries, offset = [], 0
    while offset < len(literal):
        match = pattern.match(literal, offset)
        require(match, 'nonliteral/unsupported updates_include row')
        path, state = match.groups()
        require(path.startswith('$/'), 'external update directory requires explicit reviewed mapping')
        safe_path(path[2:])
        entries.append({'path': path[2:], 'state': state})
        offset = match.end()
    require(entries and len({entry['path'] for entry in entries}) == len(entries), 'duplicate/empty includes')
    return entries


def below(path, root):
    return path.startswith(root + '/')


def source_modules(paths):
    # GetModuleSourceList: immediate modules/* directories with a src directory.
    return sorted({parts[1] for name in paths if len(parts := name.split('/')) > 3 and
                   parts[0] == 'modules' and parts[2] == 'src'})


def database_plan(paths, database, modules, read):
    source_root, base_root, match = DATABASES[database]
    base = sorted(path for path in paths if path.startswith(base_root + '/') and
                  '/' not in path[len(base_root) + 1:] and path.endswith('.sql'))
    require(base, f'missing base SQL: {database}')
    includes = parse_includes(read(base_root + '/updates_include.sql'))
    for entry in includes:
        entry['path'] = (source_root + '/' if source_root else '') + entry['path']
        entry['origin'] = 'base-updates_include'
    # Playerbots gets its own loader without AC_MODULES_LIST; source root is the module.
    if database != 'playerbots':
        for module in modules:
            root = f'modules/{module}/data/sql'
            children = sorted({path[len(root) + 1:].split('/')[0] for path in paths
                               if below(path, root) and '/' in path[len(root) + 1:]})
            includes += [{'path': root + '/' + child, 'state': 'MODULE', 'origin': module}
                         for child in children if match in child]
    updates, ignored_depth, absent = [], [], []
    for entry in includes:
        members = sorted(path for path in paths if below(path, entry['path']))
        if not members:
            absent.append(dict(entry))
        for path in members:
            if not path.endswith('.sql'):
                continue
            if len(PurePosixPath(path).relative_to(entry['path']).parts) > 10:
                ignored_depth.append(path)
            else:
                updates.append({'path': path, 'state': entry['state'], 'origin': entry['origin']})
    names = {}
    for entry in updates:
        names.setdefault(PurePosixPath(entry['path']).name, []).append(entry['path'])
    duplicates = {name: values for name, values in sorted(names.items()) if len(values) != 1}
    ordered = sorted(updates, key=lambda row: (row['state'] in LATE, PurePosixPath(row['path']).name))
    return dict(base=base, includeDirectories=includes, missingSourceDirectories=absent,
                ignoredBeyondDepth10=ignored_depth, duplicateBasenames=duplicates,
                updateOrder=ordered if not duplicates else None, discoveredUpdates=updates,
                executionOrderQualified=not duplicates and not ignored_depth,
                existingDatabasePlan=False)


def make_manifest(server, eluna, source, lock_digest, modules, profile, content_hashes):
    paths = set(server.files)
    require(len(set(modules)) == len(modules), 'duplicate module selection')
    require(all(re.fullmatch(r'[A-Za-z0-9_-]+', name) for name in modules), 'unsafe module selection')
    require(set(modules) <= set(source_modules(paths)), 'selected module has no committed src directory')
    require(server.files.get(ELUNA, {}).get('gitBlob') == source['submodules'][ELUNA] and
            server.files[ELUNA]['kind'] == 'commit', 'Eluna gitlink differs from lock')
    plans = {db: database_plan(paths, db, modules, server.read) for db in DATABASES
             if db != 'playerbots' or 'mod-playerbots' in modules}
    selected = set(EVIDENCE)
    for plan in plans.values():
        selected.update(plan['base'])
        selected.update(row['path'] for row in plan['discoveredUpdates'])
    for filename in paths:
        if '/' not in filename and filename.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'AUTHORS')):
            selected.add(filename)
    modules_doc = []
    for module in sorted(modules):
        prefix = f'modules/{module}/'
        members = sorted(path for path in paths if path.startswith(prefix))
        sql = [path for path in members if path.endswith('.sql')]
        included = set(path for path in sql if path in selected)
        config = [path for path in members if path.startswith(prefix + 'conf/') and
                  '/' not in path[len(prefix + 'conf/'):] and path.endswith('.conf.dist')]
        lua = [path for path in members if path.endswith(('.lua', '.ext', '.moon')) and
               path[len(prefix):].split('/')[0] in ('lua_scripts', 'lua')]
        notices = [path for path in members if '/' not in path[len(prefix):] and
                   PurePosixPath(path).name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'AUTHORS'))]
        excluded = [path for path in sql if path not in included]
        # Retain hashes of excluded SQL for review, but never select it for execution.
        selected.update(sql + config + lua + notices)
        modules_doc.append(dict(name=module, configTemplates=config, luaCandidates=lua,
                                automaticallyDiscoveredSql=sorted(included),
                                sqlNotDiscoveredByUpdater=excluded, notices=notices))
    eluna_paths = sorted(path for path in eluna.files if path.startswith('extensions/') and
                        path.endswith(('.lua', '.ext', '.moon')))
    eluna_paths += [path for path in ('docs/LICENSE.md', 'LICENSE') if path in eluna.files]
    blockers = []
    for database, plan in plans.items():
        if plan['duplicateBasenames']:
            blockers.append(dict(code='duplicate-update-filenames', database=database,
                                 names=plan['duplicateBasenames']))
        if plan['ignoredBeyondDepth10']:
            blockers.append(dict(code='sql-beyond-updater-depth', database=database))
    if profile == 'all-source-static':
        blockers.append(dict(code='compiled-module-list-not-compared', detail='Source profile is not a binary receipt.'))
    excluded_count = sum(len(row['sqlNotDiscoveredByUpdater']) for row in modules_doc)
    if excluded_count:
        blockers.append(dict(code='module-sql-requires-review', count=excluded_count,
                             detail='Includes optional/uninstall/manual content; never apply all exclusions.'))
    blockers.append(dict(code='lua-installation-map-unqualified',
                         detail='Candidates remain at source paths; no runtime script set or collision policy selected.'))
    return dict(formatVersion=1, scope='source-content-inventory', source=source,
                sourceLockSha256=lock_digest, sourceTree=server.tree, elunaTree=eluna.tree,
                profile=profile, enabledModules=sorted(modules), contentSha256Complete=content_hashes,
                loaderContract=dict(baseOrder='immediate .sql paths lexicographically; only on empty database',
                    updateOrder='global basename order: RELEASED/ARCHIVED, then PENDING/CUSTOM/MODULE',
                    updateIdentity='basename; duplicate names abort even across different directories',
                    maximumRecursiveDepth=10,
                    runtimeAppliedLedgerAuthoritative=True,
                    worldDatabaseOrder=['auth', 'characters', 'world', 'playerbots-module-hook'],
                    dbimportDoesNotInitializePlayerbots=True,
                    localRealmGate=dict(required=True, afterAllCoreAndModuleUpdates=True,
                        requireAuthenticatedLoopbackVerification=True,
                        sourceUpdate='modules/mod-custom-server/data/sql/db-auth/u_custom_server_2026_09_03_public_realm.sql')),
                databases=plans, modules=modules_doc,
                files=server.identities(selected, content_hashes),
                elunaFiles=eluna.identities(eluna_paths, content_hashes),
                externalInputs=[dict(name='complete-current-Esteria-custom-content', available=False,
                                    detail='Current deployed custom DB/DBC/Lua/content closure is not established by source.'),
                                dict(name='stock-base-schema-and-data-SQL', available=True,
                                    detail='Committed base directories; no external base DB download selected.')],
                blockers=blockers, sqlExecuted=False, databaseQualified=False,
                androidRuntimeQualified=False, packagingSelectionComplete=False)


def atomic_output(path, document):
    path = Path(path)
    require(not path.exists() and not path.is_symlink(), 'output already exists; preserve prior evidence')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.server-content-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        # Hard link publishes only if destination is still absent (no replace race).
        os.link(temporary, path)
    finally:
        os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=ROOT / 'sources.lock.json')
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--all-source-modules', action='store_true')
    selection.add_argument('--modules-json', type=Path, help='Reviewed array of compiled enabled module names')
    parser.add_argument('--metadata-only', action='store_true', help='Do not read/hash SQL payloads; retain exact Git blob IDs')
    parser.add_argument('--allow-source-fetch', action='store_true', help='Permit Git partial-clone lazy fetch during explicit setup')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    lock_bytes = args.lock.read_bytes()
    lock = fetch_sources.load_lock(args.lock)
    require(args.lock.read_bytes() == lock_bytes, 'source lock changed while reading')
    source = lock['sources']['server']
    require(source['commit'] == SUPPORTED_SERVER and source['submodules'].get(ELUNA) == SUPPORTED_ELUNA,
            'source revision changed: re-audit loader contract before generating a manifest')
    patches = fetch_sources.patch_inputs(source, args.lock.parent)
    for scope, path in patches:
        # Reviewed declarations/includes do not change SQL or Lua execution order.
        require(scope == ELUNA and SUPPORTED_PATCHES.get(path.name) == hashlib.sha256(path.read_bytes()).hexdigest(),
                'new patch requires runtime-content contract review')
    server = GitObjects(args.server, source['commit'], args.allow_source_fetch, SERVER_PREFIXES)
    eluna = GitObjects(args.server / ELUNA, source['submodules'][ELUNA], args.allow_source_fetch)
    if args.all_source_modules:
        modules, profile = source_modules(server.files), 'all-source-static'
    else:
        require(args.modules_json.stat().st_size <= MAX_METADATA_BYTES, 'module selection exceeds bound')
        modules, profile = json.loads(args.modules_json.read_text()), 'explicit-module-list'
        require(isinstance(modules, list) and all(isinstance(row, str) for row in modules), 'expected module name array')
    document = make_manifest(server, eluna, source, hashlib.sha256(lock_bytes).hexdigest(),
                             modules, profile, not args.metadata_only)
    require(args.lock.read_bytes() == lock_bytes, 'source lock changed during inventory; retry with one revision')
    atomic_output(args.output, document)
    print(json.dumps(dict(output=str(args.output), databases=list(document['databases']),
                          modules=len(modules), files=len(document['files']),
                          blockers=len(document['blockers']), sqlExecuted=False)))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'server content inventory failed: {error}', file=sys.stderr)
        sys.exit(2)
