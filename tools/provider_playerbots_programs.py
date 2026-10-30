#!/usr/bin/env python3
"""Build an explicitly selected helper profile beside the unchanged stock one.

Provider creation requires the full original stock source/debug verification,
the separately source-sealed and SQL-qualified original helper, and the exact
measured augmented archive. It launches no helper, server or Android process.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import measure_playerbots_programs as measure, manifest_server_modules as modules
from tools import package_server_engine as engine, package_server_content as transaction
from tools import prepare_runtime as archives, provider_server_programs as stock
from tools import server_provider_sources as bindings, verify_server_build as files

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/server/programs-playerbots-provider.lock.json'
PROFILE = 'playerbots-schema-helper'
require = files.require


def load_pin():
    pin, pid = modules.read_json(LOCK, limit=256 << 10)
    require(type(pin.get('formatVersion')) is int and pin['formatVersion'] == 1 and
            pin.get('scope') == 'measured-optional-playerbots-programs-provider-inputs' and
            pin.get('state') == 'sealed-helper-source-and-native-sql' and
            all(pin.get(k) is True for k in ('sourceCompanionComplete', 'helperSourceCompanionComplete',
                'nativeSqlQualified', 'nativeAuthWorldVersionQualified')) and
            all(pin.get(k) is False for k in ('androidRuntimeQualified', 'gameLoginQualified',
                'gameplayQualified', 'playerbotsAiQualified', 'worldserverQualified', 'productionActivated')),
            'optional-playerbots-programs-source-and-native-pin-required')
    anchor, aid, base = measure.load_anchor()
    require(pin.get('originalStockInputLock') == files.identity(stock.LOCK) and pin.get('helperSourceAnchor') == aid and
            pin.get('originalProgramsArchive') == base['archive'] and pin.get('helper') == anchor['helperRuntime'] and
            pin.get('originalNoticePackageReceipt') == base['packageReceipt'] and
            pin.get('helperSourceQualification') == dict(archive=anchor['archive'], receipt=anchor['receipt'],
                nativeObservationReceipt=anchor['nativeObservationReceipt']), 'optional-playerbots-programs-original-inputs-differ')
    for key in ('appSourceLock', 'serverBuildSourceLock', 'serverBuildSourceLockText', 'serverBuildCompatibility',
                'serverSource', 'serverRevision', 'integrationRevision', 'buildId', 'originalBuild', 'originalModules',
                'sourceQualification', 'debugArchive', 'nativeLoaderReceipt', 'programPairs', 'originalSourceInputs',
                'originalPackageReceipt', 'originalRuntimeArchive', 'noticeFiles', 'requiredServerRuntimeArchive'):
        require(bindings.same(pin.get(key), base[key]), 'optional-playerbots-programs-stock-provenance-changed:' + key)
    require(pin.get('programNames') == list(stock.PROGRAMS) and pin.get('helperNames') == ['playerbots-schema'] and
            set(pin.get('helperNoticeFiles', {})) == {measure.HELPER_NOTICE}, 'optional-playerbots-programs-closed-role-selection')
    notice = pin['helperNoticeFiles'][measure.HELPER_NOTICE]
    require(notice.get('mode') == 0o444, 'optional-playerbots-programs-helper-notice-mode')
    measure.source.identity(notice)
    expected = dict(base['files'])
    expected.update({measure.helper.HELPER: dict(pin['helper']['executable'], mode=0o555),
        measure.helper.BUILD: dict(pin['helper']['buildReceipt'], mode=0o444),
        measure.helper.NATIVE: dict(pin['helper']['nativeSqlReceipt'], mode=0o444),
        measure.SOURCE_RECEIPT: dict(measure.source.identity(anchor['receipt']), mode=0o444),
        measure.HELPER_NOTICE: notice})
    require(pin.get('files') == expected and pin.get('archiveEntries') == len(expected) and
            pin.get('archiveFileBytes') == sum(r['bytes'] for r in expected.values()),
            'optional-playerbots-programs-original-126-or-helper-delta-changed')
    stock.validate_inventory(expected, stock.LIMITS['entries'], stock.LIMITS['memberBytes'], stock.LIMITS['fileBytes'])
    require(pin.get('archive', {}).get('file') == measure.ARCHIVE and
            0 < stock.identity(pin['archive'])['bytes'] <= stock.LIMITS['fileBytes'], 'optional-playerbots-programs-archive-bound')
    return pin, pid, anchor, base


def descriptor(pin, pid, base):
    result = stock.descriptor(base)
    result.update(profile=PROFILE, helperNames=['playerbots-schema'],
        archive=dict(stock.identity(pin['archive']), file=measure.ARCHIVE, assetPath=stock.ASSETS + '/' + stock.ARCHIVE),
        requiredFiles={name: dict(stock.identity(row), **({'elfMachine': 183} if name.startswith('bin/') or
            name == measure.helper.HELPER else {})) for name, row in sorted(pin['files'].items())},
        archiveEntries=pin['archiveEntries'], archiveFileBytes=pin['archiveFileBytes'], inputLockSha256=pid['sha256'],
        freshSetupFreeBytes=pin['archive']['bytes'] + pin['archiveFileBytes'] + stock.LIMITS['metadataBytes'] + (64 << 20),
        originalStockInputLockSha256=pin['originalStockInputLock']['sha256'], originalProgramsArchive=pin['originalProgramsArchive'],
        helperNoticeFiles={name: stock.identity(row) for name, row in pin['helperNoticeFiles'].items()})
    result['playerbotsHelper'] = dict(pin['helper'], role='playerbots-schema-initializer',
        sourceReceipt=stock.identity(pin['helperSourceQualification']['receipt']),
        sourceQualification=pin['helperSourceQualification'], sourceCompanionRequired=True,
        sourceCompanionVerified=True, nativeSqlQualified=True, originalThreeProgramsUnchanged=True,
        androidRuntimeQualified=False, worldserverQualified=False, playerbotsAiQualified=False, gameplayQualified=False)
    return result


def copy_file(source, target, expected=None, mode=0o444):
    actual = files.identity(source)
    require(expected is None or actual == stock.identity(expected), 'optional-playerbots-programs-copy-input-changed')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with files.plain_file(source) as incoming, target.open('xb') as outgoing:
        require(archives.hash_stream(incoming, actual['bytes'], outgoing) == actual['sha256'],
                'optional-playerbots-programs-copy-hash-changed')
        outgoing.flush(); os.fsync(outgoing.fileno())
    target.chmod(mode)


def copy_tree(source, target):
    for path in files.installed_files(source):
        copy_file(path, target / path.relative_to(source), mode=0o555 if path.stat().st_mode & 0o111 else 0o444)


def validate_measurement(q, pin):
    require(q.get('scope') == 'measured-optional-playerbots-programs-profile-candidate' and
            q.get('archive') == pin['archive'] and q.get('files') == pin['files'] and
            q.get('helperSourceAnchor') == pin['helperSourceAnchor'] and q.get('originalStockInputLock') == pin['originalStockInputLock'] and
            q.get('archiveReadbackVerified') is True and q.get('originalThreeProgramBytesAndReceiptsUnchanged') is True and
            q.get('originalHelperBuildAndSqlReceiptsUnchanged') is True and q.get('helperSourceCompanionVerified') is True and
            all(q.get(k) is False for k in ('androidProviderCreated', 'productionActivated', 'slotPromoted',
                'newlyObservedExecutableInstalled', 'compilerExecuted', 'helperExecuted', 'sqlExecuted',
                'androidRuntimeQualified', 'playerbotsAiQualified', 'worldserverQualified', 'gameplayQualified')),
            'optional-playerbots-programs-exact-measured-candidate-required')
    return q


def verify_candidate(directory, pin):
    q, _ = modules.read_json(directory / 'measurement.json', limit=256 << 10)
    validate_measurement(q, pin)
    require(files.identity(directory / measure.ARCHIVE) == stock.identity(pin['archive']),
            'optional-playerbots-programs-candidate-archive-differs')
    engine.verify_archive(directory / measure.ARCHIVE, pin['files'])
    return q


def verify_sources(directory, pin, anchor):
    require({p.name for p in directory.iterdir()} == {'stock-provider', 'playerbots-candidate', 'playerbots-source',
            'playerbots-source-anchor.json', 'runtime-measurement.json'}, 'optional-playerbots-programs-source-root-closure')
    # The exact stock factory and its full paired-debug/source checks are kept;
    # the optional namespace adds no bypass or caller-asserted source flag.
    original = stock.verify(directory / 'stock-provider')
    require(files.identity(directory / 'playerbots-source-anchor.json') == pin['helperSourceAnchor'],
            'optional-playerbots-programs-source-anchor-copy-differs')
    registration, _, _ = measure.source.registered.load_pin()
    selected = measure.helper.verify(directory / 'playerbots-candidate',
        registration['members']['candidate/candidate-pin.json']['sha256'])
    helper_sources = archives.directory(directory / 'playerbots-source')
    require({p.name for p in helper_sources.iterdir()} == {measure.source.SOURCE_ARCHIVE, measure.source.RECEIPT},
            'optional-playerbots-programs-helper-source-file-closure')
    _, _, notice_identity = measure.verify_helper_sources(helper_sources, anchor, selected, stock.load_pin(sealed=True))
    require(pin['helperNoticeFiles'][measure.HELPER_NOTICE] == dict(notice_identity, mode=0o444),
            'optional-playerbots-programs-helper-license-differs')
    measurement, _ = modules.read_json(directory / 'runtime-measurement.json', limit=256 << 10)
    validate_measurement(measurement, pin)
    return original


def build(base_provider, candidate, helper_sources, runtime_candidate, output):
    pin, pid, anchor, base = load_pin()
    roots = [archives.directory(Path(os.path.abspath(p))) for p in
             (base_provider, candidate, helper_sources, runtime_candidate)]
    base_provider, candidate, helper_sources, runtime_candidate = roots
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and all(output != p and output not in p.parents and p not in output.parents for p in roots),
            'optional-playerbots-programs-existing-or-overlapping-provider-output')
    stock.verify(base_provider)
    registration, _, _ = measure.source.registered.load_pin()
    selected = measure.helper.verify(candidate, registration['members']['candidate/candidate-pin.json']['sha256'])
    measure.verify_helper_sources(helper_sources, anchor, selected, base)
    verify_candidate(runtime_candidate, pin)
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        sources = stage / 'sources'; sources.mkdir(mode=0o700)
        copy_tree(base_provider, sources / 'stock-provider')
        copy_tree(candidate, sources / 'playerbots-candidate')
        for name, expected in ((measure.source.SOURCE_ARCHIVE, anchor['archive']), (measure.source.RECEIPT, anchor['receipt'])):
            copy_file(helper_sources / name, sources / 'playerbots-source' / name, expected)
        copy_file(measure.ANCHOR, sources / 'playerbots-source-anchor.json', pin['helperSourceAnchor'])
        copy_file(runtime_candidate / 'measurement.json', sources / 'runtime-measurement.json')
        assets = stage / 'assets' / stock.ASSETS; assets.mkdir(mode=0o700, parents=True)
        copy_file(runtime_candidate / measure.ARCHIVE, assets / stock.ARCHIVE, pin['archive'])
        engine.put_metadata(assets / 'provider.json', descriptor(pin, pid, base))
        verify(stage)
        require(load_pin()[1] == pid, 'optional-playerbots-programs-input-pin-changed-before-publication')
        for path, _, _ in os.walk(stage, topdown=False): archives.sync_directory(Path(path))
        transaction.publish_directory(stage, output); archives.sync_directory(output.parent)
        return descriptor(pin, pid, base)
    finally:
        if stage.exists(): shutil.rmtree(stage)


def verify(provider, apk=None):
    pin, pid, anchor, base = load_pin(); provider = archives.directory(provider)
    require({p.name for p in provider.iterdir()} == {'assets', 'sources'}, 'optional-playerbots-programs-provider-root-closure')
    require({p.name for p in (provider / 'assets').iterdir()} == {stock.ASSETS}, 'optional-playerbots-programs-assets-root-closure')
    assets = archives.directory(provider / 'assets' / stock.ASSETS)
    require({p.name for p in assets.iterdir()} == {stock.ARCHIVE, 'provider.json'}, 'optional-playerbots-programs-assets-file-closure')
    original = verify_sources(archives.directory(provider / 'sources'), pin, anchor)
    require(files.identity(assets / stock.ARCHIVE) == stock.identity(pin['archive']) and
            files.identity(assets / 'provider.json') == dict(bytes=len(stock.encoded(descriptor(pin, pid, base))),
                sha256=measure.source.hashlib.sha256(stock.encoded(descriptor(pin, pid, base))).hexdigest()),
            'optional-playerbots-programs-archive-or-descriptor-differs')
    engine.verify_archive(assets / stock.ARCHIVE, pin['files'])
    if apk is not None: stock.verify_apk(assets, apk)
    return dict(providerVerified=True, sourceCompanionVerified=True, pairedOriginalDebugVerified=True,
        helperSourceCompanionVerified=True, originalThreeProgramsAndReceiptsUnchanged=True,
        nativeHelperSqlProofPreserved=True, helperNativeProofTransferredToNewExecutable=False,
        originalStockProviderVerification=original, apkBytesVerified=apk is not None,
        archive=pin['archive'], archiveEntries=pin['archiveEntries'], archiveFileBytes=pin['archiveFileBytes'],
        programNames=list(stock.PROGRAMS), helperNames=['playerbots-schema'],
        compilerExecuted=False, helperExecuted=False, sqlExecuted=False,
        productionActivated=False, slotPromoted=False, androidRuntimeQualified=False,
        worldserverQualified=False, playerbotsAiQualified=False, gameplayQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='operation', required=True)
    make = sub.add_parser('build')
    for name in ('base-provider', 'candidate', 'helper-sources', 'runtime-candidate', 'output'):
        make.add_argument('--' + name, type=Path, required=True)
    check = sub.add_parser('verify'); check.add_argument('--provider', type=Path, required=True); check.add_argument('--apk', type=Path)
    args = parser.parse_args()
    result = (build(args.base_provider, args.candidate, args.helper_sources, args.runtime_candidate, args.output)
        if args.operation == 'build' else verify(args.provider, args.apk))
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__': main()
