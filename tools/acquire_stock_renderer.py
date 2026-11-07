"""Build only the selected renderer provider from its exact published inputs."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from tools import fetch_sources, prepare_runtime, provider_client_runtime as client


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'runtime/client'
REPOSITORY = 'https://github.com/Russianranger/wowdecomp_esteria'


def xvid_source(cache, cohort):
    # A complete source-owned cohort already contains the original upstream tarball.
    # Authenticate its selected member against the independent Xvid SHA before use.
    pin = json.loads((CLIENT / 'dependency-release.lock.json').read_bytes())['xvid']
    name = 'xvidcore-1.3.7.tar.gz'
    package = cohort / 'client-corresponding-source.tar.gz'
    if not package.exists():
        return prepare_runtime.fetch(dict(pin, file=name), cache)
    cache = prepare_runtime.directory(cache, create=True)
    target = cache / name
    if os.path.lexists(target):
        client.verify_identity(target, pin)
        return target
    with prepare_runtime.plain_file(package) as source, prepare_runtime.bounded_tar(source, dict(
            entries=64, fileBytes=256 << 20, pathBytes=4096)) as archive:
        for entry in archive:
            if entry.name != name:
                continue
            prepare_runtime.require(entry.isfile() and entry.size == pin['bytes'], 'renderer-xvid-source-member')
            with archive.extractfile(entry) as incoming, tempfile.NamedTemporaryFile(dir=cache) as tmp:
                prepare_runtime.require(prepare_runtime.hash_stream(incoming, pin['bytes'], tmp) == pin['sha256'],
                                        'renderer-xvid-source-digest')
                tmp.flush()
                os.fsync(tmp.fileno())
                os.link(tmp.name, target)
            return target
    raise ValueError('Xvid source missing from retained client source package')


def acquire(output, cohort):
    source_lock = CLIENT / 'stock-renderer-sources.lock.json'
    build_lock = CLIENT / 'stock-renderer-build.lock.json'
    contract = CLIENT / 'renderer-compatibility.json'
    source = fetch_sources.load_lock(source_lock)['sources']['client']
    build = json.loads(build_lock.read_bytes())
    revision = build['sourceRevision']
    pairing = json.loads(contract.read_bytes())
    if (not re.fullmatch(r'[a-f0-9]{40}', revision) or source['url'] != REPOSITORY + '.git' or
            source['commit'] != revision or revision != pairing['executableRevision']):
        raise ValueError('Published renderer build and selected source must match')
    output.mkdir(parents=True, exist_ok=False)
    fetch_sources.fetch('client', source, output / 'source', ROOT, offline=False)
    checkout = output / 'source/client'
    # The reviewed renderer commit is a child of the prepared source. Make
    # both trees available for the factory's exact diff and ancestry checks.
    subprocess.run(['git', 'fetch', '--depth', '2', '--no-tags', 'origin', revision], cwd=checkout, check=True)
    tag = 'stock-client-arm64-' + revision
    url = f'{REPOSITORY}/releases/download/{tag}/client-ARM64-{revision}.zip'
    original = prepare_runtime.fetch(dict(build['artifact'], file='client-original.zip', url=url), output / 'cache')
    xvid = xvid_source(output / 'cache', cohort)
    factory = [sys.executable, '-m', 'tools.stock_renderer_provider']
    common = ['--client-source', checkout, '--source-lock', source_lock, '--client-input-lock', build_lock,
              '--source-package', output / 'source-companion']
    subprocess.run([*factory, 'source', *common, '--xvid-source', xvid], cwd=ROOT, check=True)
    subprocess.run([*factory, 'build', *common, '--cohort-inputs', cohort, '--artifact', original,
                    '--provider', output / 'provider', '--compatibility', contract], cwd=ROOT, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cohort-inputs', required=True, type=Path)
    args = parser.parse_args()
    acquire(args.output.resolve(), args.cohort_inputs.resolve(strict=True))
