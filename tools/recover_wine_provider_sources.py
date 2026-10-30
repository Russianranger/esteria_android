#!/usr/bin/env python3
"""Restore one filtered recipe file from retained producer sources; never rebuild."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile

try:
    from . import measure_wine_provider_candidates as measured
except ImportError:
    import measure_wine_provider_candidates as measured

require = measured.require
client = measured.client
MISSING = 'turnip/corresponding-source/build-recipe/.dockerignore'
INTEGRATION = 'source-selection/integration-source.tar'
SOURCE = 'runtime/turnip/.dockerignore'
RECEIPT = 'source-recovery.json'
WORKFLOW = '.github/workflows/wine-arm64-provider-source-recovery.yml'


def members(path):
    result = {}
    with client.archives.plain_file(path) as raw, client.checked_zip(raw,(),maximum_entries=4096) as archive:
        total = 0
        for item in archive.infolist():
            require(not item.is_dir() and stat.S_ISREG(item.external_attr >> 16), 'source-recovery-nonregular-member')
            total += item.file_size
            require(0 <= item.file_size <= 512<<20 and total <= 2<<30,'source-recovery-expanded-limit')
            with archive.open(item) as source:digest=client.archives.hash_stream(source,item.file_size)
            result[item.filename] = dict(bytes=item.file_size,sha256=digest)
    return result


def supplement(path):
    with client.archives.plain_file(path) as raw, client.checked_zip(raw,(),maximum_entries=4096) as archive:
        require(MISSING not in archive.namelist() and RECEIPT not in archive.namelist(),'source-recovery-already-complete')
        recipe = measured.member(archive,'turnip/turnip-build.json',2<<20)
        build = json.loads(recipe)
        require(build.get('integrationRevision') == measured.PRODUCER and build.get('compiled') is True and
                build.get('runtimeArchiveSha256') == measured.RUNTIME,'source-recovery-native-build-identity')
        wanted = measured.git_exact(SOURCE)
        require(build.get('recipeSources',{}).get('.dockerignore') == measured.byte_identity(wanted),
                'source-recovery-producer-recipe-hash')
        item = archive.getinfo(INTEGRATION)
        require(item.file_size <= 64<<20,'source-recovery-integration-archive-bound')
        found = None;count=0
        with archive.open(item) as source,tarfile.open(fileobj=source,mode='r|') as tar:
            for member in tar:
                count+=1;require(count<=100000,'source-recovery-integration-entry-bound')
                if member.name == SOURCE:
                    require(found is None and member.isfile() and member.size == len(wanted),'source-recovery-git-member')
                    with tar.extractfile(member) as incoming:found=incoming.read(len(wanted)+1)
                tar.members.clear()
        require(found == wanted,'source-recovery-retained-git-bytes-mismatch')
    blob=hashlib.sha1(('blob '+str(len(wanted))+'\0').encode()+wanted).hexdigest()
    return wanted,dict(path=MISSING,sourceRevision=measured.PRODUCER,sourcePath=SOURCE,gitBlob=blob,
        **measured.byte_identity(wanted),actualBuildReceipt=measured.byte_identity(recipe),
        retainedIntegrationArchive=dict(path=INTEGRATION,bytes=item.file_size))


def receipt(artifact,inventory,source):
    return dict(formatVersion=1,scope='exact-retained-turnip-recipe-source-only-recovery',
        originalNativeWorkflowRun=measured.RUN,originalNativeProducerRevision=measured.PRODUCER,
        originalArtifact=artifact,restoredSource=source,originalMembers=inventory,
        originalMemberBytesUnchanged=True,binariesRebuilt=False,newRuntimeExecutionQualified=False,
        androidQualified=False,hardwareQualified=False,gameplayQualified=False)


def recover(run_path,artifact_path,original,output):
    require(not os.path.lexists(output),'source-recovery-output-exists')
    run,_=measured.read_metadata(run_path);measured.run_metadata(run)
    api,_=measured.read_metadata(artifact_path);artifact=measured.artifact_metadata('turnip',original,api)
    inventory=members(original);raw,source=supplement(original);proof=receipt(artifact,inventory,source)
    client.archives.directory(output.parent,create=True)
    stage=Path(tempfile.mkdtemp(prefix='.wine-source-recovery-',dir=output.parent))
    try:
        with client.archives.plain_file(original) as stream,client.checked_zip(stream,(),maximum_entries=4096) as archive:
            for name,pin in inventory.items():
                target=stage/name;client.archives.directory(target.parent,create=True)
                with archive.open(name) as incoming,target.open('xb') as outgoing:
                    require(client.archives.hash_stream(incoming,pin['bytes'],outgoing)==pin['sha256'],
                            'source-recovery-original-member-changed')
                require(client.identity(target)==pin,'source-recovery-written-member-readback')
        target=stage/MISSING;client.archives.directory(target.parent,create=True);target.write_bytes(raw)
        require(client.identity(target)==measured.byte_identity(raw),'source-recovery-supplement-readback')
        (stage/RECEIPT).write_bytes(measured.encoded(proof))
        measured.publish_directory(stage,output);client.archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists():shutil.rmtree(stage)


def verify(original,recovered,artifact):
    original_members=members(original);actual_members=members(recovered)
    require(set(actual_members)==set(original_members)|{MISSING,RECEIPT} and
            all(actual_members[name]==pin for name,pin in original_members.items()),'source-recovery-original-members-differ')
    raw,source=supplement(original)
    require(actual_members[MISSING]==measured.byte_identity(raw),'source-recovery-restored-source-differs')
    with client.archives.plain_file(recovered) as stream,client.checked_zip(stream,(),maximum_entries=4096) as archive:
        actual=measured.member(archive,RECEIPT,2<<20)
    expected=receipt(artifact,original_members,source)
    require(actual==measured.encoded(expected),'source-recovery-receipt-differs')
    return expected


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('run-metadata','artifact-metadata','original-zip','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(recover(args.run_metadata,args.artifact_metadata,args.original_zip,args.output),indent=2))


if __name__=='__main__':main()
