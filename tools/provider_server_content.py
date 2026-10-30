#!/usr/bin/env python3
"""Package exact original SQL/config/notices as an install-only Android provider.

The original tar and external receipt are copied unchanged. Full source-selected
member verification occurs here and again in the product before any SQL use.
"""
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
from runtime import server_content as content
from tools import prepare_runtime as archives,verify_server_build as files,server_provider_sources as source_binding
from tools import package_server_content as transaction,provider_client_runtime as zips

ROOT=Path(__file__).resolve().parents[1]
LOCK=ROOT/'runtime/server/content-provider.lock.json'
ASSETS='server-content'
ARCHIVE='server-content.archive'
NAMES={'provider.json',ARCHIVE,'package-receipt.json'}
require=files.require
encoded=transaction.canonical


def read_json(path,maximum=16*1024**2):
    with files.plain_file(path) as stream:raw=stream.read(maximum+1)
    require(len(raw)<=maximum,'server-content-metadata-bound')
    return content._json(raw),dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def require_file(path,pin):
    require(files.identity(path)=={k:pin[k] for k in ('bytes','sha256')},'server-content-input-identity:'+path.name)


def load_pin():
    pin,_=read_json(LOCK,128*1024)
    require(pin.get('formatVersion')==1 and pin.get('scope')=='measured-server-content-provider-inputs' and
            pin.get('luaDisabled') is True and pin.get('originalNoticesPreserved') is True and
            all(pin.get(k) is False for k in ('sqlExecuted','androidRuntimeQualified','gameplayQualified')),
            'server-content-pin-scope')
    source_binding.validate_current(pin,ROOT/'sources.lock.json')
    require(set(pin.get('requiredFiles',{}))==content.METADATA and
            pin['requiredFiles']['metadata/compiled-modules.json']==pin['compiledModules'] and
            pin['archive']['file']=='server-content.tar.gz','server-content-required-metadata-selection')
    dependency,_=read_json(ROOT/'runtime/server/android-provider.lock.json')
    require(pin['requiredServerRuntimeArchiveSha256']==dependency['archive']['sha256'],
            'server-content-dependency-selection')
    for row in (pin['archive'],pin['receipt'],pin['compiledModules'],pin['originalBuild'],*pin['requiredFiles'].values()):
        content._identity(row)
    require(1<=pin['archiveEntries']<=pin['limits']['entries']<=40000 and
            pin['archiveFileBytes']<=pin['limits']['fileBytes']<=content.MAX_TOTAL and
            pin['limits']['metadataBytes']==content.MAX_METADATA,'server-content-pin-bounds')
    return pin


def validate_metadata(receipt,metadata,pin):
    require(receipt.get('formatVersion')==1 and receipt.get('scope')=='immutable-server-source-content-package' and
            receipt.get('source')==pin['serverSource'] and receipt.get('sourceLockSha256')==pin['serverBuildSourceLock']['sha256'] and
            receipt.get('moduleSelectionVerified') is True and receipt.get('archiveReadBackVerified') is True and
            receipt.get('luaMode')=='disabled' and receipt.get('luaFiles')==0 and receipt.get('sourceDirectory')=='source' and
            receipt.get('configurationRequirements')=={'Eluna.Enabled':False,'Eluna.ScriptPath':'lua_scripts'},
            'server-content-original-receipt-selection')
    require(receipt.get('archive')=={k:pin['archive'][k] for k in ('bytes','sha256')},'server-content-original-archive-selection')
    inventory=receipt['archiveFiles'];require(len(inventory)==pin['archiveEntries'] and
            sum(content._identity(row)['bytes'] for row in inventory.values())==pin['archiveFileBytes'] and
            {name for name in inventory if name.startswith('metadata/')}==content.METADATA,
            'server-content-original-inventory-selection')
    for name,row in pin['requiredFiles'].items():require(inventory.get(name)==row,'server-content-metadata-pin:'+name)
    manifest=metadata['metadata/content-manifest.json'];compiled=metadata['metadata/compiled-modules.json']
    lua=metadata['metadata/lua-map.json']
    require(compiled.get('serverBuild')==pin['originalBuild'] and receipt.get('compiledModules')==pin['compiledModules'],
            'server-content-original-compiled-build-selection')
    plan={k:v for k,v in receipt.items() if k not in ('archive','archiveFiles','archiveReadBackVerified','deterministicArchive')}
    require(metadata['metadata/package-plan.json']==plan,'server-content-original-plan-selection')
    # Share the product's strict source/module/Lua selection. No Git or SQL runs.
    payload=content._selection(manifest,compiled,lua,pin['serverSource'],pin['serverBuildSourceLock']['sha256'])
    require(set(inventory)==set(payload)|content.METADATA,'server-content-source-payload-selection')
    for name,(origin,path,row) in payload.items():
        require(inventory[name]==dict(content._identity(row),gitBlob=row['gitBlob'],origin=origin,source=path),
                'server-content-source-payload-identity')
    return inventory


