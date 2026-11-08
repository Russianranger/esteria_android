"""Start and stop the APK's production MySQL twice on an offline, fresh Android package."""
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
    base='/data/data/'+PACKAGE+'/files/qa-signed-stock-database/state'
    raw=shell(CONTAINER,'''for f in "$1"/database-operations/*/logs/stderr.log; do
         if test -f "$f"; then tail -c 5000 "$f"; fi
     done''',base)
    matches=re.findall(r'Database setup failed \(([a-zA-Z0-9_:,;= -]{1,350})\)',raw)
    if matches:
        report['bootstrapDiagnostic']=matches[-1]
    raw=shell(CONTAINER,'''f="$1/server-work/state/logs/mysql-initialize-engine.log"
        if test -f "$f"; then tail -c 12000 "$f"; fi''',base)
    rows=[]
    for line in raw.splitlines():
        match=re.match(r'(\S+) .+?\[(MY-\d+)\].*',line)
        if match and match[2] in {'MY-013169','MY-013576','MY-013577'}:
            rows.append(dict(time=match[1],code=match[2]))
    report['initializationEvents']=rows


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
        result=subprocess.run(cmd,capture_output=True,text=True,timeout=18*60)
        phases=[line for line in result.stdout.splitlines() if re.fullmatch(r'ANDROID_DB_PHASE [a-z0-9_-]+ \d+',line)]
        report['lastPhases']=phases
        rows=[line.removeprefix('ANDROID_DB_RESULT ') for line in result.stdout.splitlines() if line.startswith('ANDROID_DB_RESULT ')]
        if result.returncode or len(rows)!=1:
            report['exitCode']=result.returncode
            report['exceptionClasses']=re.findall(r'^ANDROID_DB_EXCEPTION ([A-Za-z0-9_.]+)$',result.stderr,re.MULTILINE)
            failure_details(report)
            raise RuntimeError('signed database owner failed')
        item=json.loads(rows[0])
        checked(item['mode']==mode and item['closed'] and item['sameAuthenticatedInstance'] and
                re.fullmatch(r'[a-f0-9-]{36}',item['instanceUuid']),'invalid signed SQL result')
        if mode=='warm':
            first=report['operations'][0]
            checked(first['instanceUuid']==item['instanceUuid'] and first['providerGeneration']==item['providerGeneration'] and
                    item['providerCopiedBytes']==0,'warm persisted instance or provider changed')
        check_empty(CONTAINER,package_uid)
        report['operations'].append(item)
    report['phase']='complete'


if __name__=='__main__':
    report=dict(scope='signed Android 13 ARM64 MySQL setup and service only',phase='initial',
                actualWorldSession=False,physicalThor=False)
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
