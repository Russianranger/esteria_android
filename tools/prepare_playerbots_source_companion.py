#!/usr/bin/env python3
"""Acquire only measured helper capture, candidate and original source inputs.

No compiler, SQL engine, runtime image, large paired-debug package or provider is
run or acquired. Pending native measurements fail before creating any output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import manifest_server_modules as modules, prepare_runtime as archives
from tools import prepare_server_installation_inputs as candidate, qualify_server_providers as stock
from tools import prepare_server_requalification as transfer, seal_playerbots_helper_sources as source
from tools import verify_server_build as files
from tools.release_server_dependencies import Github, API, encoded

require = files.require


def native_artifact(pin):
    native = pin['nativeCapture']; row = native.get('artifact')
    require(type(row) is dict and type(row.get('id')) is int and row['id'] > 0 and
            22 <= source.identity(row)['bytes'] <= 512 << 20, 'helper-source-native-artifact-pin-required')
    return dict(row, workflowRun=native['workflowRun'], integrationRevision=native['integrationRevision'])


def verify_native_remote(api, pin):
    native = pin['nativeCapture']; artifact = native_artifact(pin)
    stock.verify_remote(api, artifact)
    run = api.json('/actions/runs/' + str(native['workflowRun']))
    job = api.json('/actions/jobs/' + str(native['job']))
    require(run.get('id') == native['workflowRun'] and run.get('head_sha') == native['integrationRevision'] and
            run.get('status') == 'completed' and run.get('conclusion') == 'success' and
            job.get('id') == native['job'] and job.get('run_id') == native['workflowRun'] and
            job.get('status') == 'completed' and job.get('conclusion') == 'success',
            'helper-source-native-producer-not-successful-exact-run')
    return artifact


def extract_native(archive_path, output, pin):
    artifact = native_artifact(pin)
    require(files.identity(archive_path) == source.identity(artifact), 'helper-source-native-downloaded-artifact-differs')
    require(not os.path.lexists(output), 'existing-helper-source-native-inputs-preserved')
    with transfer.bounded_zip(archive_path) as (archive, members):
        require('source-build.json' in members and members['source-build.json'].file_size <= 4 << 20,
                'helper-source-native-receipt-member-required')
        raw = archive.read(members['source-build.json'])
        require(dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) == pin['nativeCapture']['receipt'],
                'helper-source-native-receipt-artifact-pin-differs')
        q = json.loads(raw)
        rows = q.get('payloadFiles')
        require(type(rows) is dict and 0 < len(rows) <= 20000 and
                sum(source.identity(row)['bytes'] for row in rows.values()) <= 512 << 20 and
                set(members) == set(rows) | {'source-build.json'}, 'helper-source-native-exact-members-required')
        expected = dict(rows, **{'source-build.json': pin['nativeCapture']['receipt']})
        for name, row in expected.items():
            source.content.safe_path(name)
            require(members[name].file_size == source.identity(row)['bytes'], 'helper-source-native-member-size-differs')
        output.mkdir(mode=0o700)
        for name, row in expected.items():
            path = output / name; path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with archive.open(members[name]) as incoming, path.open('xb') as outgoing:
                require(archives.hash_stream(incoming, row['bytes'], outgoing) == row['sha256'],
                        'helper-source-native-member-hash-differs')
                outgoing.flush(); os.fsync(outgoing.fileno())
            # Preserve the closed executable role required by the existing
            # ELF verifier; this acquisition never executes the program.
            path.chmod(0o555 if name == 'bin/playerbots-schema' else 0o444)
    source.verify_native(output, pin)
    return q


def prepare(output, api=None):
    pin, pid, _ = source.load_pin()  # Requires real native measurement first.
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'existing-helper-source-composition-inputs-preserved')
    require(shutil.disk_usage(output.parent).free >= 4 << 30, 'helper-source-composition-requires-four-GiB-free')
    api = Github(os.environ.get('GITHUB_TOKEN')) if api is None else api
    native = verify_native_remote(api, pin)
    registration, _, _ = candidate.load_pin(); candidate.verify_remote(api, registration)
    original = stock.load_pin()['artifacts']['completeSources']; stock.verify_remote(api, original)
    output.mkdir(mode=0o700)
    def phase(name):
        source.isolated.write_json(output / 'progress.json', dict(formatVersion=1,
            scope='helper-source-input-acquisition-progress', inputLock=pid, phase=name))
    native_zip = output / 'native.zip'
    phase('download-native-artifact')
    api.download(API + '/actions/artifacts/' + str(native['id']) + '/zip', native_zip, source.identity(native))
    phase('native-payload-readback')
    extract_native(native_zip, output / 'native', pin); native_zip.unlink()
    candidate_zip = output / 'registered-candidate.zip'
    phase('download-registered-candidate')
    api.download(API + '/actions/artifacts/' + str(registration['artifact']['id']) + '/zip', candidate_zip,
                 source.identity(registration['artifact']))
    phase('registered-candidate-readback')
    candidate.extract_registration(candidate_zip, output / 'registration', registration)
    candidate.extract_candidate(output / 'registration', output / 'candidate', registration); candidate_zip.unlink()
    source_zip = output / 'original-source.zip'
    phase('download-original-source-triple')
    api.download(API + '/actions/artifacts/' + str(original['id']) + '/zip', source_zip, source.identity(original))
    phase('original-source-triple-readback')
    stock.extract_selected(source_zip, output / 'original', original); source_zip.unlink()
    source.verify_original(output / 'original/sealed', pin)
    require(source.load_pin()[1] == pid, 'helper-source-input-lock-changed-during-acquisition')
    proof = dict(formatVersion=1, scope='exact-playerbots-helper-source-composition-inputs', inputLock=pid,
        nativeCaptureArtifact=native, nativeReceipt=pin['nativeCapture']['receipt'],
        candidateArtifact=registration['artifact'], candidatePin=pin['candidateRegistration']['candidatePin'],
        originalSourceArtifact=original, originalSourceQualification=pin['originalSourceQualification'],
        allSelectedBytesVerified=True, compilerExecuted=False, helperExecuted=False, sqlExecuted=False,
        pairedDebugArchiveAcquired=False, serverRuntimeImageAcquired=False, sourceCompanionComplete=False,
        androidProviderCreated=False, productionActivated=False, androidRuntimeQualified=False, gameplayQualified=False)
    transfer.write_new(output / 'preparation.json', encoded(proof))
    phase('complete')
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); print(encoded(prepare(args.output)).decode(), end='')


if __name__ == '__main__': main()