def audit_archive(path,receipt,pin):
    require_file(path,pin['archive'])
    inventory=receipt.get('archiveFiles',{});content._unique_paths(inventory)
    require(1<=len(inventory)<=pin['limits']['entries'],'server-content-archive-inventory-bound')
    metadata={};seen=set();total=0
    with files.plain_file(path) as source,archives.bounded_tar(source,pin['limits']) as archive:
        for item in archive:
            require(item.isfile() and item.name in inventory and item.name not in seen and
                    item.mode==0o644 and item.uid==item.gid==item.mtime==0 and not item.uname and not item.gname,
                    'server-content-archive-member-contract')
            row=content._identity(inventory[item.name]);require(item.size==row['bytes'],'server-content-archive-member-size')
            digest=hashlib.sha256();blob=hashlib.sha1(('blob '+str(item.size)+'\0').encode());captured=[];prefix=b''
            with archive.extractfile(item) as stream:
                while block:=stream.read(128*1024):
                    if len(prefix)<4:prefix=(prefix+block)[:4]
                    digest.update(block);blob.update(block)
                    if item.name in content.METADATA:
                        require(item.size<=content.MAX_METADATA,'server-content-archive-metadata-bound');captured.append(block)
            require(digest.hexdigest()==row['sha256'] and prefix!=b'\x7fELF','server-content-archive-member-hash-or-ELF')
            if 'gitBlob' in inventory[item.name]:require(blob.hexdigest()==inventory[item.name]['gitBlob'],
                                                        'server-content-source-git-blob')
            if item.name in content.METADATA:metadata[item.name]=content._json(b''.join(captured))
            seen.add(item.name);total+=item.size;archive.members.clear()
    require(seen==set(inventory) and len(seen)==pin['archiveEntries'] and total==pin['archiveFileBytes'],
            'server-content-archive-complete-inventory')
    validate_metadata(receipt,metadata,pin)
    return metadata


def descriptor(package,pin,asset_archive=False):
    require_file(package/'package-receipt.json',pin['receipt'])
    receipt,_=read_json(package/'package-receipt.json')
    audit_archive(package/(ARCHIVE if asset_archive else pin['archive']['file']),receipt,pin)
    limits=pin['limits']
    return dict(formatVersion=1,scope='android-server-content-install-only',packageKey='server-content-arm64',
        archive=dict(pin['archive'],assetPath=ASSETS+'/'+ARCHIVE),archiveEntries=pin['archiveEntries'],
        archiveFileBytes=pin['archiveFileBytes'],requiredFiles=pin['requiredFiles'],limits=limits,
        inputLockSha256=files.identity(LOCK)['sha256'],**source_binding.descriptor_fields(pin),
        receipt=pin['receipt'],compiledModules=pin['compiledModules'],
        requiredServerRuntimeArchiveSha256=pin['requiredServerRuntimeArchiveSha256'],originalNoticesPreserved=True,
        luaDisabled=True,archiveVerified=True,fullSourceSelectedInventoryVerified=True,elfIncluded=False,
        freshSetupFreeBytes=pin['archive']['bytes']+pin['archiveFileBytes']+limits['metadataBytes']+pin['receipt']['bytes']+(64<<20),
        sqlExecuted=False,androidRuntimeQualified=False,gameplayQualified=False)


