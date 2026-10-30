#!/usr/bin/env python3
"""Preserve only exact guest-helper inputs, with their source and license notices."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile

try:
    from . import dependency_publication as publication, provider_guest_bridges as provider
except ImportError:
    import dependency_publication as publication, provider_guest_bridges as provider

shared = publication.transport
require = shared.require
ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/bridges/dependency-release.lock.json'
ARCHIVE = 'guest-bridges-arm64.tar.gz'
INPUT_LOCK = 'guest-bridge-input-lock.json'
PAYLOAD_FILES = {ARCHIVE, INPUT_LOCK, 'guest-bridge-provider.json', 'NOTICE.txt'}
RELEASE_FILES = PAYLOAD_FILES | {'release-manifest.json', 'SHA256SUMS'}
NOTICE = b'''Esteria ARM64 glibc guest helper inputs only. No APK, Wine rootfs or game assets.
The archive retains all 30 measured binary/source/notice/config files, including
GPL-3.0 project X11 sources, MIT PCM adaptation, and complete original libXtst
source plus Debian changes and copyright notice for the statically linked code.
The build-source manifest also lists compiler/development inputs; this release
does not claim to retain every listed build-tool source or the separate Wine
rootfs source closure. The measured build recipe and hashes remain included.
Android execution, game presentation/input/audio and gameplay remain unqualified.
Original CI artifact identity is provenance; downloading that artifact is no
longer needed after this release is published and its receipt is recorded.
'''


def load_lock():
    lock = shared.small_json(LOCK)
    require(lock.get('formatVersion') == 1 and lock.get('repository') == shared.REPOSITORY and
            lock.get('scope') == 'guest-helper-inputs-write-once-prerelease' and
            re.fullmatch(r'deps-guest-bridges-[a-z0-9-]+', lock['tag']) and
            re.fullmatch('[0-9a-f]{40}', lock['targetCommit']), 'invalid-guest-release-scope')
    pin = provider.load_pin()
    require(hashlib.sha256(provider.read_small(provider.LOCK)).hexdigest() == lock['providerLockSha256'],
            'measured-provider-lock-changed; do-not-silently-repin')
    require(lock['originalIntegrationRevision'] == pin['integrationRevision'] and
            lock['workflowRun'] == pin['workflowRun'] and
            all(lock['artifact'][key] == pin['artifact'][key] for key in ('id', 'bytes', 'sha256')),
            'original-guest-artifact-pin-mismatch')
    require(lock['archive']['bytes'] == 469031 and
            lock['archive']['sha256'] == 'a91e2e7cf74957c7caf2c7e85de2a6ee8952d273b3f5e3f18cecb06127791c39',
            'measured-guest-archive-pin-mismatch')
    return lock, pin


def release_body(lock):
    return ('Dependency-only archival prerelease. ARM64 glibc guest display/input/audio helper inputs; Android/gameplay unqualified.\n\n'
            'Provider packaging revision: `' + lock['targetCommit'] + '`. Original helper build revision: `' +
            lock['originalIntegrationRevision'] + '`, workflow `' + str(lock['workflowRun']) + '`.\n\n'
            'The small archive retains all 30 measured binaries, source, license notices and config files, including complete '
            'libXtst source for statically linked code. No APK, Wine rootfs, game content or private state. Complete compiler/'
            'build-tool source and the separate Wine rootfs source closure are outside this archive.\n\n'
            'Assets and tag are write-once: this publisher never replaces them. Verify SHA256SUMS and release-manifest.json. '
            'GitHub-enforced immutability is recorded separately; this workflow does not change repository settings.\n')


def manifest(lock, identities):
    return dict(formatVersion=1, scope=lock['scope'], repository=shared.REPOSITORY,
                targetCommit=lock['targetCommit'], tag=lock['tag'],
                originalIntegrationRevision=lock['originalIntegrationRevision'], workflowRun=lock['workflowRun'],
                originalArtifact=lock['artifact'], providerLockSha256=lock['providerLockSha256'],
                files=identities, androidRuntimeQualified=False, gameplayQualified=False)


def verify_candidate(path, lock, pin):
    path = provider.archives.directory(path)
    require({item.name for item in path.iterdir()} == RELEASE_FILES, 'guest-release-file-set-mismatch')
    require(shared.identity(path / ARCHIVE) == lock['archive'], 'guest-archive-identity-mismatch')
    require(provider.read_small(path / INPUT_LOCK) == provider.read_small(provider.LOCK), 'guest-input-lock-changed')
    payload = provider.read_archive(path / ARCHIVE)
    expected = provider.descriptor(path / ARCHIVE, payload, pin)
    require(provider.read_small(path / 'guest-bridge-provider.json') == provider.encoded(expected), 'guest-descriptor-mismatch')
    require(provider.read_small(path / 'NOTICE.txt') == NOTICE, 'guest-release-notice-mismatch')
    identities = {name: shared.identity(path / name) for name in sorted(PAYLOAD_FILES)}
    require(provider.read_small(path / 'release-manifest.json') == shared.encoded(manifest(lock, identities)), 'guest-release-manifest-mismatch')
    identities['release-manifest.json'] = shared.identity(path / 'release-manifest.json')
    sums = ''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(identities.items())).encode()
    require(provider.read_small(path / 'SHA256SUMS') == sums, 'guest-release-checksums-mismatch')
    identities['SHA256SUMS'] = shared.identity(path / 'SHA256SUMS')
    return dict(sorted(identities.items()))


def stage(artifact, output, lock, pin):
    require(not os.path.lexists(output), 'guest-release-output-exists')
    provider.archives.directory(output.parent, create=True)
    with tempfile.TemporaryDirectory(prefix='.guest-release-', dir=output.parent) as temporary:
        candidate = Path(temporary) / 'candidate'; candidate.mkdir(mode=0o700)
        payload = provider.read_artifact(artifact, pin)
        provider.write_archive(candidate / ARCHIVE, payload)
        (candidate / INPUT_LOCK).write_bytes(provider.read_small(provider.LOCK))
        proof = provider.descriptor(candidate / ARCHIVE, provider.read_archive(candidate / ARCHIVE), pin)
        (candidate / 'guest-bridge-provider.json').write_bytes(provider.encoded(proof))
        (candidate / 'NOTICE.txt').write_bytes(NOTICE)
        identities = {name: shared.identity(candidate / name) for name in sorted(PAYLOAD_FILES)}
        (candidate / 'release-manifest.json').write_bytes(shared.encoded(manifest(lock, identities)))
        identities['release-manifest.json'] = shared.identity(candidate / 'release-manifest.json')
        (candidate / 'SHA256SUMS').write_text(''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(identities.items())))
        result = verify_candidate(candidate, lock, pin)
        provider.publish_directory(candidate, output)
        provider.archives.sync_directory(output.parent)
        return result


def download_original(api, path, lock):
    expected = lock['artifact']
    run = api.json('/actions/runs/' + str(lock['workflowRun']))
    require(run['head_sha'] == lock['originalIntegrationRevision'] and run['conclusion'] == 'success' and
            run['head_branch'] == 'android/client-server', 'original-guest-workflow-provenance-mismatch')
    row = api.json('/actions/artifacts/' + str(expected['id']))
    require(row['name'] == expected['name'] and row['size_in_bytes'] == expected['bytes'] and
            row.get('digest') == 'sha256:' + expected['sha256'] and row['expired'] is False and
            row['workflow_run']['id'] == lock['workflowRun'] and
            row['workflow_run']['head_sha'] == lock['originalIntegrationRevision'], 'original-guest-artifact-unavailable-or-mismatched')
    api.download(shared.API + '/actions/artifacts/' + str(expected['id']) + '/zip', path, expected)


def fetch(api, output, lock, pin):
    published = lock.get('published')
    require(isinstance(published, dict) and published.get('repository') == shared.REPOSITORY and
            published.get('tag') == lock['tag'] and published.get('targetCommit') == lock['targetCommit'] and
            set(published.get('assets', {})) == RELEASE_FILES, 'durable-guest-release-not-yet-recorded')
    require(not os.path.lexists(output), 'guest-fetch-output-exists')
    provider.archives.directory(output.parent, create=True)
    with tempfile.TemporaryDirectory(prefix='.guest-fetch-', dir=output.parent) as temporary:
        candidate = Path(temporary) / 'candidate'; candidate.mkdir(mode=0o700)
        for name, expected in sorted(published['assets'].items()):
            url = 'https://github.com/' + shared.REPOSITORY + '/releases/download/' + lock['tag'] + '/' + name
            require(expected['url'] == url and type(expected['bytes']) is int and 0 < expected['bytes'] <= 2*1024**2,
                    'guest-durable-download-pin-mismatch')
            api.download(url, candidate / name, expected)
        result = verify_candidate(candidate, lock, pin)
        provider.publish_directory(candidate, output); provider.archives.sync_directory(output.parent)
        return result


def export_payload(candidate, output, lock, pin):
    verify_candidate(candidate, lock, pin)
    require(not os.path.lexists(output), 'guest-payload-output-exists')
    provider.archives.directory(output.parent, create=True)
    payload = provider.read_archive(candidate / ARCHIVE)
    with tempfile.TemporaryDirectory(prefix='.guest-payload-', dir=output.parent) as temporary:
        tree = Path(temporary) / 'payload'; tree.mkdir(mode=0o700)
        for name, row in pin['files'].items():
            target = tree / row['payloadPath']; target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream: stream.write(payload[name])
        provider.read_payload(tree, pin)
        provider.publish_directory(tree, output); provider.archives.sync_directory(output.parent)
    return dict(exactProviderPayloadVerified=True, originalArtifactDownloadRequired=False, androidRuntimeQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'stage', 'verify', 'body', 'upload-draft', 'verify-published', 'fetch', 'export-payload'))
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--wait-seconds', type=int, default=0)
    args = parser.parse_args(); lock, pin = load_lock()
    if args.operation == 'body':
        print(release_body(lock), end=''); return
    require(args.output is not None, 'output-required')
    api = publication.Github(os.environ.get('GITHUB_TOKEN'))
    policy = publication.DraftPublication(lock, release_body(lock), lambda path: verify_candidate(path, lock, pin))
    if args.operation == 'prepare':
        if lock.get('published'): result = fetch(api, args.output, lock, pin)
        else:
            require(args.inputs is not None and not os.path.lexists(args.inputs), 'fresh-original-input-path-required')
            provider.archives.directory(args.inputs.parent, create=True)
            download_original(api, args.inputs, lock); result = stage(args.inputs, args.output, lock, pin)
    elif args.operation == 'stage':
        require(args.inputs is not None, 'artifact-input-required'); result = stage(args.inputs, args.output, lock, pin)
    elif args.operation == 'verify': result = verify_candidate(args.output, lock, pin)
    elif args.operation == 'fetch': result = fetch(api, args.output, lock, pin)
    elif args.operation == 'export-payload':
        require(args.inputs is not None, 'candidate-input-required'); result = export_payload(args.inputs, args.output, lock, pin)
    else:
        require(args.inputs is not None and not os.path.lexists(args.output), 'candidate-and-new-receipt-required')
        if args.operation == 'upload-draft':
            require(os.environ.get('GITHUB_REPOSITORY') == shared.REPOSITORY and
                    os.environ.get('GITHUB_REF') == 'refs/heads/android/client-server' and api.token,
                    'publication-requires-owned-development-branch-GitHub-Actions-context')
            result = policy.upload_draft(api, args.inputs)
        else: result = policy.verify_published(api, args.inputs, args.wait_seconds)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('xb') as stream: stream.write(shared.encoded(result))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        message = str(error) if isinstance(error, ValueError) else type(error).__name__
        raise SystemExit('Guest dependency release failed: ' + message) from None
