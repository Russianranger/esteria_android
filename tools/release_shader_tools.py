#!/usr/bin/env python3
"""Preserve exact offline shader inputs; never publish an APK or game content."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import zipfile

try:
    from . import dependency_publication as publication, provider_shader_tools as provider
except ImportError:
    import dependency_publication as publication, provider_shader_tools as provider

shared = publication.transport
require = shared.require
ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/shaders/dependency-release.lock.json'
ARCHIVE = 'shader-tools-arm64.tar.gz'
INPUT_LOCK = 'shader-tools-input-lock.json'
DESCRIPTOR = 'shader-tools-provider.json'
PAYLOAD_FILES = {ARCHIVE, INPUT_LOCK, DESCRIPTOR, 'bundle.json', 'NOTICE.txt'}
RELEASE_FILES = PAYLOAD_FILES | {'release-manifest.json', 'SHA256SUMS'}
NOTICE = b'''Esteria offline shader tool inputs only. No APK, game data or saved state.
The archive preserves all 70 measured translator/compiler/helper/source/notice
files, including complete original glslang, SPIRV-Tools and SPIRV-Headers source
archives, exact client Git blobs and compiler build recipe. Original notices are
retained; this does not assign a new license to the reconstructed client source.
Native Linux ARM64 compiler fixtures passed. The original build's separate
no-GPU driver probe failed; that does not qualify or disqualify this narrower
compiler fixture. Android compilation, imported-game shaders and gameplay remain
unqualified. Complete Wine rootfs and compiler build-tool source closure are not
claimed by this selected archive. Its input lock retains their source identities.
After publication and recorded public hashes, normal builds require no Actions
artifact URL. Release assets are never overwritten by this publisher.
'''


def load_lock():
    lock = shared.small_json(LOCK)
    require(lock.get('formatVersion') == 1 and lock.get('repository') == shared.REPOSITORY and
            lock.get('scope') == 'shader-tools-inputs-write-once-prerelease' and
            re.fullmatch(r'deps-shader-tools-[a-z0-9-]+', lock['tag']) and
            re.fullmatch('[0-9a-f]{40}', lock['targetCommit']), 'invalid-shader-release-scope')
    pin = provider.load_pin()
    require(provider.bundle.identity(provider.LOCK)['sha256'] == lock['providerLockSha256'], 'shader-provider-lock-changed')
    require(lock['clientRevision'] == pin['clientRevision'] and
            lock['compilerIntegrationRevision'] == pin['compilerIntegrationRevision'] and
            lock['workflowRun'] == pin['artifact']['runId'] and
            all(lock['artifact'][k] == pin['artifact'][k] for k in ('id', 'bytes', 'sha256')) and
            lock['artifact']['name'] == 'unqualified-adreno-turnip-linux-arm64-' + pin['compilerIntegrationRevision'] and
            lock['artifactPrefix'] == 'out/turnip/payload/' and lock['originalRunConclusion'] == 'failure',
            'shader-original-artifact-pin-mismatch')
    require(type(lock['archive']['bytes']) is int and 0 < lock['archive']['bytes'] <= provider.LIMITS['fileBytes'] and
            re.fullmatch('[0-9a-f]{64}', lock['archive']['sha256']), 'shader-release-archive-pin-invalid')
    return lock, pin


def release_body(lock):
    return ('Dependency-only archival prerelease. Exact ARM64 glibc shader compiler and source tools; no APK or game content.\n\n'
            'Provider packaging revision: `' + lock['targetCommit'] + '`. Client translator revision: `' +
            lock['clientRevision'] + '`. Original compiler build: `' + lock['compilerIntegrationRevision'] +
            '`, workflow `' + str(lock['workflowRun']) + '`.\n\n'
            'The archive retains all 70 selected files, including complete original glslang, SPIRV-Tools and SPIRV-Headers '
            'sources, original notices, exact translator Git blobs and compiler recipe. Native compiler validation passed; '
            'the original run\'s separate no-GPU driver probe failed. Android/compiler execution with imported game data and '
            'gameplay remain unqualified. Complete Wine rootfs and compiler build-tool source closure are outside this selected archive.\n\n'
            'Assets and tag are write-once: this publisher never replaces them. Verify SHA256SUMS and release-manifest.json. '
            'GitHub-enforced immutability is recorded separately; this workflow does not change repository settings.\n')


def manifest(lock, identities):
    return dict(formatVersion=1, scope=lock['scope'], repository=shared.REPOSITORY, targetCommit=lock['targetCommit'],
                tag=lock['tag'], clientRevision=lock['clientRevision'], compilerIntegrationRevision=lock['compilerIntegrationRevision'],
                workflowRun=lock['workflowRun'], originalArtifact=lock['artifact'], providerLockSha256=lock['providerLockSha256'],
                files=identities, nativeCompilerFixtureQualified=True, androidRuntimeQualified=False,
                gameAssetShadersQualified=False, gameplayQualified=False)


def verify_candidate(path, lock, pin):
    path = provider.archives.directory(path)
    require({item.name for item in path.iterdir()} == RELEASE_FILES, 'shader-release-file-set-mismatch')
    require(shared.identity(path / ARCHIVE) == lock['archive'], 'shader-release-archive-identity-mismatch')
    require(provider.bundle.small(path / INPUT_LOCK, 65536) == provider.bundle.small(provider.LOCK, 65536), 'shader-release-input-lock-changed')
    values = provider.verify_archive(path / ARCHIVE, pin)
    expected = provider.descriptor(path / ARCHIVE, pin)
    require(provider.bundle.small(path / DESCRIPTOR, 65536) == provider.encoded(expected), 'shader-release-descriptor-mismatch')
    require(provider.bundle.small(path / 'bundle.json', 65536) == values['provenance/bundle.json'], 'shader-release-bundle-mismatch')
    require(provider.bundle.small(path / 'NOTICE.txt') == NOTICE, 'shader-release-notice-mismatch')
    identities = {name: shared.identity(path / name) for name in sorted(PAYLOAD_FILES)}
    require(provider.bundle.small(path / 'release-manifest.json') == shared.encoded(manifest(lock, identities)), 'shader-release-manifest-mismatch')
    identities['release-manifest.json'] = shared.identity(path / 'release-manifest.json')
    sums = ''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(identities.items())).encode()
    require(provider.bundle.small(path / 'SHA256SUMS') == sums, 'shader-release-checksums-mismatch')
    identities['SHA256SUMS'] = shared.identity(path / 'SHA256SUMS')
    return dict(sorted(identities.items()))


def publish_tree(candidate, output):
    for directory, _, _ in os.walk(candidate, topdown=False): provider.bundle.sync_directory(directory)
    provider.publish_directory(candidate, output); provider.bundle.sync_directory(output.parent)


def stage(prepared_provider, output, lock, pin):
    require(not os.path.lexists(output), 'shader-release-output-exists')
    provider.archives.directory(output.parent, create=True)
    provider.verify(prepared_provider)
    assets = prepared_provider / 'assets' / provider.ASSETS
    with tempfile.TemporaryDirectory(prefix='.shader-release-', dir=output.parent) as temporary:
        candidate = Path(temporary) / 'candidate'; candidate.mkdir(mode=0o700)
        provider.bundle.copy(assets / provider.ARCHIVE, candidate / ARCHIVE, lock['archive'])
        provider.bundle.write(candidate / INPUT_LOCK, provider.bundle.small(provider.LOCK, 65536))
        provider.bundle.write(candidate / DESCRIPTOR, provider.bundle.small(assets / 'provider.json', 65536))
        provider.bundle.write(candidate / 'bundle.json', provider.bundle.small(assets / 'bundle.json', 65536))
        provider.bundle.write(candidate / 'NOTICE.txt', NOTICE)
        identities = {name: shared.identity(candidate / name) for name in sorted(PAYLOAD_FILES)}
        provider.bundle.write(candidate / 'release-manifest.json', shared.encoded(manifest(lock, identities)))
        identities['release-manifest.json'] = shared.identity(candidate / 'release-manifest.json')
        provider.bundle.write(candidate / 'SHA256SUMS', ''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(identities.items())).encode())
        result = verify_candidate(candidate, lock, pin); publish_tree(candidate, output); return result


def selected_originals(pin):
    """Only files consumed by the exact-source packager; no broad ZIP extraction."""
    selected = {'bin/glslangValidator': pin['files'][provider.COMPILER],
                'turnip-build.json': pin['files']['provenance/turnip-build.json'],
                'shader-tool-check/qualification.json': pin['files']['provenance/shader-tool-qualification.json']}
    for name, row in pin['files'].items():
        if name.startswith('provenance/build-recipe/'):
            selected['corresponding-source/build-recipe/' + name.removeprefix('provenance/build-recipe/')] = row
        elif name.startswith('corresponding-source/'):
            selected['corresponding-source/original-archives/' + name.removeprefix('corresponding-source/')] = row
        elif name.startswith('notices/') and name != 'notices/ESTERIA-GPL-3.0': selected[name] = row
    require(len(selected) <= 128 and sum(row['bytes'] for row in selected.values()) <= 32 << 20, 'shader-original-selection-limit')
    return selected


def extract_original(artifact, destination, lock, pin):
    require(shared.identity(artifact) == {k: lock['artifact'][k] for k in ('bytes', 'sha256')}, 'shader-original-artifact-identity')
    require(not os.path.lexists(destination), 'shader-original-extract-output-exists')
    destination.mkdir(mode=0o700)
    selected = selected_originals(pin); prefix = lock['artifactPrefix']
    with provider.archives.plain_file(artifact) as incoming, provider.checked_zip(incoming, {prefix + n for n in selected},
            maximum_bytes=512 << 20, maximum_entries=2048) as archive:
        for name, row in sorted(selected.items()):
            item = archive.getinfo(prefix + name)
            require(stat.S_ISREG(item.external_attr >> 16) and item.file_size == row['bytes'], 'shader-original-member-type-or-size')
            target = destination / name; target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(); remaining = row['bytes']
            with archive.open(item) as source, target.open('xb') as output:
                while remaining:
                    raw = source.read(min(remaining, 65536)); require(raw, 'shader-original-member-truncated')
                    output.write(raw); digest.update(raw); remaining -= len(raw)
                require(not source.read(1), 'shader-original-member-grew'); output.flush(); os.fsync(output.fileno())
            require(digest.hexdigest() == row['sha256'], 'shader-original-member-identity')
            target.chmod(0o755 if name == 'bin/glslangValidator' else 0o644)


def stage_original(artifact, output, client, compiler, lock, pin):
    require(not os.path.lexists(output), 'shader-release-output-exists')
    require(client is not None and compiler is not None, 'exact-client-and-compiler-checkouts-required')
    provider.archives.directory(output.parent, create=True)
    with tempfile.TemporaryDirectory(prefix='.shader-original-', dir=output.parent) as temporary:
        at = Path(temporary); extract_original(artifact, at / 'payload', lock, pin)
        provider.bundle.build(at / 'bundle', client, pin['clientRevision'], at / 'payload',
                              pin['compilerBuildSha256'], compiler, pin['compilerIntegrationRevision'])
        provider.build(at / 'bundle', at / 'provider')
        return stage(at / 'provider', output, lock, pin)


def download_original(api, path, lock):
    expected = lock['artifact']; run = api.json('/actions/runs/' + str(lock['workflowRun']))
    # The run failed its independent driver gate. The measured compiler receipt
    # and strict native shader fixture are required by stage_original regardless.
    require(run['head_sha'] == lock['compilerIntegrationRevision'] and run['status'] == 'completed' and
            run['conclusion'] == lock['originalRunConclusion'] and run['head_branch'] == 'android/client-server',
            'shader-original-workflow-provenance-mismatch')
    row = api.json('/actions/artifacts/' + str(expected['id']))
    require(row['name'] == expected['name'] and row['size_in_bytes'] == expected['bytes'] and
            row.get('digest') == 'sha256:' + expected['sha256'] and row['expired'] is False and
            row['workflow_run']['id'] == lock['workflowRun'] and row['workflow_run']['head_sha'] == lock['compilerIntegrationRevision'],
            'shader-original-artifact-unavailable-or-mismatched')
    api.download(shared.API + '/actions/artifacts/' + str(expected['id']) + '/zip', path, expected)


def fetch(api, output, lock, pin):
    published = lock.get('published')
    require(isinstance(published, dict) and published.get('repository') == shared.REPOSITORY and
            published.get('tag') == lock['tag'] and published.get('targetCommit') == lock['targetCommit'] and
            set(published.get('assets', {})) == RELEASE_FILES, 'durable-shader-release-not-yet-recorded')
    require(not os.path.lexists(output), 'shader-fetch-output-exists')
    provider.archives.directory(output.parent, create=True)
    with tempfile.TemporaryDirectory(prefix='.shader-fetch-', dir=output.parent) as temporary:
        candidate = Path(temporary) / 'candidate'; candidate.mkdir(mode=0o700)
        for name, expected in sorted(published['assets'].items()):
            url = 'https://github.com/' + shared.REPOSITORY + '/releases/download/' + lock['tag'] + '/' + name
            require(expected['url'] == url and type(expected['bytes']) is int and 0 < expected['bytes'] <= (32 << 20 if name == ARCHIVE else 65536),
                    'shader-durable-download-pin-mismatch')
            api.download(url, candidate / name, expected)
        result = verify_candidate(candidate, lock, pin); publish_tree(candidate, output); return result


def export_provider(candidate, output, lock, pin):
    verify_candidate(candidate, lock, pin)
    require(not os.path.lexists(output), 'shader-provider-export-output-exists')
    provider.archives.directory(output.parent, create=True)
    with tempfile.TemporaryDirectory(prefix='.shader-provider-export-', dir=output.parent) as temporary:
        tree = Path(temporary) / 'provider'; assets = tree / 'assets' / provider.ASSETS; assets.mkdir(parents=True)
        provider.bundle.copy(candidate / ARCHIVE, assets / provider.ARCHIVE, lock['archive'])
        provider.bundle.write(assets / 'provider.json', provider.bundle.small(candidate / DESCRIPTOR, 65536))
        provider.bundle.write(assets / 'bundle.json', provider.bundle.small(candidate / 'bundle.json', 65536))
        provider.bundle.write(assets / 'NOTICE.txt', provider.NOTICE)
        result = provider.verify(tree); publish_tree(tree, output); return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'stage', 'stage-original', 'verify', 'body', 'upload-draft', 'verify-published', 'fetch', 'export-provider'))
    for name in ('inputs', 'output', 'client-source', 'compiler-source'): parser.add_argument('--' + name, type=Path)
    parser.add_argument('--wait-seconds', type=int, default=0)
    args = parser.parse_args(); lock, pin = load_lock()
    if args.operation == 'body': print(release_body(lock), end=''); return
    require(args.output is not None, 'output-required')
    api = publication.Github(os.environ.get('GITHUB_TOKEN'))
    policy = publication.DraftPublication(lock, release_body(lock), lambda path: verify_candidate(path, lock, pin))
    if args.operation == 'prepare':
        if lock.get('published'): result = fetch(api, args.output, lock, pin)
        else:
            require(args.inputs is not None and not os.path.lexists(args.inputs), 'fresh-original-input-path-required')
            provider.archives.directory(args.inputs.parent, create=True)
            download_original(api, args.inputs, lock)
            result = stage_original(args.inputs, args.output, args.client_source, args.compiler_source, lock, pin)
    elif args.operation == 'stage':
        require(args.inputs is not None, 'provider-input-required'); result = stage(args.inputs, args.output, lock, pin)
    elif args.operation == 'stage-original':
        require(args.inputs is not None, 'artifact-input-required')
        result = stage_original(args.inputs, args.output, args.client_source, args.compiler_source, lock, pin)
    elif args.operation == 'verify': result = verify_candidate(args.output, lock, pin)
    elif args.operation == 'fetch': result = fetch(api, args.output, lock, pin)
    elif args.operation == 'export-provider':
        require(args.inputs is not None, 'candidate-input-required'); result = export_provider(args.inputs, args.output, lock, pin)
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
        raise SystemExit('Shader dependency release failed: ' + message) from None
