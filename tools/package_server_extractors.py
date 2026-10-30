#!/usr/bin/env python3
"""Pair four exact original ARM64 extractor derivatives with debug and notices.

Native checks stop at argument/configuration validation before data conversion.
The original desktop MPQ selection is not a matched custom Esteria data loader.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import selectors
import shutil
import subprocess
import sys
import tempfile
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import manifest_server_modules as modules, owned_process_group as process
from tools import package_server_engine as engine, package_server_engine_notices as notices
from tools import package_server_content as transaction, prepare_runtime as archives
from tools import verify_server_build as files

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/server/extractors-packaging.lock.json'
PROGRAMS = ('map_extractor', 'mmaps_generator', 'vmap4_assembler', 'vmap4_extractor')
CONFIG = 'etc/mmaps-config.yaml'
require = files.require


def load_pin():
    pin, identity = modules.read_json(LOCK)
    require(pin.get('formatVersion') == 1 and
            pin.get('scope') == 'exact-seven-patch-server-extractor-packaging-inputs' and
            pin.get('engineReferenceLock') == files.identity(ROOT / 'runtime/server/engine-reference.lock.json') and
            set(pin.get('originalFiles', {})) == {'bin/' + name for name in PROGRAMS} | {'bin/mmaps-config.yaml'} and
            pin.get('runtimeMount') == '/esteria-server-extractors' and
            pin.get('customEsteriaDataLoadOrderQualified') is False and
            pin.get('clientMpqConversionQualified') is False,
            'exact-extractor-input-pin-required')
    return pin, identity


def validate_inputs(install, compiled, commands, lock, server):
    proof = engine.validate_inputs(install, compiled, commands, lock, server)
    pin, pin_identity = load_pin()
    require(proof['sourceLock']['sha256'] == pin['sourceLockSha256'] and
            proof['buildIdentity'] == pin['originalBuild'] and proof['moduleIdentity'] == pin['originalModules'] and
            proof['build']['integrationRevision'] == pin['integrationRevision'] and
            proof['build']['buildId'] == pin['buildId'], 'extractor-exact-original-build-required')
    listed = {row['path']: row for row in proof['build']['files']}
    for name, expected in pin['originalFiles'].items():
        require(name in listed and engine.identity(listed[name]) == expected and
                files.identity(install / name) == expected, 'extractor-original-file-changed:' + name)
        if name != 'bin/mmaps-config.yaml':
            require(listed[name].get('elf', {}).get('machine') == 'AArch64', 'extractor-original-arm64-required')
            files.elf_header(install / name, executable=True)
    for name, expected in pin['sourceFiles'].items():
        engine.content.safe_path(name)
        require(files.identity(server / name) == expected, 'extractor-reviewed-cli-source-changed:' + name)
    require(files.identity(server / 'src/tools/mmaps_generator/mmaps-config.yaml') ==
            pin['originalFiles']['bin/mmaps-config.yaml'], 'extractor-original-default-configuration-required')
    return proof, pin, pin_identity


def source_notices(source_inputs, derivative):
    audit, audit_identity = notices.load_audit()
    receipt, identity, manifest, captured = notices.read_sources(source_inputs, derivative, audit, audit_identity)
    selected = {}
    for row in audit['noticeCandidates']:
        name = row['path']; origin = 'eluna' if row.get('gitRepository') == 'Eluna' else 'server'
        pristine_name = name[len(engine.content.ELUNA) + 1:] if origin == 'eluna' else name
        source = manifest['pristineGitFiles'][origin].get(pristine_name, {})
        require(source.get('gitBlob') == row['gitBlobSha1'] and source.get('bytes') == row['bytes'] and
                source.get('gitMode') == row['mode'], 'extractor-reviewed-notice-source-mismatch')
        selected['notices/source/' + name] = captured['source/' + name]
    selected['notices/external/' + notices.LUA_NOTICE] = notices.lua_notice(captured[notices.LUA_PATH])
    return dict(receipt=identity, archive=receipt['archive'], manifest=receipt['manifest']), selected


def build(output, install, compiled, commands, lock, server, source_inputs, ndk_archive, objcopy):
    inputs = [archives.directory(Path(os.path.abspath(value))) for value in (install, server, source_inputs)]
    install, server, source_inputs = inputs
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and all(value != output and value not in output.parents and
            output not in value.parents for value in inputs), 'extractor-output-exists-or-overlaps-input')
    proof, pin, pin_identity = validate_inputs(install, compiled, commands, lock, server)
    derivative = dict(formatVersion=1, scope='paired-linux-arm64-server-extractor-derivative',
        integrationRevision=proof['build']['integrationRevision'], buildId=proof['build']['buildId'],
        serverSource=proof['build']['serverSource'], sourcesLock=proof['sourceLock'],
        originalBuild=proof['buildIdentity'], originalModules=proof['moduleIdentity'],
        enabledModules=proof['modules']['enabledModules'], configFiles=proof['modules']['configFiles'],
        packagingPin=pin_identity, runtimeMount=pin['runtimeMount'],
        originalReceiptsPreserved=True, sourceCompanionComplete=False,
        isolatedSourceRebuildQualified=False, derivedExtractorsExecuted=False,
        customEsteriaDataLoadOrderQualified=False, clientMpqConversionQualified=False,
        androidProviderCreated=False, androidRuntimeQualified=False, gameplayQualified=False)
    source_proof, original_notices = source_notices(source_inputs, derivative)
    derivative['sourceInputs'] = source_proof
    strip_lock, _ = modules.read_json(engine.elf.TOOL_LOCK)
    tool = engine.elf.verify_tool(ndk_archive, objcopy, strip_lock['ndkArchive'])
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        runtime, debug = stage / 'runtime', stage / 'debug'
        (runtime / 'bin').mkdir(parents=True, mode=0o700); (debug / 'symbols').mkdir(parents=True, mode=0o700)
        derivatives = {}
        for name in PROGRAMS:
            derivatives[name] = engine.elf.derive(install / 'bin' / name, runtime / 'bin' / name,
                debug / 'symbols' / (name + '.debug'), objcopy, tool)
            require(derivatives[name]['original'] == pin['originalFiles']['bin/' + name],
                    'extractor-original-changed-after-selection')
        derivative['programs'], derivative['stripTool'] = derivatives, tool
        derivative['configuration'] = dict(originalPath='bin/mmaps-config.yaml', installedPath=CONFIG,
                                          **pin['originalFiles']['bin/mmaps-config.yaml'])
        engine.copy_verified(install / 'bin/mmaps-config.yaml', runtime / CONFIG,
                             pin['originalFiles']['bin/mmaps-config.yaml'])
        originals = {'server-build.json': (install / 'server-build.json', proof['buildIdentity']),
                     'server-modules.json': (compiled, proof['moduleIdentity']),
                     'sources.lock.json': (lock, proof['sourceLock']),
                     'extractors-packaging.lock.json': (LOCK, pin_identity)}
        for name, (path, expected) in originals.items():
            for root in (runtime, debug): engine.copy_verified(path, root / 'provenance' / name, expected)
        for name, raw in original_notices.items():
            for root in (runtime, debug): notices.write_notice(root / name, raw)
        engine.copy_verified(commands, debug / 'provenance/compile_commands.json', proof['modules']['compileCommands'])
        for name in ('tools/package_server_extractors.py', 'tools/package_server_engine.py',
                     'tools/package_server_engine_notices.py', 'tools/server_engine_elf.py',
                     'tools/owned_process_group.py', 'tools/verify_server_build.py',
                     'runtime/server/engine-strip.lock.json', 'runtime/server/EXTRACTOR-PACKAGING.md'):
            engine.copy_verified(ROOT / name, debug / 'recipes' / name, files.identity(ROOT / name))
        for root in (runtime, debug):
            engine.put_metadata(root / 'provenance/server-extractors-derivative.json', derivative)
        packages = {}
        for name, root in (('runtime', runtime), ('debug', debug)):
            archive = stage / ('server-extractors-' + name + '-arm64.tar.gz')
            packages[name] = dict(archiveFile=archive.name, inventory=engine.write_archive(root, archive),
                                  archive=files.identity(archive))
        require(files.identity(install / 'server-build.json') == proof['buildIdentity'] and
                files.identity(compiled) == proof['moduleIdentity'] and files.identity(lock) == proof['sourceLock'] and
                files.identity(source_inputs / notices.SOURCE_RECEIPT) == source_proof['receipt'] and
                files.identity(source_inputs / notices.SOURCE_ARCHIVE) == engine.identity(source_proof['archive']),
                'extractor-original-provenance-changed-during-packaging')
        receipt = dict(formatVersion=1, scope='unsealed-server-extractor-packaging', derivative=derivative,
            packages=packages, notices={name: dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                                       for name, raw in original_notices.items()},
            originalNoticeBytesPreserved=True, archiveReadbackVerified=True,
            sourceCompanionRequired=True, sourceCompanionComplete=False,
            clientMpqConversionQualified=False, customEsteriaDataLoadOrderQualified=False,
            androidProviderCreated=False, androidRuntimeQualified=False, gameplayQualified=False)
        engine.put_metadata(stage / 'package-receipt.json', receipt)
        shutil.rmtree(runtime); shutil.rmtree(debug); archives.sync_directory(stage)
        transaction.publish_directory(stage, output); archives.sync_directory(output.parent)
        return receipt
    except BaseException:
        if stage.exists(): print('Unpublished extractor staging retained at ' + str(stage), file=sys.stderr)
        raise


def load_runtime(receipt_path):
    receipt, receipt_identity = modules.read_json(receipt_path); pin, pin_identity = load_pin()
    derivative = receipt.get('derivative', {})
    require(receipt.get('formatVersion') == 1 and receipt.get('scope') == 'unsealed-server-extractor-packaging' and
            receipt.get('archiveReadbackVerified') is True and receipt.get('originalNoticeBytesPreserved') is True and
            derivative.get('scope') == 'paired-linux-arm64-server-extractor-derivative' and
            derivative.get('packagingPin') == pin_identity and derivative.get('originalBuild') == pin['originalBuild'] and
            derivative.get('originalModules') == pin['originalModules'] and
            derivative.get('sourcesLock', {}).get('sha256') == pin['sourceLockSha256'] and
            derivative.get('buildId') == pin['buildId'] and derivative.get('integrationRevision') == pin['integrationRevision'] and
            derivative.get('runtimeMount') == pin['runtimeMount'] and set(derivative.get('programs', {})) == set(PROGRAMS),
            'verified-extractor-runtime-receipt-required')
    row = receipt.get('packages', {}).get('runtime', {})
    require(row.get('archiveFile') == 'server-extractors-runtime-arm64.tar.gz', 'extractor-runtime-archive-name')
    inventory = row.get('inventory'); require(isinstance(inventory, dict) and 1 <= len(inventory) <= 1024,
                                             'extractor-runtime-inventory-bound')
    names = {'bin/' + name for name in PROGRAMS} | {CONFIG} | {'provenance/' + name for name in
        ('server-build.json', 'server-modules.json', 'sources.lock.json', 'extractors-packaging.lock.json',
         'server-extractors-derivative.json')} | set(receipt.get('notices', {}))
    require(set(inventory) == names and len(receipt.get('notices', {})) == 66 and
            all(name.startswith('notices/') for name in receipt['notices']), 'extractor-runtime-exact-file-set')
    require(sum(engine.identity(item)['bytes'] for item in inventory.values()) <= 256 * 1024**2,
            'extractor-runtime-byte-bound')
    for name, item in inventory.items():
        engine.content.safe_path(name)
        require(item.get('mode') == (0o555 if name.startswith('bin/') else 0o444), 'extractor-runtime-file-mode')
    expected_provenance = {'server-build.json': pin['originalBuild'], 'server-modules.json': pin['originalModules'],
        'sources.lock.json': derivative['sourcesLock'], 'extractors-packaging.lock.json': pin_identity}
    require(derivative['sourcesLock'] == files.identity(ROOT / 'sources.lock.json') and
            all(engine.identity(inventory['provenance/' + name]) == expected
                for name, expected in expected_provenance.items()), 'extractor-runtime-original-provenance-binding')
    archive = Path(receipt_path).absolute().parent / row['archiveFile']
    require(files.identity(archive) == row['archive'], 'extractor-runtime-archive-changed')
    engine.verify_archive(archive, inventory)
    for name in PROGRAMS:
        selected = derivative['programs'][name]
        require(selected.get('original') == pin['originalFiles']['bin/' + name] and
                selected.get('stripped') == engine.identity(inventory['bin/' + name]) and
                selected.get('runtimeBytesPreserved') is True and selected.get('debugLinkVerified') is True and
                selected.get('serverExecuted') is False, 'extractor-runtime-program-binding')
    require(engine.identity(inventory[CONFIG]) == pin['originalFiles']['bin/mmaps-config.yaml'],
            'extractor-runtime-configuration-binding')
    for name, expected in receipt['notices'].items():
        require(engine.identity(inventory[name]) == expected, 'extractor-runtime-notice-binding')
    return receipt, receipt_identity, archive, pin


def extract(receipt_path, output):
    receipt, receipt_identity, archive, _ = load_runtime(receipt_path)
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'existing-extractor-install-preserved')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    inventory = receipt['packages']['runtime']['inventory']; seen = set()
    with files.plain_file(archive) as raw, archives.bounded_tar(raw,
            dict(entries=1024, pathBytes=4096, fileBytes=256 * 1024**2)) as incoming:
        for item in incoming:
            require(item.isfile() and item.name in inventory and item.name not in seen,
                    'extractor-extraction-member-set')
            row = inventory[item.name]
            require(item.size == row['bytes'] and item.mode == row['mode'], 'extractor-extraction-metadata')
            target = stage / item.name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with incoming.extractfile(item) as source, target.open('xb') as copied:
                require(archives.hash_stream(source, row['bytes'], copied) == row['sha256'], 'extractor-extraction-hash')
                copied.flush(); os.fsync(copied.fileno())
            target.chmod(row['mode']); seen.add(item.name)
    require(seen == set(inventory), 'extractor-extraction-incomplete')
    archives.sync_directory(stage); transaction.publish_directory(stage, output); archives.sync_directory(output.parent)
    return dict(scope='extractor-runtime-extraction', packageReceipt=receipt_identity,
                archive=receipt['packages']['runtime']['archive'], extractedFiles=len(seen), programsExecuted=False)


def bounded_case(command, cwd, expected):
    child = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, start_new_session=True, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'LANG': 'C'})
    owner = process.OwnedGroup(child); selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ); chunks, count, deadline = [], 0, time.monotonic() + 30
    try:
        while selector.get_map():
            require(time.monotonic() < deadline, 'extractor-cli-timeout')
            for key, _ in selector.select(.1):
                block = os.read(key.fd, files.BUFFER)
                if not block: selector.unregister(key.fd); continue
                count += len(block); require(count <= 64 * 1024, 'extractor-cli-output-bound'); chunks.append(block)
        status = owner.wait(max(.01, deadline - time.monotonic()))
        text = b''.join(chunks).decode('utf-8', errors='strict')
        require(status == expected['exitCode'] and all(token in text for token in expected['contains']),
                'extractor-cli-result-mismatch:' + expected['name'])
        return dict(exitCode=status, output=text)
    finally:
        selector.close(); child.stdout.close(); owner.stop(graceful_timeout=0)


def smoke(install, receipt_path):
    require(platform.system() == 'Linux' and platform.machine().lower() in ('aarch64', 'arm64'),
            'native-arm64-extractor-cli-required')
    receipt, receipt_identity, _, pin = load_runtime(receipt_path)
    install = archives.directory(Path(os.path.abspath(install)))
    inventory = receipt['packages']['runtime']['inventory']
    require({path.relative_to(install).as_posix() for path in files.installed_files(install)} == set(inventory),
            'extractor-installed-file-set-changed')
    for name, row in inventory.items():
        require(files.identity(install / name) == engine.identity(row), 'extractor-installed-file-changed')
    for name in PROGRAMS: files.elf_header(install / 'bin' / name, executable=True)
    require((install / 'provenance/server-extractors-derivative.json').read_bytes() ==
            engine.canonical(receipt['derivative']), 'extractor-installed-derivative-changed')
    outputs = {}
    for case in pin['cliCases']:
        name = case['program']; require(name in PROGRAMS, 'extractor-cli-program-outside-selection')
        require(files.identity(install / 'bin' / name) == engine.identity(inventory['bin/' + name]) and
                files.identity(install / CONFIG) == pin['originalFiles']['bin/mmaps-config.yaml'],
                'extractor-changed-before-cli')
        with tempfile.TemporaryDirectory(prefix='esteria-extractor-cli-') as empty:
            args = [str(install / CONFIG) if value == '@CONFIG@' else value for value in case['arguments']]
            outputs[case['name']] = bounded_case([str(install / 'bin' / name), *args], empty, case)
            require(not list(Path(empty).iterdir()), 'extractor-cli-created-data-output')
    return dict(formatVersion=1, scope='native-arm64-derived-extractor-argument-config-validation-only',
        packageReceipt=receipt_identity, runtimeArchive=receipt['packages']['runtime']['archive'],
        originalBuild=pin['originalBuild'], packagingPin=receipt['derivative']['packagingPin'],
        programs={name: receipt['derivative']['programs'][name]['stripped'] for name in PROGRAMS},
        cases=outputs, qualificationSucceeded=True, emptyWorkingDirectoriesUnchanged=True,
        originalDefaultMmapsConfigParsed=True, clientMpqsSupplied=False, clientMpqConversionQualified=False,
        customEsteriaDataLoadOrderQualified=False, sourceCompanionComplete=False,
        androidRuntimeQualified=False, gameplayQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='operation', required=True)
    packaging = commands.add_parser('build')
    for name in ('output', 'install', 'compiled-modules', 'compile-commands', 'lock', 'server',
                 'source-inputs', 'ndk-archive', 'objcopy'):
        packaging.add_argument('--' + name, type=Path, required=True)
    extraction = commands.add_parser('extract')
    for name in ('package-receipt', 'output'): extraction.add_argument('--' + name, type=Path, required=True)
    check = commands.add_parser('smoke')
    for name in ('install', 'package-receipt', 'output'): check.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.operation == 'build':
        result = build(args.output, args.install, args.compiled_modules, args.compile_commands, args.lock,
                       args.server, args.source_inputs, args.ndk_archive, args.objcopy)
        result = dict(scope=result['scope'], packages={name: row['archive'] for name, row in result['packages'].items()},
                      archiveReadbackVerified=True, sourceCompanionComplete=False, clientMpqConversionQualified=False)
    elif args.operation == 'extract': result = extract(args.package_receipt, args.output)
    else:
        result = smoke(args.install, args.package_receipt)
        engine.put_metadata(args.output, result)
    print(json.dumps(result))


if __name__ == '__main__': main()
