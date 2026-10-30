#!/usr/bin/env python3
"""Acquire one registered measured helper candidate and retained SQL/runtime.

The authenticated deterministic tar supplies its own exact file modes. No
compiler, helper, SQL process, Android provider or production service runs here.
"""
from __future__ import annotations

import argparse
import gzip
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import prepare_playerbots_helper as helper, package_playerbots_helper as candidate
from tools import prepare_playerbots_runtime as runtime, package_server_engine as engine
from tools import prepare_server_requalification as transfer, verify_server_build as files
from tools.release_server_dependencies import Github, API, encoded

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/server/installation-native-inputs.lock.json'
MEMBERS = {'candidate.tar.gz', 'candidate/candidate-pin.json', 'acquisition.json', 'preparation.json'}
require = files.require


def load_pin():
    pin, identity = candidate.modules.read_json(LOCK, limit=128 << 10)
    require(type(pin.get('formatVersion')) is int and pin['formatVersion'] == 1 and
            pin.get('scope') == 'measured-native-server-installation-finish-inputs' and
            all(pin.get(name) is False for name in ('originalHelperArtifactComplete', 'compilerExecuted', 'helperExecuted',
                'sqlExecuted', 'productionActivated', 'androidRuntimeQualified', 'gameplayQualified')),
            'installation-input-scope-differs')
    producer = pin.get('producer', {})
    require(type(producer.get('workflowRun')) is int and producer['workflowRun'] > 0 and
            isinstance(producer.get('integrationRevision'), str) and
            re.fullmatch('[a-f0-9]{40}', producer['integrationRevision']), 'installation-input-producer-invalid')
    artifact = pin.get('artifact', {}); candidate.identity(artifact)
    require(type(artifact.get('id')) is int and artifact['id'] > 0 and artifact['bytes'] <= 64 << 20 and
            set(pin.get('members', {})) == MEMBERS, 'installation-input-exact-registered-members-required')
    for name, row in pin['members'].items():
        candidate.identity(row)
        require(row['bytes'] <= (64 << 20 if name == 'candidate.tar.gz' else 128 << 10),
                'installation-input-member-bound')
    original, original_identity = helper.load_pin()
    require(pin.get('helperInputLock') == original_identity and type(pin.get('candidateFiles')) is int and
            pin['candidateFiles'] == 45 and type(pin.get('candidateExpandedBytes')) is int and
            pin['candidateExpandedBytes'] == 175514426, 'installation-input-original-helper-selection-differs')
    return pin, identity, original


def verify_remote(api, pin):
    producer, expected = pin['producer'], pin['artifact']
    actual = api.json('/actions/runs/' + str(producer['workflowRun']))
    require(actual.get('id') == producer['workflowRun'] and actual.get('head_sha') == producer['integrationRevision'] and
            actual.get('status') == 'completed' and actual.get('conclusion') == 'success',
            'installation-candidate-producer-differs')
    row = api.json('/actions/artifacts/' + str(expected['id']))
    require(row.get('id') == expected['id'] and row.get('expired') is False and
            row.get('size_in_bytes') == expected['bytes'] and row.get('digest') == 'sha256:' + expected['sha256'] and
            row.get('workflow_run', {}).get('id') == producer['workflowRun'] and
            row.get('workflow_run', {}).get('head_sha') == producer['integrationRevision'],
            'installation-candidate-artifact-differs')


def extract_registration(archive_path, output, pin):
    require(files.identity(archive_path) == candidate.identity(pin['artifact']), 'installation-candidate-outer-pin-differs')
    require(not os.path.lexists(output), 'existing-installation-registration-preserved')
    with transfer.bounded_zip(archive_path) as (archive, members):
        require(set(members) == set(pin['members']), 'installation-candidate-exact-outer-members-required')
        require(all(item.file_size == pin['members'][name]['bytes'] for name, item in members.items()),
                'installation-candidate-outer-member-size-differs')
        output.mkdir(mode=0o700)
        for name, item in members.items():
            expected = pin['members'][name]; target = output / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with archive.open(item) as incoming, target.open('xb') as outgoing:
                require(helper.archives.hash_stream(incoming, expected['bytes'], outgoing) == expected['sha256'],
                        'installation-candidate-outer-member-hash-differs')
                outgoing.flush(); os.fsync(outgoing.fileno())
            target.chmod(0o444)


def candidate_inventory(proof, pin):
    inventory = {}
    for section in ('runtimeFiles', 'companionFiles'):
        rows = helper.safe_inventory(proof.get(section))
        for name, row in rows.items():
            expected_mode = 0o555 if (section, name) in (
                ('runtimeFiles', candidate.HELPER), ('companionFiles', 'build-payload/bin/playerbots-schema')) else 0o444
            require(row.get('mode') == expected_mode, 'installation-candidate-mode-selection-differs')
            prefix = 'runtime/' if section == 'runtimeFiles' else 'companion/'
            inventory[prefix + name] = dict(candidate.identity(row), mode=expected_mode)
    inventory['candidate-pin.json'] = dict(pin['members']['candidate/candidate-pin.json'], mode=0o444)
    helper.safe_inventory(inventory)
    require(len(inventory) == pin['candidateFiles'] and
            sum(row['bytes'] for row in inventory.values()) == pin['candidateExpandedBytes'],
            'installation-candidate-expanded-inventory-differs')
    return inventory


