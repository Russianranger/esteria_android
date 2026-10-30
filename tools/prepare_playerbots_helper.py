#!/usr/bin/env python3
"""Acquire measured helper/source proofs and register an optional candidate.

No compiler, helper, SQL engine, provider or Android process is executed. The
original incomplete artifact stays identified; only its explicitly pinned
missing workflow recipe is recovered from the original commit's Git blob.
"""
from __future__ import annotations

import argparse
import base64
import copy
import gzip
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tarfile
from urllib.parse import quote

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import package_playerbots_helper as candidate, prepare_server_requalification as transfer
from tools import verify_server_build as files, prepare_runtime as archives
from tools.release_server_dependencies import Github, API, encoded

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/server/playerbots-helper-candidate.lock.json'
RECIPE = 'recipes/.github/workflows/playerbots-schema.yml'
MAX_FILES, MAX_BYTES = 256, 256 << 20
require = files.require


def safe_inventory(rows):
    require(type(rows) is dict and 1 <= len(rows) <= MAX_FILES, 'playerbots-helper-inventory-bound')
    seen, total = set(), 0
    for name, row in rows.items():
        require(isinstance(name, str) and len(name.encode()) <= 512, 'playerbots-helper-path-bound')
        transfer.content.safe_path(name)
        require(name.casefold() not in seen, 'playerbots-helper-case-collision')
        seen.add(name.casefold()); total += candidate.identity(row)['bytes']
    require(total <= MAX_BYTES, 'playerbots-helper-expanded-byte-bound')
    return rows


def load_pin():
    pin, lock_identity = candidate.modules.read_json(LOCK, limit=128 << 10)
    require(type(pin.get('formatVersion')) is int and pin['formatVersion'] == 1 and
            pin.get('scope') == 'measured-playerbots-helper-candidate-inputs' and
            pin.get('state') == 'pending-source-provider-integration' and
            pin.get('originalHelperArtifactComplete') is False and
            all(pin.get(key) is False for key in ('sourceCompanionComplete', 'androidProviderCreated',
                'productionActivated', 'playerbotsAiQualified', 'androidRuntimeQualified', 'gameplayQualified')),
            'playerbots-helper-input-scope-differs')
    producer = pin.get('producer', {})
    require(type(producer.get('workflowRun')) is int and producer['workflowRun'] > 0 and
            isinstance(producer.get('integrationRevision'), str) and
            re.fullmatch('[a-f0-9]{40}', producer['integrationRevision']), 'playerbots-helper-producer-required')
    for field in ('helperArtifact', 'evidenceArtifact'):
        row = pin.get(field, {}); candidate.identity(row)
        require(type(row.get('id')) is int and row['id'] > 0 and 22 <= row['bytes'] <= MAX_BYTES,
                'playerbots-helper-artifact-pin-required')
    require(pin['helperArtifact']['id'] != pin['evidenceArtifact']['id'] and
            pin['evidenceArtifact']['bytes'] <= 1 << 20, 'playerbots-helper-artifact-selection-differs')
    rows = safe_inventory(pin.get('helperFiles'))
    require(len(rows) == 40 and set(pin.get('recoveredRecipes', {})) == {RECIPE} and
            rows.get('helper-build.json') == pin.get('helperBuildReceipt') and
            rows.get('bin/playerbots-schema') == pin.get('executable'), 'playerbots-helper-fixed-member-selection-differs')
    for name, row in pin['recoveredRecipes'].items():
        require({key: row.get(key) for key in ('bytes', 'sha256')} == rows.get(name) and
                row.get('integrationRevision') == producer['integrationRevision'] and
                row.get('integrationPath') == '.github/workflows/playerbots-schema.yml' and
                isinstance(row.get('gitBlob'), str) and re.fullmatch('[a-f0-9]{40}', row['gitBlob']) and
                row['bytes'] <= 256 << 10, 'playerbots-helper-approved-recovery-differs')
    programs, _ = candidate.selection()
    require(pin.get('sourceLock') == programs['serverBuildSourceLock'] and
            pin.get('originalBuild') == programs['originalBuild'] and
            pin.get('originalModules') == programs['originalModules'] and
            candidate.sources.same(pin.get('serverSource'), programs['serverSource']) and
            pin.get('sourceInputArchive') == candidate.identity(programs['originalSourceInputs']['archive']) and
            pin.get('sourceInputReceipt') == candidate.identity(programs['originalSourceInputs']['receipt']) and
            rows.get('source-inputs/original-sources.lock.json') == pin['sourceLock'] and
            rows.get('provenance/original-build.json') == pin['originalBuild'] and
            rows.get('provenance/original-modules.json') == pin['originalModules'] and
            rows.get('source-inputs/server-engine-source-inputs.tar.gz') == pin['sourceInputArchive'] and
            rows.get('source-inputs/source-inputs-receipt.json') == pin['sourceInputReceipt'],
            'playerbots-helper-current-archived-selection-differs')
    candidate.identity(pin.get('nativeSqlReceipt')); candidate.identity(pin.get('helperBuildReceipt'))
    return pin, lock_identity


