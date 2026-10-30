#!/usr/bin/env python3
"""Acquire only the exact ordered payload and original sealed source inputs.

This performs no native execution or compilation. Pending native pins are
refused before creating output or starting a download. Original server install
and paired debug artifacts are not inputs to source composition.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import package_server_engine as engine, prepare_runtime as archives
from tools import prepare_server_requalification as remote, qualify_server_providers as transfer
from tools import seal_ordered_extractor_sources as seal, verify_server_build as files

MINIMUM_FREE_BYTES = 3 << 30
require = files.require


def verify_native_remote(api, native):
    run = api.json('/actions/runs/' + str(native['workflowRun']))
    job = api.json('/actions/jobs/' + str(native['job']))
    require(run.get('id') == native['workflowRun'] and run.get('head_sha') == native['integrationRevision'] and
            run.get('status') == 'completed' and run.get('conclusion') == 'success' and
            job.get('id') == native['job'] and job.get('run_id') == native['workflowRun'] and
            job.get('status') == 'completed' and job.get('conclusion') == 'success',
            'ordered-source-native-run-or-job-not-successful')


def artifact(native, name):
    return dict(native[name], workflowRun=native['workflowRun'], integrationRevision=native['integrationRevision'])


def extract_payload(path, output, pin):
    native = pin['nativeBuild']; row = artifact(native, 'payloadArtifact')
    require(files.identity(path) == engine.identity(row), 'ordered-source-native-zip-identity')
    with remote.bounded_zip(path) as (archive, members):
        require('ordered-build.json' in members, 'ordered-source-native-receipt-missing')
        raw = remote.small_member(archive, members, 'ordered-build.json', maximum=16 << 20)
        require(dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) == seal.identity(native['receipt']),
                'ordered-source-native-receipt-identity')
        qualified = json.loads(raw)
        require(qualified.get('phase') == 'complete' and qualified.get('integrationRevision') == native['integrationRevision'] and
                qualified.get('scope') == 'native-arm64-separate-ordered-extractor-target-build-and-synthetic-lookups' and
                qualified.get('actualTargetCompileSucceeded') is True and qualified.get('sourceCompanionComplete') is False,
                'ordered-source-native-receipt-scope')
        inventory = qualified.get('payloadFiles')
        require(type(inventory) is dict and 0 < len(inventory) <= seal.MAX_FILES and
                set(members) == set(inventory) | {'ordered-build.json'}, 'ordered-source-native-zip-complete-file-set')
        for name, item in inventory.items():
            engine.content.safe_path(name); seal.identity(item)
        require(sum(item['bytes'] for item in inventory.values()) <= 256 << 20,
                'ordered-source-native-payload-byte-bound')
    selected = dict(row, members={name: dict(item, target='payload/' + name) for name, item in inventory.items()})
    selected['members']['ordered-build.json'] = dict(seal.identity(native['receipt']), target='payload/ordered-build.json')
    transfer.extract_selected(path, output, selected)
    for name in seal.TARGETS:
        target = output / 'payload/bin' / name
        require(files.identity(target) == seal.identity(native['programs'][name]), 'ordered-source-native-program-identity')
        target.chmod(0o555)
    require(files.identity(output / 'payload/build/dependency-observation/observation.json') ==
            seal.identity(native['dependencyObservation']), 'ordered-source-native-observation-identity')
    return qualified


def acquire(output, api=None):
    pin = seal.load_pin()
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'existing-ordered-source-inputs-preserved')
    require(shutil.disk_usage(output.parent).free >= MINIMUM_FREE_BYTES, 'ordered-source-inputs-require-3-GiB-free')
    original = copy.deepcopy(transfer.load_pin()['artifacts']['completeSources'])
    require(all(original[key] == pin['originalSourceArtifact'][key] for key in
                ('id', 'bytes', 'sha256', 'workflowRun', 'integrationRevision')), 'ordered-source-original-artifact-differs')
    expected = {'server-engine-complete-sources.tar.gz': pin['originalSourceQualification']['archive'],
                'qualification.json': pin['originalSourceQualification']['qualification'],
                'sealed-source-receipt.json': pin['originalSourceQualification']['receipt']}
    require(all(name in original['members'] and engine.identity(original['members'][name]) == seal.identity(item)
                for name, item in expected.items()), 'ordered-source-original-selected-members-differ')
    for item in original['members'].values():
        item['target'] = 'original-sealed/' + Path(item['target']).name
    api = api or remote.Github(os.environ.get('GITHUB_TOKEN'))
    verify_native_remote(api, pin['nativeBuild'])
    output.mkdir(mode=0o700)
    for name, row in (('original', original), ('native', artifact(pin['nativeBuild'], 'payloadArtifact'))):
        transfer.verify_remote(api, row)
        downloaded = output / (name + '.zip')
        api.download(remote.API + '/actions/artifacts/' + str(row['id']) + '/zip', downloaded, row)
        require(files.identity(downloaded) == engine.identity(row), 'ordered-source-downloaded-artifact-differs')
        if name == 'original':
            transfer.extract_selected(downloaded, output, row)
        else:
            extract_payload(downloaded, output, pin)
        downloaded.unlink()
    evidence = artifact(pin['nativeBuild'], 'evidenceArtifact')
    transfer.verify_remote(api, evidence)
    readme = pin['clientPolicyReadme']
    source = archives.fetch(readme, output / 'readme-cache')
    destination = output / 'client-reference/README.md'
    engine.copy_verified(source, destination, seal.identity(readme), 0o444)
    seal.verify_readme(destination, pin)
    receipt = dict(formatVersion=1, scope='exact-ordered-extractor-source-inputs-readback',
        inputLock=files.identity(seal.LOCK), originalSourceArtifact=pin['originalSourceArtifact'],
        nativePayloadArtifact=artifact(pin['nativeBuild'], 'payloadArtifact'),
        nativeEvidenceArtifact=evidence, nativeReceipt=pin['nativeBuild']['receipt'],
        dependencyObservation=pin['nativeBuild']['dependencyObservation'], clientPolicyReadme=seal.identity(readme),
        selectedArtifactBytesVerified=True, completeNativePayloadReadback=True, nativeEvidenceDownloaded=False,
        minimumFreeBytes=MINIMUM_FREE_BYTES, serverInstallArchiveFetched=False, pairedDebugArchiveFetched=False,
        nativeProgramsExecuted=False, nativeCompilationPerformed=False, sourceCompanionComplete=False,
        androidRuntimeQualified=False, gameplayQualified=False)
    engine.put_metadata(output / 'acquisition.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(acquire(args.output), indent=2))


if __name__ == '__main__':
    main()
