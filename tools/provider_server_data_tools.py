#!/usr/bin/env python3
"""Build the separately gated composed four-tool server data provider.

Provider creation requires the actual ordered source/strip/native receipts and both debug
companions; existing stock extractor and server program providers stay separate.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

if not __package__:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import provider_server_programs as shared,provider_server_extractors as stock
from tools import package_server_engine as engine,prepare_runtime as archives
from tools import server_provider_sources as sources,verify_server_build as files
from tools import package_server_content as transaction

ROOT=Path(__file__).resolve().parents[1]
LOCK=ROOT/'runtime/server/data-tools-provider.lock.json'
PROGRAMS=('map_extractor','vmap4_extractor','vmap4_assembler','mmaps_generator')
ORDERED=PROGRAMS[:2]
ASSETS='server-data-tools'
ARCHIVE='server-data-tools.archive'
RUNTIME='server-data-tools-runtime-arm64.tar.gz'
SOURCE_ARCHIVE='ordered-extractor-complete-sources.tar.gz'
SOURCE_RECEIPT='ordered-source-receipt.json'
MOUNT='/esteria-server-extractors'
LIMITS=dict(entries=256,memberBytes=16<<20,fileBytes=64<<20,pathBytes=512,metadataBytes=1<<20)
FALSE_FLAGS=('clientMpqConversionQualified','customEsteriaDataLoadOrderQualified','androidRuntimeQualified',
             'gameLoginQualified','gameplayQualified')
require=files.require
identity=shared.identity
encoded=engine.canonical


def source_inputs(pin):
    """Authenticate the committed source outputs against their measured native inputs."""
    from tools import seal_ordered_extractor_sources as ordered_sources
    measured=ordered_sources.load_pin()
    qualified=pin.get('actualOrderedSourceQualification')
    require(type(qualified) is dict and set(qualified)=={'archive','receipt','nativeBuild','dependencyObservation'},
            'server-data-tools-source-qualification-shape')
    for row in qualified.values():identity(row)
    require(qualified['nativeBuild']==measured['nativeBuild']['receipt'] and
            qualified['dependencyObservation']==measured['nativeBuild']['dependencyObservation'],
            'server-data-tools-measured-native-source-inputs-differ')
    return measured


def load_pin(sealed=False, *, path=None):
    pin,_=shared.read_json(LOCK if path is None else path,128<<10)
    require(type(pin.get('formatVersion')) is int and pin['formatVersion']==1 and
            pin.get('scope')=='measured-server-data-tools-provider-inputs' and
            pin.get('packageKey')=='server-data-tools-arm64' and pin.get('guestMount')==MOUNT and
            pin.get('programNames')==list(PROGRAMS) and all(pin.get(k) is False for k in FALSE_FLAGS),
            'server-data-tools-input-scope')
    sources.validate_current(pin,ROOT/'sources.lock.json')
    current,_=shared.read_json(ROOT/'sources.lock.json')
    require(pin['clientRevision']==current['sources']['client']['commit'] and
            pin['serverRevision']==pin['serverSource']['commit'],'server-data-tools-current-client-or-server-differs')
    original=stock.load_pin()
    require(pin['requiredServerRuntimeArchive']==original['requiredServerRuntimeArchive'] and
            pin['originalServerSourceQualification']==original['sourceQualification'] and
            pin['configuration']=={key:original['configuration'][key] for key in ('installedPath','bytes','sha256')},
            'server-data-tools-original-selection-differs')
    pending=pin.get('state')=='pending-ordered-source-and-derived-native-cli'
    if pending:
        require(pin.get('sourceCompanionComplete') is False and pin.get('nativeArgumentConfigQualified') is False and
                pin.get('originalNoticesPreserved') is False and all(pin.get(k) is None for k in
                ('archive','archiveEntries','archiveFileBytes','packageReceipt','programPairs','nativeCliReceipt',
                 'files','toolSelection','actualOrderedSourceQualification')),'server-data-tools-pending-pin-inconsistent')
        require(not sealed,'server-data-tools-real-ordered-source-and-derived-native-cli-required')
        return pin
    if pin.get('state')=='source-sealed-pending-derived-native-cli':
        require(pin.get('sourceCompanionComplete') is True and pin.get('nativeArgumentConfigQualified') is False and
                pin.get('originalNoticesPreserved') is False and all(pin.get(k) is None for k in
                ('archive','archiveEntries','archiveFileBytes','packageReceipt','programPairs','nativeCliReceipt',
                 'files','toolSelection')),'server-data-tools-source-only-pin-inconsistent')
        source_inputs(pin)
        require(not sealed,'server-data-tools-real-derived-native-cli-required')
        return pin
    require(pin.get('state')=='sealed-source-and-native-cli' and pin.get('sourceCompanionComplete') is True and
            pin.get('nativeArgumentConfigQualified') is True and pin.get('originalNoticesPreserved') is True,
            'server-data-tools-real-ordered-source-and-derived-native-cli-required')
    measured=source_inputs(pin)
    for key in ('archive','packageReceipt','nativeCliReceipt','orderedStripReceipt'):
        identity(pin[key])
    require(pin['archive'].get('file')==RUNTIME and pin['archive']['bytes']<=LIMITS['fileBytes'] and
            set(pin['programPairs'])==set(PROGRAMS),'server-data-tools-runtime-or-program-selection')
    qualified=pin['actualOrderedSourceQualification']
    require(set(pin['debugArchives'])=={'ordered','stock'},'server-data-tools-debug-pair-selection')
    for row in pin['debugArchives'].values():identity(row)
    require(identity(pin['debugArchives']['stock'])==identity(original['debugArchive']),
            'server-data-tools-original-stock-debug-differs')
    total=shared.validate_inventory(pin['files'],LIMITS['entries'],LIMITS['memberBytes'],LIMITS['fileBytes'])
    require(total==pin['archiveFileBytes'] and len(pin['files'])==pin['archiveEntries'] and
            {n for n in pin['files'] if n.startswith('bin/')}=={'bin/'+n for n in PROGRAMS},
            'server-data-tools-complete-inventory')
    for name,pair in pin['programPairs'].items():
        require(set(pair)=={'original','stripped','debug'},'server-data-tools-program-pair-shape')
        for row in pair.values():identity(row)
        require(identity(pair['stripped'])==identity(pin['files']['bin/'+name]),'server-data-tools-stripped-pair-differs')
        if name not in ORDERED:require(pair==original['programPairs'][name],'server-data-tools-stock-program-changed')
        else:require(pair['original']==identity(measured['nativeBuild']['programs'][name]),
                     'server-data-tools-ordered-original-program-differs-from-native-build')
    selection=pin['toolSelection']
    expected={'bin/'+n for n in PROGRAMS}|{'etc/mmaps-config.yaml','provenance/'+SOURCE_RECEIPT}
    require(set(selection)=={'formatVersion','serverRevision','clientRevision','orderedSourceReceipt','files'} and
            type(selection['formatVersion']) is int and selection['formatVersion']==1 and
            selection['serverRevision']==pin['serverRevision'] and selection['clientRevision']==pin['clientRevision'] and
            set(selection['files'])==expected and
            selection['orderedSourceReceipt']==identity(qualified['receipt'])==selection['files']['provenance/'+SOURCE_RECEIPT],
            'server-data-tools-fixed-runtime-selection')
    require(all(row==identity(pin['files'][name]) for name,row in selection['files'].items()) and
            selection['files']['etc/mmaps-config.yaml']==identity(pin['configuration']),
            'server-data-tools-runtime-selection-file-differs')
    for name,row in original['files'].items():
        if name.startswith('notices/'):
            require(pin['files'].get(name)==row,'server-data-tools-original-notice-omitted-or-changed')
    require(all(row['mode']==(0o555 if name.startswith('bin/') else 0o444) for name,row in pin['files'].items()),
            'server-data-tools-runtime-file-mode')
    return pin


def load_source_qualification():
    """Return a validated source-sealed pin; runtime packaging may still be pending."""
    pin=load_pin()
    require(pin.get('state') in ('source-sealed-pending-derived-native-cli','sealed-source-and-native-cli'),
            'server-data-tools-real-ordered-source-qualification-required')
    return pin


def descriptor(pin):
    require(pin['state']=='sealed-source-and-native-cli','server-data-tools-pending-descriptor-refused')
    return dict(formatVersion=1,scope='android-server-data-tools-install-only',packageKey=pin['packageKey'],
        guestMount=MOUNT,archive=dict(pin['archive'],assetPath=ASSETS+'/'+ARCHIVE),
        archiveEntries=pin['archiveEntries'],archiveFileBytes=pin['archiveFileBytes'],limits=LIMITS,
        requiredFiles={name:dict(identity(row),**({'elfMachine':183} if name.startswith('bin/') else {}))
            for name,row in sorted(pin['files'].items())},
        freshSetupFreeBytes=pin['archive']['bytes']+pin['archiveFileBytes']+LIMITS['metadataBytes']+(64<<20),
        inputLockSha256=files.identity(LOCK)['sha256'],**sources.descriptor_fields(pin),
        serverRevision=pin['serverRevision'],clientRevision=pin['clientRevision'],programNames=list(PROGRAMS),
        configuration=pin['configuration'],programPairs=pin['programPairs'],toolSelection=pin['toolSelection'],
        actualOrderedSourceQualification=pin['actualOrderedSourceQualification'],
        originalServerSourceQualification=pin['originalServerSourceQualification'],
        requiredServerRuntimeArchiveSha256=pin['requiredServerRuntimeArchive']['sha256'],
        packageReceipt=pin['packageReceipt'],nativeCliReceipt=pin['nativeCliReceipt'],debugArchives=pin['debugArchives'],
        sourceCompanionRequired=True,sourceCompanionVerified=True,archiveVerified=True,elfAbiInspected=True,
        originalNoticesPreserved=True,nativeArgumentConfigQualified=True,**{name:False for name in FALSE_FLAGS})


def verify_runtime(path,pin):
    shared.require_file(path,pin['archive']);engine.verify_archive(path,pin['files'])
    with files.plain_file(path) as raw,archives.bounded_tar(raw,LIMITS) as archive:
        seen=set()
        for member in archive:
            if member.name.startswith('bin/'):
                require(member.size>=64,'server-data-tools-short-ELF')
                with archive.extractfile(member) as incoming:header=incoming.read(64)
                require(header[:7]==b'\x7fELF\x02\x01\x01' and header[16:18] in (b'\x02\x00',b'\x03\x00') and
                        header[18:20]==b'\xb7\x00' and header[20:24]==b'\x01\x00\x00\x00',
                        'server-data-tools-ARM64-ELF-required')
                seen.add(member.name)
            archive.members.clear()
        require(seen=={'bin/'+name for name in PROGRAMS},'server-data-tools-runtime-program-closure')


def verify_reference_image(cli,pin):
    accepted=cli.get('referenceImageReadback')
    require(type(accepted) is dict and set(accepted)=={'identity','receipt'},
            'server-data-tools-native-reference-image-receipt-required')
    identity(accepted['identity']);image=accepted['receipt']
    require(type(image) is dict and type(image.get('formatVersion')) is int and image['formatVersion']==1 and
            image.get('scope')=='native-arm64-dependency-image-readback' and
            image.get('runtimeArchive')==pin['requiredServerRuntimeArchive'] and
            all(image.get(k) is True for k in ('actualImageMetadataAndElfHashesVerified','nativePythonExecuted')) and
            all(image.get(k) is False for k in ('mysqlServerExecuted','databaseInitialized','esteriaServerExecuted',
                                              'androidRuntimeQualified','gameplayQualified')),
            'server-data-tools-native-reference-image-selection-or-gates')


def validate_native_cli(cli,pin):
    """Retained native evidence must bind every shipped role and exact package."""
    from tools import package_server_extractors as original_cli, build_ordered_extractors as ordered
    require(type(cli.get('formatVersion')) is int and cli['formatVersion']==1 and
            cli.get('scope')=='native-arm64-composed-server-data-tools-cli-only' and
            all(cli.get(k) is True for k in ('qualificationSucceeded','nativeOrderedLookupsQualified',
                'originalStockConfigParsed','shippedRuntimeFilesUnchanged')) and
            cli.get('packageReceipt')==identity(pin['packageReceipt']) and
            cli.get('runtimeArchive')==identity(pin['archive']) and
            cli.get('orderedSourceReceipt')==identity(pin['actualOrderedSourceQualification']['receipt']) and
            cli.get('programs')=={name:pair['stripped'] for name,pair in pin['programPairs'].items()} and
            cli.get('configuration')==identity(pin['configuration']) and
            all(cli.get(k) is False for k in FALSE_FLAGS) and cli.get('sourceCompanionComplete') is False,
            'server-data-tools-real-derived-native-cli-required')
    verify_reference_image(cli,pin)
    original,_=original_cli.load_pin()
    cases=cli.get('cliCases',{})
    require(type(cases) is dict and set(cases)=={row['name'] for row in original['cliCases']},
            'server-data-tools-complete-native-cli-cases-required')
    for case in original['cliCases']:
        actual=cases[case['name']]
        require(type(actual) is dict and type(actual.get('exitCode')) is int and actual['exitCode']==case['exitCode'] and
                type(actual.get('output')) is str and len(actual['output'].encode())<=65536 and
                all(token in actual['output'] for token in case['contains']),
                'server-data-tools-native-cli-result-differs')
    capability=ordered.adaptation.load_pin()['contract']+ordered.CAPABILITY_SUFFIX+'\n'
    require(type(cli.get('capabilities')) is dict and set(cli['capabilities'])==set(ORDERED) and
            all(row==dict(exitCode=0,output=capability) for row in cli['capabilities'].values()),
            'server-data-tools-complete-native-capabilities-required')
    names=cli.get('lookupTestNames')
    require(type(names) is list and names==required_lookup_names() and
            all(type(name) is str and name.startswith('tests.test_extractor_order.RealArchiveReader.test_') for name in names) and
            len(names)==len(set(names)) and
            type(cli.get('lookupTestsRun')) is int and cli['lookupTestsRun']==len(names) and
            type(cli.get('lookupTestsSkipped')) is int and cli['lookupTestsSkipped']==0 and
            type(cli.get('syntheticLookupTests')) is dict and
            type(cli['syntheticLookupTests'].get('exitCode')) is int and cli['syntheticLookupTests']['exitCode']==0,
            'server-data-tools-all-native-lookups-without-skips-required')
    for key in ('cliPhase','lookupResult','fixturePreparation'):
        identity(cli[key])


def required_lookup_names():
    """Require every current source-bound ordered-reader native regression.

    Frozen historical providers retain their historical recipe and test roster;
    they are never reinterpreted as this newly compiled pair.
    """
    import unittest
    from tests.test_extractor_order import RealArchiveReader
    return ['tests.test_extractor_order.RealArchiveReader.'+name for name in
            unittest.defaultTestLoader.getTestCaseNames(RealArchiveReader)]


def verify_sources(directory,pin):
    qualified=pin['actualOrderedSourceQualification'];original=stock.load_pin()
    expected={'package-receipt.json':pin['packageReceipt'],SOURCE_RECEIPT:qualified['receipt'],
        SOURCE_ARCHIVE:qualified['archive'],'native-ordered-build.json':qualified['nativeBuild'],
        'dependency-observation.json':qualified['dependencyObservation'],'native-cli.json':pin['nativeCliReceipt'],
        'ordered-strip-receipt.json':pin['orderedStripReceipt'],
        'ordered-extractors-debug-arm64.tar.gz':pin['debugArchives']['ordered'],
        'stock-package-receipt.json':original['packageReceipt'],
        'stock-extractors-debug-arm64.tar.gz':pin['debugArchives']['stock']}
    require({p.name for p in directory.iterdir()}==set(expected) and
            {p.relative_to(directory).as_posix() for p in files.installed_files(directory)}==set(expected),
            'server-data-tools-source-file-set')
    for name,row in expected.items():shared.require_file(directory/name,row)
    sealed,_=shared.read_json(directory/SOURCE_RECEIPT,16<<20)
    require(sealed.get('scope')=='complete-ordered-extractor-corresponding-source-companion' and
            all(sealed.get(k) is True for k in ('archiveReadbackVerified','orderedSourceCompanionComplete',
                'originalNativeReceiptUnchanged','fullBaseAndApprovedOverlayVerified','actualTargetDependencyObservationVerified')) and
            sealed.get('nativeReceipt')==identity(qualified['nativeBuild']) and
            sealed.get('dependencyObservation')==identity(qualified['dependencyObservation']) and
            sealed.get('serverBuildSourceLock')==pin['serverBuildSourceLock'] and
            sealed.get('originalSourceQualification')==pin['originalServerSourceQualification'] and
            sealed.get('archive')==dict(file=SOURCE_ARCHIVE,**identity(qualified['archive'])) and
            all(sealed.get(k) is False for k in ('newNativeCompilationPerformed','globalServerPatchListChanged',
                'serverProgramsReplaced','worldQualified','androidRuntimeQualified','clientMpqConversionQualified',
                'customEsteriaDataLoadOrderQualified','gameplayQualified')),'server-data-tools-real-ordered-source-seal-required')
    engine.verify_archive(directory/SOURCE_ARCHIVE,sealed['archiveFiles'])
    native,_=shared.read_json(directory/'native-ordered-build.json')
    require(native.get('scope')=='native-arm64-separate-ordered-extractor-target-build-and-synthetic-lookups' and
            native.get('phase')=='complete' and native.get('targets')==list(ORDERED) and
            all(native.get(k) is True for k in ('actualTargetCompileSucceeded','nativeOrderedLookupQualified',
                'compilerCacheDisabled','originalInputsUnchanged')) and
            native.get('targetSourceDependencies',{}).get('actualTargetSourceDependencyObservation') is True and
            native.get('targetSourceDependencies',{}).get('dependenciesNotNewerThanObject') is True and
            native.get('targetSourceDependencies',{}).get('outputFiles',{}).get('observation.json')==identity(qualified['dependencyObservation']) and
            all(identity(native['programs'][name])==pin['programPairs'][name]['original'] for name in ORDERED),
            'server-data-tools-ordered-native-build-pair-differs')
    stripped,_=shared.read_json(directory/'ordered-strip-receipt.json',16<<20)
    require(stripped.get('scope')=='paired-linux-arm64-ordered-extractor-derivative' and
            stripped.get('programs') and set(stripped['programs'])==set(ORDERED) and
            stripped.get('originalNativeBuild')==identity(qualified['nativeBuild']) and
            stripped.get('archiveReadbackVerified') is True,'server-data-tools-real-ordered-strip-pair-required')
    for name in ORDERED:
        pair=stripped['programs'][name]
        require({k:pair[k] for k in ('original','stripped','debug')}==pin['programPairs'][name] and
                pair.get('runtimeBytesPreserved') is True and pair.get('debugLinkVerified') is True,
                'server-data-tools-ordered-loaded-bytes-or-debug-pair-differs')
    engine.verify_archive(directory/'ordered-extractors-debug-arm64.tar.gz',stripped['debugInventory'])
    stock_receipt,_=shared.read_json(directory/'stock-package-receipt.json')
    stock.validate_package(stock_receipt,original)
    engine.verify_archive(directory/'stock-extractors-debug-arm64.tar.gz',stock_receipt['packages']['debug']['inventory'])
    cli,_=shared.read_json(directory/'native-cli.json')
    validate_native_cli(cli,pin)
    receipt,_=shared.read_json(directory/'package-receipt.json',16<<20)
    require(receipt.get('scope')=='composed-linux-arm64-server-data-tools-runtime' and
            receipt.get('archive')==pin['archive'] and receipt.get('archiveFiles')==pin['files'] and
            receipt.get('toolSelection')==pin['toolSelection'] and receipt.get('programPairs')==pin['programPairs'] and
            receipt.get('orderedSourceReceipt')==identity(qualified['receipt']) and
            receipt.get('originalNoticesPreserved') is True and receipt.get('archiveReadbackVerified') is True,
            'server-data-tools-runtime-receipt-differs')


def build(package,sources_directory,output):
    pin=load_pin(sealed=True);package=archives.directory(package);sources_directory=archives.directory(sources_directory)
    output=Path(os.path.abspath(output));archives.directory(output.parent,create=True)
    require(not os.path.lexists(output) and all(p!=output and p not in output.parents and output not in p.parents
        for p in (package,sources_directory)),'server-data-tools-output-exists-or-overlaps-input')
    verify_sources(sources_directory,pin);verify_runtime(package/RUNTIME,pin)
    stage=Path(tempfile.mkdtemp(prefix='.'+output.name+'.stage-',dir=output.parent))
    try:
        shutil.copytree(sources_directory,stage/'sources')
        assets=stage/'assets'/ASSETS;assets.mkdir(parents=True)
        engine.copy_verified(package/RUNTIME,assets/ARCHIVE,identity(pin['archive']),0o444)
        engine.put_metadata(assets/'provider.json',descriptor(pin));verify(stage)
        transaction.publish_directory(stage,output);archives.sync_directory(output.parent);return descriptor(pin)
    finally:
        if stage.exists():shutil.rmtree(stage)


def verify(provider,apk=None):
    pin=load_pin(sealed=True);provider=archives.directory(provider)
    require({p.name for p in provider.iterdir()}=={'assets','sources'} and
            {p.name for p in archives.directory(provider/'assets').iterdir()}=={ASSETS},'server-data-tools-provider-root-closure')
    assets=archives.directory(provider/'assets'/ASSETS)
    require({p.name for p in assets.iterdir()}=={ARCHIVE,'provider.json'},'server-data-tools-provider-asset-closure')
    verify_sources(archives.directory(provider/'sources'),pin);verify_runtime(assets/ARCHIVE,pin)
    require(shared.files.small(assets/'provider.json',128<<10)==encoded(descriptor(pin)),
            'server-data-tools-provider-descriptor-differs')
    if apk is not None:
        selected={'assets/'+ASSETS+'/'+name for name in (ARCHIVE,'provider.json')}
        with files.plain_file(apk) as raw,shared.checked_zip(raw,selected,maximum_bytes=2<<30,maximum_entries=4096) as archive:
            require({n for n in archive.namelist() if n.startswith('assets/'+ASSETS+'/')}==selected,
                    'server-data-tools-apk-asset-closure')
            for name in (ARCHIVE,'provider.json'):
                row=archive.getinfo('assets/'+ASSETS+'/'+name);path=assets/name
                require(row.file_size==path.stat().st_size and (name!=ARCHIVE or row.compress_type==zipfile.ZIP_STORED),
                        'server-data-tools-apk-size-or-compression')
                with archive.open(row) as incoming,files.plain_file(path) as expected:
                    require(archives.hash_stream(incoming,row.file_size)==archives.hash_stream(expected,row.file_size),
                            'server-data-tools-apk-bytes-differ')
    return dict(providerVerified=True,sourceCompanionVerified=True,pairedDebugVerified=True,apkBytesVerified=apk is not None,
        nativeArgumentConfigQualified=True,**{name:False for name in FALSE_FLAGS})


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='operation',required=True)
    inspect=sub.add_parser('pin')
    make=sub.add_parser('build')
    for name in ('package','sources','output'):make.add_argument('--'+name,type=Path,required=True)
    check=sub.add_parser('verify');check.add_argument('--provider',type=Path,required=True);check.add_argument('--apk',type=Path)
    args=parser.parse_args()
    if args.operation=='pin':result=load_pin()
    elif args.operation=='build':result=build(args.package,args.sources,args.output)
    else:result=verify(args.provider,args.apk)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
