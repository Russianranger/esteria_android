#!/usr/bin/env python3
"""Measure or consume exact debug-provider artifacts, never enable a selection.

The committed transport lock is disabled. A measurement-only producer needs real
native SQL first; a consumer additionally needs separately committed descriptor,
readback and artifact identities. Full source/ZIP readback precedes APK use.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

if not __package__:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import provider_android_installation_x64 as provider
from tools import qualify_server_providers as transfer
from tools import prepare_server_requalification as remote

ROOT=Path(__file__).resolve().parents[1]
LOCK=ROOT/'runtime/mysql-probe/android-installation-x64-provider-artifacts.lock.json'
SCOPE='android-x64-installation-provider-artifact-selection'
FALSE_FLAGS=('sqlExecuted','androidRuntimeQualified','productionArm64ProviderQualified','fourSchemaCoordinatorQualified',
    'worldserverQualified','playerbotsAiQualified','gameplayQualified','slotPromoted','serverDataQualified')
SMALL={'provider.json','provider-readback.json','measurement.json','product-manifest.json','source-manifest.json','measurement-source.json'}
MANIFEST='PRODUCT-MANIFEST.json'
gate=provider.gate
native=provider.native
files=provider.files
require=provider.require


def artifact(row,maximum=8<<30):
    require(type(row) is dict and set(row)=={'id','bytes','sha256'} and type(row['id']) is int and row['id']>0,
        'installation-provider-exact-artifact-required')
    gate.identity({key:row[key] for key in ('bytes','sha256')},maximum)
    return row


def load_pin(*,require_enabled=False):
    pin=gate.small(LOCK,128<<10)
    require(type(pin) is dict and set(pin)=={'formatVersion','scope','repository','enabled','state',
        'producer','productArtifact','evidenceArtifact','measurementEvidence','providerDescriptor','productManifest',*FALSE_FLAGS} and
        type(pin['formatVersion']) is int and pin['formatVersion']==1 and pin['scope']==SCOPE and
        pin['repository']=='Russianranger/esteria_android' and type(pin['enabled']) is bool and
        all(pin[name] is False for name in FALSE_FLAGS),'installation-provider-selection-schema')
    fields=('producer','productArtifact','evidenceArtifact','measurementEvidence','providerDescriptor','productManifest')
    if not pin['enabled']:
        require(pin['state']=='pending-actual-provider-artifact-measurement' and all(pin[name] is None for name in fields),
            'installation-provider-pending-measurements-required')
        require(not require_enabled,'installation-provider-actual-artifact-measurements-required')
        return pin
    require(pin['state']=='measured-provider-artifacts','installation-provider-measured-state-required')
    selected=gate.load_pin(require_enabled=True)
    require(pin['providerDescriptor']==selected['provider'],'installation-provider-android-selection-differs')
    gate.identity(pin['providerDescriptor'],128<<10);gate.identity(pin['productManifest'],4<<20)
    producer=pin['producer']
    require(type(producer) is dict and set(producer)=={'workflowRun','job','integrationRevision'} and
        all(type(producer[name]) is int and producer[name]>0 for name in ('workflowRun','job')) and
        type(producer['integrationRevision']) is str and re.fullmatch('[a-f0-9]{40}',producer['integrationRevision']),
        'installation-provider-exact-producer-required')
    artifact(pin['productArtifact']);artifact(pin['evidenceArtifact'],16<<20)
    proof=gate.record(pin['measurementEvidence']);workflow=proof.get('workflow',{})
    require(proof.get('scope')=='independent-android-x64-provider-measurement-artifact-readback' and
        workflow.get('id')==producer['workflowRun'] and workflow.get('job')==producer['job'] and
        workflow.get('headSha')==producer['integrationRevision'] and workflow.get('status')=='completed' and
        workflow.get('conclusion')=='success' and proof.get('artifacts')==dict(product=pin['productArtifact'],evidence=pin['evidenceArtifact']) and
        proof.get('providerDescriptor')==pin['providerDescriptor'] and proof.get('productManifest')==pin['productManifest'] and
        proof.get('actualProviderReadback')==gate.record(selected['providerReadback']) and
        all(proof.get(name) is True for name in ('allSmallArtifactZipBytesReadBack','everySmallArtifactMemberCrcAndSha256Verified',
            'producerPackagingSourcesMatchExactGitBlobs','completeProductReadbackRequiredBeforeApk')) and
        all(proof.get(name) is False for name in FALSE_FLAGS),'installation-provider-independent-measurement-required')
    return pin


def git_archive(target,commit):
    require(type(commit) is str and re.fullmatch('[a-f0-9]{40}',commit),'installation-provider-exact-source-commit-required')
    require(not os.path.lexists(target),'installation-provider-source-archive-exists')
    environment=gate.frozen_mysql._git_environment()
    roster=subprocess.check_output(['git','-C',str(ROOT),'ls-tree','-r','-l',commit],stderr=subprocess.DEVNULL,env=environment)
    sizes=[int(row.split()[3]) for row in roster.splitlines()]
    require(1<=len(sizes)<=4096 and sum(sizes)<=64<<20,'installation-provider-source-archive-bound')
    with target.open('xb') as stream:
        subprocess.run(['git','-C',str(ROOT),'archive','--format=tar',commit],stdout=stream,stderr=subprocess.DEVNULL,check=True,timeout=120,env=environment)
        stream.flush();os.fsync(stream.fileno())
    require(0<target.stat().st_size<=128<<20,'installation-provider-source-archive-bound')
    target.chmod(0o444);return files.identity(target)


def canonical_recipe(recipe):
    require(set(recipe.get('files',{}))==set(provider.recipe_names()),'installation-provider-recipe-source-set-differs')
    for name,row in recipe['files'].items():
        raw=subprocess.check_output(['git','-C',str(ROOT),'show',recipe['commit']+':'+name],
            stderr=subprocess.DEVNULL,env=gate.frozen_mysql._git_environment())
        require(provider.identity_bytes(raw)==row,'installation-provider-canonical-git-recipe-differs')


def product_manifest(product,readback,recipe):
    require(not os.path.lexists(product/MANIFEST),'installation-provider-product-manifest-exists')
    rows={path.relative_to(product).as_posix():files.identity(path) for path in files.installed_files(product)}
    require(1<=len(rows)<=10000 and sum(row['bytes'] for row in rows.values())<=8<<30,
        'installation-provider-product-inventory-bound')
    for name in rows:
        provider.engine.content.safe_path(name)
        require(name.startswith(('provider/','corresponding-source/')) or name in ('measurement.json','measurement-recipe.tar'),
            'installation-provider-unexpected-product-file')
    return dict(formatVersion=1,scope='closed-android-x64-installation-provider-product-no-execution',files=rows,
        fileBytes=sum(row['bytes'] for row in rows.values()),providerDescriptor=readback['providerDescriptor'],
        sourceCompanionManifest=readback['sourceCompanionManifest'],integrationRecipe=recipe,
        **{name:False for name in FALSE_FLAGS})


def seal(product,evidence):
    gate.load_pin(require_native=True)  # Initial pending state refuses before output.
    product=native.archives.directory(product);evidence=provider.sql.fresh(evidence)
    readback=provider.readback(product)
    descriptor=provider.verify(product/'provider')
    canonical_recipe(descriptor['currentPackagingRecipe'])
    commit=descriptor['currentPackagingRecipe']['commit']
    require(subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()==commit and
        provider.source_snapshot()==descriptor['currentPackagingRecipe'],
        'installation-provider-measurement-requires-exact-clean-recipe-p')
    recipe=git_archive(product/'measurement-recipe.tar',commit)
    manifest=product_manifest(product,readback,recipe);provider.engine.put_metadata(product/MANIFEST,manifest)
    provider.engine.put_metadata(evidence/'provider-readback.json',readback)
    for source,target in ((product/'provider/assets/installation-probe/provider.json','provider.json'),
            (product/'measurement.json','measurement.json'),(product/MANIFEST,'product-manifest.json'),
            (product/'corresponding-source/SOURCE-MANIFEST.json','source-manifest.json')):
        provider.copy(source,evidence/target,files.identity(source))
    provider.engine.put_metadata(evidence/'measurement-source.json',dict(formatVersion=1,
        scope='exact-provider-measurement-source-p-no-execution',integrationRevision=commit,integrationRecipe=recipe,
        sourceFiles=descriptor['currentPackagingRecipe']['files'],
        androidInputSelection=files.identity(gate.LOCK),nativeInputSelection=files.identity(native.LOCK),
        **{name:False for name in FALSE_FLAGS}))
    require({p.name for p in evidence.iterdir()}==SMALL,'installation-provider-small-evidence-closure')
    return dict(providerDescriptor=readback['providerDescriptor'],productManifest=files.identity(product/MANIFEST),
        sourceRevision=commit,sqlExecuted=False,androidRuntimeQualified=False)


def restore_product(archive,output,expected_manifest):
    """Read all original ZIP members and exact closed inventory before use."""
    expected_manifest=gate.identity(expected_manifest,4<<20);output=provider.sql.fresh(output)
    with files.plain_file(archive) as stream,native.zips.checked_zip(stream,required=(MANIFEST,),maximum_bytes=8<<30,
            maximum_entries=10001,maximum_directory=16<<20) as bundle:
        item=bundle.getinfo(MANIFEST);require(not item.is_dir() and stat.S_IFMT(item.external_attr>>16) in (0,stat.S_IFREG) and
            item.file_size==expected_manifest['bytes'] and item.file_size<=4<<20,
            'installation-provider-product-manifest-size')
        raw=bundle.read(item);require(provider.identity_bytes(raw)==expected_manifest,'installation-provider-product-manifest-changed')
        value=json.loads(raw,object_pairs_hook=gate._unique);rows=value.get('files')
        require(value.get('formatVersion')==1 and value.get('scope')=='closed-android-x64-installation-provider-product-no-execution' and
            type(rows) is dict and 1<=len(rows)<=10000 and set(bundle.namelist())==set(rows)|{MANIFEST} and
            type(value.get('fileBytes')) is int and 0<value['fileBytes']<=8<<30 and
            sum(row.get('bytes',0) for row in rows.values())==value['fileBytes'] and
            all(value.get(name) is False for name in FALSE_FLAGS),'installation-provider-product-closure')
        for name,row in rows.items():
            provider.engine.content.safe_path(name);expected=native.identity(row,2<<30)
            require(name.startswith(('provider/','corresponding-source/')) or name in ('measurement.json','measurement-recipe.tar'),
                'installation-provider-product-file-namespace')
            member=bundle.getinfo(name)
            require(not member.is_dir() and stat.S_IFMT(member.external_attr>>16) in (0,stat.S_IFREG) and member.file_size==expected['bytes'],
                'installation-provider-product-member-kind-or-size')
            target=output/name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with bundle.open(member) as incoming,target.open('xb') as outgoing:
                require(native.archives.hash_stream(incoming,member.file_size,outgoing)==expected['sha256'],
                    'installation-provider-product-member-changed')
                outgoing.flush();os.fsync(outgoing.fileno())
            target.chmod(0o555 if '/original-proot-provider/jniLibs/' in name else 0o444)
        remote.write_new(output/MANIFEST,raw)
    return value


def evidence_members(path):
    with files.plain_file(path) as stream,native.zips.checked_zip(stream,required=SMALL,
            maximum_bytes=16<<20,maximum_entries=6,maximum_directory=1<<20) as bundle:
        require(set(bundle.namelist())==SMALL,'installation-provider-evidence-file-closure')
        rows=bundle.infolist()
        require(sum(row.file_size for row in rows)<=16<<20 and all(not row.is_dir() and
            stat.S_IFMT(row.external_attr>>16) in (0,stat.S_IFREG) and 0<row.file_size<=4<<20 for row in rows),
            'installation-provider-evidence-expanded-bound')
        return {name:bundle.read(name) for name in SMALL}


def remote_producer(api,producer):
    run=api.json('/actions/runs/'+str(producer['workflowRun']));job=api.json('/actions/jobs/'+str(producer['job']))
    require(run.get('id')==producer['workflowRun'] and run.get('head_sha')==producer['integrationRevision'] and
        run.get('status')=='completed' and run.get('conclusion')=='success' and job.get('id')==producer['job'] and
        job.get('run_id')==producer['workflowRun'] and job.get('status')=='completed' and job.get('conclusion')=='success',
        'installation-provider-original-producer-no-longer-successful')


def acquire(output,frozen_source,api=None):
    pin=load_pin(require_enabled=True)  # No download/output before committed measurements.
    original=gate.frozen_mysql.inspect(frozen_source)
    output=provider.sql.fresh(output);api=api or remote.Github(os.environ.get('GITHUB_TOKEN'))
    require(shutil.disk_usage(output).free>=16<<30,'installation-provider-acquisition-requires-16-gib-free')
    producer=pin['producer']
    remote_producer(api,producer)
    for name,row in (('product',pin['productArtifact']),('evidence',pin['evidenceArtifact'])):
        transfer.verify_remote(api,dict(row,workflowRun=producer['workflowRun'],integrationRevision=producer['integrationRevision']))
        api.download(remote.API+'/actions/artifacts/'+str(row['id'])+'/zip',output/(name+'.zip'),row)
    product=output/'product';manifest=restore_product(output/'product.zip',product,pin['productManifest'])
    require(manifest['providerDescriptor']==pin['providerDescriptor'],'installation-provider-product-descriptor-selection-differs')
    # The small artifact must be fully read too, even though the complete product
    # has independently pinned corresponding bytes.
    small=evidence_members(output/'evidence.zip')
    require(provider.identity_bytes(small['provider.json'])==pin['providerDescriptor'] and
        provider.identity_bytes(small['product-manifest.json'])==pin['productManifest'],
        'installation-provider-evidence-product-pins-differ')
    for name,path in (('provider.json',product/'provider/assets/installation-probe/provider.json'),
            ('product-manifest.json',product/MANIFEST),('measurement.json',product/'measurement.json'),
            ('source-manifest.json',product/'corresponding-source/SOURCE-MANIFEST.json')):
        require(provider.identity_bytes(small[name])==files.identity(path),'installation-provider-small-and-complete-member-differ')
    readback=provider.readback(product)
    selected=gate.load_pin(require_enabled=True)
    require(json.loads(small['provider-readback.json'])==readback==gate.record(selected['providerReadback']),
        'installation-provider-actual-full-source-readback-differs')
    descriptor=provider.verify(product/'provider',pin['providerDescriptor']);provider.require_current_code(descriptor['currentPackagingRecipe'])
    canonical_recipe(descriptor['currentPackagingRecipe'])
    require(descriptor['currentPackagingRecipe']['commit']==producer['integrationRevision'],
        'installation-provider-recipe-and-artifact-producer-differ')
    source=json.loads(small['measurement-source.json'])
    require(source.get('formatVersion')==1 and source.get('scope')=='exact-provider-measurement-source-p-no-execution' and
        source.get('integrationRevision')==producer['integrationRevision'] and source.get('integrationRecipe')==manifest['integrationRecipe'] and
        source.get('sourceFiles')==descriptor['currentPackagingRecipe']['files'] and
        source.get('nativeInputSelection')==native.identity(selected['nativeSql']['inputSelection']) and
        all(source.get(name) is False for name in FALSE_FLAGS), 'installation-provider-actual-producer-source-differs')
    original_selection=subprocess.check_output(['git','-C',str(ROOT),'show',producer['integrationRevision']+':'+gate.LOCK.relative_to(gate.ROOT).as_posix()],
        stderr=subprocess.DEVNULL,env=gate.frozen_mysql._git_environment())
    require(source.get('androidInputSelection')==provider.identity_bytes(original_selection),
        'installation-provider-original-p-selection-differs')
    # Verify canonical P Git bytes while current activation may be Q.
    observed=git_archive(output/'recipe-recomputed.tar',producer['integrationRevision'])
    require(observed==manifest['integrationRecipe'] and files.identity(product/'measurement-recipe.tar')==observed,
        'installation-provider-exact-original-recipe-p-differs')
    locked=original['originalPin'];row=locked['artifacts']['inputs']
    transfer.verify_remote(api,dict(row,workflowRun=locked['producer']['workflowRun'],integrationRevision=locked['producer']['integrationRevision']))
    api.download(remote.API+'/actions/artifacts/'+str(row['id'])+'/zip',output/'mysql-inputs.zip',row)
    provider.mysql.restore_inputs(output/'mysql-inputs.zip',output/'original-mysql-inputs',locked)
    provider.mysql.restore_proot(output/'original-mysql-inputs/probe.apk',output/'proot-provider')
    mysql_assets=output/'original-mysql-inputs/provider/assets/mysql-probe'
    for name in provider.mysql.retained.builder.NAMES:
        provider.copy(mysql_assets/name,output/'mysql-provider/assets/mysql-probe'/name,
            locked['files']['provider/assets/mysql-probe/'+name])
    external=provider.verify_external(product/'provider',frozen_source,output/'mysql-provider',output/'proot-provider')
    os.rename(product/'provider',output/'provider');os.rename(product/'corresponding-source',output/'corresponding-source')
    result=dict(formatVersion=1,scope='measured-android-x64-provider-complete-source-acquisition-no-execution',
        artifactSelection=files.identity(LOCK),providerDescriptor=pin['providerDescriptor'],productManifest=pin['productManifest'],
        actualProviderReadback=readback,actualExternalRuntimeVerification=external,
        allProductZipBytesAndMembersVerified=True,allOriginalSourcesAndDebugReadBack=True,
        originalRecipePAndCurrentActivationCodeBoundSeparately=True,historicalJavaProofAppliesToCurrentCaller=False,
        **{name:False for name in FALSE_FLAGS})
    provider.engine.put_metadata(output/'acquisition.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('selection')
    measure=commands.add_parser('seal');measure.add_argument('--product',type=Path,required=True);measure.add_argument('--evidence',type=Path,required=True)
    fetch=commands.add_parser('acquire');fetch.add_argument('--output',type=Path,required=True);fetch.add_argument('--frozen-source',type=Path,required=True)
    args=parser.parse_args()
    value=load_pin() if args.command=='selection' else seal(args.product,args.evidence) if args.command=='seal' else acquire(args.output,args.frozen_source)
    print(provider.encode(value).decode(),end='')


if __name__=='__main__':main()
