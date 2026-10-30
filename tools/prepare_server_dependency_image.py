#!/usr/bin/env python3
"""Prepare an offline Docker context from the exact published server rootfs.

This tool never runs Docker, a guest executable, APT or a database. It verifies
the complete source companion outside the context and copies only the measured
fresh dependency archive. Image construction/execution remain separate gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

try:
    from . import release_server_dependencies as release
    from . import provider_server_runtime as provider
    from .package_server_content import publish_directory
except ImportError:
    import release_server_dependencies as release
    import provider_server_runtime as provider
    from package_server_content import publish_directory

archives = provider.archives
require = archives.require
ARCHIVE = 'server-runtime-arm64.tar.gz'
CONTEXT_FILES = {'Dockerfile', ARCHIVE}


def dockerfile(archive_sha256):
    require(isinstance(archive_sha256, str) and re.fullmatch('[0-9a-f]{64}', archive_sha256),
            'invalid-runtime-archive-sha256')
    return ('FROM scratch\n'
            'ADD server-runtime-arm64.tar.gz /\n'
            'ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8\n'
            'LABEL io.esteria.server-runtime.sha256="' + archive_sha256 + '"\n'
            'CMD ["/usr/bin/python3", "--version"]\n').encode('ascii')


def validate_inputs(inputs):
    lock, pin = release.load_lock()
    require(lock.get('published', {}).get('assets'), 'published-dependency-release-required')
    identities = release.verify_candidate(inputs, lock, pin)
    # Bind the candidate metadata itself to the reviewed public release, not
    # only to its internally consistent per-payload hashes.
    for name, expected in lock['published']['assets'].items():
        require(identities[name] == {'bytes': expected['bytes'], 'sha256': expected['sha256']},
                'published-release-asset-mismatch:' + name)
    descriptor = provider.descriptor(inputs, pin)  # Full tar graph/ELF/readback.
    metadata = release.small_json(inputs / 'server-runtime.json')
    _, source_proof = release.validate_sources(inputs / release.SOURCE_ZIP, lock, pin, metadata)
    require(pin['archive']['file'] == ARCHIVE and descriptor['serverIncluded'] is False,
            'not-a-fresh-server-dependency-runtime')
    proof = dict(formatVersion=1, scope='verified-server-dependency-image-context-only',
                 releaseTag=lock['tag'], releaseTarget=lock['targetCommit'],
                 releaseManifest=identities['release-manifest.json'], archive=pin['archive'],
                 runtimeMetadata=pin['runtimeMetadata'], sourceLock=pin['sourceLock'],
                 sourceCompanion=identities[release.SOURCE_ZIP], sourceInventory=source_proof,
                 architecture='arm64', expectedMysqlSqlVersion=metadata['expectedMysqlSqlVersion'],
                 components=metadata['images'], completeSourceCompanionReverified=True,
                 archiveGraphAndComponentsReverified=True, dockerImageBuilt=False,
                 guestExecuted=False, databaseInitialized=False, serverIncluded=False,
                 androidRuntimeQualified=False, gameplayQualified=False)
    return pin, proof


def write_context(inputs, output, pin, proof):
    """Called only after input verification; rehash the copied archive before publication."""
    require(not os.path.lexists(output), 'dependency-image-output-exists')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        context = stage / 'context'; context.mkdir(mode=0o700)
        with archives.plain_file(inputs / ARCHIVE) as source, (context / ARCHIVE).open('xb') as target:
            shutil.copyfileobj(source, target, archives.BUFFER)
            target.flush(); os.fsync(target.fileno())
        provider.verify_file(context / ARCHIVE, pin['archive'])
        recipe = dockerfile(pin['archive']['sha256'])
        with (context / 'Dockerfile').open('xb') as target:
            target.write(recipe); target.flush(); os.fsync(target.fileno())
        require({item.name for item in context.iterdir()} == CONTEXT_FILES, 'unexpected-dependency-context-files')
        receipt = dict(proof, dockerfile=dict(bytes=len(recipe), sha256=hashlib.sha256(recipe).hexdigest()),
                       contextFiles=sorted(CONTEXT_FILES), sourceCompanionCopiedIntoContext=False)
        with (stage / 'context-receipt.json').open('xb') as target:
            target.write(release.encoded(receipt)); target.flush(); os.fsync(target.fileno())
        archives.sync_directory(context); archives.sync_directory(stage)
        publish_directory(stage, output); archives.sync_directory(output.parent)
        return receipt
    finally:
        if stage.exists(): shutil.rmtree(stage)


def prepare(inputs, output):
    inputs = archives.directory(Path(os.path.abspath(inputs)))
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(inputs != output and inputs not in output.parents and output not in inputs.parents,
            'dependency-context-and-inputs-must-be-disjoint')
    require(not os.path.lexists(output), 'dependency-image-output-exists')
    pin, proof = validate_inputs(inputs)
    return write_context(inputs, output, pin, proof)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True, help='Complete exact nine-file published release directory')
    parser.add_argument('--output', type=Path, required=True, help='New output directory; context/ is its only Docker input')
    args = parser.parse_args()
    print(json.dumps(prepare(args.inputs, args.output), indent=2))


if __name__ == '__main__':
    main()
