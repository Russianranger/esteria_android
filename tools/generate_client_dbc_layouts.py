#!/usr/bin/env python3
"""Reproduce the selected client's actual mandatory DBC disk layouts.

Read only exact Git source blobs, compare checkout bytes, select StaticDBLoadAll
calls plus Startup_Strings, and never generate game data or native structures.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REVISION = '471ee42faadf4a97a1d0a86989cf1452621f2dc5'
START = '# BEGIN GENERATED PINNED CLIENT DBC LAYOUTS\n'
END = '# END GENERATED PINNED CLIENT DBC LAYOUTS\n'


def derive(client):
    client = Path(client).resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(client), *args], timeout=30)
    if git('rev-parse', 'HEAD').decode().strip() != REVISION:
        raise ValueError('exact selected reconstructed-client checkout required')
    pins = {}
    def read(name):
        raw = git('show', REVISION + ':' + name)
        if (client / name).read_bytes() != raw:
            raise ValueError('client layout source checkout changed: ' + name)
        pins[name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        return raw.decode()
    source = read('WoW/Source/DB/DBClient/DBClient.cpp')
    read('WoW/Source/DB/WowClientDB.h'); read('WoW/Source/Client.cpp')
    start = source.index('static void StaticDBLoadAll('); end = source.index('\n}', start)
    used = re.findall(r'\((\w+)\.\*loadFunction\)', source[start:end])
    if len(used) != source[start:end].count('.*loadFunction') or len(used) != len(set(used)):
        raise ValueError('actual client DBC load declarations not understood')
    classes = {var: cls for cls, var in re.findall(r'WowClientDB(?:_RLE)?<(\w+)>\s+(\w+)\s*;', source)}
    classes['startup'] = 'Startup_StringsRec'; used.append('startup')
    layouts = {}
    for var in used:
        cls = classes[var]; base = 'WoW/Source/DB/Rec/' + cls
        header, definition = read(base + '.h'), read(base + '.cpp')
        columns = int(re.search(r's_numColumns\s*=\s*(\d+)', header)[1])
        stride = int(re.search(r's_rowSize\s*=\s*(\d+)', header)[1])
        filename = re.search(r'::GetFilename\(\).*?return "([^"]+)";', definition, re.S)[1].replace('\\\\', '\\')
        if filename in layouts:
            raise ValueError('duplicate actual client DBC filename')
        layouts[filename] = (columns, stride)
    metadata = {'clientRevision': REVISION, 'fileCount': len(pins), 'storeCount': len(layouts)}
    digest = hashlib.sha256((json.dumps(pins, sort_keys=True, separators=(',', ':')) + '\n').encode()).hexdigest()
    block = (START + 'CLIENT_DBC_LAYOUT_SOURCE = ' + repr(metadata) + '\n' +
            'CLIENT_DBC_LAYOUT_SOURCE_SHA256 = ' + repr(digest) + '\n' +
            'CLIENT_DBC_LAYOUTS = ' + repr(dict(sorted(layouts.items()))) + '\n' + END)
    return block, dict(metadata, files=pins)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    block, evidence = derive(args.client)
    output = ROOT / 'runtime/stock_content_inspection.py'
    source = output.read_text(); start = source.index(START); end = source.index(END, start) + len(END)
    expected = source[:start] + block + source[end:]
    evidence_path = ROOT / 'runtime/evidence/non-custom-client-dbc-source-layouts.json'
    raw = json.dumps(evidence, indent=2, sort_keys=True) + '\n'
    if args.check:
        if expected != source or evidence_path.read_text() != raw:
            raise ValueError('pinned client DBC layout projection differs')
    else:
        output.write_text(expected); evidence_path.write_text(raw)
    print('Verified ' + str(evidence['storeCount']) + ' client DBC layouts from ' + str(evidence['fileCount']) +
          ' exact source files; no game data or runtime execution')


if __name__ == '__main__':
    main()
