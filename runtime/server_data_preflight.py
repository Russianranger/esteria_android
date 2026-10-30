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
SERVER_NAMESPACE = 'EsteriaServerData'
SERVER_MANIFEST = 'manifest.properties'
SERVER_PACKAGE_SCOPE = 'esteria-user-supplied-server-data'
SERVER_DATA_GROUPS = ('dbc', 'dbc-continuations', 'maps', 'vmaps', 'mmaps', 'Cameras')
CONTINUATION = re.compile(r'([A-Za-z][A-Za-z0-9_]*)\.dbc([1-9])-([A-Za-z0-9_-]+)\Z')


def parse_server_manifest(raw: bytes) -> dict:
    """A package's declared source is not proof of its producer or coverage."""
    if not 0 < len(raw) <= 2048 or not raw.endswith(b'\n'):
        raise ValueError('bounded newline-terminated matched server manifest required')
    text = raw.decode('ascii')
    if '\r' in text.replace('\r\n', '\n') or any(ord(c) < 32 and c not in '\r\n' for c in text):
        raise ValueError('control character in matched server manifest')
    result = {}
    for line in text.splitlines():
        key, separator, value = line.partition('=')
        if not separator or not key or not value or key in result or any(ord(c) < 32 or ord(c) > 126 or c == '\\' for c in line):
            raise ValueError('invalid or duplicate matched server manifest field')
        result[key] = value
    if set(result) != {'format', 'scope', 'serverRevision', 'clientBuild', 'mode', 'provenance', 'clientProviderOrderSha256'} or \
            result['format'] != '1' or result['scope'] != SERVER_PACKAGE_SCOPE or \
            result['serverRevision'] != SERVER_REVISION or result['clientBuild'] != str(BUILD) or \
            result['mode'] not in ('complete', 'overlay') or result['provenance'] != 'user-supplied-format-checked' or \
            (result['clientProviderOrderSha256'] != 'none' and not re.fullmatch('[0-9a-f]{64}', result['clientProviderOrderSha256'])):
        raise ValueError('matched server manifest source, mode or provenance differs')
    return result


def data_file_checker(group: str, path: Path):
    suffix, name = path.suffix.lower(), path.name.lower()
    if group == 'dbc':
        if name.endswith('.dbc'): return check_dbc
        if re.fullmatch(r'component\.wow-[A-Za-z]{4}\.txt', path.name): return None
    elif group == 'dbc-continuations':
        if CONTINUATION.fullmatch(path.name): return check_dbc
        if path.name == 'wxl-dbc.manifest': return None
    elif group == 'maps' and suffix == '.map': return check_map
    elif group == 'vmaps' and (suffix in ('.vmtree', '.vmtile', '.vmo') or name == 'gameobjectmodels.dtree'): return check_vmap
    elif group == 'mmaps':
        if suffix == '.mmtile': return check_mmtile
        if suffix == '.mmap': return check_mmap
    elif group == 'Cameras' and suffix == '.m2': return check_camera
    raise ValueError('unrecognized matched server data file: ' + str(path))


