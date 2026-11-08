"""Start and stop the APK's production MySQL twice on an offline, fresh Android package."""
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


def failure_details(report):
    root='/data/data/'+PACKAGE+'/files'
    # Private Wine and PE logs may contain memory dumps. Export only controlled status fields.
    report['winePhases']=[]
    diagnostics=shell(CONTAINER,'''for f in "$1"/qa-grunt/*/phase.json "$1"/db/*/qa-grunt/*/phase.json; do
        if test -f "$f"; then cat "$f"; echo; fi
    done''',root)
    for line in diagnostics.splitlines():
        item=json.loads(line)
        if item.get('phase') in {'display','wineboot','windows-prefix-command','prefix-ready','wait-owned-authserver',
                                'reconstructed-grunt','grunt-exited'}:
            allowed={'elapsedMs':int,'returnCode':int,'loaderStatus135':bool,'kernel32Mentioned':bool,
                     'prefixKernel32':bool,'prefixWineboot':bool}
            report['winePhases'].append(dict(phase=item['phase'],**{k:item[k] for k,t in allowed.items()
                                               if k in item and type(item[k]) is t}))
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
    for mode in ('cold','warm'):
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
        item=json.loads(rows[0])
        checked(item['mode']==mode and item['closed'] and item['sameAuthenticatedInstance'] and
                re.fullmatch(r'[a-f0-9-]{36}',item['instanceUuid']),'invalid signed SQL result')
        auth=item['auth']
        checked(auth['build']==12340 and all(auth[k] is True for k in ('sourceChallenge','ownedListener','srpAndRealmList','mysqlKeyMatched','authserverExitedCleanly')) and
                auth['worldAddress']=='127.0.0.1:8085','incomplete authserver handshake')
        checked(auth['gruntChecks']==13 and re.fullmatch(r'[a-f0-9]{64}',auth['clientReceiptSha256']) and
                auth['commonMainStarted'] is False and auth['assetsLoaded'] is False, 'incomplete actual PE receipt')
        if mode=='warm':
            first=report['operations'][0]
            checked(first['auth']['clientReceiptSha256']!=auth['clientReceiptSha256'], 'same challenge receipt')
            checked(first['instanceUuid']==item['instanceUuid'] and all(first[k]==item[k] for k in ('providerGeneration','programsGeneration','contentGeneration','slotId','promotionProof','setupReceipt')) and
                    item['providerCopiedBytes']==0,'warm persisted instance or provider changed')
        check_empty(CONTAINER,package_uid)
        report['operations'].append(item)
    report['phase']='complete'


if __name__=='__main__':
    report=dict(scope='signed Android 13 ARM64 production slot, stock SQL/updater/four schemas and owned MySQL, disjoint empty world-data directory for config path',phase='initial',
                reconstructedGruntTarget=True,actualWorldSession=False,graphicalLogin=False,physicalThor=False)
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
