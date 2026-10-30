#!/usr/bin/env python3
"""Qualify full guest stat tuples on a disposable Android13 x64 emulator only.

This cannot enable a production cache or qualify Android ARM64/Thor execution.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import stat
import time

try:
    from . import build_android_proot_stat_probe as fixture, verify_android_proot_probe as proot
    from .qualify_android_installer import digest,instrument_passed,run_bounded
except ImportError:
    import build_android_proot_stat_probe as fixture, verify_android_proot_probe as proot
    from qualify_android_installer import digest,instrument_passed,run_bounded

PACKAGE='io.github.russianranger.esteria'
SCOPE='android-13-x86_64-proot-stat-metadata-visible-mutations'
FIELDS=('dev','ino','mode','uid','gid','nlink','size','mtimeNs','ctimeNs')
VIEWS={'work','data','rawWork','rawData'}
OBSERVATIONS={'regularInitial','hardlinkAdded','hardlinkRemoved','modeChanged','modeRestored','mtimeFixed','rewritten','replaced',
    'directoryInitial','directoryAdded','directoryRemoved','symlink','symlinkTarget','ancestor','ancestorLeaf'}
FINAL={'generation','dataRoot','receipt','regular','directory','symlink','ancestor','ancestorLeaf'}
require=fixture.require

def tuple_value(value):
    require(type(value) is dict and set(value)==set(FIELDS),'stat-tuple-field-set')
    for name,raw in value.items():
        require(type(raw) is str and re.fullmatch(r'0|[1-9][0-9]{0,19}',raw) is not None and
            0<=int(raw)<=((1<<64)-1),'stat-tuple-integer-'+name)
    require(int(value['ino'])>0 and int(value['nlink'])>0 and
        stat.S_IFMT(int(value['mode'])) in (stat.S_IFREG,stat.S_IFDIR,stat.S_IFLNK),'stat-tuple-node-type')
    require(int(value['mtimeNs'])<(1<<63) and int(value['ctimeNs'])<(1<<63),'stat-tuple-timestamp-range')
    return value

def observation(value):
    require(type(value) is dict and set(value)==VIEWS,'stat-alias-syscall-view-set')
    for row in value.values():tuple_value(row)
    require(all(row==value['work'] for row in value.values()),'stat-alias-or-syscall-mismatch')
    return value['work']

def validate_guests(mutation,relaunch):
    for value,mode in ((mutation,'mutate'),(relaunch,'verify')):
        require(type(value) is dict and set(value)=={'formatVersion','scope','mode','observations','finalSnapshot',
            'metadataVisibleMutationsOnly','unchangedMetadataCorruptionDetectionClaimed'} and type(value.get('formatVersion')) is int and value.get('formatVersion')==1 and
            value.get('scope')=='linux-glibc-stat-alias-mutation-fixture' and value.get('mode')==mode and
            value.get('metadataVisibleMutationsOnly') is True and value.get('unchangedMetadataCorruptionDetectionClaimed') is False,
            'stat-guest-scope')
        require(set(value['finalSnapshot'])==FINAL,'stat-final-node-set')
        for row in value['finalSnapshot'].values():observation(row)
    require(set(mutation['observations'])==OBSERVATIONS and relaunch['observations']=={},'stat-mutation-case-set')
    seen={name:observation(row) for name,row in mutation['observations'].items()}
    require(mutation['finalSnapshot']==relaunch['finalSnapshot'],'stat-tuples-changed-across-reaped-relaunch')
    before,mode,restored=(seen[name] for name in ('regularInitial','modeChanged','modeRestored'))
    linked,unlinked=(seen[name] for name in ('hardlinkAdded','hardlinkRemoved'))
    require((before['nlink'],linked['nlink'],unlinked['nlink'])==('1','2','1') and
        all(before[name]==linked[name]==unlinked[name] for name in FIELDS if name not in ('nlink','ctimeNs')) and
        before['ctimeNs']!=linked['ctimeNs']!=unlinked['ctimeNs'],'stat-hardlink-count-change-not-visible')
    require(stat.S_IMODE(int(before['mode']))==0o600 and stat.S_IMODE(int(mode['mode']))==0o400 and
        stat.S_IMODE(int(restored['mode']))==0o600 and before['ino']==mode['ino']==restored['ino'] and
        before['ctimeNs']!=mode['ctimeNs'],'stat-mode-change-not-visible')
    fixed,written,replaced=(seen[name] for name in ('mtimeFixed','rewritten','replaced'))
    require(int(fixed['mtimeNs'])%1_000_000_000==123456789,'stat-nanosecond-mtime-not-preserved')
    require(all(fixed[name]==written[name] for name in FIELDS if name!='ctimeNs') and fixed['ctimeNs']!=written['ctimeNs'],
        'stat-restored-mtime-write-not-visible-in-ctime')
    require(written['ino']!=replaced['ino'] and all(written[name]==replaced[name] for name in
        ('dev','mode','uid','gid','nlink','size','mtimeNs')),'stat-same-content-replacement-not-visible')
    for first,second in (('directoryInitial','directoryAdded'),('directoryAdded','directoryRemoved')):
        a,b=seen[first],seen[second]
        require(a['dev']==b['dev'] and a['ino']==b['ino'] and a['mtimeNs']==b['mtimeNs'] and a['ctimeNs']!=b['ctimeNs'],
            'stat-restored-directory-mtime-entry-change-not-visible')
    require(stat.S_ISLNK(int(seen['symlink']['mode'])) and stat.S_ISLNK(int(seen['ancestor']['mode'])) and
        seen['symlinkTarget']==replaced and seen['ancestorLeaf']==replaced,'stat-symlink-observation-differs')
    final=mutation['finalSnapshot']
    require(stat.S_ISDIR(int(observation(final['generation'])['mode'])) and
        stat.S_ISDIR(int(observation(final['dataRoot'])['mode'])) and observation(final['regular'])==replaced,
        'stat-generation-final-snapshot')
    return dict(aliasAndRawSyscallTuplesMatched=True,nanosecondMtimePreserved=True,
        sameLengthWriteRestoredMtimeChangedCtime=True,sameContentsReplacementChangedInode=True,
        modeChangesVisible=True,hardlinkAddDeleteChangedLinkCountAndCtime=True,directoryAddDeleteWithRestoredMtimeChangedCtime=True,
        terminalSymlinkVisible=True,symlinkAncestorVisible=True,leafOnlySymlinkProtectionClaimed=False,
        reapedGuestRelaunchTuplesStable=True,observations=15,finalNodes=8,
        productionCacheEnabled=False,arm64Qualified=False,gameplayQualified=False,
        unchangedMetadataCorruptionDetectionClaimed=False)

def validate_receipt(value,revision,fingerprint,build,stat_build):
    require(type(value) is dict and value.get('formatVersion')==1 and value.get('scope')==SCOPE and
        value.get('sourceRevision')==revision and value.get('fingerprint')==fingerprint and value.get('api')==33 and
        value.get('targetSdk')==35 and value.get('abi')=='x86_64' and value.get('guestLaunches')==2 and
        value.get('buildEvidence')==build and value.get('statBuildEvidence')==stat_build,'android-stat-receipt-selection')
    require(all(type(value.get(name)) is int for name in ('formatVersion','api','targetSdk','guestLaunches')),
        'android-stat-receipt-integer-types')
    require(value.get('aliases')=={'work':'/work/server-data/generations/'+'a'*64,'data':'/esteria-data'},'android-stat-mount-aliases')
    require(value.get('childExitCodes')==[0,0] and value.get('forcedChildren')==[False,False] and
        value.get('remainingNativeMembers')==[0,0] and value.get('noFollowAncestorOpenRejected') is True,
        'android-stat-actual-owned-guest-reaping')
    require(all(type(item) is int for name in ('childExitCodes','remainingNativeMembers') for item in value[name]) and
        all(type(item) is bool for item in value['forcedChildren']),'android-stat-reaping-field-types')
    require(all(value.get(key) is False for key in ('productionCacheEnabled','arm64Qualified','hardwareQualified',
        'unchangedMetadataCorruptionDetectionClaimed','gameplayQualified')),'android-stat-receipt-overclaims')
    return validate_guests(value['mutation'],value['relaunch'])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb',default='adb')
    for name in ('apk','test-apk','proot-provider','stat-provider','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--source-revision',required=True);args=parser.parse_args()
    require(re.fullmatch('[0-9a-f]{40}',args.source_revision) is not None,'android-stat-source-revision')
    proot.verify(args.proot_provider,args.apk);stat_build=fixture.verify(args.stat_provider,args.test_apk)
    require(stat_build['sourceRevision']==args.source_revision and stat_build['sourceSnapshotExact'] is True and
        fixture.exact_source(args.source_revision,stat_build['sourceInputs']),'android-stat-exact-committed-fixture-required')
    build=json.loads((args.proot_provider/'assets/proot-probe/build-evidence.json').read_bytes())
    args.output.mkdir(parents=True,exist_ok=False)
    report=dict(formatVersion=1,scope=SCOPE,sourceRevision=args.source_revision,
        apk=dict(bytes=args.apk.stat().st_size,sha256=digest(args.apk)),
        testApk=dict(bytes=args.test_apk.stat().st_size,sha256=digest(args.test_apk)),
        androidX64StatQualified=False,productionCacheEnabled=False,arm64Qualified=False,hardwareQualified=False,
        unchangedMetadataCorruptionDetectionClaimed=False,gameplayQualified=False)
    installed=False;failure=None
    def command(label,words,timeout=180,allow_failure=False):
        code,text=run_bounded([args.adb,*words],args.output/(label+'.log'),timeout)
        require(code==0 or allow_failure,label+'-failed');return text
    try:
        require(re.fullmatch(r'emulator-[0-9]+',command('serial',['get-serialno']).strip()) is not None,'physical-or-remote-device-refused')
        properties={name:command(name,['shell','getprop',name]).strip() for name in
            ('ro.kernel.qemu','ro.build.version.sdk','ro.product.cpu.abi','ro.build.fingerprint')}
        report['emulatorProperties']=properties
        require(tuple(properties[name] for name in ('ro.kernel.qemu','ro.build.version.sdk','ro.product.cpu.abi'))==('1','33','x86_64'),
            'disposable-android13-x64-required')
        require('package:' not in command('preexisting',['shell','pm','path',PACKAGE],allow_failure=True),'preexisting-installation-refused')
        command('install',['install',str(args.apk)]);installed=True
        command('install-tests',['install',str(args.test_apk)])
        result=command('instrument',['shell','am','instrument','-w','-r','-e','class',
            PACKAGE+'.runtime.ProotStatMetadataTest#statTuplesSurviveAliasesAndExposeMutations',
            PACKAGE+'.test/androidx.test.runner.AndroidJUnitRunner'],timeout=120)
        require(instrument_passed(result),'android-stat-instrumentation-failed')
        raw=command('receipt',['exec-out','run-as',PACKAGE,'cat','files/proot-stat-qualification.json'])
        require(len(raw.encode())<=256<<10,'android-stat-app-receipt-bound')
        evidence=json.loads(raw)
        report['checks']=validate_receipt(evidence,args.source_revision,properties['ro.build.fingerprint'],build,stat_build)
        report['appEvidence']=evidence;report['androidX64StatQualified']=True
    except Exception as error:failure=error;report['error']=str(error)
    finally:
        if installed:
            diagnostics=[(mode+'-'+stream,['exec-out','run-as',PACKAGE,'cat','files/proot-stat-session/logs/'+mode+'/'+stream+'.log'])
                for mode in ('mutate','verify') for stream in ('stdout','stderr')]
            diagnostics += [('logcat',['logcat','-d','-t','600']),('stop',['shell','am','force-stop',PACKAGE])]
            for label,words in diagnostics:
                try:command(label,words,allow_failure=label!='stop')
                except Exception as error:
                    report['androidX64StatQualified']=False;report.setdefault('cleanupErrors',[]).append(str(error));failure=failure or error
        report['completedAtUnix']=int(time.time())
        (args.output/'qualification.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ('scope','androidX64StatQualified','productionCacheEnabled','arm64Qualified')},indent=2))
    if failure is not None:raise failure

if __name__=='__main__':main()
