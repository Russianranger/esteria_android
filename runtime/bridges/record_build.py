#!/usr/bin/env python3
"""Inspect built ELF and exact inputs; this deliberately does not claim execution."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import struct
import subprocess

# AArch64 glibc exports __stack_chk_guard from its loader. Stack-protected
# executables/plugins can therefore directly NEEDED this same required loader.
ALLOWED_NEEDED = {'libX11.so.6', 'libXfixes.so.3', 'libXext.so.6', 'libasound.so.2', 'libc.so.6',
                  'ld-linux-aarch64.so.1'}
BINARIES = ('esteria-x11-frame', 'esteria-x11-input', 'libasound_module_pcm_esteria.so')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path):
    require(path.is_file() and not path.is_symlink(), 'regular-file-required')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(bytes=path.stat().st_size, sha256=digest)


def elf(path):
    with path.open('rb') as stream:
        head = stream.read(64)
    require(len(head) == 64 and head[:6] == b'\x7fELF\x02\x01' and
            struct.unpack_from('<H', head, 18)[0] == 183, 'not-elf64-arm64')
    dynamic = subprocess.check_output(['readelf', '--dynamic', '--wide', str(path)], text=True)
    needed = re.findall(r'\(NEEDED\).*?\[([^\]]+)\]', dynamic)
    require(needed and set(needed) <= ALLOWED_NEEDED,
            'unexpected-guest-library:' + path.name + ':' + ','.join(needed))
    require(not re.search(r'\((?:RPATH|RUNPATH)\)', dynamic), 'unexpected-library-search-path')
    program = subprocess.check_output(['readelf', '--program-headers', '--wide', str(path)], text=True)
    interpreters = re.findall(r'Requesting program interpreter: ([^\]]+)', program)
    require(interpreters == ([] if path.name.endswith('.so') else ['/lib/ld-linux-aarch64.so.1']), 'wrong-guest-interpreter')
    versions = subprocess.check_output(['readelf', '--version-info', '--wide', str(path)], text=True)
    glibc = sorted({tuple(map(int, value.split('.'))) for value in re.findall(r'Name: GLIBC_([0-9.]+)', versions)})
    require(glibc and glibc[-1] <= (2, 36), 'requires-glibc-newer-than-wine-rootfs')
    return dict(**identity(path), architecture='arm64', needed=sorted(needed),
                maxGlibc='.'.join(map(str, glibc[-1])), interpreter=interpreters[0] if interpreters else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-inputs', action='store_true')
    parser.add_argument('--revision')
    args = parser.parse_args()
    require(platform.machine() in ('aarch64', 'arm64'), 'native-arm64-builder-required')
    raw = Path('/inputs/sources.lock.json').read_bytes()
    lock = json.loads(raw)
    measured = {p.name: identity(p) for p in Path('/package-pins').iterdir()}
    installed = {}
    for expected in lock['packages']:
        require(dict(bytes=expected['bytes'], sha256=expected['sha256']) in measured.values(), 'package-input-mismatch')
        version = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', expected['package']], text=True)
        require(version == expected['version'], 'installed-package-version-mismatch')
        installed[expected['package']] = version
    if args.verify_inputs:
        print('GUEST_BRIDGE_PINNED_INPUTS_OK')
        return
    require(args.revision and re.fullmatch('[0-9a-f]{40}', args.revision), 'exact-integration-revision-required')
    binaries = {name: elf(Path('/out/bin') / name) for name in BINARIES}
    sources = {str(p.relative_to('/src')): identity(p) for p in sorted(Path('/src').rglob('*')) if p.is_file()}
    inventory = subprocess.check_output(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${Architecture}\n'], text=True)
    Path('/out/build-packages.txt').write_text(inventory)
    receipt = dict(formatVersion=1, scope='linux-arm64-guest-bridge-build-only', integrationRevision=args.revision,
                   inputLockSha256=hashlib.sha256(raw).hexdigest(), runtimeArchiveSha256=lock['runtimeArchiveSha256'],
                   binaries=binaries, sources=sources, selectedPackages=installed,
                   compiled=True, guestExecutionQualified=False, androidQualified=False, gameAudioQualified=False,
                   presentationQualified=False, inputQualified=False)
    Path('/out/bridge-build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('GUEST_BRIDGE_ELF_BUILD_ONLY_OK')


if __name__ == '__main__':
    main()
