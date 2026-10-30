#!/usr/bin/env python3
"""Build only the two separately adapted extractors and test synthetic providers.

This neither rebuilds server programs nor converts proprietary client data.
All source and original receipts remain separate and source closure stays pending.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import urllib.request

if not __package__:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import prepare_ordered_extractors as adaptation,prepare_runtime as archives
from tools import prepare_server_isolated_build as inputs,qualify_server_isolated_build as isolated
from tools import package_server_engine as engine,server_provider_sources as binding
from tools import verify_server_build as files

ROOT=Path(__file__).resolve().parents[1]
TARGETS=('map_extractor','vmap4_extractor')
RECIPES=('runtime/extractor_order.py','runtime/server/extractor-order.lock.json',
 'runtime/server/extractor-order/EsteriaArchiveOrder.h','runtime/server/extractor-order/0001-explicit-ordered-providers.patch',
 'runtime/server/EXTRACTOR-ORDER.md','tools/prepare_ordered_extractors.py','tools/build_ordered_extractors.py',
 'tools/prepare_server_isolated_build.py','tools/prepare_server_isolated_sources.py','tools/qualify_server_isolated_build.py',
 'tools/owned_process_group.py','tools/verify_server_build.py','tools/server_provider_sources.py',
 'tests/test_extractor_order.py','tests/extractor_order_reference.cpp','tests/extractor_mpqfile_reference.cpp',
 '.github/workflows/server-extractor-order.yml')
require=files.require


def client_policy(output):
    pin=adaptation.load_pin();output=Path(os.path.abspath(output));archives.directory(output.parent,create=True)
    require(not os.path.lexists(output),'existing-client-order-policy-preserved');output.mkdir(mode=0o700)
    require(re.fullmatch('[0-9a-f]{40}',pin['clientRevision']),'exact-client-order-revision-required')
    rows={}
    for name,row in pin['clientSources'].items():
        engine.content.safe_path(name);require(0<row['bytes']<=1<<20,'client-order-source-bound')
        url='https://raw.githubusercontent.com/Russianranger/wowdecomp_esteria/'+pin['clientRevision']+'/'+name
        with urllib.request.urlopen(url,timeout=60) as response:raw=response.read(row['bytes']+1)
        require(dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())==engine.identity(row) and
                hashlib.sha1(('blob '+str(len(raw))+'\0').encode()+raw).hexdigest()==row['gitBlob'],
                'exact-client-order-source-download-differs')
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);target.chmod(0o444);rows[name]=row
    proof=dict(formatVersion=1,scope='exact-client-order-policy-source-readback',clientRevision=pin['clientRevision'],
        files=rows,fullClientRepositoryFetched=False,clientAssetsFetched=False)
    engine.put_metadata(output/'policy-source-receipt.json',proof);return proof


def verify_policy(directory,pin):
    require({p.relative_to(directory).as_posix() for p in files.installed_files(directory)}==
            set(pin['clientSources'])|{'policy-source-receipt.json'},'client-order-policy-source-file-set')
    for name,row in pin['clientSources'].items():
        require(files.identity(directory/name)==engine.identity(row),'client-order-policy-source-changed')
        with files.plain_file(directory/name) as stream:
            require(hashlib.sha1(('blob '+str(row['bytes'])+'\0').encode()+stream.read()).hexdigest()==row['gitBlob'],
                    'client-order-policy-source-blob-changed')
    receipt,_=engine.modules.read_json(directory/'policy-source-receipt.json')
    require(receipt==dict(formatVersion=1,scope='exact-client-order-policy-source-readback',clientRevision=pin['clientRevision'],
        files=pin['clientSources'],fullClientRepositoryFetched=False,clientAssetsFetched=False),'client-order-policy-receipt-changed')


def tree(root):
    return {p.relative_to(root).as_posix():files.identity(p) for p in files.installed_files(root)}


def compiler_launchers(path):
    with files.plain_file(path) as stream:raw=stream.read(files.MAX_METADATA+1)
    require(len(raw)<=files.MAX_METADATA,'ordered-cmake-cache-byte-bound')
    text=raw.decode('utf-8');result={}
    for name in ('CMAKE_C_COMPILER_LAUNCHER','CMAKE_CXX_COMPILER_LAUNCHER'):
        require(re.findall(r'^'+name+r':[^=]+=(.*)$',text,re.MULTILINE)==[''],
                'ordered-compiler-cache-launcher-enabled-or-absent')
        result[name]=''
    return result


def verify_overlay(original,adapted,before,pin,adaptation_identity):
    expected=dict(before)
    for name,row in pin['adaptedFiles'].items():expected['source/'+name]=row
    expected['source/'+pin['header']['installedPath']]=engine.identity(pin['header'])
    expected['extractor-adaptation.json']=adaptation_identity
    require(tree(adapted)==expected and tree(original)==before,'ordered-adaptation-changed-unapproved-source-inputs')


def build(prepared,acquired,original_lock,environment,policy_sources,output,*,integration_revision):
    require(platform.system()=='Linux' and platform.machine()=='aarch64','native-arm64-ordered-target-build-required')
    require(re.fullmatch('[0-9a-f]{40}',integration_revision or ''),'ordered-build-integration-revision-required')
    prepared,acquired,policy_sources=[archives.directory(Path(os.path.abspath(p))) for p in (prepared,acquired,policy_sources)]
    original_lock=Path(os.path.abspath(original_lock));environment=Path(os.path.abspath(environment))
    output=Path(os.path.abspath(output));archives.directory(output.parent,create=True)
    require(not os.path.lexists(output) and all(p!=output and p not in output.parents and output not in p.parents
            for p in (prepared,acquired,policy_sources)),'ordered-build-output-exists-or-overlaps-input')
    pin=adaptation.load_pin();network=isolated.require_offline()
    output.mkdir(mode=0o700);(output/'diagnostics').mkdir();(output/'tmp').mkdir()
    proof=dict(formatVersion=1,scope='native-arm64-separate-ordered-extractor-target-build-and-synthetic-lookups',
        phase='verify-inputs',integrationRevision=integration_revision,targets=list(TARGETS),network=network,
        adaptationLock=files.identity(adaptation.LOCK),globalServerPatchListChanged=False,
        actualTargetCompileSucceeded=False,nativeOrderedLookupQualified=False,
        proprietaryClientDataSupplied=False,clientMpqConversionQualified=False,
        customEsteriaDataLoadOrderQualified=False,sourceCompanionComplete=False,
        isolatedFullServerRebuildQualified=False,serverProgramsReplaced=False,
        androidRuntimeQualified=False,gameplayQualified=False)
    isolated.write_json(output/'qualification.json',proof)
    try:
        current=binding.validate_current(json.loads((ROOT/'runtime/server/programs-provider.lock.json').read_text()),ROOT/'sources.lock.json')
        require(current['sources']['client']['commit']==pin['clientRevision'] and
                binding.same(current['sources']['server'],pin['baseServerSource']),'ordered-current-client-or-server-selection-differs')
        prep,prep_identity,_=isolated.verify_prepared(prepared,acquired,original_lock=original_lock)
        require(prep['sourceLock']==pin['serverBuildSourceLock']==files.identity(original_lock),'ordered-original-build-source-differs')
        supplied,supplied_identity=engine.modules.read_json(environment)
        require(supplied.get('relevantBuildEnvironmentMatched') is True,'ordered-relevant-input-environment-required')
        proof.update(originalPreparationReceipt=prep_identity,originalBuild=prep['originalBuild'],
            originalModules=prep['originalCompiledModules'],serverBuildSourceLock=prep['sourceLock'],
            sourceInputArchive=prep['sourceInputArchive'],sourceInputReceipt=prep['sourceInputReceipt'],
            clientRevision=pin['clientRevision'],clientPolicySources=pin['clientSources'],inputEnvironment=supplied_identity)
        verify_policy(policy_sources,pin)
        proof['environmentBefore']=inputs.verify_environment(acquired,output/'diagnostics/environment-before.json',original_lock=original_lock)
        require(proof['environmentBefore']['relevantBuildEnvironmentMatched'] is True,'ordered-relevant-build-environment-differs')
        before=tree(prepared);adapted=output/'prepared';adaptation.prepare(prepared,adapted)
        adaptation_identity=files.identity(adapted/'extractor-adaptation.json')
        verify_overlay(prepared,adapted,before,pin,adaptation_identity)
        cmake=shutil.which('cmake');require(cmake is not None,'ordered-CMake-missing');cmake=Path(cmake).resolve(strict=True)
        compilers={name:shutil.which(name) for name in ('gcc','g++')};require(all(compilers.values()),'ordered-compiler-missing')
        compilers={name:Path(path).resolve(strict=True) for name,path in compilers.items()}
        proof['compilerExecutables']={n:dict(path=str(p),**files.identity(p)) for n,p in compilers.items()}
        commands=[];env=isolated.build_environment(output)
        def run(argv,name,timeout,selected_env=None):
            commands.append(dict(phase=name,argv=[str(a) for a in argv],environment=selected_env or env))
            isolated.write_json(output/'diagnostics/commands.json',commands)
            return isolated.run_owned(argv,output/('diagnostics/'+name+'.log'),selected_env or env,cwd=ROOT,timeout=timeout)
        proof['phase']='configure';isolated.write_json(output/'qualification.json',proof)
        proof['configure']=run(isolated.configure_arguments(cmake,adapted,output)+[
            '-DCMAKE_C_COMPILER='+str(compilers['gcc']),'-DCMAKE_CXX_COMPILER='+str(compilers['g++']),
            '-DCMAKE_RUNTIME_OUTPUT_DIRECTORY='+str(output/'build/bin')],'configure',900)
        proof['cmakeOptions']=files.cmake_options(output/'build/CMakeCache.txt')
        proof['compilerLaunchers']=compiler_launchers(output/'build/CMakeCache.txt')
        with files.plain_file(output/'build/compile_commands.json') as stream:raw_commands=stream.read((128<<20)+1)
        require(len(raw_commands)<=128<<20,'ordered-compile-commands-byte-bound');command_rows=json.loads(raw_commands)
        declared={str(Path(row['file']).absolute()) for row in command_rows}
        require({str(adapted/'source'/n) for n in pin['adaptedFiles']}<=declared,'ordered-four-adapted-sources-not-in-build-commands')
        proof['phase']='build-two-targets';isolated.write_json(output/'qualification.json',proof)
        proof['compile']=run([cmake,'--build',output/'build','--parallel','2','--target',*TARGETS],'target-build',3600)
        programs={}
        for name in TARGETS:
            executable=output/'build/bin'/name
            programs[name]=dict(files.identity(executable),elf=files.elf_header(executable,executable=True))
            engine.modules.verify_literals(executable,engine.identity(programs[name]),[pin['contract']])
            proof[name+'Capability']=run([executable,'--esteria-order-capabilities'],name+'-capability',30)
        require(all(not (output/'build/bin'/n).exists() for n in ('authserver','worldserver','dbimport','mmaps_generator','vmap4_assembler')),
                'ordered-build-produced-unrequested-server-or-tool-target')
        proof['programs']=programs
        proof['compileCommands']=files.identity(output/'build/compile_commands.json')
        testenv=dict(env,ESTERIA_EXTRACTOR_SOURCE=str(prepared/'source'),
            ESTERIA_ORDERED_EXTRACTOR_PROGRAMS=json.dumps([str(output/'build/bin'/n) for n in TARGETS]))
        proof['phase']='actual-two-program-synthetic-lookups';isolated.write_json(output/'qualification.json',proof)
        proof['syntheticLookupTests']=run([sys.executable,'-m','unittest','tests.test_extractor_order','-v'],'synthetic-lookups',600,testenv)
        verify_overlay(prepared,adapted,before,pin,adaptation_identity);isolated.verify_prepared(prepared,acquired,original_lock=original_lock)
        verify_policy(policy_sources,pin)
        proof['environmentAfter']=inputs.verify_environment(acquired,output/'diagnostics/environment-after.json',original_lock=original_lock)
        require(proof['environmentAfter']['relevantBuildEnvironmentMatched'] is True,'ordered-build-environment-changed')
        payload=output/'payload';payload.mkdir()
        selected={
            'original-inputs/server-engine-source-inputs.tar.gz':acquired/'source-inputs/server-engine-source-inputs.tar.gz',
            'original-inputs/source-inputs-receipt.json':acquired/'source-inputs/source-inputs-receipt.json',
            'original-inputs/sources.lock.json':original_lock,
            'provenance/original-preparation-receipt.json':prepared/'preparation-receipt.json',
            'provenance/extractor-adaptation.json':adapted/'extractor-adaptation.json',
            'build/compile_commands.json':output/'build/compile_commands.json','build/CMakeCache.txt':output/'build/CMakeCache.txt',
            'build/commands.json':output/'diagnostics/commands.json'}
        for n in TARGETS:selected['bin/'+n]=output/'build/bin'/n
        for name in RECIPES:selected['recipes/'+name]=ROOT/name
        for path in files.installed_files(policy_sources):selected['client-policy/'+path.relative_to(policy_sources).as_posix()]=path
        for path in files.installed_files(acquired/'environment'):selected['original-environment/'+path.name]=path
        for path in files.installed_files(acquired/'supplements'):selected['supplements/'+path.relative_to(acquired/'supplements').as_posix()]=path
        for name in ('environment-before.json','environment-after.json'):selected['build/'+name]=output/'diagnostics'/name
        inventory={}
        for name,path in selected.items():
            row=files.identity(path);engine.copy_verified(path,payload/name,row,0o555 if name.startswith('bin/') else 0o444);inventory[name]=row
        proof.update(phase='complete',actualTargetCompileSucceeded=True,nativeOrderedLookupQualified=True,
            onlyRequestedToolsBuilt=True,compilerCacheDisabled=True,originalInputsUnchanged=True,payloadFiles=inventory)
        isolated.write_json(payload/'ordered-build.json',proof);isolated.write_json(output/'qualification.json',proof);return proof
    except BaseException as error:
        proof.update(failurePhase=proof['phase'],failureClass=type(error).__name__,phase='failed')
        isolated.write_json(output/'qualification.json',proof);raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='operation',required=True)
    fetch=sub.add_parser('client-policy');fetch.add_argument('--output',type=Path,required=True)
    make=sub.add_parser('build')
    for name in ('prepared','inputs','original-lock','environment','client-policy','output'):make.add_argument('--'+name,type=Path,required=True)
    make.add_argument('--integration-revision',default=os.environ.get('GITHUB_SHA'))
    args=parser.parse_args()
    proof=client_policy(args.output) if args.operation=='client-policy' else build(args.prepared,args.inputs,args.original_lock,
        args.environment,args.client_policy,args.output,integration_revision=args.integration_revision)
    print(json.dumps(proof,indent=2))


if __name__=='__main__':main()
