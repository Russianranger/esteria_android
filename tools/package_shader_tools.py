#!/usr/bin/env python3
"""Package exact client translators and a measured ARM64 shader compiler.

The executable tool root has an exact eight-file closure. Sources, notices and
build evidence live alongside it; this does not qualify game shaders or Android.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile

try:
    from .package_server_content import publish_directory
except ImportError:
    from package_server_content import publish_directory

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ('translate_shaders.py', 'bls/__init__.py', 'bls/archive.py',
          'bls/dx9ir.py', 'bls/emitter.py', 'bls/mpq_extract.py', 'bls/translate.py')
MAX_FILE = 64 * 1024**2
META = 2 * 1024**2
SOURCES = {'glslang': ('LICENSE.txt', 'GLSLANG-LICENSE.txt'),
           'spirv-tools': ('LICENSE', 'SPIRV-TOOLS-LICENSE'),
           'spirv-headers': ('LICENSE', 'SPIRV-HEADERS-LICENSE')}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def plain(path, maximum=MAX_FILE):
    """Reject symlink ancestors, special files and unexpectedly large inputs."""
    path = Path(path).absolute()
    require(path == path.resolve(), 'symlink-or-noncanonical-input')
    mode = path.lstat()
    require(stat.S_ISREG(mode.st_mode) and 0 < mode.st_size <= maximum, 'plain-bounded-file-required')
    return path


def identity(path, maximum=MAX_FILE):
    path = plain(path, maximum)
    with path.open('rb') as source:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(source, 'sha256').hexdigest())


def small(path, maximum=META):
    with plain(path, maximum).open('rb') as source:
        raw = source.read(maximum + 1)
    require(len(raw) <= maximum, 'metadata-grew-beyond-bound')
    return raw


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def checkout_blob(source, revision, name):
    require(re.fullmatch('[0-9a-f]{40}', revision), 'full-git-revision-required')
    source = Path(source).absolute()
    require(source == source.resolve() and source.is_dir(), 'canonical-checkout-required')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args], stderr=subprocess.DEVNULL)
    require(git('rev-parse', 'HEAD').decode().strip() == revision, 'checkout-revision-mismatch')
    row = git('ls-tree', revision, '--', name).decode().strip().split()
    require(len(row) == 4 and row[0] in ('100644', '100755') and row[1] == 'blob' and row[3] == name,
            'committed-plain-source-required')
    size = int(git('cat-file', '-s', row[2]))
    require(0 < size <= META, 'source-blob-bound')
    raw = git('cat-file', 'blob', row[2])
    require(len(raw) == size and small(source / name) == raw, 'source-checkout-content-mismatch')
    return raw, dict(bytes=size, sha256=hashlib.sha256(raw).hexdigest(), gitBlob=row[2], gitMode=row[0])


def qualification(value):
    expected = dict(formatVersion=1, scope='native-linux-arm64-shader-tools-only', qualified=True,
                    validGlslCompiled=True, spirvValidated=True, spirvDisassembled=True,
                    invalidGlslRejected=True, invalidSpirvRejected=True, androidQualified=False,
                    gameAssetShadersQualified=False, gameplayQualified=False)
    require(type(value) is dict and set(value) == set(expected) | {'validSpirvSha256'} and
            all(type(value.get(k)) is type(v) and value[k] == v for k, v in expected.items()) and
            re.fullmatch('[0-9a-f]{64}', value.get('validSpirvSha256', '')), 'shader-qualification-incomplete-or-overclaims')


def measure_elf(path):
    # Use the shared reviewed parser on the actual bytes, never the receipt alone.
    spec = importlib.util.spec_from_file_location('turnip_elf', ROOT / 'runtime/turnip/record_build.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.elf(plain(path), False)


def write(path, raw, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())
    path.chmod(0o755 if executable else 0o644)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def copy(path, target, pin):
    require(identity(path) == pin, 'source-file-identity-mismatch')
    target.parent.mkdir(parents=True, exist_ok=True)
    with path.open('rb') as incoming, target.open('xb') as output:
        left = pin['bytes']
        while left:
            raw = incoming.read(min(left, 1024 * 1024))
            require(raw, 'source-short-read')
            output.write(raw); left -= len(raw)
        require(not incoming.read(1), 'source-grew-during-copy')
        output.flush(); os.fsync(output.fileno())
    require(identity(target) == pin, 'output-readback-mismatch')
    target.chmod(0o644)


def license_bytes(archive, prefix, name):
    wanted = prefix + '/' + name
    result = None; count = total = 0
    # Archive hash was checked before parsing. Bound even metadata-only scanning.
    with tarfile.open(archive, 'r|gz') as source:
        for entry in source:
            count += 1; total += entry.size
            require(count <= 30000 and total <= 512 * 1024**2, 'source-archive-expanded-bound')
            if entry.name == wanted:
                require(result is None and entry.isfile() and 0 < entry.size <= META, 'source-license-entry-invalid')
                with source.extractfile(entry) as stream: result = stream.read(META + 1)
                require(len(result) == entry.size, 'source-license-truncated')
    require(result is not None, 'original-license-missing')
    return result


def build_input(integration, integration_revision, selected=None):
    raw, original = checkout_blob(integration, integration_revision, 'runtime/turnip/sources.lock.json')
    if selected is None: return raw, raw, None
    chosen = small(selected); base = json.loads(raw); value = json.loads(chosen)
    require(type(base) is dict and type(value) is dict and
            re.fullmatch('[0-9a-f]{64}', value.get('runtimeArchiveSha256', '')),
            'selected-compiler-runtime-binding')
    expected = dict(base, runtimeArchiveSha256=value['runtimeArchiveSha256'])
    require(value == expected, 'selected-compiler-build-lock-changes-other-inputs')
    return chosen, raw, dict(source='runtime/turnip/sources.lock.json', committedSource=original,
        selectedSource=dict(bytes=len(chosen), sha256=hashlib.sha256(chosen).hexdigest()),
        onlyRuntimeArchiveBindingChanged=True)


def build(output, client, client_revision, payload, build_sha256, integration, integration_revision, build_input_lock=None):
    output = Path(output).absolute(); payload = Path(payload).absolute()
    require(output.parent == output.parent.resolve() and output.parent.is_dir() and
            not os.path.lexists(output), 'fresh-canonical-output-required')
    require(re.fullmatch('[0-9a-f]{64}', build_sha256), 'explicit-measured-build-sha256-required')
    receipt_raw = small(payload / 'turnip-build.json')
    require(hashlib.sha256(receipt_raw).hexdigest() == build_sha256, 'build-receipt-pin-mismatch')
    receipt = json.loads(receipt_raw)
    require(receipt.get('formatVersion') == 1 and receipt.get('scope') == 'linux-arm64-turnip-kgsl-build-only' and
            receipt.get('integrationRevision') == integration_revision and receipt.get('compiled') is True and
            all(receipt.get(k) is False for k in ('hardwareQualified', 'androidQualified',
                'x11PresentationQualified', 'gameplayQualified')), 'build-source-or-scope-mismatch')
    lock_raw, original_lock, selected_input = build_input(integration, integration_revision, build_input_lock)
    lock = json.loads(lock_raw)
    require(receipt.get('inputLockSha256') == hashlib.sha256(lock_raw).hexdigest() and
            receipt.get('runtimeArchiveSha256') == lock['runtimeArchiveSha256'] and
            receipt.get('upstream') == lock['upstream'], 'build-input-lock-mismatch')
    compiler = payload / 'bin/glslangValidator'
    measured = measure_elf(compiler)
    require(receipt.get('binaries', {}).get('bin/glslangValidator') == measured, 'actual-compiler-elf-mismatch')
    evidence = small(payload / 'shader-tool-check/qualification.json')
    value = json.loads(evidence); qualification(value)
    require(receipt.get('shaderToolEvidence') == dict(bytes=len(evidence),
            sha256=hashlib.sha256(evidence).hexdigest(), result=value), 'shader-evidence-identity-mismatch')
    recipe = receipt.get('recipeSources')
    require(type(recipe) is dict and 1 <= len(recipe) <= 64 and 'sources.lock.json' in recipe,
            'recipe-provenance-missing')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.', dir=output.parent))
    try:
        provenance = {}; files = {}
        for name in PYTHON:
            raw, pin = checkout_blob(client, client_revision, 'Tools/VulkanShaders/' + name)
            write(stage / 'tools' / name, raw); files[name] = {k: pin[k] for k in ('bytes', 'sha256')}
            provenance[name] = pin
        readme, _ = checkout_blob(client, client_revision, 'Tools/VulkanShaders/README.md')
        write(stage / 'provenance/client-shader-README.md', readme)
        pin = {k: measured[k] for k in ('bytes', 'sha256')}
        copy(compiler, stage / 'tools/bin/glslangValidator', pin)
        (stage / 'tools/bin/glslangValidator').chmod(0o755); files['bin/glslangValidator'] = pin
        write(stage / 'tools/shader-tools.json', encoded(dict(formatVersion=1,
              clientRevision=client_revision, files=files)))
        write(stage / 'provenance/turnip-build.json', receipt_raw)
        write(stage / 'provenance/shader-tool-qualification.json', evidence)
        if selected_input is not None:
            write(stage / 'provenance/build-recipe-reference/sources.lock.json', original_lock)
        for name, pin in recipe.items():
            require(re.fullmatch('[A-Za-z0-9_.-]{1,100}', name) and name not in ('.', '..'), 'recipe-name-invalid')
            raw, actual = checkout_blob(integration, integration_revision, 'runtime/turnip/' + name)
            if name == 'sources.lock.json' and selected_input is not None:
                raw = lock_raw; actual = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            require(pin == {k: actual[k] for k in ('bytes', 'sha256')} and
                    small(payload / 'corresponding-source/build-recipe' / name) == raw, 'recipe-source-mismatch')
            write(stage / 'provenance/build-recipe' / name, raw)
        sources = {}
        for name, (license_name, notice_name) in SOURCES.items():
            pin = lock['upstream'][name]
            require(re.fullmatch('[A-Za-z0-9_.-]{1,150}', pin['file']) and
                    re.fullmatch('[A-Za-z0-9_.-]{1,150}', pin['prefix']), 'source-name-invalid')
            archive = payload / 'corresponding-source/original-archives' / pin['file']
            wanted = {k: pin[k] for k in ('bytes', 'sha256')}
            copy(archive, stage / 'corresponding-source' / pin['file'], wanted)
            original = license_bytes(stage / 'corresponding-source' / pin['file'], pin['prefix'], license_name)
            require(small(payload / 'notices' / notice_name) == original and
                    receipt.get('notices', {}).get('notices/' + notice_name) == dict(bytes=len(original),
                        sha256=hashlib.sha256(original).hexdigest()), 'original-license-mismatch')
            write(stage / 'notices' / notice_name, original); sources[name] = pin
        # Retain direct dependency copyright notices as supplied by the measured
        # build. Their full source identities remain in the adjacent original lock.
        require(receipt.get('noticeInventoryScope') == 'source-build-notices-before-integration-license',
                'notice-inventory-scope-mismatch')
        notice_total = 0
        for package in lock['packages']:
            name = package['package'] + '-copyright'
            require(re.fullmatch('[A-Za-z0-9+_.-]{1,150}', name), 'package-notice-name-invalid')
            raw = small(payload / 'notices' / name); notice_total += len(raw)
            require(notice_total <= 16 * 1024**2, 'notice-total-bound')
            require(receipt.get('notices', {}).get('notices/' + name) == dict(bytes=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest()), 'notice-receipt-identity-mismatch')
            write(stage / 'notices' / name, raw)
        license_raw, _ = checkout_blob(integration, integration_revision, 'LICENSE')
        write(stage / 'notices/ESTERIA-GPL-3.0', license_raw)
        report = dict(formatVersion=1, scope='offline-shader-tool-bundle', clientRevision=client_revision,
            clientGitFiles=provenance, integrationRevision=integration_revision, buildReceiptSha256=build_sha256,
            wineRuntimeArchiveSha256=lock['runtimeArchiveSha256'], compiler=measured, sources=sources,
            completeGuestRootfsSourceClosure=False, nativeCompilerFixtureQualified=True,
            androidQualified=False, gameAssetShadersQualified=False, gameplayQualified=False,
            toolManifestSha256=identity(stage / 'tools/shader-tools.json')['sha256'])
        if selected_input is not None: report['selectedBuildInput'] = selected_input
        write(stage / 'provenance/bundle.json', encoded(report))
        write(stage / 'NOTICE.txt', b'Exact committed Esteria shader translator sources and glslang/SPIRV tools.\n'
              b'Original license notices are retained; the client repository has no top-level LICENSE.\n'
              b'This bundle does not assign a new license to the client sources.\n'
              b'Compiler originals are included. Full Wine runtime source closure is not established here.\n'
              b'Native compiler fixtures do not qualify Android or imported game shaders.\n')
        # Re-read the exact runtime-facing closure before no-replace publication.
        for name, pin in files.items(): require(identity(stage / 'tools' / name) == pin, 'tool-readback-mismatch')
        for directory, _, _ in os.walk(stage, topdown=False): sync_directory(directory)
        publish_directory(stage, output)
        sync_directory(output.parent)
        return report
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('client', 'client-revision', 'turnip-payload', 'build-sha256',
                 'integration', 'integration-revision', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--build-input-lock', type=Path,
                        help='exact retained source lock differing only in the Wine runtime archive binding')
    args = parser.parse_args()
    result = build(args.output, args.client, args.client_revision, Path(args.turnip_payload),
                   args.build_sha256, args.integration, args.integration_revision, args.build_input_lock)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
