#!/usr/bin/env python3
"""Measure separate rebuilt Wine provider inputs from saved API metadata and ZIPs."""
import argparse
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import stat
import tempfile
import zipfile

try:
    from . import provider_client_runtime as client, provider_guest_bridges as bridge, provider_turnip as turnip
    from .package_server_content import publish_directory
except ImportError:
    import provider_client_runtime as client, provider_guest_bridges as bridge, provider_turnip as turnip
    from package_server_content import publish_directory

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'Russianranger/esteria_android'
PRODUCER = '75f50445112818c97f8d8e575d2b1c21e59af6e5'
RUN = 41073499555
WORKFLOW = '.github/workflows/wine-arm64-provider-candidate.yml'
OLD_RUNTIME = 'f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e'
RUNTIME = 'c0e13ed15a69fa72541684ac5cef49d71d5d95ee494146bc6e40d11b6977ab46'
OUTPUTS = {'guest-bridges.proposed.lock.json', 'turnip.proposed.lock.json',
           'bridge-sources.lock.json', 'turnip-sources.lock.json', 'measurement-receipt.json'}
require = client.require
encoded = client.encoded


def byte_identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def read_metadata(path):
    raw = client.small(path)
    def unique(rows):
        result = {}
        for key, value in rows:
            require(key not in result, 'provider-measurement-duplicate-metadata-key')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    require(type(value) is dict, 'provider-measurement-metadata-object-required')
    return value, byte_identity(raw)


def run_metadata(value):
    require(type(value.get('id')) is int and value['id'] == RUN and value.get('head_sha') == PRODUCER and
        value.get('head_branch') == 'android/client-server' and value.get('path') == WORKFLOW and
        value.get('event') in ('push', 'workflow_dispatch') and value.get('status') == 'completed' and
        value.get('conclusion') == 'success' and value.get('repository', {}).get('full_name') == REPOSITORY and
        value.get('head_repository', {}).get('full_name') == REPOSITORY,
        'provider-measurement-successful-owned-run-required')


def artifact_metadata(kind, path, value):
    expected_name = 'unqualified-native-arm64-new-wine-' + ('guest-bridges-' if kind == 'bridge' else 'turnip-') + PRODUCER
    workflow = value.get('workflow_run', {})
    require(type(value.get('id')) is int and value['id'] > 0 and value.get('expired') is False and
        value.get('name') == expected_name and type(value.get('size_in_bytes')) is int and
        22 <= value['size_in_bytes'] <= 512 << 20 and type(workflow.get('id')) is int and workflow['id'] == RUN and
        workflow.get('head_sha') == PRODUCER and workflow.get('head_branch') == 'android/client-server',
        'provider-measurement-artifact-provenance')
    # Hash the complete plain ZIP before any ZIP parser sees its directory.
    with client.archives.plain_file(path) as stream:
        require(os.fstat(stream.fileno()).st_size == value['size_in_bytes'], 'provider-measurement-artifact-size')
        digest = client.archives.hash_stream(stream, value['size_in_bytes'])
    require(value.get('digest') == 'sha256:' + digest, 'provider-measurement-artifact-digest')
    return dict(id=value['id'], runId=RUN, bytes=value['size_in_bytes'], sha256=digest,
        workflowPath=WORKFLOW,
        url='https://github.com/' + REPOSITORY + '/actions/runs/' + str(RUN) + '/artifacts/' + str(value['id']))


def git_exact(name):
    raw = client.source_blob(ROOT, PRODUCER, name)
    require(client.small(ROOT / name) == raw, 'provider-measurement-current-source-differs:' + name)
    return raw


def template(kind):
    name = 'runtime/' + ('bridges' if kind == 'bridge' else 'turnip') + '/android-provider.lock.json'
    raw = git_exact(name); value = json.loads(raw)
    require(type(value.get('files')) is dict and len(value['files']) == (28 if kind == 'bridge' else 68),
            'provider-measurement-template-roster')
    return copy.deepcopy(value), byte_identity(raw)


def rebound_source(kind):
    name = 'runtime/' + ('bridges' if kind == 'bridge' else 'turnip') + '/sources.lock.json'
    raw = git_exact(name); value = json.loads(raw)
    require(value.get('runtimeArchiveSha256') == OLD_RUNTIME, 'provider-measurement-original-runtime-binding')
    value['runtimeArchiveSha256'] = RUNTIME
    return encoded(value)


