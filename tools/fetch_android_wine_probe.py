#!/usr/bin/env python3
"""Acquire only the exact successful CI inputs pinned for the Wine diagnostic."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
try:
    from . import build_android_wine_probe as wine, package_android_wine_sources as sources
    from .release_server_dependencies import Github, API
    from .release_client_inputs import ClientArtifacts
except ImportError:
    import build_android_wine_probe as wine, package_android_wine_sources as sources
    from release_server_dependencies import Github, API
    from release_client_inputs import ClientArtifacts

require=wine.require


def successful_input(api,run_id,revision,artifact_id,pin):
    run=api.json('/actions/runs/'+str(run_id))
    require(run.get('id')==run_id and run.get('head_sha')==revision and
            run.get('status')=='completed' and run.get('conclusion')=='success','wine-input-run-not-qualified')
    artifact=api.json('/actions/artifacts/'+str(artifact_id))
    require(artifact.get('id')==artifact_id and artifact.get('expired') is False and
            artifact.get('workflow_run',{}).get('id')==run_id and
            artifact.get('workflow_run',{}).get('head_sha')==revision and
            artifact.get('size_in_bytes')==pin['bytes'],'wine-input-artifact-provenance')
    digest=artifact.get('digest')
    require(digest in (None,'sha256:'+pin['sha256']),'wine-input-artifact-digest')


def fetch(client_source,output):
    runtime_pin,client_pin=wine.pins()
    require(not os.path.lexists(output),'wine-input-output-exists')
    wine.client.fetch_sources.verify_checkout(client_source,dict(commit=client_pin['sourceRevision'],submodules={}),[])
    token=os.environ.get('GITHUB_TOKEN');api=Github(token);client_api=ClientArtifacts(token)
    wine.client.archives.directory(output.parent,create=True)
    stage=Path(tempfile.mkdtemp(prefix='.wine-inputs-',dir=output.parent))
    try:
        for key,artifact_key,name in (('artifact','artifactId','runtime.zip'),('sourcesArtifact','sourcesArtifactId','runtime-sources.zip')):
            successful_input(api,runtime_pin['workflowRun'],runtime_pin['sourceRevision'],runtime_pin[artifact_key],runtime_pin[key])
            api.download(API+'/actions/artifacts/'+str(runtime_pin[artifact_key])+'/zip',stage/name,runtime_pin[key])
        successful_input(client_api,client_pin['workflowRun'],client_pin['sourceRevision'],client_pin['artifactId'],client_pin['artifact'])
        client_api.download(client_pin['artifactId'],stage/'client.zip',client_pin['artifact'])
        package=stage/'runtime-package';package.mkdir()
        with sources.source_zip(stage/'runtime.zip') as (archive,members):
            require(set(members)==set(runtime_pin['files']),'wine-runtime-artifact-inventory')
            for name,pin in runtime_pin['files'].items():
                require('/' not in name and members[name].file_size==pin['bytes'],'wine-runtime-member-size-or-name')
                with archive.open(members[name]) as incoming,(package/name).open('xb') as outgoing:
                    require(wine.client.archives.hash_stream(incoming,pin['bytes'],outgoing)==pin['sha256'],'wine-runtime-member-hash')
        wine.runtime_package(package,runtime_pin)
        source_proof=sources.runtime_sources(stage/'runtime-sources.zip',runtime_pin,wine.client.small(package/'runtime.json',131072))
        recipe=wine.client.source_blob(client_source,client_pin['sourceRevision'],'cmake/XvidPortable.cmake').decode()
        url=re.search(r'URL (https://downloads\.xvid\.com/downloads/xvidcore-1\.3\.7\.tar\.gz)\s',recipe)
        digest=re.search(r'URL_HASH SHA256=([a-f0-9]{64})\s',recipe)
        require(url and digest,'wine-client-xvid-source-pin')
        with api.open(url.group(1),accept='application/octet-stream') as incoming,(stage/'xvidcore-1.3.7.tar.gz').open('xb') as outgoing:
            import hashlib
            count=0;value=hashlib.sha256()
            while block:=incoming.read(128*1024):
                count+=len(block);require(count<=16*1024**2,'wine-xvid-download-limit');value.update(block);outgoing.write(block)
            require(count>0 and value.hexdigest()==digest.group(1),'wine-xvid-download-hash')
        (stage/'input-evidence.json').write_bytes(wine.encoded(dict(runtimeSources=source_proof,runtimePin=runtime_pin,
            clientPin=client_pin,androidRuntimeQualified=False,arm64Qualified=False,gameplayQualified=False)))
        wine.client.publish_directory(stage,output);wine.client.archives.sync_directory(output.parent)
        return dict(inputsVerified=True,output=str(output),runtimeSourcePackages=source_proof['sourcePackages'])
    finally:
        if stage.exists():shutil.rmtree(stage)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(fetch(args.client_source,args.output),indent=2))


if __name__=='__main__':main()
