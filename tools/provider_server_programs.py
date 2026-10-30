#!/usr/bin/env python3
"""Build an install-only server provider after exact source/debug/loader sealing.

The checked-in pending pin permits payload auditing but never provider creation.
No command executes a server, initializes SQL, or changes application state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

try:
    from . import prepare_runtime as archives, package_server_engine as engine, server_provider_sources as source_binding
    from . import package_shader_tools as files, package_server_content as transaction
    from . import verify_server_build as elf
    from .provider_client_runtime import checked_zip
except ImportError:
    import prepare_runtime as archives, package_server_engine as engine, server_provider_sources as source_binding
    import package_shader_tools as files, package_server_content as transaction
    import verify_server_build as elf
    from provider_client_runtime import checked_zip

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/server/programs-provider.lock.json'
PROGRAMS = ('authserver', 'worldserver', 'dbimport')
ASSETS = 'server-programs'
ARCHIVE = 'server-programs.archive'
SOURCE_ARCHIVE = 'server-engine-complete-sources.tar.gz'
LIMITS = dict(entries=256, memberBytes=64 << 20, fileBytes=96 << 20, pathBytes=512, metadataBytes=1 << 20)
PROVENANCE = {'provenance/' + n for n in ('server-build.json', 'server-modules.json', 'sources.lock.json', 'server-engine-derivative.json')}
FALSE_FLAGS = ('androidRuntimeQualified', 'gameplayQualified')
require = archives.require
encoded = engine.canonical


def identity(row):
    require(type(row) is dict and type(row.get('bytes')) is int and 0 <= row['bytes'] <= 4 << 30 and
            re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')), 'server-programs-invalid-identity')
    return {k: row[k] for k in ('bytes', 'sha256')}


def safe(name):
    require(type(name) is str and len(name.encode()) <= LIMITS['pathBytes'], 'server-programs-path-bound')
    engine.content.safe_path(name)
    return name


def read_json(path, maximum=8 << 20):
    raw = files.small(Path(os.path.abspath(path)), maximum)
    return json.loads(raw), dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def require_file(path, pin):
    require(files.identity(Path(os.path.abspath(path)), 4 << 30) == identity(pin), 'server-programs-pinned-file-differs:' + Path(path).name)


def validate_inventory(inventory, maximum_entries, maximum_file, maximum_total):
    require(type(inventory) is dict and 0 < len(inventory) <= maximum_entries, 'server-programs-file-count-bound')
    total = 0
    for name, row in inventory.items():
        safe(name); identity(row)
        require(row['bytes'] <= maximum_file and row.get('mode') in (0o444, 0o555), 'server-programs-file-size-or-mode')
        total += row['bytes']
    require(total <= maximum_total, 'server-programs-total-byte-bound')
    return total


def load_pin(sealed=False):
    pin, _ = read_json(LOCK, 128 << 10)
    require(type(pin.get('formatVersion')) is int and pin['formatVersion'] == 1 and
            pin.get('scope') == 'measured-server-programs-provider-inputs' and
            pin.get('state') in ('pending-sealed-source-rebuild', 'sealed-source-and-native-loader') and
            all(pin.get(k) is False for k in FALSE_FLAGS) and pin.get('nativeAuthWorldVersionQualified') is True,
            'server-programs-input-scope')
    source_binding.validate_current(pin, ROOT / 'sources.lock.json')
    require(re.fullmatch('[0-9a-f]{40}', pin.get('serverRevision', '')) and
            re.fullmatch('[0-9a-f]{40}', pin.get('integrationRevision', '')), 'server-programs-current-source-pin')
    total = validate_inventory(pin['files'], LIMITS['entries'], LIMITS['memberBytes'], LIMITS['fileBytes'])
    require(total == pin['archiveFileBytes'] and len(pin['files']) == pin['archiveEntries'] and
            pin['archive']['file'] == 'server-programs-runtime-arm64.tar.gz' and
            identity(pin['archive'])['bytes'] <= LIMITS['fileBytes'], 'server-programs-archive-pin')
    require(set(pin['programPairs']) == set(PROGRAMS) and
            {n for n in pin['files'] if n.startswith('bin/')} == {'bin/' + n for n in PROGRAMS} and
            set(pin['noticeFiles']) == {n for n in pin['files'] if n.startswith('notices/')} and
            PROVENANCE <= pin['files'].keys(), 'server-programs-selected-file-set')
    require(all(pin['files'][n]['mode'] == (0o555 if n.startswith('bin/') else 0o444) for n in pin['files']),
            'server-programs-selected-file-mode')
    for name, row in pin['programPairs'].items():
        require(identity(row['stripped']) == identity(pin['files']['bin/' + name]), 'server-programs-pair-pin')
        identity(row['original']); identity(row['debug'])
    for key in ('packageReceipt', 'originalPackageReceipt', 'originalRuntimeArchive', 'originalBuild', 'originalModules',
                'debugArchive', 'nativeLoaderReceipt', 'requiredServerRuntimeArchive', 'noticeAudit'):
        identity(pin[key])
    deps, _ = read_json(ROOT / 'runtime/server/android-provider.lock.json')
    require(pin['requiredServerRuntimeArchive'] == deps['archive'], 'server-programs-dependency-selection-differs')
    if sealed:
        require(pin.get('state') == 'sealed-source-and-native-loader' and pin.get('sourceCompanionComplete') is True and
                type(pin.get('sourceQualification')) is dict, 'server-programs-real-sealed-source-receipt-required')
        for key in ('archive', 'receipt', 'qualification'):
            identity(pin['sourceQualification'][key])
    else:
        require((pin['state'] == 'pending-sealed-source-rebuild' and pin.get('sourceCompanionComplete') is False and
                 pin.get('sourceQualification') is None) or
                (pin['state'] == 'sealed-source-and-native-loader' and pin.get('sourceCompanionComplete') is True and
                 type(pin.get('sourceQualification')) is dict), 'server-programs-sealing-state-inconsistent')
    return pin


def validate_package(receipt, pin):
    derivative = receipt.get('derivative', {})
    require(receipt.get('formatVersion') == 1 and receipt.get('scope') == 'notice-augmented-server-programs-runtime' and
            receipt.get('archiveReadbackVerified') is True and receipt.get('originalNoticeBytesPreserved') is True and
            receipt.get('originalRuntimeFilesUnchanged') is True and receipt.get('originalReceiptsPreserved') is True and
            receipt.get('sourceCompanionComplete') is False and receipt.get('androidProviderCreated') is False and
            receipt.get('serverExecuted') is False and all(receipt.get(k) is False for k in FALSE_FLAGS),
            'server-programs-original-notice-receipt-required')
    require(receipt['archive'] == pin['archive'] and receipt['archiveFiles'] == pin['files'] and
            receipt['originalEnginePackageReceipt'] == identity(pin['originalPackageReceipt']) and
            receipt['originalRuntimeArchive'] == pin['originalRuntimeArchive'] and
            receipt['sourceInputs'] == pin['originalSourceInputs'] and receipt['noticeAudit'] == pin['noticeAudit'] and
            set(receipt['notices']) == set(pin['noticeFiles']), 'server-programs-package-provenance-differs')
    require(derivative.get('formatVersion') == 1 and derivative.get('scope') == 'paired-linux-arm64-server-engine-derivative' and
            derivative.get('runtimeMount') == '/esteria-server-programs' and derivative.get('originalReceiptsPreserved') is True and
            derivative['serverSource'] == pin['serverSource'] and
            derivative['sourcesLock'] == pin['serverBuildSourceLock'] and derivative['originalBuild'] == pin['originalBuild'] and
            derivative['originalModules'] == pin['originalModules'] and derivative['integrationRevision'] == pin['integrationRevision'] and
            derivative['buildId'] == pin['buildId'] and derivative['serverSource']['commit'] == pin['serverRevision'] and
            set(derivative['programs']) == set(PROGRAMS), 'server-programs-derivative-binding-differs')
    for name, row in derivative['programs'].items():
        require({k: row[k] for k in ('original', 'stripped', 'debug')} == pin['programPairs'][name] and
                row.get('runtimeBytesPreserved') is True and row.get('debugLinkVerified') is True and
                row.get('serverExecuted') is False, 'server-programs-loaded-byte-or-debug-proof-differs')
    return derivative


def verify_archive(path, pin, derivative):
    require_file(path, pin['archive'])
    engine.verify_archive(path, pin['files'])
    values = {}
    with tempfile.TemporaryDirectory(prefix='esteria-server-programs-elf-') as temporary:
        with archives.plain_file(path) as raw, archives.bounded_tar(raw, LIMITS) as tar:
            for item in tar:
                if item.name.startswith('bin/'):
                    destination = Path(temporary) / Path(item.name).name
                    with tar.extractfile(item) as incoming, destination.open('xb') as outgoing:
                        require(archives.hash_stream(incoming, item.size, outgoing) == pin['files'][item.name]['sha256'],
                                'server-programs-extracted-elf-differs')
                    destination.chmod(0o500); elf.elf_header(destination, executable=True)
                elif item.name in PROVENANCE:
                    require(item.size <= 128 << 10, 'server-programs-provenance-bound')
                    with tar.extractfile(item) as incoming: values[item.name] = incoming.read(item.size + 1)
                tar.members.clear()
    source_binding.validate_archived(values['provenance/sources.lock.json'], pin)
    build = json.loads(values['provenance/server-build.json']); compiled = json.loads(values['provenance/server-modules.json'])
    require(json.loads(values['provenance/server-engine-derivative.json']) == derivative and
            hashlib.sha256(values['provenance/sources.lock.json']).hexdigest() == pin['serverBuildSourceLock']['sha256'] and
            hashlib.sha256(values['provenance/server-build.json']).hexdigest() == pin['originalBuild']['sha256'] and
            hashlib.sha256(values['provenance/server-modules.json']).hexdigest() == pin['originalModules']['sha256'] and
            build['serverSource'] == derivative['serverSource'] and build['sourcesLock'] == pin['serverBuildSourceLock'] and
            compiled['serverBuild'] == pin['originalBuild'] and compiled['sourceLockSha256'] == pin['serverBuildSourceLock']['sha256'] and
            compiled['generatedListsMatchInstalledBinaries'] is True and compiled['enabledModules'] == derivative['enabledModules'] and
            compiled['configFiles'] == derivative['configFiles'], 'server-programs-original-module-binding-differs')
    configs = {'etc/' + n + '.conf.dist' for n in PROGRAMS} | {'etc/modules/' + n + '.dist' for n in compiled['configFiles']}
    require({n for n in pin['files'] if n.startswith('etc/')} == configs and
            set(pin['files']) == configs | {'bin/' + n for n in PROGRAMS} | PROVENANCE | set(pin['noticeFiles']),
            'server-programs-config-or-notice-closure-differs')


def validate_loader(loader, original, pin):
    programs = {n: pin['programPairs'][n]['stripped'] for n in PROGRAMS}
    selection = loader.get('selection', {})
    require(loader.get('formatVersion') == 1 and loader.get('scope') == 'native-arm64-derived-auth-world-version-only' and
            loader.get('qualificationSucceeded') is True and loader.get('authWorldVersionExecuted') is True and
            loader.get('dbimportExecuted') is False and loader.get('sqlExecuted') is False and
            all(loader.get(k) is False for k in FALSE_FLAGS) and loader.get('programs') == programs and
            selection.get('programs') == programs and selection.get('packageReceipt') == identity(pin['originalPackageReceipt']) and
            selection.get('originalBuild') == pin['originalBuild'] and selection.get('originalModules') == pin['originalModules'] and
            selection.get('runtimeArchive') == pin['originalRuntimeArchive'] and
            selection.get('debugArchiveIdentified') == identity(pin['debugArchive']) and
            set(loader.get('outputs', {})) == {'authserver', 'worldserver'} and
            all(pin['serverRevision'][:7] in s and 'Unix' in s for s in loader['outputs'].values()),
            'server-programs-real-derived-native-loader-receipt-required')
    require(original.get('scope') == 'unsealed-server-engine-packaging' and original.get('archiveReadbackVerified') is True and
            original['packages']['runtime']['archive'] == pin['originalRuntimeArchive'] and
            original['packages']['debug']['archive'] == identity(pin['debugArchive']), 'server-programs-original-pair-receipt-differs')


def audit(package, original_receipt=None, native_loader=None):
    pin = load_pin(); package = archives.directory(package)
    require_file(package / 'package-receipt.json', pin['packageReceipt'])
    receipt, _ = read_json(package / 'package-receipt.json'); derivative = validate_package(receipt, pin)
    verify_archive(package / pin['archive']['file'], pin, derivative)
    if original_receipt is not None or native_loader is not None:
        require(original_receipt is not None and native_loader is not None, 'server-programs-both-native-evidence-files-required')
        require_file(original_receipt, pin['originalPackageReceipt']); require_file(native_loader, pin['nativeLoaderReceipt'])
        original, _ = read_json(original_receipt); loader, _ = read_json(native_loader); validate_loader(loader, original, pin)
    return dict(payloadVerified=True, originalNoticeFiles=len(pin['noticeFiles']), archive=pin['archive'],
                archiveEntries=pin['archiveEntries'], archiveFileBytes=pin['archiveFileBytes'],
                nativeLoaderReceiptVerified=native_loader is not None, sourceCompanionComplete=False,
                productionProviderCreated=False, androidRuntimeQualified=False, gameplayQualified=False)


def verify_sources(sources, pin):
    """Exact pinned receipts plus full source/debug member readback; flags alone fail."""
    qualification_pin = pin['sourceQualification']
    expected = {'notice-package-receipt.json', 'original-package-receipt.json', 'native-loader.json',
                'sealed-source-receipt.json', 'qualification.json', SOURCE_ARCHIVE, pin['debugArchive']['file']}
    require({p.name for p in sources.iterdir()} == expected, 'server-programs-source-companion-file-set')
    for name, row in (('notice-package-receipt.json', pin['packageReceipt']), ('original-package-receipt.json', pin['originalPackageReceipt']),
                      ('native-loader.json', pin['nativeLoaderReceipt']), ('sealed-source-receipt.json', qualification_pin['receipt']),
                      ('qualification.json', qualification_pin['qualification']), (SOURCE_ARCHIVE, qualification_pin['archive']),
                      (pin['debugArchive']['file'], pin['debugArchive'])):
        require_file(sources / name, row)
    notice, _ = read_json(sources / 'notice-package-receipt.json'); derivative = validate_package(notice, pin)
    original, _ = read_json(sources / 'original-package-receipt.json'); loader, _ = read_json(sources / 'native-loader.json')
    validate_loader(loader, original, pin)
    require(original['derivative'] == derivative, 'server-programs-original-derivative-receipt-differs')
    debug_inventory = original['packages']['debug']['inventory']
    validate_inventory(debug_inventory, 128, 3 << 30, 4 << 30)
    for name in PROGRAMS:
        require(identity(debug_inventory['symbols/' + name + '.debug']) == pin['programPairs'][name]['debug'],
                'server-programs-debug-companion-pair-differs')
    engine.verify_archive(sources / pin['debugArchive']['file'], debug_inventory)
    sealed, _ = read_json(sources / 'sealed-source-receipt.json')
    qualified, _ = read_json(sources / 'qualification.json')
    require(sealed.get('formatVersion') == 1 and sealed.get('scope') == 'complete-isolated-server-source-rebuild-companion' and
            sealed.get('archiveReadbackVerified') is True and sealed.get('sourceCompanionComplete') is True and
            sealed.get('isolatedSourceRebuildQualified') is True and sealed.get('originalUnsealedReceiptsUnchanged') is True and
            sealed.get('bitIdenticalOriginalBinariesClaimed') is False and sealed.get('sqlExecuted') is False and
            all(sealed.get(k) is False for k in FALSE_FLAGS) and
            sealed.get('archive') == dict(file=SOURCE_ARCHIVE, **identity(qualification_pin['archive'])) and
            sealed.get('qualification') == identity(qualification_pin['qualification']) and
            sealed.get('sourceInputArchive') == identity(pin['originalSourceInputs']['archive']) and
            sealed.get('sourceInputReceipt') == pin['originalSourceInputs']['receipt'] and
            sealed.get('originalBuild') == pin['originalBuild'] and sealed.get('originalCompiledModules') == pin['originalModules'] and
            sealed.get('sourceLock') == pin['serverBuildSourceLock'], 'server-programs-sealed-source-binding-differs')
    require(qualified.get('formatVersion') == 1 and qualified.get('scope') == 'actual-native-arm64-isolated-server-source-rebuild' and
            qualified.get('phase') == 'complete' and all(qualified.get(k) is True for k in
                ('sourceCompanionComplete', 'isolatedSourceRebuildQualified', 'transitiveIncludeClosureProved', 'fullCompileObserved',
                 'noCompilerCacheUsed', 'fullBuildAndReferencesPassed', 'authWorldVersionExecuted', 'originalSelectionPreserved')) and
            qualified.get('originalBuild') == pin['originalBuild'] and qualified.get('originalCompiledModules') == pin['originalModules'] and
            qualified.get('sourceLock') == pin['serverBuildSourceLock'] and qualified.get('sourceBitIdenticalBinaryClaimed') is False and
            all(qualified.get(k) is False for k in FALSE_FLAGS) and
            qualified.get('network') == dict(interfaces=['lo'], externalNetworkingAvailable=False) and
            all(qualified.get(k, {}).get('exitCode') == 0 for k in ('configure', 'fullBuild', 'referenceBuild', 'install')),
            'server-programs-full-isolated-source-compile-required')
    inventory = sealed['archiveFiles']; validate_inventory(inventory, 20000, 1 << 30, 2 << 30)
    require('rebuild-plan.json' in inventory and
            identity(inventory['qualification/qualification.json']) == identity(qualification_pin['qualification']) and
            identity(inventory['inputs/source-inputs/server-engine-source-inputs.tar.gz']) == identity(pin['originalSourceInputs']['archive']) and
            identity(inventory['inputs/source-inputs/source-inputs-receipt.json']) == pin['originalSourceInputs']['receipt'],
            'server-programs-source-archive-original-input-binding-differs')
    engine.verify_archive(sources / SOURCE_ARCHIVE, inventory)
    return derivative


def descriptor(pin):
    required = {n: dict(identity(row), **({'elfMachine': 183} if n.startswith('bin/') else {})) for n, row in sorted(pin['files'].items())}
    return dict(formatVersion=1, scope='android-server-programs-install-only', packageKey='server-programs-arm64',
        archive=dict(identity(pin['archive']), file=pin['archive']['file'], assetPath=ASSETS + '/' + ARCHIVE),
        requiredFiles=required, archiveEntries=pin['archiveEntries'], archiveFileBytes=pin['archiveFileBytes'], limits=LIMITS,
        freshSetupFreeBytes=pin['archive']['bytes']+pin['archiveFileBytes']+LIMITS['metadataBytes']+(64 << 20),
        inputLockSha256=files.identity(LOCK)['sha256'], **source_binding.descriptor_fields(pin),
        serverRevision=pin['serverRevision'], integrationRevision=pin['integrationRevision'], buildId=pin['buildId'],
        requiredServerRuntimeArchiveSha256=pin['requiredServerRuntimeArchive']['sha256'],
        guestMount='/esteria-server-programs', programNames=list(PROGRAMS), originalBuild=pin['originalBuild'],
        originalModules=pin['originalModules'], originalNoticeFiles=len(pin['noticeFiles']),
        sourceQualification=pin['sourceQualification'], debugArchive=pin['debugArchive'], nativeLoaderReceipt=pin['nativeLoaderReceipt'],
        programPairs=pin['programPairs'], sourceCompanionRequired=True, sourceCompanionVerified=True,
        archiveVerified=True, elfAbiInspected=True, nativeAuthWorldVersionQualified=True,
        androidRuntimeQualified=False, gameLoginQualified=False, gameplayQualified=False)


def build(package, original_receipt, native_loader, sealed, debug_archive, output):
    pin = load_pin(sealed=True)
    package = archives.directory(package); sealed = archives.directory(sealed)
    output = Path(os.path.abspath(output)); archives.directory(output.parent)
    require(not os.path.lexists(output), 'server-programs-provider-output-exists')
    for source in (package, sealed):
        require(source != output and source not in output.parents and output not in source.parents, 'server-programs-overlapping-output')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.', dir=output.parent))
    try:
        sources = stage / 'sources'; sources.mkdir()
        selected = {
            'notice-package-receipt.json': (package / 'package-receipt.json', pin['packageReceipt']),
            'original-package-receipt.json': (original_receipt, pin['originalPackageReceipt']),
            'native-loader.json': (native_loader, pin['nativeLoaderReceipt']),
            'sealed-source-receipt.json': (sealed / 'sealed-source-receipt.json', pin['sourceQualification']['receipt']),
            'qualification.json': (sealed / 'qualification.json', pin['sourceQualification']['qualification']),
            SOURCE_ARCHIVE: (sealed / SOURCE_ARCHIVE, pin['sourceQualification']['archive']),
            pin['debugArchive']['file']: (debug_archive, pin['debugArchive'])}
        for name, (source, expected) in selected.items():
            require_file(source, expected)
            with archives.plain_file(source) as incoming, (sources / name).open('xb') as outgoing:
                require(archives.hash_stream(incoming, expected['bytes'], outgoing) == expected['sha256'],
                        'server-programs-companion-copy-differs')
                outgoing.flush(); os.fsync(outgoing.fileno())
        derivative = verify_sources(sources, pin)
        assets = stage / 'assets' / ASSETS; assets.mkdir(parents=True)
        with archives.plain_file(package / pin['archive']['file']) as incoming, (assets / ARCHIVE).open('xb') as outgoing:
            require(archives.hash_stream(incoming, pin['archive']['bytes'], outgoing) == pin['archive']['sha256'], 'server-programs-copy-differs')
            outgoing.flush(); os.fsync(outgoing.fileno())
        verify_archive(assets / ARCHIVE, pin, derivative)
        files.write(assets / 'provider.json', encoded(descriptor(pin))); verify(stage)
        for directory, _, _ in os.walk(stage, topdown=False): files.sync_directory(directory)
        transaction.publish_directory(stage, output); files.sync_directory(output.parent)
        return descriptor(pin)
    finally:
        if stage.exists(): shutil.rmtree(stage)


def verify(provider, apk=None):
    pin = load_pin(sealed=True); provider = archives.directory(provider)
    require({p.name for p in provider.iterdir()} == {'assets', 'sources'}, 'server-programs-provider-root-closure')
    require({p.name for p in archives.directory(provider / 'assets').iterdir()} == {ASSETS}, 'server-programs-assets-closure')
    assets = archives.directory(provider / 'assets' / ASSETS)
    require({p.name for p in assets.iterdir()} == {ARCHIVE, 'provider.json'}, 'server-programs-assets-file-set')
    derivative = verify_sources(archives.directory(provider / 'sources'), pin)
    verify_archive(assets / ARCHIVE, pin, derivative)
    require(files.small(assets / 'provider.json', 128 << 10) == encoded(descriptor(pin)), 'server-programs-descriptor-differs')
    if apk is not None: verify_apk(assets, apk)
    return dict(providerVerified=True, sourceCompanionVerified=True, pairedDebugVerified=True, apkBytesVerified=apk is not None,
                nativeAuthWorldVersionQualified=True, androidRuntimeQualified=False, gameLoginQualified=False, gameplayQualified=False)


def verify_apk(assets, apk):
    selected = {'assets/' + ASSETS + '/' + name for name in (ARCHIVE, 'provider.json')}
    with archives.plain_file(apk) as raw, checked_zip(raw, selected, maximum_bytes=2 << 30, maximum_entries=4096) as archive:
        require({n for n in archive.namelist() if n.startswith('assets/' + ASSETS + '/')} == selected, 'server-programs-apk-asset-closure')
        for name in (ARCHIVE, 'provider.json'):
            item = archive.getinfo('assets/' + ASSETS + '/' + name); path = assets / name
            require(item.file_size == path.stat().st_size and (name != ARCHIVE or item.compress_type == zipfile.ZIP_STORED),
                    'server-programs-apk-size-or-compression')
            with archive.open(item) as incoming, archives.plain_file(path) as original:
                require(archives.hash_stream(incoming, item.file_size) == archives.hash_stream(original, item.file_size), 'server-programs-apk-bytes-differ')


def main():
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='command', required=True)
    inspect = commands.add_parser('audit'); inspect.add_argument('--package', type=Path, required=True)
    inspect.add_argument('--original-receipt', type=Path); inspect.add_argument('--native-loader', type=Path)
    create = commands.add_parser('build')
    for name in ('package', 'original-receipt', 'native-loader', 'sealed', 'debug-archive', 'output'):
        create.add_argument('--' + name, type=Path, required=True)
    check = commands.add_parser('verify'); check.add_argument('--provider', type=Path, required=True); check.add_argument('--apk', type=Path)
    args = parser.parse_args()
    if args.command == 'audit': result = audit(args.package, args.original_receipt, args.native_loader)
    elif args.command == 'build': result = build(args.package, args.original_receipt, args.native_loader, args.sealed, args.debug_archive, args.output)
    else: result = verify(args.provider, args.apk)
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
