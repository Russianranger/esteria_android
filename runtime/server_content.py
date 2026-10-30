"""Verify an already extracted, externally pinned server-content generation.

Only Python's standard library is required. This module neither extracts archives
nor executes SQL. Keep the receipt outside the extracted root, and keep the
generation exclusively owned and immutable while verification and use proceed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

BLOCK = 128 * 1024
MAX_METADATA = 16 * 1024**2
MAX_FILES = 40000
MAX_PAYLOAD = 4 * 1024**3
MAX_TOTAL = MAX_PAYLOAD + 4 * MAX_METADATA
ELUNA = 'src/server/game/LuaEngine'
MAIN_CONFIGS = ('src/server/apps/authserver/authserver.conf.dist',
                'src/server/apps/worldserver/worldserver.conf.dist')
METADATA = {'metadata/content-manifest.json', 'metadata/compiled-modules.json',
            'metadata/lua-map.json', 'metadata/package-plan.json'}
DATABASES = {'auth': 'data/sql/base/db_auth', 'characters': 'data/sql/base/db_characters',
             'world': 'data/sql/base/db_world',
             'playerbots': 'modules/mod-playerbots/data/sql/playerbots/base'}


class ContentError(ValueError):
    """The content does not match its explicit immutable selection."""


class ContentCancelled(ContentError):
    """The caller cancelled verification; no input was modified."""


@dataclass(frozen=True)
class VerifiedContent:
    root: Path
    source: Path
    manifest: dict
    compiled: dict
    receipt: dict
    identities: dict


def _require(value, reason):
    if not value:
        raise ContentError(reason)


def _cancel(cancelled):
    if cancelled is not None and cancelled():
        raise ContentCancelled('server content verification cancelled')


def _path(value):
    _require(isinstance(value, str) and 0 < len(value.encode('utf-8')) <= 4096,
             'invalid content path')
    path = PurePosixPath(value)
    _require(not path.is_absolute() and str(path) == value and
             all(part not in ('.', '..') for part in path.parts) and
             '\\' not in value and all(ord(char) >= 32 and ord(char) != 127 for char in value),
             'unsafe content path')
    return path


def _unique_paths(paths):
    seen = {}
    directories = set()
    for name in paths:
        path = _path(name)
        for item in (path, *path.parents):
            if str(item) == '.':
                continue
            value = str(item)
            folded = value.casefold()
            _require(folded not in seen or seen[folded] == value, 'content path case collision')
            seen[folded] = value
        directories.update(str(item) for item in path.parents if str(item) != '.')
    _require(not set(paths).intersection(directories), 'content file/directory collision')
    return directories


def _identity(row, *, source=False):
    _require(isinstance(row, dict) and type(row.get('bytes')) is int and
             0 <= row['bytes'] <= MAX_PAYLOAD and
             isinstance(row.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', row['sha256']),
             'invalid content identity')
    if source:
        _require(isinstance(row.get('gitBlob'), str) and re.fullmatch('[0-9a-f]{40}', row['gitBlob']) and
                 row.get('gitMode') in ('100644', '100755'), 'invalid source content identity')
    return {key: row[key] for key in ('bytes', 'sha256')}


def _directory(path):
    """Open every absolute ancestor without following a symbolic link."""
    path = Path(os.path.abspath(path))
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in path.parts[1:]:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return path, descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open(root, name):
    parts = _path(name).parts
    descriptor = os.dup(root)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        try:
            info = os.fstat(file)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'linked or nonregular content file')
            return file, descriptor, parts[-1], info
        except BaseException:
            os.close(file)
            raise
    except BaseException:
        os.close(descriptor)
        raise


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _hash(root, name, maximum, cancelled, progress, *, expected=None, capture=False, state=None):
    _cancel(cancelled)
    descriptor, parent, basename, before = _open(root, name)
    try:
        _require(before.st_size <= maximum and
                 (expected is None or before.st_size == expected['bytes']), 'content file size mismatch')
        digest, count, chunks = hashlib.sha256(), 0, []
        while True:
            _cancel(cancelled)
            block = os.read(descriptor, BLOCK)
            if not block:
                break
            count += len(block)
            _require(count <= maximum and count <= before.st_size, 'content file grew during verification')
            digest.update(block)
            if capture:
                chunks.append(block)
            if progress is not None:
                progress(dict(phase='files' if state is not None else 'receipt', path=name,
                    bytes=(state['bytes'] if state else 0) + count,
                    totalBytes=state['totalBytes'] if state else before.st_size,
                    fileBytes=count, fileTotalBytes=before.st_size,
                    files=state['files'] if state else 0, totalFiles=state['totalFiles'] if state else 1))
            _cancel(cancelled)
        after = os.fstat(descriptor)
        current = os.stat(basename, dir_fd=parent, follow_symlinks=False)
        _require(count == before.st_size and _stamp(before) == _stamp(after) == _stamp(current),
                 'content file changed during verification')
        identity = dict(bytes=count, sha256=digest.hexdigest())
        _require(expected is None or identity == expected, 'content file digest mismatch')
        if state is not None:
            state['bytes'] += count
            state['files'] += 1
        return identity, b''.join(chunks) if capture else None
    finally:
        os.close(descriptor)
        os.close(parent)


def _json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            _require(key not in result, 'duplicate content JSON key')
            result[key] = value
        return result
    def constant(_value):
        raise ContentError('nonfinite content JSON value')
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    _require(isinstance(value, dict), 'content metadata must be an object')
    return value


def _scan(root, inventory, directories, cancelled):
    seen, found_dirs = set(), set()
    def visit(descriptor, prefix=''):
        _cancel(cancelled)
        with os.scandir(descriptor) as entries:
            for entry in entries:
                _cancel(cancelled)
                name = prefix + entry.name
                _path(name)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    _require(name in directories, 'unexpected content directory')
                    found_dirs.add(name)
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                    try:
                        visit(child, name + '/')
                    finally:
                        os.close(child)
                else:
                    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                             'linked or nonregular content member')
                    _require(name in inventory, 'unexpected content file')
                    seen.add(name)
    visit(root)
    _require(seen == set(inventory) and found_dirs == directories, 'content file set incomplete')


def _names(values, pattern, reason):
    _require(isinstance(values, list) and len(values) <= MAX_FILES and
             all(isinstance(value, str) and re.fullmatch(pattern, value) for value in values), reason)
    _require(len(values) == len({value.casefold() for value in values}), reason)
    return values


def _selection(manifest, compiled, lua, server_source, lock_hash):
    _require(type(manifest.get('formatVersion')) is int and manifest['formatVersion'] == 1 and
             manifest.get('scope') == 'source-content-inventory' and
             manifest.get('source') == server_source and manifest.get('sourceLockSha256') == lock_hash and
             manifest.get('contentSha256Complete') is True, 'content manifest source mismatch')
    _require(type(compiled.get('formatVersion')) is int and compiled['formatVersion'] == 1 and
             compiled.get('scope') == 'compiled-server-module-selection' and
             compiled.get('generatedListsMatchInstalledBinaries') is True and
             compiled.get('source') == server_source and compiled.get('sourceLockSha256') == lock_hash and
             set(compiled.get('binaries', {})) == {'worldserver', 'dbimport'}, 'unverified compiled content selection')
    enabled = _names(manifest.get('enabledModules'), r'[A-Za-z0-9_-]+', 'invalid content module selection')
    chosen = _names(compiled.get('enabledModules'), r'[A-Za-z0-9_-]+', 'invalid compiled module selection')
    configs = _names(compiled.get('configFiles'), r'[A-Za-z0-9_.-]+\.conf', 'invalid compiled configuration selection')
    _require(enabled == sorted(chosen), 'compiled modules differ from content selection')
    for field in ('files', 'elunaFiles'):
        entries = manifest.get(field)
        _require(isinstance(entries, dict) and len(entries) <= MAX_FILES, 'invalid source file inventory')
        _unique_paths(entries)
        for row in entries.values():
            _identity(row, source=True)
    selected = set(MAIN_CONFIGS)
    plans = manifest.get('databases')
    expected_databases = {'auth', 'characters', 'world'} | ({'playerbots'} if 'mod-playerbots' in enabled else set())
    _require(isinstance(plans, dict) and set(plans) == expected_databases, 'database selection differs from compiled modules')
    for name, plan in plans.items():
        _require(isinstance(plan, dict) and plan.get('executionOrderQualified') is True and
                 isinstance(plan.get('base'), list) and plan['base'] and
                 isinstance(plan.get('updateOrder'), list), 'ambiguous source SQL selection')
        base = plan['base']
        _require(base == sorted(set(base)) and all(str(_path(path).parent) == DATABASES[name] and
                 path.endswith('.sql') for path in base), 'invalid core SQL base selection')
        selected.update(base)
        updates = plan['updateOrder']
        _require(all(isinstance(row, dict) and row.get('state') in
                 ('RELEASED', 'ARCHIVED', 'PENDING', 'CUSTOM', 'MODULE') and
                 isinstance(row.get('origin'), str) and row['origin'] and
                 str(_path(row.get('path'))).endswith('.sql') for row in updates), 'invalid source SQL update selection')
        _require(len(updates) == len({PurePosixPath(row['path']).name for row in updates}), 'duplicate SQL update basename')
        selected.update(row['path'] for row in updates)
    module_rows = manifest.get('modules')
    _require(isinstance(module_rows, list) and all(isinstance(row, dict) for row in module_rows),
             'invalid content module inventory')
    _require([row.get('name') for row in module_rows] == enabled, 'module inventory differs from selection')
    candidates, template_names = {}, []
    for module in module_rows:
        prefix = 'modules/' + module['name'] + '/'
        for field in ('configTemplates', 'notices', 'luaCandidates'):
            values = module.get(field)
            _require(isinstance(values, list) and len(values) == len(set(values)), 'invalid module source selection')
            for path in values:
                _require(str(_path(path)).startswith(prefix) and path in manifest['files'], 'module source selection mismatch')
        for path in module['configTemplates']:
            _require(str(PurePosixPath(path).parent) == prefix + 'conf' and path.endswith('.conf.dist'),
                     'invalid module configuration template')
            template_names.append(PurePosixPath(path).name[:-5])
        selected.update(module['configTemplates'] + module['notices'])
        for path in module['luaCandidates']:
            _require(path.endswith(('.lua', '.ext', '.moon')), 'invalid module Lua candidate')
            candidates[('server', path)] = manifest['files'][path]
    _require(sorted(configs) == sorted(template_names) and len(template_names) == len(set(template_names)),
             'compiled configuration templates differ from source selection')
    selected.update(path for path in manifest['files'] if '/' not in path and
                    path.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'AUTHORS')))
    payload = {}
    for path in selected:
        _require(path in manifest['files'], 'selected source file absent from manifest')
        payload['source/' + path] = ('server', path, manifest['files'][path])
    for path, row in manifest['elunaFiles'].items():
        if path.startswith('extensions/') and path.endswith(('.lua', '.ext', '.moon')):
            candidates[('eluna', path)] = row
        if not path.endswith(('.lua', '.ext', '.moon')):
            payload['source/' + ELUNA + '/' + path] = ('eluna', path, row)
    _require(type(lua.get('formatVersion')) is int and lua['formatVersion'] == 1 and lua.get('mode') == 'disabled' and
             lua.get('serverRevision') == server_source['commit'] and
             lua.get('elunaRevision') == server_source['submodules'][ELUNA], 'only source-matched disabled Lua is supported')
    decisions = lua.get('files')
    _require(isinstance(decisions, list), 'invalid Lua decisions')
    seen = set()
    for row in decisions:
        _require(isinstance(row, dict), 'invalid Lua decision')
        key = (row.get('origin'), row.get('source'))
        _require(key in candidates and key not in seen and row.get('sha256') == candidates[key]['sha256'] and
                 row.get('destination') is None and isinstance(row.get('reason'), str) and row['reason'].strip() and
                 isinstance(row.get('requirements'), list), 'active, duplicate or invalid Lua mapping')
        seen.add(key)
    _require(seen == set(candidates), 'incomplete disabled Lua mapping')
    _unique_paths(payload)
    return payload


def verify(root, receipt_path, receipt_sha256, server_source, source_lock_sha256, compiled_modules,
           *, progress=None, cancelled=None):
    """Verify without writes; cancellation is checked between 128 KiB hash blocks.

    ``progress(event)`` receives phase/path, cumulative bytes/totalBytes,
    fileBytes/fileTotalBytes and completed files/totalFiles. The caller supplies
    the complete original compiled-module object from verified engine provenance.
    """
    _cancel(cancelled)
    _require(isinstance(receipt_sha256, str) and re.fullmatch('[0-9a-f]{64}', receipt_sha256) and
             isinstance(source_lock_sha256, str) and re.fullmatch('[0-9a-f]{64}', source_lock_sha256),
             'explicit content receipt and source-lock hashes required')
    _require(isinstance(server_source, dict) and isinstance(server_source.get('commit'), str) and
             re.fullmatch('[0-9a-f]{40}', server_source['commit']) and
             isinstance(server_source.get('submodules'), dict) and
             isinstance(server_source['submodules'].get(ELUNA), str) and
             re.fullmatch('[0-9a-f]{40}', server_source['submodules'][ELUNA]) and
             isinstance(compiled_modules, dict), 'full expected server source and compiled modules required')
    root_descriptor = receipt_directory = None
    try:
        receipt_path = Path(os.path.abspath(receipt_path))
        _, receipt_directory = _directory(receipt_path.parent)
        receipt_identity, raw = _hash(receipt_directory, receipt_path.name, MAX_METADATA,
                                      cancelled, progress, capture=True)
        _require(receipt_identity['sha256'] == receipt_sha256, 'content receipt outer pin mismatch')
        receipt = _json(raw)
        _require(type(receipt.get('formatVersion')) is int and receipt['formatVersion'] == 1 and
                 receipt.get('scope') == 'immutable-server-source-content-package' and
                 receipt.get('source') == server_source and receipt.get('sourceLockSha256') == source_lock_sha256 and
                 receipt.get('moduleSelectionVerified') is True and receipt.get('archiveReadBackVerified') is True,
                 'source and compiled-module verified content receipt required')
        _require(receipt.get('sourceDirectory') == 'source' and receipt.get('luaMode') == 'disabled' and
                 type(receipt.get('luaFiles')) is int and receipt['luaFiles'] == 0 and
                 receipt.get('configurationRequirements') == {'Eluna.Enabled': False, 'Eluna.ScriptPath': 'lua_scripts'},
                 'only disabled Lua content is supported')
        inventory = receipt.get('archiveFiles')
        _require(isinstance(inventory, dict) and 1 <= len(inventory) <= MAX_FILES and METADATA <= set(inventory),
                 'invalid content archive file inventory')
        directories = _unique_paths(inventory)
        expected = {name: _identity(row) for name, row in inventory.items()}
        total = sum(row['bytes'] for row in expected.values())
        _require(total <= MAX_TOTAL and {name for name in inventory if name.startswith('metadata/')} == METADATA,
                 'content total bound or metadata file set mismatch')
        root, root_descriptor = _directory(root)
        _scan(root_descriptor, inventory, directories, cancelled)
        identities, metadata = {}, {}
        state = dict(bytes=0, files=0, totalBytes=total, totalFiles=len(inventory))
        for name in sorted(inventory):
            capture = name in METADATA
            identities[name], raw = _hash(root_descriptor, name, MAX_METADATA if capture else MAX_PAYLOAD,
                cancelled, progress, expected=expected[name], capture=capture, state=state)
            if capture:
                _require(set(inventory[name]) == {'bytes', 'sha256'}, 'metadata identity has unexpected fields')
                metadata[name] = _json(raw)
        manifest, compiled, lua = (metadata['metadata/' + name + '.json']
                                   for name in ('content-manifest', 'compiled-modules', 'lua-map'))
        _require(compiled == compiled_modules, 'content compiled modules differ from original engine provenance')
        plan = {key: value for key, value in receipt.items()
                if key not in ('archive', 'archiveFiles', 'archiveReadBackVerified', 'deterministicArchive')}
        _require(metadata['metadata/package-plan.json'] == plan, 'content package plan differs from receipt')
        payload = _selection(manifest, compiled, lua, server_source, source_lock_sha256)
        _require(set(inventory) == set(payload) | METADATA, 'content files differ from source-selected payload')
        for name, (origin, path, row) in payload.items():
            expected_row = dict(_identity(row), gitBlob=row['gitBlob'], origin=origin, source=path)
            _require(inventory[name] == expected_row, 'payload identity differs from source manifest')
        _scan(root_descriptor, inventory, directories, cancelled)
        _cancel(cancelled)
        return VerifiedContent(root, root / 'source', manifest, compiled, receipt,
                               dict(receipt=receipt_identity, files=identities))
    except OSError as error:
        raise ContentError('inaccessible, linked or nonregular content path') from error
    finally:
        if root_descriptor is not None:
            os.close(root_descriptor)
        if receipt_directory is not None:
            os.close(receipt_directory)
