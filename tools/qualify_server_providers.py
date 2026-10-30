#!/usr/bin/env python3
"""Acquire exact retained stock server packages and qualify install-only providers.

Large debug archives are streamed and fully read back on CI, outside APK assets.
No server program, SQL, Android guest or proprietary game asset is executed.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

if not __package__:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import package_server_engine as engine,package_server_engine_notices as notices
from tools import prepare_runtime as archives,prepare_server_requalification as remote
from tools import provider_server_programs as programs,provider_server_extractors as extractors
from tools import provider_server_content as content,provider_server_runtime as dependencies
from tools import verify_server_build as files

ROOT=Path(__file__).resolve().parents[1]
LOCK=ROOT/'runtime/server/provider-qualification.lock.json'
require=files.require
COMPONENTS={'programs':(programs,'server-programs'),'extractors':(extractors,'server-extractors'),
            'content':(content,'server-content'),'dependencies':(dependencies,'server-runtime')}


def load_pin():
    pin,_=engine.modules.read_json(LOCK)
    require(pin.get('formatVersion')==1 and pin.get('scope')=='exact-stock-server-provider-qualification-inputs' and
            pin.get('minimumFreeBytes')==16*1024**3 and
            set(pin.get('artifacts',{}))=={'runtime','engineDebug','extractorDebug','native','completeSources'} and
            pin.get('androidRuntimeQualified') is False and pin.get('gameplayQualified') is False,
            'server-provider-qualification-input-pin')
    targets=set()
    for row in pin['artifacts'].values():
        require(type(row.get('id')) is int and row['id']>0 and type(row.get('workflowRun')) is int and row['workflowRun']>0 and
                re.fullmatch('[0-9a-f]{40}',row.get('integrationRevision','')) and
                type(row.get('bytes')) is int and 0<row['bytes']<2*1024**3 and
                re.fullmatch('[0-9a-f]{64}',row.get('sha256','')) and 0<len(row.get('members',{}))<=16,
                'server-provider-qualification-artifact-pin')
        for name,item in row['members'].items():
            engine.content.safe_path(name);engine.content.safe_path(item['target']);engine.identity(item)
            require(item['target'] not in targets,'server-provider-qualification-target-collision');targets.add(item['target'])
    return pin


def verify_remote(api,row):
    actual=api.json('/actions/artifacts/'+str(row['id']))
    require(actual.get('id')==row['id'] and actual.get('expired') is False and
            actual.get('size_in_bytes')==row['bytes'] and actual.get('digest')=='sha256:'+row['sha256'] and
            actual.get('workflow_run',{}).get('id')==row['workflowRun'] and
            actual.get('workflow_run',{}).get('head_sha')==row['integrationRevision'],
            'server-provider-qualification-remote-artifact-changed')


def extract_selected(path,output,row):
    require(files.identity(path)==engine.identity(row),'server-provider-qualification-downloaded-zip-changed')
    with remote.bounded_zip(path) as (archive,members):
        require(set(row['members'])<=members.keys(),'server-provider-qualification-required-zip-member-missing')
        for name,item in row['members'].items():
            info=members[name];expected=engine.identity(item)
            require(info.file_size==expected['bytes'],'server-provider-qualification-zip-member-size')
            target=output/item['target'];target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(info) as incoming,target.open('xb') as outgoing:
                require(archives.hash_stream(incoming,info.file_size,outgoing)==expected['sha256'],
                        'server-provider-qualification-zip-member-hash')
                outgoing.flush();os.fsync(outgoing.fileno())
            target.chmod(0o444)


def original_source_inputs(output,pin):
    selected=programs.load_pin(sealed=True)
    sealed,sid=engine.modules.read_json(output/'sealed/sealed-source-receipt.json')
    require(sid==selected['sourceQualification']['receipt'] and sealed['archiveFiles'] and
            files.identity(output/'sealed'/programs.SOURCE_ARCHIVE)==selected['sourceQualification']['archive'],
            'server-provider-qualification-complete-source-selection')
    archive_path=output/'sealed'/programs.SOURCE_ARCHIVE;engine.verify_archive(archive_path,sealed['archiveFiles'])
    wanted={'inputs/source-inputs/server-engine-source-inputs.tar.gz':selected['originalSourceInputs']['archive'],
            'inputs/source-inputs/source-inputs-receipt.json':selected['originalSourceInputs']['receipt']}
    destination=output/'original-source-inputs';destination.mkdir();seen=set()
    with files.plain_file(archive_path) as source,archives.bounded_tar(source,
            dict(entries=20000,pathBytes=4096,fileBytes=512*1024**2)) as archive:
        for member in archive:
            if member.name in wanted:
                require(member.name not in seen and member.isfile(),'server-provider-qualification-source-input-member')
                expected=engine.identity(wanted[member.name]);require(member.size==expected['bytes'],'server-provider-source-input-size')
                with archive.extractfile(member) as incoming,(destination/Path(member.name).name).open('xb') as outgoing:
                    require(archives.hash_stream(incoming,member.size,outgoing)==expected['sha256'],'server-provider-source-input-hash')
                seen.add(member.name)
            archive.members.clear()
    require(seen==set(wanted),'server-provider-source-input-missing')


def acquire(output,api=None):
    pin=load_pin();output=Path(os.path.abspath(output));archives.directory(output.parent,create=True)
    require(not os.path.lexists(output),'existing-server-provider-qualification-inputs-preserved')
    require(shutil.disk_usage(output.parent).free>=pin['minimumFreeBytes'],'server-provider-qualification-requires-16-GiB-free')
    api=api or remote.Github(os.environ.get('GITHUB_TOKEN'));output.mkdir(mode=0o700)
    for name,row in pin['artifacts'].items():
        verify_remote(api,row);path=output/(name+'.zip')
        api.download(remote.API+'/actions/artifacts/'+str(row['id'])+'/zip',path,row)
        extract_selected(path,output,row);path.unlink()
    original_source_inputs(output,pin)
    receipt=dict(formatVersion=1,scope='exact-stock-server-provider-inputs-readback',inputLock=files.identity(LOCK),
        artifacts=pin['artifacts'],everySelectedInputHashVerified=True,originalCompleteSourceArchiveReadback=True,
        sourceRepositoryFetched=False,serverInstallArchiveFetched=False,serverExecuted=False,
        androidRuntimeQualified=False,gameplayQualified=False)
    engine.put_metadata(output/'acquisition.json',receipt);return receipt


def build(acquired,output):
    pin=load_pin();acquired=archives.directory(acquired);output=Path(os.path.abspath(output));archives.directory(output.parent,create=True)
    require(not os.path.lexists(output) and acquired!=output and acquired not in output.parents and output not in acquired.parents,
            'existing-or-overlapping-server-provider-qualification-output-preserved')
    for row in pin['artifacts'].values():
        for item in row['members'].values():
            require(files.identity(acquired/item['target'])==engine.identity(item),'server-provider-staged-input-changed')
    output.mkdir(mode=0o700);notice=notices.build(acquired/'engine',acquired/'original-source-inputs',output/'notice-package')
    expected=programs.load_pin(sealed=True)
    require(notice['archive']==expected['archive'] and files.identity(output/'notice-package/package-receipt.json')==
            engine.identity(expected['packageReceipt']),'server-provider-notice-package-reproduction-changed')
    programs.build(output/'notice-package',acquired/'engine/package-receipt.json',acquired/'native/native-loader.json',
        acquired/'sealed',acquired/'engine/server-engine-debug-arm64.tar.gz',output/'programs')
    extractors.build(acquired/'extractors',acquired/'native/native-cli.json',acquired/'sealed',
        acquired/'extractors/server-extractors-debug-arm64.tar.gz',output/'extractors')
    content.build(acquired/'content',output/'content')
    receipt=dict(formatVersion=1,scope='source-and-paired-debug-verified-stock-server-install-providers',
        inputLock=files.identity(LOCK),sourceQualification=expected['sourceQualification'],
        programs=programs.verify(output/'programs'),extractors=extractors.verify(output/'extractors'),
        content=content.verify(output/'content'),nativeProgramsExecuted=False,sqlExecuted=False,
        androidRuntimeQualified=False,gameplayQualified=False)
    engine.put_metadata(output/'provider-build.json',receipt);return receipt


def java_manifest(provider,output):
    descriptions=list((provider/'assets').glob('*/provider.json'));require(len(descriptions)==1,'server-java-reference-descriptor-count')
    proof,_=engine.modules.read_json(descriptions[0]);a=proof['archive'];b=proof['limits']
    source=proof.get('serverBuildSourceLockSha256',proof.get('sourceLockSha256'))
    values=['P',proof['packageKey'],source,a['file'],str(a['bytes']),a['sha256'],str(proof['archiveEntries']),
        str(proof['archiveFileBytes']),str(b['entries']),str(b['memberBytes']),str(b['fileBytes']),str(b['pathBytes']),str(b['metadataBytes'])]
    lines=['\t'.join(values)]
    for name,row in sorted(proof['requiredFiles'].items()):
        engine.content.safe_path(name);require('\t' not in name,'server-java-reference-path')
        lines.append('\t'.join(['F',name,str(row['bytes']),row['sha256'],str(row.get('elfMachine',0)),str(row.get('peMachine',0))]))
    remote.write_new(output,('\n'.join(lines)+'\n').encode())
    return dict(manifest=files.identity(output),archive=str(descriptions[0].parent/Path(a['assetPath']).name))


def verify_final(output,dependency_provider,apk):
    import zipfile
    from tools import package_combined_android as combined
    proofs={}
    for name,(module,_) in COMPONENTS.items():
        path=dependency_provider if name=='dependencies' else output/name
        proofs[name]=module.verify(path,apk=apk)
    with zipfile.ZipFile(apk) as archive:
        combined.verify_helpers(archive)
    receipt=dict(formatVersion=1,scope='four-server-component-install-profile-apk-byte-verification',
        apk=files.identity(apk),providers=proofs,sourceCompanionAndPairedDebugVerified=True,
        exactSourceHelperClosureVerified=True,
        helperFiles={name:len(rows) for name,rows in combined.HELPER_SETS.items()},
        originalRuntimeArchivesUnchanged=True,androidGuestExecuted=False,serverProgramsExecuted=False,
        sqlExecuted=False,androidRuntimeQualified=False,gameplayQualified=False)
    engine.put_metadata(output/'apk-verification.json',receipt);return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='operation',required=True)
    fetch=sub.add_parser('acquire');fetch.add_argument('--output',type=Path,required=True)
    make=sub.add_parser('build');make.add_argument('--inputs',type=Path,required=True);make.add_argument('--output',type=Path,required=True)
    manifest=sub.add_parser('java-manifest');manifest.add_argument('--provider',type=Path,required=True);manifest.add_argument('--output',type=Path,required=True)
    final=sub.add_parser('verify-apk')
    for name in ('providers','dependency-provider','apk'):final.add_argument('--'+name,type=Path,required=True)
    a=parser.parse_args()
    if a.operation=='acquire':result=acquire(a.output)
    elif a.operation=='build':result=build(a.inputs,a.output)
    elif a.operation=='java-manifest':result=java_manifest(a.provider,a.output)
    else:result=verify_final(a.providers,a.dependency_provider,a.apk)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
