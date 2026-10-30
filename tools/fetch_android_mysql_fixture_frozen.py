#!/usr/bin/env python3
"""Use the exact qualified MySQL consumer recipe after current app code changes.

Metadata selection executes no historical code. Acquisition separately requires
the entire clean, blob-verified frozen checkout before invoking its fixed script.
Current Java changes never become historical Android or SQL qualification.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

if not __package__:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import prepare_runtime as archives, verify_server_build as files

ROOT=Path(__file__).resolve().parents[1]
RECIPE='817cbc229f4dcc24beb169ecc72838fab4d1df32'
LOCK_PATH='runtime/mysql-probe/qualified-inputs.lock.json'
LOCK_ID=dict(bytes=6228,sha256='5268fa26eb1e2165f0cf5ff9f90686792abb4af6b9af48288d75932009bf853d')
READBACK='runtime/evidence/android-mysql-input-readback-41119182469.json'
SCRIPT='tools/fetch_android_mysql_fixture.py'
MAX_RECIPE=16<<20
FALSE_FLAGS=('productionAdapterQualified','arm64Qualified','serverSchemasQualified','gameplayQualified')
require=files.require


def identity(raw):return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def small(path,maximum=2<<20):
    with files.plain_file(path) as stream:
        count=os.fstat(stream.fileno()).st_size
        require(0<count<=maximum,'mysql-frozen-consumer-metadata-bound')
        raw=stream.read(count+1);require(len(raw)==count,'mysql-frozen-consumer-metadata-changed')
    return raw


def artifact_identity(value):
    require(type(value) is dict and type(value.get('bytes')) is int and 0<value['bytes']<=2<<30 and
        re.fullmatch('[0-9a-f]{64}',value.get('sha256','')),'mysql-frozen-consumer-invalid-artifact-identity')
    return {name:value[name] for name in ('bytes','sha256')}


def input_selection():
    """Return the original pin from positive metadata; no checkout/old code runs."""
    raw=small(ROOT/LOCK_PATH,128<<10)
    require(identity(raw)==LOCK_ID,'mysql-frozen-consumer-original-selection-changed')
    pin=json.loads(raw)
    require(type(pin.get('formatVersion')) is int and pin['formatVersion']==1 and
        pin.get('scope')=='qualified-android-x64-mysql-fixture-offline-input-selection' and
        pin.get('repository')=='Russianranger/esteria_android' and pin.get('consumerFullArchiveReadbackPerformed') is False and
        all(pin.get(name) is False for name in FALSE_FLAGS),'mysql-frozen-consumer-original-selection-scope')
    positive=pin['actualAndroidEvidence']
    require(positive.get('path')=='runtime/evidence/android-mysql-service-4fd32df-readback.json',
        'mysql-frozen-consumer-original-positive-path')
    raw=small(ROOT/positive['path'],256<<10)
    require(identity(raw)==artifact_identity(positive),'mysql-frozen-consumer-original-positive-changed')
    android=json.loads(raw);producer=pin['producer']
    require(android.get('scope')=='independent-android-13-x64-mysql-and-java-service-4fd32df-readback' and
        android.get('workflow',{}).get('id')==producer['workflowRun'] and
        android['workflow'].get('headSha')==producer['integrationRevision'] and
        android['workflow'].get('status')=='completed' and android['workflow'].get('conclusion')=='success' and
        android.get('allTwentyOneProviderInputsMatchExactProducerGitRevision') is True and
        android.get('providerInputs')==pin['providerSourceInputs'] and
        android.get('actualQualification',{}).get('androidMysqlBootstrapQualified') is True and
        android['actualQualification'].get('androidJavaDatabaseServiceLifecycleQualified') is True,
        'mysql-frozen-consumer-positive-original-android-required')
    retained=android.get('retainedInputReceipt',{})
    require(retained.get('identity')==pin['retentionReceipt'] and retained.get('receiptCrcVerified') is True and
        retained.get('value',{}).get('files')==pin['files'],'mysql-frozen-consumer-original-retention-binding')
    wrapper=json.loads(small(ROOT/READBACK))
    consumer=wrapper.get('consumer',{})
    require(wrapper.get('scope')=='actual-ci-retained-android-x64-mysql-input-source-consumer-and-small-local-readback' and
        consumer.get('workflowRun')==41119182469 and consumer.get('integrationRevision')==RECIPE and
        consumer.get('status')=='completed' and consumer.get('conclusion')=='success' and
        wrapper.get('allFourConsumerSourceInputsMatchExactGitBlobs') is True and
        wrapper.get('allRetainedSmallArtifactMembersReadAndCrcVerified') is True and
        wrapper.get('originalLargeSourceReadbackPerformedOnCi') is True and
        all(wrapper.get(name) is False for name in ('androidExecutedByConsumer','aptOrCompilerExecutedByConsumer',
            'localOriginalInputAndSourceArchivesDownloaded','productionArm64Qualified','serverSchemasQualified','gameplayQualified')),
        'mysql-frozen-consumer-positive-frozen-recipe-required')
    require(wrapper.get('sourceInputs',{}).get(LOCK_PATH)==LOCK_ID,'mysql-frozen-consumer-observed-selection-binding')
    _acquisition(wrapper.get('actualCiEvidence'),pin,summary=True)
    return pin


def _git_environment():
    return dict(os.environ,GIT_OPTIONAL_LOCKS='0',GIT_NO_LAZY_FETCH='1',GIT_NO_REPLACE_OBJECTS='1',
        GIT_TERMINAL_PROMPT='0',GIT_CONFIG_NOSYSTEM='1')


def _verify_checkout(checkout,revision):
    """Private structural verifier; public entry points fix the recipe revision."""
    checkout=archives.directory(Path(os.path.abspath(checkout)))
    require(re.fullmatch('[0-9a-f]{40}',revision or ''),'mysql-frozen-consumer-full-revision-required')
    git=['git','-c','safe.directory='+str(checkout),'-c','core.fsmonitor=false','-c','core.hooksPath=/dev/null',
        '-C',str(checkout)]
    environment=_git_environment()
    def query(*arguments,maximum=2<<20):
        # Git metadata is UTF-8; source blob bytes use the separate batch reader.
        command=git+list(arguments)
        child=subprocess.Popen(command,env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL)
        try:
            raw,_=child.communicate(timeout=30)
            require(child.returncode==0 and len(raw)<=maximum,'mysql-frozen-consumer-git-query-failed')
            return raw
        finally:
            if child.poll() is None:child.kill();child.wait(timeout=5)
    require(query('rev-parse','HEAD').decode().strip()==revision,'mysql-frozen-consumer-checkout-revision')
    flags=query('ls-files','-v','-z')
    require(all(not row or row.startswith(b'H ') for row in flags.split(b'\0')),
        'mysql-frozen-consumer-hidden-index-flags')
    query('diff-index','--quiet','--no-ext-diff','--no-textconv','--cached','HEAD','--')
    # Verify working files below against every canonical blob. diff-files can
    # report a stale index stat after the declared BAT EOL conversion, and Git
    # clean filters can conceal other conversions that this byte check refuses.
    # Include ignored files: an ignored Python module must not shadow verified code.
    require(query('ls-files','--others','-z')==b'','mysql-frozen-consumer-untracked-files')
    roster=query('ls-tree','-rlz',revision);entries=[];total=0
    for entry in roster.split(b'\0'):
        if not entry:continue
        metadata,name=entry.split(b'\t',1);mode,kind,blob,count=metadata.split();name=name.decode('utf-8')
        require(mode in (b'100644',b'100755') and kind==b'blob' and re.fullmatch(b'[0-9a-f]{40}',blob) and
            name and not name.startswith('/') and '\\' not in name and
            all(part not in ('','.','..') for part in name.split('/')),'mysql-frozen-consumer-git-member')
        count=int(count);total+=count
        require(0<=count<=MAX_RECIPE and total<=MAX_RECIPE and len(entries)<4096,
            'mysql-frozen-consumer-recipe-bound')
        entries.append((name,mode,blob,count))
    require(entries,'mysql-frozen-consumer-empty-recipe')
    result=subprocess.run(git+['cat-file','--batch'],input=b''.join(row[2]+b'\n' for row in entries),
        env=environment,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=60)
    require(result.returncode==0 and len(result.stdout)<=total+len(entries)*128,'mysql-frozen-consumer-git-blob-batch')
    position=0;blobs={}
    for name,mode,blob,count in entries:
        end=result.stdout.find(b'\n',position)
        require(end>=position and result.stdout[position:end]==blob+b' blob '+str(count).encode(),
            'mysql-frozen-consumer-git-blob-header')
        start=end+1;raw=result.stdout[start:start+count];position=start+count+1
        require(len(raw)==count and result.stdout[position-1:position]==b'\n' and
            hashlib.sha1(b'blob '+str(count).encode()+b'\0'+raw).hexdigest().encode()==blob,
            'mysql-frozen-consumer-git-blob-bytes')
        blobs[name]=(mode,raw)
    require(position==len(result.stdout),'mysql-frozen-consumer-git-blob-trailing-bytes')
    attrs=blobs.get('.gitattributes',(b'',b''))[1];rows={};conversions=[]
    for name,(mode,raw) in blobs.items():
        path=checkout/name
        with files.plain_file(path) as stream:
            before=os.fstat(stream.fileno());actual=stream.read(len(raw)*2+1);after=os.fstat(stream.fileno())
        stamp=lambda value:(value.st_dev,value.st_ino,value.st_mode,value.st_size,value.st_nlink,value.st_mtime_ns,value.st_ctime_ns)
        require(stamp(before)==stamp(after)==stamp(path.lstat()) and before.st_nlink==1 and
            bool(before.st_mode&0o111)==(mode==b'100755'),'mysql-frozen-consumer-working-file-mode-or-identity')
        if actual!=raw:
            require(name=='gradlew.bat' and len(raw)<=64<<10 and b'\r' not in raw and
                b'*.bat text eol=crlf' in attrs.splitlines() and actual==raw.replace(b'\n',b'\r\n'),
                'mysql-frozen-consumer-working-file-bytes')
            conversions.append(dict(path=name,conversion='declared-lf-to-crlf',canonical=identity(raw),checkout=identity(actual)))
        rows[name]=dict(identity(raw),mode=int(mode,8),gitBlob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest())
    return dict(formatVersion=1,scope='entire-frozen-git-checkout-blob-and-working-file-verification',
        recipeRevision=revision,files=rows,fileCount=len(rows),canonicalGitFileBytes=total,
        validatedCheckoutConversions=conversions,allTrackedGitAndCheckoutBytesVerified=True,
        hiddenIndexFlagsPresent=False,untrackedFilesPresent=False,dirtyFilesPresent=False)


def inspect(checkout):
    """Verify metadata and every frozen file without importing/running old code."""
    pin=input_selection();proof=_verify_checkout(checkout,RECIPE);checkout=Path(os.path.abspath(checkout))
    require(proof['files'].get(LOCK_PATH,{}).get('sha256')==LOCK_ID['sha256'] and
        {key:proof['files'][LOCK_PATH][key] for key in ('bytes','sha256')}==LOCK_ID,
        'mysql-frozen-consumer-checkout-selection-differs')
    for name,row in pin['providerSourceInputs'].items():
        require(name in proof['files'] and {key:proof['files'][name][key] for key in ('bytes','sha256')}==row,
            'mysql-frozen-consumer-frozen-provider-recipe-differs')
    observed=json.loads(small(ROOT/READBACK))
    for name,row in observed['sourceInputs'].items():
        require(name in proof['files'] and {key:proof['files'][name][key] for key in ('bytes','sha256')}==row,
            'mysql-frozen-consumer-actual-consumer-recipe-differs')
    require(SCRIPT in proof['files'],'mysql-frozen-consumer-fixed-script-missing')
    return dict(formatVersion=1,scope='verified-frozen-android-x64-mysql-consumer-selection',
        frozenRecipe=proof,originalPin=pin,inputSelection=LOCK_ID,
        actualConsumerEvidence=dict(path=READBACK,**files.identity(ROOT/READBACK)),
        historicalRuntimeProducer=pin['producer'],historicalConsumerRecipeRevision=RECIPE,
        historicalJavaServiceEvidenceAppliesToCurrentCaller=False,**{name:False for name in FALSE_FLAGS})


def selection(checkout):return inspect(checkout)['originalPin']


def _acquisition(value,pin,*,summary=False):
    require(type(value) is dict and type(value.get('formatVersion')) is int and value['formatVersion']==1 and
        value.get('scope')=='full-original-android-x64-mysql-fixture-input-and-source-readback' and
        value.get('inputSelection')==LOCK_ID and value.get('producer')==pin['producer'] and value.get('artifacts')==pin['artifacts'] and
        all(value.get(name) is True for name in ('everyOriginalInputAndSourceZipByteReadBack','allNineRetainedInputsVerified',
            'allInstalledPackageSourceFilesReadBack','prootProviderVerified','originalApkVerified')) and
        value.get('guestExecuted') is False and value.get('sqlExecuted') is False and
        all(value.get(name) is False for name in FALSE_FLAGS),'mysql-frozen-consumer-actual-full-readback-required')
    sources=value.get('completeSourceReadbackSummary' if summary else 'completeSourceReadback',{})
    require(sources.get('installedSourceArchiveFiles')==pin['completeInstalledSources']['archiveFiles'] and
        sources.get('installedSourceArchiveBytes')==pin['completeInstalledSources']['archiveBytes'] and
        type(sources.get('sourcePackages')) is int and sources['sourcePackages']>0,
        'mysql-frozen-consumer-actual-source-inventory')
    if not summary:
        rows=sources.get('allOriginalSourceZipMembers')
        require(type(rows) is dict and 275<=len(rows)<=10000,'mysql-frozen-consumer-entire-source-zip-readback')
        for row in rows.values():artifact_identity(row)
    return value


def _environment():
    environment={name:value for name,value in os.environ.items() if not name.startswith('PYTHON')}
    environment['PYTHONDONTWRITEBYTECODE']='1'
    return environment


def acquire(checkout,output):
    proof=inspect(checkout);pin=proof['originalPin'];checkout=archives.directory(Path(os.path.abspath(checkout)))
    output=Path(os.path.abspath(output));archives.directory(output.parent,create=True)
    require(not os.path.lexists(output) and output!=checkout and output not in checkout.parents and
        checkout not in output.parents,'mysql-frozen-consumer-existing-or-overlapping-output')
    command=[sys.executable,'-B','-s','-E',str(checkout/SCRIPT),'--output',str(output)]
    with tempfile.TemporaryFile() as stdout,tempfile.TemporaryFile() as stderr:
        result=subprocess.run(command,cwd=checkout,env=_environment(),stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,timeout=3600)
        require(result.returncode==0 and 0<stdout.tell()<=2<<20 and stderr.tell()<=2<<20,
            'mysql-frozen-consumer-frozen-acquire-failed')
        stdout.seek(0);actual=json.load(stdout)
    _acquisition(actual,pin)
    require(json.loads(small(output/'acquisition.json'))==actual,'mysql-frozen-consumer-actual-receipt-differs')
    require(inspect(checkout)==proof,'mysql-frozen-consumer-source-changed-during-acquisition')
    caller={name:files.identity(ROOT/name) for name in ('tools/fetch_android_mysql_fixture_frozen.py',
        'tests/test_android_mysql_fixture_frozen.py','runtime/mysql-probe/FROZEN-CONSUMER.md')}
    result=dict(formatVersion=1,scope='current-caller-verified-frozen-x64-mysql-input-consumption',
        inputSelection=LOCK_ID,historicalRuntimeProducer=pin['producer'],historicalConsumerRecipeRevision=RECIPE,
        entireFrozenRecipe=proof['frozenRecipe'],currentCallerFiles=caller,
        actualOriginalAcquisitionReceipt=files.identity(output/'acquisition.json'),actualOriginalAcquisition=actual,
        entireOriginalInputsAndSourcesReadBackByFrozenRecipe=True,frozenCheckoutVerifiedBeforeAndAfter=True,
        historicalJavaServiceEvidenceAppliesToCurrentCaller=False,guestExecuted=False,sqlExecuted=False,
        **{name:False for name in FALSE_FLAGS})
    target=output/'frozen-consumer-readback.json'
    with target.open('xb') as stream:
        stream.write((json.dumps(result,sort_keys=True,indent=2)+'\n').encode());stream.flush();os.fsync(stream.fileno())
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen-consumer-source',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    value=acquire(args.frozen_consumer_source,args.output) if args.output else inspect(args.frozen_consumer_source)
    print(json.dumps(value,sort_keys=True,indent=2))


if __name__=='__main__':main()
