"""Start and stop the APK's production MySQL twice on an offline, fresh Android package."""
import os
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from tools.android_stock_shader.package_lifecycle import identity, check_empty
from tools.android_stock_shader.run_owner import BOOT_KEYS, PACKAGE, checked, shell

CONTAINER='esteria-android-qa'


def updater_logs():
    base='/data/data/'+PACKAGE+'/files'
    raw=shell(CONTAINER,'''for f in "$1"/s/*/{prefix-update,u}/logs/{stdout,stderr}.log; do
        if test -f "$f"; then echo "PRIVATE-QA-STREAM"; tail -c 8192 "$f"; echo; fi
    done''',base)
    # This fresh offline container never carries a game import, account or user data.
    # Export only allowlisted fixed native errors. Source line/strings are fixed.
    keys=('err:','could not load','cannot execute','not found','no such file','Permission denied','not owned','not writable','Operation not permitted','failed','wine:','proot error','wine64','wineserver','kernel32','wineboot','/opt/wine/bin/wine','/bin/sh','/usr/bin/env','prefix-update-finished','/session','missing','c0000135','cannot find','error while loading shared libraries','cannot create','mkdir','boot event','chdir','execve','bad exe format','X connection','too long','file exists','python')
    lines=[]
    for line in raw.splitlines():
        found=[k for k in keys if k.lower() in line.lower()]
        if not found:continue
        row={'matches':found, 'winstatus':re.findall(r'(?i)\b(?:c000|8007)[0-9a-f]{4}\b',line),
             'knownFiles':re.findall(r'(?i)\b(?:wine(?:boot|server|64)?|kernel32|ntdll|kernelbase|services|cmd|rundll32|start|dash|Xauthority|ld-linux-aarch64|libwine)[.a-z0-9-]{0,10}\b',line)}
        if re.fullmatch(r'wineserver: [a-z ]{1,24}: (?:Invalid argument|File name too long|Address already in use|Operation not permitted|Permission denied|No such file or directory|Bad file descriptor|Not a directory|Not a socket|Function not implemented|Connection refused)',line):row['syscallError']=line
        if len(line)<160 and line.isascii() and line.startswith('wineserver: ') and '/' not in line and '\\' not in line and re.fullmatch(r"[A-Za-z0-9 ,.():='-]{1,159}",line):row['fixedSystemDiagnostic']=line
        if row not in lines:lines.append(row)
    lengths=shell(CONTAINER,'''for tmp in "$1"/s/*/{prefix-update,u}/tmp; do
        if test -d "$tmp"; then
          real=$(readlink -f "$tmp"); echo "TMP ${#real}"
          for socketdir in "$real"/.wine-*/server-*; do if test -d "$socketdir"; then d="$socketdir/socket"; echo "CANDIDATE ${#d}"; fi; done
        fi; done''',base)
    return dict(streams=raw.count('PRIVATE-QA-STREAM'),signals=lines[:30],characters=len(raw),
                nativePathFacts=[m.groups() for m in re.finditer(r'^(TMP|CANDIDATE) ([0-9]{1,3})$',lengths,re.M)],
                testedLeaf=os.environ.get('ESTERIA_SOCKET_SHAPE','declared'))

