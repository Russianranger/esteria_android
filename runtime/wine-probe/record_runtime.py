#!/usr/bin/env python3
"""Record an actually source-built x64 Wine guest; never initialize a prefix."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess


def require(value, message):
    if not value:
        raise ValueError(message)


def package_inventory(text):
    packages = []
    seen = set()
    for line in text.splitlines():
        fields = line.split('\t')
        require(len(fields) == 5, 'invalid-package-record')
        name, version, arch, source, source_version = fields
        require(name not in seen and name and version and arch in ('amd64', 'all'), 'invalid-package-identity')
        seen.add(name)
        packages.append(dict(package=name, version=version, architecture=arch,
                             sourcePackage=source or name.split(':')[0], sourceVersion=source_version or version))
    require(0 < len(packages) <= 512, 'package-inventory-limit')
    return sorted(packages, key=lambda item: item['package'])


def source_inventory(packages):
    return [dict(package=name, version=version) for name, version in sorted(
        {(item['sourcePackage'], item['sourceVersion']) for item in packages})]


def identity(path, pe=False):
    # Build-container-owned symlinks resolve to their actual installed image.
    path = path.resolve(strict=True)
    with path.open('rb') as stream:
        header = stream.read(4096)
        if pe:
            require(len(header) >= 64 and header[:2] == b'MZ', 'missing-pe-header')
            offset = struct.unpack_from('<I', header, 60)[0]
            require(64 <= offset <= 1024**2, 'pe-header-offset-limit')
            stream.seek(offset)
            nt = stream.read(26)
            require(len(nt) == 26 and nt[:4] == b'PE\0\0' and
                    struct.unpack_from('<H', nt, 4)[0] == 0x8664 and
                    struct.unpack_from('<H', nt, 24)[0] == 0x20b, 'not-x64-pe32plus')
            machine = dict(peMachine='0x8664')
        else:
            require(len(header) >= 64 and header[:6] == b'\x7fELF\x02\x01' and
                    struct.unpack_from('<H', header, 18)[0] == 62, 'not-x64-elf')
            machine = dict(elfMachine=62, elfClass=2)
        stream.seek(0)
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(path=str(path), bytes=path.stat().st_size, sha256=digest, **machine)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.lock.read_bytes()
    lock = json.loads(raw)
    require(subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip() == 'amd64', 'amd64-build-required')
    query = '${binary:Package}\t${Version}\t${Architecture}\t${source:Package}\t${source:Version}\n'
    packages = package_inventory(subprocess.check_output(['dpkg-query', '-W', '-f=' + query], text=True))
    images = {name: identity(Path(path)) for name, path in {
        'wine': '/opt/wine/bin/wine', 'wineserver': '/opt/wine/bin/wineserver',
        'ntdllUnix': '/opt/wine/lib/wine/x86_64-unix/ntdll.so', 'python3': '/usr/bin/python3.11'}.items()}
    for name in ('kernel32.dll', 'ntdll.dll', 'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'ws2_32.dll', 'wininet.dll'):
        images[name] = identity(Path('/opt/wine/lib/wine/x86_64-windows') / name, pe=True)
    version = subprocess.check_output(['/opt/wine/bin/wine', '--version'], text=True, timeout=30).strip()
    require(re.fullmatch(r'wine-10\.13(?:[ -][^\r\n]{1,80})?', version), 'unexpected-built-wine-version')
    require(not Path('/root/.wine').exists(), 'prefix-unexpectedly-initialized')
    result = dict(formatVersion=1, scope='built-linux-x86-64-wine-probe', architecture='amd64',
                  sourceLockSha256=hashlib.sha256(raw).hexdigest(), baseImage=lock['baseImage']['reference'],
                  snapshot=lock['snapshot']['id'], wineRevision=lock['wine']['revision'],
                  wineSourceArchiveSha256=lock['wine']['sourceArchive']['sha256'], wineVersion=version,
                  privatePeCopyProfile=lock['wine']['androidPrivatePeCopy'],
                  packages=packages, sourcePackages=source_inventory(packages), images=images,
                  prefixInitialized=False, clientIncluded=False, clientExecuted=False,
                  androidRuntimeQualified=False, arm64Qualified=False, gameplayQualified=False)
    with args.output.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n'); output.flush(); os.fsync(output.fileno())
    print(json.dumps(dict(wineVersion=version, packages=len(packages), images=len(images))))


if __name__ == '__main__': main()
