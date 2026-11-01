#!/usr/bin/env python3
"""Preserve the exact qualified data-tool ZIPs as one additive public release.

The original package includes complete corresponding sources and paired debug.
Native execution was performed in its bound CI run; preservation does not run
extractors, use owner game assets or qualify Android/world entry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import prepare_data_tools_provider as inputs
from tools import publish_detached_non_custom as provenance
from tools import release_server_dependencies as github

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = 'runtime/server/data-tools-publication'
LOCK = ROOT / DIRECTORY / 'component-release.lock.json'
PUBLICATION = 'published-release.json'
READBACK = 'public-source-readback.json'
REPOSITORY = github.REPOSITORY
TAG = 'non-custom-data-tools-v7'
WORKFLOW = '.github/workflows/server-data-tools.yml'
SCOPE = 'exact-qualified-data-tools-source-debug-write-once-release'
NAMES = dict(package='composed-data-tools-package.zip', native='composed-data-tools-native-evidence.zip')
FALSE_FLAGS = ('extractorExecutedHere', 'ownerGameDataSupplied', 'androidRuntimeQualified', 'gameplayQualified')
require = inputs.require
identity = inputs.files.identity
encoded = github.encoded


def selected_inputs():
    return dict(providerInputLock=identity(inputs.provider.LOCK), qualifiedInputLock=identity(inputs.LOCK))


def validate_lock(value, selected, pin):
    require(type(value) is dict and set(value) == {'formatVersion', 'scope', 'repository', 'tag',
        'targetCommit', 'workflowRun', 'packageJobId', 'nativeJobId', 'selectedInputs', 'artifacts', *FALSE_FLAGS} and
        type(value['formatVersion']) is int and value['formatVersion'] == 1 and value['scope'] == SCOPE and
        value['repository'] == REPOSITORY and value['tag'] == TAG and value['selectedInputs'] == selected and
        value['artifacts'] == pin['artifacts'] and all(value.get(k) is False for k in FALSE_FLAGS),
        'data-tools-public-exact-current-qualified-selection')
    require(all(type(value.get(k)) is int and value[k] > 0 for k in
        ('workflowRun', 'packageJobId', 'nativeJobId')) and value['packageJobId'] != value['nativeJobId'] and
        re.fullmatch('[0-9a-f]{40}', value.get('targetCommit', '')) and
        all(row['workflowRun'] == value['workflowRun'] and row['integrationRevision'] == value['targetCommit']
            for row in value['artifacts'].values()), 'data-tools-public-one-successful-source-run-required')
    return value


def load_lock():
    return validate_lock(provenance.read_json(LOCK), selected_inputs(), inputs.load_pin())


def artifact_selection(lock, key):
    row = lock['artifacts'][key]
    prefix = 'composed-data-tools-package-' if key == 'package' else 'composed-data-tools-native-evidence-'
    return dict(id=row['id'], name=prefix + lock['targetCommit'], bytes=row['bytes'], sha256=row['sha256'])


def verify_runs(api, lock):
    result = {}
    mandatory = dict(package=('Derive only ordered readers and compose unchanged stock tools',
        'Bind transfer receipt and completely read back original paired debug'),
        native=('Run all four derived entry points and exact YAML in the reference image',
        'Exercise the actual stripped ordered pair through synthetic source-bound lookups'))
    for key in ('package', 'native'):
        result[key] = provenance.verify_run(api, lock['workflowRun'], lock[key + 'JobId'], WORKFLOW,
            key, mandatory[key], lock['targetCommit'])
        provenance.verify_artifact(api, artifact_selection(lock, key), lock['workflowRun'], lock['targetCommit'])
    return result


def measure(run, jobs, package_artifact, native_artifact):
    pin = inputs.load_pin()
    matches = {key: [j for j in jobs.get('jobs', []) if j.get('name') == key] for key in ('package', 'native')}
    require(all(len(rows) == 1 for rows in matches.values()), 'data-tools-public-two-qualified-jobs-required')
    value = dict(formatVersion=1, scope=SCOPE, repository=REPOSITORY, tag=TAG,
        targetCommit=run.get('head_sha'), workflowRun=run.get('id'),
        packageJobId=matches['package'][0]['id'], nativeJobId=matches['native'][0]['id'],
        selectedInputs=selected_inputs(), artifacts=pin['artifacts'], **{k: False for k in FALSE_FLAGS})
    validate_lock(value, selected_inputs(), pin)
    rows = {str(row.get('id')): row for row in (package_artifact, native_artifact)}
    class ReadOnlyMetadata:
        def json(self, path):
            if path == '/actions/runs/' + str(value['workflowRun']): return run
            if path == '/actions/runs/' + str(value['workflowRun']) + '/jobs?per_page=100': return jobs
            if path.startswith('/actions/artifacts/'): return rows[path.rsplit('/', 1)[1]]
            raise ValueError('data-tools-public-unexpected-measurement-query')
    verify_runs(ReadOnlyMetadata(), value)
    return value


def manifest(lock):
    return encoded(dict(formatVersion=1, scope=SCOPE, repository=REPOSITORY, tag=TAG,
        targetCommit=lock['targetCommit'], selectedInputs=lock['selectedInputs'],
        artifacts=lock['artifacts'], files={NAMES[key]: inputs.engine.identity(row)
            for key, row in lock['artifacts'].items()}, **{k: False for k in FALSE_FLAGS}))


def expected_files(lock):
    result = {NAMES[key]: inputs.engine.identity(row) for key, row in lock['artifacts'].items()}
    raw = manifest(lock)
    result['release-manifest.json'] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    raw = ''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(result.items())).encode()
    result['SHA256SUMS'] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return result


def extract_and_verify(directory, output, lock):
    require(not os.path.lexists(output), 'data-tools-public-existing-validation-output-preserved')
    output.mkdir(mode=0o700)
    acquired = output / 'inputs'; acquired.mkdir(mode=0o700)
    for key, row in lock['artifacts'].items():
        inputs.transfer.extract_selected(directory / NAMES[key], acquired, row)
    proof = inputs.build(acquired, output / 'provider')
    require(proof.get('providerVerified') is True and proof.get('sourceAndPairedDebugVerified') is True and
        all(proof.get(k) is False for k in ('androidRuntimeQualified', 'clientMpqConversionQualified', 'gameplayQualified')),
        'data-tools-public-complete-source-and-debug-admission-required')
    return proof


def stage(api, output):
    lock = load_lock()
    require(not os.path.lexists(output), 'data-tools-public-existing-output-preserved')
    runs = verify_runs(api, lock)
    output.mkdir(parents=True, mode=0o700)
    release = output / 'release'; release.mkdir(mode=0o700)
    for key, row in lock['artifacts'].items():
        api.download(github.API + '/actions/artifacts/' + str(row['id']) + '/zip', release / NAMES[key], row)
    verified = extract_and_verify(release, output / 'validation', lock)
    (release / 'release-manifest.json').write_bytes(manifest(lock))
    expected = expected_files(lock)
    sums = ''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(expected.items()) if name != 'SHA256SUMS').encode()
    (release / 'SHA256SUMS').write_bytes(sums)
    require(all(identity(release / name) == row for name, row in expected.items()), 'data-tools-public-staged-assets-differ')
    proof = dict(formatVersion=1, scope=SCOPE, lock=identity(LOCK), sourceRuns=runs,
        completeSourceAndPairedDebugVerified=True, provider=verified, assets=expected,
        **{k: False for k in FALSE_FLAGS})
    (output / 'stage.json').write_bytes(encoded(proof))
    return proof


def publish(api, output, proof):
    lock = load_lock(); expected = expected_files(lock)
    require(proof.get('lock') == identity(LOCK) and proof.get('completeSourceAndPairedDebugVerified') is True and
        proof.get('assets') == expected and
        all(identity(output / 'release' / name) == row for name, row in expected.items()),
        'data-tools-public-staged-qualification-or-bytes-changed')
    require(api.json('/git/ref/tags/' + TAG, missing=True) is None and
        api.json('/releases/tags/' + TAG, missing=True) is None,
        'data-tools-public-existing-tag-or-release-preserved')
    body = ('Exact original qualified composed data-tool package and native evidence ZIPs.\n\n'
        'The package retains the complete ordered-reader corresponding sources, paired debug, original notices, '
        'unchanged assembler/navigation pair, and fixed YAML. Native source/CLI receipts bind the shipped bytes. '
        'No game assets, private state or signing material. Android/world entry remains unqualified.\n')
    created = api.json('/releases', method='POST', value=dict(tag_name=TAG, target_commitish=lock['targetCommit'],
        name='Esteria Stock v7 ordered data tools and complete sources', body=body, draft=True, prerelease=True))
    require(type(created.get('id')) is int and created['id'] > 0 and created.get('draft') is True and
        created.get('prerelease') is True and created.get('tag_name') == TAG, 'data-tools-public-draft-creation-failed')
    (output / 'publication-draft.json').write_bytes(encoded(dict(releaseId=created['id'], tag=TAG, published=False)))
    assets = {}
    base = 'https://github.com/' + REPOSITORY + '/releases/'
    for name, row in sorted(expected.items()):
        actual = api.upload(created['id'], name, output / 'release' / name, row)
        require(type(actual.get('id')) is int and actual['id'] > 0 and actual.get('state') == 'uploaded' and
            actual.get('name') == name and actual.get('size') == row['bytes'] and
            actual.get('digest') == 'sha256:' + row['sha256'], 'data-tools-public-upload-readback-differs')
        assets[name] = dict(row, assetId=actual['id'], url=base + 'download/' + TAG + '/' + name)
    final = api.json('/releases/' + str(created['id']), method='PATCH', value=dict(draft=False))
    require(final.get('id') == created['id'] and final.get('draft') is False and final.get('prerelease') is True and
        final.get('tag_name') == TAG and final.get('html_url') == base + 'tag/' + TAG,
        'data-tools-public-published-release-differs')
    ref = api.json('/git/ref/tags/' + TAG)
    require(ref.get('object', {}).get('type') == 'commit' and ref['object'].get('sha') == lock['targetCommit'],
        'data-tools-public-exact-tag-target-required')
    value = dict(formatVersion=1, scope=SCOPE, repository=REPOSITORY, tag=TAG,
        targetCommit=lock['targetCommit'], releaseId=created['id'], url=final['html_url'],
        publisherNeverOverwrites=True, assets=assets)
    (output / PUBLICATION).write_bytes(encoded(value))
    return value


def validate_publication(value, lock):
    expected = expected_files(lock); base = 'https://github.com/' + REPOSITORY + '/releases/'
    require(type(value) is dict and set(value) == {'formatVersion', 'scope', 'repository', 'tag',
        'targetCommit', 'releaseId', 'url', 'publisherNeverOverwrites', 'assets'} and
        type(value['formatVersion']) is int and value['formatVersion'] == 1 and value['scope'] == SCOPE and
        value['repository'] == REPOSITORY and value['tag'] == TAG and value['targetCommit'] == lock['targetCommit'] and
        type(value['releaseId']) is int and value['releaseId'] > 0 and value['url'] == base + 'tag/' + TAG and
        value['publisherNeverOverwrites'] is True and type(value['assets']) is dict and set(value['assets']) == set(expected),
        'data-tools-public-publication-receipt-required')
    for name, row in expected.items():
        actual = value['assets'][name]
        require(type(actual) is dict and set(actual) == {'bytes', 'sha256', 'assetId', 'url'} and
            type(actual['assetId']) is int and actual['assetId'] > 0 and inputs.engine.identity(actual) == row and
            actual['url'] == base + 'download/' + TAG + '/' + name, 'data-tools-public-receipt-asset-differs')
    return value


def readback(publication, output, api=None):
    lock = load_lock(); validate_publication(publication, lock)
    require(not os.path.lexists(output), 'data-tools-public-existing-readback-preserved')
    api = api or github.Github(None)
    release = api.json('/releases/tags/' + TAG); ref = api.json('/git/ref/tags/' + TAG)
    require(release.get('id') == publication['releaseId'] and release.get('draft') is False and
        release.get('prerelease') is True and release.get('tag_name') == TAG and
        ref.get('object', {}).get('type') == 'commit' and ref['object'].get('sha') == lock['targetCommit'],
        'data-tools-public-live-release-or-tag-differs')
    expected = expected_files(lock); rows = release.get('assets', [])
    assets = {row.get('name'): row for row in rows}
    require(len(rows) == len(assets) and set(assets) == set(expected), 'data-tools-public-live-asset-closure')
    output.mkdir(parents=True, mode=0o700)
    for name, row in expected.items():
        actual = assets[name]
        require(actual.get('id') == publication['assets'][name]['assetId'] and actual.get('state') == 'uploaded' and
            actual.get('size') == row['bytes'] and actual.get('digest') == 'sha256:' + row['sha256'],
            'data-tools-public-live-asset-identity')
        api.download(publication['assets'][name]['url'], output / name, row)
    require((output / 'release-manifest.json').read_bytes() == manifest(lock), 'data-tools-public-manifest-differs')
    verified = extract_and_verify(output, output / 'validation', lock)
    result = dict(formatVersion=1, scope='anonymous-data-tools-complete-source-debug-readback',
        releaseId=publication['releaseId'], targetCommit=lock['targetCommit'], assets=expected,
        allStoredBytesReadBack=True, completeSourcesAndPairedDebugVerified=True,
        qualifiedInputLock=lock['selectedInputs']['qualifiedInputLock'],
        **{k: False for k in FALSE_FLAGS})
    (output / READBACK).write_bytes(encoded(result))
    return result


def public_selection(pin):
    paths = [ROOT / DIRECTORY / name for name in (PUBLICATION, READBACK)]
    present = [os.path.lexists(path) for path in paths]
    if not any(present): return None
    require(all(present), 'data-tools-public-partial-receipts-refused')
    lock = load_lock(); require(lock['artifacts'] == pin['artifacts'], 'data-tools-public-current-artifacts-differ')
    publication = validate_publication(provenance.read_json(paths[0]), lock)
    read = provenance.read_json(paths[1])
    require(type(read) is dict and set(read) == {'formatVersion', 'scope', 'releaseId', 'targetCommit', 'assets',
        'allStoredBytesReadBack', 'completeSourcesAndPairedDebugVerified', 'qualifiedInputLock', *FALSE_FLAGS} and
        type(read['formatVersion']) is int and read['formatVersion'] == 1 and
        read['scope'] == 'anonymous-data-tools-complete-source-debug-readback' and
        read['releaseId'] == publication['releaseId'] and read['targetCommit'] == lock['targetCommit'] and
        read['assets'] == expected_files(lock) and read['qualifiedInputLock'] == identity(inputs.LOCK) and
        read['allStoredBytesReadBack'] is True and read['completeSourcesAndPairedDebugVerified'] is True and
        all(read.get(k) is False for k in FALSE_FLAGS), 'data-tools-public-full-anonymous-readback-required')
    return dict(lock=lock, publication=publication, readback=read)


def acquire_public(pin, output, selected):
    api = github.Github(None)
    for key, row in pin['artifacts'].items():
        name = NAMES[key]; path = output / name
        api.download(selected['publication']['assets'][name]['url'], path, row)
        inputs.transfer.extract_selected(path, output, row); path.unlink()
    return dict(formatVersion=1, scope='exact-qualified-data-tools-provider-input-readback',
        inputLock=identity(inputs.LOCK), everySelectedInputHashVerified=True, serverRebuilt=False,
        publicReleaseId=selected['publication']['releaseId'], actionsArtifactsUsed=False,
        completeSourceAndPairedDebugPreviouslyReadBack=True, androidRuntimeQualified=False, gameplayQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('measure', 'stage', 'readback'))
    parser.add_argument('--output', type=Path, required=True)
    for name in ('run', 'jobs', 'package-artifact', 'native-artifact', 'publication'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if args.action == 'measure':
        require(all(getattr(args, key) for key in ('run', 'jobs', 'package_artifact', 'native_artifact')),
            'data-tools-public-measurement-metadata-required')
        require(not args.output.exists(), 'data-tools-public-existing-measurement-preserved')
        value = measure(*(provenance.read_json(getattr(args, key)) for key in
            ('run', 'jobs', 'package_artifact', 'native_artifact')))
        args.output.write_bytes(encoded(value))
    elif args.action == 'readback':
        require(args.publication is not None, 'data-tools-public-publication-file-required')
        value = readback(provenance.read_json(args.publication), args.output)
    else:
        require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and
            os.environ.get('GITHUB_REF') == 'refs/heads/non-custom', 'data-tools-public-repository-branch-required')
        api = github.Github(os.environ.get('GITHUB_TOKEN')); value = stage(api, args.output)
        if args.publish:
            value = publish(api, args.output, value)
            read = readback(value, args.output / 'anonymous-readback')
            (args.output / READBACK).write_bytes(encoded(read))
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == '__main__': main()
