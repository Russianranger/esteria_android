#!/usr/bin/env python3
"""Reuse exact successful Wine/runtime sources for a separately selected ARM64 client."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

try:
    from . import prepare_runtime as archives, provider_client_runtime as client
    from . import package_wine_arm64_candidate as runtime, qualify_wine_arm64 as qualification
    from . import verify_wine_arm64_sources as original_sources
    from .release_server_dependencies import Github, API
    from .fetch_android_wine_probe import successful_input
    from .package_server_content import publish_directory
    from .prepare_wine_arm64_candidate import FIXTURES
except ImportError:
    import prepare_runtime as archives, provider_client_runtime as client
    import package_wine_arm64_candidate as runtime, qualify_wine_arm64 as qualification
    import verify_wine_arm64_sources as original_sources
    from release_server_dependencies import Github, API
    from fetch_android_wine_probe import successful_input
    from package_server_content import publish_directory
    from prepare_wine_arm64_candidate import FIXTURES

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / 'runtime/wine-arm64-qualification'
RUNTIME_PIN = INPUTS / 'runtime-input.lock.json'
CLIENT_PIN = INPUTS / 'client-input.lock.json'
SOURCE_PREFIXES = ('wine-arm64-sources/', 'wine-arm64-bridge/corresponding-source/',
                   'wine-arm64-bridge/notices/', 'wine-arm64-bridge-context/', 'wine-arm64-client-inputs/')
RUNTIME_FILES = {'wine-arm64.tar.gz', 'wine-arm64.manifest.json', 'runtime.json', 'sources.lock.json',
                 'candidate-runtime.lock.json', 'package-build-receipt.json'}
require = archives.require


def pins():
    value = json.loads(client.small(RUNTIME_PIN))
    require(value.get('formatVersion') == 1 and value.get('scope') == 'measured-native-arm64-wine-host-candidate-inputs' and
            value.get('sourceBuildPassed') is True and value.get('originalNativeClientComponentGatesPassed') is True and
            re.fullmatch('[a-f0-9]{40}', value.get('sourceRevision', '')) and set(value.get('files', {})) == RUNTIME_FILES and
            value.get('sourcesPrefix') == 'wine-arm64-sources/', 'native-requalification-runtime-inputs')
    for name in ('androidQualified', 'gameplayQualified'):
        require(value.get(name) is False, 'native-requalification-input-overclaim')
    selected = json.loads(client.small(CLIENT_PIN))
    require(selected == json.loads(client.small(client.PIN)) and selected.get('formatVersion') == 1 and
            selected.get('scope') == 'measured-reconstructed-client-provider-inputs' and
            re.fullmatch('[a-f0-9]{40}', selected.get('sourceRevision', '')),
            'native-requalification-client-inputs-not-current-measured-inputs')
    return value, selected


def runtime_package(directory, pin):
    require({p.name for p in directory.iterdir()} == RUNTIME_FILES, 'native-requalification-runtime-inventory')
    for name, expected in pin['files'].items():
        client.verify_identity(directory / name, expected)
    raw = client.small(directory / 'runtime.json'); metadata, components = runtime.metadata(raw)
    require(client.small(directory / 'sources.lock.json') == runtime.LOCK.read_bytes(), 'native-requalification-build-source-lock')
    proof = json.loads(client.small(directory / 'package-build-receipt.json'))
    candidate_raw = client.small(directory / 'candidate-runtime.lock.json')
    candidate = json.loads(candidate_raw); package = candidate['packages']['wine-arm64']
    require(proof.get('scope') == 'packaged-source-built-native-arm64-wine-candidate' and
            proof.get('archiveReadBack') is True and proof.get('sourceCompanionRequired') is True and
            proof.get('sourceLockSha256') == hashlib.sha256(runtime.LOCK.read_bytes()).hexdigest() and
            proof.get('runtimeMetadataSha256') == hashlib.sha256(raw).hexdigest() and
            proof.get('candidateLockSha256') == hashlib.sha256(candidate_raw).hexdigest(), 'native-requalification-build-receipt')
    require(all(proof.get(flag) is False for flag in ('clientIncluded', 'androidQualified', 'arm64Qualified', 'gameplayQualified')),
            'native-requalification-build-overclaim')
    require(candidate.get('scope') == 'separate-native-arm64-wine-candidate' and package.get('marker') == metadata and
            package.get('components') == components and package.get('wineEnvironment') == {'WINE_ANDROID_PRIVATE_PE_COPY': '1'} and
            package.get('archive') == proof.get('archive') == dict(file='wine-arm64.tar.gz', **pin['files']['wine-arm64.tar.gz']),
            'native-requalification-candidate-binding')
    return proof, candidate


def extract_runtime(path, output, pin):
    output.mkdir(mode=0o700)
    with archives.plain_file(path) as incoming, client.checked_zip(incoming, required=RUNTIME_FILES) as archive:
        require({item.filename for item in archive.infolist()} == RUNTIME_FILES, 'native-requalification-runtime-zip-inventory')
        for name, expected in pin['files'].items():
            item = archive.getinfo(name)
            require(item.file_size == expected['bytes'], 'native-requalification-runtime-member-size')
            with archive.open(item) as source, (output / name).open('xb') as target:
                require(archives.hash_stream(source, item.file_size, target) == expected['sha256'], 'native-requalification-runtime-member-hash')
    return runtime_package(output, pin)


def extract_sources(path, output, pin):
    output.mkdir(mode=0o700)
    total = 0
    with archives.plain_file(path) as incoming, client.checked_zip(incoming, required=(),
            maximum_bytes=4*1024**3, maximum_entries=4096, maximum_directory=2*1024**2) as archive:
        for item in archive.infolist():
            mode = stat.S_IFMT(item.external_attr >> 16)
            require(not item.is_dir() and mode in (0, stat.S_IFREG) and
                    any(item.filename.startswith(prefix) for prefix in SOURCE_PREFIXES) and
                    0 <= item.file_size <= 2*1024**3, 'native-requalification-source-member-type-or-scope')
            total += item.file_size
            require(total <= 2*pin['sourcesArtifact']['bytes'], 'native-requalification-source-expansion-bound')
            target = output / item.filename; archives.directory(target.parent, create=True)
            with archive.open(item) as source, target.open('xb') as stream:
                archives.hash_stream(source, item.file_size, stream)
    root = output / pin['sourcesPrefix'].rstrip('/')
    require(root.is_dir() and not root.is_symlink(), 'native-requalification-original-source-root')
    return root


def fetch(output):
    pin, _ = pins(); require(not os.path.lexists(output), 'native-requalification-input-output-exists')
    archives.directory(output.parent, create=True)
    stage = Path(tempfile.mkdtemp(prefix='.wine-native-inputs-', dir=output.parent))
    api = Github(os.environ.get('GITHUB_TOKEN'))
    try:
        run = api.json('/actions/runs/' + str(pin['workflowRun']))
        require(run.get('path') == '.github/workflows/wine-arm64-candidate.yml', 'native-requalification-producer-workflow')
        for key, field, name in (('artifact', 'artifactId', 'runtime.zip'), ('sourcesArtifact', 'sourcesArtifactId', 'sources.zip')):
            successful_input(api, pin['workflowRun'], pin['sourceRevision'], pin[field], pin[key])
            api.download(API + '/actions/artifacts/' + str(pin[field]) + '/zip', stage / name, pin[key])
        extract_runtime(stage / 'runtime.zip', stage / 'runtime-package', pin)
        original = extract_sources(stage / 'sources.zip', stage / 'source-export', pin)
        source_proof = original_sources.verify(original, stage / 'runtime-package/runtime.json', pin['sourceRevision'])
        require(source_proof['allOriginalSourcesReadBack'] is True, 'native-requalification-original-sources-incomplete')
        proof = dict(formatVersion=1, scope='verified-retained-native-arm64-runtime-and-full-sources-only',
                     runtimeInput=pin, sourceReadback=source_proof, runtimeRecompiled=False,
                     selectedClientExecuted=False, androidQualified=False, gameplayQualified=False)
        (stage / 'input-evidence.json').write_bytes(client.encoded(proof))
        publish_directory(stage, output); archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists(): shutil.rmtree(stage)


def prepare(runtime_inputs, artifact, output):
    pin, selected = pins(); require(not os.path.lexists(output), 'native-requalification-preparation-exists')
    _, candidate = runtime_package(runtime_inputs / 'runtime-package', pin)
    client.verify_identity(artifact, selected['artifact'])
    output.mkdir(parents=True, mode=0o700)
    fixtures = output / 'client-fixtures'; fixtures.mkdir()
    with archives.plain_file(artifact) as incoming, client.checked_zip(incoming, required=FIXTURES) as archive:
        for name in FIXTURES:
            member = archive.getinfo(name)
            require(0 < member.file_size <= 128*1024**2, 'native-requalification-client-fixture-bound')
            target = fixtures / name; target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open('xb') as stream: archives.hash_stream(source, member.file_size, stream)
    client_dir = fixtures / 'bin/Win/ARM64'
    require(client.identity(client_dir / 'client-build.json')['sha256'] == selected['buildManifestSha256'],
            'native-requalification-client-manifest')
    _, measured = qualification.client_inputs(client_dir, fixtures / 'build/platform/Release/test_xvid_adapter.exe')
    require(measured['sourceRevision'] == selected['sourceRevision'] and measured['buildId'] == selected['buildId'],
            'native-requalification-client-selection')
    for name in FIXTURES:
        if name.endswith('.exe'): qualification.pe_identity(fixtures / name, False)
    context = output / 'bridge-context'
    shutil.copytree(ROOT / 'runtime/bridges', context, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    bridge_path = context / 'sources.lock.json'; original_raw = bridge_path.read_bytes(); bridge = json.loads(original_raw)
    archive_pin = candidate['packages']['wine-arm64']['archive']
    reference = json.loads(runtime.LOCK.read_bytes())
    require(bridge['runtimeArchiveSha256'] in (reference['oldProviderArchiveSha256'], archive_pin['sha256']),
            'native-requalification-bridge-template-has-unexpected-runtime')
    bridge['runtimeArchiveSha256'] = archive_pin['sha256']; bridge_path.write_bytes(client.encoded(bridge))
    prepared = archives.prepare(candidate['packages']['wine-arm64'], runtime_inputs / 'runtime-package', output / 'runtime')
    proof = dict(scope='separate-client-on-retained-arm64-wine-preparation-only', runtimeInput=pin,
                 selectedClientInput=selected, preparedRuntime=prepared,
                 originalBridgeTemplateSha256=hashlib.sha256(original_raw).hexdigest(),
                 candidateBridgeInputLockSha256=client.identity(bridge_path)['sha256'],
                 clientFiles={name: client.identity(fixtures / name) for name in FIXTURES},
                 runtimeRecompiled=False, productionPinsChanged=False, androidQualified=False, gameplayQualified=False)
    (output / 'preparation.json').write_bytes(client.encoded(proof))
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    get = sub.add_parser('fetch'); get.add_argument('--output', type=Path, required=True)
    use = sub.add_parser('prepare')
    for name in ('runtime-inputs', 'client-artifact', 'output'): use.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = fetch(args.output) if args.command == 'fetch' else prepare(args.runtime_inputs, args.client_artifact, args.output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
