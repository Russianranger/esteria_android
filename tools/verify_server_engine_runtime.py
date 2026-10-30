#!/usr/bin/env python3
"""Verify/extract paired engine derivatives and run explicit native loader checks.

Original build/module receipts remain unchanged. Derived executable identities
are a separate selection, never substituted into an original build manifest.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sys
import tempfile

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import fetch_sources, manifest_server_modules as modules
from tools import package_server_engine as package, prepare_runtime as archives
from tools import package_server_content as transaction
from tools import verify_server_build as files

require = files.require
PROVENANCE = {'provenance/' + name for name in
    ('server-build.json', 'server-modules.json', 'sources.lock.json', 'server-engine-derivative.json')}


def load_receipt(path):
    receipt, receipt_identity = modules.read_json(path)
    derivative = receipt.get('derivative', {})
    require(receipt.get('formatVersion') == 1 and receipt.get('scope') == 'unsealed-server-engine-packaging' and
            receipt.get('archiveReadbackVerified') is True and receipt.get('androidProviderCreated') is False and
            derivative.get('formatVersion') == 1 and
            derivative.get('scope') == 'paired-linux-arm64-server-engine-derivative' and
            derivative.get('runtimeMount') == '/esteria-server-programs' and
            derivative.get('originalReceiptsPreserved') is True and
            set(derivative.get('programs', {})) == set(package.PROGRAMS),
            'verified-paired-engine-package-required')
    row = receipt.get('packages', {}).get('runtime', {})
    require(row.get('archiveFile') == 'server-engine-runtime-arm64.tar.gz', 'engine-runtime-archive-name')
    package.identity(row.get('archive', {}))
    inventory = row.get('inventory')
    require(isinstance(inventory, dict) and 1 <= len(inventory) <= files.MAX_FILES,
            'engine-runtime-inventory-bound')
    total = 0
    for name, item in inventory.items():
        package.content.safe_path(name); package.identity(item)
        require(item.get('mode') == (0o555 if name.startswith('bin/') else 0o444), 'engine-runtime-file-mode')
        total += item['bytes']
    require(total <= package.MAX_ARCHIVE_PAYLOAD, 'engine-runtime-byte-bound')
    archive = Path(path).absolute().parent / row['archiveFile']
    require(files.identity(archive) == row['archive'], 'engine-runtime-archive-changed')
    package.verify_archive(archive, inventory)
    return receipt, receipt_identity, archive


def extract(receipt_path, output):
    receipt, receipt_identity, archive_path = load_receipt(receipt_path)
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'existing-engine-runtime-preserved')
    inventory = receipt['packages']['runtime']['inventory']
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        seen = set()
        with files.plain_file(archive_path) as source, archives.bounded_tar(source,
                dict(entries=files.MAX_FILES, pathBytes=4096, fileBytes=package.MAX_ARCHIVE_PAYLOAD)) as archive:
            for item in archive:
                require(item.isfile() and item.name in inventory and item.name not in seen,
                        'engine-runtime-extract-member-set')
                package.content.safe_path(item.name); row = inventory[item.name]
                require(item.size == row['bytes'] and item.mode == row['mode'] and
                        item.uid == item.gid == item.mtime == 0 and not item.uname and not item.gname,
                        'engine-runtime-extract-metadata')
                target = stage / item.name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with archive.extractfile(item) as incoming, target.open('xb') as outgoing:
                    require(archives.hash_stream(incoming, row['bytes'], outgoing) == row['sha256'],
                            'engine-runtime-extract-hash')
                    outgoing.flush(); os.fsync(outgoing.fileno())
                target.chmod(row['mode']); seen.add(item.name)
        require(seen == set(inventory), 'engine-runtime-extract-incomplete')
        archives.sync_directory(stage); transaction.publish_directory(stage, output)
        archives.sync_directory(output.parent)
        return dict(formatVersion=1, scope='engine-derivative-runtime-extraction', packageReceipt=receipt_identity,
                    archive=receipt['packages']['runtime']['archive'], extractedFiles=len(seen),
                    serverExecuted=False, androidRuntimeQualified=False, gameplayQualified=False)
    except BaseException:
        print('Unpublished engine extraction retained at ' + str(stage), file=sys.stderr)
        raise


def verify_install(install, compiled, lock_path, receipt_path):
    """Return original build/templates and separately verified derived programs."""
    receipt, receipt_identity, _ = load_receipt(receipt_path)
    derivative, inventory = receipt['derivative'], receipt['packages']['runtime']['inventory']
    install = archives.directory(Path(os.path.abspath(install)))
    lock = fetch_sources.load_lock(lock_path); source = lock['sources']['server']
    lock_identity = files.identity(lock_path)
    require(derivative.get('serverSource') == source and derivative.get('sourcesLock') == lock_identity,
            'engine-derivative-source-selection-mismatch')
    build, build_identity = modules.read_json(install / 'provenance/server-build.json')
    original_modules, module_identity = modules.read_json(install / 'provenance/server-modules.json')
    stored_derivative, _ = modules.read_json(install / 'provenance/server-engine-derivative.json')
    require(build_identity == derivative.get('originalBuild') and module_identity == derivative.get('originalModules') and
            original_modules == compiled and stored_derivative == derivative and
            files.identity(install / 'provenance/sources.lock.json') == lock_identity,
            'engine-derivative-original-provenance-mismatch')
    require(build.get('schemaVersion') == 1 and build.get('architecture') == 'Linux-ARM64' and
            build.get('serverSource') == source and build.get('sourcesLock') == lock_identity and
            build.get('sourceCheckoutAndPatchesVerified') is True and
            build.get('integrationRevision') == derivative.get('integrationRevision') and
            build.get('buildId') == derivative.get('buildId') and
            compiled.get('serverBuild') == build_identity and compiled.get('source') == source and
            compiled.get('sourceLockSha256') == lock_identity['sha256'] and
            compiled.get('generatedListsMatchInstalledBinaries') is True and
            compiled.get('enabledModules') == derivative.get('enabledModules') and
            compiled.get('configFiles') == derivative.get('configFiles'), 'engine-derivative-build-binding-mismatch')
    listed = {row['path']: row for row in build['files']}
    require(len(listed) == len(build['files']) <= files.MAX_FILES, 'engine-original-inventory-bound')
    configs = package.MAIN_CONFIGS | {'etc/modules/' + name + '.dist' for name in compiled['configFiles']}
    names = configs | {'bin/' + name for name in package.PROGRAMS} | PROVENANCE
    require(set(inventory) == names and
            {path.relative_to(install).as_posix() for path in files.installed_files(install)} == names,
            'engine-derivative-runtime-member-set')
    for name, row in inventory.items():
        require(files.identity(install / name) == package.identity(row), 'engine-derivative-runtime-file-changed')
    for name in configs:
        require(name in listed and package.identity(listed[name]) == package.identity(inventory[name]),
                'engine-derivative-configuration-changed')
    selected = {}
    for name in package.PROGRAMS:
        row = derivative['programs'][name]
        require(row.get('runtimeBytesPreserved') is True and row.get('debugLinkVerified') is True and
                row.get('serverExecuted') is False and
                row.get('original') == package.identity(listed['bin/' + name]) and
                row.get('stripped') == package.identity(inventory['bin/' + name]),
                'engine-derivative-program-binding-mismatch')
        if name in ('worldserver', 'dbimport'):
            require({key: compiled['binaries'][name][key] for key in ('bytes', 'sha256')} == row['original'],
                    'engine-derivative-original-module-program-mismatch')
        files.elf_header(install / 'bin' / name, executable=True)
        selected[name] = dict(row['stripped'])
    proof = dict(formatVersion=1, scope='verified-engine-derivative-program-selection', packageReceipt=receipt_identity,
        runtimeArchive=receipt['packages']['runtime']['archive'], originalBuild=build_identity,
        originalModules=module_identity, programs=selected, originalReceiptsUnchanged=True,
        sourceCompanionComplete=receipt.get('sourceCompanionComplete') is True,
        debugArchiveIdentified=receipt['packages']['debug']['archive'], debugArchiveReadBackHere=False,
        serverExecuted=False, androidRuntimeQualified=False, gameplayQualified=False)
    return build, install / 'etc/dbimport.conf.dist', selected, proof


def smoke(install, lock_path, receipt_path):
    require(platform.system() == 'Linux' and platform.machine().lower() in ('aarch64', 'arm64'),
            'native-arm64-engine-smoke-required')
    compiled, _ = modules.read_json(install / 'provenance/server-modules.json')
    build, _, programs, selection = verify_install(install, compiled, lock_path, receipt_path)
    outputs = {}
    with tempfile.TemporaryDirectory(prefix='esteria-derived-version-') as empty:
        for name in ('authserver', 'worldserver'):
            require(files.identity(install / 'bin' / name) == programs[name], 'engine-changed-before-loader-smoke')
            output = files.bounded_command([str(install / 'bin' / name), '--version'], cwd=empty, timeout=30,
                                           limit=64 * 1024)
            require(build['serverSource']['commit'][:7] in output and 'Unix' in output,
                    'engine-derived-version-output-mismatch')
            outputs[name] = output.strip()
    return dict(formatVersion=1, scope='native-arm64-derived-auth-world-version-only',
        selection=selection, programs=programs, outputs=outputs, qualificationSucceeded=True,
        authWorldVersionExecuted=True, dbimportExecuted=False, sqlExecuted=False,
        androidRuntimeQualified=False, gameplayQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    extraction = sub.add_parser('extract')
    extraction.add_argument('--package-receipt', type=Path, required=True)
    extraction.add_argument('--output', type=Path, required=True)
    loader = sub.add_parser('smoke')
    for name in ('install', 'lock', 'package-receipt', 'output'):
        loader.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.operation == 'extract':
        result = extract(args.package_receipt, args.output)
    else:
        result = smoke(args.install.absolute(), args.lock, args.package_receipt)
        require(not os.path.lexists(args.output), 'existing-engine-smoke-receipt-preserved')
        package.put_metadata(args.output, result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
