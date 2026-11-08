"""Run signed stock shader preparation and fresh-owner admission on one disposable offline Android."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

PACKAGE = 'io.github.russianranger.esteria.stock'
ACTOR = '/data/data/' + PACKAGE + '/files/qa-signed-stock-shaders'
INPUT = '/esteria-qa/input'
META = '/esteria-qa/import-metadata'
RUNTIME_LOCK = Path(__file__).resolve().parents[2] / 'runtime/runtime-sources.lock.json'
BOOT_KEYS = {
    'BOOTCLASSPATH', 'DEX2OATBOOTCLASSPATH', 'SYSTEMSERVERCLASSPATH', 'ANDROID_DATA',
    'ANDROID_ROOT', 'ANDROID_ART_ROOT', 'ANDROID_I18N_ROOT', 'ANDROID_TZDATA_ROOT',
    'ANDROID_RUNTIME_ROOT', 'ANDROID_SYSTEM_EXT_ROOT', 'ANDROID_ODM_ROOT', 'ANDROID_PRODUCT_ROOT',
    'ANDROID_VENDOR_ROOT', 'ANDROID_STORAGE', 'PATH',
}


def checked(condition, message):
    if not condition:
        raise ValueError(message)


def run(*cmd, timeout=75):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True).stdout


def shell(container, script, *args, timeout=75):
    return run('docker', 'exec', '--user', '0:0', container, '/system/bin/sh', '-c',
               'export PATH=/system/bin; set -eu\n' + script, 'qa', *args, timeout=timeout)


def mount_state(container, path):
    canonical = shell(container,'readlink -f "$1"',path).strip()
    checked(canonical.startswith('/') and not any(ch.isspace() for ch in canonical),
            'canonical private mount path required')
    mounts = shell(container,'cat /proc/self/mountinfo').splitlines()
    selected = [line.split() for line in mounts if len(line.split()) > 6 and line.split()[4] == canonical]
    checked(len(selected) == 1 and 'ro' in selected[0][5].split(','),
            'read-only mount required for authenticated shader input')
    return selected[0][2], selected[0][3]


def pinned_archive():
    archive = json.loads(RUNTIME_LOCK.read_bytes())['packages']['wine-arm64']['archive']
    name, size, sha = archive['file'], archive['bytes'], archive['sha256']
    checked(re.fullmatch(r'[A-Za-z0-9._-]{1,128}', name) and 0 < size <= 2 ** 33 and
            re.fullmatch(r'[a-f0-9]{64}', sha), 'invalid selected Wine archive')
    key = hashlib.sha256(f'esteria-download-v1\n{name}\n{size}\n{sha}\n'.encode()).hexdigest()
    return key + '.archive', str(size), sha


def range_counts(path):
    return struct.unpack('<QQQ', path.read_bytes())


def range_delta(path, before):
    after = range_counts(path)
    result = [end - start for start, end in zip(before, after)]
    checked(min(result) >= 0 and result[2] == 0, 'input guard recorded a changed source or a refused read')
    return dict(grantedCalls=result[0], grantedBytes=result[1], denied=result[2])


def exercise(container, report, range_counters, repair_report=None):
    inspected = json.loads(run('docker','inspect',container))[0]
    checked(inspected['State']['Running'] and inspected['HostConfig']['NetworkMode'] == 'none',
            'disposable Android must be running offline')
    report['phase'] = 'android-package'
    checked(shell(container,'getprop ro.build.version.sdk').strip() == '33' and
            shell(container,'getprop ro.product.cpu.abi').strip() == 'arm64-v8a', 'Android 13 ARM64 required')
    apk = shell(container,'pm path "$1"', PACKAGE).strip()
    match = re.fullmatch(r'package:(/data/app/[A-Za-z0-9_./=+~-]+/base\.apk)', apk)
    checked(match, 'installed stock package base APK required')
    apk = match[1]
    uid = shell(container,'stat -c %u "$1"', '/data/data/' + PACKAGE).strip()
    checked(uid.isdecimal() and 10_000 <= int(uid) < 100_000, 'stock package UID required')
    source = shell(container,'cat "$1/current"',META).strip()
    checked(re.fullmatch(r'[a-f0-9]{64}', source), 'invalid selected import')
    target = ACTOR + '/game/generations/' + source + '/data'
    cache_file, size, sha = pinned_archive()
    boot = shell(container, "set -- $(pidof zygote64); test $# -eq 1; tr '\\000' '\\n' </proc/$1/environ")
    selected = dict(item.split('=',1) for item in boot.splitlines() if '=' in item and
                    item.split('=',1)[0] in BOOT_KEYS)
    checked('BOOTCLASSPATH' in selected and 'ANDROID_ROOT' in selected, 'Android ART boot environment missing')
    mounted = False
    invocation_active = False
    try:
        report['phase'] = 'prepare-private-actor'
        shell(container,'''
            root=$1; uid=$2; selected=$3; source=$4; name=$5
            step=actor-precondition
            trap 'rc=$?; test "$rc" = 0 || echo "QA_ACTOR_STEP $step $rc" >&2' EXIT
            umask 077
            test ! -e "$root"
            if test -e "${root%/*}"; then
                test -d "${root%/*}" && test "$(stat -c %u "${root%/*}")" = "$uid"
            else
                mkdir "${root%/*}"
                chown "$uid:$uid" "${root%/*}"
            fi
            step=actor-mkdir
            mkdir "$root"
            dst="$root/game/generations/$selected"
            mkdir -p "$dst/data" "$root/runtime-downloads"
            step=import-metadata
            cp "$source/current" "$root/game/current"
            for file in journal.tsv complete; do cp "$source/generations/$selected/$file" "$dst/$file"; done
            step=archive-file-size
            archive="$root/runtime-downloads/$name"
            test "$(stat -c %s /esteria-qa/input/wine.tar.gz)" = "$6"
            step=seed-verified-download
            cp /esteria-qa/input/wine.tar.gz "$archive"
            step=actor-ownership
            chown -R "$uid:$uid" "$root"
            test "$(cat "$root/game/current")" = "$selected"
            ''', ACTOR,uid,source,META,cache_file,size,timeout=300)
        report['phase'] = 'verified-source-mount'
        source_mount = mount_state(container,'/esteria-qa/mpq')
        report['phase'] = 'bind-private-import'
        shell(container,'mount -o bind /esteria-qa/mpq "$1"',target)
        mounted = True
        report['phase'] = 'verify-private-import-mount'
        # Linux inherits the mount flags from the read-only FUSE source. Android 13's
        # mount utility refuses a redundant remount on this private bind alias.
        checked(mount_state(container,target) == source_mount, 'private bind mount differs from guarded input')
        inode = shell(container,'stat -c "%d %i" /esteria-qa/mpq "$1"',target).splitlines()
        checked(len(inode)==2 and inode[0]==inode[1], 'private bind root identity differs')
        shell(container,'test -d "$1/Data"',target)
        report.update(importGeneration=source, packageUid=int(uid), abi='arm64-v8a', sdk=33,
                      wineArchiveSha256=sha, package=PACKAGE, operations=[])
        report['phase'] = 'signed-android-owner'
        native = apk.rsplit('/',1)[0] + '/lib/arm64'
        command_prefix = ['docker','exec','--user',uid+':'+uid,container,'/system/bin/env','-i']
        command_prefix += [k+'='+v for k,v in selected.items()]
        command_prefix += ['CLASSPATH='+INPUT+'/driver.jar:'+apk,'/system/bin/app_process64',
                           '-Djava.library.path='+native+':/system/lib64','/system/bin']
        if os.environ.get('ESTERIA_LEGACY_SHADER_REPAIR')=='true':
            import historical_owner
            invocation_active = True
            historical_owner.exercise(sys.modules[__name__],container,uid,source,apk,command_prefix,range_counters,report)
            invocation_active = False
            return
        for mode in ('cold','warm'):
            report['phase'] = mode
            command = [*command_prefix, 'io.github.russianranger.esteria.runtime.ConfirmShader', mode, source]
            before = range_counts(range_counters)
            invocation_active = True
            completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, timeout=145*60 if mode == 'cold' else 10*60)
            # Keep the full output inside the runner. Emit only the known structured result and fixed phase labels.
            rows = [line.removeprefix('ANDROID_SHADER_RESULT ') for line in completed.stdout.splitlines()
                    if line.startswith('ANDROID_SHADER_RESULT ')]
            phases = [line for line in completed.stdout.splitlines() if
                      re.fullmatch(r'ANDROID_SHADER_PHASE [a-z][a-z0-9-]{0,63} [0-9]+',line)]
            report['observedPhases'] = phases[-30:]
            if completed.returncode or len(rows)!=1:
                # Source exceptions may include local content paths. Report their safe class and helper only.
                errors = re.findall(r'(?:Caused by: |^)([a-zA-Z_][a-zA-Z0-9_.]+(?:Exception|Error))\b',
                                    completed.stdout,re.MULTILINE)
                errors += re.findall(r'^ANDROID_SHADER_EXCEPTION ([a-zA-Z0-9_.]+)$',
                                     completed.stdout,re.MULTILINE)
                report['exceptionClasses'] = errors[-8:]
                raise RuntimeError('Android shader owner failed, exit '+str(completed.returncode))
            invocation_active = False
            result = json.loads(rows[0])
            result['authenticatedInput'] = range_delta(range_counters, before)
            if mode == 'cold':
                checked(result['authenticatedInput']['grantedBytes'] > 0, 'cold build did not read authenticated input')
            checked(result['mode']==mode and result['importGeneration']==source and
                    re.fullmatch('[a-f0-9]{64}',result['generation']) and result['files']==4742 and
                    result['modules']==1580 and result['ownerClosed'] and result['sessionReceiptAdmitted'],
                    'signed shader admission result differs')
            receipt = ACTOR+'/state/shader-work/shaders/generations/'+result['generation']+'/receipt.json'
            digest = shell(container,'sha256sum "$1"',receipt).split()[0]
            stamp = shell(container,'stat -c "%d %i %s %Y" "$1"',receipt).strip()
            checked(re.fullmatch(r'[a-f0-9]{64}',digest) and re.fullmatch(r'\d+ \d+ \d+ \d+',stamp),
                    'shader receipt observation invalid')
            result.update(receiptSha256=digest,receiptStat=stamp)
            if mode == 'warm':
                first = report['operations'][0]
                for field in ('generation','bytes','receiptSha256','receiptStat','wineGeneration','toolsGeneration'):
                    checked(result[field]==first[field], 'warm receipt/provider changed')
                checked(not result['ownedTranslatorLaunched'] and
                        result['wineCopiedBytes']==result['toolsCopiedBytes']==0,'warm owner repeated preparation')
            else:
                checked(result['ownedTranslatorLaunched'] and min(result['wineCopiedBytes'],result['toolsCopiedBytes'])>0,
                        'cold execution and fresh provider install required')
            report['operations'].append(result)
        if repair_report is not None:
            from repair_owner import run_repair
            report['phase'] = 'installed-named-shader-repair'
            invocation_active = True
            before = range_counts(range_counters)
            cold = report['operations'][0]
            repaired = run_repair(container, command_prefix, source, cold['generation'], repair_report)
            checked(repaired['initialReceipt'] == cold['receiptSha256'], 'repair began from a different shader receipt')
            report['namedRepairAuthenticatedInput'] = range_delta(range_counters, before)
            invocation_active = False
        report['phase'] = 'complete'
    finally:
        if invocation_active:
            # docker exec timing out/killed does not ensure the Android grandchildren have exited.
            subprocess.run(['docker','stop','--time','8',container],stdout=subprocess.DEVNULL,check=True,timeout=40)
        elif mounted:
            shell(container,'umount "$1"',target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container',required=True,choices=('esteria-android-qa',))
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--range-counters', type=Path, required=True)
    parser.add_argument('--repair-report', type=Path, help='exercise named repair after verified cold and warm admission')
    args = parser.parse_args()
    report = dict(formatVersion=1,scope='offline signed Android stock shader owner',phase='container',
                  physicalThor=False,gameplayQualified=False)
    start=time.monotonic()
    try:
        exercise(args.container, report, args.range_counters, args.repair_report)
    except Exception as error:
        report['failureType']=type(error).__name__
        if isinstance(error,subprocess.CalledProcessError):
            report['exitCode'] = error.returncode
            diagnostic = error.stderr or ''
            at = re.search(r'^QA_ACTOR_STEP ([a-z-]+) ([0-9]+)$',diagnostic,re.MULTILINE)
            if at: report['actorStep'] = at[1]
            for note in ('Permission denied','Read-only file system','No such file or directory',
                         'not in /proc/mounts','No space left on device','Operation not permitted'):
                if note in diagnostic: report['reason'] = note; break
        elif isinstance(error,(RuntimeError,ValueError)):
            report['reason']=str(error)[:160]
        print('Android shader qualification failed in '+report['phase']+' ('+type(error).__name__+
              ', '+report.get('actorStep','')+' '+report.get('reason','')+')',file=sys.stderr)
        return 1
    finally:
        report['elapsedSeconds']=round(time.monotonic()-start,3)
        args.report.write_text(json.dumps(report,indent=2)+'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
