#!/usr/bin/env python3
"""Recover only measured x64 Android MySQL fixture inputs and complete sources.

This compiler-free consumer reads both entire original Actions ZIPs, verifies
every retained input and installed-package source file, and restores the exact
source-pinned x64 PRoot provider from the verified original APK. It starts no
guest or SQL and grants no ARM64/application/world qualification.
"""
from __future__ import annotations

import argparse
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
from tools import preserve_android_mysql_probe as retained
from tools import prepare_server_requalification as remote
from tools import qualify_server_providers as transfer

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/mysql-probe/qualified-inputs.lock.json'
require = retained.require
files = retained.builder
archives = retained.archives
FALSE_FLAGS = ('productionAdapterQualified', 'arm64Qualified', 'serverSchemasQualified', 'gameplayQualified')


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def identity(value, maximum=2 << 30):
    require(type(value) is dict and type(value.get('bytes')) is int and
            0 < value['bytes'] <= maximum and re.fullmatch('[0-9a-f]{64}', value.get('sha256', '')),
            'mysql-fixture-invalid-identity')
    return {key: value[key] for key in ('bytes', 'sha256')}


def bytes_identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def failure_context(error):
    # Only this module's fixed guard tokens are public diagnostics. Network,
    # archive and OS exception bodies may contain signed URLs or private paths.
    token = str(error)
    return dict(exceptionType=type(error).__name__,
        guard=token if re.fullmatch('mysql-fixture-[a-z0-9-]{1,120}', token) else 'unavailable')