def member(archive, name, maximum):
    item = archive.getinfo(name)
    require(not item.is_dir() and stat.S_ISREG(item.external_attr >> 16) and 0 <= item.file_size <= maximum,
            'provider-measurement-member-type-or-bound')
    with archive.open(item) as stream: raw = stream.read(item.file_size + 1)
    require(len(raw) == item.file_size, 'provider-measurement-member-length')
    return raw


def repository_sources(archive, kind):
    """Read retained recipe/source extras too; the installed roster stays exact."""
    base = kind + '/'; recipe = 'runtime/' + ('bridges' if kind == 'bridge' else 'turnip') + '/'
    prefixes = {base + 'corresponding-source/build-recipe/': recipe}
    singles = {base + 'notices/ESTERIA-GPL-3.0': 'LICENSE'}
    if kind == 'bridge':
        prefixes.update({base + 'corresponding-source/guest-bridges/': 'native/guest-bridges/',
                         base + 'corresponding-source/presentation/': 'native/presentation/'})
        singles.update({base + 'corresponding-source/bridge-reference.json': 'runtime/bridge-reference.json',
                        base + 'notices/AUDIO-LICENSE': 'native/guest-bridges/AUDIO-LICENSE',
                        base + 'x11-test/x11_input_observer.c': 'native/guest-tests/x11_input_observer.c'})
    checked = {}
    for item in archive.infolist():
        if item.is_dir(): continue
        name = singles.get(item.filename)
        for prefix, source in prefixes.items():
            if item.filename.startswith(prefix): name = source + item.filename.removeprefix(prefix)
        if name is None: continue
        require(client.archives.member_path(name) == name, 'provider-measurement-repository-path')
        expected = rebound_source(kind) if name == recipe + 'sources.lock.json' else git_exact(name)
        require(member(archive, item.filename, 1 << 20) == expected,
                'provider-measurement-retained-source-differs:' + name)
        checked[name] = byte_identity(expected)
    require(recipe + 'sources.lock.json' in checked and 'LICENSE' in checked,
            'provider-measurement-retained-recipe-missing')
    return checked


def selected_payload(path, kind, old):
    limits = bridge.LIMITS if kind == 'bridge' else turnip.LIMITS
    entries = {}
    for logical, row in old['files'].items():
        if kind == 'bridge': entries[logical] = 'bridge/' + row['payloadPath']
        else:
            require(row['zipEntry'].startswith(turnip.PREFIX), 'provider-measurement-turnip-template-prefix')
            entries[logical] = 'turnip/' + row['zipEntry'].removeprefix(turnip.PREFIX)
    raw = {}; total = 0
    with client.archives.plain_file(path) as stream, client.checked_zip(stream, entries.values(),
            maximum_entries=4096, maximum_directory=2 << 20) as archive:
        sources = repository_sources(archive, kind)
        for logical, name in entries.items():
            data = member(archive, name, limits['memberBytes']); total += len(data)
            require(total <= limits['fileBytes'], 'provider-measurement-selected-payload-bound')
            raw[logical] = data
        if kind == 'turnip':
            # The older template predates repository packaging documentation.
            # Retain every recipe file declared by this actual build too; each
            # was independently checked against the producer Git blob above.
            build=json.loads(raw['provenance/turnip-build.json'])
            for name,pin in build.get('recipeSources',{}).items():
                require(type(name) is str and re.fullmatch('[A-Za-z0-9_.-]{1,100}',name) and name not in ('.','..'),
                        'provider-measurement-recipe-name')
                logical='provenance/build-recipe/'+name
                if logical in raw:continue
                entry='turnip/corresponding-source/build-recipe/'+name
                data=member(archive,entry,limits['memberBytes'])
                require(byte_identity(data)==pin and sources.get('runtime/turnip/'+name)==pin,
                        'provider-measurement-declared-recipe-source-mismatch')
                total+=len(data);require(total<=limits['fileBytes'],'provider-measurement-selected-payload-bound')
                raw[logical]=data;entries[logical]=entry
            require(len(raw)<limits['entries']-len(turnip.GENERATED),'provider-measurement-provider-file-count')
            shader = member(archive, 'turnip/shader-runtime-check/qualification.json', 65536)
            turnip.files.qualification(json.loads(shader))
        else: shader = None
    return raw, entries, sources, byte_identity(shader) if shader is not None else None


