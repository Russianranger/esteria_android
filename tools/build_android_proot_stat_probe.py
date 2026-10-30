#!/usr/bin/env python3
"""Build a new AndroidTest-only glibc stat fixture beside the unchanged probe.

No guest runs, production provider changes, or cache activation occur here.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import zipfile

try:
    from . import verify_android_proot_probe as old
    from . import prepare_runtime as files
except ImportError:
    import verify_android_proot_probe as old
    import prepare_runtime as files

ROOT=Path(__file__).resolve().parents[1]
SCOPE='android-x86_64-glibc-stat-fixture-build-only'
ASSET='proot-stat-probe'
SOURCES=('native/proot-stat-probe/stat_probe.c','native/proot-stat-probe/README.md',
    'tools/build_android_proot_stat_probe.py','tools/qualify_android_proot_stat.py',
    'app/src/androidTest/java/io/github/russianranger/esteria/runtime/ProotStatMetadataTest.java',
    'app/src/androidTest/assets/proot-stat-probe/.gitignore',
    'tests/test_android_proot_stat.py','.github/workflows/android-proot-stat.yml','LICENSE')
ASSETS={'probe-stat','build-evidence.json','ESTERIA-GPL-3.0.txt'}
# Measured with the pinned NDK28.2 compiler and the original Debian2.36 sysroot.
# CI must reproduce these bytes; a caller-authored source flag cannot substitute
# a different executable which merely prints the expected observations.
FIXTURE_PIN=dict(bytes=18536,sha256='a0e6aeec97fb7e218d98820c333b97d3c11f681ab79660ebc191dffc9fc762c2')
require=old.require

def identity(path):
    with files.plain_file(path) as incoming:
        size=os.fstat(incoming.fileno()).st_size
        return dict(bytes=size,sha256=files.hash_stream(incoming,size))

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()

def source_inputs():return {name:identity(ROOT/name) for name in SOURCES}

def exact_source(revision,inputs):
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()!=revision:return False
    if subprocess.run(['git','diff','--quiet','HEAD'],cwd=ROOT).returncode:return False
    for name,row in inputs.items():
        child=subprocess.run(['git','show',revision+':'+name],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        if child.returncode or dict(bytes=len(child.stdout),sha256=hashlib.sha256(child.stdout).hexdigest())!=row:return False
    return True

def build(work,proot_work,ndk,revision,test_assets=None):
    require(re.fullmatch('[0-9a-f]{40}',revision) is not None,'exact-stat-fixture-revision-required')
    work=Path(os.path.abspath(work));files.directory(work.parent,create=True)
    require(not os.path.lexists(work) and work!=ROOT and ROOT not in work.parents,'new-external-stat-fixture-work-required')
    proot_work=files.directory(proot_work);ndk=files.directory(ndk)
    old.verify(proot_work/'provider')
    previous=json.loads((proot_work/'provider/assets/proot-probe/build-evidence.json').read_bytes())
    require(re.search(r'^Pkg.Revision\s*=\s*28\.2\.13676358\s*$',(ndk/'source.properties').read_text(),re.M),'stat-fixture-pinned-ndk-required')
    compiler=ndk/'toolchains/llvm/prebuilt/linux-x86_64/bin/clang'
    require(identity(compiler.resolve(strict=True))['sha256']==previous['compilerSha256'],'stat-fixture-compiler-differs-from-probe')
    sysroot=files.directory(proot_work/'glibc-sysroot');startup=sysroot/'usr/lib/x86_64-linux-gnu'
    require(identity(sysroot/'lib/x86_64-linux-gnu/libc.so.6')==previous['rootfsFiles']['lib/x86_64-linux-gnu/libc.so.6'],
            'stat-fixture-glibc-differs-from-probe')
    inputs=source_inputs();work.mkdir(mode=0o700)
    provider=work/'provider';assets=provider/'assets'/ASSET;assets.mkdir(parents=True,mode=0o700)
    executable=assets/'probe-stat'
    command=[str(compiler),'--target=x86_64-linux-gnu','--sysroot='+str(sysroot),
        '-isystem',str(sysroot/'usr/include/x86_64-linux-gnu'),'-O2','-Wall','-Wextra','-Werror',
        '-fno-stack-protector','-fuse-ld=lld','-nostdlib','-fPIE','-pie',
        '-Wl,-z,noexecstack,-z,max-page-size=16384','-Wl,--dynamic-linker=/lib64/ld-linux-x86-64.so.2',
        '-L'+str(sysroot/'usr/lib/x86_64-linux-gnu'),'-L'+str(sysroot/'lib/x86_64-linux-gnu'),
        str(startup/'Scrt1.o'),str(startup/'crti.o'),str(ROOT/'native/proot-stat-probe/stat_probe.c'),'-lc',
        str(startup/'crtn.o'),'-o',str(executable)]
    environment=dict(os.environ)
    for name in ('CC','CXX','CFLAGS','CPPFLAGS','LDFLAGS','LD_PRELOAD','LD_LIBRARY_PATH'):environment.pop(name,None)
    with (work/'build.log').open('xb') as log:
        subprocess.run(command,env=environment,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
    old.elf(executable.read_bytes(),'guest')
    require(identity(executable)==FIXTURE_PIN,'stat-fixture-binary-differs-from-measured-recipe')
    shutil.copyfile(ROOT/'LICENSE',assets/'ESTERIA-GPL-3.0.txt')
    companion=work/'corresponding-source.tar.gz'
    with tarfile.open(companion,'w:gz') as archive:
        for name in SOURCES:archive.add(ROOT/name,arcname='esteria/'+name,recursive=False)
        archive.add(proot_work/'corresponding-source.tar.gz',arcname='original-proot-corresponding-source.tar.gz',recursive=False)
        archive.add(proot_work/'provider/assets/proot-probe/build-evidence.json',arcname='original-proot-build-evidence.json',recursive=False)
    proof=dict(formatVersion=1,scope=SCOPE,sourceRevision=revision,sourceSnapshotExact=exact_source(revision,inputs),
        fixture=identity(executable),sourceInputs=inputs,compilerSha256=previous['compilerSha256'],
        ndkVersion='28.2.13676358',glibcVersion='2.36',prootBuildEvidence=identity(proot_work/'provider/assets/proot-probe/build-evidence.json'),
        originalProotNativeFiles=previous['nativeFiles'],sourceCompanion=identity(companion),
        compileCommand=command,glibcStartupInputs={name:identity(startup/name) for name in ('Scrt1.o','crti.o','crtn.o')},
        androidExecuted=False,prootGuestExecuted=False,arm64Qualified=False,productionCacheEnabled=False,
        unchangedMetadataCorruptionDetectionClaimed=False,gameplayQualified=False)
    (assets/'build-evidence.json').write_bytes(encoded(proof));(work/'build-evidence.json').write_bytes(encoded(proof))
    verify(provider)
    if test_assets is not None:
        destination=Path(os.path.abspath(test_assets));destination.mkdir(parents=True,exist_ok=True)
        require({p.name for p in destination.iterdir()}<={'.gitignore'},'existing-test-stat-assets-preserved')
        for name in ASSETS:shutil.copyfile(assets/name,destination/name)
    return proof

def verify(provider,test_apk=None):
    provider=files.directory(provider);assets=files.directory(provider/'assets'/ASSET)
    require({path.relative_to(provider).as_posix() for path in provider.rglob('*') if path.is_file()}==
        {'assets/'+ASSET+'/'+name for name in ASSETS},'stat-fixture-provider-inventory')
    for path in provider.rglob('*'):require(not path.is_symlink() and (path.is_file() or path.is_dir()),'stat-fixture-provider-path')
    require((assets/'build-evidence.json').stat().st_size<=128<<10,'stat-fixture-build-metadata-bound')
    proof=json.loads((assets/'build-evidence.json').read_bytes())
    require(proof.get('formatVersion')==1 and proof.get('scope')==SCOPE and proof.get('sourceInputs')==source_inputs() and
        proof.get('originalProotNativeFiles')==old.builder.NATIVE_PINS and proof.get('ndkVersion')=='28.2.13676358' and
        proof.get('glibcVersion')=='2.36' and re.fullmatch('[0-9a-f]{40}',proof.get('sourceRevision','')),
        'stat-fixture-build-source-selection')
    require(all(proof.get(key) is False for key in ('androidExecuted','prootGuestExecuted','arm64Qualified',
        'productionCacheEnabled','unchangedMetadataCorruptionDetectionClaimed','gameplayQualified')),'stat-fixture-build-overclaims')
    require(identity(assets/'probe-stat')==proof['fixture']==FIXTURE_PIN and identity(assets/'ESTERIA-GPL-3.0.txt')==identity(ROOT/'LICENSE'),
        'stat-fixture-build-bytes')
    old.elf((assets/'probe-stat').read_bytes(),'guest')
    if test_apk is not None:
        with zipfile.ZipFile(test_apk) as archive:
            names=archive.namelist();require(len(names)==len(set(names)),'stat-fixture-test-apk-duplicates')
            actual={name for name in names if name.startswith('assets/'+ASSET+'/') and not name.endswith('/')}
            expected={'assets/'+ASSET+'/'+name for name in ASSETS}
            optional='assets/'+ASSET+'/.gitignore'
            require(actual in (expected,expected|{optional}),'stat-fixture-test-apk-assets')
            for name in ASSETS:
                info=archive.getinfo('assets/'+ASSET+'/'+name)
                require(info.file_size==(assets/name).stat().st_size and archive.read(info)==(assets/name).read_bytes(),
                    'stat-fixture-test-apk-byte-differs')
            if optional in actual:require(archive.read(optional)==(ROOT/'app/src/androidTest/assets/proot-stat-probe/.gitignore').read_bytes(),
                'stat-fixture-test-apk-ignore-file')
    return proof

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='operation',required=True)
    create=sub.add_parser('build')
    for name in ('work','proot-work','ndk'):create.add_argument('--'+name,type=Path,required=True)
    create.add_argument('--source-revision',required=True);create.add_argument('--test-assets',type=Path)
    check=sub.add_parser('verify');check.add_argument('--provider',type=Path,required=True);check.add_argument('--test-apk',type=Path)
    args=parser.parse_args()
    result=build(args.work,args.proot_work,args.ndk,args.source_revision,args.test_assets) if args.operation=='build' else verify(args.provider,args.test_apk)
    print(json.dumps({key:result[key] for key in ('scope','sourceRevision','sourceSnapshotExact','fixture','productionCacheEnabled')},indent=2))

if __name__=='__main__':main()