def continuation_order(root: Path, base: Path) -> dict:
    """Mirror pinned WxlDbcScan ordering; refuse ambiguous or escaping input.

    Source sorts tier, explicit manifest position, project and base-table name.
    Unordered-map ties have no stable source order and need explicit manifest
    positions. No rows are merged or fabricated by this preflight.
    """
    entries = {}; manifest_positions = {}; base_headers = {}
    if base.is_dir():
        for path in files_bounded(base):
            if path.name.lower().endswith('.dbc'):
                check_dbc(path); header, _ = read_header(path, 20)
                signature = struct.unpack('<4s4I', header)[2:4]
                key = path.name.lower()
                if key in base_headers and base_headers[key] != signature:
                    raise ValueError('locale/base DBC field layout disagrees: ' + path.name)
                base_headers[key] = signature
    for path in files_bounded(root):
        relative = path.relative_to(root).as_posix()
        if path.name == 'wxl-dbc.manifest':
            if relative != 'wxl-dbc.manifest': raise ValueError('continuation manifest must be at the continuation root')
            continue
        matched = CONTINUATION.fullmatch(path.name)
        if not matched: raise ValueError('unrecognized continuation filename: ' + relative)
        check_dbc(path); header, _ = read_header(path, 20)
        signature = struct.unpack('<4s4I', header)[2:4]
        table, tier, project = matched.groups(); base_name = table + '.dbc'
        if base_name.lower() in base_headers and base_headers[base_name.lower()] != signature:
            raise ValueError('continuation field count or record size differs from base: ' + relative)
        entries[relative] = (int(tier), project.lower(), base_name.lower())
    manifest = root / 'wxl-dbc.manifest'
    if manifest.exists() or manifest.is_symlink():
        if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 1024*1024:
            raise ValueError('bounded regular continuation manifest required')
        with manifest.open('r', encoding='ascii', newline='') as stream:
            manifest_text = stream.read(1024*1024+1)
        if len(manifest_text) > 1024*1024: raise ValueError('continuation manifest grew beyond bound')
        if any(ord(c) > 126 or ord(c) < 32 and c not in '\n\r\t' for c in manifest_text):
            raise ValueError('continuation manifest requires ASCII without other control characters')
        position = 0
        for line in manifest_text.split('\n'):
            line = line.rstrip(' \t\r').lstrip(' \t')
            if not line or line.startswith('#'): continue
            if line.startswith('/') or '\\' in line or ':' in line or any(p in ('', '.', '..') for p in line.split('/')) or \
                    any(ord(c) < 32 or ord(c) > 126 for c in line) or line not in entries:
                raise ValueError('continuation manifest references an unsafe or absent file')
            if line not in manifest_positions: manifest_positions[line] = position
            position += 1
    keys = {}
    for name, (tier, project, table) in entries.items():
        key = (tier, manifest_positions.get(name, 0x7fffffff), project, table)
        if key in keys: raise ValueError('ambiguous continuation order; list both files in wxl-dbc.manifest')
        keys[key] = name
    return {'files_checked': len(entries), 'order': [keys[key] for key in sorted(keys)],
            'ordering': 'tier-then-manifest-position-then-project-then-base-table',
            'base_field_layouts_checked': len(base_headers), 'rows_merged': False}


def check_server_package(root: Path, selected: dict) -> dict:
    """Validate all supplied files, including the server's separate DBC folder."""
    if root.is_symlink() or not root.is_dir(): raise ValueError('matched server data root required')
    allowed = SERVER_DATA_GROUPS if selected['mode'] == 'complete' else ('dbc', 'dbc-continuations')
    groups = {}; recognized = 0
    for child in root.iterdir():
        if child.name not in allowed or child.is_symlink() or not child.is_dir():
            raise ValueError('unsupported matched server data group: ' + child.name)
        checked = 0
        for path in files_bounded(child):
            if not path.is_file(): raise ValueError('regular matched server file required')
            checker = data_file_checker(child.name, path)
            if checker: checker(path); checked += 1
            elif path.stat().st_size > (1024*1024 if path.name == 'wxl-dbc.manifest' else 65536):
                raise ValueError('matched server ancillary file exceeds bound')
        groups[child.name] = checked; recognized += checked
    if not recognized: raise ValueError('matched server package contains no recognized data')
    if selected['mode'] == 'complete' and not all(groups.get(name, 0) > 0 for name in ('dbc', 'maps', 'vmaps', 'mmaps', 'Cameras')):
        raise ValueError('complete matched server package requires all five data groups')
    if 'dbc-continuations' in groups: continuation_order(root / 'dbc-continuations', root / 'dbc')
    return {'groups': groups, 'provenance': 'user-supplied-format-checked', 'worldQualified': False}


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
    if (root / 'dbc-continuations').exists() or (root / 'dbc-continuations').is_symlink():
        try:
            report['continuations'] = continuation_order(root / 'dbc-continuations', root / 'dbc')
        except (ValueError, OSError) as failure:
            error('dbc-continuations', failure)
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
