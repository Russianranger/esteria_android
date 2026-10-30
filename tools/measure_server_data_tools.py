#!/usr/bin/env python3
"""Measure a positive data-tool admission pin from retained actual native outputs.

This performs full source/runtime/debug readback and binds the separately retained
native CLI/lookup receipt. It never edits the committed pin or runs ARM64 programs
on the measurement host. Review and publish the emitted pin before building the
optional Android provider with provider_server_data_tools.py.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

if not __package__: sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import provider_server_data_tools as provider, qualify_server_data_tools as qualify
from tools import package_server_data_tools as package

require=provider.require
identity=provider.identity
files=provider.files
engine=provider.engine
archives=provider.archives


def measure(package_directory,native_directory,stock_debug,output,*,expected_package_sha256,expected_native_sha256):
    directory=archives.directory(Path(os.path.abspath(package_directory)))
    native=archives.directory(Path(os.path.abspath(native_directory)))
    stock_debug=Path(os.path.abspath(stock_debug))
    verified=qualify.validate_package(directory,expected_package_sha256)
    receipt=verified['receipt']; original=package.stock.load_pin(sealed=True)
    cli,cid=qualify.expected_receipt(native/'native-cli.json',expected_native_sha256)
    qualify.verify_phase(native/'native-cli-phase.json',cli['cliPhase']['sha256'],verified)
    result,result_id=package.sources.read_json(native/'lookup-result.json')
    qualify.verify_suite_result(result)
    require(result_id==cli['lookupResult'] and result['testNames']==cli['lookupTestNames'] and
            result['testsRun']==cli['lookupTestsRun'] and result['skipped']==cli['lookupTestsSkipped'],
            'data-tools-measured-native-result-binding-differs')
    pin=dict(verified['selected'])
    pin.update(state='sealed-source-and-native-cli',sourceCompanionComplete=True,
        nativeArgumentConfigQualified=True,originalNoticesPreserved=True,
        archive=receipt['archive'],archiveEntries=receipt['archiveEntries'],archiveFileBytes=receipt['archiveFileBytes'],
        files=receipt['archiveFiles'],packageReceipt=verified['receiptIdentity'],programPairs=receipt['programPairs'],
        nativeCliReceipt=cid,orderedStripReceipt=receipt['orderedStripReceipt'],toolSelection=receipt['toolSelection'],
        debugArchives=dict(ordered=receipt['orderedDebugArchive'],stock=original['debugArchive']))
    provider.validate_native_cli(cli,pin)
    output=Path(os.path.abspath(output)); archives.directory(output.parent,create=True)
    require(not os.path.lexists(output) and all(output!=p and output not in p.parents and p not in output.parents
        for p in (directory,native,stock_debug.parent)), 'data-tools-measurement-output-exists-or-overlaps')
    stage=Path(tempfile.mkdtemp(prefix='.'+output.name+'.stage-',dir=output.parent))
    try:
        selected=stage/'sources';selected.mkdir()
        names=('package-receipt.json',package.SOURCE_RECEIPT,package.SOURCE_ARCHIVE,'native-ordered-build.json',
            'dependency-observation.json','ordered-strip-receipt.json',package.DEBUG,'stock-package-receipt.json')
        for name in names:
            engine.copy_verified(directory/name,selected/name,files.identity(directory/name),0o444)
        engine.copy_verified(native/'native-cli.json',selected/'native-cli.json',cid,0o444)
        engine.copy_verified(stock_debug,selected/'stock-extractors-debug-arm64.tar.gz',identity(original['debugArchive']),0o444)
        lock=stage/'data-tools-provider.lock.json'; engine.put_metadata(lock,pin)
        provider.load_pin(sealed=True,path=lock)
        provider.verify_sources(selected,pin);provider.verify_runtime(directory/package.RUNTIME,pin)
        require(files.identity(native/'native-cli.json')==cid and
                files.identity(directory/'package-receipt.json')==verified['receiptIdentity'],
                'data-tools-measurement-input-changed')
        proof=dict(formatVersion=1,scope='measured-complete-server-data-tools-provider-admission',
            inputLock=files.identity(provider.LOCK),candidatePin=files.identity(lock),archive=pin['archive'],
            archiveEntries=pin['archiveEntries'],archiveFileBytes=pin['archiveFileBytes'],nativeCliReceipt=cid,
            nativeCliCases=len(cli['cliCases']),nativeCapabilities=len(cli['capabilities']),
            nativeLookupTestsRun=cli['lookupTestsRun'],nativeLookupTestsSkipped=cli['lookupTestsSkipped'],
            sourceCompanionVerified=True,pairedDebugVerified=True,originalNoticesPreserved=True,
            originalStockProgramsAndConfigUnchanged=True,retainedNativeOutputsVerified=True,
            nativeProgramsExecutedHere=False,committedPinChangedHere=False,androidProviderCreated=False,
            **{name:False for name in provider.FALSE_FLAGS})
        engine.put_metadata(stage/'measurement.json',proof)
        archives.sync_directory(stage);provider.transaction.publish_directory(stage,output);archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists():shutil.rmtree(stage)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('package','native','stock-debug','output'):parser.add_argument('--'+name,type=Path,required=True)
    for name in ('expected-package-sha256','expected-native-sha256'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    proof=measure(args.package,args.native,args.stock_debug,args.output,
        expected_package_sha256=args.expected_package_sha256,expected_native_sha256=args.expected_native_sha256)
    print(json.dumps(proof,sort_keys=True,indent=2))

if __name__=='__main__':main()
