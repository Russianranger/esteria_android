#!/usr/bin/env python3
"""Select the retained seven-patch derivative for a separate actual client pairing."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import stat
import tempfile

try:
    from . import provider_client_runtime as client, verify_server_engine_runtime as engine
    from . import qualify_dbimport as importer
    from .release_server_dependencies import Github,API
    from .package_server_content import publish_directory
except ImportError:
    import provider_client_runtime as client, verify_server_engine_runtime as engine
    import qualify_dbimport as importer
    from release_server_dependencies import Github,API
    from package_server_content import publish_directory

ROOT=Path(__file__).resolve().parents[1]
LOCK=ROOT/'runtime/client-auth-candidate/inputs.lock.json'
require=client.require


def inputs():
    raw=client.small(LOCK);pin=json.loads(raw)
    require(type(pin.get('formatVersion')) is int and pin['formatVersion']==1 and pin.get('scope')=='separate-measured471-new-wine-seven-patch-auth-inputs' and
        pin.get('clientInput')==json.loads(client.small(client.PIN)) and pin.get('privatePeCopy') is True and
        all(pin.get(k) is False for k in ('thisTupleCompiledAuthQualified','androidQualified','gameplayQualified')),
        'matched-auth-separate-input-selection')
    require(pin['clientComponentProof'].get('path')=='runtime/evidence/wine-arm64-selected471-41069065089.json',
            'matched-auth-component-proof-path')
    proof=json.loads(client.small(ROOT/pin['clientComponentProof']['path']))
    client.verify_identity(ROOT/pin['clientComponentProof']['path'],pin['clientComponentProof'])
    require(proof.get('selected471ActualComponentGatesPassed') is True and
        proof.get('selectedClientInput')==pin['clientInput'] and
        proof.get('qualification',{}).get('runtimeArchiveSha256')==pin['runtimeArchiveSha256'],
        'matched-auth-client-new-wine-component-proof')
    public=json.loads(client.small(ROOT/'runtime/wine-arm64-publication/dependency-release.lock.json'))
    require(public['runtimeInput']['files']['wine-arm64.tar.gz']['sha256']==pin['runtimeArchiveSha256'],
            'matched-auth-public-runtime-binding')
    server=pin['server'];current=json.loads(client.small(ROOT/'runtime/server/programs-provider.lock.json'))
    require(server['programs']=={name:row['stripped'] for name,row in current['programPairs'].items()} and
            server['serverSourceLock']==current['serverBuildSourceLock'] and
            type(server['workflowRun']) is int and server['workflowRun']>0 and
            re.fullmatch('[0-9a-f]{40}',server['integrationRevision']), 'matched-auth-current-seven-patch-programs')
    return pin,hashlib.sha256(raw).hexdigest()


def extract(path,output,pin):
    require(not os.path.lexists(output),'matched-auth-server-output-exists')
    client.verify_identity(path,pin['artifact'])
    output.mkdir(mode=0o700)
    prefixes={'server-engine-package/':'package/', 'engine-inputs/content/':'content/'}
    wanted='engine-inputs/locked/sources.lock.json';seen=set();total=0
    with client.archives.plain_file(path) as stream,client.checked_zip(stream,(),maximum_entries=4096) as archive:
        for item in archive.infolist():
            target='locked/sources.lock.json' if item.filename==wanted else None
            for prefix,destination in prefixes.items():
                if item.filename.startswith(prefix):target=destination+item.filename.removeprefix(prefix)
            if target is None:continue
            require(not item.is_dir() and stat.S_ISREG(item.external_attr>>16) and
                client.archives.member_path(target)==target and target not in seen,'matched-auth-server-member')
            total+=item.file_size;require(0<=item.file_size<=512<<20 and total<=768<<20,'matched-auth-server-expanded-bound')
            selected=output/target;client.archives.directory(selected.parent,create=True)
            with archive.open(item) as incoming,selected.open('xb') as out:client.archives.hash_stream(incoming,item.file_size,out)
            seen.add(target)
    receipt=output/'package/package-receipt.json';lock=output/'locked/sources.lock.json'
    client.verify_identity(receipt,pin['packageReceipt']);client.verify_identity(lock,pin['serverSourceLock'])
    extraction=engine.extract(receipt,output/'install')
    compiled=json.loads(client.small(output/'install/provenance/server-modules.json'))
    build,_,programs,derivative=importer.select_install(output/'install',compiled,lock,receipt)
    require(programs==pin['programs'] and build['buildId']==pin['originalBuildId'] and
        derivative['runtimeArchive']==pin['runtimeArchive'],'matched-auth-seven-patch-program-identity')
    content=json.loads(client.small(output/'content/package-receipt.json'))
    require(content.get('sourceLockSha256')==pin['serverSourceLock']['sha256'] and content.get('moduleSelectionVerified') is True and
        content.get('archiveReadBackVerified') is True,'matched-auth-content-source-binding')
    return dict(extraction=extraction,engineDerivative=derivative,contentReceipt=client.identity(output/'content/package-receipt.json'))


def fetch(output,api=None):
    require(not os.path.lexists(output),'matched-auth-output-exists')
    pin,identity=inputs();server=pin['server'];api=api if api is not None else Github(os.environ.get('GITHUB_TOKEN'))
    run=api.json('/actions/runs/'+str(server['workflowRun']))
    require(run.get('id')==server['workflowRun'] and run.get('head_sha')==server['integrationRevision'] and run.get('head_branch')=='android/client-server' and
        run.get('path')=='.github/workflows/server-engine-package.yml' and run.get('conclusion')=='success' and
        run.get('status')=='completed','matched-auth-server-successful-producer')
    row=api.json('/actions/artifacts/'+str(server['artifact']['id']));producer=row.get('workflow_run',{})
    require(row.get('id')==server['artifact']['id'] and row.get('name')=='unsealed-server-engine-runtime-'+server['integrationRevision'] and row.get('expired') is False and
        row.get('size_in_bytes')==server['artifact']['bytes'] and row.get('digest')=='sha256:'+server['artifact']['sha256'] and
        producer.get('id')==server['workflowRun'] and producer.get('head_sha')==server['integrationRevision'],
        'matched-auth-server-artifact-provenance')
    client.archives.directory(output.parent,create=True);stage=Path(tempfile.mkdtemp(prefix='.matched-auth-',dir=output.parent))
    try:
        original=stage/'original-server.zip';api.download(API+'/actions/artifacts/'+str(server['artifact']['id'])+'/zip',original,server['artifact'])
        selected=extract(original,stage/'server',server)
        proof=dict(formatVersion=1,scope='retained-seven-patch-server-for-new-client-wine-auth-only',inputLockSha256=identity,
            selectedServer=server,prepared=selected,serverRecompiled=False,clientExecuted=False,
            androidQualified=False,gameplayQualified=False)
        (stage/'preparation.json').write_bytes(client.encoded(proof));publish_directory(stage,output)
        return proof
    finally:
        if stage.exists():shutil.rmtree(stage)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(fetch(args.output.absolute()),indent=2))


if __name__=='__main__':main()
