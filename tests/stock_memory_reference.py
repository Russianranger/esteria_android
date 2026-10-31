#!/usr/bin/env python3
"""Host RSS reference over encrypted synthetic MPQs; no owner-data or Android proof.

Fixture construction happens outside measured children. The old app helper is
retained verbatim from Git. Upstream reader bytes and provider manifests stay
unchanged. Reports must match exactly, including all 238 DBC/UI decisions.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import shutil
import struct
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BASELINE_REVISION = '3ff41e8292a08258f05f84e20317d04bb5c2eb4e'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def build(destination, client_source, hash_count, baseline_revision):
    if len(baseline_revision) != 40 or any(c not in '0123456789abcdef' for c in baseline_revision):
        raise ValueError('exact baseline commit SHA required')
    if hash_count < 32 or hash_count > 1 << 17 or hash_count & (hash_count - 1):
        raise ValueError('bounded power-of-two hash count required')
    if destination.exists():
        raise ValueError('fixture output must not already exist')
    destination.mkdir(parents=True)
    os.environ['ESTERIA_CLIENT_SOURCE'] = str(client_source.resolve())
    from tests.test_stock_content_inspection import RealPinnedMpqInspection
    from runtime import stock_content_inspection as stock
    fixture = RealPinnedMpqInspection('test_actual_reader_inspects_ui_dbcs_and_shader_inventory_without_claiming_authentication')
    fixture.setUp()
    try:
        shutil.copytree(fixture.tools, destination / 'tools')
        baseline = subprocess.run(['git', 'show', baseline_revision + ':runtime/stock_content_inspection.py'], cwd=ROOT,
                                  check=True, capture_output=True).stdout
        (destination / 'baseline_stock_content_inspection.py').write_bytes(baseline)
        original_path = client_source / 'Tools/VulkanShaders/tests/test_archive.py'
        namespace = {'__name__': '_large_mpq_fixture', '__file__': str(original_path)}
        with patch.dict('sys.modules', {'bls': __import__('_esteria_verified_stock_bls')}):
            exec(compile(original_path.read_text().replace('] * 32', '] * ' + str(hash_count)),
                         'large-encrypted-mpq-fixture', 'exec'), namespace)
        large = namespace['make_mpq']
        variants = {}
        for label, generation in (('stock', 'a' * 64), ('unknown-overlay', 'b' * 64),
                                  ('excluded-optional-over-budget', 'c' * 64)):
            at = destination / 'game/generations' / generation
            source = at / 'data'; source.mkdir(parents=True)
            providers = ('Data/common.MPQ', 'Data/common-2.MPQ', 'Data/common-3.MPQ',
                         'Data/expansion.MPQ', 'Data/lichking.MPQ', 'Data/patch.MPQ',
                         'Data/enUS/locale-enUS.MPQ', 'Data/enUS/speech-enUS.MPQ')
            for name in providers:
                files = fixture.files if name == 'Data/common.MPQ' else {}
                large(source / name, [(name, raw, 0) for name, raw in files.items()])
            fixture.make_mpq(source / 'Data/patch-Optional.MPQ', [('Esteria\\EsteriaNaga.bin',
                struct.pack('<3I', 0x314D4845, 1, 0), 0)])
            for name in ('Data/wow-update-base-12340.MPQ', 'Installer.MPQ', 'Data/installer.MPQ/help.txt'):
                target = source / name; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'ignored ancillary synthetic file')
            if label == 'unknown-overlay':
                fixture.make_mpq(source / 'Data/patch-Unknown.MPQ', [('Interface\\Icons\\Generic.blp', b'unclassified', 0)])
            if label == 'excluded-optional-over-budget':
                for index in range(9):
                    large(source / ('Data/patch-Optional-Large-' + str(index) + '.MPQ'),
                          [('Esteria\\EsteriaNaga.bin', struct.pack('<3I', 0x314D4845, 1, 0), 0)])
            rows = []
            for path in sorted(source.rglob('*')):
                if path.is_file():
                    name = path.relative_to(source).as_posix()
                    rows.append(base64.b64encode(name.encode()).decode() + '\t' + str(path.stat().st_size) + '\t0\t' +
                                hashlib.sha256(path.read_bytes()).hexdigest() + '\n')
            (at / 'journal.tsv').write_text(''.join(rows))
            variants[label] = {'source': str(source.resolve()), 'generation': generation}
        config = {'clientRevision': stock.CLIENT_REVISION, 'tools': str((destination / 'tools').resolve()),
                  'variants': variants, 'largeProviderCount': 8, 'hashEntriesPerLargeProvider': hash_count,
                  'excludedLargeOptionalProviders': 9,
                  'baselineHelperSha256': hashlib.sha256(baseline).hexdigest(),
                  'baselineRevision': baseline_revision,
                  'scope': 'encrypted synthetic MPQ host memory reference; handcrafted import journals; no owner assets'}
        (destination / 'fixture.json').write_bytes(encoded(config))
        print(json.dumps({'fixture': str(destination.resolve()), 'hashEntries': 8 * hash_count}))
    finally:
        fixture.doCleanups()


def enrich(fixture_root, client_source):
    """Add the over-physical-budget optional case to an existing reference."""
    config = json.loads((fixture_root / 'fixture.json').read_text())
    label = 'excluded-optional-over-budget'
    if label in config['variants']:
        raise ValueError('optional fixture already present')
    os.environ['ESTERIA_CLIENT_SOURCE'] = str(client_source.resolve())
    from tests.test_stock_content_inspection import RealPinnedMpqInspection
    fixture = RealPinnedMpqInspection('test_actual_reader_inspects_ui_dbcs_and_shader_inventory_without_claiming_authentication')
    fixture.setUp()
    try:
        original_path = client_source / 'Tools/VulkanShaders/tests/test_archive.py'
        namespace = {'__name__': '_large_optional_mpq_fixture', '__file__': str(original_path)}
        with patch.dict('sys.modules', {'bls': __import__('_esteria_verified_stock_bls')}):
            exec(compile(original_path.read_text().replace('] * 32', '] * ' + str(config['hashEntriesPerLargeProvider'])),
                         'large-optional-encrypted-mpq-fixture', 'exec'), namespace)
        generation = 'c' * 64
        at = fixture_root / 'game/generations' / generation
        source = at / 'data'
        shutil.copytree(Path(config['variants']['stock']['source']), source)
        for index in range(9):
            namespace['make_mpq'](source / ('Data/patch-Optional-Large-' + str(index) + '.MPQ'),
                                  [('Esteria\\EsteriaNaga.bin', struct.pack('<3I', 0x314D4845, 1, 0), 0)])
        rows = []
        for path in sorted(source.rglob('*')):
            if path.is_file():
                name = path.relative_to(source).as_posix()
                rows.append(base64.b64encode(name.encode()).decode() + '\t' + str(path.stat().st_size) + '\t0\t' +
                            hashlib.sha256(path.read_bytes()).hexdigest() + '\n')
        (at / 'journal.tsv').write_text(''.join(rows))
        config['variants'][label] = {'source': str(source.resolve()), 'generation': generation}
        config['excludedLargeOptionalProviders'] = 9
        (fixture_root / 'fixture.json').write_bytes(encoded(config))
        print(json.dumps({'fixture': str(fixture_root), 'addedVariant': label, 'largeOptionalProviders': 9}))
    finally:
        fixture.doCleanups()


def child(fixture, mode, variant, result):
    config = json.loads((fixture / 'fixture.json').read_text())
    if mode == 'baseline':
        name = 'runtime._stock_memory_baseline'
        specification = importlib.util.spec_from_file_location(name, fixture / 'baseline_stock_content_inspection.py')
        stock = importlib.util.module_from_spec(specification)
        sys.modules[name] = stock
        specification.loader.exec_module(stock)
    else:
        from runtime import stock_content_inspection as stock
    selected = config['variants'][variant]
    began = time.monotonic()
    report = stock.inspect(Path(selected['source']), Path(config['tools']), config['clientRevision'],
                           'enUS', selected['generation'])
    proof = {'mode': mode, 'variant': variant, 'peakRssKiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
             'elapsedSeconds': round(time.monotonic() - began, 6),
             'reportSha256': hashlib.sha256(encoded(report)).hexdigest(), 'passed': report['passed'],
             'providers': len(report['providers']), 'dbcLayouts': len(report['checks'].get('clientDbcs', {})),
             'exclusions': len(report['exclusions']), 'unknownOverlays': len(report['unknownOverlays']), 'report': report}
    result.write_bytes(encoded(proof))
    print(json.dumps({key: value for key, value in proof.items() if key != 'report'}))


def measure(fixture, output):
    config = json.loads((fixture / 'fixture.json').read_text())
    rows = []
    for variant in config['variants']:
        compared = []
        for mode in ('baseline', 'fixed'):
            result = fixture / (mode + '-' + variant + '.json')
            process = subprocess.run([sys.executable, str(Path(__file__).resolve()), 'child', '--fixture', str(fixture),
                '--mode', mode, '--variant', variant, '--result', str(result)], capture_output=True, text=True, timeout=180)
            if process.returncode:
                raise RuntimeError(process.stdout + process.stderr)
            proof = json.loads(result.read_text())
            compared.append(proof)
            rows.append({key: value for key, value in proof.items() if key != 'report'})
        if compared[0]['report'] != compared[1]['report']:
            raise AssertionError('baseline and fixed inspection decisions differ: ' + variant)
    proof = {**config, 'runs': rows, 'reportsIdentical': True, 'ownerClientData': False,
             'androidExecution': False, 'worldEntry': False, 'metric': 'Linux ru_maxrss, KiB, independent subprocesses',
             'fixedHelperSha256': hashlib.sha256((ROOT / 'runtime/stock_content_inspection.py').read_bytes()).hexdigest()}
    output.write_bytes(encoded(proof))
    print(json.dumps({'output': str(output), 'reportsIdentical': True, 'runs': rows}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    builder = sub.add_parser('build')
    builder.add_argument('--output', type=Path, required=True)
    builder.add_argument('--client-source', type=Path, required=True)
    builder.add_argument('--hash-count', type=int, default=1 << 17)
    builder.add_argument('--baseline-revision', default=BASELINE_REVISION)
    enriching = sub.add_parser('enrich')
    enriching.add_argument('--fixture', type=Path, required=True)
    enriching.add_argument('--client-source', type=Path, required=True)
    measuring = sub.add_parser('measure')
    measuring.add_argument('--fixture', type=Path, required=True)
    measuring.add_argument('--output', type=Path, required=True)
    runner = sub.add_parser('child')
    runner.add_argument('--fixture', type=Path, required=True)
    runner.add_argument('--mode', choices=('baseline', 'fixed'), required=True)
    runner.add_argument('--variant', choices=('stock', 'unknown-overlay', 'excluded-optional-over-budget'), required=True)
    runner.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'build': build(args.output, args.client_source, args.hash_count, args.baseline_revision)
    elif args.command == 'enrich': enrich(args.fixture, args.client_source)
    elif args.command == 'measure': measure(args.fixture, args.output)
    else: child(args.fixture, args.mode, args.variant, args.result)


if __name__ == '__main__':
    main()
