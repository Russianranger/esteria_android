#!/usr/bin/env python3
"""Qualify composed ARM64 data-tool CLI behavior and actual synthetic lookups.

The CLI phase can run in the pinned small reference image. The separate lookup
phase needs a native compiler host for the existing source-verified fixture. A
capability response alone never qualifies native ordered lookups.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import package_server_data_tools as package, package_server_extractors as original_cli
from tools import build_ordered_extractors as ordered, qualify_server_isolated_build as processes

ROOT = Path(__file__).resolve().parents[1]
files, archives, engine, provider = package.files, package.archives, package.engine, package.provider
require, identity = files.require, package.identity
PHASE_RECEIPT = 'native-cli-phase.json'
FINAL_RECEIPT = 'native-cli.json'
MAX_LOG = 1 << 20
FIXTURE_RECIPES = ('tests/test_extractor_order.py', 'tests/extractor_order_reference.cpp',
    'tests/extractor_mpqfile_reference.cpp', 'runtime/extractor_order.py', 'tools/prepare_ordered_extractors.py',
    'tools/build_ordered_extractors.py', 'runtime/server/extractor-order.lock.json',
    'runtime/server/extractor-order/EsteriaArchiveOrder.h',
    'runtime/server/extractor-order/0001-explicit-ordered-providers.patch')


def native():
    require(platform.system() == 'Linux' and platform.machine().lower() in ('aarch64', 'arm64'),
            'native-arm64-data-tool-qualification-required')


def expected_receipt(path, sha256):
    require(re.fullmatch('[0-9a-f]{64}', sha256 or ''), 'external-exact-package-receipt-sha256-required')
    value, row = package.sources.read_json(path)
    require(row['sha256'] == sha256, 'external-package-or-phase-receipt-sha256-differs')
    return value, row


def verify_image_binding(accepted, selected):
    require(type(accepted) is dict and set(accepted) == {'identity', 'receipt'},
            'accepted-reference-image-readback-required')
    identity(accepted['identity']); value = accepted['receipt']
    require(type(value) is dict and type(value.get('formatVersion')) is int and value['formatVersion'] == 1 and
            value.get('scope') == 'native-arm64-dependency-image-readback' and
            value.get('runtimeArchive') == selected['requiredServerRuntimeArchive'] and
            all(value.get(k) is True for k in ('actualImageMetadataAndElfHashesVerified', 'nativePythonExecuted')) and
            all(value.get(k) is False for k in ('mysqlServerExecuted', 'databaseInitialized', 'esteriaServerExecuted',
                'androidRuntimeQualified', 'gameplayQualified')), 'exact-reference-image-readback-scope-or-boundary')


def accept_image_readback(path, sha256, selected):
    require(path is not None, 'reference-image-check-path-required')
    value, row = expected_receipt(Path(path), sha256)
    accepted = dict(identity=row, receipt=value); verify_image_binding(accepted, selected)
    return accepted


def metadata_from_archive(path, wanted, inventory):
    result = {}
    with files.plain_file(path) as raw, archives.bounded_tar(raw,
            dict(entries=20000, pathBytes=4096, fileBytes=128 << 20)) as tar:
        for member in tar:
            if member.name in wanted:
                require(member.name not in result and member.isfile() and member.size <= 16 << 20,
                        'data-tool-retained-metadata-bound')
                with tar.extractfile(member) as stream: data = stream.read(member.size+1)
                require(dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest()) == identity(inventory[member.name]),
                        'data-tool-retained-metadata-identity')
                result[member.name] = data
            tar.members.clear()
    require(set(result) == set(wanted), 'data-tool-retained-metadata-missing')
    return result


def validate_package(directory, expected_sha256):
    selected = provider.load_source_qualification(); measured = package.sources.load_pin()
    stock = package.stock.load_pin(sealed=True)
    receipt, rid = expected_receipt(directory/package.PACKAGE_RECEIPT, expected_sha256)
    require(receipt.get('formatVersion') == 1 and receipt.get('scope') == 'composed-linux-arm64-server-data-tools-runtime' and
            receipt.get('archiveReadbackVerified') is True and receipt.get('originalNoticesPreserved') is True and
            receipt.get('originalNoticeFiles') == 66 and all(receipt.get(k) is False for k in package.FALSE_FLAGS) and
            receipt.get('orderedSourceReceipt') == selected['actualOrderedSourceQualification']['receipt'] and
            receipt.get('actualOrderedSourceQualification') == selected['actualOrderedSourceQualification'] and
            receipt.get('originalServerSourceQualification') == stock['sourceQualification'],
            'data-tool-real-composed-package-required')
    require(receipt['archive']['file'] == package.RUNTIME and files.identity(directory/package.RUNTIME) == identity(receipt['archive']),
            'data-tool-runtime-archive-identity')
    rows = receipt['archiveFiles']
    provider.shared.validate_inventory(rows, provider.LIMITS['entries'], provider.LIMITS['memberBytes'], provider.LIMITS['fileBytes'])
    require(all(row['mode'] == (0o555 if name.startswith('bin/') else 0o444) for name, row in rows.items()) and
            {name for name in rows if name.startswith('bin/')} == {'bin/'+name for name in package.PROGRAMS} and
            all(rows[name] == stock['files'][name] for name in stock['noticeFiles']) and
            identity(rows[package.CONFIG]) == identity(stock['configuration']) and
            identity(rows['notices/integration/LICENSE']) == package.INTEGRATION_LICENSE,
            'data-tool-runtime-modes-notices-or-yaml')
    require(set(receipt['programPairs']) == set(package.PROGRAMS), 'data-tool-fixed-four-program-pairs')
    for name, pair in receipt['programPairs'].items():
        require(set(pair) == {'original', 'stripped', 'debug'} and pair['stripped'] == identity(rows['bin/'+name]),
                'data-tool-runtime-stripped-pair-differs')
        if name in package.STOCK:
            require(pair == stock['programPairs'][name], 'data-tool-stock-pair-changed')
        else:
            require(pair['original'] == identity(measured['nativeBuild']['programs'][name]), 'data-tool-ordered-original-pair-changed')
    engine.verify_archive(directory/package.RUNTIME, rows)
    q, qid = package.sources.read_json(directory/'native-ordered-build.json')
    require(qid == measured['nativeBuild']['receipt'], 'data-tool-original-native-receipt-changed')
    # The package root contains other files, so stage only the two exact source
    # members for the source verifier's strict input directory contract.
    with tempfile.TemporaryDirectory(prefix='data-tool-source-view-') as name:
        view = Path(name)
        for filename, row in ((package.SOURCE_ARCHIVE, selected['actualOrderedSourceQualification']['archive']),
                              (package.SOURCE_RECEIPT, selected['actualOrderedSourceQualification']['receipt'])):
            engine.copy_verified(directory/filename, view/filename, identity(row))
        sealed, _ = package.verify_ordered_sources(view, selected, measured, q, qid)
    stripped, sid = package.sources.read_json(directory/package.STRIP_RECEIPT)
    require(sid == receipt['orderedStripReceipt'] and stripped.get('scope') == 'paired-linux-arm64-ordered-extractor-derivative' and
            stripped.get('originalNativeBuild') == qid and stripped.get('archiveReadbackVerified') is True and
            set(stripped['programs']) == set(package.ORDERED), 'data-tool-ordered-strip-receipt-binding')
    for name, pair in stripped['programs'].items():
        require({k: pair[k] for k in ('original', 'stripped', 'debug')} == receipt['programPairs'][name] and
                pair.get('runtimeBytesPreserved') is True and pair.get('debugLinkVerified') is True and
                pair.get('serverExecuted') is False, 'data-tool-loaded-byte-or-debug-pair-proof')
    require(files.identity(directory/package.DEBUG) == identity(receipt['orderedDebugArchive']) == identity(stripped['debugArchive']),
            'data-tool-ordered-debug-archive-changed')
    engine.verify_archive(directory/package.DEBUG, stripped['debugInventory'])
    stock_receipt, stock_id = package.sources.read_json(directory/'stock-package-receipt.json')
    require(stock_id == stock['packageReceipt'] == receipt['originalStockPackageReceipt'], 'data-tool-stock-receipt-binding')
    package.stock.validate_package(stock_receipt, stock)
    selection = receipt['toolSelection']; selected_names = {'bin/'+name for name in package.PROGRAMS} | {
        package.CONFIG, 'provenance/'+package.SOURCE_RECEIPT}
    require(set(selection) == {'formatVersion', 'serverRevision', 'clientRevision', 'orderedSourceReceipt', 'files'} and
            selection['formatVersion'] == 1 and selection['serverRevision'] == selected['serverRevision'] and
            selection['clientRevision'] == selected['clientRevision'] and set(selection['files']) == selected_names and
            selection['orderedSourceReceipt'] == receipt['orderedSourceReceipt'] and
            all(row == identity(rows[name]) for name, row in selection['files'].items()), 'data-tool-fixed-six-selection')
    return dict(receipt=receipt, receiptIdentity=rid, selected=selected, measured=measured, native=q,
                strip=stripped, sourceSeal=sealed)


def extract_runtime(directory, verified, output):
    rows = verified['receipt']['archiveFiles']; seen = set()
    with files.plain_file(directory/package.RUNTIME) as raw, archives.bounded_tar(raw, provider.LIMITS) as tar:
        for member in tar:
            require(member.isfile() and member.name in rows and member.name not in seen,
                    'data-tool-runtime-extraction-members')
            row = rows[member.name]
            require(member.size == row['bytes'] and member.mode == row['mode'] and
                    member.uid == member.gid == member.mtime == 0 and not member.uname and not member.gname,
                    'data-tool-runtime-extraction-metadata')
            target = output/member.name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tar.extractfile(member) as incoming, target.open('xb') as copied:
                require(archives.hash_stream(incoming, member.size, copied) == row['sha256'], 'data-tool-runtime-extraction-hash')
                copied.flush(); os.fsync(copied.fileno())
            target.chmod(row['mode']); seen.add(member.name); tar.members.clear()
    require(seen == set(rows), 'data-tool-runtime-extraction-incomplete')
    for name in package.PROGRAMS: files.elf_header(output/'bin'/name, executable=True)


def verify_install(install, verified):
    package.sources.check_inventory(install, verified['receipt']['archiveFiles'])
    require(all((install/name).stat().st_mode & 0o777 == row['mode'] for name, row in
                verified['receipt']['archiveFiles'].items()), 'data-tool-installed-file-mode-changed')


def verify_derived_debug(directory, install, verified, output):
    selected = {name: row for name, row in verified['strip']['debugInventory'].items() if name.startswith('symbols/')}
    require(set(selected) == {'symbols/'+name+'.debug' for name in package.ORDERED}, 'data-tool-two-debug-symbols-required')
    with files.plain_file(directory/package.DEBUG) as raw, archives.bounded_tar(raw,
            dict(entries=10000, pathBytes=4096, fileBytes=128 << 20)) as tar:
        for member in tar:
            if member.name in selected:
                row = selected[member.name]; target = output/Path(member.name).name
                with tar.extractfile(member) as incoming, target.open('xb') as copied:
                    require(archives.hash_stream(incoming, member.size, copied) == row['sha256'], 'data-tool-debug-symbol-copy')
                target.chmod(0o444)
            tar.members.clear()
    for name in package.ORDERED:
        pair = verified['strip']['programs'][name]; binary = install/'bin'/name; debug = output/(name+'.debug')
        after = engine.elf.inspect(binary); symbols = engine.elf.inspect(debug, debug=True)
        require(after['segments'] == pair['loadedSegments'] and files.identity(debug) == pair['debug'] and
                all(section in symbols['sections'] for section in pair['debugSectionsPreserved']),
                'data-tool-derived-loaded-segments-or-debug-sections-differ')
        with files.plain_file(debug) as stream:
            crc = 0
            while block := stream.read(files.BUFFER): crc = zlib.crc32(block, crc)
        label = debug.name.encode('ascii')+b'\0'; link = label+bytes((-len(label)) % 4)+struct.pack('<I', crc)
        require(after['sections']['.gnu_debuglink']['bytes'] == len(link) and
                after['sections']['.gnu_debuglink']['sha256'] == hashlib.sha256(link).hexdigest(), 'data-tool-debuglink-crc-or-name')


def fresh_output(path, inputs):
    path = Path(os.path.abspath(path))
    require(not os.path.lexists(path) and all(path != p and p not in path.parents and path not in p.parents for p in inputs),
            'data-tool-qualification-output-exists-or-overlaps')
    archives.directory(path.parent, create=True); path.mkdir(mode=0o700)
    for name in ('logs', 'tmp'): (path/name).mkdir(mode=0o700)
    return path


def cli(package_directory, expected_sha256, output, *, reference_image_check=None, expected_reference_image_check_sha256=None):
    native(); directory = archives.directory(Path(os.path.abspath(package_directory)))
    verified = validate_package(directory, expected_sha256)
    accepted_image = accept_image_readback(reference_image_check, expected_reference_image_check_sha256, verified['selected'])
    output = fresh_output(output, (directory,))
    proof = dict(formatVersion=1, scope='native-arm64-composed-server-data-tools-cli-phase', phase='verify',
        packageReceipt=verified['receiptIdentity'], runtimeArchive=identity(verified['receipt']['archive']),
        orderedSourceReceipt=verified['receipt']['orderedSourceReceipt'],
        programs={n: row['stripped'] for n, row in verified['receipt']['programPairs'].items()},
        configuration=identity(verified['selected']['configuration']), qualificationSucceeded=False,
        nativeOrderedLookupsQualified=False, originalStockConfigParsed=False,
        requiredReferenceRuntimeArchive=verified['selected']['requiredServerRuntimeArchive'],
        referenceImageReadback=accepted_image, referenceImageIdentityVerifiedByQualifier=False,
        originalUnstrippedELFReadbackPerformed=False,
        **{name: False for name in package.FALSE_FLAGS})
    processes.write_json(output/PHASE_RECEIPT, proof)
    try:
        install = output/'install'; extract_runtime(directory, verified, install)
        symbols = output/'symbols'; symbols.mkdir(mode=0o700); verify_derived_debug(directory, install, verified, symbols)
        cases, _ = original_cli.load_pin(); results = {}
        for case in cases['cliCases']:
            verify_install(install, verified); name = case['program']; require(name in package.PROGRAMS, 'unselected-cli-program')
            with tempfile.TemporaryDirectory(prefix='empty-cli-', dir=output/'tmp') as empty:
                arguments = [str(install/package.CONFIG) if value == '@CONFIG@' else value for value in case['arguments']]
                result = original_cli.bounded_case([str(install/'bin'/name), *arguments], empty, case)
                require(not list(Path(empty).iterdir()), 'data-tool-cli-created-conversion-output')
                results[case['name']] = result
                with (output/'logs'/(case['name']+'.txt')).open('xb') as stream: stream.write(result['output'].encode())
        capabilities = {}; capability = ordered.adaptation.load_pin()['contract']+ordered.CAPABILITY_SUFFIX
        for name in package.ORDERED:
            verify_install(install, verified)
            with tempfile.TemporaryDirectory(prefix='empty-capability-', dir=output/'tmp') as empty:
                result = original_cli.bounded_case([str(install/'bin'/name), '--esteria-order-capabilities'], empty,
                    dict(name=name+'-capability', exitCode=0, contains=[capability]))
                require(result['output'] == capability+'\n' and not list(Path(empty).iterdir()), 'data-tool-exact-capability-output')
                capabilities[name] = result
        verify_install(install, verified); validate_package(directory, expected_sha256)
        proof.update(phase='complete', qualificationSucceeded=True, originalStockConfigParsed=True,
            emptyWorkingDirectoriesUnchanged=True, derivativeLoadedSegmentsAndDebugLinkVerified=True,
            cases=results, capabilities=capabilities)
        processes.write_json(output/PHASE_RECEIPT, proof); return proof
    except BaseException as error:
        proof.update(phase='failed', failureClass=type(error).__name__); processes.write_json(output/PHASE_RECEIPT, proof); raise


def verify_phase(path, sha256, verified):
    phase, row = expected_receipt(path, sha256)
    require(type(phase.get('formatVersion')) is int and phase['formatVersion'] == 1 and
            phase.get('scope') == 'native-arm64-composed-server-data-tools-cli-phase' and phase.get('phase') == 'complete' and
            phase.get('qualificationSucceeded') is True and phase.get('originalStockConfigParsed') is True and
            phase.get('nativeOrderedLookupsQualified') is False and phase.get('emptyWorkingDirectoriesUnchanged') is True and
            phase.get('derivativeLoadedSegmentsAndDebugLinkVerified') is True and
            phase.get('packageReceipt') == verified['receiptIdentity'] and
            phase.get('runtimeArchive') == identity(verified['receipt']['archive']) and
            phase.get('orderedSourceReceipt') == verified['receipt']['orderedSourceReceipt'] and
            phase.get('programs') == {n: p['stripped'] for n, p in verified['receipt']['programPairs'].items()} and
            phase.get('configuration') == identity(verified['selected']['configuration']) and
            all(phase.get(k) is False for k in package.FALSE_FLAGS), 'data-tool-complete-bound-cli-phase-required')
    verify_image_binding(phase.get('referenceImageReadback'), verified['selected'])
    original, _ = original_cli.load_pin(); require(set(phase['cases']) == {row['name'] for row in original['cliCases']},
                                                 'data-tool-all-original-cli-cases-required')
    for case in original['cliCases']:
        actual = phase['cases'][case['name']]
        require(actual['exitCode'] == case['exitCode'] and type(actual['output']) is str and
                len(actual['output'].encode()) <= 65536 and all(token in actual['output'] for token in case['contains']),
                'data-tool-original-cli-result-differs')
    capability = ordered.adaptation.load_pin()['contract']+ordered.CAPABILITY_SUFFIX+'\n'
    require(set(phase['capabilities']) == set(package.ORDERED) and all(result == dict(exitCode=0, output=capability)
            for result in phase['capabilities'].values()), 'data-tool-original-capability-results-required')
    return phase, row


def fixture_inputs(fixture_source, directory, verified):
    source = archives.directory(Path(os.path.abspath(fixture_source))); require(source.name == 'source', 'original-base-source-directory-required')
    seal = verified['sourceSeal']; raw = metadata_from_archive(directory/package.SOURCE_ARCHIVE,
        {'source-coverage.json'}, seal['archiveFiles'])['source-coverage.json']
    require(dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) == seal['sourceCoverage'], 'data-tool-source-coverage-binding')
    coverage = json.loads(raw); expected = coverage['basePreparedFiles']; base = source.parent
    package.sources.check_inventory(base, expected)
    require(files.identity(base/'preparation-receipt.json') == verified['native']['originalPreparationReceipt'],
            'data-tool-exact-original-seven-patch-preparation-required')
    recipes = {}
    for name in FIXTURE_RECIPES:
        row = verified['native']['payloadFiles']['recipes/'+name]
        require(files.identity(ROOT/name) == identity(row), 'data-tool-native-fixture-recipe-changed:'+name)
        recipes[name] = identity(row)
    return source, expected, recipes


def run_suite(suite, output):
    def identifiers(suite):
        result = []
        for test in suite:
            result.extend(identifiers(test) if isinstance(test, unittest.TestSuite) else [test.id()])
        return result
    names = identifiers(suite); require(names and len(names) == len(set(names)), 'nonempty-unique-lookup-test-suite-required')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    proof = dict(formatVersion=1, scope='actual-ordered-reader-unittest-result', expectedTests=len(names), testNames=names,
        testsRun=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        expectedFailures=len(result.expectedFailures), unexpectedSuccesses=len(result.unexpectedSuccesses),
        wasSuccessful=result.wasSuccessful())
    engine.put_metadata(output, proof); verify_suite_result(proof); return proof


def verify_suite_result(result):
    names = result.get('testNames', [])
    require(result.get('scope') == 'actual-ordered-reader-unittest-result' and type(names) is list and names and
            all(type(name) is str for name in names) and len(names) == len(set(names)) and
            type(result.get('expectedTests')) is int and result['expectedTests'] == len(names) and
            type(result.get('testsRun')) is int and result['testsRun'] == len(names) and
            all(type(result.get(k)) is int and result[k] == 0 for k in
                ('failures', 'errors', 'skipped', 'expectedFailures', 'unexpectedSuccesses')) and
            result.get('wasSuccessful') is True, 'all-actual-reader-tests-must-run-without-failure-or-skip')


def fixture_runner(output):
    native()
    require(os.environ.get('ESTERIA_EXTRACTOR_SOURCE') and
            len(json.loads(os.environ.get('ESTERIA_ORDERED_EXTRACTOR_PROGRAMS', '[]'))) == 2,
            'actual-source-and-two-stripped-programs-required-no-bridge-fallback')
    from tests.test_extractor_order import RealArchiveReader
    return run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(RealArchiveReader), output)


def lookup(package_directory, expected_sha256, cli_phase, cli_sha256, fixture_source, output):
    native(); directory = archives.directory(Path(os.path.abspath(package_directory)))
    verified = validate_package(directory, expected_sha256)
    phase_path = Path(os.path.abspath(cli_phase))/PHASE_RECEIPT; phase, phase_id = verify_phase(phase_path, cli_sha256, verified)
    source, expected, recipes = fixture_inputs(fixture_source, directory, verified)
    output = fresh_output(output, (directory, phase_path.parent, source.parent))
    install = output/'install'; extract_runtime(directory, verified, install)
    symbols = output/'symbols'; symbols.mkdir(); verify_derived_debug(directory, install, verified, symbols)
    environment = dict(PATH=os.environ.get('PATH', '/usr/bin:/bin'), LANG='C.UTF-8', LC_ALL='C.UTF-8',
        PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(output/'tmp'), GIT_NO_LAZY_FETCH='1',
        ESTERIA_EXTRACTOR_SOURCE=str(source), ESTERIA_ORDERED_EXTRACTOR_PROGRAMS=json.dumps([
            str(install/'bin'/name) for name in package.ORDERED]))
    result_path = output/'lookup-result.json'
    command = [sys.executable, str(Path(__file__).resolve()), '_fixture-run', '--output', str(result_path)]
    observed = processes.run_owned(command, output/'logs/synthetic-lookups.log', environment,
        cwd=ROOT, timeout=600, maximum=MAX_LOG)
    result, result_identity = package.sources.read_json(result_path); verify_suite_result(result)
    verify_install(install, verified); package.sources.check_inventory(source.parent, expected)
    require(all(files.identity(ROOT/name) == row for name, row in recipes.items()) and files.identity(phase_path) == phase_id,
            'data-tool-lookup-input-changed-before-final-receipt')
    validate_package(directory, expected_sha256)
    proof = dict(formatVersion=1, scope='native-arm64-composed-server-data-tools-cli-only',
        qualificationSucceeded=True, nativeOrderedLookupsQualified=True, originalStockConfigParsed=True,
        packageReceipt=verified['receiptIdentity'], runtimeArchive=identity(verified['receipt']['archive']),
        orderedSourceReceipt=verified['receipt']['orderedSourceReceipt'], programs=phase['programs'], configuration=phase['configuration'],
        cliPhase=phase_id, cliCases=phase['cases'], capabilities=phase['capabilities'], syntheticLookupTests=observed,
        referenceImageReadback=phase['referenceImageReadback'], referenceImageIdentityVerifiedByQualifier=False,
        lookupResult=result_identity, lookupTestNames=result['testNames'], lookupTestsRun=result['testsRun'], lookupTestsSkipped=0,
        fixturePreparation=verified['native']['originalPreparationReceipt'], fixtureRecipes=recipes,
        shippedRuntimeFilesUnchanged=True, originalUnstrippedELFReadbackPerformed=False,
        sourceCompanionComplete=False, **{name: False for name in package.FALSE_FLAGS})
    engine.put_metadata(output/FINAL_RECEIPT, proof); return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='operation', required=True)
    first = sub.add_parser('cli'); second = sub.add_parser('lookup'); internal = sub.add_parser('_fixture-run')
    for branch in (first, second):
        branch.add_argument('--package', type=Path, required=True)
        branch.add_argument('--expected-package-receipt-sha256', required=True)
        branch.add_argument('--output', type=Path, required=True)
    first.add_argument('--reference-image-check', type=Path, required=True)
    first.add_argument('--expected-reference-image-check-sha256', required=True)
    second.add_argument('--cli-phase', type=Path, required=True); second.add_argument('--expected-cli-phase-sha256', required=True)
    second.add_argument('--fixture-source', type=Path, required=True); internal.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.operation == 'cli': result = cli(args.package, args.expected_package_receipt_sha256, args.output,
        reference_image_check=args.reference_image_check,
        expected_reference_image_check_sha256=args.expected_reference_image_check_sha256)
    elif args.operation == 'lookup': result = lookup(args.package, args.expected_package_receipt_sha256,
        args.cli_phase, args.expected_cli_phase_sha256, args.fixture_source, args.output)
    else: result = fixture_runner(args.output)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__': main()
