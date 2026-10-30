#!/usr/bin/env python3
"""Execute the separate x86_64 PRoot/glibc probe only on a disposable Android13 emulator."""
import argparse
import json
from pathlib import Path
import re
import time
try:
    from .qualify_android_installer import digest, instrument_passed, run_bounded
    from .verify_android_proot_probe import verify, require
except ImportError:
    from qualify_android_installer import digest, instrument_passed, run_bounded
    from verify_android_proot_probe import verify, require

PACKAGE='io.github.russianranger.esteria'
SCOPE='android-13-x86_64-proot-glibc-execution'
FLAGS=('androidProotExecuted','privateElfLoaderExecuted','directPrivateBionicExecRejected',
       'dynamicLibraryAndTlsVerified','forkExecLoopbackVerified','relaunchPersistenceVerified',
       'androidTracerDeathQualified','pidfdIdentityVerified','gracefulGuestStopVerified','userSpaceWaitArmed',
       'androidOwnerProcessDeathQualified','ownerDeathControlTracerSurvived','ownerDeathProtectedTracerExited')


def validate_receipt(value,revision,fingerprint,build):
    require(type(value.get('formatVersion')) is int and value['formatVersion']==1 and value.get('scope')==SCOPE and
            value.get('sourceRevision')==revision and value.get('fingerprint')==fingerprint and value.get('abi')=='x86_64' and
            value.get('glibcVersion')=='2.36','proot-receipt-identity')
    for key,expected in (('api',33),('targetSdk',35),('guestLaunches',8),('guestChildExit',17),
                         ('controlSurvivors',3),('patchedSurvivors',0),('detachedTraceesPerCase',3),('gracefulSavedFilesRestored',3),
                         ('ownerDeathVerifiedHandles',9),('ownerDeathControlSurvivors',3),('ownerDeathProtectedSurvivors',0)):
        require(type(value.get(key)) is int and value[key]==expected,'proot-receipt-count-'+key)
    for key in ('controlObservationMillis','patchedObservationMillis','ownerDeathObservationMillis'):
        require(type(value.get(key)) is int and 0<=value[key]<25000,'proot-receipt-alarm-budget-'+key)
    require(value.get('buildEvidence')==build,'proot-receipt-build-differs')
    require(all(value.get(flag) is True for flag in FLAGS),'proot-receipt-missing-check')
    require(all(value.get(flag) is False for flag in ('arm64GuestExecuted','appDeathQualified','wineQualified','gameplayQualified',
            'isolatedParentDeathSignalQualified')),'proot-receipt-overclaims-scope')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb',default='adb'); parser.add_argument('--apk',type=Path,required=True)
    parser.add_argument('--test-apk',type=Path,required=True); parser.add_argument('--provider',type=Path,required=True)
    parser.add_argument('--source-revision',required=True); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    require(re.fullmatch('[0-9a-f]{40}',args.source_revision) is not None,'full-source-revision-required')
    verify(args.provider,args.apk)
    require(0<args.test_apk.stat().st_size<=64*1024**2,'test-apk-size-limit')
    build=json.loads((args.provider/'assets/proot-probe/build-evidence.json').read_text())
    args.output.mkdir(parents=True,exist_ok=False)
    report=dict(formatVersion=1,scope=SCOPE,sourceRevision=args.source_revision,
        apk=dict(bytes=args.apk.stat().st_size,sha256=digest(args.apk)),
        testApk=dict(bytes=args.test_apk.stat().st_size,sha256=digest(args.test_apk)),
        androidProotGlibcQualified=False,androidTracerDeathQualified=False,androidOwnerProcessDeathQualified=False,
        isolatedParentDeathSignalQualified=False,arm64GuestExecuted=False,appDeathQualified=False,wineQualified=False,gameplayQualified=False)
    installed=False;failure=None
    def command(label,words,timeout=180,allow_failure=False):
        code,text=run_bounded([args.adb,*words],args.output/(label+'.log'),timeout)
        require(code==0 or allow_failure,label+'-command-failed');return code,text
    try:
        _,serial=command('serial',['get-serialno']);require(re.fullmatch(r'emulator-[0-9]+',serial.strip()) is not None,'physical-or-remote-device-refused')
        properties={}
        for name in ('ro.kernel.qemu','ro.build.version.sdk','ro.product.cpu.abi','ro.build.fingerprint'):
            _,text=command(name,['shell','getprop',name]);properties[name]=text.strip()
        report['emulatorProperties']=properties
        require(tuple(properties[name] for name in ('ro.kernel.qemu','ro.build.version.sdk','ro.product.cpu.abi'))==('1','33','x86_64'),'android13-x86_64-emulator-required')
        _,existing=command('preexisting',['shell','pm','path',PACKAGE],allow_failure=True)
        require('package:' not in existing,'preexisting-installation-refused')
        command('install-app',['install',str(args.apk)]);installed=True
        command('install-tests',['install',str(args.test_apk)])
        _,result=command('proot-contracts',['shell','am','instrument','-w','-r','-e','class',
            PACKAGE+'.runtime.ProotExecutionTest#privateGlibcExecutesThroughApkLoader',
            PACKAGE+'.test/androidx.test.runner.AndroidJUnitRunner'],timeout=240)
        require(instrument_passed(result),'proot-instrumentation-did-not-pass')
        _,raw=command('app-receipt',['exec-out','run-as',PACKAGE,'cat','files/proot-probe-qualification.json'])
        require(len(raw.encode())<=65536,'oversized-app-receipt')
        evidence=json.loads(raw);validate_receipt(evidence,args.source_revision,properties['ro.build.fingerprint'],build)
        report['appEvidence']=evidence;report['androidProotGlibcQualified']=True;report['androidTracerDeathQualified']=True
        report['androidOwnerProcessDeathQualified']=True
    except Exception as error:
        failure=error;report['error']=str(error)
    finally:
        if installed:
            diagnostics=[(mode+'-'+stream,['exec-out','run-as',PACKAGE,'cat','files/proot-probe-session/logs/'+mode+'/'+stream+'.log'])
                         for mode in ('write','verify') for stream in ('stdout','stderr')]
            diagnostics += [(mode+'-'+stream,['exec-out','run-as',PACKAGE,'cat','files/proot-probe-session/'+mode+'/logs/'+stream+'.log'])
                            for mode in ('ownership-control','ownership-patched','ownership-graceful') for stream in ('stdout','stderr')]
            diagnostics += [('graceful-relaunch-'+stream,['exec-out','run-as',PACKAGE,'cat','files/proot-probe-session/ownership-graceful/verify/'+stream+'.log'])
                            for stream in ('stdout','stderr')]
            diagnostics += [('owner-process-'+mode+'-'+stream,['exec-out','run-as',PACKAGE,'cat',
                            'files/proot-probe-session/owner-process-death/'+mode+'/logs/'+stream+'.log'])
                            for mode in ('control','service') for stream in ('stdout','stderr')]
            diagnostics += [('bounded-logcat',['logcat','-d','-t','1500']),('stop-owned-test-app',['shell','am','force-stop',PACKAGE])]
            for label,words in diagnostics:
                try:command(label,words,allow_failure=label!='stop-owned-test-app')
                except Exception as error:
                    report['androidProotGlibcQualified']=False;report['androidTracerDeathQualified']=False
                    report['androidOwnerProcessDeathQualified']=False;report.setdefault('cleanupErrors',[]).append(str(error))
                    if failure is None:failure=error
        report['completedAtUnix']=int(time.time())
        (args.output/'qualification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if failure is not None:raise failure


if __name__=='__main__':main()
