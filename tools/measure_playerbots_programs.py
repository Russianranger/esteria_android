#!/usr/bin/env python3
"""Measure a separate three-program plus one schema-helper runtime candidate.

The original stock provider remains immutable. This emits no Android provider
or admission pin: measured archive bytes must be separately pinned and verified
before the optional helper profile can be packaged or installed.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import manifest_server_modules as modules, package_playerbots_helper as helper
from tools import package_server_engine as engine, package_server_content as transaction
from tools import prepare_runtime as archives, provider_server_programs as stock
from tools import seal_playerbots_helper_sources as source, server_provider_sources as bindings
from tools import verify_server_build as files

ROOT = Path(__file__).resolve().parents[1]
ANCHOR = ROOT / 'runtime/server/playerbots-helper-source-qualified.lock.json'
ARCHIVE = 'server-programs-runtime-arm64.tar.gz'
SOURCE_RECEIPT = 'provenance/playerbots-source-receipt.json'
HELPER_NOTICE = 'helper-notices/esteria-integration-LICENSE.txt'
SOURCE_LICENSE = 'recipes/initial-helper/LICENSE'
require = files.require


def load_anchor():
    pin, pid = modules.read_json(ANCHOR, limit=128 << 10)
    require(type(pin.get('formatVersion')) is int and pin['formatVersion'] == 1 and
            pin.get('scope') == 'actual-playerbots-helper-corresponding-source-anchor' and
            pin.get('state') == 'verified-native-capture-and-source-only-archive-readback' and
            all(pin.get(k) is True for k in ('archiveReadbackVerified', 'helperSourceCompanionComplete',
                'originalThreeProgramsAndReceiptsUnchanged', 'originalHelperAndNativeReceiptsUnchanged')) and
            all(pin.get(k) is False for k in ('compilerExecutedHere', 'helperExecutedHere', 'sqlExecutedHere',
                'originalNativeObjectsObserved', 'bitIdenticalExecutableClaimed', 'productionActivated',
                'androidProviderCreated', 'androidRuntimeQualified', 'playerbotsAiQualified',
                'worldserverQualified', 'gameplayQualified')), 'playerbots-programs-qualified-source-anchor-required')
    base = stock.load_pin(sealed=True)
    for name, key in (('serverBuildSourceLock', 'serverBuildSourceLock'), ('originalBuild', 'originalBuild'),
                      ('originalModules', 'originalModules'), ('originalProgramsArchive', 'archive'),
                      ('requiredServerRuntimeArchive', 'requiredServerRuntimeArchive'),
                      ('originalThreeProgramSourceQualification', 'sourceQualification')):
        require(pin.get(name) == base[key], 'playerbots-programs-original-stock-binding-differs')
    require(bindings.same(pin.get('serverSource'), base['serverSource']), 'playerbots-programs-server-source-differs')
    runtime = pin.get('helperRuntime', {})
    require(runtime.get('name') == 'playerbots-schema' and
            runtime.get('guestPath') == '/esteria-server-programs/' + helper.HELPER,
            'playerbots-programs-fixed-helper-required')
    for name in ('executable', 'buildReceipt', 'nativeSqlReceipt'): source.identity(runtime[name])
    for name in ('archive', 'receipt', 'sourceCoverage', 'replayPlan', 'sourceInputLock', 'nativeObservationReceipt'):
        source.identity(pin[name])
    require(pin['archive'].get('file') == source.SOURCE_ARCHIVE and pin['receipt'].get('file') == source.RECEIPT and
            type(pin.get('archiveEntries')) is int and 0 < pin['archiveEntries'] <= 20000 and
            type(pin.get('archiveFileBytes')) is int and 0 < pin['archiveFileBytes'] <= 512 << 20,
            'playerbots-programs-source-archive-contract')
    return pin, pid, base


def verify_helper_sources(directory, pin, selected, base):
    directory = archives.directory(directory)
    expected = {source.SOURCE_ARCHIVE: pin['archive'], source.RECEIPT: pin['receipt']}
    for name, row in expected.items():
        require(files.identity(directory / name) == source.identity(row), 'playerbots-programs-source-file-changed')
    q, _ = modules.read_json(directory / source.RECEIPT, limit=8 << 20)
    require(q.get('scope') == 'complete-playerbots-helper-corresponding-source-companion' and
            all(q.get(k) is True for k in ('sourceCompanionComplete', 'helperSourceCompanionComplete',
                'archiveReadbackVerified', 'originalThreeProgramsAndReceiptsUnchanged',
                'originalHelperAndNativeReceiptsUnchanged')) and
            all(q.get(k) is False for k in ('newCompilationPerformedHere', 'originalNativeObjectsObserved',
                'bitIdenticalExecutableClaimed', 'sqlExecuted', 'androidProviderCreated', 'productionActivated',
                'androidRuntimeQualified', 'worldserverQualified', 'playerbotsAiQualified', 'gameplayQualified')),
            'playerbots-programs-complete-helper-source-receipt-required')
    require(q.get('helperRuntime') == selected['helper'] == pin['helperRuntime'] and
            q.get('archive') == pin['archive'] and q.get('inputLock') == pin['sourceInputLock'] and
            q.get('serverBuildSourceLock') == base['serverBuildSourceLock'] and
            q.get('originalBuild') == base['originalBuild'] and q.get('originalModules') == base['originalModules'] and
            q.get('originalThreeProgramSourceQualification') == base['sourceQualification'] and
            q.get('nativeObservationReceipt') == pin['nativeObservationReceipt'] and
            q.get('sourceCoverage') == pin['sourceCoverage'] and q.get('replayPlan') == pin['replayPlan'],
            'playerbots-programs-source-receipt-crossbinding-differs')
    rows = q['archiveFiles']
    require(len(rows) == pin['archiveEntries'] and sum(r['bytes'] for r in rows.values()) == pin['archiveFileBytes'] and
            source.identity(rows['source-coverage.json']) == pin['sourceCoverage'] and
            source.identity(rows['replay-plan.json']) == pin['replayPlan'], 'playerbots-programs-source-inventory-differs')
    engine.verify_archive(directory / source.SOURCE_ARCHIVE, rows)
    require(SOURCE_LICENSE in rows and 0 < rows[SOURCE_LICENSE]['bytes'] <= 128 << 10,
            'playerbots-programs-initial-helper-license-required')
    wanted = {'source-coverage.json': pin['sourceCoverage'], 'replay-plan.json': pin['replayPlan'],
              SOURCE_LICENSE: source.identity(rows[SOURCE_LICENSE])}; documents = {}
    with files.plain_file(directory / source.SOURCE_ARCHIVE) as raw, archives.bounded_tar(raw,
            dict(entries=20000, pathBytes=4096, fileBytes=512 << 20)) as stream:
        for member in stream:
            if member.name in wanted:
                require(member.isfile() and member.size == wanted[member.name]['bytes'] <= 4 << 20,
                        'playerbots-programs-source-metadata-bound')
                with stream.extractfile(member) as body:
                    documents[member.name] = body.read() if member.name == SOURCE_LICENSE else json.load(body)
            stream.members.clear()
    require(set(documents) == set(wanted), 'playerbots-programs-source-metadata-missing')
    coverage, replay = documents['source-coverage.json'], documents['replay-plan.json']
    relation = coverage.get('originalAndObservationCorrespondence', {})
    observed = pin['sourceObservation']
    require(coverage.get('scope') == 'playerbots-helper-composed-corresponding-source-coverage' and
            coverage.get('helperRuntime') == selected['helper'] and
            coverage.get('nativeObservationReceipt') == observed['receipt'] == pin['nativeObservationReceipt'] and
            relation.get('originalRuntimeExecutable') == selected['helper']['executable'] and
            relation.get('sourceObservationExecutable') == observed['executable'] and
            all(relation.get(k) is True for k in ('exactOriginalPreparedSourceAndReferenceInputs',
                'exactCompilerIdentitiesAndCmakeOptions', 'separatelyBuiltDependencyObservation')) and
            all(relation.get(k) is False for k in ('bitIdenticalExecutableClaimed', 'originalNativeObjectsObserved')),
            'playerbots-programs-original-runtime-and-source-observation-confused')
    dependency = coverage.get('dependencyObservation', {}).get('receipt', {})
    require(dependency.get('observedObjects') == observed['observedObjects'] and
            dependency.get('observedLinks') == observed['observedLinks'] == 1 and
            dependency.get('objectElfMachines') == dependency.get('linkElfMachines') == [183] and
            dependency.get('dependenciesNotNewerThanObject') is True and
            dependency.get('linkDependenciesNotNewerThanOutput') is True and
            replay.get('scope') == 'offline-single-helper-source-replay-plan' and
            replay.get('targets') == ['esteria_playerbots_database_reference'] and
            replay.get('originalRuntimeHelperUnchanged') is True and
            replay.get('archivedBuildDriverRequiresGitMetadata') is False and
            replay.get('nativeProducerCommitGuardRelaxed') is False,
            'playerbots-programs-source-coverage-or-replay-contract-differs')
    return q, documents[SOURCE_LICENSE], wanted[SOURCE_LICENSE]


def assemble_runtime(original, original_rows, additions, output):
    """Stream every original member unchanged, then the closed helper delta."""
    require(not os.path.lexists(output) and not (set(original_rows) & set(additions)),
            'playerbots-programs-existing-output-or-member-collision')
    rows = dict(original_rows)
    for name, (path, row) in additions.items():
        stock.safe(name); source.identity(row)
        require(files.identity(path) == source.identity(row) and row.get('mode') in (0o444, 0o555),
                'playerbots-programs-addition-bytes-or-mode-differ')
        rows[name] = row
    stock.validate_inventory(rows, stock.LIMITS['entries'], stock.LIMITS['memberBytes'], stock.LIMITS['fileBytes'])
    seen = set()
    with output.open('xb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0, compresslevel=6) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as writer:
            def add(name, row, incoming):
                info = tarfile.TarInfo(name); info.size = row['bytes']; info.mode = row['mode']
                reader = transaction.HashReader(incoming, row); writer.addfile(info, reader); reader.finish()
            with files.plain_file(original) as incoming, archives.bounded_tar(incoming,
                    dict(entries=256, pathBytes=512, fileBytes=64 << 20)) as archive:
                for member in archive:
                    require(member.isfile() and member.name in original_rows and member.name not in seen,
                            'playerbots-programs-original-runtime-member-set')
                    row = original_rows[member.name]
                    require(member.mode == row['mode'] and member.size == row['bytes'] and
                            member.uid == member.gid == member.mtime == 0 and not member.uname and not member.gname,
                            'playerbots-programs-original-runtime-member-metadata')
                    with archive.extractfile(member) as body: add(member.name, row, body)
                    seen.add(member.name); archive.members.clear()
            require(seen == set(original_rows), 'playerbots-programs-original-runtime-member-missing')
            for name, (path, row) in sorted(additions.items()):
                with files.plain_file(path) as incoming: add(name, row, incoming)
    engine.verify_archive(output, rows)
    return rows


def measure(base_package, candidate, helper_sources, output):
    pin, pid, base = load_anchor()
    roots = [archives.directory(Path(os.path.abspath(p))) for p in (base_package, candidate, helper_sources)]
    base_package, candidate, helper_sources = roots
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and all(output != p and output not in p.parents and p not in output.parents for p in roots),
            'playerbots-programs-existing-or-overlapping-candidate-output')
    # This is a candidate measurement, not provider admission. The later
    # optional provider factory must retain stock.verify's full source/debug
    # guard before creating any install descriptor or Android assets.
    base_verified = stock.audit(base_package)
    registration, _, _ = source.registered.load_pin()
    selected = helper.verify(candidate, registration['members']['candidate/candidate-pin.json']['sha256'])
    _, license_body, license_identity = verify_helper_sources(helper_sources, pin, selected, base)
    extra = {helper.HELPER: (candidate / 'runtime' / helper.HELPER,
                          dict(selected['helper']['executable'], mode=0o555)),
             helper.BUILD: (candidate / 'runtime' / helper.BUILD, dict(selected['helper']['buildReceipt'], mode=0o444)),
             helper.NATIVE: (candidate / 'runtime' / helper.NATIVE, dict(selected['helper']['nativeSqlReceipt'], mode=0o444)),
             SOURCE_RECEIPT: (helper_sources / source.RECEIPT, dict(source.identity(pin['receipt']), mode=0o444))}
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        license_path = stage / 'helper-LICENSE.txt'
        with license_path.open('xb') as out:
            out.write(license_body); out.flush(); os.fsync(out.fileno())
        extra[HELPER_NOTICE] = (license_path, dict(license_identity, mode=0o444))
        original = base_package / base['archive']['file']
        rows = assemble_runtime(original, base['files'], extra, stage / ARCHIVE)
        license_path.unlink()
        require(load_anchor()[1] == pid and helper.verify(candidate,
                registration['members']['candidate/candidate-pin.json']['sha256']) == selected,
                'playerbots-programs-inputs-changed-during-measurement')
        proof = dict(formatVersion=1, scope='measured-optional-playerbots-programs-profile-candidate',
            helperSourceAnchor=pid, originalStockInputLock=files.identity(stock.LOCK),
            originalProgramsArchive=base['archive'], originalProgramPairs=base['programPairs'],
            originalBuild=base['originalBuild'], originalModules=base['originalModules'],
            serverBuildSourceLock=base['serverBuildSourceLock'], serverSource=base['serverSource'],
            requiredServerRuntimeArchive=base['requiredServerRuntimeArchive'],
            archive=dict(file=ARCHIVE, **files.identity(stage / ARCHIVE)), files=rows,
            archiveEntries=len(rows), archiveFileBytes=sum(r['bytes'] for r in rows.values()),
            programNames=list(stock.PROGRAMS), helperNames=['playerbots-schema'], helper=selected['helper'],
            helperNoticeFiles={HELPER_NOTICE: dict(license_identity, mode=0o444)},
            helperSourceQualification=dict(archive=pin['archive'], receipt=pin['receipt'],
                nativeObservationReceipt=pin['nativeObservationReceipt']),
            baseRuntimePayloadAudit=base_verified, originalStockSourceDebugReverifiedHere=False,
            originalThreeProgramBytesAndReceiptsUnchanged=True,
            originalHelperBuildAndSqlReceiptsUnchanged=True, helperSourceCompanionVerified=True,
            archiveReadbackVerified=True, newlyObservedExecutableInstalled=False,
            compilerExecuted=False, helperExecuted=False, sqlExecuted=False,
            androidProviderCreated=False, productionActivated=False, slotPromoted=False,
            androidRuntimeQualified=False, playerbotsAiQualified=False, worldserverQualified=False, gameplayQualified=False)
        engine.put_metadata(stage / 'measurement.json', proof)
        archives.sync_directory(stage); transaction.publish_directory(stage, output); archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base-package', 'candidate', 'helper-sources', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    q = measure(args.base_package, args.candidate, args.helper_sources, args.output)
    print(json.dumps({k: q[k] for k in ('scope', 'archive', 'archiveEntries', 'archiveFileBytes', 'androidProviderCreated')}, sort_keys=True))


if __name__ == '__main__': main()