def stage_artifact(path,output,pin):
    require_file(path,pin['artifact']);output.mkdir(mode=0o700)
    required={'server-content/package-receipt.json','server-content/server-content.tar.gz',
              'server-modules.json','server-content-manifest.json'}
    with files.plain_file(path) as source,zips.checked_zip(source,required=required,maximum_entries=16) as archive:
        require(set(archive.namelist())==required,'server-content-original-artifact-member-set')
        for name,row in (('package-receipt.json',pin['receipt']),('server-content.tar.gz',pin['archive'])):
            item=archive.getinfo('server-content/'+name);require(item.file_size==row['bytes'],'server-content-original-artifact-member-size')
            with archive.open(item) as incoming,(output/name).open('xb') as outgoing:
                require(archives.hash_stream(incoming,row['bytes'],outgoing)==row['sha256'],'server-content-original-artifact-member-hash')
        item=archive.getinfo('server-modules.json')
        with archive.open(item) as incoming:
            require(archives.hash_stream(incoming,pin['compiledModules']['bytes'])==pin['compiledModules']['sha256'],
                    'server-content-artifact-compiled-modules')


def build(package,output,artifact=None):
    pin=load_pin();output=Path(os.path.abspath(output));archives.directory(output.parent,create=True)
    require(not os.path.lexists(output),'server-content-provider-output-exists')
    with tempfile.TemporaryDirectory(prefix='esteria-original-content-') as temporary:
        if artifact is not None:
            package=Path(temporary)/'original';stage_artifact(artifact,package,pin)
        else:package=archives.directory(Path(os.path.abspath(package)))
        require(package!=output and package not in output.parents and output not in package.parents,'server-content-provider-input-overlap')
        proof=descriptor(package,pin)
        stage=Path(tempfile.mkdtemp(prefix='.'+output.name+'.stage-',dir=output.parent))
        try:
            assets=stage/'assets'/ASSETS;assets.mkdir(parents=True,mode=0o700)
            for name,source in ((ARCHIVE,package/pin['archive']['file']),('package-receipt.json',package/'package-receipt.json')):
                with files.plain_file(source) as incoming,(assets/name).open('xb') as outgoing:
                    shutil.copyfileobj(incoming,outgoing,128*1024);outgoing.flush();os.fsync(outgoing.fileno())
            (assets/'provider.json').write_bytes(encoded(proof));verify(stage)
            transaction.publish_directory(stage,output);archives.sync_directory(output.parent)
            return proof
        finally:
            if stage.exists():shutil.rmtree(stage)


def verify(provider,apk=None):
    assets=archives.directory(Path(os.path.abspath(provider))/'assets'/ASSETS)
    require({p.name for p in assets.iterdir()}==NAMES,'server-content-provider-file-set')
    proof=descriptor(assets,load_pin(),True)
    require((assets/'provider.json').read_bytes()==encoded(proof),'server-content-provider-descriptor-changed')
    if apk is not None:
        expected={'assets/'+ASSETS+'/'+name for name in NAMES}
        with files.plain_file(apk) as source,zips.checked_zip(source,required=expected,maximum_bytes=4<<30,
                maximum_entries=100000,maximum_directory=32<<20) as archive:
            require({n for n in archive.namelist() if n.startswith('assets/'+ASSETS+'/')}==expected,
                    'server-content-apk-asset-set')
            for name in NAMES:
                item=archive.getinfo('assets/'+ASSETS+'/'+name);local=assets/name
                require(item.file_size==local.stat().st_size,'server-content-apk-asset-size')
                if name==ARCHIVE:require(item.compress_type==zipfile.ZIP_STORED,'server-content-apk-archive-must-be-stored')
                with archive.open(item) as incoming:require(archives.hash_stream(incoming,item.file_size)==files.identity(local)['sha256'],
                                                          'server-content-apk-asset-hash')
    return dict(providerVerified=True,apkBytesVerified=apk is not None,archive=proof['archive'],
                archiveEntries=proof['archiveEntries'],archiveFileBytes=proof['archiveFileBytes'],
                fullSourceSelectedInventoryVerified=True,sqlExecuted=False,androidRuntimeQualified=False,gameplayQualified=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='operation',required=True)
    b=sub.add_parser('build');group=b.add_mutually_exclusive_group(required=True)
    group.add_argument('--package',type=Path);group.add_argument('--artifact',type=Path);b.add_argument('--output',type=Path,required=True)
    v=sub.add_parser('verify');v.add_argument('--provider',type=Path,required=True);v.add_argument('--apk',type=Path)
    a=p.parse_args();result=build(a.package,a.output,a.artifact) if a.operation=='build' else verify(a.provider,a.apk)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