def verify_remote(api, pin):
    producer = pin['producer']; run = api.json('/actions/runs/' + str(producer['workflowRun']))
    require(run.get('id') == producer['workflowRun'] and run.get('head_sha') == producer['integrationRevision'] and
            run.get('status') == 'completed' and run.get('conclusion') == 'success',
            'playerbots-helper-producer-result-differs')
    for field in ('helperArtifact', 'evidenceArtifact'):
        expected = pin[field]; row = api.json('/actions/artifacts/' + str(expected['id']))
        require(row.get('id') == expected['id'] and row.get('expired') is False and
                row.get('size_in_bytes') == expected['bytes'] and row.get('digest') == 'sha256:' + expected['sha256'] and
                row.get('workflow_run', {}).get('id') == producer['workflowRun'] and
                row.get('workflow_run', {}).get('head_sha') == producer['integrationRevision'],
                'playerbots-helper-remote-artifact-differs')


def extract_selected(archive_path, artifact, rows, output, *, approved_missing=()):
    """Hash the complete ZIP, then extract only its exact selected regular files."""
    require(files.identity(archive_path) == candidate.identity(artifact), 'playerbots-helper-zip-pin-differs')
    safe_inventory(rows)
    archives.directory(output.parent)
    require(not os.path.lexists(output), 'existing-playerbots-helper-extraction-preserved')
    with transfer.bounded_zip(archive_path) as (archive, members):
        require(set(members) <= set(rows), 'playerbots-helper-unexpected-zip-member')
        missing = set(rows) - set(members)
        require(missing == set(approved_missing), 'playerbots-helper-missing-member-not-approved')
        require(sum(item.file_size for item in members.values()) <= MAX_BYTES, 'playerbots-helper-zip-expanded-bound')
        output.mkdir(mode=0o700)
        for name, item in members.items():
            expected = candidate.identity(rows[name])
            require(item.file_size == expected['bytes'], 'playerbots-helper-zip-member-size-differs')
            target = output / name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with archive.open(item) as incoming, target.open('xb') as outgoing:
                require(archives.hash_stream(incoming, expected['bytes'], outgoing) == expected['sha256'],
                        'playerbots-helper-zip-member-hash-differs')
                outgoing.flush(); os.fsync(outgoing.fileno())
            # Actions does not preserve executable modes. Restore only this
            # byte-pinned helper's mode; all source/proof members are read-only.
            target.chmod(0o555 if name == 'bin/playerbots-schema' else 0o444)
    return missing


