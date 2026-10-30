#!/usr/bin/env python3
"""Stage exact current engine inputs for a separate Linux x64 packaging job.

Downloads occur only on explicit invocation, after a 12 GiB disk preflight and
GitHub provenance checks. No server, database or stripping tool is executed.
Failed staging is retained; only a complete result receives preparation.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import fetch_sources, manifest_server_content as content
from tools import manifest_server_modules as modules, package_server_content as package
from tools import prepare_server_requalification as reference
from tools import qualify_dbimport as importer, verify_server_build as files

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/server/engine-reference.lock.json'
SOURCE_LOCK = ROOT / 'sources.lock.json'
MINIMUM_FREE_BYTES = 12 * 1024**3
require = content.require


def load_pin():
    pin, identity = modules.read_json(LOCK)
    require(pin.get('formatVersion') == 1 and pin.get('scope') == 'exact-current-server-engine-inputs' and
            pin.get('repository') == 'Russianranger/esteria_android', 'invalid-engine-reference-scope')
    require(re.fullmatch('[0-9a-f]{40}', pin.get('integrationRevision', '')) and
            re.fullmatch('[0-9a-f]{64}', pin.get('sourceLockSha256', '')) and
            re.fullmatch('[0-9a-f]{64}', pin.get('runtimeSourceLockSha256', '')) and
            type(pin.get('workflowRun')) is int and pin['workflowRun'] > 0 and
            type(pin.get('job')) is int and pin['job'] > 0 and
            pin.get('buildId') == str(pin['workflowRun']) + '.1' and
            pin.get('minimumFreeBytes') == MINIMUM_FREE_BYTES and
            set(pin.get('artifacts', {})) == {'install', 'content', 'diagnostics'},
            'invalid-engine-reference-identity')
    for row in pin['artifacts'].values():
        require(type(row.get('id')) is int and row['id'] > 0 and type(row.get('bytes')) is int and
                22 <= row['bytes'] < 2 * 1024**3 and re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')),
                'invalid-engine-artifact-pin')
    for flag in ('sourceCompanionComplete', 'androidRuntimeQualified', 'gameplayQualified'):
        require(pin.get(flag) is False, 'invalid-engine-reference-qualification')
    require(files.identity(SOURCE_LOCK)['sha256'] == pin['sourceLockSha256'],
            'current-application-source-lock-differs-from-engine-reference')
    require(files.identity(ROOT / 'runtime/server/sources.lock.json')['sha256'] == pin['runtimeSourceLockSha256'],
            'current-server-dependency-source-lock-differs-from-engine-reference')
    fetch_sources.load_lock(SOURCE_LOCK)
    return pin, identity


def disk_preflight(output):
    usage = shutil.disk_usage(output)
    receipt = dict(formatVersion=1, scope='server-engine-input-disk-preflight',
        minimumFreeBytes=MINIMUM_FREE_BYTES, observedFreeBytes=usage.free,
        sufficientFreeSpace=usage.free >= MINIMUM_FREE_BYTES,
        measurement='shutil.disk_usage.free', downloadsStarted=False,
        engineInputsPrepared=False, androidRuntimeQualified=False, gameplayQualified=False)
    reference.write_new(output / 'disk-preflight.json', reference.encoded(receipt))
    require(receipt['sufficientFreeSpace'], 'server-engine-inputs-require-at-least-12-GiB-free')
    return receipt


def download_inputs(output, api, pin):
    downloads = output / 'downloads'; downloads.mkdir(mode=0o700)
    for name, row in pin['artifacts'].items():
        path = downloads / (name + '.zip')
        api.download(reference.API + '/actions/artifacts/' + str(row['id']) + '/zip', path, row)
        # Github.download streams through the pinned hash before returning. This
        # independent readback also binds custom downloaders and detects disk loss.
        require(files.identity(path) == {key: row[key] for key in ('bytes', 'sha256')},
                'downloaded-engine-artifact-identity-mismatch:' + name)
    return downloads


def repack_content(output, pin, build, compiled, original):
    lock_path = output / 'locked/sources.lock.json'
    require(files.identity(lock_path) == files.identity(SOURCE_LOCK) and
            build['serverSource'] == fetch_sources.load_lock(SOURCE_LOCK)['sources']['server'],
            'engine-source-selection-is-not-current')
    source = build['serverSource']
    fetch_sources.fetch('server', source, output / 'sources', lock_path.parent, False)
    server_path = output / 'sources/server'
    server = content.GitObjects(server_path, source['commit'], prefixes=content.SERVER_PREFIXES)
    eluna = content.GitObjects(server_path / content.ELUNA, source['submodules'][content.ELUNA])
    manifest = content.make_manifest(server, eluna, source, pin['sourceLockSha256'],
                                    compiled['enabledModules'], 'explicit-module-list', True)
    manifest_path = output / 'repacked-content-manifest.json'
    reference.write_new(manifest_path, package.canonical(manifest))
    lua, lua_identity = modules.read_json(ROOT / 'runtime/server-lua-map.json')
    repacked = package.build_package(output / 'content', manifest, files.identity(manifest_path),
        compiled, files.identity(output / 'server-modules.json'), lua, lua_identity, server, eluna)
    require(repacked['source'] == original['source'] and
            repacked['sourceLockSha256'] == original['sourceLockSha256'],
            'engine-content-repack-changed-source-selection')
    return repacked


def prepare(output, api=None):
    output = reference.zip_tools.archives.directory(Path(os.path.abspath(output)).parent, create=True) / output.name
    require(not os.path.lexists(output), 'existing-engine-input-staging-preserved')
    pin, pin_identity = load_pin()
    output.mkdir(mode=0o700)
    disk = disk_preflight(output)
    api = api or reference.Github(os.environ.get('GITHUB_TOKEN'))
    reference.verify_remote(api, pin)
    downloads = download_inputs(output, api, pin)
    install = output / 'install'
    build = reference.extract_install(downloads / 'install.zip', install, pin)
    lock_path = reference.stage_diagnostics(downloads / 'diagnostics.zip', output, install / 'sources.lock.json', pin)
    require(files.identity(lock_path) == files.identity(SOURCE_LOCK),
            'engine-diagnostics-lock-is-not-current-application-lock')
    original = reference.original_metadata(downloads / 'content.zip', output / 'original-content')
    compiled_path = output / 'original-content/server-modules.json'
    compiled, compiled_identity = modules.read_json(compiled_path)
    require(compiled == modules.verify(output / 'compile_commands.json', install, install / 'server-build.json'),
            'engine-original-module-selection-differs-from-binaries')
    importer.verify_install(install, compiled, lock_path)
    manifest, manifest_identity = modules.read_json(output / 'original-content/server-content-manifest.json')
    require(original.get('contentManifest') == manifest_identity and original.get('source') == build['serverSource'] and
            original.get('sourceLockSha256') == pin['sourceLockSha256'] and
            original.get('compiledModules') == compiled_identity and
            original.get('moduleSelectionVerified') is True and original.get('archiveReadBackVerified') is True,
            'engine-original-content-provenance-mismatch')
    package.validate_modules(compiled, manifest)
    raw = compiled_path.read_bytes()
    require(dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) == compiled_identity,
            'engine-original-module-receipt-changed')
    reference.write_new(output / 'server-modules.json', raw)
    # Remove only this invocation's fully verified ZIPs. Their immutable hashes
    # remain in the preparation receipt; partial failures retain all other work.
    for name in pin['artifacts']:
        (downloads / (name + '.zip')).unlink()
    repack_content(output, pin, build, compiled, original)
    evidence = dict(formatVersion=1, scope='exact-current-server-engine-inputs-prepared',
        inputPin=pin_identity, originalInputs=pin, diskPreflight=files.identity(output / 'disk-preflight.json'),
        initialFreeBytes=disk['observedFreeBytes'], serverBuild=files.identity(install / 'server-build.json'),
        compiledModules=compiled_identity, compileCommands=files.identity(output / 'compile_commands.json'),
        sourceLock=files.identity(lock_path), originalContentReceipt=files.identity(output / 'original-content/package-receipt.json'),
        repackedContentReceipt=files.identity(output / 'content/package-receipt.json'),
        currentSourceCheckoutVerified=True, sourceContentRepacked=True,
        preparationSucceeded=True, binariesChanged=False, recompiled=False,
        sourceCompanionComplete=False, strippedDerivativeCreated=False, sqlExecuted=False,
        androidProviderCreated=False, androidRuntimeQualified=False, gameplayQualified=False)
    reference.write_new(output / 'preparation.json', reference.encoded(evidence))
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.output.absolute()), indent=2))
    except Exception as error:
        raise SystemExit('Engine input preparation failed (' + type(error).__name__ + '); partial staging retained') from None


if __name__ == '__main__':
    main()
