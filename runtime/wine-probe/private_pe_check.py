#!/usr/bin/env python3
"""Run one source-built PE pair with original and explicit anonymous-image Wine modes.

Only bounded public fixture logs/receipts enter --output. Fresh Wine prefixes and
mutable images remain in a private temporary sibling and are never exported.
This native Linux reference does not qualify Android, ARM64 or game execution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import tempfile
import threading
import time

try:
    from owned_process_group import OwnedGroup
except ImportError:
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from tools.owned_process_group import OwnedGroup

MAX_LOG=2*1024*1024
PASS=b'ESTERIA_PE_IMAGE_CHECK_PASS relocation=1 protections=1 data=1 bss=1 dirty-text=1 shared-cross-process=1'
CHILD=b'ESTERIA_PE_CHILD_SHARED_PASS'
BRANCH=b'ESTERIA_PRIVATE_PE_COPY mapped'
SCOPE='native-linux-x64-wine-original-vs-private-image-copy'


def require(value,reason):
    if not value:raise ValueError(reason)


def identity(path):
    info=path.lstat();require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and 0<info.st_size<=16*1024**2,'fixture-file-bound')
    with path.open('rb') as stream:return dict(bytes=info.st_size,sha256=hashlib.file_digest(stream,'sha256').hexdigest())


def pe_image(path,shared):
    pin=identity(path)
    with path.open('rb') as stream:
        dos=stream.read(64);require(dos[:2]==b'MZ','fixture-dos-signature')
        offset=struct.unpack_from('<I',dos,60)[0];require(64<=offset<=4096,'fixture-pe-offset')
        stream.seek(offset);header=stream.read(24);require(header[:4]==b'PE\0\0','fixture-pe-signature')
        machine,count=struct.unpack_from('<HH',header,4);optional_size=struct.unpack_from('<H',header,20)[0]
        require(machine==0x8664 and 1<=count<=64 and 112<=optional_size<=4096,'fixture-x64-header')
        optional=stream.read(optional_size);require(struct.unpack_from('<H',optional)[0]==0x20b,'fixture-pe32plus')
        sections=[]
        for _ in range(count):
            row=stream.read(40);require(len(row)==40,'fixture-section-table-truncated')
            name=row[:8].split(b'\0',1)[0].decode('ascii');flags=struct.unpack_from('<I',row,36)[0]
            sections.append(dict(name=name,flags=flags,rawBytes=struct.unpack_from('<I',row,16)[0]))
        if shared:
            require(struct.unpack_from('<Q',optional,24)[0]==0x180000000,'fixture-preferred-base-differs')
            found=[x for x in sections if x['name']=='.shared']
            require(len(found)==1 and found[0]['flags']&0xd0000000==0xd0000000 and found[0]['rawBytes']>0,
                'fixture-real-writable-shared-section-required')
    return dict(**pin,machine='x86_64',sections=sections)


class Capture:
    def __init__(self,argv,environment,cwd,log):
        self.process=subprocess.Popen(argv,cwd=cwd,env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,start_new_session=True)
        self.owner=OwnedGroup(self.process);self.count=0;self.kept=bytearray();self.failure=[]
        self.log=log;self.timed_out=False;self.exit_code=None;self.forced=False
        self.reader=threading.Thread(target=self.drain,daemon=True);self.reader.start()
    def drain(self):
        try:
            while True:
                chunk=self.process.stdout.read(65536)
                if not chunk:break
                self.count+=len(chunk)
                if len(self.kept)<MAX_LOG:self.kept.extend(chunk[:MAX_LOG-len(self.kept)])
        except BaseException as error:self.failure.append(type(error).__name__)
    def wait(self,timeout):
        try:
            try:self.exit_code=self.owner.wait(timeout)
            except subprocess.TimeoutExpired:self.timed_out=True
        finally:self.exit_code,self.forced=self.owner.stop(graceful_timeout=1,reap_timeout=5)
        require(not self.timed_out and not self.forced,'fixture-process-timeout-or-forced-stop')
        return self
    def finish(self,timeout):
        self.reader.join(max(0,timeout))
        if self.reader.is_alive():self.failure.append('LogReaderStillAlive')
        else:self.process.stdout.close()
        with self.log.open('xb') as stream:stream.write(bytes(self.kept))
        require(not self.reader.is_alive() and not self.failure and self.count<=MAX_LOG,'bounded-fixture-log-failure')
        return dict(exitCode=self.exit_code,logBytes=self.count,logSha256=hashlib.sha256(self.kept).hexdigest())


def run(argv,environment,cwd,log,timeout,captures):
    capture=Capture(argv,environment,cwd,log);captures.append(capture)
    return capture.wait(timeout)


def run_mode(mode,wine,wineserver,exe,dll,private,output):
    root=private/mode;root.mkdir(mode=0o700);home=root/'home';home.mkdir(mode=0o700)
    images=root/'images';images.mkdir(mode=0o700)
    for source,name in ((exe,'private-pe-check.exe'),(dll,'private-pe-fixture.dll')):
        shutil.copyfile(source,images/name);require(identity(images/name)==identity(source),'fixture-copy-identity')
    env={'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8',
         'HOME':str(home),'WINEPREFIX':str(root/'prefix'),'WINEARCH':'win64','WINEDEBUG':'-all,err+all',
         'WINEESYNC':'0','WINEFSYNC':'0','WINEDLLOVERRIDES':'winemenubuilder.exe=d'}
    if mode=='private-copy':env['WINE_ANDROID_PRIVATE_PE_COPY']='1'
    receipt=dict(mode=mode,privateCopyRequested=mode=='private-copy',qualified=False)
    started=False;problem=None;cleanup=[];captures=[];boot=program=None
    try:
        started=True
        boot=run([str(wine),'wineboot','-u'],env,root,output/(mode+'-boot.log'),120,captures)
        require(boot.exit_code==0,'wine-prefix-initialization-failed')
        program=run([str(wine),str(images/'private-pe-check.exe')],env,images,output/(mode+'-fixture.log'),100,captures)
        require(program.exit_code==0,'real-pe-image-fixture-exited-nonzero')
    except BaseException as error:problem=error;receipt['failureType']=type(error).__name__
    finally:
        if started:
            for name,arg in (('stop','-k'),('wait','-w')):
                try:
                    result=run([str(wineserver),arg],env,root,output/(mode+'-'+name+'.log'),30,captures)
                    require(result.exit_code==0,'wine-prefix-shutdown-failed')
                except BaseException as error:cleanup.append(name+':'+type(error).__name__)
        deadline=time.monotonic()+10;receipt['captures']={}
        for capture in captures:
            try:receipt['captures'][capture.log.name]=capture.finish(deadline-time.monotonic())
            except BaseException as error:cleanup.append('log-drain:'+type(error).__name__)
        if problem is None and not cleanup:
            try:
                require(program is not None and boot is not None,'missing-program-capture')
                log=bytes(program.kept)
                require(log.splitlines().count(PASS)==1 and log.splitlines().count(CHILD)==1,
                    'real-pe-image-fixture-did-not-pass')
                branch_count=log.splitlines().count(BRANCH)
                require(branch_count>=2 if mode=='private-copy' else branch_count==0,
                    'actual-private-copy-branch-selection-differs')
                receipt.update(privateCopyBranchMarkers=branch_count,forcedRelocation=True,
                    sectionProtectionsVerified=True,initializedDataVerified=True,zeroFillVerified=True,
                    dirtyTextExecutableAgain=True,privateDataIsolated=True,sharedWritableCrossProcess=True)
            except BaseException as error:problem=error;receipt['failureType']=type(error).__name__
        try:
            for source,name in ((exe,'private-pe-check.exe'),(dll,'private-pe-fixture.dll')):
                require(identity(images/name)==identity(source),'fixture-backing-image-was-modified')
            receipt['backingImagesUnchanged']=True
        except BaseException as error:cleanup.append('image-readback:'+type(error).__name__)
        receipt['cleanupFailures']=cleanup
        receipt['qualified']=problem is None and not cleanup
        (output/(mode+'-receipt.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    require(receipt['qualified'],'private-pe-mode-failed:'+mode)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('wine','wineserver','exe','dll','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();output=args.output.absolute();require(not os.path.lexists(output),'existing-pe-evidence-refused')
    output.mkdir(mode=0o700,parents=True)
    result=dict(formatVersion=1,scope=SCOPE,qualified=False,androidQualified=False,arm64Qualified=False,
        gameClientQualified=False,modes=[])
    try:
        result['images']=dict(exe=pe_image(args.exe,False),dll=pe_image(args.dll,True))
        result['wineExecutable']=identity(args.wine.resolve(strict=True));result['wineServer']=identity(args.wineserver.resolve(strict=True))
        with tempfile.TemporaryDirectory(prefix='esteria-private-pe-') as scratch:
            private=Path(scratch);private.chmod(0o700)
            for mode in ('original','private-copy'):
                result['modes'].append(run_mode(mode,args.wine.resolve(strict=True),args.wineserver.resolve(strict=True),
                    args.exe.resolve(strict=True),args.dll.resolve(strict=True),private,output))
        result['privatePrefixesRemoved']=True;result['qualified']=True
        print('Original and explicit private-copy Wine PE fixture passed; native Linux x64 only.');return 0
    except BaseException as error:
        result['failureType']=type(error).__name__
        print('Wine private PE fixture failed; retain bounded mode logs and receipt.');return 1
    finally:(output/'qualification.json').write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':raise SystemExit(main())