def wine_details(report, mode):
    root='/data/data/'+PACKAGE+'/files'
    # Private Wine and PE logs may contain memory dumps. Export only controlled status fields.
    if mode in ('interrupt','reentry'):root+='/qa-original'
    report['winePhases']=[]
    diagnostics=shell(CONTAINER,'''for f in "$1"/state/client-work/*/phase.json; do
        if test -f "$f"; then cat "$f"; echo; fi
    done''',root)
    for line in diagnostics.splitlines():
        item=json.loads(line)
        if item.get('phase') in {'display','wineboot','windows-prefix-command','windows-first-use','prefix-ready','wait-owned-authserver',
                                'reconstructed-grunt','reconstructed-grunt-first-use','grunt-exited'}:
            allowed={'elapsedMs':int,'returnCode':int,'loaderStatus135':bool,'kernel32Mentioned':bool,
                     'prefixKernel32':bool,'prefixWineboot':bool}
            report['winePhases'].append(dict(phase=item['phase'],**{k:item[k] for k,t in allowed.items()
                                               if k in item and type(item[k]) is t}))
    observation=shell(CONTAINER,'''for f in "$1"/state/client-work/"$2"/first-use.json; do
        if test -f "$f"; then cat "$f"; fi
    done''',root,mode)
    if observation:
        from tools.android_stock_database.wine_prefix import DLLS, NAMES, PATTERNS, REGISTRATIONS
        timeline=[]
        for sample in json.loads(observation)['samples'][-100:]:
            row={k:v for k,v in sample.items() if k in ('seconds','system32Entries','systemRegBytes','traceBytes','wineInfMtime','updateTimestamp') and type(v) is int}
            for k,allowed in [('installed',DLLS),('processes',NAMES),('traceMarkers',PATTERNS)]:
                row[k]=[v for v in sample[k] if v in allowed]
            row['commandExits']=[v for v in sample['commandExits'][:2] if v is None or type(v) is int]
            row['waits']={pid:{'name':w['name'],'appwizMono':w['appwizMono'] is True,
                                'appwizGecko':w['appwizGecko'] is True,'waits':[v for v in w['waits'] if re.fullmatch(
                r'(?:[0-9a-z_]{1,40}|sha256:[a-f0-9]{64})',v)]} for pid,w in sample['waits'].items()
                if re.fullmatch(r'\d{1,8}',pid) and w['name'] in ('rundll32','wineboot','control.exe')}
            if sample['registration'] in REGISTRATIONS:
                row['lastSelectedRegistration']=sample['registration']
            # These labels were safely mapped before they crossed the X11 process boundary.
            from tools.android_stock_database.wine_windows import LABELS
            allow=lambda v: isinstance(v,str) and (v in LABELS or re.fullmatch(r'sha256:[0-9a-f]{64}',v))
            row['windows']=[{'title':w['title'],'classes':w['classes'],'pid':w['pid']} for w in sample['windows']
                           if (w['title'] is None or allow(w['title'])) and all(allow(v) for v in w['classes']) and
                           (w['pid'] is None or type(w['pid']) is int)]
            setup=sample['setup']
            if setup and type(setup['tid']) is int and re.fullmatch(r'[a-z0-9_]{1,80}',setup['function']):
                row['setup']=setup
            timeline.append(row)
        report['firstUseTimeline']=timeline
