#!/usr/bin/env python3
"""Package paired Linux ARM64 engine/debug derivatives from a verified install.

This preparatory layer produces no Android provider. A complete corresponding-
source companion and actual derived-engine runtime gates are still required.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import tempfile

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import fetch_sources, manifest_server_content as content
from tools import manifest_server_modules as modules, package_server_content as package
from tools import provider_server_runtime as provider, server_engine_elf as elf
from tools import verify_server_build as files

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = ('authserver', 'worldserver', 'dbimport')
MAIN_CONFIGS = {'etc/' + name + '.conf.dist' for name in PROGRAMS}
MAX_ARCHIVE_PAYLOAD = 8 * 1024**3
require = files.require


class BoundedGNUInfo(tarfile.TarInfo):
    """The writer needs only regular GNU entries and bounded GNU long names."""
    def _proc_pax(self, archive):
        raise ValueError('engine-pax-header-not-supported')

    def _proc_sparse(self, archive):
        raise ValueError('engine-sparse-header-not-supported')

    def _proc_gnulong(self, archive):
        require(self.type == tarfile.GNUTYPE_LONGNAME and 0 < self.size <= 4096,
                'engine-gnu-name-header-bound')
        return super()._proc_gnulong(archive)


def canonical(document):
    return (json.dumps(document, sort_keys=True, indent=2) + '\n').encode()


def identity(row):
    require(type(row.get('bytes')) is int and 0 <= row['bytes'] <= files.MAX_FILE and
            re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')), 'invalid-engine-file-identity')
    return {key: row[key] for key in ('bytes', 'sha256')}


def validate_inputs(install, compiled_path, commands, lock_path, server):
    """Recheck exact source selection and original receipts before any derivation."""
    lock = fetch_sources.load_lock(lock_path)
    pin = lock['sources']['server']
    lock_identity = files.identity(lock_path)
    fetch_sources.verify_checkout(server, pin, fetch_sources.patch_inputs(pin, lock_path.parent))
    build, build_identity = modules.read_json(install / 'server-build.json')
    require(build.get('schemaVersion') == 1 and build.get('architecture') == 'Linux-ARM64' and
            build.get('sourceCheckoutAndPatchesVerified') is True and
            build.get('serverSource') == pin and build.get('sourcesLock') == lock_identity and
            re.fullmatch('[0-9a-f]{40}', build.get('integrationRevision', '')) and
            re.fullmatch('[A-Za-z0-9_.-]{1,128}', build.get('buildId', '')),
            'engine-build-source-selection-mismatch')
    require(build.get('cmakeOptions', {}).get('CMAKE_BUILD_TYPE') == 'RelWithDebInfo' and
            build.get('hostLoaderSmoke', {}).get('qualified') is True,
            'engine-original-debug-build-and-loader-receipt-required')
    rows = build.get('files')
    require(isinstance(rows, list) and len(rows) <= files.MAX_FILES, 'engine-build-inventory-bound')
    listed = {}
    for row in rows:
        content.safe_path(row['path'])
        require(row['path'] not in listed, 'duplicate-engine-build-file')
        identity(row)
        listed[row['path']] = row
    require(files.identity(install / 'sources.lock.json') == lock_identity,
            'engine-installed-source-lock-mismatch')
    compiled, compiled_identity = modules.read_json(compiled_path)
    require(compiled == modules.verify(commands, install, install / 'server-build.json'),
            'engine-compiled-module-receipt-changed')
    require(compiled.get('serverBuild') == build_identity and
            compiled.get('source') == pin and compiled.get('sourceLockSha256') == lock_identity['sha256'],
            'engine-module-build-selection-mismatch')
    configs = MAIN_CONFIGS | {'etc/modules/' + name + '.dist' for name in compiled['configFiles']}
    require(len(configs) == len(MAIN_CONFIGS) + len(compiled['configFiles']) and
            {name for name in listed if name.startswith('etc/')} == configs,
            'engine-installed-configuration-selection-mismatch')
    selected = configs | {'bin/' + name for name in PROGRAMS}
    for name in selected:
        require(name in listed and files.identity(install / name) == identity(listed[name]),
                'engine-selected-installed-file-changed:' + name)
    for name in PROGRAMS:
        require(listed['bin/' + name].get('elf', {}).get('machine') == 'AArch64',
                'engine-program-not-verified-arm64')
        files.elf_header(install / 'bin' / name, executable=True)
    # A future private DSO cannot be silently omitted by this three-program plan.
    known_programs = {'bin/' + name for name in files.REQUIRED_APPS + files.REQUIRED_TOOLS}
    require(not any('elf' in row and name not in known_programs for name, row in listed.items()),
            'engine-private-shared-library-needs-review')
    return dict(build=build, buildIdentity=build_identity, modules=compiled,
                moduleIdentity=compiled_identity, sourceLock=lock_identity,
                configs=sorted(configs), selected={name: identity(listed[name]) for name in selected})


def copy_verified(source, target, expected, mode=0o444):
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with files.plain_file(source) as original, target.open('xb') as copied:
        shutil.copyfileobj(original, copied, files.BUFFER)
        copied.flush(); os.fsync(copied.fileno())
    require(files.identity(target) == expected, 'engine-copy-readback-mismatch')
    target.chmod(mode)


def put_metadata(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
    path.chmod(0o444)


def write_archive(root, output):
    """Read regular files only; normalize all tar and gzip metadata."""
    inventory, total = {}, 0
    with output.open('xb') as raw:
        with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as archive:
                for source in files.installed_files(root):
                    name = source.relative_to(root).as_posix(); content.safe_path(name)
                    row = files.identity(source)
                    row['mode'] = 0o555 if name.startswith('bin/') else 0o444
                    total += row['bytes']
                    require(total <= MAX_ARCHIVE_PAYLOAD, 'engine-archive-payload-bound')
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = row['bytes'], row['mode']
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ''
                    with files.plain_file(source) as stream:
                        reader = package.HashReader(stream, row)
                        archive.addfile(info, reader); reader.finish()
                    inventory[name] = row
        raw.flush(); os.fsync(raw.fileno())
    verify_archive(output, inventory)
    return inventory


def verify_archive(path, inventory):
    seen, total = set(), 0
    with files.plain_file(path) as raw, gzip.GzipFile(fileobj=raw, mode='rb') as compressed:
        with tarfile.open(fileobj=compressed, mode='r|', tarinfo=BoundedGNUInfo) as archive:
            for item in archive:
                content.safe_path(item.name)
                require(item.isfile() and item.name in inventory and item.name not in seen,
                        'engine-archive-member-set')
                row = inventory[item.name]
                require(item.size == row['bytes'] and item.mode == row['mode'] and
                        item.uid == item.gid == item.mtime == 0 and not item.uname and not item.gname,
                        'engine-archive-member-metadata')
                total += item.size
                require(total <= MAX_ARCHIVE_PAYLOAD, 'engine-archive-payload-bound')
                with archive.extractfile(item) as stream:
                    reader = package.HashReader(stream, row)
                    while reader.read(files.BUFFER):
                        pass
                    reader.finish()
                seen.add(item.name)
        trailing = 0
        while block := compressed.read(files.BUFFER):
            # Require the gzip trailer/CRC, with only bounded tar record padding.
            trailing += len(block)
            require(trailing <= tarfile.RECORDSIZE and not any(block), 'engine-archive-trailing-data')
    require(seen == set(inventory), 'engine-archive-members-missing')


def build(output, install, compiled, commands, lock_path, server, ndk_archive, objcopy):
    install = provider.archives.directory(Path(os.path.abspath(install)))
    server = provider.archives.directory(Path(os.path.abspath(server)))
    output = Path(os.path.abspath(output)); provider.archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and all(source not in output.parents and output not in source.parents
            for source in (install, server)), 'engine-output-exists-or-overlaps-input')
    proof = validate_inputs(install, compiled, commands, lock_path, server)
    strip_lock, _ = modules.read_json(elf.TOOL_LOCK)
    tool = elf.verify_tool(ndk_archive, objcopy, strip_lock['ndkArchive'])
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        runtime, debug = stage / 'runtime', stage / 'debug'
        (runtime / 'bin').mkdir(mode=0o700, parents=True)
        (debug / 'symbols').mkdir(mode=0o700, parents=True)
        derivatives = {}
        for name in PROGRAMS:
            derivatives[name] = elf.derive(install / 'bin' / name, runtime / 'bin' / name,
                debug / 'symbols' / (name + '.debug'), objcopy, tool)
            require(derivatives[name]['original'] == proof['selected']['bin/' + name],
                    'engine-original-changed-after-selection')
        for name in proof['configs']:
            copy_verified(install / name, runtime / name, proof['selected'][name])
        originals = {'server-build.json': (install / 'server-build.json', proof['buildIdentity']),
                     'server-modules.json': (compiled, proof['moduleIdentity']),
                     'sources.lock.json': (lock_path, proof['sourceLock'])}
        for name, (source, expected) in originals.items():
            for root in (runtime, debug):
                copy_verified(source, root / 'provenance' / name, expected)
        copy_verified(commands, debug / 'provenance/compile_commands.json', proof['modules']['compileCommands'])
        for name in ('tools/package_server_engine.py', 'tools/server_engine_elf.py',
                     'tools/owned_process_group.py', 'tools/verify_server_build.py',
                     'runtime/server/engine-strip.lock.json'):
            copy_verified(ROOT / name, debug / 'recipes' / name, files.identity(ROOT / name))
        derivative = dict(formatVersion=1, scope='paired-linux-arm64-server-engine-derivative',
            integrationRevision=proof['build']['integrationRevision'], buildId=proof['build']['buildId'],
            serverSource=proof['build']['serverSource'], sourcesLock=proof['sourceLock'],
            originalBuild=proof['buildIdentity'], originalModules=proof['moduleIdentity'], stripTool=tool,
            enabledModules=proof['modules']['enabledModules'], configFiles=proof['modules']['configFiles'],
            programs=derivatives, originalReceiptsPreserved=True, runtimeMount='/esteria-server-programs',
            sourceCompanionComplete=False, isolatedSourceRebuildQualified=False,
            derivedServerExecuted=False, androidProviderCreated=False,
            androidRuntimeQualified=False, gameplayQualified=False)
        for root in (runtime, debug):
            put_metadata(root / 'provenance/server-engine-derivative.json', derivative)
        inventories = {}
        for name, root in (('runtime', runtime), ('debug', debug)):
            archive = stage / ('server-engine-' + name + '-arm64.tar.gz')
            inventories[name] = dict(archiveFile=archive.name, inventory=write_archive(root, archive),
                                     archive=files.identity(archive))
        receipt = dict(formatVersion=1, scope='unsealed-server-engine-packaging',
            derivative=derivative, packages=inventories, archiveReadbackVerified=True,
            sourceCompanionRequired=True, sourceCompanionComplete=False,
            androidProviderCreated=False, androidRuntimeQualified=False, gameplayQualified=False)
        put_metadata(stage / 'package-receipt.json', receipt)
        # The final receipt references these archives, not duplicate expanded trees.
        shutil.rmtree(runtime); shutil.rmtree(debug)
        provider.archives.sync_directory(stage)
        package.publish_directory(stage, output); provider.archives.sync_directory(output.parent)
        return receipt
    except BaseException:
        # Keep partial derivatives private and unpublished for diagnostics.
        if stage.exists():
            print('Unpublished engine staging retained at ' + str(stage), file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('install', 'compiled-modules', 'compile-commands', 'lock', 'server', 'ndk-archive', 'objcopy', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    receipt = build(args.output, args.install, args.compiled_modules, args.compile_commands,
                    args.lock, args.server, args.ndk_archive, args.objcopy)
    print(json.dumps(dict(scope=receipt['scope'], archiveReadbackVerified=True,
        archives={name: value['archive'] for name, value in receipt['packages'].items()},
        sourceCompanionComplete=False, androidProviderCreated=False)))


if __name__ == '__main__':
    main()
