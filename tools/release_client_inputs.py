#!/usr/bin/env python3
"""Retain the measured reconstructed client artifact and full matching sources.

Client GitHub access is GET-only and fixed to the authorized public client repo.
Release writes use the shared integration-repository upload-only draft policy.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener
import zipfile

try:
    from . import dependency_publication as publication, provider_client_runtime as provider
except ImportError:
    import dependency_publication as publication, provider_client_runtime as provider

shared = publication.transport
require = shared.require
ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/client/dependency-release.lock.json'
CLIENT_API = 'https://api.github.com/repos/Russianranger/wowdecomp_esteria'
ARTIFACT = 'reconstructed-client-arm64-original.zip'
SOURCE_ARCHIVE = 'client-corresponding-source.tar.gz'
SOURCE_RECEIPT = 'source-receipt.json'
INPUT_LOCK = 'client-input-lock.json'
PAYLOAD_FILES = {ARTIFACT, SOURCE_ARCHIVE, SOURCE_RECEIPT, INPUT_LOCK, 'NOTICE.txt'}
RELEASE_FILES = PAYLOAD_FILES | {'release-manifest.json', 'SHA256SUMS'}
NOTICE = provider.NOTICE + b'''This archival release retains the original CI ZIP without repacking it, including
compiler logs and symbols. It pairs it with the complete pinned client Git tree,
original Xvid source, integration recipes and existing component license notices.
The client Git tree includes its committed addon source/assets. No separately
imported WoW data, account credentials, database or private saves are included.
The integration repository license does not relicense the client or dependencies.
'''


class ClientArtifacts:
    """No configurable origin or mutation methods; credentials never cross redirects."""
    def __init__(self, token=None):
        self.token = token; self.opener = build_opener(shared.NoRedirect)

    def open(self, path):
        require(re.fullmatch(r'/actions/(?:runs/[0-9]+|artifacts/[0-9]+(?:/zip)?)', path), 'client-read-route-rejected')
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'esteria-client-input-preserver',
                   'X-GitHub-Api-Version': '2022-11-28'}
        if self.token: headers['Authorization'] = 'Bearer ' + self.token
        try:
            return self.opener.open(Request(CLIENT_API + path, headers=headers), timeout=180)
        except HTTPError as error:
            if path.endswith('/zip') and error.code in (301, 302, 303, 307, 308):
                destination = error.headers.get('Location', ''); parsed = urlsplit(destination)
                require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password and
                        (parsed.hostname.endswith('.githubusercontent.com') or parsed.hostname.endswith('.blob.core.windows.net')),
                        'unexpected-client-artifact-redirect')
                # Rebuild unauthenticated request; the signed URL is never logged.
                return self.opener.open(Request(destination, headers={'User-Agent': 'esteria-client-input-preserver'}), timeout=180)
            raise

    def json(self, path):
        try:
            with self.open(path) as incoming: data = incoming.read(shared.MAX_JSON + 1)
        except HTTPError as error:
            raise ValueError(f'client GET {path} failed with HTTP {error.code}; no token/response exported') from None
        require(len(data) <= shared.MAX_JSON, 'client-api-metadata-limit'); return json.loads(data)

    def download(self, artifact_id, path, expected):
        require(not os.path.lexists(path), 'client-input-output-exists')
        try:
            with self.open('/actions/artifacts/' + str(artifact_id) + '/zip') as incoming, path.open('xb') as outgoing:
                require(provider.archives.hash_stream(incoming, expected['bytes'], outgoing) == expected['sha256'],
                        'client-original-artifact-hash-mismatch')
                outgoing.flush(); os.fsync(outgoing.fileno())
        except HTTPError as error:
            raise ValueError(f'client artifact download failed with HTTP {error.code}; no token/redirect/response exported') from None


def load_lock():
    lock = shared.small_json(LOCK); pin_bytes = provider.small(provider.PIN); pin = json.loads(pin_bytes)
    require(lock.get('formatVersion') == 1 and lock.get('repository') == shared.REPOSITORY and
            lock.get('scope') == 'reconstructed-client-inputs-write-once-prerelease' and
            re.fullmatch(r'deps-client-arm64-[a-z0-9-]+', lock['tag']) and
            re.fullmatch('[0-9a-f]{40}', lock['targetCommit']), 'invalid-client-release-scope')
    require(hashlib.sha256(pin_bytes).hexdigest() == lock['providerLockSha256'] and
            pin['sourceRevision'] == lock['sourceRevision'] and pin['buildId'] == lock['buildId'] and
            pin['workflowRun'] == lock['workflowRun'] and pin['artifactId'] == lock['artifact']['id'] and
            pin['artifact'] == {key: lock['artifact'][key] for key in ('bytes', 'sha256')}, 'measured-client-release-pin-mismatch')
    return lock, pin


def release_body(lock):
    return ('Dependency-only archival prerelease. Reconstructed Windows ARM64 client requiring a separate local Wine runtime; Android/gameplay unqualified.\n\n'
            'Provider packaging revision: `' + lock['targetCommit'] + '`. Exact client source revision: `' + lock['sourceRevision'] +
            '`, build `' + lock['buildId'] + '`.\n\n'
            'The exact original CI ZIP is retained with symbols/build logs and matching complete client Git tree, original Xvid '
            'source, integration recipes and existing license notices. The client Git tree includes its committed addon source/assets. '
            'No APK, separately imported game data, database, credentials or private saves. The integration license does not relicense client code.\n\n'
            'Assets and tag are write-once: this publisher never replaces them. Verify SHA256SUMS and release-manifest.json. '
            'GitHub-enforced immutability is recorded separately; this workflow does not change repository settings.\n')


def receipt_check(companion, lock, pin):
    require(shared.identity(companion / SOURCE_RECEIPT) == lock['sourceReceipt'], 'client-source-receipt-identity-mismatch')
    receipt = shared.small_json(companion / SOURCE_RECEIPT)
    require(receipt['formatVersion'] == 1 and receipt['scope'] == 'retained-reconstructed-client-source-inputs' and
            receipt['source']['commit'] == pin['sourceRevision'] and receipt['source']['patches'] == [] and
            receipt['source']['submodules'] == {} and receipt['clientArtifact'] == pin['artifact'] and
            receipt['clientBuildId'] == pin['buildId'] and receipt['inputLockSha256'] == lock['providerLockSha256'] and
            receipt['archive'] == lock['sourceArchive'] and receipt['archiveReadBack'] is True and
            receipt['androidRuntimeQualified'] is False and receipt['gameplayQualified'] is False,
            'client-source-receipt-provenance-mismatch')
    require(shared.identity(companion / SOURCE_ARCHIVE) == lock['sourceArchive'], 'client-source-archive-identity-mismatch')
    provider.audit(companion / SOURCE_ARCHIVE, receipt['members'])
    return receipt


def retained_source_lock(companion, receipt):
    name = 'integration-recipe/sources.lock.json'; expected = receipt['members'][name]
    limits = dict(entries=len(receipt['members']), memberBytes=256*1024**2, fileBytes=256*1024**2, pathBytes=4096)
    with provider.archives.plain_file(companion / SOURCE_ARCHIVE) as incoming, provider.archives.bounded_tar(incoming, limits) as tar:
        for member in tar:
            if member.name == name:
                require(member.size == expected['bytes'] and member.size <= provider.META_LIMIT, 'retained-source-lock-size')
                with tar.extractfile(member) as stream: data = stream.read(member.size + 1)
                require(hashlib.sha256(data).hexdigest() == receipt['sourceLockSha256'] == expected['sha256'], 'retained-source-lock-hash')
                return data
            tar.members.clear()
    raise ValueError('retained-source-lock-missing')


def manifest(lock, identities):
    return dict(formatVersion=1, scope=lock['scope'], repository=shared.REPOSITORY, targetCommit=lock['targetCommit'],
                tag=lock['tag'], sourceRevision=lock['sourceRevision'], buildId=lock['buildId'], workflowRun=lock['workflowRun'],
                providerLockSha256=lock['providerLockSha256'], originalArtifact=lock['artifact'], files=identities,
                androidRuntimeQualified=False, gameplayQualified=False)


def verify_candidate(path, lock, pin, client_source):
    path = provider.archives.directory(path)
    require({item.name for item in path.iterdir()} == RELEASE_FILES, 'client-release-file-set-mismatch')
    require(shared.identity(path / ARTIFACT) == pin['artifact'], 'client-original-artifact-identity-mismatch')
    require(provider.small(path / INPUT_LOCK) == provider.small(provider.PIN), 'client-input-lock-changed')
    receipt = receipt_check(path, lock, pin)
    source_bytes = retained_source_lock(path, receipt)
    # Actual pinned PE parser, descriptors, imports and notices are rechecked on
    # every validation/publishing job, using the exact retained source lock.
    with tempfile.TemporaryDirectory(prefix='esteria-release-client-check-') as temporary:
        provider.prepare(path / ARTIFACT, client_source, Path(temporary), pin, source_bytes)
    require(provider.small(path / 'NOTICE.txt') == NOTICE, 'client-release-notice-mismatch')
    identities = {name: shared.identity(path / name) for name in sorted(PAYLOAD_FILES)}
    require(provider.small(path / 'release-manifest.json') == shared.encoded(manifest(lock, identities)), 'client-release-manifest-mismatch')
    identities['release-manifest.json'] = shared.identity(path / 'release-manifest.json')
    sums = ''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(identities.items())).encode()
    require(provider.small(path / 'SHA256SUMS') == sums, 'client-release-checksums-mismatch')
    identities['SHA256SUMS'] = shared.identity(path / 'SHA256SUMS')
    return dict(sorted(identities.items()))


def stage(artifact, companion, output, lock, pin, client_source):
    require(not os.path.lexists(output), 'client-release-output-exists')
    receipt_check(companion, lock, pin)
    require(shared.identity(artifact) == pin['artifact'], 'client-original-artifact-identity-mismatch')
    provider.archives.directory(output.parent, create=True)
    with tempfile.TemporaryDirectory(prefix='.client-release-', dir=output.parent) as temporary:
        candidate = Path(temporary) / 'candidate'; candidate.mkdir(mode=0o700)
        for original, name in ((artifact, ARTIFACT), (companion / SOURCE_ARCHIVE, SOURCE_ARCHIVE), (companion / SOURCE_RECEIPT, SOURCE_RECEIPT)):
            with provider.archives.plain_file(original) as incoming, (candidate / name).open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing, 128*1024)
        (candidate / INPUT_LOCK).write_bytes(provider.small(provider.PIN)); (candidate / 'NOTICE.txt').write_bytes(NOTICE)
        identities = {name: shared.identity(candidate / name) for name in sorted(PAYLOAD_FILES)}
        (candidate / 'release-manifest.json').write_bytes(shared.encoded(manifest(lock, identities)))
        identities['release-manifest.json'] = shared.identity(candidate / 'release-manifest.json')
        (candidate / 'SHA256SUMS').write_text(''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(identities.items())))
        result = verify_candidate(candidate, lock, pin, client_source)
        provider.publish_directory(candidate, output); provider.archives.sync_directory(output.parent)
        return result


def download_original(api, output, lock):
    run = api.json('/actions/runs/' + str(lock['workflowRun'])); expected = lock['artifact']
    require(run['head_sha'] == lock['sourceRevision'] and run['conclusion'] == 'success' and
            run['head_branch'] == 'android/arm64-port', 'original-client-workflow-provenance-mismatch')
    row = api.json('/actions/artifacts/' + str(expected['id']))
    require(row['name'] == expected['name'] and row['size_in_bytes'] == expected['bytes'] and
            row.get('digest') == 'sha256:' + expected['sha256'] and row['expired'] is False and
            row['workflow_run']['id'] == lock['workflowRun'] and row['workflow_run']['head_sha'] == lock['sourceRevision'],
            'original-client-artifact-unavailable-or-mismatched')
    api.download(expected['id'], output, expected)


def fetch(api, output, lock, pin, client_source):
    published = lock.get('published')
    require(isinstance(published, dict) and published.get('repository') == shared.REPOSITORY and
            published.get('tag') == lock['tag'] and published.get('targetCommit') == lock['targetCommit'] and
            set(published.get('assets', {})) == RELEASE_FILES, 'durable-client-release-not-yet-recorded')
    require(not os.path.lexists(output), 'client-fetch-output-exists')
    provider.archives.directory(output.parent, create=True)
    with tempfile.TemporaryDirectory(prefix='.client-fetch-', dir=output.parent) as temporary:
        candidate = Path(temporary) / 'candidate'; candidate.mkdir(mode=0o700)
        for name, expected in sorted(published['assets'].items()):
            url = 'https://github.com/' + shared.REPOSITORY + '/releases/download/' + lock['tag'] + '/' + name
            require(expected['url'] == url and type(expected['bytes']) is int and 0 < expected['bytes'] <= 512*1024**2,
                    'client-durable-download-pin-mismatch')
            api.download(url, candidate / name, expected)
        result = verify_candidate(candidate, lock, pin, client_source)
        provider.publish_directory(candidate, output); provider.archives.sync_directory(output.parent)
        return result


def prepare(api, artifact_api, inputs, output, lock, pin, client_source, packaging_source):
    if lock.get('published'): return fetch(api, output, lock, pin, client_source)
    require(inputs is not None and not os.path.lexists(inputs), 'fresh-client-input-directory-required')
    provider.archives.directory(inputs.parent, create=True); inputs.mkdir(mode=0o700)
    download_original(artifact_api, inputs / ARTIFACT, lock)
    require(packaging_source is not None, 'exact-packaging-checkout-required')
    provider.fetch_sources.verify_checkout(packaging_source,
        dict(commit=lock['targetCommit'], submodules={}, patches=[]), [])
    # Use the fixed packaging revision instead of allowing later server lock
    # edits to change this historical client's source companion.
    for name, expected in lock['generationInputs'].items():
        require(shared.identity(packaging_source / name) == expected, 'source-generation-input-changed:' + name)
    api.download(lock['xvid']['url'], inputs / 'xvidcore-1.3.7.tar.gz', lock['xvid'])
    subprocess.run([sys.executable, str((packaging_source / 'tools/package_client_sources.py').resolve()),
        '--client-source', str(client_source.resolve()), '--xvid-source', str((inputs / 'xvidcore-1.3.7.tar.gz').resolve()),
        '--output', str((inputs / 'companion').resolve())], check=True, timeout=180, stdout=subprocess.DEVNULL)
    return stage(inputs / ARTIFACT, inputs / 'companion', output, lock, pin, client_source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'stage', 'verify', 'body', 'upload-draft', 'verify-published', 'fetch'))
    parser.add_argument('--inputs', type=Path); parser.add_argument('--companion', type=Path)
    parser.add_argument('--client-source', type=Path); parser.add_argument('--packaging-source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--wait-seconds', type=int, default=0)
    args = parser.parse_args(); lock, pin = load_lock()
    if args.operation == 'body': print(release_body(lock), end=''); return
    require(args.output is not None and args.client_source is not None, 'output-and-pinned-client-source-required')
    api = publication.Github(os.environ.get('GITHUB_TOKEN')); artifact_api = ClientArtifacts(os.environ.get('GITHUB_TOKEN'))
    policy = publication.DraftPublication(lock, release_body(lock), lambda path: verify_candidate(path, lock, pin, args.client_source))
    if args.operation == 'prepare': result = prepare(api, artifact_api, args.inputs, args.output, lock, pin, args.client_source, args.packaging_source)
    elif args.operation == 'stage':
        require(args.inputs is not None and args.companion is not None, 'artifact-and-companion-required')
        result = stage(args.inputs, args.companion, args.output, lock, pin, args.client_source)
    elif args.operation == 'verify': result = verify_candidate(args.output, lock, pin, args.client_source)
    elif args.operation == 'fetch': result = fetch(api, args.output, lock, pin, args.client_source)
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
        raise SystemExit('Client dependency release failed: ' + message) from None