def failure_details(report):
    wine_details(report,report['phase'])
    root='/data/data/'+PACKAGE+'/files'
    paths=shell(CONTAINER,'''for dir in "$1"/db/*; do if test -d "$dir"; then basename "$dir"; fi; done''',root).splitlines()
    if len(paths)!=1 or not re.fullmatch(r'[a-f0-9]{16}',paths[0]):
        report['allocatedSlots']=len(paths)
        return
    base=root+'/db/'+paths[0]
    files=shell(CONTAINER,'''for f in "$2"/qa-auth-*/phase.json; do test ! -f "$f" || cat "$f"; done''',root,base)
    report['authObserverPhases']=re.findall(r'"phase": "([a-z0-9-]+)"',files)
    raw=shell(CONTAINER,'''for f in "$1"/state/database-operations/*/logs/stderr.log "$1"/state/server-installation-processes/*/logs/stderr.log; do
         if test -f "$f"; then tail -c 5000 "$f"; fi
     done''',root)
    matches=re.findall(r'Database setup failed \(([a-zA-Z0-9_:,;= -]{1,350})\)',raw)
    if matches:
        report['bootstrapDiagnostic']=matches[-1]
    for name, kind in [('mysql-initialize-engine.log','initialization'),('mysql-bootstrap-engine.log','bootstrap')]:
        raw=shell(CONTAINER,'''f="$1/state/logs/$2"
            if test -f "$f"; then tail -c 32000 "$f"; fi''',base,name)
        events=[]
        for line in raw.splitlines():
            m=re.fullmatch(r'(\S+) \d+ \[(\w+)\] \[(MY-\d+)\] \[([\w ]+)\] (.*)',line)
            if m:
                row=dict(time=m[1],level=m[2],code=m[3],component=m[4])
                msg=m[5]
                # The isolated attempt has a newly generated secret, never record raw
                # SQL, arbitrary daemon strings or a potentially password-bearing line.
                if m[2] in {'ERROR','Warning'} and not re.search(
                        r'password|secret|credential|authentication|statement|query|user=|identified by',msg,re.I):
                    row['unixSocket']='socket' in msg.lower()
                    row['fsError']=[error for error in ('Permission denied','No such file or directory',
                        'File name too long','Address already in use','Operation not permitted',
                        'Read-only file system','Invalid argument','Function not implemented','No space left on device')
                        if error.lower() in msg.lower()]
                    row['errno']=re.findall(r'(?:errno|errcode|OS error|operating system error number)[ :]*(\d+)',msg,re.I)
                events.append(row)
        report[kind+'Events']=events
        report[kind+'EngineLogSha256']=hashlib.sha256(raw.encode()).hexdigest()
    meta=shell(CONTAINER,'''for file in database-bootstrap.json server-installation-staged.json server-installation-verified.json server-setup-complete.json; do
            if test -f "$1/state/$file"; then echo "$file"; fi
        done''',base)
    report['durableComponentReceipts']=meta.splitlines()



