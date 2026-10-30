#!/usr/bin/env python3
"""Build a deterministic, hash-checked SQL/config/Lua content archive from Git.

No SQL or Lua is executed. Manual/excluded SQL remains review metadata only.
Unqualified module/Lua selections are recorded and cannot become gameplay evidence.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import ctypes
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zlib

try:
    from . import fetch_sources
    from . import manifest_server_content as content
    from . import manifest_server_modules as modules
    from . import verify_server_build as files
except ImportError:
    import fetch_sources
    import manifest_server_content as content
    import manifest_server_modules as modules
    import verify_server_build as files

MAX_TOTAL = 4 * 1024 ** 3
METADATA = 16 * 1024 ** 2


def canonical(document):
    return (json.dumps(document, sort_keys=True, indent=2) + '\n').encode('utf-8')


def require_identity(row):
    content.require(isinstance(row.get('bytes'), int) and 0 <= row['bytes'] <= MAX_TOTAL and
                    re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')) and
                    re.fullmatch('[0-9a-f]{40}', row.get('gitBlob', '')) and
                    row.get('gitMode') in ('100644', '100755'), 'incomplete content identity')


def validate_inventory(manifest, server, eluna, source, lock_sha):
    content.require(manifest.get('formatVersion') == 1 and manifest.get('scope') == 'source-content-inventory' and
                    manifest.get('contentSha256Complete') is True, 'full hashed content inventory required')
    content.require(manifest.get('source') == source and manifest.get('sourceLockSha256') == lock_sha,
                    'content inventory source lock mismatch')
    content.require(manifest.get('profile') in ('all-source-static', 'explicit-module-list'), 'unknown content profile')
    expected = content.make_manifest(server, eluna, source, lock_sha, manifest['enabledModules'],
                                     manifest['profile'], False)
    for key in ('sourceTree', 'elunaTree', 'sourceAdaptations', 'enabledModules', 'loaderContract', 'databases', 'modules'):
        content.require(manifest.get(key) == expected[key], 'content inventory contract changed: ' + key)
    for field in ('files', 'elunaFiles'):
        content.require(set(manifest[field]) == set(expected[field]), 'content file set differs from pinned source')
        for name, row in manifest[field].items():
            require_identity(row)
            content.require(all(row.get(k) == v for k, v in expected[field][name].items()), 'content object identity changed')
    content.require(sum(row['bytes'] for field in ('files', 'elunaFiles') for row in manifest[field].values()) <= MAX_TOTAL,
                    'content package byte limit')
    for database in manifest['databases'].values():
        content.require(database['executionOrderQualified'] is True and database['updateOrder'] is not None,
                        'ambiguous or truncated source SQL discovery')


def validate_modules(receipt, manifest):
    if receipt is None:
        return False
    content.require(receipt.get('formatVersion') == 1 and receipt.get('scope') == 'compiled-server-module-selection' and
                    receipt.get('generatedListsMatchInstalledBinaries') is True, 'unverified compiled module receipt')
    content.require(receipt.get('source') == manifest['source'] and
                    receipt.get('sourceLockSha256') == manifest['sourceLockSha256'], 'compiled module source mismatch')
    content.require(sorted(receipt['enabledModules']) == manifest['enabledModules'], 'compiled modules differ from inventory')
    config = sorted(Path(path).name[:-5] for module in manifest['modules'] for path in module['configTemplates'])
    content.require(sorted(receipt['configFiles']) == config, 'compiled config list differs from inventory')
    content.require(set(receipt.get('binaries', {})) == {'worldserver', 'dbimport'}, 'compiled binary selection incomplete')
    return True


def lua_candidates(manifest):
    rows = {}
    for module in manifest['modules']:
        for path in module['luaCandidates']:
            rows[('server', path)] = manifest['files'][path]
    for path, identity in manifest['elunaFiles'].items():
        if path.startswith('extensions/') and path.endswith(('.lua', '.ext', '.moon')):
            rows[('eluna', path)] = identity
    return rows


def validate_lua(mapping, manifest):
    content.require(mapping.get('formatVersion') == 1 and mapping.get('mode') in ('disabled', 'mapped') and
                    mapping.get('serverRevision') == manifest['source']['commit'] and
                    mapping.get('elunaRevision') == manifest['source']['submodules'][content.ELUNA],
                    'Lua map source or mode mismatch')
    candidates, seen, destinations, selected = lua_candidates(manifest), set(), set(), []
    for row in mapping.get('files', []):
        key = (row.get('origin'), row.get('source'))
        content.require(key in candidates and key not in seen, 'unknown/duplicate Lua candidate')
        content.require(row.get('sha256') == candidates[key]['sha256'] and
                        isinstance(row.get('reason'), str) and row['reason'].strip(), 'Lua decision lacks source identity/reason')
        seen.add(key)
        target = row.get('destination')
        if target is not None:
            content.require(mapping['mode'] == 'mapped', 'disabled Lua map contains active mapping')
            content.safe_path(target)
            content.require(target.endswith(('.lua', '.ext', '.moon')) and
                            target.casefold() not in destinations, 'Lua destination extension/collision')
            destinations.add(target.casefold())
            # The packager cannot attest matching client assets, live schemas or
            # terrain. Outstanding dependencies must not be erased by activation.
            content.require(row.get('requirements') == [], 'Lua dependency evidence is still required before activation')
            selected.append((row['origin'], row['source'], 'lua_scripts/' + target))
        else:
            content.require(isinstance(row.get('requirements'), list), 'Lua exclusion must record dependency requirements')
    content.require(seen == set(candidates), 'every Lua candidate needs an explicit inclusion/exclusion decision')
    content.require(mapping['mode'] != 'mapped' or selected, 'mapped Lua policy has no scripts')
    return selected


def select_payload(manifest, lua):
    content.require(all(path in manifest['files'] for path in content.MAIN_CONFIG_TEMPLATES),
                    'main server configuration templates missing from source inventory')
    selected = set(content.MAIN_CONFIG_TEMPLATES)
    for plan in manifest['databases'].values():
        selected.update(plan['base'])
        selected.update(row['path'] for row in plan['updateOrder'])
    for module in manifest['modules']:
        selected.update(module['configTemplates'])
        selected.update(module['notices'])
    selected.update(path for path in manifest['files'] if '/' not in path and
                    path.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'AUTHORS')))
    rows = [('server', path, 'source/' + path) for path in selected]
    rows += [('eluna', path, 'source/' + content.ELUNA + '/' + path)
             for path in manifest['elunaFiles'] if not path.endswith(('.lua', '.ext', '.moon'))]
    rows += lua
    rows.sort(key=lambda row: row[2])
    paths = [row[2] for row in rows]
    content.require(len(paths) == len(set(path.casefold() for path in paths)), 'package path collision')
    for path in paths:
        content.safe_path(path)
    return rows


class GitBatch:
    def __init__(self, source):
        self.errors = tempfile.TemporaryFile()
        self.process = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=source.path,
            env=dict(source.env, GIT_NO_LAZY_FETCH='1'), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.errors)
        self.active = False

    def blob(self, expected):
        oid = expected['gitBlob']
        self.process.stdin.write((oid + '\n').encode('ascii'))
        self.process.stdin.flush()
        header = self.process.stdout.readline(256).decode('ascii').strip().split()
        content.require(header == [oid, 'blob', str(expected['bytes'])], 'Git payload unavailable or different length')
        self.active = True
        return HashReader(self.process.stdout, expected)

    def finish_blob(self, reader):
        reader.finish()
        content.require(self.process.stdout.read(1) == b'\n', 'invalid Git payload delimiter')
        self.active = False

    def close(self):
        try:
            if self.process.poll() is None:
                if self.active:
                    self.process.kill()
                else:
                    self.process.stdin.close()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            self.process.stdout.close()
            if not self.process.stdin.closed:
                self.process.stdin.close()
            self.errors.close()


class HashReader:
    def __init__(self, stream, expected):
        self.stream, self.expected, self.remaining = stream, expected, expected['bytes']
        self.digest = hashlib.sha256()

    def read(self, size=-1):
        content.require(0 <= size <= content.CHUNK, 'unbounded package read')
        data = self.stream.read(min(size, self.remaining))
        content.require(data or not self.remaining, 'truncated package input')
        self.remaining -= len(data)
        self.digest.update(data)
        return data

    def finish(self):
        content.require(self.remaining == 0 and self.digest.hexdigest() == self.expected['sha256'],
                        'package input SHA-256 mismatch')


def tar_info(path, size):
    info = tarfile.TarInfo(path)
    info.size, info.mode, info.mtime = size, 0o644, 0
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    return info


def write_archive(path, payload, manifest, readers, metadata):
    inventory = {}
    inputs = {target: (origin, source) for origin, source, target in payload}
    content.require(not set(inputs).intersection(metadata), 'metadata path collision')
    with path.open('xb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0, compresslevel=6) as compressed:
        # The bounded Android importer supports GNU long-name metadata; PAX
        # extended headers are deliberately not part of its accepted format.
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as archive:
            for target in sorted(set(inputs) | set(metadata)):
                if target in metadata:
                    data = metadata[target]
                    inventory[target] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                    archive.addfile(tar_info(target, len(data)), io.BytesIO(data))
                else:
                    origin, source = inputs[target]
                    field = 'files' if origin == 'server' else 'elunaFiles'
                    identity = manifest[field][source]
                    reader = readers[origin].blob(identity)
                    archive.addfile(tar_info(target, identity['bytes']), reader)
                    readers[origin].finish_blob(reader)
                    inventory[target] = {key: identity[key] for key in ('bytes', 'sha256')}
                    inventory[target].update(origin=origin, source=source, gitBlob=identity['gitBlob'])
        compressed.flush()
    return inventory


def verify_archive(path, inventory):
    seen, total = set(), 0
    with path.open('rb') as raw, gzip.GzipFile(fileobj=raw, mode='rb') as compressed:
        with tarfile.open(fileobj=compressed, mode='r|') as archive:
            for item in archive:
                content.safe_path(item.name)
                content.require(item.isfile() and item.name in inventory and item.name not in seen,
                                'unexpected/link/duplicate archive member')
                content.require(item.uid == item.gid == item.mtime == 0 and item.mode == 0o644 and
                                not item.uname and not item.gname, 'nondeterministic archive metadata')
                expected = inventory[item.name]
                content.require(item.size == expected['bytes'], 'archive length mismatch')
                total += item.size
                content.require(total <= MAX_TOTAL + 4 * METADATA, 'archive size bound')
                digest = hashlib.sha256()
                with archive.extractfile(item) as stream:
                    while block := stream.read(content.CHUNK):
                        digest.update(block)
                content.require(digest.hexdigest() == expected['sha256'], 'archive readback hash mismatch')
                seen.add(item.name)
        # Read through gzip footer so trailing corruption does not evade CRC checks.
        while compressed.read(content.CHUNK):
            pass
    content.require(seen == set(inventory), 'archive member set incomplete')


def publish_directory(stage, output):
    # The server packaging host is Linux. Refuse a weaker overwrite-prone
    # rename when its atomic no-replace primitive is unavailable.
    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, 'renameat2', None)
    content.require(rename is not None, 'atomic no-replace directory publication requires Linux renameat2')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(stage), -100, os.fsencode(output), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(output))


def build_package(output, manifest, manifest_identity, module_receipt, module_identity, lua_map, lua_identity,
                  server, eluna):
    module_verified = validate_modules(module_receipt, manifest)
    lua = validate_lua(lua_map, manifest)
    payload = select_payload(manifest, lua)
    gates = ['real-updater-schema-load', 'authenticated-post-update-loopback-realm',
             'playerbots-schema-readiness', 'matched-custom-content', 'Android-runtime-validation']
    if not module_verified:
        gates.append('compiled-module-selection-verification')
    if lua_map['mode'] == 'disabled':
        gates.append('Esteria-Lua-dependency-closure-and-explicit-mapping')
    plan = dict(formatVersion=1, scope='immutable-server-source-content-package',
        source=manifest['source'], sourceLockSha256=manifest['sourceLockSha256'],
        contentManifest=manifest_identity, compiledModules=module_identity,
        moduleSelectionVerified=module_verified, luaMap=lua_identity, luaMode=lua_map['mode'],
        configurationRequirements={'Eluna.Enabled': lua_map['mode'] == 'mapped',
                                   'Eluna.ScriptPath': 'lua_scripts'},
        sourceDirectory='source', postUpdateRealmGate=manifest['loaderContract']['localRealmGate'],
        excludedSqlFiles=sum(len(row['sqlNotDiscoveredByUpdater']) for row in manifest['modules']),
        luaFiles=len(lua), gates=gates, sqlExecuted=False, gameSchemasLoaded=False,
        luaRuntimeQualified=False, androidRuntimeQualified=False, gameplayQualified=False)
    plan['producer'] = dict(python=sys.version.split()[0], zlib=zlib.ZLIB_RUNTIME_VERSION,
        packagerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        inventoryToolSha256=hashlib.sha256(Path(content.__file__).read_bytes()).hexdigest(),
        moduleToolSha256=hashlib.sha256(Path(modules.__file__).read_bytes()).hexdigest())
    metadata = {'metadata/content-manifest.json': canonical(manifest),
                'metadata/lua-map.json': canonical(lua_map), 'metadata/package-plan.json': canonical(plan)}
    if module_receipt is not None:
        metadata['metadata/compiled-modules.json'] = canonical(module_receipt)
    content.require(not output.exists() and not output.is_symlink(), 'package output exists; preserve prior generation')
    output.parent.mkdir(parents=True, exist_ok=True)
    for ancestor in (output.parent, *output.parent.parents):
        content.require(not ancestor.is_symlink(), 'symlinked package parent')
    stage = Path(tempfile.mkdtemp(prefix='.server-content-', dir=output.parent))
    try:
        with ExitStack() as stack:
            readers = {'server': GitBatch(server), 'eluna': GitBatch(eluna)}
            for reader in readers.values():
                stack.callback(reader.close)
            archive = stage / 'server-content.tar.gz'
            inventory = write_archive(archive, payload, manifest, readers, metadata)
        verify_archive(archive, inventory)
        receipt = dict(plan, archive=files.identity(archive), archiveFiles=inventory,
                       archiveReadBackVerified=True, deterministicArchive=True)
        content.atomic_output(stage / 'package-receipt.json', receipt)
        content.require(not output.exists() and not output.is_symlink(), 'package destination appeared during staging')
        publish_directory(stage, output)
        return receipt
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--module-receipt', type=Path)
    parser.add_argument('--lua-map', type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=content.ROOT / 'sources.lock.json')
    parser.add_argument('--output', type=Path, required=True, help='New immutable output directory')
    args = parser.parse_args()
    lock_bytes = args.lock.read_bytes()
    lock, lock_sha = fetch_sources.load_lock(args.lock), hashlib.sha256(lock_bytes).hexdigest()
    source = lock['sources']['server']
    content.require(source['commit'] == content.SUPPORTED_SERVER and
                    source['submodules'].get(content.ELUNA) == content.SUPPORTED_ELUNA, 'unreviewed source contract')
    content.validate_patch_contract(source, args.lock.parent)
    manifest, manifest_id = modules.read_json(args.manifest)
    lua_map, lua_id = modules.read_json(args.lua_map)
    module_receipt, module_id = modules.read_json(args.module_receipt) if args.module_receipt else (None, None)
    server = content.GitObjects(args.server, source['commit'], prefixes=content.SERVER_PREFIXES)
    eluna = content.GitObjects(args.server / content.ELUNA, source['submodules'][content.ELUNA])
    validate_inventory(manifest, server, eluna, source, lock_sha)
    content.require(args.lock.read_bytes() == lock_bytes, 'source lock changed during packaging setup')
    result = build_package(args.output, manifest, manifest_id, module_receipt, module_id, lua_map, lua_id, server, eluna)
    print(json.dumps(dict(output=str(args.output), archive=result['archive'], files=len(result['archiveFiles']),
                          moduleSelectionVerified=result['moduleSelectionVerified'], gameSchemasLoaded=False)))


if __name__ == '__main__':
    main()
