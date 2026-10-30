#!/usr/bin/env python3
"""Bounded-read offline data-format preflight for the pinned Esteria server.

This checks headers and declared lengths, not gameplay completeness or client/server
DBC row equivalence. No downloads, extraction, repairs or writes to imported content.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import struct
from typing import Callable

SERVER_REVISION = 'f35f04d01689f034778e3474b3c820092f51e461'
BUILD = 12340


def read_header(path: Path, size: int) -> tuple[bytes, int]:
    if path.is_symlink() or not path.is_file():
        raise ValueError('regular file required; symbolic links are unsupported')
    with path.open('rb') as stream:
        total = os.fstat(stream.fileno()).st_size
        header = stream.read(size)
    if len(header) != size:
        raise ValueError(f'truncated header: need {size} bytes, got {len(header)}')
    return header, total


def check_dbc(path: Path) -> None:
    header, size = read_header(path, 20)
    magic, rows, fields, stride, strings = struct.unpack('<4s4I', header)
    if magic != b'WDBC' or not fields or not stride:
        raise ValueError('expected WDBC header with nonzero field count and row stride')
    expected = 20 + rows * stride + strings
    if size != expected:
        raise ValueError(f'DBC declared length {expected} differs from file length {size}')


def check_map(path: Path) -> None:
    header, size = read_header(path, 44)
    magic, version, build, *chunks = struct.unpack('<4s10I', header)
    if magic != b'MAPS' or version != 9 or build != BUILD:
        raise ValueError(f'expected MAPS version 9 build {BUILD}, got {magic!r}/{version}/{build}')
    ranges = []
    for offset, length in zip(chunks[::2], chunks[1::2]):
        if length:
            if offset < 44 or offset + length > size:
                raise ValueError('map chunk lies outside the file')
            ranges.append((offset, offset + length))
    ranges.sort()
    if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
        raise ValueError('map chunks overlap')


def check_vmap(path: Path) -> None:
    header, _ = read_header(path, 8)
    if header != b'VMAP_4.8':
        raise ValueError(f'expected assembled VMAP_4.8, got {header!r}')


def check_mmtile(path: Path) -> None:
    header, size = read_header(path, 56)
    magic, detour, version, payload = struct.unpack_from('<4I', header)
    if (magic, detour, version) != (0x4D4D4150, 7, 20):
        raise ValueError('expected MMAP magic, Detour version 7, mmap version 20')
    if not payload or payload != size - 56:
        raise ValueError('mmap tile payload length does not match its 56-byte header')


def check_mmap(path: Path) -> None:
    _, size = read_header(path, 28)
    if size != 28:
        raise ValueError('expected 28-byte dtNavMeshParams for a map index')


def check_camera(path: Path) -> None:
    header, _ = read_header(path, 8)
    if header[:4] != b'MD20':
        raise ValueError('expected legacy MD20 camera model')


def files_bounded(root: Path):
    """Walk names only. No content hashing and no symlink traversal."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError('required directory missing or is a symbolic link')
    def failed(error):
        raise error
    count = 0
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed):
        if len(Path(directory).relative_to(root).parts) > 16:
            raise ValueError('server data directory depth exceeds bound')
        seen = set()
        for name in dirs + files:
            count += 1
            if count > 300000:
                raise ValueError('server data entry count exceeds bound')
            folded = name.casefold()
            if folded in seen:
                raise ValueError(f'case-colliding names under {Path(directory).relative_to(root)}')
            seen.add(folded)
            if (Path(directory) / name).is_symlink():
                raise ValueError(f'symbolic link found: {(Path(directory) / name).relative_to(root)}')
        for name in files:
            yield Path(directory) / name


def check_server_data(root: Path) -> dict:
    # dbcN-project continuation files use the same WDBC format, not just *.dbc.
    groups: dict[str, Callable[[Path], Callable | None]] = {
        'dbc': lambda p: check_dbc if re.search(r'\.dbc(?:[1-9]-[^/]+)?$', p.name, re.I) else None,
        'maps': lambda p: check_map if p.suffix.lower() == '.map' else None,
        'vmaps': lambda p: check_vmap if p.suffix.lower() in ('.vmtree', '.vmtile', '.vmo')
        or p.name.lower() == 'gameobjectmodels.dtree' else None,
        'mmaps': lambda p: check_mmtile if p.suffix.lower() == '.mmtile'
        else check_mmap if p.suffix.lower() == '.mmap' else None,
        'Cameras': lambda p: check_camera if p.suffix.lower() == '.m2' else None,
    }
    report = {'server_revision': SERVER_REVISION, 'expected_client_build': BUILD,
              'validation': 'file headers and declared lengths only', 'groups': {},
              'error_count': 0, 'errors': []}

    def error(path, message):
        report['error_count'] += 1
        # A damaged archive can produce many thousands of files; keep reports bounded.
        if len(report['errors']) < 100:
            report['errors'].append({'path': str(path), 'error': str(message)})
    for name, classifier in groups.items():
        checked = 0
        try:
            for path in files_bounded(root / name):
                checker = classifier(path)
                if checker:
                    checked += 1
                    try:
                        checker(path)
                    except (ValueError, OSError) as failure:
                        error(path.relative_to(root), failure)
            if not checked:
                error(name, 'no recognized data files')
        except (ValueError, OSError) as failure:
            error(name, failure)
        report['groups'][name] = {'files_checked': checked}
    report['checks_passed'] = report['error_count'] == 0
    report['gameplay_qualified'] = False
    report['limitations'] = ['Does not establish map coverage, DBC schema/row compatibility or custom asset closure.',
                             'Cameras and VMAP checks verify magic only; payload parsing remains the server loader gate.',
                             'Use extractors from the pinned server against the same effective client MPQ stack.',
                             'Run again after content changes; the importer owns the resumable copy/hash journal.']
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-data', type=Path, required=True)
    args = parser.parse_args(argv)
    report = check_server_data(args.server_data)
    print(json.dumps(report, indent=2))
    return 0 if report['checks_passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
