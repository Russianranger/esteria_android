#!/usr/bin/env python3
"""Fetch measured prequalified client inputs; never select a latest or launch a game."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

if not __package__:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import provider_client_runtime as provider
from tools.release_client_inputs import ClientArtifacts

LOCK=Path(__file__).resolve().parents[1]/'runtime/client/auth-reference.lock.json'
require=provider.require
SCOPES=('linuxArm64CodecQualified','linuxArm64VulkanPresentationQualified',
    'linuxArm64VulkanTextureLifecycleQualified','linuxArm64ClientEntryQualified',
    'linuxArm64ClientOfflineBoundariesQualified','linuxArm64ClientLoopbackTransportQualified',
    'linuxArm64ClientGruntSyntheticPeerQualified','linuxArm64VulkanEngineFrameReadbackQualified',
    'linuxArm64FmodPcmTransportQualified')


def load_pin():
    raw=provider.small(LOCK);pin=json.loads(raw)
    require(type(pin.get('formatVersion')) is int and pin['formatVersion']==1 and pin.get('scope')=='measured-client-for-compiled-authserver-qualification' and
        pin.get('repository')=='Russianranger/wowdecomp_esteria' and
        re.fullmatch('[a-f0-9]{40}',pin['sourceRevision']) and
        type(pin['workflowRun']) is int and pin['workflowRun']>0 and
        re.fullmatch(r'[0-9]+\.[0-9]+',pin['buildId']) and
        re.fullmatch('[a-f0-9]{64}',pin['clientManifestSha256']),'invalid-auth-client-source-pin')
    for key in ('clientArtifact','wineEvidence'):
        row=pin[key]
        require(type(row['id']) is int and row['id']>0 and type(row['bytes']) is int and
            22<=row['bytes']<=512*1024**2 and re.fullmatch('[a-f0-9]{64}',row['sha256']),'invalid-auth-client-artifact-pin')
    require(pin['wineEvidence']['receiptPath']=='wine-codec-evidence/qualification.json' and
        re.fullmatch('[a-f0-9]{64}',pin['wineEvidence']['receiptSha256']) and
        all(pin.get(key) is False for key in ('compiledAuthserverQualified','androidRuntimeQualified','gameplayQualified')),
        'invalid-auth-client-qualification-scope')
    return pin,hashlib.sha256(raw).hexdigest()


def verify_remote(api,pin):
    run=api.json('/actions/runs/'+str(pin['workflowRun']))
    require(run.get('id')==pin['workflowRun'] and run.get('head_sha')==pin['sourceRevision'] and
        run.get('status')=='completed' and run.get('conclusion')=='success','client-workflow-did-not-pass')
    for key,prefix in (('clientArtifact','client-ARM64-'),('wineEvidence','linux-arm64-wine-')):
        expected=pin[key];actual=api.json('/actions/artifacts/'+str(expected['id']))
        require(actual.get('id')==expected['id'] and actual.get('name')==prefix+pin['sourceRevision'] and
            actual.get('expired') is False and actual.get('size_in_bytes')==expected['bytes'] and
            actual.get('digest')=='sha256:'+expected['sha256'] and
            actual.get('workflow_run',{}).get('id')==pin['workflowRun'] and
            actual.get('workflow_run',{}).get('head_sha')==pin['sourceRevision'],'client-artifact-provenance-differs')


def validate_receipt(value,pin):
    require(type(value.get('formatVersion')) is int and value['formatVersion']==1 and value.get('scope')=='native-linux-arm64-wine-component-fixtures' and
        all(value.get(key) is True for key in SCOPES) and value.get('processNamespaceExited') is True and
        type(value.get('namespaceExit')) is int and value['namespaceExit']==0 and
        all(value.get(key) is False for key in ('androidRuntimeQualified','gameInitializationStarted',
            'renderingQualified','audioQualified','gameLoginQualified','serverRuntimeIncluded')),
        'client-component-scopes-did-not-pass')
    client=value.get('client',{})
    require(client.get('sourceRevision')==pin['sourceRevision'] and client.get('buildId')==pin['buildId'] and
        client.get('clientManifestSha256')==pin['clientManifestSha256'],'client-evidence-identity-differs')


def evidence(path,pin):
    expected=pin['wineEvidence'];provider.verify_identity(path,expected)
    with provider.archives.plain_file(path) as incoming,provider.checked_zip(incoming,required=(expected['receiptPath'],)) as archive:
        info=archive.getinfo(expected['receiptPath']);require(0<info.file_size<=1024*1024,'client-evidence-size-bound')
        with archive.open(info) as source:raw=source.read(1024*1024+1)
        require(len(raw)==info.file_size and hashlib.sha256(raw).hexdigest()==expected['receiptSha256'],
            'client-evidence-receipt-differs')
    value=json.loads(raw);validate_receipt(value,pin);return raw


def prepare(output,api):
    pin,pin_sha=load_pin();require(not os.path.lexists(output),'existing-client-auth-inputs-preserved')
    verify_remote(api,pin);output.mkdir(mode=0o700,parents=True)
    for name,key in (('client-arm64.zip','clientArtifact'),('wine-evidence.zip','wineEvidence')):
        api.download(pin[key]['id'],output/name,pin[key]);provider.verify_identity(output/name,pin[key])
    receipt=evidence(output/'wine-evidence.zip',pin);(output/'wine-component-qualification.json').write_bytes(receipt)
    value=dict(formatVersion=1,scope='measured-client-auth-inputs-only',inputLockSha256=pin_sha,
        sourceRevision=pin['sourceRevision'],buildId=pin['buildId'],clientManifestSha256=pin['clientManifestSha256'],
        clientArtifact=pin['clientArtifact'],wineEvidence=pin['wineEvidence'],componentScopes=list(SCOPES),
        compiledAuthserverQualified=False,androidRuntimeQualified=False,gameplayQualified=False)
    (output/'preparation.json').write_text(json.dumps(value,indent=2)+'\n');return value


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    try:
        prepare(args.output.absolute(),ClientArtifacts(os.environ.get('GITHUB_TOKEN')))
        print('Measured client and Wine component inputs prepared; compiled server authentication remains unqualified.');return 0
    except BaseException:
        print('Measured client preparation failed; no signed download URL, credential or response exported.',file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
