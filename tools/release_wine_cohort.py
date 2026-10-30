#!/usr/bin/env python3
"""Publish a separately measured provider/source cohort to an exact owned draft."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile

try:
    from . import release_wine_arm64 as wine, release_client_inputs as original
    from . import package_client_sources as client_sources, package_shader_tools as shaders
    from . import provider_client_runtime as client, provider_guest_bridges as bridges
    from . import provider_turnip as turnip, provider_shader_tools as shader_provider
    from . import measure_wine_provider_candidates as measured, recover_wine_provider_sources as recovery
except ImportError:
    import release_wine_arm64 as wine, release_client_inputs as original
    import package_client_sources as client_sources, package_shader_tools as shaders
    import provider_client_runtime as client, provider_guest_bridges as bridges
    import provider_turnip as turnip, provider_shader_tools as shader_provider
    import measure_wine_provider_candidates as measured, recover_wine_provider_sources as recovery

ROOT=Path(__file__).resolve().parents[1]
MEASURED=ROOT/'runtime/wine-arm64-adoption/measured'
SCOPE='selected471-source-owned-wine-provider-cohort-write-once-prerelease'
TAG='deps-wine-cohort-471ee42f-c0e13ed15a69'
LOCK=ROOT/'runtime/wine-cohort-publication/dependency-release.lock.json'
require=client.require
encoded=client.encoded
identity=client.identity
PUBLICATION=wine.publication
INPUTS={'sources.lock.json':ROOT/'sources.lock.json',
    'runtime/client/android-provider.lock.json':client.PIN,
    'runtime/runtime-sources.lock.json':MEASURED/'runtime-sources.proposed.lock.json'}
PROVIDERS={'client-runtime':('client-provider',client.ARCHIVE),
    'guest-bridges':('bridge-provider',bridges.ASSET_ARCHIVE),
    'turnip':('turnip-provider',turnip.ARCHIVE),
    'shader-tools':('shader-provider-verified',shader_provider.ARCHIVE)}
SOURCE_FILES={'client-corresponding-source.tar.gz':'client-sources-selected3/client-corresponding-source.tar.gz',
    'client-source-receipt.json':'client-sources-selected3/source-receipt.json',
    'client-original-source-receipt.json':'client-original-source-receipt.json',
    'shader-corresponding-source.tar.gz':'shader-corresponding-source.tar.gz',
    'shader-source-receipt.json':'shader-source-receipt.json',
    'guest-bridges-original.zip':'bridge.zip','turnip-original-native.zip':'turnip.zip',
    'turnip-source-complete.zip':'turnip-source-complete.zip',
    'turnip-source-receipt.json':'turnip-provider/sources/source-receipt.json'}
FIXED_FILES={'runtime-public-release.lock.json':ROOT/'runtime/wine-arm64-publication/dependency-release.lock.json',
    'runtime-published-release.json':ROOT/'runtime/wine-arm64-publication/published-release.json'}
PAYLOAD=set(SOURCE_FILES)|set(FIXED_FILES)|{'provider-assets.tar.gz','provider-assets-receipt.json',
    'client-original.zip','source-selection.tar.gz','source-selection-receipt.json','NOTICE.txt'}
ALL_FILES=PAYLOAD|{'release-manifest.json','SHA256SUMS'}
NOTICE=b'''Rebuilt reconstructed client471, guest bridges, shader tools and Turnip providers.
Every provider selects source-owned Wine archivec0e13ed15a69. Original binary/source
inputs and component license notices are retained. The unchanged complete Wine
source ZIP is a separate public release, pinned in runtime-public-release.lock.json
and runtime-published-release.json; retain it with the runtime and this cohort.
The source-only Turnip supplement restores18 bytes from the original producer's
retained Git tree and exact build receipt. It does not rebuild or relabel binaries.
The client source receipt uses three explicitly selected inputs. Historical client
release receipts with two selected inputs retain their separate schema.
Linux ARM64 component fixtures passed. This release does not qualify Android,
Adreno, audible output, CommonMain/assets, world entry or gameplay. No game data,
accounts, private credentials, initialized prefixes, database or saved state.
Individual upstream licenses/notices apply; nothing here relicenses a component.
'''


def selected_inputs():
    return {name:identity(path) for name,path in INPUTS.items()}


def recipe_inputs(revision):
    require(re.fullmatch('[0-9a-f]{40}',revision or ''),'cohort-recipe-revision')
    roster=subprocess.check_output(['git','ls-tree','-r','--name-only',revision,'--','tools','runtime'],cwd=ROOT,timeout=30)
    tracked=set(roster.decode().splitlines())
    pending={'tools/release_wine_cohort.py','tests/test_wine_cohort_release.py',
        'runtime/wine-cohort-publication/README.md','.github/workflows/preserve-wine-cohort.yml'}
    pending.update(str(p.relative_to(ROOT)) for p in INPUTS.values())
    pending.update(str(p.relative_to(ROOT)) for p in FIXED_FILES.values())
    pending.update(str(p.relative_to(ROOT)) for p in MEASURED.glob('*lock.json'))
    pending.update(json.loads(client.small(MEASURED/'guest-bridges-input.lock.json'))['repositoryInputs'])
    pending.update({'runtime/shader_generation.py','runtime/turnip/sources.lock.json',
        'runtime/turnip/android-provider.lock.json','runtime/turnip/.dockerignore',
        'runtime/bridges/android-provider.lock.json','runtime/bridge-reference.json',
        'runtime/client/dependency-release.lock.json','runtime/wine-arm64-adoption/x11-runtime.lock.json'})
    pending.update({'runtime/evidence/wine-arm64-selected471-41069065089.json',
        'runtime/evidence/wine-arm64-providers-41073499555.json',
        'runtime/evidence/wine-arm64-public-consumer-41079114080.json',
        'runtime/evidence/wine-arm64-source-recovery-41079114080.json'})
    result={};total=0
    while pending:
        name=min(pending);pending.remove(name);raw=wine.git_blob(revision,name)
        total+=len(raw);require(total<=24<<20 and len(result)<160,'cohort-recipe-bound')
        require(client.small(ROOT/name)==raw,'cohort-executing-recipe-changed:'+name)
        result[name]=wine.bytes_identity(raw)
        if not name.endswith('.py'):continue
        for node in ast.walk(ast.parse(raw,filename=name)):
            modules=[];extra=[]
            if isinstance(node,ast.ImportFrom):
                modules=[node.module.split('.')[0]] if node.module else [x.name for x in node.names]
                if node.module and node.module.startswith('runtime'):
                    extra=[node.module.replace('.','/')+'.py']
                    extra += [node.module.replace('.','/')+'/'+x.name+'.py' for x in node.names]
                if node.level:
                    base=Path(name).parent
                    for _ in range(node.level-1):base=base.parent
                    extra += [str(base/((node.module.replace('.','/') if node.module else x.name)+'.py')) for x in node.names]
            elif isinstance(node,ast.Import):modules=[x.name.split('.')[0] for x in node.names]
            for path in ['tools/'+module+'.py' for module in modules]+extra:
                if path in tracked and path not in result:pending.add(path)
    return dict(sorted(result.items()))


def fresh(path):
    require(not os.path.lexists(path),'cohort-existing-output-preserved')
    client.archives.directory(path.parent,create=True);path.mkdir(mode=0o700)


def copy(source,target):
    wine.copy_verified(source,target,identity(source))


def retain(source,target):
    """Retain immutable staged input bytes without duplicating a large ZIP."""
    pin=identity(source)
    try:os.link(source,target,follow_symlinks=False)
    except OSError:copy(source,target)
    client.verify_identity(target,pin)


def read_archive(path,inventory,output=None):
    """Read every deterministic member, rejecting links and unbounded extraction."""
    require(type(inventory) is dict and 1<=len(inventory)<=4096,'cohort-tar-inventory')
    total=sum(v['bytes'] for v in inventory.values());require(total<=512<<20,'cohort-tar-expanded-bound')
    seen=set()
    with client.archives.plain_file(path) as raw,client.archives.bounded_tar(raw,
            dict(entries=4096,pathBytes=4096,fileBytes=512<<20)) as archive:
        for entry in archive:
            require(entry.isfile() and entry.name in inventory and entry.name not in seen and
                client.archives.member_path(entry.name)==entry.name,'cohort-tar-member')
            pin=inventory[entry.name]
            require(entry.size==pin['bytes'] and entry.uid==entry.gid==entry.mtime==0 and
                not entry.uname and not entry.gname and entry.mode in (0o444,0o555),'cohort-tar-metadata')
            if output is None:
                with archive.extractfile(entry) as incoming:require(client.archives.hash_stream(incoming,entry.size)==pin['sha256'],'cohort-tar-member-hash')
            else:
                target=output/entry.name;client.archives.directory(target.parent,create=True)
                with archive.extractfile(entry) as incoming,target.open('xb') as outgoing:
                    require(client.archives.hash_stream(incoming,entry.size,outgoing)==pin['sha256'],'cohort-tar-member-hash')
            seen.add(entry.name)
    require(seen==set(inventory),'cohort-tar-incomplete')


def source_receipt(directory,archive_name,receipt_name,selected=None):
    receipt=json.loads(client.small(directory/receipt_name));require(receipt.get('archiveReadBack') is True and
        receipt['archive']==identity(directory/archive_name) and receipt.get('gameplayQualified') is False,
        'cohort-source-receipt')
    require(receipt.get('androidQualified',receipt.get('androidRuntimeQualified')) is False,'cohort-source-android-claim')
    if selected is not None:
        require(type(receipt.get('formatVersion')) is int and receipt['formatVersion']==1 and
            receipt.get('scope')=='retained-reconstructed-client-source-inputs' and
            set(receipt.get('selectedInputs',{}))==set(INPUTS) and receipt['selectedInputs']==selected,
            'cohort-client-source-exact-three-selected-inputs')
        require(receipt['clientArtifact']==json.loads(client.small(client.PIN))['artifact'] and
            receipt['source']['commit']=='471ee42faadf4a97a1d0a86989cf1452621f2dc5','cohort-client-source-selection')
        for name,pin in selected.items():require(receipt['members'].get('integration-recipe/'+name)==pin,'cohort-retained-selected-input')
        old=directory/'client-original-source-receipt.json'
        original_lock=json.loads(client.small(original.LOCK))
        client.verify_identity(old,original_lock['sourceReceipt'])
        original_receipt=json.loads(client.small(old))
        require(set(original_receipt.get('selectedInputs',{}))==original.SELECTED_INPUT_PATHS,
            'cohort-historical-two-input-schema-preserved')
        for name in ('client-source.tar','xvidcore-1.3.7.tar.gz'):
            require(receipt['members'][name]==original_receipt['members'][name],'cohort-original-client-source-changed')
    else:
        pin=shader_provider.load_pin(MEASURED/'shader-tools-input.lock.json')
        require(receipt.get('clientRevision')==pin['clientRevision'] and
            receipt.get('compilerProducerRevision')==pin['compilerIntegrationRevision'] and
            receipt.get('compilerProducerRun')==pin['artifact']['originalBuildRunId'] and
            receipt.get('members')==pin['files'],'cohort-exact-shader-source-bundle')
    read_archive(directory/archive_name,receipt['members'])
    return receipt


def bridge_sources(path):
    # The installable helper archive retains its source recipe. The adjacent
    # unchanged original ZIP additionally retains all direct Debian build sources.
    inventory=recovery.members(path)
    prefix='bridge/corresponding-source/original-archives/'
    with client.archives.plain_file(path) as raw,client.checked_zip(raw,(),maximum_entries=4096) as archive:
        lock=json.loads(measured.member(archive,'bridge/corresponding-source/build-recipe/sources.lock.json',2<<20))
        manifest=json.loads(measured.member(archive,prefix+'SOURCE-MANIFEST.json',2<<20))
    require(lock['runtimeArchiveSha256']==measured.RUNTIME,'cohort-guest-original-runtime-selection')
    expected=[];names=set()
    for source in lock['sources']:
        for row in source['archives']:
            name=row['file'];require(client.archives.member_path(name)==name and '/' not in name and name not in names,
                'cohort-guest-original-source-name')
            names.add(name);pin={key:row[key] for key in ('bytes','sha256')}
            require(inventory.get(prefix+name)==pin,'cohort-guest-original-source-hash:'+name)
            expected.append(dict(package=source['package'],version=source['version'],file=name,**pin))
    require(1<=len(names)<=256 and {n.removeprefix(prefix) for n in inventory if n.startswith(prefix)}==names|{'SOURCE-MANIFEST.json'} and
        type(manifest.get('formatVersion')) is int and manifest['formatVersion']==1 and manifest.get('files')==expected and
        manifest.get('completeGuestRootfsSourceClosure') is False,'cohort-guest-original-source-closure')
    return dict(originalArchives=len(names),allOriginalMembersReadBack=True,allLockedSourceArchivesVerified=True)


def validate_payload(directory,selected):
    # Whole payload identities are checked by the caller before any parsing.
    assets=json.loads(client.small(directory/'provider-assets-receipt.json'))
    require(type(assets.get('formatVersion')) is int and assets['formatVersion']==1 and assets.get('scope')=='source-owned-wine-four-provider-assets' and
        assets['runtimeArchiveSha256']==measured.RUNTIME and assets['selectedInputs']==selected,
        'cohort-provider-receipt-selection')
    require(all(assets.get(k) is False for k in ('androidQualified','hardwareQualified','gameplayQualified')),
        'cohort-provider-receipt-scope')
    require(assets['archive']==identity(directory/'provider-assets.tar.gz'),'cohort-assets-archive')
    source_receipt(directory,'client-corresponding-source.tar.gz','client-source-receipt.json',selected)
    source_receipt(directory,'shader-corresponding-source.tar.gz','shader-source-receipt.json')
    require(identity(directory/'client-original.zip')==json.loads(client.small(client.PIN))['artifact'],'cohort-original-client')
    guest_pin=json.loads(client.small(MEASURED/'guest-bridges-input.lock.json'))['artifact']
    for name,pin in [('guest-bridges-original.zip',guest_pin),
            ('turnip-source-complete.zip',json.loads(client.small(MEASURED/'turnip-input.lock.json'))['artifact'])]:
        client.verify_identity(directory/name,pin)
    bridge_sources(directory/'guest-bridges-original.zip')
    original_artifact=json.loads(client.small(MEASURED/'turnip-input.lock.json'))['artifact']['originalNativeBuildArtifact']
    client.verify_identity(directory/'turnip-original-native.zip',original_artifact)
    recovery.verify(directory/'turnip-original-native.zip',directory/'turnip-source-complete.zip',original_artifact)
    turnip_pin=turnip.load_pin(MEASURED/'turnip-input.lock.json')
    require(client.small(directory/'turnip-source-receipt.json')==encoded(turnip.verify_sources(directory/'turnip-source-complete.zip',turnip_pin)),
        'cohort-turnip-source-receipt')
    selection=json.loads(client.small(directory/'source-selection-receipt.json'))
    require(selection['selectedInputs']==selected and selection['archive']==identity(directory/'source-selection.tar.gz'),
        'cohort-source-selection-archive')
    read_archive(directory/'source-selection.tar.gz',selection['members'])
    for name,path in FIXED_FILES.items():require(identity(directory/name)==identity(path),'cohort-public-runtime-record')
    with tempfile.TemporaryDirectory(prefix='.cohort-provider-readback-',dir=directory.parent) as tmp:
        tree=Path(tmp);read_archive(directory/'provider-assets.tar.gz',assets['members'],tree/'assets')
        for name,(_,archive_name) in PROVIDERS.items():
            proof=json.loads(client.small(tree/'assets'/name/'provider.json'))
            require(proof['archive']['sha256']==identity(tree/'assets'/name/archive_name)['sha256'] and
                proof['requiredWineArchiveSha256']==measured.RUNTIME,'cohort-provider-wine-binding')
            if name=='client-runtime':
                require(proof['inputLockSha256']==selected['runtime/client/android-provider.lock.json']['sha256'] and
                    proof['requiredWineRuntime']['manifestSha256']==json.loads(client.small(INPUTS['runtime/runtime-sources.lock.json']))['packages']['wine-arm64']['manifest']['sha256'],
                    'cohort-client-provider-selection')
                client.audit(tree/'assets'/name/archive_name,proof['requiredFiles'])
        # Use the existing strict source/ELF/descriptor validators unchanged.
        for name,validator,args in [('guest-bridges',bridges.verify,dict(input_lock=MEASURED/'guest-bridges-input.lock.json',bridge_input_lock=MEASURED/'bridge-sources.lock.json')),
                ('shader-tools',shader_provider.verify,dict(input_lock=MEASURED/'shader-tools-input.lock.json')),
                ('turnip',turnip.verify,dict(input_lock=MEASURED/'turnip-input.lock.json'))]:
            provider=tree/name;provider.mkdir();(provider/'assets').mkdir()
            shutil.move(tree/'assets'/name,provider/'assets'/name)
            if name=='turnip':
                (provider/'sources').mkdir();os.link(directory/'turnip-source-complete.zip',provider/'sources'/turnip.SOURCE)
                copy(directory/'turnip-source-receipt.json',provider/'sources/source-receipt.json')
            validator(provider,**args)
    return dict(completeProviderAssetsReadBack=True,allRetainedSourceMembersReadBack=True,
        androidQualified=False,hardwareQualified=False,gameplayQualified=False)


def load_lock(path):
    value=wine.shared.small_json(path)
    require(type(value) is dict and set(value)=={'formatVersion','scope','repository','tag','targetCommit','selectedInputs','recipeInputs','files'} and
        type(value.get('formatVersion')) is int and value['formatVersion']==1 and value['scope']==SCOPE and
        value['repository']==wine.shared.REPOSITORY and value['tag']==TAG and set(value['files'])==PAYLOAD and
        value['selectedInputs']==selected_inputs(),'cohort-release-separate-schema')
    require(value['recipeInputs']==recipe_inputs(value['targetCommit']),'cohort-release-recipe')
    return value


def verify(directory,lock):
    require({p.name for p in directory.iterdir()}==ALL_FILES,'cohort-release-file-set')
    for name,pin in lock['files'].items():client.verify_identity(directory/name,pin)
    manifest=dict(formatVersion=1,scope=SCOPE,targetCommit=lock['targetCommit'],tag=TAG,
        selectedInputs=lock['selectedInputs'],assets=lock['files'])
    require(client.small(directory/'release-manifest.json')==encoded(manifest),'cohort-release-manifest')
    sums=''.join(pin['sha256']+'  '+name+'\n' for name,pin in sorted(dict(lock['files'],**{'release-manifest.json':identity(directory/'release-manifest.json')}).items()))
    require(client.small(directory/'SHA256SUMS')==sums.encode(),'cohort-release-sums')
    validate_payload(directory,lock['selectedInputs'])
    return {p.name:identity(p) for p in sorted(directory.iterdir())}


def stage(inputs,client_artifact,target,output,lock_output=None,existing_lock=None):
    require(not os.path.lexists(output) and (lock_output is None or not os.path.lexists(lock_output)),'cohort-existing-output-preserved')
    recipe=recipe_inputs(target);selected=selected_inputs();fresh(output)
    for name,relative in SOURCE_FILES.items():retain(inputs/relative,output/name)
    for name,path in FIXED_FILES.items():copy(path,output/name)
    retain(client_artifact,output/'client-original.zip');(output/'NOTICE.txt').write_bytes(NOTICE)
    with tempfile.TemporaryDirectory(prefix='.cohort-stage-',dir=output.parent) as tmp:
        tree=Path(tmp);assets=tree/'assets';assets.mkdir()
        for name,(directory,_) in PROVIDERS.items():shutil.copytree(inputs/directory/'assets'/name,assets/name)
        inventory={str(p.relative_to(assets)):identity(p) for p in sorted(assets.rglob('*')) if p.is_file()}
        client.write_archive(output/'provider-assets.tar.gz',assets,inventory)
        receipt=dict(formatVersion=1,scope='source-owned-wine-four-provider-assets',runtimeArchiveSha256=measured.RUNTIME,
            selectedInputs=selected,archive=identity(output/'provider-assets.tar.gz'),members=inventory,
            androidQualified=False,hardwareQualified=False,gameplayQualified=False)
        (output/'provider-assets-receipt.json').write_bytes(encoded(receipt))
        sources=tree/'selection';sources.mkdir()
        for name,path in INPUTS.items():
            destination=sources/'selected-inputs'/name;destination.parent.mkdir(parents=True,exist_ok=True);copy(path,destination)
        for name,pin in recipe.items():
            destination=sources/'recipe'/name;destination.parent.mkdir(parents=True,exist_ok=True);copy(ROOT/name,destination)
        native={name:json.loads(client.small(MEASURED/path))['artifact'] for name,path in
            [('guest','guest-bridges-input.lock.json'),('turnip','turnip-input.lock.json'),('shader','shader-tools-input.lock.json')]}
        (sources/'retained-native-artifact-selection.json').write_bytes(encoded(native))
        members={str(p.relative_to(sources)):identity(p) for p in sorted(sources.rglob('*')) if p.is_file()}
        client.write_archive(output/'source-selection.tar.gz',sources,members)
        (output/'source-selection-receipt.json').write_bytes(encoded(dict(formatVersion=1,selectedInputs=selected,
            archive=identity(output/'source-selection.tar.gz'),members=members)))
    files={p.name:identity(p) for p in sorted(output.iterdir())}
    require(set(files)==PAYLOAD,'cohort-payload-file-set')
    lock=dict(formatVersion=1,scope=SCOPE,repository=wine.shared.REPOSITORY,tag=TAG,targetCommit=target,
        selectedInputs=selected,recipeInputs=recipe,files=files)
    require(existing_lock is None or lock==existing_lock,'cohort-reproduced-release-differs')
    manifest=dict(formatVersion=1,scope=SCOPE,targetCommit=target,tag=TAG,selectedInputs=selected,assets=files)
    (output/'release-manifest.json').write_bytes(encoded(manifest))
    (output/'SHA256SUMS').write_text(''.join(pin['sha256']+'  '+name+'\n' for name,pin in sorted(dict(files,**{'release-manifest.json':identity(output/'release-manifest.json')}).items())))
    verify(output,lock)
    if lock_output is not None:wine.write_new(lock_output,encoded(lock))
    return lock


def prepare(output,client_source,producer_source,api=None):
    """Recover approved originals and repackage them; no compiler or Wine runs."""
    fresh(output);api=api if api is not None else PUBLICATION.Github(os.environ.get('GITHUB_TOKEN'))
    public_lock,pin=original.load_lock()
    original.fetch(PUBLICATION.Github(),output/'client-original-inputs',public_lock,pin,client_source)
    copy(output/'client-original-inputs/source-receipt.json',output/'client-original-source-receipt.json')
    source_pin=json.loads(client.small(MEASURED/'turnip-input.lock.json'))['artifact']
    requests=[('bridge',12985639875,41073499555,measured.PRODUCER,'bridge.zip'),
        ('turnip',12986648082,41073499555,measured.PRODUCER,'turnip.zip'),
        ('source-recovery',source_pin['id'],source_pin['runId'],source_pin['sourceRecoveryRevision'],'turnip-source-complete.zip')]
    for kind,artifact_id,run_id,revision,name in requests:
        run=api.json('/actions/runs/'+str(run_id));row=api.json('/actions/artifacts/'+str(artifact_id))
        require(run.get('id')==run_id and run.get('head_sha')==revision and run.get('status')=='completed' and
            run.get('conclusion')=='success' and row.get('id')==artifact_id and row.get('expired') is False and
            row.get('workflow_run',{}).get('id')==run_id and row['workflow_run'].get('head_sha')==revision,
            'cohort-retained-successful-producer')
        if kind=='bridge':expected=json.loads(client.small(MEASURED/'guest-bridges-input.lock.json'))['artifact']
        elif kind=='turnip':expected=source_pin['originalNativeBuildArtifact']
        else:expected=source_pin
        require(row['size_in_bytes']==expected['bytes'] and row.get('digest')=='sha256:'+expected['sha256'],
            'cohort-retained-artifact-api-identity')
        api.download(wine.shared.API+'/actions/artifacts/'+str(artifact_id)+'/zip',output/name,expected)
        metadata_name='source-recovery-artifact.json' if kind=='source-recovery' else kind+'-artifact.json'
        (output/metadata_name).write_bytes(encoded(row))
        (output/('source-recovery-run.json' if kind=='source-recovery' else 'run.json')).write_bytes(encoded(run))
    measured.measure(output/'run.json',output/'bridge-artifact.json',output/'bridge.zip',
        output/'turnip-artifact.json',output/'turnip.zip',output/'remeasured',
        output/'source-recovery-run.json',output/'source-recovery-artifact.json',output/'turnip-source-complete.zip')
    for actual,selected in [('guest-bridges.proposed.lock.json','guest-bridges-input.lock.json'),
        ('turnip.proposed.lock.json','turnip-input.lock.json'),('bridge-sources.lock.json','bridge-sources.lock.json'),
        ('turnip-sources.lock.json','turnip-sources.lock.json')]:
        require(identity(output/'remeasured'/actual)==identity(MEASURED/selected),'cohort-original-remeasurement-changed')
    bridges.build(output/'bridge.zip',output/'bridge-provider',input_lock=MEASURED/'guest-bridges-input.lock.json',
        bridge_input_lock=MEASURED/'bridge-sources.lock.json')
    turnip.build(output/'turnip-source-complete.zip',output/'turnip-provider',input_lock=MEASURED/'turnip-input.lock.json')
    client.run(output/'client-original-inputs'/original.ARTIFACT,client_source,output/'client-provider',
        runtime_lock=INPUTS['runtime/runtime-sources.lock.json'])
    old_source=json.loads(client.small(output/'client-original-source-receipt.json'))
    with tarfile.open(output/'client-original-inputs'/original.SOURCE_ARCHIVE,'r|gz') as archive:
        count=0;found=False
        for entry in archive:
            count+=1;require(count<=64,'cohort-original-client-source-entry-bound')
            if entry.name=='xvidcore-1.3.7.tar.gz':
                require(not found and entry.isfile() and entry.size==old_source['xvid']['bytes'],'cohort-original-xvid')
                with archive.extractfile(entry) as incoming,(output/'xvidcore-1.3.7.tar.gz').open('xb') as outgoing:
                    require(client.archives.hash_stream(incoming,entry.size,outgoing)==old_source['xvid']['sha256'],'cohort-original-xvid-hash')
                found=True
        require(found,'cohort-original-xvid-missing')
    client_sources.build(client_source,output/'xvidcore-1.3.7.tar.gz',output/'client-sources-selected3',
        INPUTS['sources.lock.json'],INPUTS['runtime/client/android-provider.lock.json'],INPUTS['runtime/runtime-sources.lock.json'])
    prepare_shaders(output,client_source,producer_source,pin,source_pin)
    return dict(prepared=True,binariesRecompiled=False,androidQualified=False,gameplayQualified=False)


def shader_source_names():
    selected=json.loads(client.small(MEASURED/'turnip-sources.lock.json'))
    return {'corresponding-source/original-archives/'+selected['upstream'][name]['file'] for name in shaders.SOURCES}


def prepare_shaders(output,client_source,producer_source,pin,source_pin):
    # Select the compiler, its source originals, recipe and notices without
    # expanding the unrelated Mesa source archive or any runtime filesystem.
    compiler_pin=json.loads(client.small(MEASURED/'shader-tools-input.lock.json'))
    payload=output/'shader-payload';payload.mkdir()
    allowed={'turnip-build.json','bin/glslangValidator','shader-tool-check/qualification.json'}|shader_source_names()
    count=total=0
    with client.archives.plain_file(output/'turnip-source-complete.zip') as stream,client.checked_zip(stream,(),maximum_entries=4096) as archive:
        for item in archive.infolist():
            if not item.filename.startswith('turnip/'):continue
            name=item.filename.removeprefix('turnip/')
            if name not in allowed and not name.startswith(('corresponding-source/build-recipe/','notices/')) :continue
            require(not item.is_dir() and stat.S_ISREG(item.external_attr>>16) and item.file_size<=32<<20,'cohort-shader-selected-member')
            count+=1;total+=item.file_size;require(count<=128 and total<=64<<20,'cohort-shader-selected-total-bound')
            target=payload/name;target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(item) as incoming,target.open('xb') as outgoing:client.archives.hash_stream(incoming,item.file_size,outgoing)
    shaders.build(output/'shader-bundle',client_source,pin['sourceRevision'],payload,compiler_pin['compilerBuildSha256'],
        producer_source,measured.PRODUCER,MEASURED/'turnip-sources.lock.json')
    shader_provider.build(output/'shader-bundle',output/'shader-provider-verified',MEASURED/'shader-tools-input.lock.json')
    inventory={str(p.relative_to(output/'shader-bundle')):identity(p) for p in sorted((output/'shader-bundle').rglob('*')) if p.is_file()}
    require(inventory==compiler_pin['files'],'cohort-reproduced-shader-sources-changed')
    client.write_archive(output/'shader-corresponding-source.tar.gz',output/'shader-bundle',inventory)
    shader_receipt=dict(formatVersion=1,archive=identity(output/'shader-corresponding-source.tar.gz'),members=inventory,
        archiveReadBack=True,clientRevision=pin['sourceRevision'],compilerProducerRevision=measured.PRODUCER,
        compilerProducerRun=measured.RUN,completeWineRootfsSourceClosure=False,androidQualified=False,gameplayQualified=False,
        runtimeArchiveSha256=measured.RUNTIME,scope='retained-selected471-source-owned-runtime-shader-bundle',
        sourceRecoveryRun=source_pin['runId'])
    (output/'shader-source-receipt.json').write_bytes(encoded(shader_receipt))


def body(lock):
    return ('Dependency-only archival prerelease: selected reconstructed client471ee42f and four providers bound to source-owned Winec0e13ed15a69.\n\n'
        'Exact packaging recipe `'+lock['targetCommit']+'`. Original successful native provider workflow41073499555 and source-only recovery41079114080 remain distinct. '
        'All provider asset bytes, original client/guest/native Turnip ZIPs, complete provider source companions and their exact selected inputs are retained and independently read back. '
        'The complete original Wine source ZIP is pinned through its separate public source release. Three-key selected client source inputs are a new cohort schema; historical client releases are unchanged.\n\n'
        'Linux ARM64 component fixtures only. Android, Adreno, audible output, CommonMain/assets, world entry and gameplay remain unqualified. No APK, game data, accounts, initialized database/prefix or private saves.\n\n'
        'This uploader only adds missing exact assets to an existing owned UI draft. It never creates/finalizes a release, moves tags, replaces assets or changes repository settings.\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('operation',choices=('prepare','stage','verify','body','upload-draft','verify-published'))
    parser.add_argument('--release-lock',type=Path,default=LOCK);parser.add_argument('--inputs',type=Path)
    parser.add_argument('--client-artifact',type=Path);parser.add_argument('--target');parser.add_argument('--output',type=Path)
    parser.add_argument('--wait-seconds',type=int,default=0);parser.add_argument('--client-source',type=Path);parser.add_argument('--producer-source',type=Path);args=parser.parse_args()
    if args.operation=='prepare':
        print(json.dumps(prepare(args.output,args.client_source,args.producer_source),indent=2));return
    if args.operation=='stage':
        lock=stage(args.inputs,args.client_artifact,args.target,args.output,args.release_lock);print(json.dumps(lock,indent=2));return
    lock=load_lock(args.release_lock)
    if args.operation=='body':print(body(lock),end='');return
    if args.operation=='verify':result=verify(args.inputs,lock)
    else:
        publisher=PUBLICATION.DraftPublication(lock,body(lock),lambda path:verify(path,lock));api=PUBLICATION.Github(os.environ.get('GITHUB_TOKEN'))
        result=publisher.upload_draft(api,args.inputs) if args.operation=='upload-draft' else publisher.verify_published(api,args.inputs,args.wait_seconds)
    if args.output:wine.write_new(args.output,encoded(result))
    else:print(json.dumps(result,indent=2))


if __name__=='__main__':main()
