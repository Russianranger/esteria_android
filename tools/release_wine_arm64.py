#!/usr/bin/env python3
"""Stage exact source-owned ARM64 Wine inputs and upload only to an owned UI draft."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

try:
    from . import dependency_publication as publication, wine_arm64_requalification as retained
except ImportError:
    import dependency_publication as publication, wine_arm64_requalification as retained

ROOT = Path(__file__).resolve().parents[1]
shared = publication.transport
archives = retained.archives
require = archives.require
encoded = shared.encoded
identity = shared.identity
SCOPE = 'source-owned-arm64-wine-inputs-write-once-prerelease'
SOURCE_ZIP = 'wine-arm64-corresponding-sources.zip'
INPUT_LOCK = 'runtime-input.lock.json'
PAYLOAD_FILES = retained.RUNTIME_FILES | {SOURCE_ZIP, INPUT_LOCK, 'NOTICE.txt'}
RELEASE_FILES = PAYLOAD_FILES | {'release-manifest.json', 'SHA256SUMS'}
PRODUCER = '681b2e9f30b19e94bf8e8de44f67fedba5033c8a'
PRODUCER_RUN = 41057900330
TAG = 'deps-wine-arm64-681b2e9-c0e13ed15a69'
INPUT_IDENTITY = dict(bytes=2084, sha256='e5fd2de4935cbf10372cc18c23dec387478867a624d984b568e09a4a0b0515c0')
INPUT_CANONICAL_SHA256 = 'a037a35d1f365fb32c552965ed3bd1287f5d1282719cd7c546ea055500bc28d0'
RECIPE_ROOTS = {'tools/release_wine_arm64.py', 'tests/test_wine_release.py',
    'runtime/wine-arm64-publication/README.md', 'runtime/wine-arm64/sources.lock.json',
    'runtime/wine-arm64/record_runtime.py', 'runtime/wine-arm64/capture_toolchain_sources.py',
    'runtime/wine-probe/apply_adaptations.py', 'runtime/wine-probe/android-private-pe-copy.patch',
    'tools/owned_process_group.py'}
NOTICE = b'''Source-owned Debian12 native ARM64 Wine runtime inputs only.
Original producer 681b2e9f30b19e94bf8e8de44f67fedba5033c8a, workflow41057900330.
The six original package files and full original corresponding-source ZIP are
retained unchanged. The ZIP includes the full Debian runtime/build source union,
original Wine/FEX/toolchain archives, selected toolchain Git trees, adaptations,
integration recipe and original notices. Preserve these sources with the runtime.
Wine is LGPL-2.1-or-later; FEX, toolchain and Debian components retain their
individual original notices. Nothing here relicenses an upstream component.
Native Linux component fixtures are separate evidence. This release does not
qualify Android execution, device graphics/audio, game login or gameplay.
No APK, game data, accounts, database, initialized prefix or saved state.
Historical f036 runtime and dependency releases remain separate and unchanged.
'''


def bytes_identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def checked_input(raw):
    require(bytes_identity(raw) == INPUT_IDENTITY, 'wine-release-original-runtime-input-changed')
    value = json.loads(raw)
    require(hashlib.sha256(encoded(value)).hexdigest() == INPUT_CANONICAL_SHA256 and
            value.get('sourceRevision') == PRODUCER and value.get('workflowRun') == PRODUCER_RUN and
            value.get('sourceBuildPassed') is True and value.get('originalNativeClientComponentGatesPassed') is True and
            value.get('androidQualified') is False and value.get('gameplayQualified') is False and
            set(value['files']) == retained.RUNTIME_FILES, 'wine-release-original-producer-mismatch')
    return value


def git_blob(revision, name):
    require(re.fullmatch('[a-f0-9]{40}', revision or '') and archives.member_path(name) == name,
            'wine-release-recipe-revision-or-path')
    spec = revision + ':' + name
    size = int(subprocess.check_output(['git', 'cat-file', '-s', spec], cwd=ROOT, timeout=30))
    require(0 < size <= 2 * 1024**2, 'wine-release-recipe-file-bound')
    raw = subprocess.check_output(['git', 'show', spec], cwd=ROOT, timeout=30)
    require(len(raw) == size, 'wine-release-recipe-file-changed')
    return raw


def recipe_inputs(revision):
    """Pin imported repository Python code plus the explicit dynamic resources."""
    require(re.fullmatch('[a-f0-9]{40}', revision or ''), 'wine-release-recipe-revision-or-path')
    roster = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', revision, '--', 'tools'], cwd=ROOT, timeout=30)
    require(len(roster) <= 2 * 1024**2, 'wine-release-recipe-roster-bound')
    tracked = set(roster.decode().splitlines())
    pending = set(RECIPE_ROOTS); result = {}; total = 0
    while pending:
        name = min(pending); pending.remove(name)
        raw = git_blob(revision, name); total += len(raw)
        require(total <= 16 * 1024**2 and len(result) < 128, 'wine-release-recipe-total-bound')
        require(identity(ROOT / name) == bytes_identity(raw), 'wine-release-executing-recipe-changed:' + name)
        result[name] = bytes_identity(raw)
        if not name.endswith('.py'): continue
        tree = ast.parse(raw, filename=name)
        for node in ast.walk(tree):
            candidates = []
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                candidates = [node.module.split('.')[0]] if node.module else [item.name for item in node.names]
            # Scripts retain direct-import fallbacks for execution outside a package.
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                candidates = [node.module.split('.')[0]]
            elif isinstance(node, ast.Import):
                candidates = [item.name.split('.')[0] for item in node.names]
            for module in candidates:
                dependency = 'tools/' + module + '.py'
                if dependency in tracked and dependency not in result:
                    pending.add(dependency)
    return dict(sorted(result.items()))


def write_new(path, raw):
    archives.directory(path.parent, create=True)
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    archives.sync_directory(path.parent)


def make_lock(target, runtime_input_lock, output):
    require(not os.path.lexists(output), 'wine-release-lock-output-exists')
    pin = checked_input(retained.client.small(runtime_input_lock))
    value = dict(formatVersion=1, repository=shared.REPOSITORY, scope=SCOPE,
        tag=TAG, targetCommit=target,
        runtimeInputFile=INPUT_IDENTITY, runtimeInput=pin, recipeInputs=recipe_inputs(target))
    write_new(output, encoded(value))
    return value


def load_lock(path):
    value = shared.small_json(path)
    require(type(value) is dict and set(value) == {'formatVersion', 'repository', 'scope', 'tag', 'targetCommit',
                'runtimeInputFile', 'runtimeInput', 'recipeInputs'} and type(value.get('formatVersion')) is int and
            value['formatVersion'] == 1 and value['repository'] == shared.REPOSITORY and value['scope'] == SCOPE and
            re.fullmatch('[a-f0-9]{40}', value.get('targetCommit', '')) and
            value['tag'] == TAG,
            'wine-release-lock-scope')
    pin = value['runtimeInput']
    require(value['runtimeInputFile'] == INPUT_IDENTITY and
            hashlib.sha256(encoded(pin)).hexdigest() == INPUT_CANONICAL_SHA256 and
            pin['sourceRevision'] == PRODUCER and pin['workflowRun'] == PRODUCER_RUN,
            'wine-release-original-producer-mismatch')
    require(value['recipeInputs'] == recipe_inputs(value['targetCommit']), 'wine-release-recipe-input-mismatch')
    return value


def release_body(lock):
    return ('Dependency-only archival prerelease. Source-owned Debian12 ARM64 Wine runtime and complete original source inputs.\n\n'
        'Original producer `' + PRODUCER + '`, workflow `' + str(PRODUCER_RUN) + '`. Packaging recipe `' +
        lock['targetCommit'] + '`. Runtime archive `c0e13ed15a69fa72541684ac5cef49d71d5d95ee494146bc6e40d11b6977ab46`.\n\n'
        'The six original package files and full original corresponding-source ZIP are retained unchanged. '
        'The complete ZIP is read back and its Debian/Wine/FEX/toolchain sources and original notices are verified before staging/upload. '
        'Native Linux fixtures are separate evidence; Android execution, device graphics/audio, game login and gameplay remain unqualified. '
        'No APK, imported game data, accounts, database or saves. Historical f036 releases remain unchanged.\n\n'
        'Assets and tag are write-once. This uploader only adds missing exact assets to an existing owned UI draft; '
        'it never creates/finalizes a release, moves tags, replaces assets or changes repository settings.\n')


def copy_verified(source, target, pin):
    with archives.plain_file(source) as incoming, target.open('xb') as outgoing:
        require(os.fstat(incoming.fileno()).st_size == pin['bytes'] and
                archives.hash_stream(incoming, pin['bytes'], outgoing) == pin['sha256'],
                'wine-release-copy-identity:' + source.name)
        outgoing.flush(); os.fsync(outgoing.fileno())


def validate_payload(path, lock):
    """Read every source ZIP member and verify the full original source closure."""
    pin = checked_input(retained.client.small(path / INPUT_LOCK))
    require(pin == lock['runtimeInput'], 'wine-release-input-lock-mismatch')
    require(identity(path / SOURCE_ZIP) == pin['sourcesArtifact'] and
            0 < pin['sourcesArtifact']['bytes'] < 2 * 1024**3, 'wine-release-original-source-zip-mismatch')
    # The original checker expects a directory containing exactly the six raw
    # package files. Confined hardlinks create that view without unpacking Wine.
    with tempfile.TemporaryDirectory(prefix='.wine-release-readback-', dir=path.parent) as temporary:
        at = Path(temporary); package = at / 'runtime-package'; package.mkdir()
        for name in sorted(retained.RUNTIME_FILES):
            with archives.plain_file(path / name): pass
            os.link(path / name, package / name, follow_symlinks=False)
        retained.runtime_package(package, pin)
        original = retained.extract_sources(path / SOURCE_ZIP, at / 'sources', pin)
        proof = retained.original_sources.verify(original, package / 'runtime.json', pin['sourceRevision'])
        require(proof.get('allOriginalSourcesReadBack') is True and proof.get('completeIntegrationTreeReadBack') is True and
                all(proof.get(key) is False for key in ('androidQualified', 'gameClientQualified', 'gameplayQualified')),
                'wine-release-original-source-closure-incomplete')
        # Preserve the producer's receipt format as well as its immutable ZIP.
        require(bytes_identity((json.dumps(proof, indent=2) + '\n').encode()) == pin['sourceReadbackReceipt'],
                'wine-release-original-source-receipt-mismatch')
    return {name: identity(path / name) for name in sorted(PAYLOAD_FILES)}


def manifest(lock, identities):
    pin = lock['runtimeInput']
    return dict(formatVersion=1, scope=SCOPE, repository=shared.REPOSITORY, tag=lock['tag'],
        targetCommit=lock['targetCommit'], releaseLockSha256=bytes_identity(encoded(lock))['sha256'],
        sourceRevision=pin['sourceRevision'], workflowRun=pin['workflowRun'],
        originalRuntimeArtifact=dict(id=pin['artifactId'], **pin['artifact']),
        originalSourcesArtifact=dict(id=pin['sourcesArtifactId'], **pin['sourcesArtifact']),
        runtimeInputFile=lock['runtimeInputFile'], recipeInputs=lock['recipeInputs'], files=identities,
        originalFilesPreserved=True, entireSourceZipReadBack=True, completeOriginalSourcesVerified=True,
        androidQualified=False, gameplayQualified=False)


def checksums(identities):
    return ''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(identities.items())).encode()


def verify_envelope(path, lock, identities):
    require(set(identities) == PAYLOAD_FILES, 'wine-release-payload-identity-set')
    identities = dict(identities)
    require({item.name for item in path.iterdir()} == RELEASE_FILES, 'wine-release-file-set-mismatch')
    require(retained.client.small(path / 'NOTICE.txt') == NOTICE, 'wine-release-notice-mismatch')
    require(retained.client.small(path / 'release-manifest.json') == encoded(manifest(lock, identities)),
            'wine-release-manifest-mismatch')
    identities['release-manifest.json'] = identity(path / 'release-manifest.json')
    require(retained.client.small(path / 'SHA256SUMS') == checksums(identities), 'wine-release-checksums-mismatch')
    identities['SHA256SUMS'] = identity(path / 'SHA256SUMS')
    return dict(sorted(identities.items()))


def verify_candidate(path, lock):
    path = archives.directory(path)
    require({item.name for item in path.iterdir()} == RELEASE_FILES, 'wine-release-file-set-mismatch')
    return verify_envelope(path, lock, validate_payload(path, lock))


def stage(inputs, runtime_input_lock, output, lock):
    require(not os.path.lexists(output), 'wine-release-output-exists')
    require(checked_input(retained.client.small(runtime_input_lock)) == lock['runtimeInput'], 'wine-release-input-lock-mismatch')
    inputs = archives.directory(inputs); archives.directory(output.parent, create=True)
    pin = lock['runtimeInput']
    at = Path(tempfile.mkdtemp(prefix='.wine-release-', dir=output.parent))
    try:
        for name, expected in pin['files'].items(): copy_verified(inputs / 'runtime-package' / name, at / name, expected)
        copy_verified(inputs / 'sources.zip', at / SOURCE_ZIP, pin['sourcesArtifact'])
        copy_verified(runtime_input_lock, at / INPUT_LOCK, lock['runtimeInputFile'])
        write_new(at / 'NOTICE.txt', NOTICE)
        identities = validate_payload(at, lock)
        write_new(at / 'release-manifest.json', encoded(manifest(lock, identities)))
        checksum_records = dict(identities, **{'release-manifest.json': identity(at / 'release-manifest.json')})
        write_new(at / 'SHA256SUMS', checksums(checksum_records))
        # Read back the generated envelope without repeating the full source
        # extraction already completed for these exact staged payload bytes.
        result = verify_envelope(at, lock, identities)
        retained.publish_directory(at, output); archives.sync_directory(output.parent)
        return result
    finally:
        if at.exists(): shutil.rmtree(at)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('lock', 'body', 'stage', 'verify', 'upload-draft', 'verify-published'))
    parser.add_argument('--release-lock', type=Path)
    parser.add_argument('--runtime-input-lock', type=Path)
    parser.add_argument('--target-commit')
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--wait-seconds', type=int, default=0)
    args = parser.parse_args()
    if args.operation == 'lock':
        require(args.target_commit and args.runtime_input_lock is not None and args.output is not None,
                'wine-release-lock-inputs-required')
        result = make_lock(args.target_commit, args.runtime_input_lock, args.output)
    else:
        require(args.release_lock is not None, 'explicit-wine-release-lock-required')
        lock = load_lock(args.release_lock)
        if args.operation == 'body': print(release_body(lock), end=''); return
        require(args.output is not None, 'wine-release-output-required')
        if args.operation == 'stage':
            require(args.inputs is not None and args.runtime_input_lock is not None, 'wine-release-stage-inputs-required')
            result = stage(args.inputs, args.runtime_input_lock, args.output, lock)
        elif args.operation == 'verify': result = verify_candidate(args.output, lock)
        else:
            require(args.inputs is not None and not os.path.lexists(args.output), 'wine-release-candidate-and-new-receipt-required')
            api = publication.Github(os.environ.get('GITHUB_TOKEN'))
            policy = publication.DraftPublication(lock, release_body(lock), lambda path: verify_candidate(path, lock))
            if args.operation == 'upload-draft':
                require(os.environ.get('GITHUB_REPOSITORY') == shared.REPOSITORY and
                    os.environ.get('GITHUB_REF') == 'refs/heads/android/client-server' and api.token,
                    'publication-requires-owned-development-branch-GitHub-Actions-context')
                result = policy.upload_draft(api, args.inputs)
            else: result = policy.verify_published(api, args.inputs, args.wait_seconds)
            write_new(args.output, encoded(result))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        message = str(error) if isinstance(error, ValueError) else type(error).__name__
        raise SystemExit('ARM64 Wine dependency release failed: ' + message) from None
