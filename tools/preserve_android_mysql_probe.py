#!/usr/bin/env python3
"""Retain exact fresh x64 MySQL fixture inputs and their paired source artifact.

This copies no emulator filesystem or database. A retained runtime is not an
Android success receipt, an offline consumer pin or a production ARM64 provider.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

if not __package__:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import verify_android_mysql_probe as verify, build_android_mysql_probe as builder
from tools import package_server_engine as engine, package_server_content as transaction

require=builder.require
archives=builder.archives
MAX_SOURCES=8<<30


def verify_sources(directory,runtime_raw,lock_raw):
    directory=archives.directory(directory)
    runtime=json.loads(runtime_raw);lock=json.loads(lock_raw)
    manifest_path=directory/'SOURCE-MANIFEST.json'
    with archives.plain_file(manifest_path) as stream:raw=stream.read((2<<20)+1)
    require(len(raw)<=2<<20,'mysql-retention-source-manifest-bound');manifest=json.loads(raw)
    require(type(manifest.get('formatVersion')) is int and manifest['formatVersion']==1 and
            manifest.get('scope')=='installed-ubuntu-package-corresponding-sources' and
            manifest.get('runtimeManifestSha256')==builder.hashlib.sha256(runtime_raw).hexdigest() and
            manifest.get('sourceLockSha256')==builder.hashlib.sha256(lock_raw).hexdigest() and
            manifest.get('sourcePackages')==runtime.get('sourcePackages') and
            type(manifest.get('sourcePackages')) is list and 0<len(manifest['sourcePackages'])<=512,
            'mysql-retention-source-runtime-binding')
    rows=manifest.get('files');require(type(rows) is list and 0<len(rows)<=4096,'mysql-retention-source-inventory-bound')
    names=set();total=0
    for row in rows:
        name=row.get('file')
        require(type(name) is str and re.fullmatch('[A-Za-z0-9][A-Za-z0-9.+_~%-]*',name) and name not in names and
                type(row.get('bytes')) is int and 0<row['bytes']<=2<<30 and
                re.fullmatch('[0-9a-f]{64}',row.get('sha256','')), 'mysql-retention-source-entry')
        names.add(name);total+=row['bytes'];require(total<=MAX_SOURCES,'mysql-retention-source-total-bound')
        require(builder.identity(directory/name)=={key:row[key] for key in ('bytes','sha256')},
                'mysql-retention-source-file-changed')
    require(type(manifest.get('fileBytes')) is int and manifest['fileBytes']==total and
            {p.name for p in directory.iterdir()}==names|{'SOURCE-MANIFEST.json','server-runtime.json','sources.lock.json'} and
            verify.reserve.read_small(directory/'server-runtime.json')==runtime_raw and
            verify.reserve.read_small(directory/'sources.lock.json')==lock_raw,'mysql-retention-source-closure')
    selected={row['file']:row for row in rows}
    require(all(selected.get(row['file'])=={key:row[key] for key in ('file','bytes','sha256')} for row in lock['mysql']['sourceArchives']),
            'mysql-retention-original-mysql-source-pins')
    return manifest,builder.identity(manifest_path)


def retain(provider,proot_provider,apk,test_apk,sources,revision,source_artifact_id,source_artifact_digest,output):
    require(re.fullmatch('[0-9a-f]{40}',revision or '') and type(source_artifact_id) is int and source_artifact_id>0 and
            re.fullmatch('[0-9a-f]{64}',source_artifact_digest or ''),'mysql-retention-exact-source-artifact-required')
    provider=archives.directory(provider);sources=archives.directory(sources)
    proof=verify.verify(provider,proot_provider,apk)
    assets=provider/'assets'/builder.ASSET
    runtime=verify.reserve.read_small(assets/'runtime.json');lock=verify.reserve.read_small(assets/'sources.lock.json')
    source_manifest,source_id=verify_sources(sources,runtime,lock)
    require(0<test_apk.stat().st_size<=64<<20,'mysql-retention-test-apk-bound')
    output=Path(os.path.abspath(output));archives.directory(output.parent,create=True)
    require(not os.path.lexists(output) and all(output!=p and output not in p.parents and p not in output.parents
        for p in (provider,sources,Path(os.path.abspath(apk)),Path(os.path.abspath(test_apk)))),
        'mysql-retention-existing-or-overlapping-output')
    stage=Path(tempfile.mkdtemp(prefix='.'+output.name+'.stage-',dir=output.parent))
    try:
        retained={}
        for name in sorted(builder.NAMES):
            retained['provider/assets/mysql-probe/'+name]=(assets/name,builder.identity(assets/name))
        retained.update({'probe.apk':(apk,builder.identity(apk)),'tests.apk':(test_apk,builder.identity(test_apk)),
                         'SOURCE-MANIFEST.json':(sources/'SOURCE-MANIFEST.json',source_id)})
        for name,(path,row) in retained.items():engine.copy_verified(path,stage/name,row,0o444)
        q=dict(formatVersion=1,scope='retained-fresh-android-x86-64-mysql-fixture-inputs-only',sourceRevision=revision,
            sourceCompanionArtifact=dict(id=source_artifact_id,sha256=source_artifact_digest,
                sourceRevision=revision,sourceManifest=source_id,sourceArchiveFiles=len(source_manifest['files']),
                sourceArchiveBytes=source_manifest['fileBytes'],completeInstalledSourceFilesReadBack=True),
            files={name:row for name,(_,row) in retained.items()},providerVerification=proof,
            rootfsAndApkBytesReadBack=True,emulatorFilesystemCopied=False,databaseStateCopied=False,
            offlineConsumerPinCreated=False,androidExecutionSucceeded=False,productionAdapterQualified=False,
            arm64Qualified=False,serverSchemasQualified=False,gameplayQualified=False)
        engine.put_metadata(stage/'retention.json',q)
        archives.sync_directory(stage);transaction.publish_directory(stage,output);archives.sync_directory(output.parent)
        return q
    finally:
        if stage.exists():shutil.rmtree(stage)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('provider','proot-provider','apk','test-apk','sources','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--revision',required=True);p.add_argument('--source-artifact-id',type=int,required=True)
    p.add_argument('--source-artifact-digest',required=True);a=p.parse_args()
    print(json.dumps(retain(a.provider,a.proot_provider,a.apk,a.test_apk,a.sources,a.revision,
        a.source_artifact_id,a.source_artifact_digest,a.output),sort_keys=True,indent=2))

if __name__=='__main__':main()
