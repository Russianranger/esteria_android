#!/usr/bin/env python3
"""Acquire the exact already-qualified seven-patch runtime for a new PB gate.

This bounded transfer reuses measured derivatives/content without downloading
the original gigabyte install or rebuilding any of the three server programs.
No guest program, SQL, Docker or source repository is executed here.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import prepare_server_requalification as transfer
from tools import prepare_server_isolated_build as inputs
from tools import verify_server_build as files, verify_server_engine_runtime as engine
from tools.release_server_dependencies import Github, API, encoded

require = files.require
RUN = 41058676543
REVISION = 'b258529f695be0de810040eacb0ee07e483b11d4'
ARTIFACT = dict(id=12976974609, bytes=192900091,
    sha256='67cc07940819d89524760c965a6144ec91ac4d73dc90c98a930b087538be50d4')
ENGINE_RECEIPT = dict(bytes=34652, sha256='bb62ad200ac9be9b756616e351bf591508eedb7420f9fd39d5ea0544ae1cc548')
CONTENT_RECEIPT = dict(bytes=1343739, sha256='1c00990e090e85af0232fe633b64e2718071a5f8e81f3b0ca1c8f2b214ffb3af')
PREFIXES = ('server-engine-package/', 'engine-inputs/content/', 'engine-inputs/locked/')


def verify_remote(api):
    run = api.json('/actions/runs/' + str(RUN))
    require(run.get('id') == RUN and run.get('head_sha') == REVISION and
            run.get('status') == 'completed' and run.get('conclusion') == 'success',
            'playerbots-runtime-producer-identity-differs')
    row = api.json('/actions/artifacts/' + str(ARTIFACT['id']))
    require(row.get('id') == ARTIFACT['id'] and row.get('expired') is False and
            row.get('size_in_bytes') == ARTIFACT['bytes'] and row.get('digest') == 'sha256:' + ARTIFACT['sha256'] and
            row.get('workflow_run', {}).get('id') == RUN and
            row.get('workflow_run', {}).get('head_sha') == REVISION,
            'playerbots-runtime-artifact-identity-differs')


def extract_selected(archive_path, output):
    """Full outer hash precedes a link-free, bounded, explicit-prefix extraction."""
    require(files.identity(archive_path) == {key: ARTIFACT[key] for key in ('bytes', 'sha256')},
            'playerbots-runtime-transfer-changed')
    require(not os.path.lexists(output), 'existing-playerbots-transfer-preserved')
    with transfer.bounded_zip(archive_path) as (archive, members):
        selected = {name: row for name, row in members.items() if name.startswith(PREFIXES)}
        require(selected and sum(row.file_size for row in selected.values()) <= 512 * 1024**2,
                'playerbots-runtime-transfer-selection-bound')
        output.mkdir(mode=0o700)
        for name, item in selected.items():
            transfer.content.safe_path(name)
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with archive.open(item) as incoming, target.open('xb') as outgoing:
                transfer.zip_tools.archives.hash_stream(incoming, item.file_size, outgoing)
                outgoing.flush(); os.fsync(outgoing.fileno())
            target.chmod(0o444)
    require(files.identity(output / 'server-engine-package/package-receipt.json') == ENGINE_RECEIPT and
            files.identity(output / 'engine-inputs/content/package-receipt.json') == CONTENT_RECEIPT,
            'playerbots-runtime-original-receipt-differs')
    inputs.load_pin(output / 'engine-inputs/locked/sources.lock.json')
    return len(selected)


def prepare(output, api=None):
    output = Path(os.path.abspath(output))
    transfer.zip_tools.archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'existing-playerbots-runtime-inputs-preserved')
    require(shutil.disk_usage(output.parent).free >= 2 * 1024**3, 'playerbots-runtime-requires-2-GiB-free')
    api = api or Github(os.environ.get('GITHUB_TOKEN'))
    verify_remote(api)
    output.mkdir(mode=0o700)
    archive = output / 'runtime-transfer.zip'
    api.download(API + '/actions/artifacts/' + str(ARTIFACT['id']) + '/zip', archive, ARTIFACT)
    count = extract_selected(archive, output / 'transfer')
    extracted = engine.extract(output / 'transfer/server-engine-package/package-receipt.json', output / 'install')
    proof = dict(formatVersion=1, scope='exact-seven-patch-runtime-for-playerbots-component',
        originalProducer=dict(workflowRun=RUN, integrationRevision=REVISION, artifact=ARTIFACT),
        selectedTransferFiles=count, engineReceipt=ENGINE_RECEIPT, contentReceipt=CONTENT_RECEIPT,
        engineExtraction=extracted, originalServerProgramsRebuilt=False, originalReceiptsPreserved=True,
        sqlExecuted=False, helperExecuted=False, androidRuntimeQualified=False, gameplayQualified=False)
    transfer.write_new(output / 'preparation.json', encoded(proof))
    archive.unlink()  # Only this invocation's completely verified transfer.
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(encoded(prepare(args.output)).decode(), end='')


if __name__ == '__main__': main()
