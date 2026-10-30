#!/usr/bin/env python3
"""Prepare measured candidate/native fixture inputs without selecting an APK provider."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

try:
    from . import prepare_runtime as archives, provider_client_runtime as client
    from . import qualify_wine_arm64 as qualification
except ImportError:
    import prepare_runtime as archives, provider_client_runtime as client
    import qualify_wine_arm64 as qualification

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/wine-arm64/sources.lock.json'
FIXTURES = ('bin/Win/ARM64/WowClient64.exe', 'bin/Win/ARM64/XvidDecoder.dll',
            'bin/Win/ARM64/client-build.json', 'build/platform/Release/test_xvid_adapter.exe',
            'build/vulkan/Release/presentation_device.exe', 'build/vulkan/Release/texture_device.exe',
            'build/audio/Release/fmod_output_device.exe')
require = archives.require


def bridge_context(package, output):
    require(not os.path.lexists(output), 'candidate-bridge-context-exists')
    raw = (package / 'candidate-runtime.lock.json').read_bytes(); selected = json.loads(raw)
    require(selected.get('scope') == 'separate-native-arm64-wine-candidate', 'candidate-runtime-scope')
    archive = selected['packages']['wine-arm64']['archive']['sha256']
    shutil.copytree(ROOT / 'runtime/bridges', output, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    path = output / 'sources.lock.json'; lock = json.loads(path.read_bytes())
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    pinned = json.loads(LOCK.read_bytes())['qualificationReference']['bridgeInputLock']
    require(client.identity(path) == {key: pinned[key] for key in ('bytes', 'sha256')},
            'reference-bridge-input-lock-changed')
    require(lock['runtimeArchiveSha256'] == json.loads(LOCK.read_bytes())['oldProviderArchiveSha256'],
            'reference-bridge-runtime-changed')
    lock['runtimeArchiveSha256'] = archive
    path.write_text(json.dumps(lock, indent=2) + '\n')
    return dict(originalBridgeInputLockSha256=original, candidateBridgeInputLockSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                candidateRuntimeLockSha256=hashlib.sha256(raw).hexdigest(), runtimeArchiveSha256=archive,
                productionFilesChanged=False)


def fixtures(artifact, output):
    require(not os.path.lexists(output), 'candidate-client-fixtures-exist')
    lock = json.loads(LOCK.read_bytes()); pin = lock['clientQualification']
    require(pin == json.loads(client.PIN.read_bytes()), 'candidate-client-input-lock-changed')
    client.verify_identity(artifact, pin['artifact'])
    output.mkdir(parents=True)
    with archives.plain_file(artifact) as stream, client.checked_zip(stream, required=FIXTURES) as archive:
        for name in FIXTURES:
            member = archive.getinfo(name)
            require(0 < member.file_size <= 128 * 1024**2, 'candidate-fixture-bound')
            path = output / name; path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as incoming, path.open('xb') as outgoing:
                archives.hash_stream(incoming, member.file_size, outgoing)
    directory = output / 'bin/Win/ARM64'
    require(client.identity(directory / 'client-build.json')['sha256'] == pin['buildManifestSha256'],
            'candidate-client-manifest-pin')
    manifest, value = qualification.client_inputs(directory, output / 'build/platform/Release/test_xvid_adapter.exe')
    require(value['sourceRevision'] == pin['sourceRevision'] and value['buildId'] == pin['buildId'],
            'candidate-client-source-selection')
    for name in FIXTURES:
        if name.endswith('.exe'):
            qualification.pe_identity(output / name, False)
    return dict(sourceRevision=pin['sourceRevision'], originalArtifact=pin['artifact'], files={name: client.identity(output / name)
                for name in FIXTURES}, binaryFixturesOnly=True, runtimeProviderSelected=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-package', type=Path)
    parser.add_argument('--bridge-context', type=Path)
    parser.add_argument('--stage', type=Path)
    parser.add_argument('--client-artifact', type=Path)
    parser.add_argument('--client-output', type=Path)
    args = parser.parse_args(); result = {}
    if args.stage:
        require(args.runtime_package is not None, 'candidate-runtime-package-required')
        lock = json.loads((args.runtime_package / 'candidate-runtime.lock.json').read_bytes())
        require(lock.get('scope') == 'separate-native-arm64-wine-candidate', 'candidate-runtime-scope')
        result['preparedRuntime'] = archives.prepare(lock['packages']['wine-arm64'], args.runtime_package, args.stage)
    if args.bridge_context:
        require(args.runtime_package is not None, 'candidate-runtime-package-required')
        result['candidateBridge'] = bridge_context(args.runtime_package, args.bridge_context)
    if args.client_output:
        require(args.client_artifact is not None, 'candidate-client-artifact-required')
        result['clientFixtures'] = fixtures(args.client_artifact, args.client_output)
    require(result, 'candidate-preparation-operation-required')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
