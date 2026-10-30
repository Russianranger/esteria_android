#!/usr/bin/env python3
"""Measure a separate native ARM64 Wine candidate without initializing a prefix."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess


def require(value, reason):
    if not value:
        raise ValueError(reason)


def package_inventory(text):
    result = []
    seen = set()
    for line in text.splitlines():
        fields = line.split('\t')
        require(len(fields) == 5, 'package-record')
        name, version, arch, source, source_version = fields
        require(name not in seen and name and version and arch in ('arm64', 'all'), 'package-identity')
        seen.add(name)
        result.append(dict(package=name, version=version, architecture=arch,
                           sourcePackage=source or name.split(':')[0], sourceVersion=source_version or version))
    require(0 < len(result) <= 512, 'package-count')
    return sorted(result, key=lambda row: row['package'])


def source_inventory(packages):
    return [dict(package=name, version=version) for name, version in sorted(
        {(row['sourcePackage'], row['sourceVersion']) for row in packages})]


PE = '/opt/wine/lib/wine/aarch64-windows/'
IMAGES = {name: (path, None) for name, path in {
    'wine': '/opt/wine/bin/wine', 'wineserver': '/opt/wine/bin/wineserver',
    'ntdllUnix': '/opt/wine/lib/wine/aarch64-unix/ntdll.so', 'python3': '/usr/bin/python3.11',
    'x11': '/usr/bin/Xtigervnc', 'lavapipe': '/usr/lib/aarch64-linux-gnu/libvulkan_lvp.so',
    'vulkanLoader': '/usr/lib/aarch64-linux-gnu/libvulkan.so.1.3.239',
    'wineVulkan': '/opt/wine/lib/wine/aarch64-unix/winevulkan.so',
    'asound': '/usr/lib/aarch64-linux-gnu/libasound.so.2.0.0',
    'wineAlsa': '/opt/wine/lib/wine/aarch64-unix/winealsa.so'}.items()}
IMAGES.update({name: (PE + name, (0xaa64,)) for name in
               ('kernel32.dll', 'ntdll.dll', 'wininet.dll', 'ws2_32.dll', 'vulkan-1.dll', 'winealsa.drv',
                'msvcp140.dll', 'vcruntime140.dll', 'libwow64fex.dll')})
IMAGES.update({name: (PE + name, (0x8664, 0xa641)) for name in ('libarm64ecfex.dll', 'vcruntime140_1.dll')})
IMAGES['i386Ntdll'] = ('/opt/wine/lib/wine/i386-windows/ntdll.dll', (0x14c,))
DATA = ('usr/share/vulkan/icd.d/lvp_icd.aarch64.json', 'usr/share/alsa/alsa.conf', 'usr/lib/os-release')


def identity(path, allowed=None):
    with path.open('rb') as stream:
        head = stream.read(4096)
        if allowed is not None:
            require(head[:2] == b'MZ' and len(head) >= 64, 'pe-signature')
            offset = struct.unpack_from('<I', head, 60)[0]
            require(64 <= offset <= 1024**2, 'pe-offset')
            stream.seek(offset)
            nt = stream.read(26)
            require(len(nt) == 26 and nt[:4] == b'PE\0\0', 'pe-header')
            machine = struct.unpack_from('<H', nt, 4)[0]
            require(machine in allowed and struct.unpack_from('<H', nt, 24)[0] ==
                    (0x10b if machine == 0x14c else 0x20b), 'pe-architecture')
            architecture = dict(peMachine=hex(machine))
        else:
            require(head[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', head, 18)[0] == 183,
                    'native-arm64-elf-required')
            architecture = dict(elfMachine=183, elfClass=2)
        stream.seek(0)
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest(), **architecture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.lock.read_bytes(); lock = json.loads(raw)
    require(subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip() == 'arm64', 'native-arm64-builder')
    query = '${binary:Package}\t${Version}\t${Architecture}\t${source:Package}\t${source:Version}\n'
    packages = package_inventory(subprocess.check_output(['dpkg-query', '-W', '-f=' + query], text=True))
    images = {name: dict(path=path, **identity(Path(path), allowed)) for name, (path, allowed) in IMAGES.items()}
    data = {}
    for name in DATA:
        contents = Path('/' + name).read_bytes()
        require(0 < len(contents) <= 262144, 'runtime-data-bound')
        data[name] = dict(bytes=len(contents), sha256=hashlib.sha256(contents).hexdigest())
    version = subprocess.check_output(['/opt/wine/bin/wine', '--version'], text=True, timeout=30).strip()
    require(re.fullmatch(r'wine-10\.13(?:[ -][^\r\n]{1,80})?', version), 'wine-version')
    require(not Path('/root/.wine').exists(), 'fresh-runtime-required')
    notices = {}
    notice_bytes = 0
    for path in sorted(Path('/usr/share/doc/esteria-wine-arm64').rglob('*')):
        if path.is_dir():
            continue
        require(path.is_file() and not path.is_symlink(), 'regular-runtime-notice-required')
        notice_bytes += path.stat().st_size
        require(0 < path.stat().st_size <= 4 * 1024**2 and notice_bytes <= 32 * 1024**2 and
                len(notices) < 4096, 'runtime-notice-bounds')
        with path.open('rb') as stream:
            notices[str(path.relative_to('/'))] = dict(bytes=path.stat().st_size,
                sha256=hashlib.file_digest(stream, 'sha256').hexdigest())
    require(len(notices) >= 3, 'wine-fex-toolchain-notices-required')
    result = dict(formatVersion=1, scope='source-built-native-arm64-wine-candidate', architecture='arm64',
                  sourceLockSha256=hashlib.sha256(raw).hexdigest(), baseImage=lock['baseImage']['reference'],
                  snapshot=lock['snapshot']['id'], wineRevision=lock['wine']['revision'],
                  wineSourceArchiveSha256=lock['wine']['sourceArchive']['sha256'], fexRevision=lock['fex']['revision'],
                  fexSourceArchiveSha256=lock['fex']['archive']['sha256'], toolchainArchiveSha256=lock['toolchain']['archive']['sha256'],
                  privatePeCopyProfile=lock['wine']['androidPrivatePeCopy'], wineVersion=version,
                  packages=packages, sourcePackages=source_inventory(packages), images=images, data=data, notices=notices,
                  softwareGraphicsIcd=json.loads(Path('/usr/share/vulkan/icd.d/lvp_icd.aarch64.json').read_bytes()),
                  prefixInitialized=False, clientIncluded=False, androidQualified=False, gameplayQualified=False)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())


if __name__ == '__main__':
    main()
