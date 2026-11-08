"""Check the signed APK's Android package and launcher in the disposable native ARM64 runner."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

PACKAGE = 'io.github.russianranger.esteria.stock'
ACTIVITY = 'io.github.russianranger.esteria.MainActivity'
NAME = '0.1.0-non-custom.19'
SCOPE = 'disposable Android 13 signed v19 package lifecycle'


def require(value, message):
    if not value:
        raise RuntimeError(message)


def shell(container, script, *args, timeout=60):
    call = subprocess.run(['docker','exec','--user','0:0',container,'/system/bin/sh','-c',
                           'export PATH=/system/bin; set -eu\n' + script,'qa',*args],
                          capture_output=True,text=True,timeout=timeout,check=True)
    return call.stdout


def identity(container):
    result = shell(container,'dumpsys package "$1"',PACKAGE)
    require(re.search(r'^\s*versionCode=19\b',result,re.MULTILINE) and
            re.search(r'^\s*versionName='+re.escape(NAME)+r'\s*$',result,re.MULTILINE),
            'installed package version differs')
    package_list = shell(container,'pm list packages --user 0 -U "$1"',PACKAGE)
    match = re.search(r'^package:'+re.escape(PACKAGE)+r' uid:(\d+)\s*$',package_list,re.MULTILINE)
    require(match and 10_000 <= int(match[1]) < 100_000,'dedicated installed package UID required')
    return int(match[1])


def processes(container, uid):
    rows = shell(container,'ps -A -o PID,UID,NAME').splitlines()
    require(rows and rows[0].split()==['PID','UID','NAME'],'invalid Android process table')
    parsed=[]
    for row in rows[1:]:
        fields=row.split(None,2)
        require(len(fields)==3 and fields[0].isdecimal() and fields[1].isdecimal(),
                'numeric Android PID/UID observation required')
        parsed.append((int(fields[0]),int(fields[1]),fields[2]))
    require(any(pid==1 and owner==0 for pid,owner,_ in parsed),'Android init process is not visible')
    return [(pid,name) for pid,owner,name in parsed if owner==uid]


def check_empty(container, uid):
    deadline=time.monotonic()+20
    while True:
        owned=processes(container,uid)
        if not owned:
            return
        require(time.monotonic()<deadline,'Android package UID still owns processes')
        time.sleep(.5)


def exercise(container, report, check_only):
    inspection=json.loads(subprocess.check_output(['docker','inspect',container],text=True))[0]
    require(inspection['State']['Running'] and inspection['HostConfig']['NetworkMode']=='none',
            'disposable networkless Android container required')
    if check_only:
        require(report.get('scope')==SCOPE and report.get('launcherStopped'),
                'completed launcher observation required')
        uid=identity(container)
        require(uid==report['uid'],'installed UID changed')
        check_empty(container,uid)
        report.update(postShaderUidProcesses=0,postShaderOwnersReaped=True,phase='complete')
        return
    report.update(scope=SCOPE,package=PACKAGE,phase='package-installation',physicalThor=False,
                  gameplayQualified=False)
    require(shell(container,'pm list packages --user 0 "$1"',PACKAGE).strip()=='','fresh runtime required')
    output = shell(container,'''
        apk=/data/local/tmp/esteria-signed-stock-qa.apk
        test ! -e "$apk"
        trap 'rm -f "$apk"' EXIT
        cp /esteria-qa/input/stock.apk "$apk"
        chmod 644 "$apk"
        pm install -r --user 0 "$apk"
        ''',timeout=360)
    require('Success' in output.splitlines(),'package installation did not succeed')
    uid=identity(container)
    report.update(versionCode=19,versionName=NAME,uid=uid,phase='launcher')
    try:
        component=PACKAGE+'/'+ACTIVITY
        result = shell(container,'am start -W --user 0 -n "$1"',component,timeout=120)
        require(re.search(r'^Status: ok\s*$',result,re.MULTILINE),'Android launcher did not report success')
        # The legacy process NAME field can truncate an Android process; use exact argv[0] from the package PID.
        pids=shell(container,'pidof "$1"',PACKAGE).split()
        require(len(pids)==1 and pids[0].isdecimal(),'exact stock application process required')
        pid=int(pids[0])
        name=shell(container,'''tr '\\000' '\\n' <"/proc/$1/cmdline" | head -1''',str(pid)).strip()
        require(name==PACKAGE and any(p==pid for p,_ in processes(container,uid)),
                'launcher process UID or argv differs')
        report.update(launcherStatus='ok',launcherComponent=component,launcherPid=pid,launcherProcessVerified=True)
        wait=re.search(r'^WaitTime: (\d+)\s*$',result,re.MULTILINE)
        if wait:
            report['launcherWaitMs']=int(wait[1])
    finally:
        shell(container,'am force-stop --user 0 "$1"',PACKAGE)
    check_empty(container,uid)
    report.update(launcherStopped=True,postLauncherUidProcesses=0,phase='launcher-closed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container',choices=['esteria-android-qa'],required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--check-reaped',action='store_true')
    args=parser.parse_args()
    report=json.loads(args.report.read_bytes()) if args.check_reaped else {}
    try:
        exercise(args.container,report,args.check_reaped)
    except Exception as error:
        report.update(failureType=type(error).__name__)
        if isinstance(error,RuntimeError): report['reason']=str(error)
        print('Android package lifecycle failed in '+report.get('phase','container'),file=sys.stderr)
        return 1
    finally:
        args.report.write_text(json.dumps(report,indent=2)+'\n')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