def recover_recipe(api, output, name, row):
    """Require both the original commit/path mapping and addressed blob bytes."""
    require(name == RECIPE and row.get('integrationPath') == '.github/workflows/playerbots-schema.yml' and
            re.fullmatch('[a-f0-9]{40}', row.get('integrationRevision', '')) and
            re.fullmatch('[a-f0-9]{40}', row.get('gitBlob', '')), 'playerbots-helper-unapproved-recovery')
    archives.directory(output)
    target = output / name
    require(not os.path.lexists(target), 'playerbots-helper-existing-recovery-preserved')
    path = '/contents/' + quote(row['integrationPath'], safe='/') + '?ref=' + row['integrationRevision']
    original = api.json(path)
    require(original.get('type') == 'file' and original.get('path') == row['integrationPath'] and
            original.get('sha') == row['gitBlob'] and type(original.get('size')) is int and
            original['size'] == row['bytes'], 'playerbots-helper-original-commit-path-differs')
    blob = api.json('/git/blobs/' + row['gitBlob'])
    require(blob.get('sha') == row['gitBlob'] and blob.get('encoding') == 'base64' and
            type(blob.get('size')) is int and blob['size'] == row['bytes'] and
            isinstance(blob.get('content'), str) and len(blob['content']) <= row['bytes'] * 2 + 1024,
            'playerbots-helper-recovery-blob-metadata-differs')
    try:
        raw = base64.b64decode(''.join(blob['content'].split()), validate=True)
    except ValueError:
        raise ValueError('playerbots-helper-recovery-base64-invalid') from None
    require(dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) == candidate.identity(row) and
            hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == row['gitBlob'],
            'playerbots-helper-recovered-blob-identity-differs')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    transfer.write_new(target, raw, mode=0o444)
    return dict(identity=candidate.identity(row), gitBlob=row['gitBlob'],
        integrationRevision=row['integrationRevision'], integrationPath=row['integrationPath'],
        missingFromOriginalArtifact=True, originalCommitPathVerified=True, gitBlobAndSha256Verified=True,
        sourceOnlyRecovery=True)


def extract_native(archive_path, artifact, expected, output):
    require(files.identity(archive_path) == candidate.identity(artifact), 'playerbots-helper-evidence-zip-pin-differs')
    with transfer.bounded_zip(archive_path) as (archive, members):
        name = 'native-sql-qualification.json'
        require(name in members and members[name].file_size == expected['bytes'],
                'playerbots-helper-native-proof-member-differs')
        with archive.open(name) as incoming, output.open('xb') as outgoing:
            require(archives.hash_stream(incoming, expected['bytes'], outgoing) == expected['sha256'],
                    'playerbots-helper-native-proof-hash-differs')
            outgoing.flush(); os.fsync(outgoing.fileno())
        output.chmod(0o444)


def write_candidate_archive(root, verified, pin_identity, output):
    """Preserve authenticated candidate modes across Actions' ZIP transport."""
    root = archives.directory(root); output = Path(os.path.abspath(output))
    archives.directory(output.parent)
    require(root != output and root not in output.parents, 'playerbots-helper-candidate-archive-overlap')
    inventory = {'runtime/' + name: dict(row) for name, row in verified['runtimeFiles'].items()}
    inventory.update({'companion/' + name: dict(row) for name, row in verified['companionFiles'].items()})
    inventory['candidate-pin.json'] = dict(pin_identity, mode=0o444)
    safe_inventory(inventory)
    require({path.relative_to(root).as_posix() for path in files.installed_files(root)} == set(inventory),
            'playerbots-helper-candidate-archive-member-set-differs')
    require(not os.path.lexists(output), 'existing-playerbots-candidate-archive-preserved')
    with output.open('xb') as raw:
        with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as archive:
                for name, row in sorted(inventory.items()):
                    require(row.get('mode') in (0o444, 0o555), 'playerbots-helper-candidate-archive-mode-differs')
                    with files.plain_file(root / name) as source:
                        metadata = os.fstat(source.fileno())
                        require(metadata.st_size == row['bytes'] and (name == 'candidate-pin.json' or
                            stat.S_IMODE(metadata.st_mode) == row['mode']), 'playerbots-helper-candidate-archive-input-differs')
                        info = tarfile.TarInfo(name)
                        info.size, info.mode = row['bytes'], row['mode']
                        info.uid = info.gid = info.mtime = 0; info.uname = info.gname = ''
                        reader = candidate.transaction.HashReader(source, row)
                        archive.addfile(info, reader); reader.finish()
        raw.flush(); os.fsync(raw.fileno())
    output.chmod(0o444)
    candidate.programs.engine.verify_archive(output, inventory)
    return dict(file=output.name, **files.identity(output), files=len(inventory),
        expandedBytes=sum(row['bytes'] for row in inventory.values()),
        archiveReadbackVerified=True, fileModesPreserved=True, deterministicArchive=True)