def exercise(report):
    package_uid=identity(CONTAINER)
    apk=shell(CONTAINER,'pm path "$1"',PACKAGE).strip()
    match=re.fullmatch(r'package:(/data/app/[A-Za-z0-9_./=+~-]+/base\.apk)',apk)
    checked(match,'single installed APK required')
    apk=match[1]
    native=apk.rsplit('/',1)[0]+'/lib/arm64'
    raw=shell(CONTAINER, "set -- $(pidof zygote64); test $# -eq 1; tr '\\000' '\\n' </proc/$1/environ")
    boot=[v for v in raw.splitlines() if '=' in v and v.split('=',1)[0] in BOOT_KEYS]
    checked(any(v.startswith('BOOTCLASSPATH=') for v in boot),'missing ART environment')
    report['operations']=[]
    report.update(packageUid=package_uid,selinux=shell(CONTAINER,'getenforce').strip(),
                  fingerprint=shell(CONTAINER,'getprop ro.build.fingerprint').strip())
    scenario=os.environ['ESTERIA_WINE_CONTROL'];assert scenario in ('reference','retained')
    phases=['reference','noop','unknown'] if scenario=='reference' else ['interrupt','reentry','clone','cancel','update','finish','noop','warm','audit']
    report['samples']={}
    for mode in phases:
        report['phase']=mode
        cmd=['docker','exec','--user',f'{package_uid}:{package_uid}',CONTAINER,
             '/system/bin/env','-i',*boot,'CLASSPATH=/esteria-qa/input/driver.jar:'+apk,
             '/system/bin/app_process64','-Djava.library.path='+native+':/system/lib64','/system/bin',
             'io.github.russianranger.esteria.runtime.ConfirmDatabase',mode]
        result=subprocess.run(cmd,capture_output=True,text=True,timeout=50*60)
        phases=[line for line in result.stdout.splitlines() if re.fullmatch(r'ANDROID_DB_PHASE [a-z0-9_-]+ \d+',line)]
        report['lastPhases']=phases
        sizes=re.findall(r'^ANDROID_DB_SOCKET_BYTES (\d+)$',result.stdout,re.MULTILINE)
        if sizes: report['coldPhysicalBootstrapSocketBytes']=int(sizes[-1])
        rows=[line.removeprefix('ANDROID_DB_RESULT ') for line in result.stdout.splitlines() if line.startswith('ANDROID_DB_RESULT ')]
        if result.returncode or len(rows)!=1:
            report['exitCode']=result.returncode
            report['appStack']=re.findall(r'^\s*at (io\.github\.russianranger\.esteria(?:\.[A-Za-z_$0-9]+)+)\(([A-Za-z0-9_]+\.java:\d+)\)',result.stderr,re.MULTILINE)[:30]
            report['exceptionClasses']=re.findall(r'^ANDROID_DB_EXCEPTION ([A-Za-z0-9_.]+)$',result.stderr,re.MULTILINE)
            failure_details(report)
            raise RuntimeError('signed database owner failed')
        item=json.loads(rows[0]); checked(item['control']==mode and item['ownerClosed'],'invalid observer exit')
        if mode in ('cancel','update','finish'):
            item['updaterLogEvidence']=updater_logs()
        check_empty(CONTAINER,package_uid)
        report['postCleanupPackageUidProcesses']=0
        report['operations'].append(item)
        checked(item['changedSource']=='UNRECOGNIZED' and item['foreign']=='UNRECOGNIZED','unexpected non-selected source acceptance')
        sample={'owner':item,'postCleanupPackageUidProcesses':0};report['samples'][mode]=sample
        if mode in ('interrupt','reentry','reference','warm'):
            files='/data/data/'+PACKAGE+'/files'+('/qa-original' if mode in ('interrupt','reentry') else '')
            def proof(name):return json.loads(shell(CONTAINER,'cat "$1/state/client-work/$2/$3"',files,mode,name))
            sample['controlResult']=proof('control-result.json');sample['prefix']=proof('prefix-proof.json');wine_details(sample,mode)
        if mode=='reference':checked(item['before']=='ABSENT' and item['after']=='NO_REPAIR','fresh healthy classification failed')
        if mode in ('interrupt','reentry'):checked(item['after']=='INCOMPLETE','actual interrupted prefix failed classification')
        if mode=='clone':checked(item['after']=='INCOMPLETE' and item['copy']['originalTreeUnchanged'],'ineligible clone')
        if mode=='cancel':checked(item.get('nativeCancelled') and item.get('liveWinebootBeforeCancel') and item['competingLeaseDenied'] and item['pending'] and item['after']=='RESUME','cancelled updater/lease/pending recovery not proven')
        if mode=='update':checked(item.get('cutAfterGuestExitBeforePendingRetired') and item['pending'] and item['after']=='RESUME' and item['competingLeaseDenied'],'named recovery failed to return through verify')
        if mode=='finish':checked(item.get('handlerReturn') and not item['phases'] and item['after']=='NO_REPAIR' and not item['pending'],'side-effect-complete recovery did not retire pending once')
        if mode=='unknown':checked(item.get('handlerReturn') is False and item['phases']==['client-prefix-preserved'] and item['preservedUnknownMarker'] and item['unknownFileCount']==1 and not item['unknownPending'],'unknown prefix changed instead of allowing named provider repair')
        if mode=='noop':checked(item.get('handlerReturn') is False and not item['phases'],'unnecessary prefix repair')
        if mode in ('warm','reference'):checked(all(v['expectedValuePresent'] for v in sample['prefix']['registry'].values()),'real post-registration witnesses missing')
        if mode=='audit':checked(item['copy']['originalTreeUnchanged'] and item['copy']['sentinelRetained'],'source prefix changed')
    report['phase']='complete'


if __name__=='__main__':
    report=dict(scope='Dedicated fresh signed Android 13 ARM64 stock Wine first-use prefix and real cmd.exe, observed without UI action',phase='initial',
                reconstructedGruntTarget=False,actualWorldSession=False,graphicalLogin=False,physicalThor=False)
    start=time.monotonic()
    try:
        exercise(report)
    except Exception as error:
        report['errorType']=type(error).__name__
        if isinstance(error,RuntimeError):report['reason']=str(error)
        raise
    finally:
        report['elapsedSeconds']=round(time.monotonic()-start,3)
        Path(sys.argv[1]).write_text(json.dumps(report,indent=2)+'\n')
