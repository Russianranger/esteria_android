#!/usr/bin/env python3
"""Select and restore a source-backed public local-server profile, fail closed.

Absent publication receipts retain the explicitly qualified Actions acquisition
path. A partial or changed publication never silently falls back. Public mode
executes only its complete hash-checked frozen recipe and rechecks the restored
providers using the current application's admission guards.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import release_local_server_components as release

ROOT = release.ROOT
DIRECTORY = 'runtime/server-components-publication'
PUBLICATION = 'published-release.json'
READBACK = 'public-source-readback.json'
require = release.require


def bytes_identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def measured_lock(path):
    lock = release.transport.small_json(path)
    require(type(lock) is dict and set(lock) == {'formatVersion', 'scope', 'repository', 'tag',
        'state', 'targetCommit', 'ownedDraftReleaseId', 'selectedInputs', 'recipeInputs', 'files'} and
        type(lock['formatVersion']) is int and lock['formatVersion'] == 1 and lock['scope'] == release.SCOPE and
        lock['repository'] == release.transport.REPOSITORY and lock['tag'] == release.TAG,
        'public-server-profile-lock-schema')
    if lock['state'] == 'pending-measurement':
        require(all(lock[key] is None for key in ('targetCommit', 'ownedDraftReleaseId', 'selectedInputs',
            'recipeInputs', 'files')), 'public-server-profile-pending-selection')
        return lock
    require(lock['state'] in ('measured-unbound', 'owned-draft-bound') and
        re.fullmatch('[0-9a-f]{40}', lock.get('targetCommit') or '') and
        lock['selectedInputs'] == release.selected_inputs() and
        type(lock['files']) is dict and set(lock['files']) == release.PAYLOAD,
        'public-server-profile-measured-source-selection')
    release.validate_inventory(lock['recipeInputs'], release.MAX_RECIPE)
    require({'tools/release_local_server_components.py', '.github/workflows/preserve-local-server-components.yml',
        *release.SELECTED} <= lock['recipeInputs'].keys(), 'public-server-profile-complete-recipe-required')
    for name, row in lock['selectedInputs'].items():
        require({key: lock['recipeInputs'][name][key] for key in ('bytes', 'sha256')} == row,
            'public-server-profile-recipe-input-binding')
    for row in lock['files'].values():
        require(type(row) is dict and set(row) == {'bytes', 'sha256'} and type(row['bytes']) is int and
            0 < row['bytes'] <= release.MAX_ASSET and re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')),
            'public-server-profile-asset-pin')
    require((lock['state'] == 'measured-unbound' and lock['ownedDraftReleaseId'] is None) or
        (lock['state'] == 'owned-draft-bound' and type(lock['ownedDraftReleaseId']) is int and
            lock['ownedDraftReleaseId'] > 0), 'public-server-profile-owned-release-selection')
    return lock


def expected_assets(lock):
    expected = dict(lock['files'])
    raw = release.encoded(dict(formatVersion=1, scope=release.SCOPE, targetCommit=lock['targetCommit'],
        tag=release.TAG, selectedInputs=lock['selectedInputs'], assets=lock['files']))
    expected['release-manifest.json'] = bytes_identity(raw)
    raw = ''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(expected.items())).encode()
    expected['SHA256SUMS'] = bytes_identity(raw)
    require(set(expected) == release.ALL_FILES, 'public-server-profile-twelve-asset-closure')
    return expected


def selection(root=ROOT):
    root = Path(root)
    lock_path = root / DIRECTORY / 'dependency-release.lock.json'
    lock = measured_lock(lock_path)
    receipt_paths = [root / DIRECTORY / name for name in (PUBLICATION, READBACK)]
    present = [os.path.lexists(path) for path in receipt_paths]
    if not any(present):
        return dict(formatVersion=1, scope='local-game-server-input-selection', source='retained-actions',
            recipeRevision=None, publicationReceiptsPresent=False, runtimeQualified=False, gameplayQualified=False)
    require(all(present), 'public-server-profile-partial-publication-receipts')
    require(lock['state'] == 'owned-draft-bound', 'public-server-profile-owned-published-lock-required')
    published, readback = [release.transport.small_json(path) for path in receipt_paths]
    expected = expected_assets(lock)
    base = 'https://github.com/' + lock['repository'] + '/releases/'
    require(type(published) is dict and set(published) == {'formatVersion', 'repository', 'tag', 'targetCommit',
        'releaseId', 'url', 'githubImmutable', 'publisherNeverOverwrites', 'assets'} and
        type(published['formatVersion']) is int and published['formatVersion'] == 1 and
        published['repository'] == lock['repository'] and published['tag'] == lock['tag'] and
        published['targetCommit'] == lock['targetCommit'] and
        type(published['releaseId']) is int and published['releaseId'] == lock['ownedDraftReleaseId'] and
        published['publisherNeverOverwrites'] is True and type(published['githubImmutable']) is bool and
        published['url'] == base + 'tag/' + lock['tag'] and type(published['assets']) is dict and
        set(published['assets']) == set(expected), 'public-server-profile-publication-receipt')
    for name, row in expected.items():
        require(published['assets'][name] == dict(row, url=base + 'download/' + lock['tag'] + '/' + name),
            'public-server-profile-publication-asset-pin')
    require(type(readback) is dict and set(readback) == {'formatVersion', 'scope', 'releaseId', 'targetCommit',
        'assets', 'allStoredBytesReadBack', 'completeOriginalSourceAndPairedDebugVerified', 'actionsArtifactsUsed',
        *release.FALSE_FLAGS} and type(readback['formatVersion']) is int and readback['formatVersion'] == 1 and
        readback['scope'] == 'anonymous-complete-local-server-public-source-debug-readback' and
        type(readback['releaseId']) is int and readback['releaseId'] == lock['ownedDraftReleaseId'] and
        readback['targetCommit'] == lock['targetCommit'] and readback['assets'] == expected and
        readback['allStoredBytesReadBack'] is True and readback['completeOriginalSourceAndPairedDebugVerified'] is True and
        readback['actionsArtifactsUsed'] is False and all(readback[name] is False for name in release.FALSE_FLAGS),
        'public-server-profile-anonymous-full-source-readback-required')
    return dict(formatVersion=1, scope='local-game-server-input-selection', source='public-release',
        recipeRevision=lock['targetCommit'], releaseId=lock['ownedDraftReleaseId'], publicationReceiptsPresent=True,
        releaseSelection=release.identity(lock_path), publicationReceipt=release.identity(receipt_paths[0]),
        publicSourceReadback=release.identity(receipt_paths[1]), assets=expected,
        runtimeQualified=False, gameplayQualified=False)


def wrapper_attributes(source):
    with release.files.plain_file(source / '.gitattributes') as incoming:
        raw = incoming.read((64 << 10) + 1)
    return len(raw) <= 64 << 10 and b'*.bat text eol=crlf' in raw.splitlines()


def recipe_checkout(source, lock):
    """Read all pinned Git blobs and checkout bytes before importing frozen code."""
    source = release.archives.directory(Path(os.path.abspath(source)))
    environment = dict(os.environ, GIT_OPTIONAL_LOCKS='0', GIT_NO_LAZY_FETCH='1')
    git = ['git', '-c', 'safe.directory=' + str(source), '-C', str(source)]
    def query(*args):
        return subprocess.check_output(git + list(args), env=environment, stderr=subprocess.DEVNULL, timeout=30)
    require(query('rev-parse', 'HEAD').decode().strip() == lock['targetCommit'],
        'public-server-profile-exact-recipe-checkout')
    flags = query('ls-files', '-v', '-z')
    require(len(flags) <= 2 << 20 and all(not row or row.startswith(b'H ') for row in flags.split(b'\0')),
        'public-server-profile-hidden-index-flags')
    query('diff-index', '--quiet', '--cached', 'HEAD', '--'); query('diff-files', '--quiet', '--')
    require(query('ls-files', '--others', '--exclude-standard', '-z') == b'',
        'public-server-profile-untracked-recipe-files')
    roster = query('ls-tree', '-rlz', lock['targetCommit']); rows = {}
    require(len(roster) <= 2 << 20, 'public-server-profile-git-roster-bound')
    total = 0
    for entry in roster.split(b'\0'):
        if not entry: continue
        metadata, raw_name = entry.split(b'\t', 1); mode, kind, blob, size = metadata.split()
        name = raw_name.decode('utf-8')
        require(mode in (b'100644', b'100755') and kind == b'blob' and name in lock['recipeInputs'] and
            name not in rows, 'public-server-profile-recipe-git-member')
        row = lock['recipeInputs'][name]
        total += int(size)
        require(int(size) == row['bytes'] and total <= release.MAX_RECIPE and
            row['mode'] == (0o555 if mode == b'100755' else 0o444), 'public-server-profile-recipe-git-size-mode')
        raw = query('cat-file', 'blob', blob.decode())
        require(len(raw) == row['bytes'] and bytes_identity(raw) == {key: row[key] for key in ('bytes', 'sha256')},
            'public-server-profile-retained-recipe-git-blob')
        with release.files.plain_file(source / name) as incoming: actual = incoming.read(len(raw) * 2 + 1)
        if name == 'gradlew.bat' and actual != raw:
            require(b'\r' not in raw and len(raw) <= 64 << 10 and actual == raw.replace(b'\n', b'\r\n') and
                wrapper_attributes(source),
                'public-server-profile-wrapper-checkout-conversion')
        else: require(actual == raw, 'public-server-profile-recipe-working-file')
        rows[name] = row
    require(rows == lock['recipeInputs'], 'public-server-profile-complete-recipe-git-roster')
    return source


def run_frozen(source, lock_path, environment, operation, destination, inputs=None):
    command = [sys.executable, '-B', str(source / 'tools/release_local_server_components.py'), operation,
        '--release-lock', str(lock_path), '--output', str(destination)]
    if inputs is not None: command += ['--inputs', str(inputs)]
    # Child output is source-owned but a failure must not expand memory before
    # its metadata limit is checked. Private diagnostic bodies stay local.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
        result = subprocess.run(command, cwd=source, env=environment, stdin=subprocess.DEVNULL,
            stdout=output, stderr=error, timeout=3600)
        require(result.returncode == 0 and output.tell() <= 2 << 20 and error.tell() <= 2 << 20,
            'public-server-profile-frozen-' + operation + '-failed')
        output.seek(0)
        return json.load(output)


def acquire(source, output, providers, root=ROOT):
    output, providers = Path(os.path.abspath(output)), Path(os.path.abspath(providers))
    require(not os.path.lexists(output) and not os.path.lexists(providers) and
        output != providers and output not in providers.parents and providers not in output.parents,
        'public-server-profile-existing-or-overlapping-output-preserved')
    chosen = selection(root)
    require(chosen['source'] == 'public-release', 'public-server-profile-not-yet-published')
    lock_path = (Path(root) / DIRECTORY / 'dependency-release.lock.json').resolve()
    lock = measured_lock(lock_path); source = recipe_checkout(source, lock)
    require(all(path != source and source not in path.parents and path not in source.parents
        for path in (output, providers)), 'public-server-profile-output-overlaps-frozen-source')
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', GIT_OPTIONAL_LOCKS='0', GIT_NO_LAZY_FETCH='1')
    for name in ('GITHUB_TOKEN', 'GH_TOKEN', 'PYTHONPATH'): environment.pop(name, None)
    release.archives.directory(output.parent, create=True); release.archives.directory(providers.parent, create=True)
    output.mkdir(mode=0o700)
    readback = run_frozen(source, lock_path, environment, 'fetch-published', output / 'release')
    require(readback == release.transport.small_json(Path(root) / DIRECTORY / READBACK),
        'public-server-profile-current-anonymous-readback-differs')
    restored = run_frozen(source, lock_path, environment, 'consume', providers, output / 'release')
    require(restored.get('scope') == 'public-local-server-provider-directories-restored' and
        restored.get('selectedInputs') == lock['selectedInputs'] and restored.get('actionsArtifactsUsed') is False and
        restored.get('completeOriginalSourceAndPairedDebugVerified') is True and
        all(restored.get(name) is False for name in release.FALSE_FLAGS), 'public-server-profile-restored-source-scope')
    actual = {}
    for asset, (_, verifier) in release.BUNDLES.items():
        name = release.CONSUMER_DIRECTORIES[asset]
        actual[name] = verifier(providers / name)
    # A later source checkout cannot quietly reinterpret a historical provider.
    require(selection(root) == chosen, 'public-server-profile-selection-changed-during-acquisition')
    receipt = dict(formatVersion=1, scope='public-local-game-server-provider-acquisition', selection=chosen,
        publicReadback=readback, restoredProviders=restored, currentProviderAdmission=actual,
        actionsArtifactsUsed=False, completeOriginalSourceAndPairedDebugVerified=True,
        **{name: False for name in release.FALSE_FLAGS})
    release.engine.put_metadata(output / 'acquisition.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('select', 'acquire'))
    parser.add_argument('--packaging-source', type=Path); parser.add_argument('--output', type=Path)
    parser.add_argument('--providers', type=Path)
    args = parser.parse_args()
    if args.operation == 'select': result = selection()
    else:
        require(args.packaging_source and args.output and args.providers, 'public-server-profile-acquisition-paths-required')
        result = acquire(args.packaging_source, args.output, args.providers)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__': main()