def bridge_pin(path, artifact):
    value, template_pin = template('bridge')
    raw, entries, sources, _ = selected_payload(path, 'bridge', value)
    value.update(integrationRevision=PRODUCER, workflowRun=RUN, artifact=artifact, androidRuntimeQualified=False)
    value['files'] = {name: dict(byte_identity(data), zipEntry=entries[name], payloadPath=value['files'][name]['payloadPath'])
                      for name, data in raw.items()}
    for name, row in value['repositoryInputs'].items():
        expected = rebound_source('bridge') if name == 'runtime/bridges/sources.lock.json' else git_exact(name)
        require(raw[row['installedPath']] == expected, 'provider-measurement-bridge-source-input-differs:' + name)
        row.update(byte_identity(expected))
    require(raw[bridge.SOURCE_LOCK] == rebound_source('bridge'), 'provider-measurement-bridge-runtime-lock')
    return value, raw, dict(template=template_pin, repositorySources=sources)


def turnip_pin(path, artifact):
    value, template_pin = template('turnip')
    raw, entries, sources, shader = selected_payload(path, 'turnip', value)
    value.update(integrationRevision=PRODUCER, artifact=artifact, artifactPrefix='turnip/',
        requiredWineArchiveSha256=RUNTIME, buildReceiptSha256=byte_identity(raw['provenance/turnip-build.json'])['sha256'],
        nativeNoGpuQualified=True, **{key: False for key in turnip.FALSE_FLAGS})
    value['files'] = {name: dict(byte_identity(data), zipEntry=entries[name]) for name, data in raw.items()}
    require(raw['provenance/build-recipe/sources.lock.json'] == rebound_source('turnip'),
            'provider-measurement-turnip-runtime-lock')
    return value, raw, dict(template=template_pin, repositorySources=sources, runtimeShaderFixture=shader)


def write(path, raw):
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def source_recovery_metadata(run, row, path):
    try: from . import recover_wine_provider_sources as recovery
    except ImportError: import recover_wine_provider_sources as recovery
    head=run.get('head_sha','');workflow=row.get('workflow_run',{})
    require(type(run.get('id')) is int and run['id']>0 and type(head) is str and re.fullmatch('[0-9a-f]{40}',head) and
        run.get('path')==recovery.WORKFLOW and run.get('head_branch')=='android/client-server' and
        run.get('status')=='completed' and run.get('conclusion')=='success' and
        run.get('event') in ('push','workflow_dispatch') and
        run.get('repository',{}).get('full_name')==REPOSITORY and run.get('head_repository',{}).get('full_name')==REPOSITORY,
        'provider-source-recovery-successful-owned-run')
    require(type(row.get('id')) is int and row['id']>0 and row.get('expired') is False and
        row.get('name')=='source-complete-native-arm64-new-wine-turnip-'+PRODUCER+'-'+head and
        type(row.get('size_in_bytes')) is int and 22<=row['size_in_bytes']<=512<<20 and
        workflow.get('id')==run['id'] and workflow.get('head_sha')==head and
        workflow.get('head_branch')=='android/client-server','provider-source-recovery-artifact-provenance')
    with client.archives.plain_file(path) as stream:
        require(os.fstat(stream.fileno()).st_size==row['size_in_bytes'],'provider-source-recovery-artifact-size')
        digest=client.archives.hash_stream(stream,row['size_in_bytes'])
    require(row.get('digest')=='sha256:'+digest,'provider-source-recovery-artifact-digest')
    return dict(id=row['id'],runId=run['id'],bytes=row['size_in_bytes'],sha256=digest,
        workflowPath=recovery.WORKFLOW,sourceRecoveryRevision=head,
        url='https://github.com/'+REPOSITORY+'/actions/runs/'+str(run['id'])+'/artifacts/'+str(row['id']))


