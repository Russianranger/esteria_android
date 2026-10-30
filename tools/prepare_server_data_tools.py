#!/usr/bin/env python3
"""Stage exact source-sealed data-tool packaging and native fixture inputs.

Only the ordered payload, complete sources and original small extractor package
are selected. No original installed server or gigabyte engine debug is fetched.
The native fixture source replay prepares source only; it runs no compiler.
"""
from __future__ import annotations
import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
import sys

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import package_server_engine as engine, prepare_runtime as archives
from tools import prepare_ordered_extractor_sources as ordered, prepare_server_requalification as remote
from tools import provider_server_data_tools as provider, provider_server_extractors as stock
from tools import qualify_server_providers as transfer, seal_ordered_extractor_sources as sources
from tools import prepare_server_isolated_sources as preparation, verify_server_build as files

MINIMUM_FREE_BYTES = 4 << 30
require = files.require


def source_artifact(pin):
    row = copy.deepcopy(pin.get('orderedSourceArtifact'))
    require(type(row) is dict and all(type(row.get(name)) is int and row[name]>0 for name in
                ('id','workflowRun','job')) and type(row.get('bytes')) is int and 22<=row['bytes']<=128<<20 and
            re.fullmatch('[0-9a-f]{40}',row.get('integrationRevision','')) and
            re.fullmatch('[0-9a-f]{64}',row.get('sha256','')), 'data-tools-complete-source-artifact-required')
    expected = {sources.SOURCE_ARCHIVE: pin['actualOrderedSourceQualification']['archive'],
                sources.RECEIPT: pin['actualOrderedSourceQualification']['receipt']}
    require(set(row.get('members', {})) == set(expected), 'data-tools-source-artifact-member-set')
    for name, identity in expected.items():
        require(engine.identity(row['members'][name]) == identity and
                row['members'][name].get('target') == 'ordered-sources/'+name,
                'data-tools-source-artifact-anchor-differs')
    return row


def stock_artifacts():
    pin = stock.load_pin(sealed=True); common = transfer.load_pin()['artifacts']
    runtime = copy.deepcopy(common['runtime']); debug = copy.deepcopy(common['extractorDebug'])
    wanted = {'server-extractors-package/package-receipt.json':
                  dict(pin['packageReceipt'], target='stock-package/package-receipt.json'),
              'server-extractors-package/'+pin['archive']['file']:
                  dict(engine.identity(pin['archive']), target='stock-package/'+pin['archive']['file'])}
    require(all(name in runtime['members'] and engine.identity(runtime['members'][name]) == engine.identity(row)
                for name, row in wanted.items()), 'data-tools-original-stock-artifact-differs')
    runtime['members'] = wanted
    require(len(debug['members']) == 1, 'data-tools-original-stock-debug-member-set')
    for row in debug['members'].values():
        require(engine.identity(row) == engine.identity(pin['debugArchive']), 'data-tools-original-stock-debug-differs')
        row['target'] = 'stock-debug/stock-extractors-debug-arm64.tar.gz'
    return {'stockRuntime': runtime, 'stockDebug': debug}


def acquire(output, api=None):
    selected = provider.load_source_qualification()
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'existing-data-tools-inputs-preserved')
    require(shutil.disk_usage(output.parent).free >= MINIMUM_FREE_BYTES, 'data-tools-inputs-require-4-GiB-free')
    rows = {'orderedSources': source_artifact(selected), **stock_artifacts()}
    api = api or remote.Github(os.environ.get('GITHUB_TOKEN'))
    # Reuse the authenticated complete native payload transfer, including its
    # original source companion for the later small native fixture preparation.
    original = ordered.acquire(output, api)
    engine.copy_verified(output/'payload/ordered-build.json',output/'native-ordered-build.json',
                         sources.load_pin()['nativeBuild']['receipt'],0o444)
    for name, row in rows.items():
        transfer.verify_remote(api, row)
        path = output/(name+'.zip')
        api.download(remote.API+'/actions/artifacts/'+str(row['id'])+'/zip', path, row)
        transfer.extract_selected(path, output, row); path.unlink()
    receipt = dict(formatVersion=1, scope='exact-source-sealed-server-data-tools-packaging-inputs',
        providerInputLock=files.identity(provider.LOCK), nativeInputLock=files.identity(sources.LOCK),
        orderedAcquisition=files.identity(output/'acquisition.json'), artifacts=rows,
        completeNativePayloadReadback=original['completeNativePayloadReadback'],
        sourceQualification=selected['actualOrderedSourceQualification'], selectedInputHashesVerified=True,
        minimumFreeBytes=MINIMUM_FREE_BYTES, serverInstallArchiveFetched=False, engineDebugArchiveFetched=False,
        nativeProgramsExecuted=False, nativeCompilationPerformed=False,
        androidRuntimeQualified=False, gameplayQualified=False)
    engine.put_metadata(output/'data-tools-acquisition.json', receipt)
    return receipt


def fixture_source(acquired, output):
    provider.load_source_qualification(); measured = sources.load_pin()
    acquired = archives.directory(Path(os.path.abspath(acquired))); output = Path(os.path.abspath(output))
    require(not os.path.lexists(output) and acquired != output and acquired not in output.parents and
            output not in acquired.parents, 'data-tools-fixture-output-exists-or-overlaps')
    archives.directory(output.parent, create=True); output.mkdir(mode=0o700)
    original = output/'original'
    sources.verify_original(acquired/'original-sealed', measured, original)
    # The native job needs the original source and raw measured receipt, not
    # another transfer of the 105 MB producer payload or its original ELFs.
    q, qid = sources.read_json(acquired/'native-ordered-build.json')
    lock = original/'recipes/sources.lock.json'
    require(qid == measured['nativeBuild']['receipt'] and q.get('phase')=='complete' and
            q.get('scope')=='native-arm64-separate-ordered-extractor-target-build-and-synthetic-lookups' and
            files.identity(lock)==q['serverBuildSourceLock']==measured['serverBuildSourceLock'],
            'data-tools-fixture-original-source-or-native-receipt-differs')
    base = output/'base'
    preparation.prepare(original/'inputs/source-inputs', base, original/'inputs/supplements', original_lock=lock)
    require(files.identity(base/'preparation-receipt.json') == q['originalPreparationReceipt'],
            'data-tools-fixture-original-seven-patch-source-differs')
    receipt = dict(formatVersion=1, scope='original-seven-patch-source-prepared-for-synthetic-data-tool-fixtures',
        nativeReceipt=qid, sourceLock=files.identity(lock), preparationReceipt=files.identity(base/'preparation-receipt.json'),
        fixtureSource=str(base/'source'), sourceRepositoryFetched=False, clientAssetsFetched=False,
        nativeCompilationPerformed=False, nativeProgramsExecuted=False, androidRuntimeQualified=False, gameplayQualified=False)
    engine.put_metadata(output/'fixture-source.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='operation', required=True)
    get = sub.add_parser('acquire'); get.add_argument('--output', type=Path, required=True)
    fixture = sub.add_parser('fixture-source')
    fixture.add_argument('--inputs', type=Path, required=True); fixture.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(acquire(args.output) if args.operation == 'acquire' else fixture_source(args.inputs, args.output), indent=2))


if __name__ == '__main__': main()
