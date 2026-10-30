#!/usr/bin/env python3
"""Acquire the exact qualified data4 provider inputs; do not rebuild the server.

Source and paired-debug archives stay outside Android assets. This reads pinned
Actions artifacts through the supported authenticated GitHub API. Their expiry
must be resolved by durable preservation before a final user package is released.
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
from tools import provider_server_data_tools as provider, qualify_server_providers as transfer
from tools import prepare_server_requalification as remote, measure_server_data_tools as measure

ROOT=Path(__file__).resolve().parents[1]
LOCK=ROOT/'runtime/server/data-tools-qualified-artifacts.lock.json'
require=provider.require
files=provider.files
engine=provider.engine
archives=provider.archives


def load_pin():
    pin,_=provider.shared.read_json(LOCK,128<<10)
    require(type(pin.get('formatVersion')) is int and pin['formatVersion']==1 and
            pin.get('scope')=='exact-actual-composed-data-tools-provider-inputs' and
            pin.get('providerInputLock')==files.identity(provider.LOCK) and
            set(pin.get('artifacts',{}))=={'package','native'} and
            all(pin.get(k) is False for k in ('androidRuntimeQualified','clientMpqConversionQualified','gameplayQualified')),
            'qualified-data-tools-exact-input-pin-required')
    targets=set()
    for row in pin['artifacts'].values():
        require(all(type(row.get(k)) is int and row[k]>0 for k in ('id','workflowRun','bytes')) and
                row['bytes']<=256<<20 and re.fullmatch('[0-9a-f]{40}',row.get('integrationRevision','')) and
                re.fullmatch('[0-9a-f]{64}',row.get('sha256','')), 'qualified-data-tools-artifact-pin')
        for name,item in row['members'].items():
            engine.content.safe_path(name);engine.content.safe_path(item['target']);provider.identity(item)
            require(item['target'] not in targets,'qualified-data-tools-input-target-collision');targets.add(item['target'])
    selected=provider.load_pin(sealed=True)
    expected={
        'package-receipt.json':selected['packageReceipt'],
        provider.SOURCE_RECEIPT:selected['actualOrderedSourceQualification']['receipt'],
        provider.SOURCE_ARCHIVE:selected['actualOrderedSourceQualification']['archive'],
        'native-ordered-build.json':selected['actualOrderedSourceQualification']['nativeBuild'],
        'dependency-observation.json':selected['actualOrderedSourceQualification']['dependencyObservation'],
        'ordered-strip-receipt.json':selected['orderedStripReceipt'],
        'ordered-extractors-debug-arm64.tar.gz':selected['debugArchives']['ordered'],
        'stock-package-receipt.json':provider.stock.load_pin(sealed=True)['packageReceipt'],
        selected['archive']['file']:selected['archive']}
    package=pin['artifacts']['package']['members']
    require(set(package)=={'data-tools-package/'+name for name in expected}|
            {'data-tools-inputs/stock-debug/stock-extractors-debug-arm64.tar.gz'},
            'qualified-data-tools-exact-package-closure')
    for name,row in expected.items():
        actual=package['data-tools-package/'+name]
        require(provider.identity(actual)==provider.identity(row) and actual['target']=='package/'+name,
                'qualified-data-tools-package-selection-differs')
    debug=package['data-tools-inputs/stock-debug/stock-extractors-debug-arm64.tar.gz']
    require(provider.identity(debug)==provider.identity(selected['debugArchives']['stock']) and
            debug['target']=='stock-debug/stock-extractors-debug-arm64.tar.gz',
            'qualified-data-tools-original-debug-selection-differs')
    native=pin['artifacts']['native']['members']
    require(set(native)=={'native-cli.json','native-cli-phase.json','lookup-result.json'} and
            all(row['target']=='native/'+name for name,row in native.items()) and
            provider.identity(native['native-cli.json'])==selected['nativeCliReceipt'],
            'qualified-data-tools-native-selection-differs')
    return pin


def acquire(output,api=None):
    pin=load_pin();output=Path(os.path.abspath(output));archives.directory(output.parent,create=True)
    require(not os.path.lexists(output),'existing-qualified-data-tools-inputs-preserved')
    require(shutil.disk_usage(output.parent).free>=1<<30,'qualified-data-tools-acquisition-requires-1-GiB-free')
    api=api or remote.Github(os.environ.get('GITHUB_TOKEN'));output.mkdir(mode=0o700)
    for name,row in pin['artifacts'].items():
        transfer.verify_remote(api,row);path=output/(name+'.zip')
        api.download(remote.API+'/actions/artifacts/'+str(row['id'])+'/zip',path,row)
        transfer.extract_selected(path,output,row);path.unlink()
    proof=dict(formatVersion=1,scope='exact-qualified-data-tools-provider-input-readback',inputLock=files.identity(LOCK),
        everySelectedInputHashVerified=True,serverRebuilt=False,androidRuntimeQualified=False,gameplayQualified=False)
    engine.put_metadata(output/'acquisition.json',proof);return proof


def build(inputs,output):
    pin=load_pin();inputs=archives.directory(inputs)
    for artifact in pin['artifacts'].values():
        for row in artifact['members'].values():
            require(files.identity(inputs/row['target'])==provider.identity(row),'qualified-data-tools-input-bytes-differ')
    output=Path(os.path.abspath(output));archives.directory(output.parent,create=True)
    require(not os.path.lexists(output) and output!=inputs and output not in inputs.parents and inputs not in output.parents,
            'qualified-data-tools-existing-or-overlapping-output')
    output.mkdir(mode=0o700)
    selected=provider.load_pin(sealed=True)
    q=measure.measure(inputs/'package',inputs/'native',inputs/'stock-debug/stock-extractors-debug-arm64.tar.gz',
        output/'measured',expected_package_sha256=selected['packageReceipt']['sha256'],
        expected_native_sha256=selected['nativeCliReceipt']['sha256'])
    require(files.identity(output/'measured/data-tools-provider.lock.json')==files.identity(provider.LOCK),
            'qualified-data-tools-measurement-does-not-reproduce-committed-pin')
    provider.build(inputs/'package',output/'measured/sources',output/'provider')
    return dict(formatVersion=1,scope='exact-qualified-data-tools-install-provider',providerVerified=True,
        sourceAndPairedDebugVerified=True,provider=str(output/'provider'),androidRuntimeQualified=False,
        clientMpqConversionQualified=False,gameplayQualified=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='operation',required=True)
    a=s.add_parser('acquire');a.add_argument('--output',type=Path,required=True)
    b=s.add_parser('build');b.add_argument('--inputs',type=Path,required=True);b.add_argument('--output',type=Path,required=True)
    args=p.parse_args();q=acquire(args.output) if args.operation=='acquire' else build(args.inputs,args.output)
    print(json.dumps(q,sort_keys=True,indent=2))

if __name__=='__main__':main()
