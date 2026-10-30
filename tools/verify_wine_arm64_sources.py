#!/usr/bin/env python3
"""Read back exact candidate runtime/build, toolchain, Wine and FEX originals."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

try:
    from . import prepare_runtime as archives, package_wine_arm64_candidate as runtime
    from .release_server_dependencies import validate_dsc
except ImportError:
    import prepare_runtime as archives, package_wine_arm64_candidate as runtime
    from release_server_dependencies import validate_dsc

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/wine-arm64/sources.lock.json'
require = archives.require


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def identity(path):
    with archives.plain_file(path) as stream:
        return dict(bytes=os.fstat(stream.fileno()).st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def small(path, limit=2*1024**2):
    with archives.plain_file(path) as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, 'candidate-source-metadata-limit')
    return data


def checked(path, pin):
    require(identity(path) == {key: pin[key] for key in ('bytes', 'sha256')}, 'candidate-original-source-identity:' + path.name)


def inventory(directory):
    result = set()
    for path in directory.rglob('*'):
        require(not path.is_symlink(), 'candidate-source-link-refused')
        if path.is_file():
            result.add(str(path.relative_to(directory)))
        else:
            require(path.is_dir(), 'candidate-source-type')
    require(len(result) <= 16384, 'candidate-source-file-count')
    return result


def verify(directory, runtime_metadata, revision):
    require(re.fullmatch('[a-f0-9]{40}', revision or ''), 'candidate-source-revision')
    directory = archives.directory(directory)
    raw = small(runtime_metadata); metadata, _ = runtime.metadata(raw)
    lock_raw = LOCK.read_bytes(); lock = json.loads(lock_raw)
    require(small(directory / 'wine/runtime.json') == raw and small(directory / 'debian/runtime.json') == raw and
            small(directory / 'debian/sources.lock.json') == lock_raw, 'candidate-source-wrapper-selection')
    recorder = module('candidate_source_recorder', ROOT / 'runtime/wine-arm64/record_runtime.py')
    build_raw = small(directory / 'wine/build-packages.tsv', 131072)
    selected = recorder.source_inventory(recorder.package_inventory(build_raw.decode()) + metadata['packages'])
    manifest = json.loads(small(directory / 'debian/SOURCE-MANIFEST.json'))
    require(manifest.get('scope') == 'installed-debian-runtime-and-wine-build-corresponding-sources' and
            manifest.get('formatVersion') == 1 and manifest.get('sourcePackages') == selected and
            manifest.get('sourceLockSha256') == hashlib.sha256(lock_raw).hexdigest() and
            manifest.get('runtimeManifestSha256') == hashlib.sha256(raw).hexdigest(), 'candidate-debian-source-provenance')
    rows = manifest.get('files', []); files = {row['file']: row for row in rows}
    require(0 < len(rows) == len(files) <= 2048 and
            sum(row['bytes'] for row in rows) == manifest.get('fileBytes') <= 8 * 1024**3,
            'candidate-debian-source-inventory')
    descriptors = set()
    for name, row in files.items():
        require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9.+_~:-]*', name) and set(row) == {'file', 'bytes', 'sha256'},
                'candidate-debian-source-name')
        checked(directory / 'debian' / name, row)
        if name.endswith('.dsc'):
            pair = validate_dsc(small(directory / 'debian' / name), files)
            require(pair not in descriptors, 'candidate-duplicate-source-descriptor'); descriptors.add(pair)
    require(descriptors == {(row['package'], row['version']) for row in selected}, 'candidate-debian-source-closure')
    require(inventory(directory / 'debian') == set(files) | {'SOURCE-MANIFEST.json', 'runtime.json', 'sources.lock.json'},
            'candidate-debian-source-extra-or-missing')
    original_files = {pin['file'] for pin in (lock['wine']['sourceArchive'], lock['fex']['archive'], lock['toolchain']['archive'])}
    for pin in (lock['wine']['sourceArchive'], lock['fex']['archive'], lock['toolchain']['archive']):
        checked(directory / 'wine' / pin['file'], pin)
    license_raw = small(directory / 'wine/Wine-COPYING.LIB')
    require(hashlib.sha256(license_raw).hexdigest() == lock['wine']['licenseFileSha256'], 'candidate-wine-license')
    adapt = module('candidate_source_adaptations', ROOT / 'runtime/wine-probe/apply_adaptations.py')
    _, retained = adapt.inputs(lock, directory / 'wine/android-private-pe-copy')
    require(inventory(directory / 'wine/android-private-pe-copy') == set(retained), 'candidate-adaptation-source-extra')
    fex_notices = json.loads(small(directory / 'wine/fex-notices/NOTICE-MANIFEST.json'))
    require(0 < len(fex_notices) <= 4096, 'candidate-fex-notice-count')
    for name, pin in fex_notices.items():
        require(archives.member_path(name) == name, 'candidate-fex-notice-path')
        checked(directory / 'wine/fex-notices' / name, pin)
    checked(directory / 'wine/fex-notices/LICENSE', lock['licenses']['fex-license'])
    require(inventory(directory / 'wine/fex-notices') == set(fex_notices) | {'NOTICE-MANIFEST.json'}, 'candidate-fex-notice-extra')
    toolchain_metadata = json.loads(small(directory / 'wine/toolchain-metadata.json'))
    require(toolchain_metadata.get('archive') == lock['toolchain']['archive'] and
            toolchain_metadata.get('llvmRevisionCorroborated') == lock['toolchain']['sourceRefs'][0]['revision'],
            'candidate-toolchain-binary-selection')
    for name, pin in toolchain_metadata['bundledNotices'].items():
        require(archives.member_path(name) == name, 'candidate-toolchain-notice-path')
        checked(directory / 'wine/toolchain-notices' / name, pin)
    require(all(toolchain_metadata['bundledNotices'].get(name) == pin for name, pin in lock['toolchain']['bundledNotices'].items()) and
            inventory(directory / 'wine/toolchain-notices') == set(toolchain_metadata['bundledNotices']), 'candidate-toolchain-notice-extra')
    capture = module('candidate_toolchain_source_capture', ROOT / 'runtime/wine-arm64/capture_toolchain_sources.py')
    toolchain_sources = capture.verify_output(lock, directory / 'wine/toolchain-sources')
    wine_allowed = original_files | {'Wine-COPYING.LIB', 'build-packages.tsv', 'wine-build-config.log',
        'runtime.json', 'fex-arm64ec-CMakeCache.txt', 'fex-aarch64-CMakeCache.txt', 'toolchain-metadata.json'}
    wine_allowed |= {'android-private-pe-copy/' + name for name in retained}
    for name in ('fex-notices', 'toolchain-notices', 'toolchain-sources'):
        wine_allowed |= {name + '/' + item for item in inventory(directory / 'wine' / name)}
    require(inventory(directory / 'wine') == wine_allowed, 'candidate-wine-source-extra-or-missing')
    require(small(directory / 'integration-revision.txt') == (revision + '\n').encode(), 'candidate-integration-revision')
    original = subprocess.check_output(['git', 'archive', '--format=tar', revision], cwd=ROOT, timeout=30)
    require(len(original) <= 32 * 1024**2 and identity(directory / 'integration-source.tar') ==
            dict(bytes=len(original), sha256=hashlib.sha256(original).hexdigest()), 'candidate-integration-source-tree')
    require({p.name for p in directory.iterdir()} == {'wine', 'debian', 'integration-source.tar', 'integration-revision.txt'},
            'candidate-source-root-extra')
    return dict(formatVersion=1, scope='read-back-source-owned-arm64-wine-candidate-originals', sourceRevision=revision,
        runtimeMetadataSha256=hashlib.sha256(raw).hexdigest(), sourceLockSha256=hashlib.sha256(lock_raw).hexdigest(),
        debianSourcePackages=len(selected), originalDebianFiles=len(files), debianSourceBytes=manifest['fileBytes'],
        originalArchives={name: identity(directory / 'wine' / name) for name in sorted(original_files)},
        toolchainSources=toolchain_sources, fexNotices=len(fex_notices), adaptationSources=len(retained),
        completeIntegrationTreeReadBack=True, allOriginalSourcesReadBack=True, androidQualified=False,
        gameClientQualified=False, gameplayQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('sources', 'runtime-metadata'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.sources, args.runtime_metadata, args.revision), indent=2))


if __name__ == '__main__':
    main()
