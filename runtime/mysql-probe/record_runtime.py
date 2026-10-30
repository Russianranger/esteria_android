#!/usr/bin/env python3
"""Record an actually built Ubuntu x86_64 emulator dependency image; do not initialize data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
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
        require(len(fields) == 5, 'invalid-dpkg-record')
        name, version, architecture, source, source_version = fields
        require(name not in seen and name and version and architecture in ('amd64', 'all'), 'invalid-package-identity')
        seen.add(name)
        packages.append(dict(package=name, version=version, architecture=architecture,
                             sourcePackage=source or name.split(':')[0], sourceVersion=source_version or version))
    require(packages, 'empty-package-inventory')
    return sorted(packages, key=lambda item: item['package'])


def elf_identity(path):
    # Resolving OS-owned symlinks here is intentional: this runs inside the new
    # container and records the actual installed executable, not an import.
    path = path.resolve(strict=True)
    with path.open('rb') as stream:
        head = stream.read(64)
        require(len(head) == 64 and head[:6] == b'\x7fELF\x02\x01' and
                struct.unpack_from('<H', head, 18)[0] == 62, 'runtime-executable-is-not-x86-64-elf')
        stream.seek(0)
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(path=str(path), bytes=path.stat().st_size, sha256=digest, elfMachine=62)


def source_inventory(packages):
    return [dict(package=name, version=version) for name, version in sorted(
        {(item['sourcePackage'], item['sourceVersion']) for item in packages})]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    lock_bytes = args.lock.read_bytes()
    lock = json.loads(lock_bytes)
    require(platform.machine().lower() in ('x86_64', 'amd64'), 'x86-64-probe-runtime-required')
    query = '${binary:Package}\t${Version}\t${Architecture}\t${source:Package}\t${source:Version}\n'
    packages = package_inventory(subprocess.check_output(['dpkg-query', '-W', '-f=' + query], text=True))
    versions = {item['package'].split(':')[0]: item['version'] for item in packages}
    require(all(versions.get(item['package']) == item['version'] for item in lock['mysql']['binaryPackages']),
            'mysql-package-version-mismatch')
    require(all(name in versions for name in lock['runtimePackages']), 'missing-runtime-package')
    images = {}
    outputs = {}
    for name in ('mysqld', 'mysql', 'python3'):
        selected = shutil.which(name)
        require(selected is not None, 'missing-runtime-executable:' + name)
        images[name] = elf_identity(Path(selected))
        outputs[name] = subprocess.check_output([selected, '--version'], text=True, stderr=subprocess.STDOUT,
                                                timeout=30).strip()
    match = re.search(r'\bVer\s+(\S+)\s+for\s+', outputs['mysqld'])
    require(match and match.group(1) == lock['mysql']['expectedRuntimeVersion'], 'mysqld-version-output-mismatch')
    require(not Path('/var/lib/mysql/auto.cnf').exists(), 'database-was-unexpectedly-initialized')
    result = dict(formatVersion=1, scope='built-linux-x86-64-mysql-probe',
                  sourceLockSha256=hashlib.sha256(lock_bytes).hexdigest(), baseImage=lock['baseImage']['reference'],
                  snapshot=lock['snapshot']['id'], architecture='amd64', packages=packages,
                  sourcePackages=source_inventory(packages), images=images, versionOutputs=outputs,
                  expectedMysqlSqlVersion=match.group(1), mysqlSqlVersionVerified=False,
                  databaseInitialized=False, serverIncluded=False, serverExecuted=False,
                  androidRuntimeQualified=False, gameLoginQualified=False)
    with args.output.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    print(json.dumps(dict(packages=len(packages), sourcePackages=len(result['sourcePackages']),
                         mysqlVersionFromExecutable=match.group(1), mysqlSqlVersionVerified=False)))


if __name__ == '__main__':
    main()
