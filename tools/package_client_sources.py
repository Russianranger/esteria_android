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


def build(source, xvid, output):
    source_bytes = client.small(client.SOURCE_LOCK);lock = client.fetch_sources.load_lock(client.SOURCE_LOCK)
    pin_bytes = client.small(client.PIN);pin = json.loads(pin_bytes);source_pin = lock['sources']['client']
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
            target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(client.small(path))
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
    args = parser.parse_args();print(json.dumps(build(args.client_source, args.xvid_source, args.output), indent=2))


if __name__ == '__main__':main()
