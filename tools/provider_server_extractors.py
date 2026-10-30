#!/usr/bin/env python3
"""Optional extractor provider; real sealed source/debug/CLI receipts are mandatory.

The measured pending pin supports auditing but refuses production provider output.
No extractor, database or game process is executed by this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

try:
    from . import provider_server_programs as shared, package_server_extractors as package, server_provider_sources as source_binding
except ImportError:
    import provider_server_programs as shared, package_server_extractors as package, server_provider_sources as source_binding

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/server/extractors-provider.lock.json'
PROGRAMS = package.PROGRAMS
ASSETS, ARCHIVE = 'server-extractors', 'server-extractors.archive'
SOURCE_ARCHIVE = shared.SOURCE_ARCHIVE
LIMITS = dict(entries=128, memberBytes=8 << 20, fileBytes=16 << 20, pathBytes=512, metadataBytes=1 << 20)
PROVENANCE = {'provenance/' + n for n in ('server-build.json', 'server-modules.json', 'sources.lock.json',
                                        'extractors-packaging.lock.json', 'server-extractors-derivative.json')}
FALSE_FLAGS = ('androidRuntimeQualified', 'gameplayQualified', 'clientMpqConversionQualified',
               'customEsteriaDataLoadOrderQualified')
archives, files, engine = shared.archives, shared.files, shared.engine
require, identity, encoded = shared.require, shared.identity, shared.encoded
read_json, require_file, safe = shared.read_json, shared.require_file, shared.safe
validate_inventory = shared.validate_inventory


def load_pin(sealed=False):
    pin, _ = read_json(LOCK, 128 << 10); original, original_identity = package.load_pin()
    require(pin.get('formatVersion') == 1 and pin.get('scope') == 'measured-server-extractors-provider-inputs' and
            pin.get('state') in ('pending-sealed-source-rebuild', 'sealed-source-and-native-cli') and
            pin.get('nativeArgumentConfigQualified') is True and all(pin.get(k) is False for k in FALSE_FLAGS),
            'server-extractors-input-scope')
    source_binding.validate_current(pin, ROOT / 'sources.lock.json')
    require(pin['serverBuildSourceLock']['sha256'] == original['sourceLockSha256'] and
            pin['packagingPin'] == original_identity and pin['originalBuild'] == original['originalBuild'] and
            pin['originalModules'] == original['originalModules'] and pin['integrationRevision'] == original['integrationRevision'] and
            pin['buildId'] == original['buildId'] and pin['serverSource'] ==
            package.engine.fetch_sources.load_lock(ROOT / 'sources.lock.json')['sources']['server'] and
            pin['serverRevision'] == pin['serverSource']['commit'], 'server-extractors-current-original-source-pin')
    require(validate_inventory(pin['files'], LIMITS['entries'], LIMITS['memberBytes'], LIMITS['fileBytes']) ==
            pin['archiveFileBytes'] and len(pin['files']) == pin['archiveEntries'] and
            pin['archive']['file'] == 'server-extractors-runtime-arm64.tar.gz' and identity(pin['archive'])['bytes'] <= LIMITS['fileBytes'],
            'server-extractors-archive-pin')
    require(set(pin['programPairs']) == set(PROGRAMS) and len(pin['noticeFiles']) == 66 and
            set(pin['noticeFiles']) == {n for n in pin['files'] if n.startswith('notices/')} and
            set(pin['files']) == {'bin/' + n for n in PROGRAMS} | {package.CONFIG} | PROVENANCE | set(pin['noticeFiles']) and
            all(row['mode'] == (0o555 if name.startswith('bin/') else 0o444) for name, row in pin['files'].items()),
            'server-extractors-selected-file-set')
    for name, row in pin['programPairs'].items():
        require(row['original'] == original['originalFiles']['bin/' + name] and
                row['stripped'] == identity(pin['files']['bin/' + name]), 'server-extractors-program-pair-pin')
        identity(row['debug'])
    require(pin['configuration'] == dict(originalPath='bin/mmaps-config.yaml', installedPath=package.CONFIG,
                **original['originalFiles']['bin/mmaps-config.yaml']) and
            identity(pin['files'][package.CONFIG]) == identity(pin['configuration']), 'server-extractors-original-yaml-pin')
    for name, row in (('server-build.json', pin['originalBuild']), ('server-modules.json', pin['originalModules']),
                      ('sources.lock.json', pin['serverBuildSourceLock']), ('extractors-packaging.lock.json', original_identity)):
        require(identity(pin['files']['provenance/' + name]) == row, 'server-extractors-original-provenance-pin')
    for key in ('packageReceipt', 'debugArchive', 'nativeCliReceipt', 'requiredServerRuntimeArchive'):
        identity(pin[key])
    deps, _ = read_json(ROOT / 'runtime/server/android-provider.lock.json')
    require(pin['requiredServerRuntimeArchive'] == deps['archive'] and
            pin['debugArchive']['file'] == 'server-extractors-debug-arm64.tar.gz', 'server-extractors-dependency-or-debug-pin')
    if sealed:
        require(pin['state'] == 'sealed-source-and-native-cli' and pin.get('sourceCompanionComplete') is True and
                isinstance(pin.get('sourceQualification'), dict), 'server-extractors-real-sealed-source-receipt-required')
        for key in ('archive', 'receipt', 'qualification'): identity(pin['sourceQualification'][key])
    else:
        require((pin['state'] == 'pending-sealed-source-rebuild' and pin.get('sourceCompanionComplete') is False and
                 pin.get('sourceQualification') is None) or
                (pin['state'] == 'sealed-source-and-native-cli' and pin.get('sourceCompanionComplete') is True and
                 isinstance(pin.get('sourceQualification'), dict)), 'server-extractors-sealing-state-inconsistent')
    return pin


def validate_package(receipt, pin):
    derivative = receipt.get('derivative', {})
    require(receipt.get('formatVersion') == 1 and receipt.get('scope') == 'unsealed-server-extractor-packaging' and
            receipt.get('archiveReadbackVerified') is True and receipt.get('originalNoticeBytesPreserved') is True and
            receipt.get('sourceCompanionComplete') is False and receipt.get('androidProviderCreated') is False and
            all(receipt.get(k) is False for k in FALSE_FLAGS) and
            receipt['packages']['runtime'] == dict(archiveFile=pin['archive']['file'], archive=identity(pin['archive']), inventory=pin['files']) and
            receipt['packages']['debug']['archive'] == identity(pin['debugArchive']) and
            receipt['packages']['debug']['archiveFile'] == pin['debugArchive']['file'] and
            set(receipt['notices']) == set(pin['noticeFiles']), 'server-extractors-original-package-receipt-required')
    require(derivative.get('formatVersion') == 1 and derivative.get('scope') == 'paired-linux-arm64-server-extractor-derivative' and
            derivative.get('runtimeMount') == '/esteria-server-extractors' and derivative.get('originalReceiptsPreserved') is True and
            derivative['sourcesLock'] == pin['serverBuildSourceLock'] and derivative['serverSource'] == pin['serverSource'] and
            derivative['originalBuild'] == pin['originalBuild'] and derivative['originalModules'] == pin['originalModules'] and
            derivative['integrationRevision'] == pin['integrationRevision'] and derivative['buildId'] == pin['buildId'] and
            derivative['packagingPin'] == pin['packagingPin'] and derivative['sourceInputs'] == pin['originalSourceInputs'] and
            derivative['configuration'] == pin['configuration'] and set(derivative['programs']) == set(PROGRAMS),
            'server-extractors-original-derivative-binding')
    for name, row in derivative['programs'].items():
        require({k: row[k] for k in ('original', 'stripped', 'debug')} == pin['programPairs'][name] and
                row.get('runtimeBytesPreserved') is True and row.get('debugLinkVerified') is True and
                row.get('serverExecuted') is False, 'server-extractors-loaded-byte-debug-proof')
    return derivative


def validate_native(cli, pin):
    original, _ = package.load_pin()
    require(cli.get('formatVersion') == 1 and cli.get('scope') == 'native-arm64-derived-extractor-argument-config-validation-only' and
            cli.get('qualificationSucceeded') is True and cli.get('originalDefaultMmapsConfigParsed') is True and
            cli.get('emptyWorkingDirectoriesUnchanged') is True and cli.get('clientMpqsSupplied') is False and
            cli.get('sourceCompanionComplete') is False and all(cli.get(k) is False for k in FALSE_FLAGS) and
            cli.get('packageReceipt') == pin['packageReceipt'] and cli.get('packagingPin') == pin['packagingPin'] and
            cli.get('originalBuild') == pin['originalBuild'] and cli.get('runtimeArchive') == identity(pin['archive']) and
            cli.get('programs') == {n: pin['programPairs'][n]['stripped'] for n in PROGRAMS} and
            set(cli.get('cases', {})) == {c['name'] for c in original['cliCases']}, 'server-extractors-real-native-cli-binding')
    for case in original['cliCases']:
        actual = cli['cases'][case['name']]
        require(actual.get('exitCode') == case['exitCode'] and isinstance(actual.get('output'), str) and
                len(actual['output'].encode()) <= 65536 and all(token in actual['output'] for token in case['contains']),
                'server-extractors-native-case-differs')


def verify_archive(path, pin, derivative):
    require_file(path, pin['archive']); engine.verify_archive(path, pin['files']); values = {}
    with tempfile.TemporaryDirectory(prefix='esteria-extractor-elf-') as temporary:
        with archives.plain_file(path) as raw, archives.bounded_tar(raw, LIMITS) as tar:
            for item in tar:
                if item.name.startswith('bin/'):
                    dest = Path(temporary) / Path(item.name).name
                    with tar.extractfile(item) as source, dest.open('xb') as target:
                        require(archives.hash_stream(source, item.size, target) == pin['files'][item.name]['sha256'], 'server-extractors-elf-copy')
                    dest.chmod(0o500); shared.elf.elf_header(dest, executable=True)
                elif item.name in PROVENANCE:
                    require(item.size <= 128 << 10, 'server-extractors-provenance-bound')
                    with tar.extractfile(item) as source: values[item.name] = source.read(item.size + 1)
                tar.members.clear()
    require(json.loads(values['provenance/server-extractors-derivative.json']) == derivative,
            'server-extractors-archived-derivative-differs')
    source_binding.validate_archived(values['provenance/sources.lock.json'], pin)
    build, compiled = (json.loads(values['provenance/' + n]) for n in ('server-build.json', 'server-modules.json'))
    require(build['serverSource'] == pin['serverSource'] and build['sourcesLock'] == pin['serverBuildSourceLock'] and
            compiled['serverBuild'] == pin['originalBuild'] and compiled['source'] == pin['serverSource'] and
            compiled['sourceLockSha256'] == pin['serverBuildSourceLock']['sha256'] and
            compiled['generatedListsMatchInstalledBinaries'] is True, 'server-extractors-build-module-source-binding')


def audit(directory, native_cli=None):
    pin = load_pin(); directory = archives.directory(directory)
    require_file(directory / 'package-receipt.json', pin['packageReceipt'])
    receipt, _ = read_json(directory / 'package-receipt.json'); derivative = validate_package(receipt, pin)
    verify_archive(directory / pin['archive']['file'], pin, derivative)
    if native_cli is not None:
        require_file(native_cli, pin['nativeCliReceipt']); cli, _ = read_json(native_cli); validate_native(cli, pin)
    return dict(payloadVerified=True, nativeArgumentConfigReceiptVerified=native_cli is not None,
        archive=pin['archive'], archiveEntries=pin['archiveEntries'], archiveFileBytes=pin['archiveFileBytes'],
        originalNoticeFiles=66, sourceCompanionComplete=False, productionProviderCreated=False,
        clientMpqConversionQualified=False, customEsteriaDataLoadOrderQualified=False,
        androidRuntimeQualified=False, gameplayQualified=False)


def verify_sources(sources, pin):
    q = pin['sourceQualification']
    selected = {'package-receipt.json': pin['packageReceipt'], 'native-cli.json': pin['nativeCliReceipt'],
        'sealed-source-receipt.json': q['receipt'], 'qualification.json': q['qualification'],
        SOURCE_ARCHIVE: q['archive'], pin['debugArchive']['file']: pin['debugArchive']}
    require({p.name for p in sources.iterdir()} == set(selected), 'server-extractors-source-companion-file-set')
    for name, expected in selected.items(): require_file(sources / name, expected)
    receipt, _ = read_json(sources / 'package-receipt.json'); derivative = validate_package(receipt, pin)
    cli, _ = read_json(sources / 'native-cli.json'); validate_native(cli, pin)
    debug = receipt['packages']['debug']['inventory']; validate_inventory(debug, 256, 128 << 20, 256 << 20)
    require({n for n in debug if n.startswith('symbols/')} == {'symbols/' + n + '.debug' for n in PROGRAMS} and
            all(identity(debug['symbols/' + n + '.debug']) == pin['programPairs'][n]['debug'] for n in PROGRAMS),
            'server-extractors-four-debug-pairs-required')
    engine.verify_archive(sources / pin['debugArchive']['file'], debug)
    sealed, _ = read_json(sources / 'sealed-source-receipt.json'); qualified, _ = read_json(sources / 'qualification.json')
    require(sealed.get('formatVersion') == 1 and sealed.get('scope') == 'complete-isolated-server-source-rebuild-companion' and
            all(sealed.get(k) is True for k in ('archiveReadbackVerified', 'sourceCompanionComplete',
                'isolatedSourceRebuildQualified', 'originalUnsealedReceiptsUnchanged')) and
            sealed.get('bitIdenticalOriginalBinariesClaimed') is False and sealed.get('sqlExecuted') is False and
            all(sealed.get(k) is False for k in shared.FALSE_FLAGS) and
            sealed.get('archive') == dict(file=SOURCE_ARCHIVE, **identity(q['archive'])) and
            sealed.get('qualification') == identity(q['qualification']) and
            sealed.get('sourceInputArchive') == identity(pin['originalSourceInputs']['archive']) and
            sealed.get('sourceInputReceipt') == pin['originalSourceInputs']['receipt'] and
            sealed.get('originalBuild') == pin['originalBuild'] and sealed.get('originalCompiledModules') == pin['originalModules'] and
            sealed.get('sourceLock') == pin['serverBuildSourceLock'], 'server-extractors-sealed-source-binding')
    require(qualified.get('formatVersion') == 1 and qualified.get('scope') == 'actual-native-arm64-isolated-server-source-rebuild' and
            qualified.get('phase') == 'complete' and all(qualified.get(k) is True for k in
                ('sourceCompanionComplete', 'isolatedSourceRebuildQualified', 'transitiveIncludeClosureProved', 'fullCompileObserved',
                 'noCompilerCacheUsed', 'fullBuildAndReferencesPassed', 'authWorldVersionExecuted', 'originalSelectionPreserved')) and
            qualified.get('originalBuild') == pin['originalBuild'] and qualified.get('originalCompiledModules') == pin['originalModules'] and
            qualified.get('sourceLock') == pin['serverBuildSourceLock'] and qualified.get('sourceBitIdenticalBinaryClaimed') is False and
            all(qualified.get(k) is False for k in shared.FALSE_FLAGS) and
            qualified.get('sqlExecuted') is False and qualified.get('worldserverSessionStarted') is False and
            all(qualified.get(k, {}).get('relevantBuildEnvironmentMatched') is True
                for k in ('environmentBefore', 'environmentAfter')) and
            qualified.get('network') == dict(interfaces=['lo'], externalNetworkingAvailable=False) and
            all(qualified.get(k, {}).get('exitCode') == 0 for k in ('configure', 'fullBuild', 'referenceBuild', 'install')) and
            set(PROGRAMS) <= set(qualified.get('actualInstalledPrograms', {})), 'server-extractors-actual-full-source-rebuild-required')
    for name in PROGRAMS:
        row = qualified['actualInstalledPrograms'][name]; identity(row)
        require(row.get('elf', {}).get('machine') == 'AArch64', 'server-extractors-rebuilt-program-architecture')
    inventory = sealed['archiveFiles']; validate_inventory(inventory, 20000, 1 << 30, 2 << 30)
    require('rebuild-plan.json' in inventory and identity(inventory['qualification/qualification.json']) == identity(q['qualification']) and
            identity(inventory['inputs/source-inputs/server-engine-source-inputs.tar.gz']) == identity(pin['originalSourceInputs']['archive']) and
            identity(inventory['inputs/source-inputs/source-inputs-receipt.json']) == pin['originalSourceInputs']['receipt'],
            'server-extractors-source-archive-input-binding')
    engine.verify_archive(sources / SOURCE_ARCHIVE, inventory)
    return derivative


def descriptor(pin):
    return dict(formatVersion=1, scope='android-server-extractors-install-only', packageKey='server-extractors-arm64',
        archive=dict(identity(pin['archive']), file=pin['archive']['file'], assetPath=ASSETS + '/' + ARCHIVE),
        requiredFiles={n: dict(identity(row), **({'elfMachine': 183} if n.startswith('bin/') else {})) for n,row in sorted(pin['files'].items())},
        archiveEntries=pin['archiveEntries'], archiveFileBytes=pin['archiveFileBytes'], limits=LIMITS,
        freshSetupFreeBytes=pin['archive']['bytes']+pin['archiveFileBytes']+LIMITS['metadataBytes']+(64 << 20),
        inputLockSha256=files.identity(LOCK)['sha256'], **source_binding.descriptor_fields(pin),
        serverRevision=pin['serverRevision'], integrationRevision=pin['integrationRevision'], buildId=pin['buildId'],
        requiredServerRuntimeArchiveSha256=pin['requiredServerRuntimeArchive']['sha256'], guestMount='/esteria-server-extractors',
        programNames=list(PROGRAMS), originalBuild=pin['originalBuild'], originalModules=pin['originalModules'],
        originalNoticeFiles=66, configuration=pin['configuration'], packagingPin=pin['packagingPin'],
        packageReceipt=pin['packageReceipt'], nativeCliReceipt=pin['nativeCliReceipt'], debugArchive=pin['debugArchive'],
        sourceQualification=pin['sourceQualification'], programPairs=pin['programPairs'], sourceCompanionRequired=True,
        sourceCompanionVerified=pin['sourceCompanionComplete'] is True and pin['sourceQualification'] is not None,
        archiveVerified=True, elfAbiInspected=True, nativeArgumentConfigQualified=True,
        clientMpqConversionQualified=False, customEsteriaDataLoadOrderQualified=False,
        androidRuntimeQualified=False, gameLoginQualified=False, gameplayQualified=False)


def build(directory, native_cli, sealed, debug_archive, output):
    pin = load_pin(sealed=True); directory, sealed = archives.directory(directory), archives.directory(sealed)
    output = Path(os.path.abspath(output)); archives.directory(output.parent)
    require(not os.path.lexists(output) and all(source != output and source not in output.parents and output not in source.parents
            for source in (directory, sealed)), 'server-extractors-output-exists-or-overlaps-input')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.', dir=output.parent))
    try:
        sources = stage / 'sources'; sources.mkdir()
        selected = {'package-receipt.json': (directory / 'package-receipt.json', pin['packageReceipt']),
            'native-cli.json': (native_cli, pin['nativeCliReceipt']),
            'sealed-source-receipt.json': (sealed / 'sealed-source-receipt.json', pin['sourceQualification']['receipt']),
            'qualification.json': (sealed / 'qualification.json', pin['sourceQualification']['qualification']),
            SOURCE_ARCHIVE: (sealed / SOURCE_ARCHIVE, pin['sourceQualification']['archive']),
            pin['debugArchive']['file']: (debug_archive, pin['debugArchive'])}
        for name,(source,expected) in selected.items():
            require_file(source,expected)
            with archives.plain_file(source) as incoming, (sources/name).open('xb') as outgoing:
                require(archives.hash_stream(incoming,expected['bytes'],outgoing)==expected['sha256'],'server-extractors-companion-copy')
                outgoing.flush();os.fsync(outgoing.fileno())
        derivative = verify_sources(sources,pin); assets=stage/'assets'/ASSETS;assets.mkdir(parents=True)
        with archives.plain_file(directory/pin['archive']['file']) as incoming,(assets/ARCHIVE).open('xb') as outgoing:
            require(archives.hash_stream(incoming,pin['archive']['bytes'],outgoing)==pin['archive']['sha256'],'server-extractors-runtime-copy')
            outgoing.flush();os.fsync(outgoing.fileno())
        verify_archive(assets/ARCHIVE,pin,derivative);files.write(assets/'provider.json',encoded(descriptor(pin)));verify(stage)
        for parent,_,_ in os.walk(stage,topdown=False):files.sync_directory(parent)
        shared.transaction.publish_directory(stage,output);files.sync_directory(output.parent)
        return descriptor(pin)
    finally:
        if stage.exists():shutil.rmtree(stage)


def verify(provider,apk=None):
    pin=load_pin(sealed=True);provider=archives.directory(provider)
    require({p.name for p in provider.iterdir()}=={'assets','sources'},'server-extractors-provider-root-closure')
    require({p.name for p in archives.directory(provider/'assets').iterdir()}=={ASSETS},'server-extractors-assets-closure')
    assets=archives.directory(provider/'assets'/ASSETS)
    require({p.name for p in assets.iterdir()}=={ARCHIVE,'provider.json'},'server-extractors-assets-file-set')
    derivative=verify_sources(archives.directory(provider/'sources'),pin);verify_archive(assets/ARCHIVE,pin,derivative)
    require(files.small(assets/'provider.json',128<<10)==encoded(descriptor(pin)),'server-extractors-descriptor-differs')
    if apk is not None:verify_apk(assets,apk)
    return dict(providerVerified=True,sourceCompanionVerified=True,pairedDebugVerified=True,apkBytesVerified=apk is not None,
        nativeArgumentConfigQualified=True,clientMpqConversionQualified=False,customEsteriaDataLoadOrderQualified=False,
        androidRuntimeQualified=False,gameLoginQualified=False,gameplayQualified=False)


def verify_apk(assets,apk):
    # The shared checker uses this module's two fixed names and byte hashes.
    selected={'assets/'+ASSETS+'/'+n for n in (ARCHIVE,'provider.json')}
    with archives.plain_file(apk) as raw,shared.checked_zip(raw,selected,maximum_bytes=2<<30,maximum_entries=4096) as zipped:
        require({n for n in zipped.namelist() if n.startswith('assets/'+ASSETS+'/')}==selected,'server-extractors-apk-asset-closure')
        for name in (ARCHIVE,'provider.json'):
            item=zipped.getinfo('assets/'+ASSETS+'/'+name);path=assets/name
            require(item.file_size==path.stat().st_size and (name!=ARCHIVE or item.compress_type==shared.zipfile.ZIP_STORED),
                    'server-extractors-apk-size-or-compression')
            with zipped.open(item) as incoming,archives.plain_file(path) as original:
                require(archives.hash_stream(incoming,item.file_size)==archives.hash_stream(original,item.file_size),'server-extractors-apk-bytes')


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    inspect=commands.add_parser('audit');inspect.add_argument('--package',type=Path,required=True);inspect.add_argument('--native-cli',type=Path)
    create=commands.add_parser('build')
    for name in ('package','native-cli','sealed','debug-archive','output'):create.add_argument('--'+name,type=Path,required=True)
    check=commands.add_parser('verify');check.add_argument('--provider',type=Path,required=True);check.add_argument('--apk',type=Path)
    args=parser.parse_args()
    if args.command=='audit':result=audit(args.package,args.native_cli)
    elif args.command=='build':result=build(args.package,args.native_cli,args.sealed,args.debug_archive,args.output)
    else:result=verify(args.provider,args.apk)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
