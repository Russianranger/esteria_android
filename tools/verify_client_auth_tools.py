#!/usr/bin/env python3
"""Verify the separate, offline-only compiled authentication test tool image."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tempfile


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def identity(path):
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), 'tool-input-not-regular')
    digest = hashlib.sha256()
    count = 0
    with path.open('rb') as source:
        for block in iter(lambda: source.read(131072), b''):
            count += len(block)
            require(count <= 256 * 1024**2, 'tool-input-bound')
            digest.update(block)
    return dict(bytes=count, sha256=digest.hexdigest())


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def run(command):
    # These are fixed package-query/version commands, never arbitrary test
    # executables. File-size limits apply only to their bounded diagnostic files.
    def limit_output():
        import resource
        resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024**2, 2 * 1024**2))
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output,
                                stderr=subprocess.STDOUT, timeout=30,
                                env=dict(PATH='/usr/sbin:/usr/bin:/sbin:/bin', LANG='C.UTF-8'),
                                preexec_fn=limit_output)
        output.seek(0)
        data = output.read(2 * 1024**2 + 1)
    require(result.returncode == 0 and len(data) < 2 * 1024**2, 'tool-command-failed:' + command[0])
    return data.decode('utf-8', errors='strict')


def inventory():
    result = {}
    raw = run(['/usr/bin/dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\t${Status}\n'])
    for line in raw.splitlines():
        name, version, arch, status = line.split('\t')
        require(name not in result and status == 'install ok installed', 'tool-package-status')
        result[name] = dict(version=version, architecture=arch)
    return result


def expected_packages(lock):
    return {row['name']: dict(version=row['version'], architecture=row['architecture'])
            for row in lock['packages']}


def verify_transition(before, after, lock):
    added = expected_packages(lock)
    require(not set(before).intersection(added), 'tool-overlay-must-not-replace-base-packages')
    require(after == {**before, **added}, 'tool-overlay-package-set-changed')


def verify_base(lock):
    require(platform.system() == 'Linux' and platform.machine() in ('aarch64', 'arm64'),
            'native-arm64-tool-image-required')
    require(identity('/etc/esteria-server-runtime.json') == lock['base']['metadata'],
            'tool-image-base-metadata-mismatch')
    metadata = json.loads(Path('/etc/esteria-server-runtime.json').read_text())
    dependency = lock['diagnosticAddition']['dependency']
    libc = [row for row in metadata['packages'] if row['package'].split(':')[0] == dependency['name']]
    require(len(libc) == 1 and libc[0]['architecture'] == 'arm64' and libc[0]['version'] == dependency['installed'],
            'tool-diagnostic-base-dependency-mismatch')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--archives', type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    require(args.lock.stat().st_size <= 1024**2, 'tool-lock-bound')
    lock = json.loads(args.lock.read_text())
    verify_base(lock)
    if args.archives:
        require(args.receipt is None and not args.before.exists(), 'tool-before-output-exists')
        require(identity('/var/lib/dpkg/status') == lock['base']['dpkgStatus'],
                'tool-image-base-package-status-mismatch')
        require({p.name for p in args.archives.iterdir()} == {Path(r['filename']).name for r in lock['packages']},
                'tool-archive-set-mismatch')
        for row in lock['packages']:
            path = args.archives / Path(row['filename']).name
            require(identity(path) == {k: row[k] for k in ('bytes', 'sha256')}, 'tool-archive-mismatch')
            metadata = run(['/usr/bin/dpkg-deb', '-f', str(path), 'Package', 'Version', 'Architecture'])
            actual = dict(line.split(': ', 1) for line in metadata.splitlines())
            require(actual == dict(Package=row['name'], Version=row['version'], Architecture=row['architecture']),
                    'tool-archive-package-identity')
        before = inventory()
        require(not set(before).intersection(expected_packages(lock)), 'tool-base-already-has-overlay')
        with args.before.open('xb') as output:
            output.write(encoded(before))
    else:
        require(args.receipt is not None and not args.receipt.exists(), 'tool-receipt-output-exists')
        require(args.before.stat().st_size <= 1024**2, 'tool-before-bound')
        before = json.loads(args.before.read_text())
        after = inventory()
        verify_transition(before, after, lock)
        commands = {'git': ['/usr/bin/git', '--version'], 'readelf': ['/usr/bin/readelf', '--version'],
                    'ip': ['/usr/sbin/ip', '-Version'], 'unshare': ['/usr/bin/unshare', '--version']}
        versions = {name: run(command).strip() for name, command in commands.items()}
        require(versions['git'].startswith('git version ') and versions['readelf'].startswith('GNU readelf ') and
                versions['ip'].startswith('ip utility, iproute2-') and 'util-linux' in versions['unshare'],
                'tool-version-command-contract')
        receipt = dict(formatVersion=1, scope='native-arm64-auth-test-tools-only',
                       lock=identity(args.lock), base=lock['base'], packages=expected_packages(lock),
                       actualVersions=versions, existingPackageVersionsPreserved=True,
                       offlineInstallation=True, clientExecuted=False, serverExecuted=False,
                       androidRuntimeQualified=False, gameplayQualified=False)
        with args.receipt.open('xb') as output:
            output.write(encoded(receipt))
        print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
