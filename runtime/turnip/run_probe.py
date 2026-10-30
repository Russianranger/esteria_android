#!/usr/bin/env python3
"""Bind a bounded component probe to exact build bytes and an exclusive ICD."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import selectors
import signal
import subprocess
import time


def require(ok, reason):
    if not ok: raise ValueError(reason)


def identity(path):
    require(path.is_file() and not path.is_symlink(), 'plain-file-required')
    with path.open('rb') as source: digest=hashlib.file_digest(source,'sha256').hexdigest()
    return dict(bytes=path.stat().st_size,sha256=digest)


def bounded_json(path, maximum):
    require(path.is_file() and not path.is_symlink(), 'plain-json-file-required')
    with path.open('rb') as source: raw=source.read(maximum+1)
    require(len(raw)<=maximum,'json-size-limit');return json.loads(raw)


def environment(output, manifest):
    # Do not inherit LD_*, VK_*, Mesa overrides, injected layers, or user ICDs.
    return dict(PATH='/usr/bin:/bin',LANG='C.UTF-8',HOME=str(output/'home'),TMPDIR=str(output/'tmp'),
        XDG_CONFIG_HOME=str(output/'empty'),XDG_CONFIG_DIRS=str(output/'empty'),XDG_DATA_HOME=str(output/'empty'),
        XDG_DATA_DIRS=str(output/'empty'),VK_DRIVER_FILES=str(manifest),VK_ICD_FILENAMES=str(manifest),
        VK_LAYER_PATH=str(output/'empty'),VK_IMPLICIT_LAYER_PATH=str(output/'empty'),VK_LOADER_LAYERS_DISABLE='~all~',
        MESA_SHADER_CACHE_DISABLE='true',MESA_VK_WSI_DEBUG='sw')


def execute(command, env, output):
    process=subprocess.Popen([str(x) for x in command],cwd=output,env=env,stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,start_new_session=True)
    deadline=time.monotonic()+20;overflow=False;stored=0
    try:
        os.set_blocking(process.stdout.fileno(),False)
        with selectors.DefaultSelector() as ready, (output/'probe.log').open('xb') as log:
            ready.register(process.stdout,selectors.EVENT_READ)
            while ready.get_map():
                require(time.monotonic()<deadline,'probe-timeout')
                for key,_ in ready.select(min(0.1,max(0,deadline-time.monotonic()))):
                    chunk=os.read(key.fileobj.fileno(),65536)
                    if not chunk:ready.unregister(key.fileobj);continue
                    keep=chunk[:max(0,1024**2-stored)];log.write(keep);stored+=len(keep)
                    overflow|=len(keep)!=len(chunk)
        code=process.wait(timeout=max(0.01,deadline-time.monotonic()))
        require(code==0 and not overflow,'probe-exit-or-log-limit')
        return code
    finally:
        # Do not reap the leader until after any required group kill, preserving
        # its identity while cleaning up this one owned process group.
        if process.returncode is None:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait(timeout=5)
        process.stdout.close()


def validate(value, no_gpu):
    expected={'formatVersion','scope','icdLoaded','noKgslHostVerified','turnip740ShaderReadbackQualified',
        'pixelsVerified','vendorId','deviceId','deviceName','x11PresentationQualified','androidQualified','gameplayQualified'}
    require(type(value) is dict and set(value)==expected,'probe-receipt-schema')
    require(type(value['formatVersion']) is int and value['formatVersion']==1 and
        value['scope']=='linux-arm64-turnip-kgsl-component-probe' and value['icdLoaded'] is True and
        value['noKgslHostVerified'] is no_gpu and value['turnip740ShaderReadbackQualified'] is (not no_gpu) and
        all(value[x] is False for x in ('x11PresentationQualified','androidQualified','gameplayQualified')),'probe-receipt-scope')
    require(all(type(value[x]) is int for x in ('pixelsVerified','vendorId','deviceId')) and
        type(value['deviceName']) is str and len(value['deviceName'])<=255,'probe-receipt-types')
    if no_gpu:
        require(value['pixelsVerified']==value['vendorId']==value['deviceId']==0 and value['deviceName']=='','unexpected-device')
    else:
        require(value['pixelsVerified']==4096 and value['vendorId']==0x5143 and value['deviceId']>0 and
                '740' in value['deviceName'],'actual-turnip740-readback-required')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--build-sha256',required=True);parser.add_argument('--source-revision',required=True)
    parser.add_argument('--expect-no-kgsl',action='store_true');args=parser.parse_args()
    require(platform.machine() in ('aarch64','arm64'),'native-arm64-required')
    require(re.fullmatch('[0-9a-f]{64}',args.build_sha256) and re.fullmatch('[0-9a-f]{40}',args.source_revision),'exact-provenance-required')
    payload=args.payload.resolve();receipt=payload/'turnip-build.json'
    require(identity(receipt)['sha256']==args.build_sha256,'build-receipt-pin-mismatch')
    build=bounded_json(receipt,1024**2)
    require(build.get('scope')=='linux-arm64-turnip-kgsl-build-only' and
            build.get('integrationRevision')==args.source_revision and build.get('compiled') is True,'build-identity-mismatch')
    for name in ('lib/libvulkan_freedreno.so','bin/esteria-turnip-probe'):
        pin=build['binaries'][name]
        require(identity(payload/name)==dict(bytes=pin['bytes'],sha256=pin['sha256']),'binary-identity-mismatch')
    preload=Path('/etc/ld.so.preload')
    require(not preload.exists() or preload.stat().st_size==0,'global-loader-preload-refused')
    args.output.mkdir(mode=0o700);output=args.output.resolve()
    for name in ('tmp','home','empty'):(output/name).mkdir(mode=0o700)
    manifest=output/'exclusive-icd.json'
    manifest.write_text(json.dumps(dict(file_format_version='1.0.0',ICD=dict(
        library_path=str(payload/'lib/libvulkan_freedreno.so'),api_version='1.3.0')))+'\n')
    result=dict(formatVersion=1,scope='pinned-linux-arm64-turnip-probe',sourceRevision=args.source_revision,
        buildReceiptSha256=args.build_sha256,driver=build['binaries']['lib/libvulkan_freedreno.so'],
        probe=build['binaries']['bin/esteria-turnip-probe'],qualified=False,hardwareQualified=False,
        androidQualified=False,x11PresentationQualified=False,gameplayQualified=False)
    try:
        mode='--expect-no-kgsl' if args.expect_no_kgsl else '--gpu-readback'
        execute([payload/'bin/esteria-turnip-probe',payload/'lib/libvulkan_freedreno.so',output/'probe.json',mode],
                environment(output,manifest),output)
        value=bounded_json(output/'probe.json',4096);validate(value,args.expect_no_kgsl)
        result.update(qualified=True,hardwareQualified=not args.expect_no_kgsl,receipt=value)
    finally:
        (output/'qualification.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
