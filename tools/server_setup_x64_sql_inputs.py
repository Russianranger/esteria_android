#!/usr/bin/env python3
"""Admit measured x64 SQL-tool inputs without granting execution qualification.

The pending selection cannot create output or run SQL. Measured selections bind
the actual source build, full original component ZIP, complete corresponding
sources, independent MySQL consumer and unchanged public server content.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import zlib

if not __package__:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import build_server_setup_x64_probe as builder
from tools import fetch_android_mysql_fixture as mysql
from tools import fetch_local_server_profile as public
from tools import provider_client_runtime as zips
from tools import prepare_runtime as archives, verify_server_build as files

ROOT=Path(__file__).resolve().parents[1]
LOCK=ROOT/'runtime/mysql-probe/server-setup-x64-sql-inputs.lock.json'
FALSE_FLAGS=builder.FALSE_FLAGS
COMPONENT='x64-setup-build/component'
CONTEXT='x64-setup-context'
RECIPE='7e498c50cdf55027e679d63e31f0a5e4b117f934'
require=files.require


def identity(value,maximum=4<<30):
    require(type(value) is dict and type(value.get('bytes')) is int and 0<value['bytes']<=maximum and
        re.fullmatch('[0-9a-f]{64}',value.get('sha256','')),'x64-sql-input-invalid-identity')
    return {key:value[key] for key in ('bytes','sha256')}


def small(path,maximum=2<<20):
    with files.plain_file(path) as stream:
        size=os.fstat(stream.fileno()).st_size
        require(0<size<=maximum,'x64-sql-input-metadata-bound')
        raw=stream.read(size+1);require(len(raw)==size,'x64-sql-input-metadata-changed')
    return json.loads(raw)


def pinned(path,row,maximum=4<<30):
    require(files.identity(path)==identity(row,maximum),'x64-sql-input-file-changed')


def record(row,expected_path=None):
    require(type(row) is dict and set(row)=={'path','bytes','sha256'},'x64-sql-input-record-schema')
    name=row['path']
    require(type(name) is str and name.startswith('runtime/') and name.endswith('.json') and
        '\\' not in name and not any(part in ('','..','.') for part in name.split('/')) and
        (expected_path is None or name==expected_path),'x64-sql-input-record-path')
    pinned(ROOT/name,row,2<<20);return small(ROOT/name)


def load_pin(*,require_enabled=False):
    pin=small(LOCK,128<<10)
    require(type(pin) is dict and set(pin)=={'formatVersion','scope','repository','enabled','state',
        'minimumFreeBytes','build','mysql','serverContent',*FALSE_FLAGS} and type(pin['formatVersion']) is int and
        pin['formatVersion']==1 and pin['scope']=='x64-server-setup-sql-input-selection' and
        pin['repository']=='Russianranger/esteria_android' and type(pin['enabled']) is bool and
        type(pin['minimumFreeBytes']) is int and pin['minimumFreeBytes']==16<<30 and
        all(pin[name] is False for name in FALSE_FLAGS),'x64-sql-input-selection-schema')
    if not pin['enabled']:
        require(pin['state']=='pending-x64-compile-source-measurement' and
            all(pin[key] is None for key in ('build','mysql','serverContent')),'x64-sql-input-pending-selection')
        require(not require_enabled,'x64-sql-input-measured-build-required')
        return pin
    require(pin['state']=='measured-component-inputs','x64-sql-input-measured-state')
    build=pin['build'];require(type(build) is dict and set(build)=={'producer','artifacts','componentPrefix',
        'contextPrefix','buildReceipt','librarySourceReadback','librarySourceManifest','contextReceipt','actualEvidence'},
        'x64-sql-input-build-selection-schema')
    producer=build['producer']
    require(type(producer) is dict and set(producer)=={'workflowRun','job','integrationRevision'} and
        all(type(producer[name]) is int and producer[name]>0 for name in ('workflowRun','job')) and
        re.fullmatch('[0-9a-f]{40}',producer.get('integrationRevision','')) and
        build['componentPrefix']==COMPONENT and build['contextPrefix']==CONTEXT,'x64-sql-input-exact-producer')
    require(type(build['artifacts']) is dict and set(build['artifacts'])=={'complete','evidence'},'x64-sql-input-artifact-pair')
    for row in build['artifacts'].values():
        require(type(row) is dict and set(row)=={'id','bytes','sha256'} and type(row['id']) is int and row['id']>0,
            'x64-sql-input-exact-artifact')
        identity(row)
    for key in ('buildReceipt','librarySourceReadback','librarySourceManifest','contextReceipt'):
        require(type(build[key]) is dict and set(build[key])=={'bytes','sha256'},'x64-sql-input-scalar-pin-schema')
        identity(build[key],2<<20)
    actual=record(build['actualEvidence'])
    workflow=actual.get('workflow',{})
    require(actual.get('scope')=='independent-x64-server-setup-build-and-source-readback' and
        workflow.get('id')==producer['workflowRun'] and workflow.get('headSha')==producer['integrationRevision'] and
        workflow.get('status')=='completed' and workflow.get('conclusion')=='success' and
        actual.get('buildReceiptIdentity')==build['buildReceipt'] and
        actual.get('librarySourceReadbackIdentity')==build['librarySourceReadback'] and
        actual.get('artifactMetadataOnly')==build['artifacts'],'x64-sql-input-positive-build-evidence')
    validate_build(actual.get('actualBuildReceipt'),pin)
    validate_source_readback(actual.get('actualLibrarySourceReadback'),pin)
    selected=pin['mysql'];require(type(selected) is dict and set(selected)=={'selection','fullReadbackEvidence'},
        'x64-sql-input-mysql-selection-schema')
    record(selected['selection'],'runtime/mysql-probe/qualified-inputs.lock.json');mysql_pin=mysql.load_pin()
    wrapper=record(selected['fullReadbackEvidence'])
    require(wrapper.get('scope')=='actual-ci-retained-android-x64-mysql-input-source-consumer-and-small-local-readback' and
        wrapper.get('consumer',{}).get('workflowRun')==41119182469 and
        wrapper['consumer'].get('integrationRevision')=='817cbc229f4dcc24beb169ecc72838fab4d1df32' and
        wrapper['consumer'].get('status')=='completed' and wrapper['consumer'].get('conclusion')=='success' and
        wrapper.get('allFourConsumerSourceInputsMatchExactGitBlobs') is True and
        wrapper.get('allRetainedSmallArtifactMembersReadAndCrcVerified') is True and
        wrapper.get('originalLargeSourceReadbackPerformedOnCi') is True and
        all(wrapper.get(name) is False for name in ('androidExecutedByConsumer','aptOrCompilerExecutedByConsumer',
            'localOriginalInputAndSourceArchivesDownloaded','productionArm64Qualified','serverSchemasQualified','gameplayQualified')),
        'x64-sql-input-actual-mysql-consumer-wrapper')
    observed=wrapper.get('actualCiEvidence',{})
    require(observed.get('scope')=='full-original-android-x64-mysql-fixture-input-and-source-readback' and
        observed.get('inputSelection')==identity(selected['selection']) and
        observed.get('producer')==mysql_pin['producer'] and observed.get('artifacts')==mysql_pin['artifacts'] and
        all(observed.get(name) is True for name in ('everyOriginalInputAndSourceZipByteReadBack','allNineRetainedInputsVerified',
            'allInstalledPackageSourceFilesReadBack','prootProviderVerified','originalApkVerified')) and
        observed.get('guestExecuted') is False and observed.get('sqlExecuted') is False and
        all(observed.get(name) is False for name in mysql.FALSE_FLAGS),'x64-sql-input-full-mysql-readback-required')
    content=pin['serverContent'];require(type(content) is dict and set(content)=={'recipeRevision','releaseSelection',
        'publicationReceipt','publicSourceReadback','asset'},'x64-sql-input-public-content-schema')
    for key,name in (('releaseSelection','dependency-release.lock.json'),('publicationReceipt','published-release.json'),
            ('publicSourceReadback','public-source-readback.json')):
        record(content[key],'runtime/server-components-publication/'+name)
    selection=public.selection();asset=small(ROOT/public.DIRECTORY/public.PUBLICATION)['assets']['server-content-provider.tar.gz']
    require(selection['source']=='public-release' and content['recipeRevision']==selection['recipeRevision']==RECIPE and
        content['asset']==asset and asset['bytes']==168956728 and
        asset['sha256']=='0fe3d5ec91f25295fcfff1acca898cfb36136ecbe40f1d65653f98817d58803e',
        'x64-sql-input-exact-public-content-required')
    return pin


def validate_build(value,pin):
    require(type(value) is dict and value.get('formatVersion')==1 and type(value.get('formatVersion')) is int and
        value.get('scope')=='source-built-x86-64-server-setup-tools-only' and value.get('phase')=='built-unqualified-inputs' and
        value.get('integrationRevision')==pin['build']['producer']['integrationRevision'] and
        value.get('targets')==list(builder.TARGETS) and value.get('buildNetwork')==dict(interfaces=['lo'],externalNetworkingAvailable=False) and
        value.get('actualCompileSucceeded') is True and value.get('correspondingSourcesCaptured') is False and
        type(value.get('statementsDeclared')) is int and value['statementsDeclared']==52 and
        value.get('originalArm64ReceiptReusedForX64Qualification') is False and
        value.get('originalDbimportTargetAndFullStaticModuleScriptLinkGraphBuilt') is True and
        value.get('originalDbimportExecutableBuilt') is True and value.get('dbimportSqlQualified') is False and
        value.get('runtimeOverlayCompatibilityQualified') is False and value.get('librarySourceCaptureRequired') is True and
        all(value.get(name) is False for name in FALSE_FLAGS),'x64-sql-input-actual-x64-build-required')
    source=json.loads((ROOT/'sources.lock.json').read_bytes())['sources']['server']
    require(value.get('serverSource')==source and value.get('sourceLock')==files.identity(builder.inputs.ARCHIVED_LOCK) and
        value.get('originalArm64Build')==builder.bots.ORIGINAL_BUILD and
        value.get('originalArm64Modules')==builder.bots.ORIGINAL_MODULES,'x64-sql-input-source-module-binding')
    require(value.get('actualPlayerbotsCompileInputs')==value.get('compileCommands'),
        'x64-sql-input-actual-playerbots-compile-inputs')
    identity(value['compileCommands'],64<<20)
    require(value.get('compilerLaunchers')=={'CMAKE_C_COMPILER_LAUNCHER':'','CMAKE_CXX_COMPILER_LAUNCHER':''},
        'x64-sql-input-compiler-launchers')
    require(type(value.get('executables')) is dict and set(value['executables'])=={'dbimport','playerbots-schema'},
        'x64-sql-input-executable-set')
    for name,row in value['executables'].items():
        identity(row,2<<30);identity(row.get('original'),2<<30);identity(row.get('pairedDebug'),2<<30)
        elf=row.get('elf',{})
        require(elf.get('machine')==62 and type(elf.get('machine')) is int and
            elf.get('elfClass')==2 and type(elf.get('elfClass')) is int and
            type(elf.get('loadSegments')) is int and 0<elf['loadSegments']<=8192 and
            elf.get('interpreter')=='/lib64/ld-linux-x86-64.so.2' and
            row.get('originalFile')=='originals/'+name and row.get('debugFile')=='debug/'+name+'.debug',
            'x64-sql-input-executable-metadata-abi')
    return value


def validate_source_readback(value,pin):
    require(type(value) is dict and type(value.get('formatVersion')) is int and value['formatVersion']==1 and
        value.get('scope')=='x64-server-setup-tools-library-source-preservation-only' and
        value.get('buildReceipt')==pin['build']['buildReceipt'] and
        value.get('sourceManifest')==pin['build']['librarySourceManifest'] and
        type(value.get('sourceArchiveFiles')) is int and 0<value['sourceArchiveFiles']<=4096 and
        type(value.get('sourceArchiveBytes')) is int and 0<value['sourceArchiveBytes']<=8<<30 and
        value.get('everyCopiedLibrarySourceCaptured') is True and all(value.get(name) is False for name in FALSE_FLAGS),
        'x64-sql-input-library-source-readback-required')
    return value


def restore_component_zip(path,output,pin):
    """Read every original ZIP byte/member before any executable is admitted."""
    require(pin.get('enabled') is True,'x64-sql-input-measured-build-required')
    pinned(path,pin['build']['artifacts']['complete'])
    output=Path(os.path.abspath(output));archives.directory(output.parent,create=True)
    require(not os.path.lexists(output),'x64-sql-input-existing-output-preserved');output.mkdir(mode=0o700)
    inventory={};total=0
    with files.plain_file(path) as stream,zips.checked_zip(stream,required=(),maximum_bytes=4<<30,
            maximum_entries=10000,maximum_directory=8<<20) as archive:
        for item in archive.infolist():
            name=item.filename;public.release.engine.content.safe_path(name)
            require(not item.is_dir() and stat.S_IFMT(item.external_attr>>16) in (0,stat.S_IFREG) and
                name not in inventory and name.startswith((COMPONENT+'/',CONTEXT+'/')) and
                0<item.file_size<=2<<30,'x64-sql-input-original-member-selection')
            total+=item.file_size;require(total<=8<<30,'x64-sql-input-expanded-artifact-bound')
            target=output/name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with archive.open(item) as incoming,target.open('xb') as outgoing:
                digest=archives.hash_stream(incoming,item.file_size,outgoing)
            target.chmod(0o444);inventory[name]=dict(bytes=item.file_size,sha256=digest)
    proof=admit_component(output/COMPONENT,pin)
    context=output/CONTEXT;pinned(context/'context.json',pin['build']['contextReceipt'])
    context_value=small(context/'context.json')
    require(context_value.get('scope')=='x64-server-setup-compiler-context-only' and context_value.get('baseImage')==builder.BASE and
        all(context_value.get(name) is False for name in FALSE_FLAGS),'x64-sql-input-compiler-context-scope')
    expected={CONTEXT+'/context.json':pin['build']['contextReceipt'],CONTEXT+'/Dockerfile':context_value['dockerfile']}
    for name,row in context_value['files'].items():expected[CONTEXT+'/'+Path(name).name]=row
    for name,row in expected.items():require(inventory.get(name)==identity(row),'x64-sql-input-compiler-context-file-changed')
    require({name for name in inventory if name.startswith(CONTEXT+'/')}==set(expected),
        'x64-sql-input-compiler-context-closure')
    return dict(formatVersion=1,scope='full-original-x64-server-setup-component-source-readback',
        componentDirectory=str(output/COMPONENT),originalArtifact=files.identity(path),allOriginalMembers=inventory,
        everyOriginalMemberCrcAndSha256Verified=True,componentAdmission=proof,**{name:False for name in FALSE_FLAGS})


def _tree(root):
    return {path.relative_to(root).as_posix() for path in files.installed_files(root)}


def debug_pair(executable,debug,name):
    """Read a bounded ELF64 section table; no toolchain is needed in the guest."""
    with files.plain_file(executable) as stream:
        size=os.fstat(stream.fileno()).st_size;header=stream.read(64)
        require(len(header)==64 and header[:7]==b'\x7fELF\x02\x01\x01' and
            struct.unpack_from('<H',header,18)[0]==62,'x64-sql-input-debug-link-elf')
        offset=struct.unpack_from('<Q',header,40)[0];entry,count,strings=struct.unpack_from('<HHH',header,58)
        require(entry==64 and 0<count<=8192 and 0<strings<count and 64<=offset<=size and
            count*entry<=size-offset,'x64-sql-input-debug-section-table')
        stream.seek(offset);table=stream.read(count*entry)
        sections=[struct.unpack_from('<IIQQQQIIQQ',table,index*entry) for index in range(count)]
        for row in sections:
            require(row[1]==8 or (row[4]<=size and row[5]<=size-row[4]),'x64-sql-input-debug-section-bound')
        names=sections[strings]
        require(names[1]==3 and 0<names[5]<=64<<10,'x64-sql-input-debug-section-names')
        stream.seek(names[4]);roster=stream.read(names[5]);matches=[]
        for row in sections:
            require(row[0]<len(roster),'x64-sql-input-debug-section-name-offset')
            end=roster.find(b'\0',row[0],row[0]+129)
            require(end>=row[0],'x64-sql-input-debug-section-name-bound')
            if roster[row[0]:end]==b'.gnu_debuglink':matches.append(row)
        require(len(matches)==1 and matches[0][1]==1 and 4<=matches[0][5]<=256,'x64-sql-input-debug-link-section')
        stream.seek(matches[0][4]);raw=stream.read(matches[0][5])
    expected=(name+'.debug').encode()+b'\0';offset=(len(expected)+3)&~3
    require(len(raw)==offset+4 and raw[:len(expected)]==expected and
        not any(raw[len(expected):offset]),'x64-sql-input-debug-link-section')
    crc=0
    with files.plain_file(debug) as stream:
        while True:
            block=stream.read(128<<10)
            if not block:break
            crc=zlib.crc32(block,crc)
    require(int.from_bytes(raw[offset:],'little')==crc,'x64-sql-input-paired-debug-crc')


def original_sources(payload,build):
    root=payload/'corresponding-source/source-inputs'
    receipt=small(root/'source-inputs-receipt.json',8<<20)
    selected=receipt.get('archiveFiles')
    require(receipt.get('scope')=='unsealed-engine-source-input-package' and
        receipt.get('completeArchiveReadbackVerified') is True and type(selected) is dict and
        0<len(selected)<=10000 and identity(receipt.get('archive'))==
            identity(build['sourceInputs']['source-inputs/server-engine-source-inputs.tar.gz']),
        'x64-sql-input-original-source-archive-receipt')
    seen=set();total=0
    with files.plain_file(root/'server-engine-source-inputs.tar.gz') as stream,archives.bounded_tar(stream,
            dict(entries=10000,pathBytes=4096,fileBytes=256<<20)) as archive:
        for member in archive:
            name=member.name;public.release.engine.content.safe_path(name)
            require(member.isfile() and name in selected and name not in seen and member.size==selected[name]['bytes'],
                'x64-sql-input-original-source-member')
            total+=member.size;require(total<=256<<20,'x64-sql-input-original-source-bound')
            with archive.extractfile(member) as incoming:
                require(archives.hash_stream(incoming,member.size)==selected[name]['sha256'],
                    'x64-sql-input-original-source-member-changed')
            seen.add(name)
    require(seen==set(selected),'x64-sql-input-original-source-closure')
    return dict(members=len(seen),fileBytes=total,everyOriginalSourceMemberReadBack=True)


def admit_component(component,pin):
    """Rehash the closed tree. No guest, SQL process, or wrapper is created."""
    require(pin.get('enabled') is True,'x64-sql-input-measured-build-required')
    component=archives.directory(component);payload=archives.directory(component/'payload')
    pinned(payload/'build-receipt.json',pin['build']['buildReceipt']);build=validate_build(small(payload/'build-receipt.json'),pin)
    pinned(component/'library-source-readback.json',pin['build']['librarySourceReadback'])
    readback=validate_source_readback(small(component/'library-source-readback.json'),pin)
    expected={'build-receipt.json'}
    for name,row in build['executables'].items():
        require(row.get('originalFile')=='originals/'+name and row.get('debugFile')=='debug/'+name+'.debug',
            'x64-sql-input-original-debug-path')
        for path,selection in (('bin/'+name,row),('originals/'+name,row['original']),('debug/'+name+'.debug',row['pairedDebug'])):
            pinned(payload/path,selection);expected.add(path)
        require(builder.elf64_x64(payload/'bin'/name)==row['elf'] and builder.elf64_x64(payload/'originals'/name)['machine']==62,
            'x64-sql-input-runtime-original-elf-differs')
        debug_pair(payload/'bin'/name,payload/'debug'/(name+'.debug'),name)
    require(type(build.get('libraries')) is dict and 0<len(build['libraries'])<=128 and
        type(build.get('libraryPackages')) is dict and type(build.get('libraryNotices')) is dict,
        'x64-sql-input-library-closure-required')
    require({'lib64/ld-linux-x86-64.so.2','usr/lib/x86_64-linux-gnu/libc.so.6'}<=set(build['libraries']),
        'x64-sql-input-captured-loader-and-libc-required')
    source_packages={}
    for name,row in build['libraries'].items():
        public.release.engine.content.safe_path(name)
        require(name.startswith(('usr/lib/x86_64-linux-gnu/','lib64/')),'x64-sql-input-library-path')
        pinned(payload/'libraries'/name,row);expected.add('libraries/'+name)
        require(builder.elf64_x64(payload/'libraries'/name)==row['elf'] and
            build['libraryPackages'].get(row['package']['binaryPackage'])==row['package'],'x64-sql-input-library-package-binding')
        source_packages[row['package']['package']+'='+row['package']['version']]=dict(package=row['package']['package'],version=row['package']['version'])
    for name,row in build['libraryNotices'].items():
        require(re.fullmatch('[a-z0-9][a-z0-9+.-]*',name),'x64-sql-input-notice-name')
        path='notices/'+name+'/copyright';pinned(payload/path,row);expected.add(path)
    require(set(build['libraryNotices'])=={name.split(':')[0] for name in build['libraryPackages']},
        'x64-sql-input-all-library-notices-required')
    require(type(build.get('sourceInputs')) is dict and 10<=len(build['sourceInputs'])<=128,
        'x64-sql-input-complete-original-source-selection')
    for name,row in build['sourceInputs'].items():
        public.release.engine.content.safe_path(name);pinned(payload/'corresponding-source'/name,row);expected.add('corresponding-source/'+name)
    require({'integration-recipe.tar','source-inputs/server-engine-source-inputs.tar.gz','source-inputs/source-inputs-receipt.json',
        'integration/tools/build_server_setup_x64_probe.py','integration/tests/playerbots_database_reference.cpp',
        'integration/tests/playerbots_database_reference.cmake','integration/runtime/server/server-build-sources.lock.json'}<=set(build['sourceInputs']),
        'x64-sql-input-original-recipe-and-source-required')
    require(_tree(payload)==expected,'x64-sql-input-payload-file-closure')
    original=original_sources(payload,build)
    source=component/'corresponding-library-sources'
    pinned(source/'SOURCE-MANIFEST.json',pin['build']['librarySourceManifest'])
    runtime=small(component/'library-runtime.json')
    require(runtime.get('sourceLockSha256')==files.identity(ROOT/'runtime/mysql-probe/sources.lock.json')['sha256'] and
        type(runtime.get('sourcePackages')) is list and
        {row['package']+'='+row['version']:row for row in runtime['sourcePackages']}==source_packages and
        len(runtime['sourcePackages'])==len(source_packages),'x64-sql-input-library-runtime-source-binding')
    manifest,_=mysql.retained.verify_sources(source,(component/'library-runtime.json').read_bytes(),
        (ROOT/'runtime/mysql-probe/sources.lock.json').read_bytes())
    require(readback['sourceArchiveFiles']==len(manifest['files']) and readback['sourceArchiveBytes']==manifest['fileBytes'],
        'x64-sql-input-library-source-count')
    require(_tree(component)=={'payload/'+name for name in expected}|{'library-runtime.json','library-source-readback.json'}|
        {'corresponding-library-sources/'+name for name in _tree(source)},'x64-sql-input-component-file-closure')
    return dict(formatVersion=1,scope='admitted-x64-server-setup-tools-complete-source-only',payloadPath=str(payload),
        build=build,sourceReadback=readback,libraryManifest=manifest,originalSourceArchiveReadback=original,
        allRuntimeOriginalDebugLibraryNoticeAndSourceFilesVerified=True,
        newCompileCommandsBytesRetained=False,newCompileCommandsIdentityMetadataOnly=True,
        **{name:False for name in FALSE_FLAGS})