def extract_candidate(registration, output, pin):
    require(not os.path.lexists(output), 'existing-installation-candidate-preserved')
    proof, identity = candidate.modules.read_json(registration / 'candidate/candidate-pin.json', limit=128 << 10)
    require(identity == pin['members']['candidate/candidate-pin.json'], 'installation-candidate-pin-differs')
    inventory = candidate_inventory(proof, pin)
    archive_path = registration / 'candidate.tar.gz'
    require(files.identity(archive_path) == pin['members']['candidate.tar.gz'], 'installation-candidate-tar-pin-differs')
    # Full member/header/hash/CRC validation precedes creating the extraction.
    engine.verify_archive(archive_path, inventory)
    output.mkdir(mode=0o700)
    with files.plain_file(archive_path) as raw, gzip.GzipFile(fileobj=raw, mode='rb') as compressed:
        with tarfile.open(fileobj=compressed, mode='r|', tarinfo=engine.BoundedGNUInfo) as archive:
            seen = set()
            for item in archive:
                require(item.isfile() and item.name in inventory and item.name not in seen, 'installation-candidate-tar-member-differs')
                row = inventory[item.name]
                require(item.size == row['bytes'] and item.mode == row['mode'] and item.uid == item.gid == item.mtime == 0 and
                        not item.uname and not item.gname, 'installation-candidate-tar-metadata-differs')
                target = output / item.name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with archive.extractfile(item) as incoming, target.open('xb') as outgoing:
                    require(helper.archives.hash_stream(incoming, row['bytes'], outgoing) == row['sha256'],
                            'installation-candidate-extracted-file-differs')
                    outgoing.flush(); os.fsync(outgoing.fileno())
                target.chmod(row['mode']); seen.add(item.name)
            require(seen == set(inventory), 'installation-candidate-tar-members-missing')
    # Re-read the compressed trailer after extraction as well as before it.
    engine.verify_archive(archive_path, inventory)
    verified = candidate.verify(output, identity['sha256'])
    require(verified == proof, 'installation-candidate-verification-object-differs')
    return verified


def prepare(output, api=None):
    output = Path(os.path.abspath(output)); helper.archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'existing-installation-inputs-preserved')
    require(shutil.disk_usage(output.parent).free >= 3 << 30, 'installation-input-storage-reserve-required')
    pin, pin_identity, original = load_pin(); api = Github(os.environ.get('GITHUB_TOKEN')) if api is None else api
    verify_remote(api, pin)
    output.mkdir(mode=0o700)
    archive = output / 'registered-candidate.zip'
    api.download(API + '/actions/artifacts/' + str(pin['artifact']['id']) + '/zip', archive,
                 candidate.identity(pin['artifact']))
    extract_registration(archive, output / 'registration', pin)
    verified = extract_candidate(output / 'registration', output / 'candidate', pin)
    require(verified.get('helper', {}).get('executable') == original['executable'] and
            verified.get('helper', {}).get('buildReceipt') == original['helperBuildReceipt'] and
            verified.get('helper', {}).get('nativeSqlReceipt') == original['nativeSqlReceipt'],
            'installation-measured-helper-proofs-differ')
    runtime_proof = runtime.prepare(output / 'runtime-inputs', api)
    require(runtime_proof.get('engineReceipt') == runtime.ENGINE_RECEIPT and
            runtime_proof.get('contentReceipt') == runtime.CONTENT_RECEIPT,
            'installation-original-runtime-content-differs')
    proof = dict(formatVersion=1, scope='prepared-native-server-installation-finish-inputs',
        inputLock=pin_identity, producer=pin['producer'], artifact=pin['artifact'], candidatePin=pin['members']['candidate/candidate-pin.json'],
        candidateArchive=pin['members']['candidate.tar.gz'], candidateFiles=pin['candidateFiles'],
        candidateAllBytesAndModesVerified=True, originalRegistrationReceiptsUnchanged=True,
        helperExecutable=original['executable'], helperBuildReceipt=original['helperBuildReceipt'], helperNativeReceipt=original['nativeSqlReceipt'],
        runtimePreparation=files.identity(output / 'runtime-inputs/preparation.json'),
        compilerExecuted=False, helperExecuted=False, sqlExecuted=False, productionActivated=False,
        androidRuntimeQualified=False, gameplayQualified=False)
    transfer.write_new(output / 'preparation.json', encoded(proof))
    archive.unlink()
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); print(encoded(prepare(args.output)).decode(), end='')


if __name__ == '__main__': main()
