#!/usr/bin/env python3
"""Execute reconstructed x64 client diagnostics in a disposable Android13 emulator."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import types
try:
    from .qualify_android_installer import digest, instrument_passed, run_bounded
    from .verify_android_wine_probe import verify, require
except ImportError:
    from qualify_android_installer import digest, instrument_passed, run_bounded
    from verify_android_wine_probe import verify, require

PACKAGE='io.github.russianranger.esteria'
SCOPE='android-13-x86_64-wine-reconstructed-client-diagnostics'
FALSE_FLAGS=('arm64Qualified','graphicsQualified','audioQualified','authenticationQualified','commonMainStarted','assetsLoaded','gameplayQualified')
PHASES=('entry','offline','loopback')


def client_receipts(provider, directory):
    names=('verify_client_entry','verify_client_offline','verify_client_loopback')
    prior={name:sys.modules.get(name) for name in names};result={}
    try:
        for name,phase in zip(names,PHASES):
            path=provider/'assets/wine-probe/helpers'/(name+'.py')
            module=types.ModuleType(name);module.__file__=str(path)
            sys.modules[name]=module;exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
            receipt,sha=module.read_receipt(directory/(phase+'.json'),'x64')
            result[phase]=dict(clientReceipt=receipt,clientReceiptSha256=sha)
    finally:
        for name,value in prior.items():
            if value is None:sys.modules.pop(name,None)
            else:sys.modules[name]=value
    return result


def validate_receipt(value,revision,fingerprint,proof_raw,proot,checked):
    proof=json.loads(proof_raw)
    require(type(value.get('formatVersion')) is int and value['formatVersion']==1 and value.get('scope')==SCOPE and
            value.get('sourceRevision')==revision and value.get('fingerprint')==fingerprint and value.get('abi')=='x86_64','wine-receipt-identity')
    for name,expected in (('api',33),('targetSdk',35),('guestLaunches',4)):
        require(type(value.get(name)) is int and value[name]==expected,'wine-receipt-count:'+name)
    require(value.get('runtimeProviderSha256')==hashlib.sha256(proof_raw).hexdigest() and
            value.get('runtimeArchiveSha256')==proof['archive']['sha256'] and
            value.get('clientRevision')==proof['clientInput']['sourceRevision'] and
            value.get('clientArtifactSha256')==proof['clientInput']['artifact']['sha256'] and
            value.get('wineVersion')==proof['wineVersion'] and value.get('prootBuildEvidence')==proot and
            re.fullmatch('[a-f0-9]{64}',value.get('runtimeGeneration','')),'wine-receipt-build-identity')
    require(all(value.get(flag) is True for flag in ('runtimeInstalledByProductionInstaller','exactClientPayloadVerified','prefixInitialized','normalPhaseExits')),
            'wine-receipt-missing-behavior')
    require(all(value.get(flag) is False for flag in FALSE_FLAGS),'wine-receipt-overclaim')
    results=value.get('clientChecks',{});require(set(results)==set(checked)==set(PHASES),'wine-receipt-diagnostic-inventory')
    for phase in PHASES:
        expected=dict(formatVersion=1,scope='owned-reconstructed-client-diagnostic-only',phase=phase,
                      **checked[phase],wineserverStoppedNormally=True,commonMainStarted=False,assetsLoaded=False,
                      arm64Qualified=False,gameplayQualified=False)
        require(results[phase]==expected and all(type(results[phase][key]) is type(item) for key,item in expected.items()),
                'wine-receipt-diagnostic-mismatch:'+phase)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--adb',default='adb')
    for name in ('apk','test-apk','provider','proot-provider','runtime-package','client-artifact','client-source','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--source-revision',required=True);args=parser.parse_args()
    require(re.fullmatch('[a-f0-9]{40}',args.source_revision),'full-source-revision-required')
    verify(args.provider,args.proot_provider,args.runtime_package,args.client_artifact,args.client_source,args.apk)
    require(0<args.test_apk.stat().st_size<=64*1024**2,'wine-test-apk-size-limit')
    proof_raw=(args.provider/'assets/wine-probe/provider.json').read_bytes()
    proot=json.loads((args.proot_provider/'assets/proot-probe/build-evidence.json').read_text())
    args.output.mkdir(parents=True,exist_ok=False)
    report=dict(formatVersion=1,scope=SCOPE,sourceRevision=args.source_revision,
                apk=dict(bytes=args.apk.stat().st_size,sha256=digest(args.apk)),
                testApk=dict(bytes=args.test_apk.stat().st_size,sha256=digest(args.test_apk)),
                androidX64WineClientDiagnosticsQualified=False,**{key:False for key in FALSE_FLAGS})
    installed=False;failure=None
    def command(label,words,timeout=180,allow_failure=False):
        code,text=run_bounded([args.adb,*words],args.output/(label+'.log'),timeout)
        require(code==0 or allow_failure,label+'-command-failed');return code,text
    try:
        _,serial=command('serial',['get-serialno']);require(re.fullmatch('emulator-[0-9]+',serial.strip()),'physical-or-remote-device-refused')
        properties={}
        for name in ('ro.kernel.qemu','ro.build.version.sdk','ro.product.cpu.abi','ro.build.fingerprint'):
            _,raw=command(name,['shell','getprop',name]);properties[name]=raw.strip()
        report['emulatorProperties']=properties
        require(tuple(properties[name] for name in ('ro.kernel.qemu','ro.build.version.sdk','ro.product.cpu.abi'))==('1','33','x86_64'),
                'android13-x64-emulator-required')
        _,current=command('preexisting',['shell','pm','path',PACKAGE],allow_failure=True)
        require('package:' not in current,'preexisting-installation-refused')
        command('install-app',['install',str(args.apk)]);installed=True
        command('install-tests',['install',str(args.test_apk)])
        _,result=command('wine-test',['shell','am','instrument','-w','-r','-e','class',
            PACKAGE+'.runtime.WineExecutionTest#actualReconstructedClientRunsThroughWine',
            PACKAGE+'.test/androidx.test.runner.AndroidJUnitRunner'],timeout=1500)
        require(instrument_passed(result),'wine-instrumentation-did-not-pass')
        _,raw=command('app-receipt',['exec-out','run-as',PACKAGE,'cat','files/wine-probe-qualification.json'])
        require(len(raw.encode())<=65536,'wine-receipt-size-limit');evidence=json.loads(raw)
        original=args.output/'client-receipts';original.mkdir()
        for phase,name in zip(PHASES,('Esteria-entry-check.json','Esteria-local-offline-check.json','Esteria-loopback-check.json')):
            _,raw=command('original-'+phase,['exec-out','run-as',PACKAGE,'cat','files/wine-probe-session/work/client/'+name])
            require(len(raw.encode())<=4096,'client-receipt-size-limit');(original/(phase+'.json')).write_text(raw)
        checked=client_receipts(args.provider,original)
        validate_receipt(evidence,args.source_revision,properties['ro.build.fingerprint'],proof_raw,proot,checked)
        report['appEvidence']=evidence;report['androidX64WineClientDiagnosticsQualified']=True
    except Exception as error:failure=error;report['error']=str(error)
    finally:
        if installed:
            for phase in ('prefix',*PHASES):
                for stream in ('stdout','stderr'):
                    try:command(phase+'-'+stream,['exec-out','run-as',PACKAGE,'cat','files/wine-probe-session/sessions/'+phase+'/logs/'+stream+'.log'],allow_failure=True)
                    except Exception as error:report.setdefault('diagnosticErrors',[]).append(str(error))
            for label,words in [('bounded-logcat',['logcat','-d','-t','1200']),('stop-owned-test-app',['shell','am','force-stop',PACKAGE])]:
                try:command(label,words,allow_failure=label!='stop-owned-test-app')
                except Exception as error:
                    report['androidX64WineClientDiagnosticsQualified']=False;report.setdefault('cleanupErrors',[]).append(str(error))
                    if failure is None:failure=error
        report['completedAtUnix']=int(time.time());(args.output/'qualification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if failure is not None:raise failure


if __name__=='__main__':main()
