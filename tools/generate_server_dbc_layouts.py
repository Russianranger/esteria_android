#!/usr/bin/env python3
"""Derive present-file WDBC header layouts from the exact locked server source.

No game data is generated or required. Missing files are not inferred to be a
startup failure: this server overlays every active DBC store from a SQL table.
On-disk columns use one byte for b/X and four for all other supported fields;
DBCFileLoader::GetFormatRecordSize instead measures native decoded structures.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pprint
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'runtime/server_data_preflight.py'
START = '# BEGIN GENERATED PINNED SERVER DBC LAYOUTS\n'
END = '# END GENERATED PINNED SERVER DBC LAYOUTS\n'
STORES = 'src/server/game/DataStores/DBCStores.cpp'
FORMATS = 'src/server/shared/DataStores/DBCfmt.h'
LOADER = 'src/common/DataStores/DBCFileLoader.cpp'
FIELD_TYPES = 'src/common/DataStores/DBCFileLoader.h'
OVERLAY = 'src/server/shared/DataStores/DBCStore.cpp'
REGISTRY = 'modules/mod-wxl-dbc/src/WxlDbcRegistry.cpp'
SOURCE_FILES = (STORES, FORMATS, LOADER, FIELD_TYPES, OVERLAY, REGISTRY)


def require(condition, reason):
    if not condition: raise ValueError(reason)


def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def uncomment(source):
    # These fixed declarations have no comment delimiters in string literals.
    return re.sub(r'//[^\n]*|/\*.*?\*/', '', source, flags=re.S)


def derive(stores_source, formats_source, registry_source):
    stores_source, formats_source, registry_source = map(uncomment,
        (stores_source, formats_source, registry_source))
    formats = dict(re.findall(r'char\s+constexpr\s+(\w+)\[\]\s*=\s*"([nidxfsbX]+)"\s*;', formats_source))
    stores = dict(re.findall(r'DBCStorage\s*<[^;>]+>\s+(\w+)\((\w+)\)\s*;', stores_source))
    calls = re.findall(r'^\s*LOAD_DBC\(\s*(\w+)\s*,\s*"([A-Za-z0-9_]+\.dbc)"\s*,\s*"([a-z0-9_]+)"\s*\)\s*;',
        stores_source, re.M)
    require(calls and len(re.findall(r'\bLOAD_DBC\s*\(', stores_source)) == len(calls) + 1,
        'active-DBC-loader-declaration-not-understood')
    continuations = re.findall(r'^\s*WXL_DBC\(\s*(\w+)\s*,\s*"([A-Za-z0-9_]+\.dbc)"\s*\)\s*;', registry_source, re.M)
    require(continuations and len(re.findall(r'\bWXL_DBC\s*\(', registry_source)) == len(continuations) + 1,
        'active-continuation-declaration-not-understood')
    result = {}
    for store, filename, sql_table in calls:
        require(store in stores and stores[store] in formats and filename.casefold() not in result,
            'active-DBC-store-format-or-name-not-understood')
        fmt = formats[stores[store]]
        result[filename.casefold()] = (len(fmt), sum(1 if column in 'bX' else 4 for column in fmt), sql_table)
    require(len({filename.casefold() for _, filename in continuations}) == len(continuations) and
        all(filename.casefold() in result and (store, filename) in [(s, f) for s, f, _ in calls]
            for store, filename in continuations), 'continuation-store-binding-differs')
    return dict(sorted(result.items())), sorted(filename.casefold() for _, filename in continuations)


def locked_sources(server, root=ROOT):
    server, root = Path(server).resolve(), Path(root)
    lock = json.loads((root / 'sources.lock.json').read_bytes())['sources']['server']
    require(re.fullmatch('[0-9a-f]{40}', lock['commit']) and
        lock['url'] == 'https://github.com/Russianranger/EsteriaWoW.git', 'exact-locked-server-source-required')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(server), *args], stderr=subprocess.DEVNULL, timeout=30)
    require(git('rev-parse', 'HEAD').decode().strip() == lock['commit'], 'server-checkout-revision-differs')
    raw = {}
    for name in SOURCE_FILES:
        canonical = git('show', lock['commit'] + ':' + name)
        require(0 < len(canonical) <= 512 << 10, 'server-layout-source-size-bound')
        with (server / name).open('rb') as incoming: actual = incoming.read(len(canonical) + 1)
        require(actual == canonical, 'server-layout-source-file-modified:' + name)
        raw[name] = canonical
    # Current adaptations do not change the DBC loader/schema files. A future
    # patch touching them requires an explicit adapted-source generator update.
    for patch in lock['patches']:
        body = (root / patch['path']).read_bytes()
        require(identity(body)['sha256'] == patch['sha256'], 'server-layout-patch-identity-differs')
        prefix = patch.get('submodule', '')
        changed = [((prefix + '/') if prefix else '') + name for name in
            re.findall(r'^\+\+\+ b/(.+)$', body.decode('utf-8'), re.M)]
        require(not set(changed) & set(SOURCE_FILES), 'server-layout-source-adaptation-needs-explicit-support')
    loader = raw[LOADER].decode('utf-8'); types = raw[FIELD_TYPES].decode('utf-8')
    require("fmt[i - 1] == 'b' || fmt[i - 1] == 'X'" in loader and
        'fieldsOffset[i] += sizeof(uint8)' in loader and 'fieldsOffset[i] += sizeof(uint32)' in loader and
        re.search(r"FT_NA_BYTE\s*=\s*'X'", types) and re.search(r"FT_BYTE\s*=\s*'b'", types),
        'server-on-disk-byte-packing-changed')
    require('if (dbTable)' in raw[STORES].decode('utf-8') and
        'storage.LoadFromDB(dbTable, storage.GetFormat())' in raw[STORES].decode('utf-8') and
        'if (storage.GetNumRows())' in raw[STORES].decode('utf-8'), 'server-DBC-SQL-fallback-changed')
    metadata = dict(serverRevision=lock['commit'], serverPatches=lock['patches'],
        sourceFiles={name: identity(body) for name, body in sorted(raw.items())})
    return raw, metadata


def generated_block(server, root=ROOT):
    raw, metadata = locked_sources(server, root)
    layouts, continuations = derive(*(raw[name].decode('utf-8') for name in (STORES, FORMATS, REGISTRY)))
    return (START + '# Derived by tools/generate_server_dbc_layouts.py; do not edit this block.\n'
        '# Values: WDBC field count, on-disk row bytes, SQL overlay table.\n'
        '# They are not decoded C++ structure sizes or mandatory file lists.\n'
        + 'DBC_LAYOUT_SOURCE = ' + pprint.pformat(metadata, width=112, sort_dicts=True) + '\n'
        + 'DBC_LAYOUTS = ' + pprint.pformat(layouts, width=112, sort_dicts=True) + '\n'
        + 'DBC_CONTINUATION_STORES = ' + pprint.pformat(tuple(continuations), width=112) + '\n' + END)


def update(text, block):
    require(text.count(START) == text.count(END) == 1, 'generated-DBC-layout-block-markers-required')
    start, end = text.index(START), text.index(END) + len(END)
    require(start < end, 'generated-DBC-layout-marker-order')
    return text[:start] + block + text[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    text = args.output.read_text(); expected = update(text, generated_block(args.server))
    if args.check: require(text == expected, 'generated-DBC-layouts-out-of-date')
    else: args.output.write_text(expected)
    print(json.dumps(dict(scope='pinned-server-present-DBC-layout-generation-only',
        checked=args.check, gameplayQualified=False)))


if __name__ == '__main__': main()
