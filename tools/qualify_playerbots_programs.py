#!/usr/bin/env python3
"""Qualify the separate schema-helper programs profile without executing it.

The original stock factory remains responsible for complete original sources
and paired debug. This only acquires the registered original helper and its
separately sealed sources, measures the closed delta and invokes that guarded
optional factory. It never runs a compiler, SQL, helper or Android guest.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import provider_playerbots_programs as provider, qualify_server_providers as stock
from tools import prepare_server_installation_inputs as candidate, prepare_server_requalification as transfer
from tools import verify_server_build as files, prepare_runtime as archives
from tools.release_server_dependencies import Github, API

require = files.require


def source_artifact(anchor):
    row = dict(anchor['artifact'], workflowRun=anchor['producer']['workflowRun'],
        integrationRevision=anchor['producer']['integrationRevision'])
    require(type(row.get('id')) is int and row['id'] > 0 and
            22 <= provider.stock.identity(row)['bytes'] <= 256 << 20,
            'optional-programs-helper-source-artifact-required')
    return row


def extract_sources(archive_path, output, anchor):
    require(files.identity(archive_path) == provider.stock.identity(source_artifact(anchor)),
            'optional-programs-helper-source-outer-identity-differs')
    require(not os.path.lexists(output), 'existing-optional-programs-helper-sources-preserved')
    expected = {provider.measure.source.SOURCE_ARCHIVE: anchor['archive'],
        provider.measure.source.RECEIPT: anchor['receipt']}
    with transfer.bounded_zip(archive_path) as (archive, members):
        require(set(members) == set(expected) and all(members[name].file_size == row['bytes']
            for name, row in expected.items()), 'optional-programs-helper-source-outer-member-set-or-size')
        output.mkdir(mode=0o700)
        for name, row in expected.items():
            with archive.open(members[name]) as incoming, (output / name).open('xb') as outgoing:
                require(archives.hash_stream(incoming, row['bytes'], outgoing) == row['sha256'],
                        'optional-programs-helper-source-member-hash-differs')
                outgoing.flush(); os.fsync(outgoing.fileno())
            (output / name).chmod(0o444)


def acquire(output, api=None):
    pin, pid, anchor, base = provider.load_pin()
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'existing-optional-programs-inputs-preserved')
    require(shutil.disk_usage(output.parent).free >= 1 << 30, 'optional-programs-inputs-require-one-GiB-free')
    registration, _, _ = candidate.load_pin()
    api = Github(os.environ.get('GITHUB_TOKEN')) if api is None else api
    candidate.verify_remote(api, registration)
    source_row = source_artifact(anchor); stock.verify_remote(api, source_row)
    output.mkdir(mode=0o700)
    candidate_zip = output / 'registered-candidate.zip'
    api.download(API + '/actions/artifacts/' + str(registration['artifact']['id']) + '/zip',
        candidate_zip, provider.stock.identity(registration['artifact']))
    candidate.extract_registration(candidate_zip, output / 'registration', registration)
    selected = candidate.extract_candidate(output / 'registration', output / 'candidate', registration)
    candidate_zip.unlink()
    source_zip = output / 'helper-sources.zip'
    api.download(API + '/actions/artifacts/' + str(source_row['id']) + '/zip', source_zip,
        provider.stock.identity(source_row))
    extract_sources(source_zip, output / 'helper-sources', anchor); source_zip.unlink()
    provider.measure.verify_helper_sources(output / 'helper-sources', anchor, selected, base)
    require(provider.load_pin()[1] == pid, 'optional-programs-input-pin-changed-during-acquisition')
    proof = dict(formatVersion=1, scope='exact-optional-playerbots-programs-helper-inputs',
        inputLock=pid, sourceAnchor=pin['helperSourceAnchor'], helperArtifact=registration['artifact'],
        helperSourceArtifact=source_row, allSelectedBytesAndModesVerified=True,
        completeHelperSourceReadback=True, originalHelperBuildAndNativeSqlReceiptsUnchanged=True,
        originalStockSourcesAndDebugVerifiedHere=False, compilerExecuted=False, helperExecuted=False,
        sqlExecuted=False, androidProviderCreated=False, productionActivated=False,
        androidRuntimeQualified=False, worldserverQualified=False, playerbotsAiQualified=False, gameplayQualified=False)
    provider.engine.put_metadata(output / 'acquisition.json', proof)
    return proof


def build(stock_providers, inputs, output):
    pin, pid, _, _ = provider.load_pin()
    stock_providers, inputs = archives.directory(stock_providers), archives.directory(inputs)
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and all(output != p and output not in p.parents and p not in output.parents
        for p in (stock_providers, inputs)), 'existing-or-overlapping-optional-programs-output-preserved')
    acquisition, _ = provider.modules.read_json(inputs / 'acquisition.json', limit=128 << 10)
    require(acquisition.get('scope') == 'exact-optional-playerbots-programs-helper-inputs' and
        acquisition.get('inputLock') == pid and acquisition.get('allSelectedBytesAndModesVerified') is True,
        'optional-programs-acquisition-selection-differs')
    # This runs the original full source/debug checker before any candidate or
    # new provider. The optional factory repeats it before and after copying.
    original = provider.stock.verify(stock_providers / 'programs')
    output.mkdir(mode=0o700)
    provider.measure.measure(stock_providers / 'notice-package', inputs / 'candidate',
        inputs / 'helper-sources', output / 'runtime-candidate')
    provider.verify_candidate(output / 'runtime-candidate', pin)
    provider.build(stock_providers / 'programs', inputs / 'candidate', inputs / 'helper-sources',
        output / 'runtime-candidate', output / 'programs')
    proof = dict(formatVersion=1, scope='source-and-paired-debug-verified-optional-playerbots-programs-provider',
        inputLock=pid, originalStockProviderVerification=original,
        provider=provider.verify(output / 'programs'), compilerExecuted=False, helperExecuted=False,
        sqlExecuted=False, androidRuntimeQualified=False, worldserverQualified=False,
        playerbotsAiQualified=False, gameplayQualified=False)
    provider.engine.put_metadata(output / 'provider-build.json', proof)
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='operation', required=True)
    get = sub.add_parser('acquire'); get.add_argument('--output', type=Path, required=True)
    make = sub.add_parser('build')
    for name in ('stock-providers', 'inputs', 'output'): make.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = acquire(args.output) if args.operation == 'acquire' else build(args.stock_providers, args.inputs, args.output)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__': main()
