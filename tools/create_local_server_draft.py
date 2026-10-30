#!/usr/bin/env python3
"""Create only the explicitly measured local-server draft release metadata.

This separate operation creates no asset, publishes nothing and never adopts,
edits or deletes an existing release/tag. The frozen uploader remains unchanged.
An interrupted creation must be inspected, not retried by matching tag/body.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import quote
import zipfile

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import release_server_dependencies as transport
from tools import package_server_engine as engine

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / 'runtime/server-components-publication/draft-creation.lock.json'
REPOSITORY = 'Russianranger/esteria_android'
TAG = 'deps-local-server-f35f04d-21ce4e1b-b7d9b72c'
WORKFLOW = '.github/workflows/create-local-server-draft.yml'
NAME = 'Esteria local server providers ' + TAG
FALSE_FLAGS = ('compilerExecuted', 'helperExecuted', 'sqlExecuted', 'androidGuestExecuted',
    'androidRuntimeQualified', 'worldserverQualified', 'playerbotsAiQualified', 'gameplayQualified')
MEASUREMENT_FILES = {'measured-release.lock.json', 'measurement.json', 'release-body.txt', 'failure-context.json'}
require = transport.require


def digest(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def load_pin():
    pin = transport.small_json(PIN)
    require(set(pin) == {'formatVersion', 'scope', 'state', 'repository', 'tag', 'targetCommit',
        'workflowRun', 'measurementArtifact', 'candidateArtifact', 'measurementFiles', 'assets'} and
        type(pin['formatVersion']) is int and pin['formatVersion'] == 1 and
        pin['scope'] == 'explicit-local-server-draft-metadata-creation' and pin['state'] == 'creation-authorized' and
        pin['repository'] == REPOSITORY and pin['tag'] == TAG and
        re.fullmatch('[a-f0-9]{40}', pin['targetCommit']) and
        type(pin['workflowRun']) is int and pin['workflowRun'] > 0,
        'draft-creation-explicit-selection-required')
    require(set(pin['measurementFiles']) == MEASUREMENT_FILES and len(pin['assets']) == 12,
        'draft-creation-fixed-metadata-and-twelve-assets-required')
    for rows, limit in ((pin['measurementFiles'], 1 << 20), (pin['assets'], (2 << 30) - 1)):
        for name, row in rows.items():
            require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,127}', name) and
                set(row) == {'bytes', 'sha256'} and type(row['bytes']) is int and 0 < row['bytes'] <= limit and
                re.fullmatch('[a-f0-9]{64}', row['sha256']), 'draft-creation-file-identity-required')
    for field, name in (('measurementArtifact', 'local-server-provider-release-measurement'),
            ('candidateArtifact', 'validated-local-server-provider-release-candidate')):
        row = pin[field]
        require(set(row) == {'id', 'name', 'bytes', 'sha256'} and type(row['id']) is int and row['id'] > 0 and
            row['name'] == name and type(row['bytes']) is int and 0 < row['bytes'] < 2 << 30 and
            re.fullmatch('[a-f0-9]{64}', row['sha256']), 'draft-creation-artifact-identity-required')
    require(pin['measurementArtifact']['bytes'] <= 1 << 20 and
        pin['measurementArtifact']['id'] != pin['candidateArtifact']['id'], 'draft-creation-metadata-bound')
    return pin


def frozen_selection(recipe, measured_lock, pin):
    """Let the exact archived recipe validate its own locks and canonical Git blobs."""
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=recipe, timeout=30).decode().strip()
    require(revision == pin['targetCommit'], 'draft-creation-exact-frozen-checkout-required')
    script = ("import os,sys,json;sys.path.insert(0,os.getcwd());"
        "from tools import release_local_server_components as r;"
        "lock=r.load_lock(sys.argv[1]);"
        "assert lock['state']=='measured-unbound' and lock['ownedDraftReleaseId'] is None;"
        "print(json.dumps(dict(lock=lock,body=r.body(lock),assets=sorted(r.ALL_FILES))))")
    raw = subprocess.check_output([sys.executable, '-I', '-c', script, str(measured_lock)],
        cwd=recipe, timeout=120)
    require(len(raw) <= 1 << 20, 'draft-creation-frozen-result-bound')
    return json.loads(raw)


def validate_measurement(recipe, directory, pin):
    directory = Path(directory).absolute()
    require({p.name for p in directory.iterdir()} == MEASUREMENT_FILES, 'draft-creation-measurement-file-set')
    raw = {}
    for name, expected in pin['measurementFiles'].items():
        with transport.archives.plain_file(directory / name) as source: value = source.read(expected['bytes'] + 1)
        require(digest(value) == expected, 'draft-creation-measurement-file-differs')
        raw[name] = value
    selection = frozen_selection(recipe, directory / 'measured-release.lock.json', pin)
    lock, body = selection['lock'], selection['body']
    measurement = json.loads(raw['measurement.json'])
    require(lock['targetCommit'] == pin['targetCommit'] and lock['repository'] == REPOSITORY and lock['tag'] == TAG and
        lock['state'] == 'measured-unbound' and lock['ownedDraftReleaseId'] is None and
        set(pin['assets']) == set(selection['assets']) and
        all(pin['assets'].get(name) == row for name, row in lock['files'].items()) and
        measurement.get('formatVersion') == 1 and
        measurement.get('scope') == 'complete-local-server-publication-candidate-readback' and
        measurement.get('targetCommit') == pin['targetCommit'] and measurement.get('assets') == pin['assets'] and
        measurement.get('measuredLock') == pin['measurementFiles']['measured-release.lock.json'] and
        all(measurement.get(name) is True for name in ('allCandidateAssetBytesReadBack',
            'allOriginalSourceAndPairedDebugVerified', 'originalNestedArchiveBytesPreserved')) and
        all(measurement.get(name) is False for name in (*FALSE_FLAGS, 'releaseUploaded', 'releasePublished')) and
        body.encode() == raw['release-body.txt'], 'draft-creation-measured-candidate-or-body-differs')
    # Authenticate the two non-payload identities without a recursive manifest hash.
    manifest = engine.canonical(dict(formatVersion=1, scope=lock['scope'], targetCommit=lock['targetCommit'],
        tag=TAG, selectedInputs=lock['selectedInputs'], assets=lock['files']))
    expected = dict(lock['files'], **{'release-manifest.json': digest(manifest)})
    sums = ''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(expected.items())).encode()
    require(pin['assets'] == dict(expected, SHA256SUMS=digest(sums)), 'draft-creation-manifest-or-sums-differs')
    return body


def acquire_measurement(api, directory, pin):
    run = api.json('/actions/runs/' + str(pin['workflowRun']))
    require(run.get('id') == pin['workflowRun'] and run.get('head_sha') == pin['targetCommit'] and
        run.get('status') == 'completed' and run.get('conclusion') == 'success' and
        run.get('repository', {}).get('full_name') == REPOSITORY and
        run.get('path') == '.github/workflows/preserve-local-server-components.yml',
        'draft-creation-successful-exact-producer-required')
    for key in ('measurementArtifact', 'candidateArtifact'):
        expected = pin[key]; actual = api.json('/actions/artifacts/' + str(expected['id']))
        require(actual.get('id') == expected['id'] and actual.get('name') == expected['name'] and
            actual.get('expired') is False and actual.get('size_in_bytes') == expected['bytes'] and
            actual.get('digest') == 'sha256:' + expected['sha256'] and
            actual.get('workflow_run', {}).get('id') == pin['workflowRun'] and
            actual.get('workflow_run', {}).get('head_sha') == pin['targetCommit'],
            'draft-creation-exact-retained-artifacts-required')
    archive = directory / 'measurement.zip'; expected = pin['measurementArtifact']
    api.download(transport.API + '/actions/artifacts/' + str(expected['id']) + '/zip', archive, expected)
    output = directory / 'measurement'; output.mkdir(mode=0o700)
    with zipfile.ZipFile(archive) as zipped:
        rows = transport.zip_members(zipped)
        require(set(rows) == MEASUREMENT_FILES, 'draft-creation-measurement-zip-file-set')
        for name, row in rows.items():
            value = transport.zip_read(zipped, row, 1 << 20)
            require(digest(value) == pin['measurementFiles'][name], 'draft-creation-measurement-zip-bytes-differ')
            (output / name).write_bytes(value)
    return output


def check_created(release, pin, body, release_id=None):
    require(type(release.get('id')) is int and release['id'] > 0 and
        (release_id is None or release['id'] == release_id) and release.get('tag_name') == TAG and
        release.get('target_commitish') == pin['targetCommit'] and release.get('draft') is True and
        release.get('prerelease') is True and release.get('name') == NAME and release.get('body') == body and
        release.get('author', {}).get('login') == 'github-actions[bot]',
        'draft-creation-stored-metadata-differs; existing-release-preserved')


def check_tag(api, pin, *, absent=False):
    ref = api.json('/git/ref/tags/' + quote(TAG, safe=''), missing=True)
    require(ref is None if absent else ref is None or
        (ref.get('object', {}).get('type') == 'commit' and
            ref.get('object', {}).get('sha') == pin['targetCommit']),
        'draft-creation-existing-tag-refused; tag-preserved')


def create(api, pin, body, context):
    require(digest(body.encode()) == pin['measurementFiles']['release-body.txt'],
        'draft-creation-exact-measured-body-required')
    require(context.get('repository') == REPOSITORY and context.get('ref') == 'refs/heads/android/client-server' and
        context.get('event') in ('push', 'workflow_dispatch') and
        type(context.get('run')) is int and context['run'] > 0 and
        re.fullmatch('[a-f0-9]{40}', context.get('revision', '')),
        'draft-creation-authorized-workflow-context-required')
    check_tag(api, pin, absent=True)
    for page in range(1, 11):
        rows = api.json('/releases?per_page=100&page=' + str(page))
        require(type(rows) is list and all(row.get('tag_name') != TAG for row in rows),
            'draft-creation-existing-release-refused; no-adoption-or-mutation')
        if len(rows) < 100: break
    else: raise ValueError('draft-creation-release-list-bound; no-mutation')
    created = api.json('/releases', method='POST', value=dict(tag_name=TAG, target_commitish=pin['targetCommit'],
        name=NAME, body=body, draft=True, prerelease=True, make_latest='false'))
    require(type(created.get('id')) is int and created['id'] > 0, 'draft-creation-response-id-required')
    release_id = created['id']
    current = api.json('/releases/' + str(release_id)); check_created(current, pin, body, release_id)
    check_tag(api, pin)
    require(api.json('/releases/' + str(release_id) + '/assets?per_page=100') == [],
        'draft-creation-must-have-no-assets')
    return dict(formatVersion=1, scope='actions-created-local-server-draft-metadata-readback', repository=REPOSITORY,
        tag=TAG, targetCommit=pin['targetCommit'], releaseId=release_id, draft=True, prerelease=True,
        metadataCreatedBy='github-actions-token', creatorWorkflow=WORKFLOW, creatorRun=context['run'],
        creatorRevision=context['revision'], measuredProducerRun=pin['workflowRun'],
        selection=digest(engine.canonical(pin)), body=digest(body.encode()),
        measuredLock=pin['measurementFiles']['measured-release.lock.json'], assets=pin['assets'],
        draftUiInspected=False, releaseUploaded=False, releasePublished=False,
        candidateAssetBytesReverifiedHere=False, **{name: False for name in FALSE_FLAGS})


def verify_created(api, pin, body, receipt):
    expected = {'formatVersion', 'scope', 'repository', 'tag', 'targetCommit', 'releaseId',
        'draft', 'prerelease', 'metadataCreatedBy', 'creatorWorkflow', 'creatorRun', 'creatorRevision',
        'measuredProducerRun', 'selection', 'body', 'measuredLock', 'assets', 'draftUiInspected',
        'releaseUploaded', 'releasePublished', 'candidateAssetBytesReverifiedHere', *FALSE_FLAGS}
    require(set(receipt) == expected and receipt['formatVersion'] == 1 and
        receipt['scope'] == 'actions-created-local-server-draft-metadata-readback' and
        receipt['repository'] == REPOSITORY and receipt['tag'] == TAG and receipt['targetCommit'] == pin['targetCommit'] and
        type(receipt['releaseId']) is int and receipt['releaseId'] > 0 and
        receipt['draft'] is True and receipt['prerelease'] is True and
        receipt['metadataCreatedBy'] == 'github-actions-token' and receipt['creatorWorkflow'] == WORKFLOW and
        type(receipt['creatorRun']) is int and receipt['creatorRun'] > 0 and
        re.fullmatch('[a-f0-9]{40}', receipt['creatorRevision']) and receipt['measuredProducerRun'] == pin['workflowRun'] and
        receipt['selection'] == digest(engine.canonical(pin)) and receipt['body'] == digest(body.encode()) and
        receipt['measuredLock'] == pin['measurementFiles']['measured-release.lock.json'] and receipt['assets'] == pin['assets'] and
        all(receipt[name] is False for name in ('draftUiInspected', 'releaseUploaded', 'releasePublished',
            'candidateAssetBytesReverifiedHere', *FALSE_FLAGS)), 'draft-creation-explicit-prior-receipt-required')
    run = api.json('/actions/runs/' + str(receipt['creatorRun']))
    require(run.get('id') == receipt['creatorRun'] and run.get('head_sha') == receipt['creatorRevision'] and
        run.get('path') == WORKFLOW and run.get('repository', {}).get('full_name') == REPOSITORY,
        'draft-creation-prior-workflow-differs')
    current = api.json('/releases/' + str(receipt['releaseId']))
    check_created(current, pin, body, receipt['releaseId']); check_tag(api, pin)
    require(api.json('/releases/' + str(receipt['releaseId']) + '/assets?per_page=100') == [],
        'draft-creation-prior-draft-no-longer-empty')
    return dict(formatVersion=1, scope='read-only-prior-actions-created-draft-verification',
        releaseId=receipt['releaseId'], targetCommit=pin['targetCommit'], mutationsPerformed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('create', 'validate-measurement', 'verify-created'))
    parser.add_argument('--recipe-root', type=Path, required=True)
    parser.add_argument('--measurement-directory', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); pin = load_pin()
    require(not os.path.lexists(args.output), 'draft-creation-existing-receipt-preserved')
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.operation == 'validate-measurement':
        require(args.measurement_directory is not None, 'draft-creation-local-measurement-required')
        body = validate_measurement(args.recipe_root, args.measurement_directory, pin)
        result = dict(formatVersion=1, scope='local-exact-draft-measurement-validation',
            targetCommit=pin['targetCommit'], body=digest(body.encode()), mutationPerformed=False,
            candidateAssetBytesReverifiedHere=False)
    else:
        require(args.measurement_directory is None, 'draft-creation-must-acquire-exact-retained-measurement')
        api = transport.Github(os.environ.get('GITHUB_TOKEN'))
        with tempfile.TemporaryDirectory(prefix='esteria-draft-metadata-') as temporary:
            directory = acquire_measurement(api, Path(temporary), pin)
            body = validate_measurement(args.recipe_root, directory, pin)
        if args.operation == 'create':
            require(args.receipt is None, 'draft-creation-prior-receipt-use-read-only-verification')
            context = dict(repository=os.environ.get('GITHUB_REPOSITORY'), ref=os.environ.get('GITHUB_REF'),
                event=os.environ.get('GITHUB_EVENT_NAME'), run=int(os.environ.get('GITHUB_RUN_ID', '0')),
                revision=os.environ.get('GITHUB_SHA'))
            result = create(api, pin, body, context)
        else:
            require(args.receipt is not None, 'draft-creation-explicit-prior-receipt-required')
            result = verify_created(api, pin, body, transport.small_json(args.receipt))
    engine.put_metadata(args.output, result)
    print(json.dumps(dict(operation=args.operation, targetCommit=pin['targetCommit'],
        releaseId=result.get('releaseId'), outputWritten=True)))


if __name__ == '__main__': main()
