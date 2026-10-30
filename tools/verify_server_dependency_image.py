#!/usr/bin/env python3
"""Read back a fresh native container built from the verified dependency archive.

Mount this file and the host-verified context receipt read-only. This checks the
actual image metadata and ELF bytes; it starts no MySQL/server and writes no state.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import struct

COMPONENTS = {'mysql': '/usr/bin/mysql', 'mysqld': '/usr/sbin/mysqld', 'python3': '/usr/bin/python3.12'}
PRIVATE_TREES = ('var/lib/mysql', 'esteria-state', 'esteria-content', 'esteria-server')
MAX_METADATA = 2 * 1024**2
MAX_COMPONENT = 512 * 1024**2


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


@contextmanager
def regular(path):
    path = Path(path).absolute()
    for parent in path.parents:
        require(stat.S_ISDIR(parent.lstat().st_mode), 'dependency-image-linked-parent')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), 'dependency-image-not-regular')
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            yield stream
    finally:
        if descriptor is not None:
            os.close(descriptor)


def metadata(path):
    with regular(path) as stream:
        raw = stream.read(MAX_METADATA + 1)
    require(len(raw) <= MAX_METADATA, 'dependency-image-metadata-bound')
    return json.loads(raw), dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def component(path, expected):
    require(type(expected.get('bytes')) is int and 64 <= expected['bytes'] <= MAX_COMPONENT and
            re.fullmatch('[0-9a-f]{64}', expected.get('sha256', '')) and
            expected.get('elfMachine') == 183, 'dependency-image-component-contract')
    with regular(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        require(size == expected['bytes'], 'dependency-image-component-size')
        header = stream.read(64)
        require(header[:7] == b'\x7fELF\x02\x01\x01' and struct.unpack_from('<H', header, 18)[0] == 183,
                'dependency-image-component-architecture')
        stream.seek(0)
        digest = hashlib.sha256()
        remaining = size
        while remaining:
            block = stream.read(min(128 * 1024, remaining))
            require(block, 'dependency-image-component-short-read')
            remaining -= len(block)
            digest.update(block)
        require(not stream.read(1) and digest.hexdigest() == expected['sha256'],
                'dependency-image-component-hash')
    return dict(bytes=size, sha256=digest.hexdigest(), elfMachine=183)


def running_python_matches(path):
    return os.path.samefile('/proc/self/exe', path)


def verify(receipt_path, root=Path('/')):
    require(platform.system() == 'Linux' and platform.machine().lower() in ('aarch64', 'arm64'),
            'native-arm64-dependency-image-required')
    root = Path(root).absolute()
    expected, receipt_identity = metadata(receipt_path)
    require(expected.get('formatVersion') == 1 and
            expected.get('scope') == 'verified-server-dependency-image-context-only' and
            expected.get('architecture') == 'arm64' and
            expected.get('completeSourceCompanionReverified') is True and
            expected.get('archiveGraphAndComponentsReverified') is True and
            expected.get('serverIncluded') is False and expected.get('databaseInitialized') is False,
            'verified-dependency-image-context-receipt-required')
    actual, identity = metadata(root / 'etc/esteria-server-runtime.json')
    require(identity == {key: expected['runtimeMetadata'][key] for key in ('bytes', 'sha256')},
            'dependency-image-runtime-metadata-changed')
    require(actual.get('scope') == 'built-linux-arm64-server-dependencies' and
            actual.get('architecture') == 'arm64' and
            actual.get('sourceLockSha256') == expected['sourceLock']['sha256'] and
            actual.get('images') == expected.get('components') and
            actual.get('expectedMysqlSqlVersion') == expected.get('expectedMysqlSqlVersion'),
            'dependency-image-runtime-selection-changed')
    for flag in ('databaseInitialized', 'serverIncluded', 'serverExecuted', 'androidRuntimeQualified', 'gameLoginQualified'):
        require(actual.get(flag) is False, 'dependency-image-not-fresh:' + flag)
    require(set(actual['images']) == set(COMPONENTS), 'dependency-image-component-set')
    checked = {}
    for name, relative in COMPONENTS.items():
        row = actual['images'][name]
        require(row.get('path') == relative, 'dependency-image-component-path')
        checked[name] = component(root / relative[1:], row)
    require(running_python_matches(root / COMPONENTS['python3'][1:]),
            'dependency-image-running-interpreter-mismatch')
    for relative in PRIVATE_TREES:
        path = root / relative
        if os.path.lexists(path):
            require(stat.S_ISDIR(path.lstat().st_mode) and not any(path.iterdir()),
                    'dependency-image-private-state-present')
    return dict(formatVersion=1, scope='native-arm64-dependency-image-readback',
                contextReceipt=receipt_identity, runtimeMetadata=identity, components=checked,
                runtimeArchive=expected['archive'], sourceCompanion=expected['sourceCompanion'],
                expectedMysqlSqlVersion=actual['expectedMysqlSqlVersion'],
                actualImageMetadataAndElfHashesVerified=True, nativePythonExecuted=True,
                mysqlServerExecuted=False, databaseInitialized=False, esteriaServerExecuted=False,
                androidRuntimeQualified=False, gameplayQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context-receipt', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.context_receipt), indent=2))


if __name__ == '__main__':
    main()
