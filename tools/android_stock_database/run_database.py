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


def wine_details(report, mode):
    root='/data/data/'+PACKAGE+'/files'
    # Private Wine and PE logs may contain memory dumps. Export only controlled status fields.
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
    scenario=os.environ['ESTERIA_WINE_CONTROL'];assert scenario=='early-proof'
    pending=['interrupt']
    report['samples']={}; reference=None
    while pending:
        mode=pending.pop(0);report['phase']=mode
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
        check_empty(CONTAINER,package_uid)
        report['postCleanupPackageUidProcesses']=0
        report['operations'].append(item)
        args=('/data/data/'+PACKAGE+'/files',mode)
        def proof(name):
            return json.loads(shell(CONTAINER,'cat "$1/state/client-work/$2/$3"',*args,name))
        selected=proof('control-result.json');prefix=proof('prefix-proof.json')
        sample={'controlResult':selected,'prefix':prefix,'postCleanupPackageUidProcesses':0}
        wine_details(sample,mode);report['samples'][mode]=sample
        if mode=='interrupt':
            assert selected['confirmedMonoInterruption'] and prefix['after']['markerHash']
            reference=prefix['after']
        if mode=='reentry':
            before=prefix['before'];after=prefix['after']
            assert all(before[k]==after[k]==reference[k] for k in ('prefixInode','markerHash','markerInode'))
            pending.extend(['warm'] if all(v['expectedValuePresent'] for v in prefix['registry'].values()) else ['copy-force','copy-warm'])
        if mode.startswith('copy-'):
            assert prefix['originalPrefixAuditUnchanged'] and prefix['after']['markerHash']==reference['markerHash']
        if mode in ('reference','copy-force','copy-warm','warm'):
            checked(all(v['expectedValuePresent'] for v in prefix['registry'].values()),'post-registration registry witness missing')
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
