#!/usr/bin/env python3
"""Retain the exact client tree, upstream Xvid source and integration recipe beside binaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

try:
    from . import provider_client_runtime as client
except ImportError:
    import provider_client_runtime as client

README = b'''Corresponding source companion for the reconstructed Esteria ARM64 client.
client-source.tar is the complete pinned Git tree (including original notices,
build scripts, reconstructed engine code and historical bundled dependencies).
xvidcore-1.3.7.tar.gz is the unchanged hash-pinned upstream source used by ARM64.
cmake/XvidPortable.cmake in client-source.tar contains every Xvid adaptation;
Tools/XvidDecoder contains the adapter and exports. No private signing material,
imported game data, database or saves are included. Existing licenses remain.
Read docs/android-arm64-platform.md and .github/workflows/arm64-client.yml in
the client tree for Windows ARM64 toolchain and exact build/protocol options.
For offline Xvid source selection unpack its original archive and set CMake
FETCHCONTENT_SOURCE_DIR_XVID137 to its extracted directory; the build patches
only its build-tree copy. Microsoft toolchain/SDK redistribution is not included.
integration-recipe retains this source packager, binary-provider tool and their
exact input locks. This companion is separate from the installable APK assets.
Retain both this archive and its receipt with any redistributed binary package.
It establishes retained source inputs, not Android or gameplay qualification.
'''


def input_selection(source_lock=None, client_input_lock=None):
    client.require((source_lock is None) == (client_input_lock is None), 'paired-client-source-inputs-required')
    source_path = Path(source_lock) if source_lock is not None else client.SOURCE_LOCK
    pin_path = Path(client_input_lock) if client_input_lock is not None else client.PIN
    source_bytes = client.small(source_path);lock = client.fetch_sources.load_lock(source_path)
    client.require(client.encoded(json.loads(source_bytes)) == client.encoded(lock), 'client-source-input-changed')
    pin_bytes = client.small(pin_path);pin = json.loads(pin_bytes)
    selected = None
    if source_lock is not None:
        # Override both raw inputs together. A fixed committed recipe can then
        # retain newly measured inputs without a self-referential commit pin.
        source_pin = lock['sources']['client']
        client.require(type(lock.get('schema')) is int and lock['schema'] == 1 and
            client.encoded(lock['compatibility']) == client.encoded(dict(base_client_build=12340, extended_limits=True,
                container_slots=254, quest_log_slots=25, client_class_capacity=32)), 'client-selected-protocol-mismatch')
        client.require(set(pin) == {'formatVersion', 'scope', 'sourceRevision', 'workflowRun', 'buildId',
            'artifactId', 'artifact', 'buildManifestSha256', 'androidRuntimeQualified'} and
            type(pin.get('formatVersion')) is int and pin['formatVersion'] == 1 and
            pin.get('scope') == 'measured-reconstructed-client-provider-inputs' and pin.get('androidRuntimeQualified') is False and
            type(pin.get('sourceRevision')) is str and re.fullmatch('[0-9a-f]{40}', pin['sourceRevision']) and
            type(pin.get('workflowRun')) is int and pin['workflowRun'] > 0 and type(pin.get('artifactId')) is int and pin['artifactId'] > 0 and
            type(pin.get('buildId')) is str and re.fullmatch(str(pin['workflowRun']) + r'\.[1-9][0-9]*', pin['buildId']) and
            type(pin.get('artifact')) is dict and set(pin['artifact']) == {'bytes', 'sha256'} and
            type(pin['artifact'].get('bytes')) is int and
            22 <= pin['artifact']['bytes'] <= 512 * 1024**2 and
            type(pin['artifact'].get('sha256')) is str and re.fullmatch('[0-9a-f]{64}', pin['artifact']['sha256']) and
            type(pin.get('buildManifestSha256')) is str and re.fullmatch('[0-9a-f]{64}', pin['buildManifestSha256']),
            'client-selected-measured-input-mismatch')
        client.require(source_pin == dict(url='https://github.com/Russianranger/wowdecomp_esteria.git',
            commit=pin['sourceRevision'], branch='android/arm64-port', submodules={}, patches=[]),
            'client-selected-source-revision-mismatch')
        selected = {name: dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) for name, raw in (
            ('sources.lock.json', source_bytes), ('runtime/client/android-provider.lock.json', pin_bytes))}
    return source_bytes, lock, pin_bytes, pin, selected


def build(source, xvid, output, source_lock=None, client_input_lock=None):
    source_bytes, lock, pin_bytes, pin, selected = input_selection(source_lock, client_input_lock)
    source_pin = lock['sources']['client']
    client.require(source_pin['commit'] == pin['sourceRevision'] and not source_pin['patches'] and
                   not source_pin['submodules'], 'client-source-companion-pin-mismatch')
    client.fetch_sources.verify_checkout(source, source_pin, [])
    recipe = client.source_blob(source, pin['sourceRevision'], 'cmake/XvidPortable.cmake').decode()
    url = re.search(r'URL (https://downloads\.xvid\.com/downloads/xvidcore-1\.3\.7\.tar\.gz)\s', recipe)
    digest = re.search(r'URL_HASH SHA256=([0-9a-f]{64})\s', recipe)
    client.require(url is not None and digest is not None, 'pinned-client-xvid-source-required')
    output = Path(os.path.abspath(output));client.archives.directory(output.parent, create=True)
    client.require(not os.path.lexists(output), 'client-source-companion-output-exists')
    stage = Path(tempfile.mkdtemp(prefix='.client-sources-', dir=output.parent))
    try:
        tree = stage / 'tree';tree.mkdir();package = stage / 'package';package.mkdir()
        with client.archives.plain_file(xvid) as incoming, (tree / 'xvidcore-1.3.7.tar.gz').open('xb') as outgoing:
            before = os.fstat(incoming.fileno());client.require(0 < before.st_size <= 16 * 1024**2, 'xvid-source-size-limit')
            actual = client.archives.hash_stream(incoming, before.st_size, outgoing)
            client.require(actual == digest.group(1), 'xvid-source-hash-mismatch')
        with (tree / 'client-source.tar').open('xb') as stream:
            subprocess.run(['git', 'archive', '--format=tar', pin['sourceRevision']], cwd=source,
                           stdout=stream, check=True, timeout=120)
        client.require((tree / 'client-source.tar').stat().st_size <= 256 * 1024**2, 'client-source-archive-size-limit')
        recipes = tree / 'integration-recipe';recipes.mkdir()
        helpers = ['prepare_runtime.py', 'fetch_sources.py', 'package_server_content.py', 'manifest_server_content.py',
                   'manifest_server_modules.py', 'verify_server_build.py', 'provider_client_runtime.py']
        for path in (client.PIN, client.SOURCE_LOCK, client.archives.DEFAULT_LOCK,
                     *(client.ROOT / 'tools' / name for name in helpers), Path(__file__).resolve(), client.ROOT / 'LICENSE'):
            relative = path.relative_to(client.ROOT);target = recipes / relative
            data = source_bytes if path == client.SOURCE_LOCK else pin_bytes if path == client.PIN else client.small(path)
            target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(data)
        (tree / 'README.txt').write_bytes(README)
        inventory = {str(path.relative_to(tree)): client.identity(path) for path in sorted(tree.rglob('*')) if path.is_file()}
        archive = package / 'client-corresponding-source.tar.gz'
        client.write_archive(archive, tree, inventory);client.audit(archive, inventory)
        receipt = dict(formatVersion=1, scope='retained-reconstructed-client-source-inputs', source=source_pin,
                       sourceLockSha256=hashlib.sha256(source_bytes).hexdigest(),
                       clientArtifact=pin['artifact'], clientBuildId=pin['buildId'], inputLockSha256=hashlib.sha256(pin_bytes).hexdigest(),
                       xvid=dict(url=url.group(1), sha256=actual, bytes=before.st_size),
                       archive=client.identity(archive), members=inventory, archiveReadBack=True,
                       androidRuntimeQualified=False, gameplayQualified=False)
        if selected is not None:receipt['selectedInputs'] = selected
        (package / 'source-receipt.json').write_bytes(client.encoded(receipt))
        client.publish_directory(package, output);client.archives.sync_directory(output.parent)
        return receipt
    finally:
        shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-source', type=Path, required=True)
    parser.add_argument('--xvid-source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-lock', type=Path, help='explicit source-lock input; requires --client-input-lock')
    parser.add_argument('--client-input-lock', type=Path, help='explicit measured client input; requires --source-lock')
    args = parser.parse_args();print(json.dumps(build(args.client_source, args.xvid_source, args.output,
        args.source_lock, args.client_input_lock), indent=2))


if __name__ == '__main__':main()
