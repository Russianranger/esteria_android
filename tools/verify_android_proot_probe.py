#!/usr/bin/env python3
"""Verify only the opt-in Android x86_64 PRoot/glibc probe provider/APK."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile
try:
    from . import build_android_proot_probe as builder
except ImportError:
    import build_android_proot_probe as builder

ROOT = Path(__file__).resolve().parents[1]
ROOTFS = {'probe', 'probe-plugin.so', 'lib/x86_64-linux-gnu/libc.so.6', 'lib64/ld-linux-x86-64.so.2'}
NOTICES = {'libc6-copyright.txt', 'libc6-dev-copyright.txt', 'linux-libc-dev-copyright.txt',
           'proot-COPYING.txt', 'talloc-COPYING.txt', 'ESTERIA-GPL-3.txt', 'FTA-MIT-LICENSE.txt'}


def require(ok, message):
    if not ok: raise ValueError(message)


def identity(data):
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def elf(data, role):
    """Architecture-specific structural checks, independent of ARM64 provider proof."""
    require(64 <= len(data) <= 16 * 1024**2 and data[:7] == b'\x7fELF\x02\x01\x01', 'invalid-probe-elf')
    kind, machine, version, entry, phoff = struct.unpack_from('<HHIQQ', data, 16)
    ehsize, phsize, count = struct.unpack_from('<HHH', data, 52)
    require((kind, machine, version, ehsize, phsize) == (2 if role == 'loader' else 3, 62, 1, 64, 56), 'wrong-probe-elf-target')
    require(1 <= count <= 32 and 64 <= phoff and phoff + count * phsize <= len(data), 'invalid-probe-program-headers')
    loads = []; dynamic = []; interpreters = []; stacks = []; executable = False
    for index in range(count):
        typ, flags, offset, virtual, _, size, memory, alignment = struct.unpack_from('<IIQQQQQQ', data, phoff + index * 56)
        require(offset <= len(data) and size <= len(data) - offset, 'probe-segment-outside-file')
        if typ == 1:
            minimum = 16384 if role in ('tracer', 'loader', 'owner') else 4096
            require(size <= memory and alignment >= minimum and alignment & (alignment - 1) == 0 and
                    offset % alignment == virtual % alignment and flags & 3 != 3, 'probe-load-contract')
            loads.append((offset, virtual, size)); executable |= bool(flags & 1 and virtual <= entry < virtual + size)
        elif typ == 2:
            require(0 < size <= 65536 and size % 16 == 0, 'probe-dynamic-bounds'); dynamic.append((offset, size))
        elif typ == 3:
            require(0 < size <= 256 and data[offset + size - 1] == 0, 'probe-interpreter-bounds')
            interpreters.append(data[offset:offset + size - 1].decode('ascii'))
        elif typ == 0x6474e551: stacks.append(flags)
    require(loads and len(stacks) == 1 and not stacks[0] & 1, 'probe-stack-contract')
    require(executable if role in ('tracer', 'loader', 'guest', 'libc', 'ld') else entry == 0, 'probe-entry-contract')
    expected_interpreter = ['/system/bin/linker64'] if role == 'tracer' else (
        ['/lib64/ld-linux-x86-64.so.2'] if role in ('guest', 'libc') else [])
    require(interpreters == expected_interpreter, 'probe-interpreter-contract')
    if role == 'loader':
        require(not dynamic, 'probe-loader-has-dynamic-table'); return
    require(len(dynamic) == 1, 'probe-dynamic-contract')
    tags = {}; ended = False; offset, size = dynamic[0]
    for pos in range(offset, offset + size, 16):
        tag, value = struct.unpack_from('<qQ', data, pos)
        if tag == 0: ended = True; break
        tags.setdefault(tag, []).append(value)
    require(ended and not any(tag in tags for tag in (15, 22, 29)) and
            len(tags.get(5, [])) == 1 and len(tags.get(10, [])) == 1, 'probe-dynamic-strings')
    address, length = tags[5][0], tags[10][0]
    require(0 < length <= 1024**2, 'probe-string-limit')
    mapping = [off + address - virt for off, virt, size in loads if virt <= address and address + length <= virt + size]
    require(len(mapping) == 1, 'probe-strings-not-file-backed')
    strings = data[mapping[0]:mapping[0] + length]
    needed = []
    for index in tags.get(1, []):
        require(index < length, 'probe-needed-index'); end = strings.find(b'\0', index)
        require(end > index, 'probe-needed-termination'); needed.append(strings[index:end].decode('ascii'))
    expected = {'tracer': {'libc.so', 'libdl.so'}, 'owner': {'libc.so', 'libdl.so', 'libm.so'},
                'guest': {'libc.so.6'}, 'plugin': {'libc.so.6', 'ld-linux-x86-64.so.2'},
                'libc': {'ld-linux-x86-64.so.2'}, 'ld': set()}[role]
    require(len(needed) == len(expected) and set(needed) == expected, 'probe-dependency-contract')


def verify(provider, apk=None):
    provider = provider.resolve(strict=True)
    expected = {'assets/proot-probe/build-evidence.json'} | {'assets/proot-probe/notices/' + name for name in NOTICES}
    expected |= {'jniLibs/x86_64/' + name for name in builder.NATIVE_PINS}
    expected |= {'assets/proot-probe/rootfs/' + name for name in ROOTFS}
    actual = set()
    for path in provider.rglob('*'):
        require(not path.is_symlink(), 'probe-provider-link')
        if path.is_dir(): continue
        require(path.is_file(), 'probe-provider-special-file'); actual.add(path.relative_to(provider).as_posix())
    require(actual == expected, 'probe-provider-inventory-differs')
    receipt_path = provider / 'assets/proot-probe/build-evidence.json'
    require(receipt_path.stat().st_size <= 65536, 'oversized-probe-evidence')
    receipt = json.loads(receipt_path.read_text())
    require(receipt['formatVersion'] == 1 and receipt['scope'] == 'android-13-x86_64-proot-glibc-probe-build-only' and
            receipt['glibcVersion'] == '2.36' and receipt['ndkVersion'] == '28.2.13676358', 'wrong-probe-profile')
    for field in ('androidProotExecuted', 'arm64GuestExecuted', 'gameplayQualified'):
        require(receipt[field] is False, 'build-evidence-must-not-claim-execution')
    sources = {'prootSourceLockSha256': 'runtime/proot/sources.lock.json', 'glibcLockSha256': 'native/proot-probe/glibc.lock.json',
               'builderSha256': 'tools/build_android_proot_probe.py', 'guestSourceSha256': 'native/proot-probe/guest.c',
               'pluginSourceSha256': 'native/proot-probe/plugin.c', 'ownershipPatchSha256': 'runtime/proot/proot-exitkill.patch'}
    for field, path in sources.items(): require(receipt[field] == identity((ROOT / path).read_bytes())['sha256'], 'stale-probe-source-receipt')
    require(receipt['nativeFiles'] == builder.NATIVE_PINS and set(receipt['rootfsFiles']) == ROOTFS, 'probe-file-inventory')
    for name, pin in builder.NATIVE_PINS.items():
        path = provider / 'jniLibs/x86_64' / name
        require(path.stat().st_size == pin['bytes'], 'probe-native-size')
        data = path.read_bytes()
        require(identity(data) == pin, 'probe-native-identity'); elf(data, 'loader' if 'loader' in name else 'tracer')
    roles = {'probe': 'guest', 'probe-plugin.so': 'plugin', 'lib/x86_64-linux-gnu/libc.so.6': 'libc', 'lib64/ld-linux-x86-64.so.2': 'ld'}
    for name, role in roles.items():
        path = provider / 'assets/proot-probe/rootfs' / name
        require(path.stat().st_size <= 16 * 1024**2, 'probe-rootfs-file-limit')
        data = path.read_bytes(); require(identity(data) == receipt['rootfsFiles'][name], 'probe-rootfs-identity'); elf(data, role)
    for name in NOTICES: require(0 < (provider / 'assets/proot-probe/notices' / name).stat().st_size <= 256 * 1024, 'probe-notice-size')
    if apk:
        require(0 < apk.stat().st_size <= 64 * 1024**2, 'probe-apk-size-limit')
        with zipfile.ZipFile(apk) as archive:
            names = archive.namelist(); require(len(names) == len(set(names)), 'duplicate-apk-entry')
            natives = {name for name in names if name.startswith('lib/') and not name.endswith('/')}
            require(natives == {'lib/x86_64/' + name for name in builder.NATIVE_PINS} | {'lib/x86_64/libesteria_process.so'}, 'probe-apk-native-inventory')
            require(64 <= archive.getinfo('lib/x86_64/libesteria_process.so').file_size <= 16 * 1024**2, 'probe-owner-size-limit')
            elf(archive.read('lib/x86_64/libesteria_process.so'), 'owner')
            require({name for name in names if name.startswith('assets/proot-probe/') and not name.endswith('/')} ==
                    {name for name in expected if name.startswith('assets/')}, 'probe-apk-asset-inventory')
            for relative in expected:
                target = relative.replace('jniLibs/', 'lib/', 1)
                require(target in names and archive.getinfo(target).file_size == (provider / relative).stat().st_size and
                        archive.read(target) == (provider / relative).read_bytes(), 'probe-apk-bytes-differ')
    return dict(scope='android-13-x86_64-proot-glibc-probe-build-only', providerVerified=True,
                apkVerified=bool(apk), androidProotExecuted=False, arm64GuestExecuted=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', type=Path, required=True); parser.add_argument('--apk', type=Path)
    args = parser.parse_args(); print(json.dumps(verify(args.provider, args.apk)))


if __name__ == '__main__': main()
