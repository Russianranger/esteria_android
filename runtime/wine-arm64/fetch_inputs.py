#!/usr/bin/env python3
"""Acquire exact candidate build inputs and retain original bundled notices."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

from prepare_runtime import fetch, require


def identity(path):
    require(path.is_file() and not path.is_symlink(), 'regular-input-required')
    with path.open('rb') as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def notices(source, output):
    require(not os.path.lexists(output), 'notice-output-exists')
    selected = {}
    total = 0
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if not (re.match(r'(?i)^(?:license|copying|notice|copyright)', path.name) or
                any(part.lower() in ('license', 'licenses') for part in relative.parts)):
            continue
        if path.is_dir():
            continue
        require(not path.is_symlink() and path.is_file(), 'notice-must-be-regular')
        pin = identity(path)
        total += pin['bytes']
        require(0 < pin['bytes'] <= 4 * 1024**2 and total <= 32 * 1024**2 and len(selected) < 4096,
                'notice-bounds')
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        selected[str(relative)] = pin
    require(selected, 'original-notices-missing')
    return selected


def toolchain(lock, source, output):
    selected = lock['toolchain']
    compiler = source / 'bin/clang-21'
    require(identity(compiler) == {k: selected['nativeCompiler'][k] for k in ('bytes', 'sha256')},
            'toolchain-compiler-identity')
    header = compiler.read_bytes()[:64]
    require(header[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', header, 18)[0] == 183,
            'native-arm64-toolchain-required')
    llvm = selected['sourceRefs'][0]['revision']
    version = subprocess.check_output([str(source / 'bin/clang'), '--version'], text=True, timeout=30)
    require('clang version 21.1.0' in version and llvm in version, 'toolchain-llvm-source-pairing')
    for name, expected in selected['bundledNotices'].items():
        require(identity(source / name) == expected, 'toolchain-bundled-notice-identity')
    result = dict(formatVersion=1, scope='exact-native-arm64-toolchain-build-input-only',
                  archive=selected['archive'], compiler=identity(compiler), compilerVersion=version,
                  llvmRevisionCorroborated=llvm, otherSourceRefsSelection='exact-retained-recipe',
                  bundledNotices=notices(source, output.parent / 'toolchain-notices'))
    require(not os.path.lexists(output), 'toolchain-evidence-exists')
    output.write_text(json.dumps(result, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--download', type=Path)
    parser.add_argument('--toolchain', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--notices', type=Path)
    parser.add_argument('--notice-output', type=Path)
    args = parser.parse_args()
    lock = json.loads(args.lock.read_bytes())
    if args.download:
        args.download.mkdir(parents=True, exist_ok=True)
        for pin in (lock['wine']['sourceArchive'], lock['fex']['archive'], lock['toolchain']['archive']):
            fetch(pin, args.download)
    if args.toolchain:
        require(args.output is not None, 'toolchain-output-required')
        toolchain(lock, args.toolchain, args.output)
    if args.notices:
        require(args.notice_output is not None, 'notice-output-required')
        result = notices(args.notices, args.notice_output)
        (args.notice_output / 'NOTICE-MANIFEST.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
