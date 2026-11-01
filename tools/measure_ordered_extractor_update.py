#!/usr/bin/env python3
"""Measure new ordered-reader admission candidates from downloaded CI evidence.

Run/job/artifact JSON is retained from read-only GitHub API responses. Every
selected ZIP and member is hashed locally before a candidate is emitted. This
does not edit committed locks, compile or execute native programs, or qualify
Android/gameplay. Native source sealing and derived four-tool CLI are later
independent gates; the composed command reads their completed outputs through
the existing complete provider/source/debug/native-CLI admission checks.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import build_ordered_extractors as ordered
from tools import prepare_ordered_extractor_sources as transfer
from tools import seal_ordered_extractor_sources as seal
from tools import provider_server_data_tools as provider
from tools import measure_server_data_tools as composed_measurement
from tools import prepare_data_tools_provider as qualified_inputs

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'Russianranger/esteria_android'
require = seal.require
identity = seal.files.identity
read_json = seal.read_json
COMPOSED_PACKAGE_MEMBERS = {
    'data-tools-package/' + name: 'package/' + name for name in (
        'package-receipt.json', seal.RECEIPT, seal.SOURCE_ARCHIVE,
        'native-ordered-build.json', 'dependency-observation.json',
        'ordered-strip-receipt.json', 'ordered-extractors-debug-arm64.tar.gz',
        'stock-package-receipt.json', provider.RUNTIME)}
COMPOSED_PACKAGE_MEMBERS['data-tools-inputs/stock-debug/stock-extractors-debug-arm64.tar.gz'] = \
    'stock-debug/stock-extractors-debug-arm64.tar.gz'
COMPOSED_NATIVE_MEMBERS = {name: 'native/' + name for name in
                           ('native-cli.json', 'native-cli-phase.json', 'lookup-result.json')}


def document(raw):
    def unique(rows):
        result = {}
        for name, value in rows:
            require(name not in result, 'ordered-update-duplicate-json-key')
            result[name] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: require(False, 'ordered-update-nonfinite-json'))


def successful_job(run, jobs, workflow, name):
    """Require the actual successful producer, never a similarly named fork."""
    revision = run.get('head_sha', '')
    require(type(run.get('id')) is int and run['id'] > 0 and
            re.fullmatch('[0-9a-f]{40}', revision) and
            run.get('path') == '.github/workflows/' + workflow and
            run.get('head_branch') == 'non-custom' and
            run.get('repository', {}).get('full_name') == REPOSITORY and
            run.get('head_repository', {}).get('full_name') == REPOSITORY and
            type(run['repository'].get('id')) is int and run['repository']['id'] > 0 and
            run['head_repository'].get('id') == run['repository']['id'] and
            run.get('event') in ('push', 'workflow_dispatch') and
            run.get('status') == 'completed' and run.get('conclusion') == 'success',
            'ordered-update-successful-exact-repository-run-required')
    require(type(jobs) is list and 0 < len(jobs) <= 100 and
            all(type(job) is dict for job in jobs), 'ordered-update-job-list-bound')
    selected = [job for job in jobs if job.get('name') == name]
    require(len(selected) == 1, 'ordered-update-one-producer-job-required')
    job = selected[0]
    require(type(job.get('id')) is int and job['id'] > 0 and
            job.get('run_id') == run['id'] and job.get('head_sha') == revision and
            job.get('status') == 'completed' and job.get('conclusion') == 'success',
            'ordered-update-successful-source-matched-job-required')
    return job


def artifact_pin(metadata, run, path, prefix):
    """Bind a complete local ZIP to the unmodified API row and exact producer."""
    workflow = metadata.get('workflow_run', {})
    require(type(metadata.get('id')) is int and metadata['id'] > 0 and
            metadata.get('name') == prefix + run['head_sha'] and metadata.get('expired') is False and
            type(metadata.get('size_in_bytes')) is int and 22 <= metadata['size_in_bytes'] <= 256 << 20 and
            type(metadata.get('digest')) is str and
            re.fullmatch('sha256:[0-9a-f]{64}', metadata['digest']) and
            workflow.get('id') == run['id'] and workflow.get('head_sha') == run['head_sha'] and
            workflow.get('head_branch') == run['head_branch'] and
            workflow.get('repository_id') == workflow.get('head_repository_id') == run['repository'].get('id'),
            'ordered-update-exact-artifact-metadata-required')
    actual = identity(path)
    require(actual == dict(bytes=metadata['size_in_bytes'], sha256=metadata['digest'][7:]),
            'ordered-update-local-zip-hash-or-length-differs')
    return dict(id=metadata['id'], **actual)


def native_candidate(base, run, job, payload_pin, evidence_pin, payload_zip, evidence_zip):
    """Read the full native payload and retained dependency graph before measuring."""
    candidate = copy.deepcopy(base)
    with transfer.remote.bounded_zip(payload_zip) as (archive, members):
        raw = transfer.remote.small_member(archive, members, 'ordered-build.json', maximum=16 << 20)
        q = document(raw)
    native = dict(workflowRun=run['id'], job=job['id'], integrationRevision=run['head_sha'],
        payloadArtifact=payload_pin, evidenceArtifact=evidence_pin,
        receipt=dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        programs=q.get('programs'),
        dependencyObservation=q.get('targetSourceDependencies', {}).get('outputFiles', {}).get('observation.json'))
    require(type(native['dependencyObservation']) is dict, 'ordered-update-native-dependency-capture-required')
    require(type(native['programs']) is dict and set(native['programs']) == set(seal.TARGETS),
            'ordered-update-fixed-native-programs-required')
    candidate.update(nativeBuild=native, adaptationLock=identity(ordered.adaptation.LOCK))
    require(q.get('adaptationLock') == candidate['adaptationLock'] and
            q.get('clientRevision') == ordered.adaptation.load_pin()['clientRevision'],
            'ordered-update-native-adaptation-or-client-differs')
    with tempfile.TemporaryDirectory(prefix='ordered-native-readback-') as temporary:
        output = Path(temporary)
        transfer.extract_payload(payload_zip, output, candidate)
        payload = output / 'payload'
        verified, qid, inventory = seal.verify_native(payload, candidate)
        require(qid == native['receipt'] and verified == q, 'ordered-update-native-receipt-changed')
        require(identity(payload / 'build/compile_commands.json') == q['compileCommands'],
                'ordered-update-compile-command-bytes-differ')
        observation, observation_id = read_json(payload / 'build/dependency-observation/observation.json')
        require(observation_id == native['dependencyObservation'], 'ordered-update-observation-bytes-differ')
        ordered.verify_native_observation(q['targetSourceDependencies'], observation,
                                         native['programs'], q['compileCommands'])
        for name in ordered.RECIPES:
            require(inventory.get('recipes/' + name) == identity(ROOT / name),
                    'ordered-update-native-recipe-not-current:' + name)
        require(q.get('clientPolicySources') == ordered.adaptation.load_pin()['clientSources'],
                'ordered-update-client-policy-selection-differs')
        for name, row in q['targetSourceDependencies']['outputFiles'].items():
            require(inventory.get('build/dependency-observation/' + name) == seal.identity(row),
                    'ordered-update-dependency-output-unbound')
    # The evidence artifact is independently downloaded and every member read;
    # these two anchors must be byte-identical to the native payload receipt.
    with transfer.remote.bounded_zip(evidence_zip) as (archive, members):
        expected = {'ordered-build.json': native['receipt'],
                    'target-source-dependencies.json': native['dependencyObservation']}
        found = {}
        for name, member in members.items():
            with archive.open(member) as incoming:
                digest = seal.archives.hash_stream(incoming, member.file_size)
            basename = Path(name).name
            if basename in expected:
                require(basename not in found, 'ordered-update-ambiguous-evidence-anchor')
                found[basename] = dict(bytes=member.file_size, sha256=digest)
        require(found == expected, 'ordered-update-evidence-anchors-differ')
    return candidate


def source_candidate(base, measured, run, job, artifact, source_zip):
    """Measure only source qualification; all old runtime/CLI claims are cleared."""
    with transfer.remote.bounded_zip(source_zip) as (archive, members):
        require(set(members) == {seal.SOURCE_ARCHIVE, seal.RECEIPT},
                'ordered-update-source-artifact-member-set')
        raw = transfer.remote.small_member(archive, members, seal.RECEIPT, maximum=16 << 20)
        source = document(raw)
        receipt = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        require(source.get('scope') == 'complete-ordered-extractor-corresponding-source-companion' and
                all(source.get(k) is True for k in ('archiveReadbackVerified', 'orderedSourceCompanionComplete',
                    'originalNativeReceiptUnchanged', 'fullBaseAndApprovedOverlayVerified',
                    'actualTargetDependencyObservationVerified', 'integrationRecipesAllReadFromNativeGitBlobs')) and
                all(source.get(k) is False for k in ('newNativeCompilationPerformed', 'globalServerPatchListChanged',
                    'serverProgramsReplaced', 'worldQualified', 'androidRuntimeQualified',
                    'clientMpqConversionQualified', 'customEsteriaDataLoadOrderQualified', 'gameplayQualified')),
                'ordered-update-complete-source-seal-required')
        require(source.get('inputLock') == identity(seal.LOCK) and
                source.get('nativeBuild') == measured['nativeBuild'] and
                source.get('nativeReceipt') == measured['nativeBuild']['receipt'] and
                source.get('dependencyObservation') == measured['nativeBuild']['dependencyObservation'] and
                source.get('adaptationLock') == measured['adaptationLock'] and
                source.get('serverBuildSourceLock') == measured['serverBuildSourceLock'] and
                source.get('originalSourceQualification') == measured['originalSourceQualification'],
                'ordered-update-source-native-and-original-bindings')
        with tempfile.TemporaryDirectory(prefix='ordered-source-readback-') as temporary:
            path = Path(temporary) / seal.SOURCE_ARCHIVE
            with archive.open(members[seal.SOURCE_ARCHIVE]) as incoming, path.open('xb') as outgoing:
                archive_hash = seal.archives.hash_stream(incoming, members[seal.SOURCE_ARCHIVE].file_size, outgoing)
            archive_id = dict(bytes=path.stat().st_size, sha256=archive_hash)
            require(source.get('archive') == dict(file=seal.SOURCE_ARCHIVE, **archive_id),
                    'ordered-update-source-archive-identity-differs')
            seal.engine.verify_archive(path, source['archiveFiles'])
    candidate = copy.deepcopy(base)
    candidate.update(state='source-sealed-pending-derived-native-cli', sourceCompanionComplete=True,
        nativeArgumentConfigQualified=False, originalNoticesPreserved=False,
        actualOrderedSourceQualification=dict(archive=archive_id, receipt=receipt,
            nativeBuild=measured['nativeBuild']['receipt'],
            dependencyObservation=measured['nativeBuild']['dependencyObservation']),
        orderedSourceArtifact=dict(artifact, workflowRun=run['id'], job=job['id'],
            integrationRevision=run['head_sha'], members={
                seal.SOURCE_ARCHIVE: dict(archive_id, target='ordered-sources/' + seal.SOURCE_ARCHIVE),
                seal.RECEIPT: dict(receipt, target='ordered-sources/' + seal.RECEIPT)}))
    for key in ('archive', 'archiveEntries', 'archiveFileBytes', 'packageReceipt', 'programPairs',
                'nativeCliReceipt', 'orderedStripReceipt', 'debugArchives', 'files', 'toolSelection'):
        candidate[key] = None
    return candidate


def extract_selected(path, selected, destination):
    """Retain only the fixed package/native input closure from a bounded ZIP."""
    require(type(selected) is dict and 0 < len(selected) <= 16 and
            len(set(selected.values())) == len(selected), 'ordered-update-selected-member-bound')
    for name, target in selected.items():
        seal.engine.content.safe_path(name); seal.engine.content.safe_path(target)
    rows = {}
    with transfer.remote.bounded_zip(path) as (archive, members):
        require(set(selected) <= set(members), 'ordered-update-selected-member-missing')
        total = 0
        for name, relative in selected.items():
            item = members[name]; total += item.file_size
            require(item.file_size <= 128 << 20 and total <= 256 << 20 and
                    (not name.endswith('.json') or item.file_size <= 16 << 20),
                    'ordered-update-selected-input-byte-bound')
            target = destination / relative; target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with archive.open(item) as incoming, target.open('xb') as outgoing:
                digest = seal.archives.hash_stream(incoming, item.file_size, outgoing)
                outgoing.flush(); os.fsync(outgoing.fileno())
            target.chmod(0o444)
            row = dict(bytes=item.file_size, sha256=digest)
            require(identity(target) == row, 'ordered-update-extracted-input-changed')
            rows[name] = dict(row, target=relative)
    return rows


def composed_candidates(run, jobs, package_artifact, package_zip, native_artifact, native_zip, output):
    """Measure both final locks through the existing complete source/debug verifier."""
    package_job = successful_job(run, jobs, 'server-data-tools.yml', 'package')
    native_job = successful_job(run, jobs, 'server-data-tools.yml', 'native')
    package_pin = artifact_pin(package_artifact, run, package_zip, 'composed-data-tools-package-')
    native_pin = artifact_pin(native_artifact, run, native_zip, 'composed-data-tools-native-evidence-')
    output = Path(os.path.abspath(output)); seal.archives.directory(output.parent)
    require(not os.path.lexists(output), 'ordered-update-existing-output-preserved')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        inputs = stage / 'inputs'; inputs.mkdir(mode=0o700)
        package_members = extract_selected(package_zip, COMPOSED_PACKAGE_MEMBERS, inputs)
        native_members = extract_selected(native_zip, COMPOSED_NATIVE_MEMBERS, inputs)
        receipt_id = identity(inputs / 'package/package-receipt.json')
        cli_id = identity(inputs / 'native/native-cli.json')
        measured = composed_measurement.measure(inputs / 'package', inputs / 'native',
            inputs / 'stock-debug/stock-extractors-debug-arm64.tar.gz', stage / 'measured',
            expected_package_sha256=receipt_id['sha256'], expected_native_sha256=cli_id['sha256'])
        result = stage / 'result'; result.mkdir(mode=0o700)
        provider_lock = result / 'data-tools-provider.lock.json'
        seal.engine.copy_verified(stage / 'measured/data-tools-provider.lock.json', provider_lock,
                                  identity(stage / 'measured/data-tools-provider.lock.json'), 0o444)
        qualified = dict(formatVersion=1, scope='exact-actual-composed-data-tools-provider-inputs',
            providerInputLock=identity(provider_lock), artifacts={
                'package': dict(package_pin, workflowRun=run['id'], integrationRevision=run['head_sha'],
                                members=package_members),
                'native': dict(native_pin, workflowRun=run['id'], integrationRevision=run['head_sha'],
                               members=native_members)},
            androidRuntimeQualified=False, clientMpqConversionQualified=False, gameplayQualified=False)
        qualified_lock = result / 'data-tools-qualified-artifacts.lock.json'
        seal.engine.put_metadata(qualified_lock, qualified)
        old_provider_lock, old_qualified_lock = provider.LOCK, qualified_inputs.LOCK
        try:
            provider.LOCK = provider_lock
            qualified_inputs.LOCK = qualified_lock
            require(qualified_inputs.load_pin() == qualified, 'ordered-update-qualified-candidate-readback-differs')
        finally:
            provider.LOCK, qualified_inputs.LOCK = old_provider_lock, old_qualified_lock
        proof = dict(formatVersion=1, scope='measured-updated-composed-data-tools-lock-pair',
            integrationRevision=run['head_sha'], workflowRun=run['id'],
            packageJob=package_job['id'], nativeJob=native_job['id'],
            providerInputLock=identity(provider_lock), qualifiedArtifactsLock=identity(qualified_lock),
            packageArtifact=package_pin, nativeArtifact=native_pin,
            fixedPackageMembers=len(package_members), fixedNativeMembers=len(native_members),
            fullSourceRuntimeDebugAndNativeCliReadback=measured,
            candidateQualifiedPinReadbackVerified=True, committedPinChanged=False,
            nativeProgramsExecuted=False, androidRuntimeQualified=False, gameplayQualified=False)
        seal.engine.put_metadata(result / 'measurement.json', proof)
        provider.transaction.publish_directory(result, output)
        seal.archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    for operation in ('native', 'source', 'composed'):
        command = sub.add_parser(operation)
        for name in ('run', 'jobs', 'artifact', 'zip', 'output'):
            command.add_argument('--' + name, type=Path, required=True)
        if operation in ('native', 'composed'):
            if operation == 'native':
                command.add_argument('--base-pin', type=Path, default=seal.LOCK)
            command.add_argument('--evidence-artifact', type=Path, required=True)
            command.add_argument('--evidence-zip', type=Path, required=True)
        else:
            command.add_argument('--base-pin', type=Path, default=provider.LOCK)
    args = parser.parse_args()
    run, _ = read_json(args.run); jobs, _ = read_json(args.jobs)
    if type(jobs) is dict: jobs = jobs.get('jobs')
    if args.operation == 'composed':
        package_metadata, _ = read_json(args.artifact)
        native_metadata, _ = read_json(args.evidence_artifact)
        proof = composed_candidates(run, jobs, package_metadata, args.zip, native_metadata,
                                    args.evidence_zip, args.output)
        print(json.dumps(proof, indent=2)); return
    workflow, name, prefix = (
        ('server-extractor-order.yml', 'ordered-targets', 'separate-ordered-extractors-')
        if args.operation == 'native' else
        ('server-ordered-sources.yml', 'ordered-sources', 'complete-ordered-extractor-sources-'))
    job = successful_job(run, jobs, workflow, name)
    metadata, _ = read_json(args.artifact)
    artifact = artifact_pin(metadata, run, args.zip, prefix)
    base, _ = read_json(args.base_pin)
    if args.operation == 'native':
        evidence_metadata, _ = read_json(args.evidence_artifact)
        evidence = artifact_pin(evidence_metadata, run, args.evidence_zip, 'ordered-extractor-build-evidence-')
        candidate = native_candidate(base, run, job, artifact, evidence, args.zip, args.evidence_zip)
    else:
        candidate = source_candidate(base, seal.load_pin(), run, job, artifact, args.zip)
    output = Path(os.path.abspath(args.output)); seal.archives.directory(output.parent)
    require(not os.path.lexists(output), 'ordered-update-existing-output-preserved')
    seal.engine.put_metadata(output, candidate)
    print(json.dumps(dict(candidate=str(output), identity=identity(output),
        producer=run['head_sha'], run=run['id'], job=job['id'],
        committedPinChanged=False, nativeProgramsExecuted=False,
        androidRuntimeQualified=False, gameplayQualified=False), indent=2))


if __name__ == '__main__': main()