def prepare(output, api=None):
    pin, lock_identity = load_pin()
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'existing-playerbots-helper-preparation-preserved')
    require(shutil.disk_usage(output.parent).free >= 1 << 30, 'playerbots-helper-requires-1-GiB-free')
    api = api or Github(os.environ.get('GITHUB_TOKEN'))
    verify_remote(api, pin)
    output.mkdir(mode=0o700); inputs = output / 'inputs'; inputs.mkdir(mode=0o700)
    transfers = {}
    for field in ('helperArtifact', 'evidenceArtifact'):
        path = inputs / (field + '.zip')
        api.download(API + '/actions/artifacts/' + str(pin[field]['id']) + '/zip', path, pin[field])
        require(files.identity(path) == candidate.identity(pin[field]), 'playerbots-helper-downloaded-artifact-differs')
        transfers[field] = path
    payload = inputs / 'payload'
    missing = extract_selected(transfers['helperArtifact'], pin['helperArtifact'], pin['helperFiles'], payload,
                               approved_missing=pin['recoveredRecipes'])
    recovered = {name: recover_recipe(api, payload, name, pin['recoveredRecipes'][name]) for name in sorted(missing)}
    require({path.relative_to(payload).as_posix() for path in files.installed_files(payload)} == set(pin['helperFiles']),
            'playerbots-helper-completed-payload-members-differ')
    for name, identity in pin['helperFiles'].items():
        require(files.identity(payload / name) == identity, 'playerbots-helper-completed-payload-bytes-differ')
    native = inputs / 'native-sql-qualification.json'
    extract_native(transfers['evidenceArtifact'], pin['evidenceArtifact'], pin['nativeSqlReceipt'], native)
    acquisition = dict(formatVersion=1, scope='measured-playerbots-helper-source-only-acquisition',
        inputLock=lock_identity, producer=copy.deepcopy(pin['producer']),
        helperArtifact=pin['helperArtifact'], evidenceArtifact=pin['evidenceArtifact'],
        originalHelperArtifactComplete=False, originalArtifactsAndReceiptsUnchanged=True,
        extractedOriginalHelperFiles=len(pin['helperFiles']) - len(recovered),
        recoveredRecipes=recovered, completedPayloadFiles=len(pin['helperFiles']),
        allDeclaredPayloadBytesReadBack=True, nativeSqlReceipt=pin['nativeSqlReceipt'],
        helperBuildReceipt=pin['helperBuildReceipt'], helperExecutable=pin['executable'],
        originalServerProgramsRebuilt=False, helperExecuted=False, sqlExecuted=False,
        sourceCompanionComplete=False, androidProviderCreated=False, productionActivated=False,
        androidRuntimeQualified=False, gameplayQualified=False)
    transfer.write_new(output / 'acquisition.json', encoded(acquisition))
    result = candidate.build(payload, pin['helperBuildReceipt']['sha256'], native,
                             pin['nativeSqlReceipt']['sha256'], output / 'candidate')
    candidate_identity = files.identity(output / 'candidate/candidate-pin.json')
    require(candidate.verify(output / 'candidate', candidate_identity['sha256']) == result,
            'playerbots-helper-candidate-readback-differs')
    archive = write_candidate_archive(output / 'candidate', result, candidate_identity, output / 'candidate.tar.gz')
    proof = dict(formatVersion=1, scope='prepared-optional-playerbots-helper-candidate',
        inputLock=lock_identity, acquisitionReceipt=files.identity(output / 'acquisition.json'),
        candidatePin=candidate_identity, candidateArchive=archive, helperExecutable=pin['executable'],
        helperBuildReceipt=pin['helperBuildReceipt'], nativeSqlReceipt=pin['nativeSqlReceipt'],
        originalHelperArtifactComplete=False, sourceOnlyRecoveryVerified=True, candidateAllBytesVerified=True,
        helperOrServerExecutedHere=False, sourceCompanionComplete=False, androidProviderCreated=False,
        productionActivated=False, completeSetupQualified=False, androidRuntimeQualified=False, gameplayQualified=False)
    transfer.write_new(output / 'preparation.json', encoded(proof))
    for path in transfers.values(): path.unlink()
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); print(encoded(prepare(args.output)).decode(), end='')


if __name__ == '__main__': main()
