#!/usr/bin/env python3
"""Validate/preserve exact server dependency artifacts as a write-once prerelease.

Only explicit publish/upload-draft operations write to GitHub. Neither overwrites an
asset, moves a tag, deletes a release, changes repository settings, or ships APKs,
game files, SQL content or private state. Large files are streamed with bounds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import stat
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import zipfile

try:
    from . import provider_server_runtime as provider, prepare_runtime as archives
except ImportError:
    import provider_server_runtime as provider, prepare_runtime as archives

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/server/dependency-release.lock.json'
REPOSITORY = 'Russianranger/esteria_android'
API = 'https://api.github.com/repos/' + REPOSITORY
UPLOAD = 'https://uploads.github.com/repos/' + REPOSITORY
MAX_JSON = 4 * 1024**2
SOURCE_PREFIX = 'out/server-runtime/sources/'
PACKAGE_FILES = {'server-runtime-arm64.tar.gz': 'archive', 'package-receipt.json': 'packageReceipt',
                 'server-runtime.json': 'runtimeMetadata', 'sources.lock.json': 'sourceLock'}
SOURCE_ZIP = 'server-runtime-corresponding-sources.zip'
SOURCE_MANIFEST = 'server-runtime-source-manifest.json'
PAYLOAD_FILES = set(PACKAGE_FILES) | {SOURCE_ZIP, SOURCE_MANIFEST, 'NOTICE.txt'}
RELEASE_FILES = PAYLOAD_FILES | {'release-manifest.json', 'SHA256SUMS'}
NOTICE = (
    'Esteria server dependency runtime only; Linux ARM64 Ubuntu24.04/MySQL8/Python3.\n'
    'No APK, authserver/worldserver, game assets, SQL game content, accounts or saved data.\n'
    'Android execution and gameplay are not qualified by this release.\n'
    'Retain rootfs usr/share/doc/*/copyright and the complete corresponding-source ZIP.\n'
    'That ZIP retains the exact recipe, project LICENSE and original sources for all installed source packages.\n'
    'MySQL is GPL-2.0 with its component notices; dependencies retain individual licenses.\n').encode()
require = archives.require


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def small_json(path):
    with archives.plain_file(path) as stream:
        data = stream.read(MAX_JSON + 1)
    require(len(data) <= MAX_JSON, 'metadata-size-limit')
    return json.loads(data)


def identity(path):
    with archives.plain_file(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        require(0 < size < 2 * 1024**3, 'release-file-size-limit')
        return dict(bytes=size, sha256=archives.hash_stream(stream, size))


def load_lock():
    lock = small_json(LOCK)
    require(lock.get('formatVersion') == 1 and lock.get('repository') == REPOSITORY and
            lock.get('scope') == 'dependency-only-write-once-prerelease', 'invalid-release-scope')
    require(re.fullmatch(r'deps-server-arm64-[a-z0-9-]+', lock['tag']) and
            re.fullmatch('[0-9a-f]{40}', lock['targetCommit']), 'invalid-release-target')
    require(hashlib.sha256(provider.read_small(provider.LOCK)).hexdigest() == lock['providerLockSha256'],
            'measured-provider-lock-changed; do-not-silently-repin')
    pin = provider.load_pin()
    require(lock['targetCommit'] == pin['integrationRevision'] and lock['workflowRun'] == pin['workflowRun'],
            'release-provenance-mismatch')
    require(set(lock['artifactInputs']) == {'runtime', 'evidence', 'sources'}, 'invalid-artifact-set')
    require(lock['artifactInputs']['sources']['id'] == pin['sourceCompanion']['artifactId'] and
            lock['artifactInputs']['sources']['bytes'] == pin['sourceCompanion']['zipBytes'] and
            lock['artifactInputs']['sources']['sha256'] == pin['sourceCompanion']['zipSha256'], 'source-zip-pin-mismatch')
    return lock, pin


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Github:
    def __init__(self, token=None):
        self.token = token
        self.opener = build_opener(NoRedirect)

    def open(self, url, *, method='GET', data=None, accept='application/vnd.github+json', headers=None):
        parsed = urlsplit(url)
        require(parsed.scheme == 'https' and not parsed.username and not parsed.password, 'unsafe-network-url')
        authenticated = parsed.netloc in ('api.github.com', 'uploads.github.com')
        if authenticated:
            require(url.startswith(API + '/') or url.startswith(UPLOAD + '/'), 'repository-boundary')
        fields = {'Accept': accept, 'User-Agent': 'esteria-dependency-preserver', 'X-GitHub-Api-Version': '2022-11-28'}
        if authenticated and self.token:
            fields['Authorization'] = 'Bearer ' + self.token
        fields.update(headers or {})
        try:
            return self.opener.open(Request(url, data=data, headers=fields, method=method), timeout=180)
        except HTTPError as error:
            if method == 'GET' and error.code in (301, 302, 303, 307, 308):
                destination = error.headers.get('Location', '')
                host = urlsplit(destination)
                require(host.scheme == 'https' and host.hostname and not host.username and not host.password and
                        (host.hostname.endswith('.githubusercontent.com') or host.hostname.endswith('.blob.core.windows.net')),
                        'unexpected-download-redirect')
                # A signed object-store URL never receives the GitHub token.
                return self.opener.open(Request(destination, headers={'User-Agent': 'esteria-dependency-preserver'}), timeout=180)
            raise

    def json(self, path, *, method='GET', value=None, missing=False):
        try:
            with self.open(API + path, method=method, data=encoded(value) if value is not None else None,
                           headers={'Content-Type': 'application/json'}) as stream:
                raw = stream.read(MAX_JSON + 1)
        except HTTPError as error:
            if missing and error.code == 404:
                return None
            raise ValueError(f'GitHub {method} {path.split("?")[0]} failed with HTTP {error.code}; no token/response exported') from None
        require(len(raw) <= MAX_JSON, 'github-json-size-limit')
        return json.loads(raw)

    def download(self, url, target, expected):
        require(not os.path.lexists(target), 'download-output-exists')
        # Actions returns its archive redirect through the JSON API media type.
        # Release assets use octet-stream to select bytes instead of metadata.
        actions = url.startswith(API + '/actions/artifacts/')
        accept = 'application/vnd.github+json' if actions else 'application/octet-stream'
        try:
            with self.open(url, accept=accept) as source, target.open('xb') as output:
                digest = archives.hash_stream(source, expected['bytes'], output)
                require(digest == expected['sha256'], 'download-hash-mismatch')
                output.flush(); os.fsync(output.fileno())
        except HTTPError as error:
            # Never render error.url/str(error): object-store redirects carry
            # signed query credentials. The caller's original URL is public.
            route = urlsplit(url).path
            raise ValueError(f'download {route} failed with HTTP {error.code}; no token/redirect/response exported') from None

    def upload(self, release_id, name, path, expected):
        try:
            with archives.plain_file(path) as source, self.open(
                    UPLOAD + '/releases/' + str(release_id) + '/assets?name=' + quote(name), method='POST', data=source,
                    headers={'Content-Type': 'application/octet-stream', 'Content-Length': str(expected['bytes'])}) as response:
                data = response.read(MAX_JSON + 1)
        except HTTPError as error:
            raise ValueError(f'release asset upload failed with HTTP {error.code}; no token/response exported') from None
        require(len(data) <= MAX_JSON, 'github-json-size-limit')
        return json.loads(data)


def zip_members(z):
    result = {}
    for entry in z.infolist():
        name = archives.member_path(entry.filename)
        mode = stat.S_IFMT(entry.external_attr >> 16)
        require(name == entry.filename and name not in result and not entry.is_dir() and
                mode in (0, stat.S_IFREG) and not entry.flag_bits & 1 and
                0 <= entry.file_size <= 512 * 1024**2, 'unsafe-or-duplicate-zip-entry')
        result[name] = entry
    require(len(result) <= 1024, 'zip-entry-count-limit')
    return result


def zip_read(z, entry, maximum=MAX_JSON):
    require(entry.file_size <= maximum, 'zip-metadata-size-limit')
    with z.open(entry) as stream:
        data = stream.read(maximum + 1)
    require(len(data) == entry.file_size, 'zip-metadata-length-mismatch')
    return data


def verify_zip_member(z, entry, expected, output=None):
    require(entry.file_size == expected['bytes'], 'zip-member-size-mismatch')
    with z.open(entry) as stream:
        require(archives.hash_stream(stream, expected['bytes'], output) == expected['sha256'], 'zip-member-hash-mismatch')


def validate_dsc(data, manifest_files):
    fields, key = {}, None
    for line in data.decode('utf-8').splitlines():
        if line.startswith('-----BEGIN PGP SIGNATURE-----'):
            break
        if line.startswith(' ') and key:
            fields[key] += '\n' + line.strip()
        elif ':' in line and not line.startswith('-'):
            key, value = line.split(':', 1); fields[key] = value.strip()
    require('Source' in fields and 'Version' in fields and 'Checksums-Sha256' in fields, 'incomplete-source-descriptor')
    checksums = [line for line in fields['Checksums-Sha256'].splitlines() if line]
    require(checksums, 'missing-source-archive-checksums')
    for line in checksums:
        values = line.split()
        require(len(values) == 3 and values[1].isdigit(), 'invalid-source-descriptor-checksum')
        digest, size, name = values
        require(manifest_files.get(name) == dict(file=name, bytes=int(size), sha256=digest), 'source-descriptor-inventory-mismatch')
    return fields['Source'], fields['Version']


def validate_sources(path, lock, pin, metadata):
    provider.verify_file(path, lock['artifactInputs']['sources'])
    with zipfile.ZipFile(path) as z:
        members = zip_members(z)
        manifest_bytes = zip_read(z, members[SOURCE_PREFIX + 'SOURCE-MANIFEST.json'])
        require(hashlib.sha256(manifest_bytes).hexdigest() == pin['sourceCompanion']['manifestSha256'], 'source-manifest-pin-mismatch')
        manifest = json.loads(manifest_bytes)
        require(manifest['formatVersion'] == 1 and manifest['scope'] == 'installed-ubuntu-package-corresponding-sources' and
                manifest['runtimeManifestSha256'] == pin['runtimeMetadata']['sha256'] and
                manifest['sourceLockSha256'] == pin['sourceLock']['sha256'] and
                manifest['sourcePackages'] == metadata['sourcePackages'], 'source-manifest-provenance-mismatch')
        files = {row['file']: row for row in manifest['files']}
        require(len(files) == len(manifest['files']) == pin['sourceCompanion']['files'] and
                sum(row['bytes'] for row in files.values()) == manifest['fileBytes'] == pin['sourceCompanion']['fileBytes'] and
                len(manifest['sourcePackages']) == pin['sourceCompanion']['sourcePackages'], 'source-manifest-inventory-mismatch')
        expected = {SOURCE_PREFIX + name: row for name, row in files.items()}
        expected.update(lock['sourceCompanionWrappers'])
        expected.update({SOURCE_PREFIX + 'SOURCE-MANIFEST.json': dict(bytes=len(manifest_bytes), sha256=hashlib.sha256(manifest_bytes).hexdigest()),
                         SOURCE_PREFIX + 'server-runtime.json': pin['runtimeMetadata'], SOURCE_PREFIX + 'sources.lock.json': pin['sourceLock']})
        require(set(members) == set(expected), 'source-companion-has-unexpected-or-missing-files')
        sources = set()
        for name, row in expected.items():
            verify_zip_member(z, members[name], row)
            if name.startswith(SOURCE_PREFIX) and name.endswith('.dsc'):
                sources.add(validate_dsc(zip_read(z, members[name]), files))
        require(sources == {(item['package'], item['version']) for item in metadata['sourcePackages']}, 'source-package-closure-mismatch')
    return manifest_bytes, dict(sourcePackages=len(sources), originalArchives=len(files), fileBytes=manifest['fileBytes'])


def validate_notices(path, metadata, limits):
    entries = {}
    with archives.plain_file(path) as stream, archives.bounded_tar(stream, limits) as tar:
        for item in tar:
            entries[item.name] = (item.isfile(), item.size,
                                  archives.link_target(item.name, item.linkname, item.islnk(), 4096) if item.issym() or item.islnk() else None)
            tar.members.clear()
    def resolve(name):
        for _ in range(40):
            components = name.split('/')
            for n in range(1, len(components) + 1):
                prefix = '/'.join(components[:n])
                if entries.get(prefix, (None, None, None))[2] is not None:
                    name = posixpath.normpath('/'.join([entries[prefix][2]] + components[n:])); break
            else:
                return name
        raise ValueError('copyright-link-cycle')
    paths = []
    for package in metadata['packages']:
        name = resolve('usr/share/doc/' + package['package'].split(':')[0] + '/copyright')
        entry = entries.get(name)
        require(entry is not None and entry[0] and entry[1] > 0, 'missing-installed-package-copyright')
        paths.append(name)
    return dict(binaryPackages=len(paths), resolvedCopyrightFiles=len(set(paths)))


def stage(inputs, output, lock, pin):
    require(not os.path.lexists(output), 'release-output-exists')
    archives.directory(output.parent, create=True)
    temporary = Path(tempfile.mkdtemp(prefix='.' + output.name + '-', dir=output.parent))
    try:
        for key, expected in lock['artifactInputs'].items():
            provider.verify_file(inputs / (key + '.zip'), expected)
        with zipfile.ZipFile(inputs / 'runtime.zip') as z:
            members = zip_members(z)
            require(set(members) == set(PACKAGE_FILES), 'unexpected-runtime-artifact-files')
            for name, key in PACKAGE_FILES.items():
                with (temporary / name).open('xb') as out:
                    verify_zip_member(z, members[name], pin[key], out)
        descriptor = provider.descriptor(temporary, pin)
        metadata = small_json(temporary / 'server-runtime.json')
        manifest, source_proof = validate_sources(inputs / 'sources.zip', lock, pin, metadata)
        notice_proof = validate_notices(temporary / pin['archive']['file'], metadata, provider.runtime.LIMITS)
        shutil.copyfile(inputs / 'sources.zip', temporary / SOURCE_ZIP)
        (temporary / SOURCE_MANIFEST).write_bytes(manifest)
        (temporary / 'NOTICE.txt').write_bytes(NOTICE)
        proof = dict(formatVersion=1, scope=lock['scope'], repository=REPOSITORY, tag=lock['tag'],
                     targetCommit=lock['targetCommit'], originalWorkflowRun=lock['workflowRun'],
                     providerLockSha256=lock['providerLockSha256'], sources=source_proof, notices=notice_proof,
                     assets={name: identity(temporary / name) for name in sorted(PAYLOAD_FILES)},
                     sourceInventoryValidated=True, packageNoticesValidated=True,
                     androidRuntimeQualified=False, gameplayQualified=False)
        (temporary / 'release-manifest.json').write_bytes(encoded(proof))
        (temporary / 'SHA256SUMS').write_text(''.join(identity(temporary / name)['sha256'] + '  ' + name + '\n'
                                                    for name in sorted(RELEASE_FILES - {'SHA256SUMS'})))
        verify_candidate(temporary, lock, pin)
        require(not os.path.lexists(output), 'release-output-exists')
        os.rename(temporary, output)
        return proof
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def verify_candidate(path, lock, pin):
    require({item.name for item in path.iterdir()} == RELEASE_FILES, 'unexpected-release-files')
    proof = small_json(path / 'release-manifest.json')
    require(set(proof) == {'formatVersion', 'scope', 'repository', 'tag', 'targetCommit', 'originalWorkflowRun',
                          'providerLockSha256', 'sources', 'notices', 'assets', 'sourceInventoryValidated',
                          'packageNoticesValidated', 'androidRuntimeQualified', 'gameplayQualified'} and
            proof['formatVersion'] == 1 and proof['originalWorkflowRun'] == lock['workflowRun'] and
            proof.get('scope') == lock['scope'] and proof.get('repository') == REPOSITORY and
            proof.get('tag') == lock['tag'] and proof.get('targetCommit') == lock['targetCommit'] and
            proof.get('providerLockSha256') == lock['providerLockSha256'] and
            proof.get('sourceInventoryValidated') is True and proof.get('packageNoticesValidated') is True and
            proof.get('androidRuntimeQualified') is False and proof.get('gameplayQualified') is False and
            set(proof.get('assets', {})) == PAYLOAD_FILES, 'invalid-release-manifest')
    require(proof['sources'] == dict(sourcePackages=pin['sourceCompanion']['sourcePackages'],
                                    originalArchives=pin['sourceCompanion']['files'], fileBytes=pin['sourceCompanion']['fileBytes']),
            'release-source-closure-mismatch')
    for name, expected in proof['assets'].items():
        require(identity(path / name) == expected, 'candidate-file-hash-mismatch')
    for name, key in PACKAGE_FILES.items():
        provider.verify_file(path / name, pin[key])
    provider.verify_file(path / SOURCE_ZIP, lock['artifactInputs']['sources'])
    require(identity(path / SOURCE_MANIFEST)['bytes'] <= MAX_JSON and
            identity(path / SOURCE_MANIFEST)['sha256'] == pin['sourceCompanion']['manifestSha256'],
            'candidate-source-manifest-mismatch')
    require((path / 'NOTICE.txt').stat().st_size == len(NOTICE) and (path / 'NOTICE.txt').read_bytes() == NOTICE,
            'candidate-notice-mismatch')
    metadata = small_json(path / 'server-runtime.json')
    require(proof['notices'] == validate_notices(path / pin['archive']['file'], metadata, provider.runtime.LIMITS),
            'candidate-notice-inventory-mismatch')
    sums = ''.join(identity(path / name)['sha256'] + '  ' + name + '\n' for name in sorted(RELEASE_FILES - {'SHA256SUMS'}))
    require((path / 'SHA256SUMS').stat().st_size < 8192 and
            (path / 'SHA256SUMS').read_text() == sums, 'release-checksum-file-mismatch')
    return {name: identity(path / name) for name in sorted(RELEASE_FILES)}


def download_inputs(api, output, lock):
    require(not os.path.lexists(output), 'input-output-exists')
    output.mkdir(parents=True, mode=0o700)
    run = api.json('/actions/runs/' + str(lock['workflowRun']))
    require(run['head_sha'] == lock['targetCommit'] and run['conclusion'] == 'success' and
            run['head_branch'] == 'android/client-server', 'original-workflow-provenance-mismatch')
    for name, expected in lock['artifactInputs'].items():
        row = api.json('/actions/artifacts/' + str(expected['id']))
        require(row['name'] == expected['name'] and row['size_in_bytes'] == expected['bytes'] and
                row.get('digest') == 'sha256:' + expected['sha256'] and not row['expired'] and
                row['workflow_run']['id'] == lock['workflowRun'] and row['workflow_run']['head_sha'] == lock['targetCommit'],
                'original-artifact-provenance-mismatch-or-expired')
        api.download(API + '/actions/artifacts/' + str(expected['id']) + '/zip', output / (name + '.zip'), expected)


def release_body(lock):
    return ('Dependency-only archival prerelease. Linux ARM64 Ubuntu24.04/MySQL8/Python3; Android/gameplay unqualified.\n\n'
            'Exact original integration revision: `' + lock['targetCommit'] + '`. Original workflow: `' + str(lock['workflowRun']) + '`.\n\n'
            'No APK, game assets, Esteria auth/world executables, game SQL, accounts or saves. The complete corresponding-source ZIP '
            'and retained rootfs copyright notices accompany the runtime.\n\n'
            'Assets and tag are write-once: this publisher never replaces them. Verify SHA256SUMS and release-manifest.json. '
            'GitHub-enforced immutability is recorded separately; this workflow does not change repository settings.\n')


def release_identity(release, lock):
    # The authorized GitHub web editor stores CRLF. Normalize only that exact
    # newline encoding; do not trim, collapse whitespace, or accept bare CR.
    body = release.get('body')
    require(release['tag_name'] == lock['tag'] and release['prerelease'] is True and
            isinstance(body, str) and body.replace('\r\n', '\n') == release_body(lock),
            'existing-release-identity-mismatch; release-preserved')


def find_owned_draft(api, lock):
    # GitHub's by-tag endpoint may omit drafts. List with the publication job's
    # authorized contents permission; never infer ownership from the name alone.
    matches = []
    for page in range(1, 11):
        rows = api.json('/releases?per_page=100&page=' + str(page))
        matches.extend(row for row in rows if row['tag_name'] == lock['tag'])
        if len(rows) < 100:
            break
    else:
        raise ValueError('release-list-bound; no-mutation')
    require(len(matches) == 1, 'exact-owned-UI-draft-required; no-release-created')
    release = matches[0]
    release_identity(release, lock)
    return release


def stored_assets(api, release_id, identities):
    rows = api.json('/releases/' + str(release_id) + '/assets?per_page=100')
    assets = {item['name']: item for item in rows}
    require(len(assets) == len(rows) and set(assets).issubset(RELEASE_FILES), 'unexpected-existing-release-assets')
    for name, row in assets.items():
        check_stored_asset(api, row, identities[name])
    return assets


def check_stored_asset(api, row, expected):
    require(row['state'] == 'uploaded' and row['size'] == expected['bytes'] and
            row.get('digest') == 'sha256:' + expected['sha256'], 'existing-asset-differs; no-overwrite')
    with tempfile.TemporaryDirectory(prefix='esteria-release-verify-') as directory:
        api.download(API + '/releases/assets/' + str(row['id']), Path(directory) / 'stored-asset', expected)


def publication_receipt(release, assets, identities, lock):
    return dict(formatVersion=1, repository=REPOSITORY, tag=lock['tag'], targetCommit=lock['targetCommit'],
                releaseId=release['id'], url=release['html_url'], githubImmutable=release.get('immutable'),
                publisherNeverOverwrites=True, assets={name: dict(identities[name], url=assets[name]['browser_download_url']) for name in sorted(identities)})


def verify_published(api, candidate, lock, pin, wait_seconds=0):
    """Read-only verification after an authorized publisher finalizes the draft."""
    require(type(wait_seconds) is int and 0 <= wait_seconds <= 1200, 'publication-wait-bound')
    identities = verify_candidate(candidate, lock, pin)
    deadline = time.monotonic() + wait_seconds
    while True:
        release = api.json('/releases/tags/' + quote(lock['tag'], safe=''), missing=True)
        if release is not None and release['draft'] is False:
            break
        require(time.monotonic() < deadline, 'published-release-not-yet-available; no-mutation')
        time.sleep(min(15, max(0, deadline - time.monotonic())))
    release_identity(release, lock)
    ref = api.json('/git/ref/tags/' + quote(lock['tag'], safe=''))
    require(ref['object']['type'] == 'commit' and ref['object']['sha'] == lock['targetCommit'], 'existing-tag-target-mismatch; tag-preserved')
    assets = stored_assets(api, release['id'], identities)
    require(set(assets) == RELEASE_FILES, 'published-release-missing-assets; no-repair-or-overwrite')
    return publication_receipt(release, assets, identities, lock)


def upload_draft(api, candidate, lock, pin):
    """Only upload missing assets to the exact existing UI-created draft.

    No tag/ref creation, release creation, metadata mutation, or finalization.
    The UI draft must bind the full original SHA even before its tag exists.
    """
    identities = verify_candidate(candidate, lock, pin)
    release = find_owned_draft(api, lock)
    if release['draft'] is False:
        # A repeated invocation may verify a complete published release, but
        # cannot add even one missing asset or alter its metadata.
        return dict(draft=False, completeAssetSetVerified=True,
                    published=verify_published(api, candidate, lock, pin))
    require(release['draft'] is True and release['target_commitish'] == lock['targetCommit'],
            'UI-draft-must-bind-exact-original-commit')
    ref = api.json('/git/ref/tags/' + quote(lock['tag'], safe=''), missing=True)
    require(ref is None or (ref['object']['type'] == 'commit' and ref['object']['sha'] == lock['targetCommit']),
            'existing-tag-target-mismatch; tag-preserved')
    release_id = release['id']
    assets = stored_assets(api, release_id, identities)
    for name, expected in identities.items():
        if name not in assets:
            current = api.json('/releases/' + str(release_id))
            release_identity(current, lock)
            require(current['draft'] is True and current['target_commitish'] == lock['targetCommit'],
                    'UI-draft-changed-before-upload; no-metadata-mutation')
            assets[name] = api.upload(release_id, name, candidate / name, expected)
            check_stored_asset(api, assets[name], expected)
    current = api.json('/releases/' + str(release_id))
    release_identity(current, lock)
    require(current['draft'] is True and current['target_commitish'] == lock['targetCommit'],
            'UI-draft-changed-before-receipt')
    return dict(formatVersion=1, repository=REPOSITORY, tag=lock['tag'], targetCommit=lock['targetCommit'],
                releaseId=release_id, draft=True, completeAssetSetVerified=True, publicationQualified=False,
                assets={name: dict(identities[name]) for name in sorted(identities)})


def publish(api, candidate, lock, pin):
    identities = verify_candidate(candidate, lock, pin)
    ref_path = '/git/ref/tags/' + quote(lock['tag'], safe='')
    ref = api.json(ref_path, missing=True)
    if ref is None:
        api.json('/git/refs', method='POST', value={'ref': 'refs/tags/' + lock['tag'], 'sha': lock['targetCommit']})
        ref = api.json(ref_path)
    require(ref['object']['type'] == 'commit' and ref['object']['sha'] == lock['targetCommit'], 'existing-tag-target-mismatch; tag-preserved')
    release = api.json('/releases/tags/' + quote(lock['tag'], safe=''), missing=True)
    if release is None:
        release = api.json('/releases', method='POST', value=dict(tag_name=lock['tag'], target_commitish=lock['targetCommit'],
                           name='Esteria server dependencies ' + lock['tag'], body=release_body(lock),
                           draft=True, prerelease=True, make_latest='false'))
    release_identity(release, lock)
    release_id = release['id']
    rows = api.json('/releases/' + str(release_id) + '/assets?per_page=100')
    assets = {item['name']: item for item in rows}
    require(len(assets) == len(rows) and set(assets).issubset(RELEASE_FILES), 'unexpected-existing-release-assets')
    def check_asset(name, row):
        expected = identities[name]
        require(row['state'] == 'uploaded' and row['size'] == expected['bytes'] and
                row.get('digest') == 'sha256:' + expected['sha256'], 'existing-asset-differs; no-overwrite')
        # Download actual stored bytes, rather than trusting size/digest metadata alone.
        with tempfile.TemporaryDirectory(prefix='esteria-release-verify-') as directory:
            api.download(API + '/releases/assets/' + str(row['id']), Path(directory) / name, expected)
    # Validate all existing assets before extending an owned draft.
    for name, row in assets.items():
        check_asset(name, row)
    for name, expected in identities.items():
        if name not in assets:
            require(release['draft'] is True, 'published-release-missing-assets; no-repair-or-overwrite')
            assets[name] = api.upload(release_id, name, candidate / name, expected)
            check_asset(name, assets[name])
    if release['draft']:
        release = api.json('/releases/' + str(release_id), method='PATCH', value={'draft': False, 'prerelease': True, 'make_latest': 'false'})
    require(release['draft'] is False and release['prerelease'] is True, 'release-not-published-as-prerelease')
    return dict(formatVersion=1, repository=REPOSITORY, tag=lock['tag'], targetCommit=lock['targetCommit'],
                releaseId=release_id, url=release['html_url'], githubImmutable=release.get('immutable'),
                publisherNeverOverwrites=True, assets={name: dict(identities[name], url=assets[name]['browser_download_url']) for name in sorted(identities)})


def fetch_published(api, output, lock, pin, include_sources=False, candidate=False):
    published = lock.get('published')
    require(isinstance(published, dict) and published.get('tag') == lock['tag'] and
            published.get('targetCommit') == lock['targetCommit'] and
            set(published.get('assets', {})) == RELEASE_FILES, 'durable-release-not-yet-recorded')
    require(not os.path.lexists(output), 'fetch-output-exists')
    output.mkdir(parents=True, mode=0o700)
    names = RELEASE_FILES if candidate else set(PACKAGE_FILES) | ({SOURCE_ZIP, SOURCE_MANIFEST} if include_sources else set())
    for name in sorted(names):
        row = published['assets'][name]
        expected = pin[PACKAGE_FILES[name]] if name in PACKAGE_FILES else (
            lock['artifactInputs']['sources'] if name == SOURCE_ZIP else row)
        require(row['bytes'] == expected['bytes'] and row['sha256'] == expected['sha256'] and
                row['url'] == 'https://github.com/' + REPOSITORY + '/releases/download/' + lock['tag'] + '/' + name,
                'durable-download-pin-mismatch')
        if name == SOURCE_MANIFEST:
            require(row['sha256'] == pin['sourceCompanion']['manifestSha256'] and row['bytes'] <= MAX_JSON,
                    'durable-source-manifest-pin-mismatch')
        api.download(row['url'], output / name, expected)
    provider.descriptor(output, pin)
    if candidate:
        verify_candidate(output, lock, pin)
    return dict(runtimeInputsVerified=True, sourceCompanionDownloaded=include_sources, androidRuntimeQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'download-inputs', 'stage', 'verify', 'publish', 'upload-draft', 'verify-published', 'fetch'))
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include-sources', action='store_true')
    parser.add_argument('--wait-seconds', type=int, default=0)
    args = parser.parse_args()
    lock, pin = load_lock()
    api = Github(os.environ.get('GITHUB_TOKEN'))
    if args.operation == 'prepare':
        if lock.get('published'):
            result = fetch_published(api, args.output, lock, pin, candidate=True)
        else:
            require(args.inputs is not None, 'prepare-requires-new-input-directory-before-first-publication')
            download_inputs(api, args.inputs, lock)
            result = stage(args.inputs, args.output, lock, pin)
    elif args.operation == 'download-inputs':
        download_inputs(api, args.output, lock); result = {'originalInputsDownloaded': True}
    elif args.operation == 'stage':
        require(args.inputs is not None, 'stage-requires-inputs'); result = stage(args.inputs, args.output, lock, pin)
    elif args.operation == 'verify':
        result = verify_candidate(args.output, lock, pin)
    elif args.operation in ('publish', 'upload-draft'):
        require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and
                os.environ.get('GITHUB_REF') == 'refs/heads/android/client-server' and api.token,
                'publication-requires-owned-development-branch-GitHub-Actions-context')
        require(args.inputs is not None and not args.output.exists(), 'publish-requires-candidate-and-new-receipt')
        result = (upload_draft if args.operation == 'upload-draft' else publish)(api, args.inputs, lock, pin)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(encoded(result))
    elif args.operation == 'verify-published':
        require(args.inputs is not None and not args.output.exists(), 'verify-published-requires-candidate-and-new-receipt')
        result = verify_published(api, args.inputs, lock, pin, args.wait_seconds)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(encoded(result))
    else:
        result = fetch_published(api, args.output, lock, pin, args.include_sources)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        # URLs from failed HTTP requests may contain signed credentials; do not echo them.
        message = str(error) if isinstance(error, ValueError) else type(error).__name__
        raise SystemExit('Dependency release failed: ' + message) from None