def measure(run_path, bridge_metadata, bridge_zip, turnip_metadata, turnip_zip, output,
            recovery_run_path=None,recovery_metadata_path=None,recovery_zip=None):
    require(not os.path.lexists(output), 'provider-measurement-output-exists')
    run, run_pin = read_metadata(run_path); run_metadata(run)
    bridge_api, bridge_api_pin = read_metadata(bridge_metadata)
    turnip_api, turnip_api_pin = read_metadata(turnip_metadata)
    bridge_artifact = artifact_metadata('bridge', bridge_zip, bridge_api)
    turnip_artifact = artifact_metadata('turnip', turnip_zip, turnip_api)
    require(bridge_artifact['id'] != turnip_artifact['id'], 'provider-measurement-artifact-identity-collision')
    recovered_proof=None;recovered_metadata=None
    require(all(x is None for x in (recovery_run_path,recovery_metadata_path,recovery_zip)) or
            all(x is not None for x in (recovery_run_path,recovery_metadata_path,recovery_zip)),
            'provider-source-recovery-selection-incomplete')
    if recovery_zip is not None:
        try: from . import recover_wine_provider_sources as recovery
        except ImportError: import recover_wine_provider_sources as recovery
        recovery_run,recovery_run_pin=read_metadata(recovery_run_path)
        recovery_api,recovery_api_pin=read_metadata(recovery_metadata_path)
        recovered_artifact=source_recovery_metadata(recovery_run,recovery_api,recovery_zip)
        recovered_proof=recovery.verify(turnip_zip,recovery_zip,turnip_artifact)
        recovered_artifact['originalNativeBuildArtifact']=turnip_artifact
        turnip_artifact=recovered_artifact;turnip_zip=recovery_zip
        recovered_metadata=dict(run=recovery_run_pin,artifact=recovery_api_pin)
    # Every complete original/recovered ZIP identity is established before payload selection.
    selected_bridge, bridge_raw, bridge_proof = bridge_pin(bridge_zip, bridge_artifact)
    selected_turnip, turnip_raw, turnip_proof = turnip_pin(turnip_zip, turnip_artifact)
    client.archives.directory(output.parent, create=True)
    stage = Path(tempfile.mkdtemp(prefix='.wine-provider-measurement-', dir=output.parent))
    try:
        bridge_lock = stage / 'guest-bridges.proposed.lock.json'; bridge_source = stage / 'bridge-sources.lock.json'
        turnip_lock = stage / 'turnip.proposed.lock.json'
        write(bridge_lock, encoded(selected_bridge)); write(bridge_source, bridge_raw[bridge.SOURCE_LOCK])
        write(turnip_lock, encoded(selected_turnip))
        write(stage / 'turnip-sources.lock.json', turnip_raw['provenance/build-recipe/sources.lock.json'])
        bridge.load_pin(bridge_lock, bridge_source)
        bridge.validate_payload(dict(bridge_raw, **bridge.GENERATED), selected_bridge)
        turnip.load_pin(turnip_lock)
        source_proof = turnip.verify_sources(turnip_zip, selected_turnip)
        require(source_proof.get('allLockedOriginalSourcesVerified') is True, 'provider-measurement-turnip-source-closure')
        validation = stage / 'turnip-validation.tar.gz'
        turnip.write_archive(validation, turnip_zip, selected_turnip)
        turnip.verify_archive(validation, selected_turnip); validation.unlink()
        outputs = {path.name: client.identity(path) for path in stage.iterdir()}
        receipt = dict(formatVersion=1, scope='review-only-measured-native-arm64-wine-provider-candidates',
            integrationRevision=PRODUCER, workflowRun=RUN, workflowPath=WORKFLOW, runtimeArchiveSha256=RUNTIME,
            savedApiMetadataValidated=True, apiMetadata=dict(run=run_pin, bridgeArtifact=bridge_api_pin, turnipArtifact=turnip_api_pin),
            artifacts=dict(bridge=bridge_artifact, turnip=turnip_artifact), bridgeInputs=bridge_proof,
            turnipInputs=turnip_proof, turnipOriginalSources=source_proof, outputFiles=outputs,
            completeOriginalZipsHashedBeforeParsing=True, actualProviderPayloadsValidated=True,
            reviewOnly=True, productionPinsChanged=False, productionProviderCreated=False,
            androidQualified=False, hardwareQualified=False, gameplayQualified=False)
        if recovered_proof is not None:
            receipt['sourceOnlyRecovery']=dict(apiMetadata=recovered_metadata,relation=recovered_proof)
        write(stage / 'measurement-receipt.json', encoded(receipt))
        require({path.name for path in stage.iterdir()} == OUTPUTS, 'provider-measurement-output-file-set')
        publish_directory(stage, output); client.archives.sync_directory(output.parent)
        return receipt
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run-metadata', 'bridge-artifact-metadata', 'bridge-zip', 'turnip-artifact-metadata', 'turnip-zip', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('source-recovery-run-metadata','source-recovery-artifact-metadata','source-recovery-zip'):
        parser.add_argument('--'+name,type=Path)
    args = parser.parse_args()
    print(json.dumps(measure(args.run_metadata, args.bridge_artifact_metadata, args.bridge_zip,
        args.turnip_artifact_metadata, args.turnip_zip, args.output,
        args.source_recovery_run_metadata,args.source_recovery_artifact_metadata,args.source_recovery_zip), indent=2))


if __name__ == '__main__': main()
