#!/usr/bin/env python3
"""Test-only Python producers for Android receipt-consumer regression tests.

The production data/shader coordinators create their real metadata, canonical
hashes, receipts and activation pointers. Only source-qualified native tools and
shader compilation are replaced at their execution boundary with tiny synthetic
format files. These fixtures are not game assets, extraction or GPU evidence.
No fixture is packaged in the main application.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from runtime import server_data_generation as data
from runtime import shader_generation as storage
from runtime import stock_shader_generation as shader

IMPORT = 'a' * 64


def identity(path):
    raw = path.read_bytes()
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def imported(root):
    game = root / 'game'
    selected = game / 'generations' / IMPORT
    (selected / 'data/Data/enUS').mkdir(parents=True)
    (selected / 'data/Data/common.MPQ').write_bytes(b'X')
    (selected / 'data/Data/enUS/locale-enUS.MPQ').write_bytes(b'Y')
    (selected / 'complete').write_text('format=1\nclientBuild=12340\nrequest=' + IMPORT + '\nsource=' + 'b' * 64 + '\n')
    (selected / 'journal.tsv').write_bytes(b'TEST_ONLY_SYNTHETIC_IMPORT_METADATA\n')
    (game / 'current').write_text(IMPORT + '\n')
    return game


def native_fixture(command, cwd, log, timeout, **kwargs):
    """Synthetic structural output, never actual extraction/navigation."""
    name = Path(command[0]).name
    if command[1:] == ['--esteria-order-capabilities']:
        log.write_bytes(data.CAPABILITY + b'\n')
        return
    log.write_bytes(b'TEST_ONLY_SYNTHETIC_TOOL_OUTPUT\n')
    if name == 'map_extractor':
        for folder in ('maps', 'dbc', 'Cameras'):
            (cwd / folder).mkdir()
        (cwd / 'maps/0000000.map').write_bytes(struct.pack('<4s10I', b'MAPS', 9, 12340, *([0] * 8)))
        (cwd / 'dbc/Map.dbc').write_bytes(struct.pack('<4s4I', b'WDBC', 0, 66, 264, 1) + b'\0')
        (cwd / 'Cameras/fixture.m2').write_bytes(b'MD20' + struct.pack('<I', 264))
    elif name == 'vmap4_extractor':
        (cwd / 'Buildings').mkdir()
        (cwd / 'Buildings/dir_bin').write_bytes(b'TEST_ONLY_RAW_FORMAT')
    elif name == 'vmap4_assembler':
        (cwd / 'vmaps/000.vmtree').write_bytes(b'VMAP_4.8')
    elif name == 'mmaps_generator':
        (cwd / 'mmaps').mkdir()
        (cwd / 'mmaps/000.mmap').write_bytes(b'\0' * 28)
    else:
        raise AssertionError('Unrecognized fixture executable')


def data_fixture(root):
    game = imported(root)
    tools = root / 'tools'
    tools.mkdir()
    work = root / 'work'
    work.mkdir()
    selection = dict(formatVersion=1, clientRevision=data.CLIENT_REVISION,
        serverRevision=data.formats.SERVER_REVISION,
        files={'bin/fixture-only': dict(bytes=1, sha256='c' * 64)},
        orderedSourceReceipt=dict(bytes=1, sha256='d' * 64))
    selected = work / 'data-tools-selection.json'
    selected.write_bytes(storage.encoded(selection))
    selection_hash = identity(selected)['sha256']
    plan = dict(scope=data.order.SCHEMA, priorityOrder='highest-first', effectiveLocale='enUS',
        configuredLocale='enUS', profile=data.PROFILE,
        providers=[dict(rank=0, kind='mpq', path='Data/common.MPQ', prefix='', bytes=1, sha256='c' * 64)])
    with patch.object(data, 'tools_verified', return_value=selection_hash), \
            patch.object(data.order, 'plan', return_value=plan), \
            patch.object(data, 'execute', side_effect=native_fixture), redirect_stdout(io.StringIO()):
        receipt = data.generate(work / 'server-data', game, IMPORT, tools, selection, 'enUS')
    # Reentry must preserve the exact key and completed bytes with no tool call.
    with patch.object(data, 'tools_verified', return_value=selection_hash), \
            patch.object(data.order, 'plan', side_effect=AssertionError('Completed data must not replan')), \
            patch.object(data, 'execute', side_effect=AssertionError('Completed data must not reextract')):
        assert data.generate(work / 'server-data', game, IMPORT, tools, selection, 'enUS') == receipt
    return dict(generation=receipt['generation'], helperGeneration=data.preparation_helper_generation(),
        toolSelectionSha256=selection_hash, clientRevision=data.CLIENT_REVISION,
        serverRevision=data.formats.SERVER_REVISION, locale='enUS')


def shader_fixture(root):
    game = imported(root)
    tools = root / 'tools'
    tools.mkdir()
    work = root / 'work'
    work.mkdir()
    manifest = '3' * 64

    def translate(command, log, timeout, **kwargs):
        output = Path(command[command.index('--out') + 1])
        lines = []
        for kind, digest, model, profile in (('vertex', '4' * 32, 0, 'vs_3_0'), ('pixel', '5' * 32, 4, 'ps_3_0')):
            (output / kind).mkdir()
            raw = struct.pack('<9I', 0x07230203, 0x00010000, 0, 2, 0, (4 << 16) | 15, model, 1, 0)
            (output / kind / (digest + '.spv')).write_bytes(raw)
            lines.append('record ' + digest + ' ' + kind + ' ' + profile + ' ' + kind + '/' + digest + '.spv vconst=64 pconst=20')
        (output / 'manifest.txt').write_text('\n'.join(lines) + '\n')
        (output / 'index.txt').write_bytes(b'TEST_ONLY_SYNTHETIC_SHADER_INDEX\n')
        log.write_bytes(b'TEST_ONLY_TRANSLATOR_BOUNDARY\n')

    with patch.object(shader, 'tool_identity', return_value=manifest), \
            patch.object(shader, 'execute', side_effect=translate):
        receipt = shader.generate(work / 'shaders', game, IMPORT, tools, data.CLIENT_REVISION, 'enUS')
    with patch.object(shader, 'tool_identity', return_value=manifest), \
            patch.object(shader, 'execute', side_effect=AssertionError('Completed shaders must not recompile')):
        assert shader.generate(work / 'shaders', game, IMPORT, tools, data.CLIENT_REVISION, 'enUS') == receipt
    return dict(generation=receipt['generation'], toolManifestSha256=manifest,
        clientRevision=data.CLIENT_REVISION, locale='enUS')


def prepare(output):
    output = output.absolute()
    if output.exists():
        raise ValueError('Fixture output already exists')
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='esteria-python-receipts-') as temporary:
        staging = Path(temporary)
        data_root, shader_root = staging / 'data', staging / 'shader'
        data_root.mkdir()
        shader_root.mkdir()
        details = dict(data=data_fixture(data_root), shader=shader_fixture(shader_root))
        for name in ('data', 'shader'):
            shutil.copytree(staging / name / 'game', output / name / 'game')
            shutil.copytree(staging / name / 'work', output / name / 'work')
    # Locks are ephemeral ownership, not receipt inputs or test assets. Android
    # AAPT deliberately excludes dotfiles; consumers acquire their own leases.
    for path in output.rglob('.setup.lock'):
        path.unlink()
    for kind, field_changes in (
            ('data', {'contentProfile': 'esteria-custom', 'preparationHelperGeneration': '0' * 64,
                      'clientRevision': '0' * 40, 'serverRevision': '0' * 40,
                      'importGeneration': '0' * 64, 'locale': 'enGB', 'threads': 2,
                      'toolSelectionSha256': '0' * 64, 'formatVersion': True}),
            ('shader', {'contentProfile': 'esteria-custom', 'preparationHelperSha256': '0' * 64,
                        'clientRevision': '0' * 40, 'importGeneration': '0' * 64,
                        'locale': 'enGB', 'toolManifestSha256': '0' * 64, 'formatVersion': True})):
        selected = output / kind / 'work' / ('server-data' if kind == 'data' else 'shaders') / 'generations' / details[kind]['generation']
        inputs = json.loads((selected / 'receipt.json').read_bytes())['inputs']
        variants = []
        for field, value in field_changes.items():
            changed = copy.deepcopy(inputs)
            changed[field] = value
            variants.append(dict(name=field, inputs=changed,
                generation=hashlib.sha256(storage.encoded(changed)).hexdigest()))
        for label in ('ancestry', 'unknown-field'):
            changed = copy.deepcopy(inputs)
            if label == 'ancestry':
                changed['importMetadata'][IMPORT + '/journal.tsv']['sha256'] = '0' * 64
            else:
                changed['unexpectedField'] = 1
            variants.append(dict(name=label, inputs=changed,
                generation=hashlib.sha256(storage.encoded(changed)).hexdigest()))
        if kind == 'shader':
            changed = copy.deepcopy(inputs)
            changed['preparationHelperFiles']['stock_shader_translate.py']['sha256'] = '0' * 64
            variants.append(dict(name='helper-file', inputs=changed,
                generation=hashlib.sha256(storage.encoded(changed)).hexdigest()))
        (output / (kind + '-mutants.json')).write_bytes(storage.encoded(variants))
    vectors = [
        {'slash/key': '</literal/path>', 'backslash': '\\path\\file', 'quotes': '\"quoted\"'},
        {'control': ''.join(chr(n) for n in range(32)) + chr(127)},
        {'unicode': 'caf\u00e9\u2028\U0001f600', '\U00010000': 1, '\ue000': 2, 'nested': {'é/field': '中文'}},
        {'integers': {'minimum': -(1 << 63), 'maximum': (1 << 63) - 1, 'beyondJavascriptExact': 9007199254740993}},
        {'unpaired': '\ud800/\udfff'},
        {'boolean': {'true': True, 'false': False}},
    ]
    (output / 'codec-vectors.json').write_bytes(storage.encoded([
        dict(value=value, canonical=storage.encoded(value)[:-1].decode('ascii'),
             sha256=hashlib.sha256(storage.encoded(value)).hexdigest()) for value in vectors]))
    records = {path.relative_to(output).as_posix(): identity(path)
               for path in sorted(output.rglob('*')) if path.is_file()}
    assert len(records) < 64 and sum(row['bytes'] for row in records.values()) < 1 << 20
    metadata = dict(formatVersion=1, scope='synthetic-production-python-to-android-receipt-consumers',
        importGeneration=IMPORT, **details, files=records,
        productionPythonGenerationExecuted=True, nativeToolExecutionReplaced=True,
        shaderCompilerExecutionReplaced=True, gameplayQualified=False, thorQualified=False)
    (output / 'fixture.json').write_bytes(storage.encoded(metadata))
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().output), sort_keys=True))