def small(path, maximum):
    with archives.plain_file(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        require(0 < size <= maximum, 'mysql-fixture-metadata-bound')
        raw = stream.read(size + 1)
        require(len(raw) == size, 'mysql-fixture-metadata-changed')
        return raw


def load_pin():
    raw = small(LOCK, 128 << 10)
    pin = json.loads(raw)
    require(type(pin) is dict and type(pin.get('formatVersion')) is int and pin['formatVersion'] == 1 and
            pin.get('scope') == 'qualified-android-x64-mysql-fixture-offline-input-selection' and
            pin.get('repository') == 'Russianranger/esteria_android' and
            pin.get('minimumFreeBytes') == 6 << 30 and
            all(pin.get(name) is False for name in FALSE_FLAGS) and
            pin.get('consumerFullArchiveReadbackPerformed') is False,
            'mysql-fixture-qualification-only-selection-required')
    producer = pin.get('producer', {})
    require(set(producer) == {'workflowRun', 'job', 'integrationRevision'} and
            all(type(producer.get(name)) is int and producer[name] > 0 for name in ('workflowRun', 'job')) and
            re.fullmatch('[0-9a-f]{40}', producer.get('integrationRevision', '')),
            'mysql-fixture-exact-producer-required')
    require(set(pin.get('artifacts', {})) == {'inputs', 'completeSources'}, 'mysql-fixture-artifact-pair-required')
    for row in pin['artifacts'].values():
        require(type(row.get('id')) is int and row['id'] > 0 and set(row) == {'id', 'bytes', 'sha256'},
                'mysql-fixture-exact-artifact-required')
        identity(row)
    expected = {'SOURCE-MANIFEST.json', 'probe.apk', 'tests.apk'} | {
        'provider/assets/mysql-probe/' + name for name in retained.builder.NAMES}
    require(set(pin.get('files', {})) == expected, 'mysql-fixture-nine-inputs-required')
    for row in pin['files'].values():
        require(set(row) == {'bytes', 'sha256'}, 'mysql-fixture-input-schema')
        identity(row)
    identity(pin['retentionReceipt'], 128 << 10)
    sources = pin.get('completeInstalledSources', {})
    identity(sources.get('manifest'), 2 << 20)
    require(sources['manifest'] == pin['files']['SOURCE-MANIFEST.json'] and
            type(sources.get('archiveFiles')) is int and 0 < sources['archiveFiles'] <= 4096 and
            type(sources.get('archiveBytes')) is int and 0 < sources['archiveBytes'] <= retained.MAX_SOURCES,
            'mysql-fixture-source-inventory-required')
    evidence = pin.get('actualAndroidEvidence', {})
    require(evidence.get('path') == 'runtime/evidence/android-mysql-service-4fd32df-readback.json',
            'mysql-fixture-positive-evidence-path')
    require(files.identity(ROOT / evidence['path']) == identity(evidence, 256 << 10),
            'mysql-fixture-positive-evidence-changed')
    observed = json.loads(small(ROOT / evidence['path'], 256 << 10))
    require(observed.get('scope') == 'independent-android-13-x64-mysql-and-java-service-4fd32df-readback' and
            observed.get('workflow', {}).get('id') == producer['workflowRun'] and
            observed['workflow'].get('headSha') == producer['integrationRevision'] and
            observed['workflow'].get('status') == 'completed' and observed['workflow'].get('conclusion') == 'success' and
            observed.get('allTwentyOneProviderInputsMatchExactProducerGitRevision') is True and
            observed.get('actualQualification', {}).get('androidMysqlBootstrapQualified') is True and
            observed['actualQualification'].get('androidJavaDatabaseServiceLifecycleQualified') is True,
            'mysql-fixture-positive-android-evidence-required')
    expected_inputs = {name: files.identity(ROOT / name) for name in retained.builder.INPUTS}
    require(pin.get('providerSourceInputs') == expected_inputs == observed.get('providerInputs'),
            'mysql-fixture-current-provider-recipe-differs')
    receipt = observed.get('retainedInputReceipt', {})
    require(receipt.get('identity') == pin['retentionReceipt'] and
            receipt.get('receiptCrcVerified') is True and receipt.get('value', {}).get('files') == pin['files'],
            'mysql-fixture-positive-retention-binding')
    original = receipt['value']
    require(original.get('sourceRevision') == producer['integrationRevision'] and
            original.get('sourceCompanionArtifact', {}).get('id') == pin['artifacts']['completeSources']['id'] and
            original['sourceCompanionArtifact'].get('sha256') == pin['artifacts']['completeSources']['sha256'] and
            original['sourceCompanionArtifact'].get('sourceManifest') == sources['manifest'] and
            original['sourceCompanionArtifact'].get('sourceArchiveFiles') == sources['archiveFiles'] and
            original['sourceCompanionArtifact'].get('sourceArchiveBytes') == sources['archiveBytes'],
            'mysql-fixture-source-companion-binding')
    require({row['id']: identity(row) for row in observed.get('artifactMetadataOnly', [])} ==
            {row['id']: identity(row) for row in pin['artifacts'].values()},
            'mysql-fixture-observed-artifact-pair-differs')
    return pin


def copy_member(archive, member, target, expected):
    require(member.file_size == expected['bytes'], 'mysql-fixture-member-size')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with archive.open(member) as incoming, target.open('xb') as outgoing:
        require(archives.hash_stream(incoming, member.file_size, outgoing) == expected['sha256'],
                'mysql-fixture-member-hash')
        outgoing.flush(); os.fsync(outgoing.fileno())
    target.chmod(0o444)


def restore_inputs(path, output, pin):
    require(files.identity(path) == identity(pin['artifacts']['inputs']), 'mysql-fixture-input-zip-identity')
    with remote.bounded_zip(path) as (archive, members):
        expected = dict(pin['files'], **{'retention.json': pin['retentionReceipt']})
        require(set(members) == set(expected), 'mysql-fixture-input-zip-closure')
        for name, row in expected.items():
            copy_member(archive, members[name], output / name, row)
    raw = small(output / 'retention.json', 128 << 10)
    receipt = json.loads(raw)
    require(receipt.get('scope') == 'retained-fresh-android-x86-64-mysql-fixture-inputs-only' and
            receipt.get('sourceRevision') == pin['producer']['integrationRevision'] and
            receipt.get('files') == pin['files'] and receipt.get('rootfsAndApkBytesReadBack') is True and
            receipt.get('emulatorFilesystemCopied') is False and receipt.get('databaseStateCopied') is False and
            receipt.get('offlineConsumerPinCreated') is False and receipt.get('androidExecutionSucceeded') is False and
            all(receipt.get(name) is False for name in FALSE_FLAGS), 'mysql-fixture-retention-scope')
    return receipt


def restore_sources(path, output, pin, inputs):
    require(files.identity(path) == identity(pin['artifacts']['completeSources']), 'mysql-fixture-source-zip-identity')
    output.mkdir(mode=0o700)
    inventory = {}
    with remote.bounded_zip(path) as (archive, members):
        manifest_name = remote.unique_member(members, 'SOURCE-MANIFEST.json')
        require(members[manifest_name].file_size <= 2 << 20, 'mysql-fixture-source-manifest-bound')
        manifest_raw = archive.read(members[manifest_name])
        require(bytes_identity(manifest_raw) == pin['completeInstalledSources']['manifest'],
                'mysql-fixture-source-manifest-identity')
        prefix = manifest_name[:-len('SOURCE-MANIFEST.json')]
        manifest = json.loads(manifest_raw)
        require(type(manifest.get('files')) is list and len(manifest['files']) == pin['completeInstalledSources']['archiveFiles'] and
                manifest.get('fileBytes') == pin['completeInstalledSources']['archiveBytes'],
                'mysql-fixture-source-manifest-inventory')
        # Read every original ZIP member, including the original exact project
        # recipes, licenses and PRoot/relinkable-source companion. None executes.
        for name, member in members.items():
            retained.engine.content.safe_path(name)
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with archive.open(member) as incoming, target.open('xb') as outgoing:
                digest = archives.hash_stream(incoming, member.file_size, outgoing)
                outgoing.flush(); os.fsync(outgoing.fileno())
            target.chmod(0o444)
            inventory[name] = dict(bytes=member.file_size, sha256=digest)
    source_root = output / prefix
    assets = inputs / 'provider/assets/mysql-probe'
    source_manifest, _ = retained.verify_sources(source_root,
        retained.verify.reserve.read_small(assets / 'runtime.json'),
        retained.verify.reserve.read_small(assets / 'sources.lock.json'))
    require((source_root / 'SOURCE-MANIFEST.json').read_bytes() ==
            (inputs / 'SOURCE-MANIFEST.json').read_bytes(), 'mysql-fixture-source-manifest-copy-differs')
    companion = remote.unique_member(inventory, 'corresponding-source.tar.gz')
    require(0 < inventory[companion]['bytes'] <= 256 << 20, 'mysql-fixture-proot-source-companion-bound')
    return dict(sourcePackages=len(source_manifest['sourcePackages']), installedSourceArchiveFiles=len(source_manifest['files']),
        installedSourceArchiveBytes=source_manifest['fileBytes'], allOriginalSourceZipMembers=inventory,
        installedSourceDirectory=prefix.rstrip('/'), prootCorrespondingSource=dict(path=companion, **inventory[companion]))


def restore_proot(apk, output):
    proot = retained.verify.proot
    expected = {'assets/proot-probe/build-evidence.json'} | {
        'assets/proot-probe/notices/' + name for name in proot.NOTICES} | {
        'assets/proot-probe/rootfs/' + name for name in proot.ROOTFS} | {
        'lib/x86_64/' + name for name in proot.builder.NATIVE_PINS}
    with remote.bounded_zip(apk) as (archive, members):
        selected = {name for name in members if name.startswith(('assets/proot-probe/', 'lib/x86_64/libproot_probe'))}
        require(selected == expected, 'mysql-fixture-apk-proot-closure')
        for name in sorted(expected):
            member = members[name]
            require(0 < member.file_size <= 16 << 20, 'mysql-fixture-apk-proot-member-bound')
            target = output / (name.replace('lib/', 'jniLibs/', 1) if name.startswith('lib/') else name)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with archive.open(member) as incoming, target.open('xb') as outgoing:
                archives.hash_stream(incoming, member.file_size, outgoing)
            target.chmod(0o555 if name.startswith('lib/') else 0o444)
    proot.verify(output)


def acquire(output, api=None):
    pin = load_pin()
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'mysql-fixture-existing-output-preserved')
    require(shutil.disk_usage(output.parent).free >= pin['minimumFreeBytes'], 'mysql-fixture-requires-6-GiB-free')
    api = api or remote.Github(os.environ.get('GITHUB_TOKEN'))
    run = api.json('/actions/runs/' + str(pin['producer']['workflowRun']))
    require(run.get('id') == pin['producer']['workflowRun'] and
            run.get('head_sha') == pin['producer']['integrationRevision'] and
            run.get('status') == 'completed' and run.get('conclusion') == 'success',
            'mysql-fixture-original-successful-run-required')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        for name, row in pin['artifacts'].items():
            transfer.verify_remote(api, dict(row, workflowRun=pin['producer']['workflowRun'],
                integrationRevision=pin['producer']['integrationRevision']))
            target = stage / (name + '.zip')
            api.download(remote.API + '/actions/artifacts/' + str(row['id']) + '/zip', target, row)
            require(files.identity(target) == identity(row), 'mysql-fixture-downloaded-zip-identity')
        restore_inputs(stage / 'inputs.zip', stage, pin)
        sources = restore_sources(stage / 'completeSources.zip', stage / 'complete-sources', pin, stage)
        restore_proot(stage / 'probe.apk', stage / 'proot-provider')
        verified = retained.verify.verify(stage / 'provider', stage / 'proot-provider', stage / 'probe.apk')
        proof = dict(formatVersion=1, scope='full-original-android-x64-mysql-fixture-input-and-source-readback',
            inputSelection=files.identity(LOCK), producer=pin['producer'], artifacts=pin['artifacts'],
            everyOriginalInputAndSourceZipByteReadBack=True, allNineRetainedInputsVerified=True,
            allInstalledPackageSourceFilesReadBack=True, prootProviderVerified=True, originalApkVerified=True,
            completeSourceReadback=sources, providerVerification=verified,
            guestExecuted=False, sqlExecuted=False, **{name: False for name in FALSE_FLAGS})
        retained.engine.put_metadata(stage / 'acquisition.json', proof)
        archives.sync_directory(stage)
        retained.transaction.publish_directory(stage, output); archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(acquire(args.output), sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
