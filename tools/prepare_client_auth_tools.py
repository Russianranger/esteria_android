#!/usr/bin/env python3
"""Stage exact signed-index packages/sources for an offline test-only image.

No resolver, APT, dpkg, guest executable or database runs on this host. The
selection preserves the original signed APT solver result plus the explicit
single-package diagnostic addition. Alternate transport may deliver only the
identical signed-index bytes; the base packages cannot be replaced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import urllib.error
import urllib.request

try:
    from . import prepare_runtime as archives
    from .package_server_content import publish_directory
    from .verify_client_auth_tools import encoded, identity, require
except ImportError:
    import prepare_runtime as archives
    from package_server_content import publish_directory
    from verify_client_auth_tools import encoded, identity, require

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/client-auth/tool-inputs.lock.json'
MAX_FILE = 256 * 1024**2
MAX_TOTAL = 1024**3
ORIGINS = ('https://ports.ubuntu.com/ubuntu-ports/',
           'https://snapshot.ubuntu.com/ubuntu/20261029T000000Z/')


def file_record(row):
    filename = row.get('filename', '')
    path = PurePosixPath(filename)
    require(isinstance(filename, str) and path.as_posix() == filename and
            len(path.parts) >= 4 and path.parts[0] == 'pool' and
            all(part not in ('.', '..') and re.fullmatch(r'[A-Za-z0-9+_.~-]+', part)
                for part in path.parts), 'invalid-tool-pool-path')
    require(type(row.get('bytes')) is int and 0 < row['bytes'] <= MAX_FILE and
            re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')), 'invalid-tool-file-identity')


def load_lock(path=LOCK):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 1024**2, 'tool-lock-bound')
    lock = json.loads(path.read_text())
    require(lock.get('formatVersion') == 1 and lock.get('scope') == 'compiled-client-auth-test-tools',
            'tool-lock-contract')
    require(lock.get('selectionComplete') is True and lock.get('missing') == [] and
            lock.get('snapshot') == '20261029T000000Z', 'tool-selection-incomplete')
    packages = lock.get('packages', [])
    require(len(packages) == 33 and len({r['name'] for r in packages}) == 33 and
            {'git', 'binutils', 'iproute2', 'strace'} <= {r['name'] for r in packages}, 'tool-selection-contract')
    diagnostic = lock.get('diagnosticAddition', {})
    require(diagnostic.get('scope') == 'single-signed-index-package-with-no-base-replacement' and
            diagnostic.get('name') == 'strace' and diagnostic.get('version') == '6.8-0ubuntu2' and
            diagnostic.get('originalSolverPackages') == 32 and
            diagnostic.get('dependency') == dict(name='libc6', required='>= 2.38', installed='2.39-0ubuntu8.9',
                                                  boundByBaseDpkgStatus=True), 'tool-diagnostic-selection-contract')
    tracer = next(row for row in packages if row['name'] == 'strace')
    require(tracer['version'] == diagnostic['version'] and tracer['architecture'] == 'arm64' and
            tracer['dependencyFields'] == {'Depends': 'libc6 (>= 2.38)'}, 'tool-diagnostic-package-contract')
    sources = lock.get('sources', [])
    source_keys = {(r['name'], r['version']) for r in sources}
    require(len(source_keys) == len(sources) and
            {(r['source']['name'], r['source']['version']) for r in packages} == source_keys,
            'tool-source-selection-contract')
    all_files = []
    for row in packages:
        file_record(row)
        require(row['architecture'] in ('arm64', 'all') and row['filename'].endswith('.deb'),
                'tool-package-architecture')
        all_files.append(row)
    for source in sources:
        require(source['files'] and any(r['filename'].endswith('.dsc') for r in source['files']),
                'tool-corresponding-source-missing')
        for row in source['files']:
            file_record(row)
            all_files.append(row)
    require(len({r['filename'] for r in all_files}) == len(all_files) and
            len({Path(r['filename']).name for r in packages}) == len(packages) and
            sum(r['bytes'] for r in all_files) <= MAX_TOTAL, 'tool-input-set-bound')
    for name in ('metadata', 'dpkgStatus'):
        require(type(lock['base'][name].get('bytes')) is int and
                re.fullmatch('[0-9a-f]{64}', lock['base'][name].get('sha256', '')), 'tool-base-contract')
    return lock


def fetch(row, cache, download):
    target = cache / (row['sha256'] + '-' + Path(row['filename']).name)
    expected = {k: row[k] for k in ('bytes', 'sha256')}
    if os.path.lexists(target):
        require(identity(target) == expected, 'cached-tool-input-mismatch')
        return target
    require(download, 'missing-tool-input:' + Path(row['filename']).name)
    errors = []
    for origin in ORIGINS:
        descriptor, name = tempfile.mkstemp(prefix='.' + target.name + '-', dir=cache)
        partial = Path(name)
        try:
            digest = hashlib.sha256(); count = 0
            with os.fdopen(descriptor, 'wb') as output:
                descriptor = None
                with urllib.request.urlopen(origin + row['filename'], timeout=45) as source:
                    while True:
                        block = source.read(131072)
                        if not block:
                            break
                        count += len(block)
                        require(count <= row['bytes'], 'downloaded-tool-input-too-large')
                        digest.update(block); output.write(block)
                    output.flush(); os.fsync(output.fileno())
            require(dict(bytes=count, sha256=digest.hexdigest()) == expected, 'downloaded-tool-input-mismatch')
            # Never overwrite a concurrently published cache entry.
            os.link(partial, target); partial.unlink()
            return target
        except (OSError, ValueError) as error:
            errors.append(type(error).__name__)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if partial.exists(): partial.unlink()
    raise ValueError('exact-tool-input-unavailable:' + Path(row['filename']).name + ':' + ','.join(errors))


def recipe():
    path = ROOT / 'runtime/client-auth/Dockerfile'
    require(path.is_file() and not path.is_symlink() and path.stat().st_size < 16384, 'tool-recipe-bound')
    return path.read_bytes()


def prepare(cache, output, download=False):
    cache = archives.directory(Path(os.path.abspath(cache)), create=True)
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and cache != output and
            cache not in output.parents and output not in cache.parents, 'tool-output-overlap-or-exists')
    lock = load_lock()
    package_inputs = [(row, fetch(row, cache, download)) for row in lock['packages']]
    source_inputs = [(row, fetch(row, cache, download)) for source in lock['sources'] for row in source['files']]
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '-', dir=output.parent))
    try:
        context = stage / 'context'; context.mkdir(mode=0o700)
        debs = context / 'debs'; debs.mkdir(mode=0o700)
        sources = stage / 'sources'; sources.mkdir(mode=0o700)
        for rows, directory in ((package_inputs, debs), (source_inputs, sources)):
            for row, source in rows:
                target = directory / Path(row['filename']).name
                with archives.plain_file(source) as input_file, target.open('xb') as output_file:
                    shutil.copyfileobj(input_file, output_file, 131072)
                    output_file.flush(); os.fsync(output_file.fileno())
                require(identity(target) == {k: row[k] for k in ('bytes', 'sha256')}, 'copied-tool-input-mismatch')
        (context / 'tool-inputs.lock.json').write_bytes(encoded(lock))
        (context / 'Dockerfile').write_bytes(recipe())
        verifier = ROOT / 'tools/verify_client_auth_tools.py'
        shutil.copyfile(verifier, context / 'verify.py')
        proof = dict(formatVersion=1, scope='auth-test-tool-context-only', lock=identity(LOCK),
                     solver=lock['solver'], base=lock['base'], packageCount=len(package_inputs),
                     sourceFileCount=len(source_inputs), sourceFiles={p.name: identity(p) for p in sources.iterdir()},
                     recipe=identity(context / 'Dockerfile'), verifier=identity(context / 'verify.py'),
                     correspondingSourceRetained=True, sourcesCopiedIntoImage=False,
                     dependencySolverExecuted=False, dockerImageBuilt=False, guestExecuted=False,
                     androidRuntimeQualified=False, gameplayQualified=False)
        (stage / 'context-receipt.json').write_bytes(encoded(proof))
        for path in (context / 'tool-inputs.lock.json', context / 'Dockerfile',
                     context / 'verify.py', stage / 'context-receipt.json'):
            with path.open('rb') as stream: os.fsync(stream.fileno())
        for directory in (debs, sources, context, stage): archives.sync_directory(directory)
        publish_directory(stage, output)
        archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.cache, args.output, args.download), indent=2))


if __name__ == '__main__':
    main()
