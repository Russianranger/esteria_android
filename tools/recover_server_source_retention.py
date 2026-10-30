#!/usr/bin/env python3
"""Recover an exact already-qualified source archive after an upload-only failure.

Configure regenerates missing metadata; it never supplies a new full-build claim.
Every member and the final compressed archive must match the original receipts.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys

if not __package__:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import package_server_engine as engine,prepare_runtime as archives
from tools import prepare_server_requalification as remote,prepare_server_isolated_build as inputs
from tools import qualify_server_isolated_build as isolated,server_provider_sources as sources
from tools import verify_server_build as files

ROOT=Path(__file__).resolve().parents[1]
LOCK=ROOT/'runtime/server/isolated-source-recovery.lock.json'
require=files.require


def load_pin():
    pin,_=engine.modules.read_json(LOCK)
    require(pin.get('formatVersion')==1 and pin.get('scope')=='exact-successful-isolated-build-source-retention-recovery' and
            pin.get('repository')=='Russianranger/esteria_android' and
            re.fullmatch('[0-9a-f]{40}',pin.get('integrationRevision','')) and
            pin.get('archiveEntries')==266 and pin.get('archiveFileBytes')==126583360 and
            pin.get('originalWorkspace')=='/home/runner/work/esteria_android/esteria_android' and
            pin.get('minimumFreeBytes')==16*1024**3,'invalid-source-retention-recovery-pin')
    for flag in ('fullServerCompilationPerformed','newNativeQualificationClaimed','androidRuntimeQualified','gameplayQualified'):
        require(pin.get(flag) is False,'invalid-source-retention-qualification-claim')
    for name in ('qualification','sealedReceipt','archive','evidenceArtifact'):
        row=pin[name]
        require(type(row.get('bytes')) is int and 0<row['bytes']<=64*1024**2 and
                re.fullmatch('[0-9a-f]{64}',row.get('sha256','')),'invalid-source-retention-input-identity')
    require(pin['archive'].get('file')==isolated.SOURCE_ARCHIVE and
            all(type(pin.get(name)) is int and pin[name]>0 for name in ('workflowRun','job')) and
            type(pin['evidenceArtifact'].get('id')) is int and pin['evidenceArtifact']['id']>0,
            'invalid-source-retention-remote-identity')
    require({pin[name] for name in ('originalPrepared','originalInputs','originalOutput','originalProtocol')}==
            {'out/isolated-tree','out/isolated-inputs','out/isolated-rebuild','out/protocol-reference'},
            'invalid-source-retention-original-paths')
    return pin


def verify_remote(api,pin):
    run=api.json('/actions/runs/'+str(pin['workflowRun']))
    job=api.json('/actions/jobs/'+str(pin['job']))
    require(run.get('id')==pin['workflowRun'] and run.get('head_sha')==pin['integrationRevision'] and
            run.get('status')=='completed' and run.get('conclusion')=='failure' and
            job.get('id')==pin['job'] and job.get('run_id')==pin['workflowRun'] and
            job.get('status')=='completed' and job.get('conclusion')=='failure','original-source-build-result-changed')
    steps={row['number']:row for row in job['steps']}
    require(all(steps.get(n,{}).get('conclusion')=='success' for n in range(3,10)) and
            steps.get(10,{}).get('conclusion')=='failure' and steps.get(11,{}).get('conclusion')=='success',
            'original-source-failure-is-not-retention-only')
    row=pin['evidenceArtifact'];actual=api.json('/actions/artifacts/'+str(row['id']))
    require(actual.get('id')==row['id'] and actual.get('expired') is False and
            actual.get('size_in_bytes')==row['bytes'] and actual.get('digest')=='sha256:'+row['sha256'] and
            actual.get('workflow_run',{}).get('id')==pin['workflowRun'] and
            actual.get('workflow_run',{}).get('head_sha')==pin['integrationRevision'],
            'source-recovery-original-evidence-artifact-changed')


def verify_evidence(directory,pin):
    qualification,qid=engine.modules.read_json(directory/'qualification.json')
    sealed,sid=engine.modules.read_json(directory/'sealed-source-receipt.json')
    require(qid==pin['qualification'] and sid==pin['sealedReceipt'],'source-recovery-original-receipt-changed')
    require(qualification.get('scope')=='actual-native-arm64-isolated-server-source-rebuild' and
            qualification.get('phase')=='complete' and
            all(qualification.get(n) is True for n in ('fullBuildAndReferencesPassed','fullCompileObserved',
                'isolatedSourceRebuildQualified','sourceCompanionComplete','transitiveIncludeClosureProved')) and
            all(qualification.get(n) is False for n in ('sqlExecuted','worldserverSessionStarted',
                'androidRuntimeQualified','gameplayQualified','sourceBitIdenticalBinaryClaimed')),
            'source-recovery-successful-original-build-required')
    require(sealed.get('scope')=='complete-isolated-server-source-rebuild-companion' and
            sealed.get('qualification')==qid and sealed.get('archive')==pin['archive'] and
            all(sealed.get(n) is True for n in ('archiveReadbackVerified','sourceCompanionComplete',
                'isolatedSourceRebuildQualified','originalUnsealedReceiptsUnchanged')) and
            sealed.get('originalBuild')==qualification.get('originalBuild') and
            sealed.get('originalCompiledModules')==qualification.get('originalCompiledModules') and
            sealed.get('sourceLock')==qualification.get('sourceLock'),'source-recovery-original-sealed-binding')
    rows=sealed.get('archiveFiles',{})
    require(len(rows)==pin['archiveEntries'] and sum(r['bytes'] for r in rows.values())==pin['archiveFileBytes'],
            'source-recovery-original-archive-inventory')
    for name,row in rows.items():
        engine.content.safe_path(name)
        require(type(row.get('bytes')) is int and 0<=row['bytes']<=64*1024**2 and row.get('mode')==0o444 and
                re.fullmatch('[0-9a-f]{64}',row.get('sha256','')),'source-recovery-invalid-original-member')
    manifest,_=engine.modules.read_json(directory/'environment-receipt.json')
    require({p.relative_to(directory).as_posix() for p in files.installed_files(directory)}==
            set(manifest['files'])|{'environment-receipt.json'},
            'source-recovery-evidence-file-set')
    for name,row in manifest['files'].items():
        require(Path(name).name==name and files.identity(directory/name)==row,'source-recovery-evidence-readback')
    return qualification,sealed


def acquire(output,api=None):
    pin=load_pin();output=Path(os.path.abspath(output));archives.directory(output.parent,create=True)
    require(not os.path.lexists(output),'existing-source-recovery-evidence-preserved')
    api=api or remote.Github(os.environ.get('GITHUB_TOKEN'));verify_remote(api,pin)
    output.mkdir(mode=0o700);archive_path=output/'original-evidence.zip';row=pin['evidenceArtifact']
    api.download(remote.API+'/actions/artifacts/'+str(row['id'])+'/zip',archive_path,row)
    require(files.identity(archive_path)==engine.identity(row),'source-recovery-evidence-download-changed')
    directory=output/'evidence';directory.mkdir()
    with remote.bounded_zip(archive_path) as (archive,members):
        require(0<len(members)<=32 and sum(r.file_size for r in members.values())<=4*1024**2,
                'source-recovery-evidence-expanded-bound')
        for name,item in members.items():
            require(Path(name).name==name and 0<=item.file_size<=1024**2,'source-recovery-evidence-member-bound')
            remote.write_new(directory/name,archive.read(item))
    verify_evidence(directory,pin)
    return dict(scope='exact-original-successful-source-build-evidence-readback',evidenceArtifact=row,
                originalRun=pin['workflowRun'],originalIntegrationRevision=pin['integrationRevision'])


def rebuild_plan():
    return dict(formatVersion=1,scope='offline-native-arm64-source-rebuild-recipe',workingDirectory='archive-root',
        originalSourceInputsRetained='inputs/source-inputs',sourcePreparationCommand=[
            'python3','recipes/tools/prepare_server_isolated_sources.py','--source-inputs','inputs/source-inputs',
            '--supplements','inputs/supplements','--output','prepared'],buildCommand=[
            'python3','recipes/tools/qualify_server_isolated_build.py','--prepared','prepared','--inputs','inputs',
            '--protocol-manifest','protocol/limits.json','--output','rebuild'],requiresNativeLinuxArm64=True,
        requiresLoopbackOnlyNetworkNamespace=True,environmentContract='recipes/runtime/server/isolated-build.lock.json',
        compilerCacheDisabled=True,sourceRepositoryFetchRequired=False,gameAssetsRequired=False,
        originalBinaryBitIdentityRequired=False)


def revision_metadata_arguments(cmake,prepared,output):
    # Replay the original revision.h custom target's CMake script, without
    # building any C/C++ target. Script mode has a different variable context
    # from CMakeLists.txt configuration and overwrites the configure-time header.
    return [cmake,'-DBUILDDIR='+str(output/'build'),
        '-DESTERIA_ARCHIVAL_REVISION_FILE='+str(prepared/'provenance/archival-revision.txt'),
        '-P',str(prepared/'source/src/cmake/genrev.cmake'),str(output/'build')]


def selected_files(sealed,*,integration,acquired,prepared,protocol,evidence,output,plan):
    selected={}
    for name,row in sealed['archiveFiles'].items():
        if name.startswith('recipes/'):path=integration/name[len('recipes/'):]
        elif name=='inputs/acquisition.json':path=evidence/'acquisition.json'
        elif name.startswith('inputs/'):path=acquired/name[len('inputs/'):]
        elif name.startswith('preparation/'):path=prepared/name[len('preparation/'):]
        elif name.startswith('protocol/'):path=protocol/name[len('protocol/'):]
        elif name.startswith('qualification/'):path=evidence/name[len('qualification/'):]
        elif name.startswith('new-build/generated/'):path=output/'build'/name[len('new-build/generated/'):]
        elif name.startswith('new-build/'):path=output/'build'/name[len('new-build/'):]
        elif name=='rebuild-plan.json':path=plan
        else:raise ValueError('source-recovery-unrecognized-original-member')
        require(files.identity(path)==engine.identity(row),'source-recovery-member-not-byte-identical:'+name)
        selected[name]=path
    return selected


def publish_exact(selected,sealed,evidence,destination,receipt_identities):
    require(not os.path.lexists(destination),'existing-source-recovery-publication-preserved')
    for name in ('qualification.json','sealed-source-receipt.json'):
        require(files.identity(evidence/name)==receipt_identities[name],'source-recovery-original-public-receipt-changed')
    destination.mkdir(mode=0o700)
    archive=destination/sealed['archive']['file']
    inventory=isolated.write_source_archive(archive,selected)
    require(inventory==sealed['archiveFiles'] and files.identity(archive)==engine.identity(sealed['archive']),
            'recovered-source-archive-not-byte-identical-to-original')
    for name in ('qualification.json','sealed-source-receipt.json'):
        engine.copy_verified(evidence/name,destination/name,receipt_identities[name],0o444)
    return files.identity(archive)


def recover(workspace,integration,evidence_root,destination):
    pin=load_pin()
    require(platform.system()=='Linux' and platform.machine()=='aarch64','native-arm64-source-retention-recovery-required')
    workspace=archives.directory(Path(os.path.abspath(workspace)))
    require(str(workspace)==pin['originalWorkspace'],'source-recovery-original-absolute-workspace-required')
    integration=archives.directory(Path(os.path.abspath(integration)))
    evidence_root=archives.directory(Path(os.path.abspath(evidence_root)));evidence=evidence_root/'evidence'
    destination=Path(os.path.abspath(destination));archives.directory(destination.parent,create=True)
    require(not os.path.lexists(destination),'existing-source-recovery-publication-preserved')
    require(files.identity(evidence_root/'original-evidence.zip')==engine.identity(pin['evidenceArtifact']),
            'source-recovery-original-evidence-zip-changed')
    qualification,sealed=verify_evidence(evidence,pin)
    provider,_=engine.modules.read_json(ROOT/'runtime/server/programs-provider.lock.json')
    sources.validate_current(provider,ROOT/'sources.lock.json')
    require(provider['serverBuildSourceLock']==sealed['sourceLock'],'source-recovery-selected-server-build-differs')
    prepared=workspace/pin['originalPrepared'];acquired=workspace/pin['originalInputs']
    protocol=workspace/pin['originalProtocol'];output=workspace/pin['originalOutput']
    require(all(p!=destination and p not in destination.parents and destination not in p.parents
                for p in (prepared,acquired,protocol,output,integration,evidence_root)),
            'source-recovery-publication-overlaps-input-or-configure-tree')
    original_lock=integration/'sources.lock.json'
    require(not os.path.lexists(output),'existing-source-recovery-configure-output-preserved')
    require(shutil.disk_usage(workspace).free>=pin['minimumFreeBytes'],'source-recovery-requires-16-GiB-free')
    require(isolated.verify_prepared(prepared,acquired,original_lock=original_lock)[1]==qualification['preparationReceipt'],
            'source-recovery-preparation-not-byte-identical')
    for name,row in sealed['archiveFiles'].items():
        if name.startswith('recipes/'):
            require(files.identity(integration/name[len('recipes/'):])==engine.identity(row),
                    'source-recovery-original-integration-recipe-changed:'+name)
    network=isolated.require_offline();output.mkdir(mode=0o700);(output/'diagnostics').mkdir();(output/'tmp').mkdir()
    current_environment=inputs.verify_environment(acquired,output/'diagnostics/recovery-environment.json',original_lock=original_lock)
    cmake=Path(shutil.which('cmake') or '/nonexistent').resolve(strict=True)
    require(dict(path=str(cmake),**files.identity(cmake))==qualification['cmakeExecutable'],
            'source-recovery-original-cmake-executable-required')
    compilers={n:str(Path(shutil.which(n) or '/nonexistent').resolve(strict=True)) for n in ('gcc','g++')}
    environment=isolated.build_environment(output)
    arguments=isolated.configure_arguments(cmake,prepared,output)+['-DCMAKE_C_COMPILER='+compilers['gcc'],
        '-DCMAKE_CXX_COMPILER='+compilers['g++']]
    configure=isolated.run_owned(arguments,output/'diagnostics/recovery-configure.log',environment,cwd=workspace,timeout=900)
    revision=isolated.run_owned(revision_metadata_arguments(cmake,prepared,output),
        output/'diagnostics/recovery-revision.log',environment,cwd=prepared/'source',timeout=30)
    generated={name:dict(expected=engine.identity(row),observed=files.identity(output/'build'/name[len('new-build/generated/'):]))
        for name,row in sealed['archiveFiles'].items() if name.startswith('new-build/generated/')}
    engine.put_metadata(output/'diagnostics/recovery-generated.json',generated)
    revision_header=output/'build/revision.h'
    require(revision_header.stat().st_size<=65536,'source-recovery-revision-header-byte-bound')
    engine.copy_verified(revision_header,output/'diagnostics/recovery-revision.h',files.identity(revision_header),0o444)
    engine.put_metadata(output/'rebuild-plan.json',rebuild_plan())
    selected=selected_files(sealed,integration=integration,acquired=acquired,prepared=prepared,
        protocol=protocol,evidence=evidence,output=output,plan=output/'rebuild-plan.json')
    archive_identity=publish_exact(selected,sealed,evidence,destination,{
        'qualification.json':pin['qualification'],'sealed-source-receipt.json':pin['sealedReceipt']})
    receipt=dict(formatVersion=1,scope='byte-identical-original-qualified-source-retention-recovery',
        originalWorkflowRun=pin['workflowRun'],originalIntegrationRevision=pin['integrationRevision'],
        originalEvidenceArtifact=pin['evidenceArtifact'],originalQualification=pin['qualification'],
        originalSealedSourceReceipt=pin['sealedReceipt'],archive=archive_identity,
        exactOriginalMemberIdentitiesMatched=len(selected),exactOriginalCompressedArchiveMatched=True,
        originalReceiptsPreserved=True,configureAndRevisionMetadataOnly=True,compilerFeatureProbesMayRun=True,
        fullServerCompilationPerformed=False,newNativeQualificationClaimed=False,
        currentRelevantEnvironment=current_environment,configure=configure,revisionMetadata=revision,network=network,
        androidRuntimeQualified=False,gameplayQualified=False)
    engine.put_metadata(destination/'retention-recovery-receipt.json',receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='operation',required=True)
    fetch=sub.add_parser('acquire');fetch.add_argument('--output',type=Path,required=True)
    make=sub.add_parser('recover')
    for name in ('workspace','integration','evidence','output'):make.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    result=acquire(args.output) if args.operation=='acquire' else recover(args.workspace,args.integration,args.evidence,args.output)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
