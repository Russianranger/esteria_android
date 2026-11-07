#!/usr/bin/env python3
"""Exercise the two signed stock APKs on a fresh disposable Android 13 emulator."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import time

import sign_android_apk as signing


ROOT = signing.ROOT
OUTPUT = ROOT / 'out/detached-publication'
PACKAGE = signing.STOCK_PACKAGE
ACTIVITY = PACKAGE + '/io.github.russianranger.esteria.MainActivity'


def adb(*args, check=True):
    process = subprocess.run(['adb', *map(str, args)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
    if check and process.returncode:
        raise RuntimeError(str(args[0]) + ' failed: ' + process.stdout[-1800:])
    return process.returncode, process.stdout.strip()


def shell(command):
    return adb('shell', command)[1]


def installed(expected):
    output = shell('dumpsys package ' + PACKAGE)
    version = re.search(r'^\s*versionCode=(\d+)\b', output, re.M)
    directory = re.search(r'^\s*dataDir=(\S+)\s*$', output, re.M)
    uid = re.fullmatch(r'package:' + re.escape(PACKAGE) + r' uid:(\d+)',
                       shell('pm list packages -U --user 0 ' + PACKAGE))
    assert version and int(version[1]) == expected['versionCode'] and directory and uid, 'Package Manager metadata'
    assert directory[1] in ('/data/user/0/' + PACKAGE, '/data/data/' + PACKAGE) and int(uid[1]) >= 10000
    path = re.fullmatch(r'package:(/data/app/[a-zA-Z0-9_./=+~-]+/base\.apk)', shell('pm path ' + PACKAGE))
    assert path, 'one installed base APK required'
    digest = shell('sha256sum ' + shlex.quote(path[1])).split()[0]
    assert digest == expected['apkSha256'], 'installed APK differs from independently verified bytes'
    return dict(package=PACKAGE, versionCode=int(version[1]), uid=int(uid[1]), dataDir=directory[1], apkSha256=digest)


def launch():
    shell('pm grant ' + PACKAGE + ' android.permission.POST_NOTIFICATIONS')
    output = shell('am start -W -n ' + ACTIVITY)
    assert 'Status: ok' in output.splitlines() and 'Error:' not in output, output
    for _ in range(15):
        _, resumed = adb('shell', 'dumpsys activity activities | grep -E "mResumedActivity|topResumedActivity"', check=False)
        if ACTIVITY in resumed and adb('shell', 'pidof ' + PACKAGE, check=False)[1]:
            return
        time.sleep(1)
    raise RuntimeError('The signed launcher did not remain resumed')


def fixture_files(nonce):
    # Use the on-device directory layout with fresh fixture-only generation/slot IDs.
    generation = hashlib.sha256(nonce.encode()).hexdigest()
    slot = generation[:16]
    locations = {
        'import': f'game/generations/{generation}/data/Data',
        'preparedWorld': f'server-data-work/server-data/generations/{generation}/data/maps',
        'preparedShaders': f'state/shader-work/shaders/generations/{generation}/shaders/vertex',
        'clientConfiguration': 'state/client-work/client-state/WTF',
        'databaseIdentity': f'db/{slot}/state/database',
        'characterSaveStorage': f'db/{slot}/state/database/acore_characters',
    }
    return {name: f'{directory}/signed-update-{nonce}.fixture' for name, directory in locations.items()}


def check_update(receipt):
    old = Path(os.environ['RUNNER_TEMP']) / 'signed-stock-baseline.apk'
    new = OUTPUT / 'release/Esteria-Stock-3.3.5a-arm64.apk'
    release = json.loads((OUTPUT / 'release/release.json').read_text())
    lock = signing.load_lock(ROOT / 'app/stock-signing.lock.json')
    tools = signing.sdk_tools(Path(os.environ['ANDROID_HOME']) / 'build-tools/35.0.0')
    assert lock['packageId'] == PACKAGE
    baseline = lock['lastPublished']
    before = signing.verify(old, tools, lock, baseline['versionCode'])
    after = signing.verify(new, tools, lock, release['signedApk']['versionCode'])
    assert before['apkSha256'] == baseline['apkSha256'] and after == release['signedApk'], 'exact signed APKs'
    assert after['versionCode'] > before['versionCode']
    receipt.update(sourceCommit=release['appRevision'], baselineApk=before, updateApk=after)
    assert re.fullmatch(r'emulator-\d+', adb('get-serialno')[1]), 'disposable local emulator required'
    assert shell('getprop ro.kernel.qemu') == '1' and shell('getprop ro.build.version.sdk') == '33'
    abis = shell('getprop ro.product.cpu.abilist').split(',')
    receipt.update(emulatorAbis=abis, buildFingerprint=shell('getprop ro.build.fingerprint'))
    adb('root')
    adb('wait-for-device')
    assert shell('id -u') == '0', 'rooted emulator required'
    assert 'package:' + PACKAGE not in shell('pm list packages --user 0 ' + PACKAGE).splitlines(), 'fresh package required'
    status, output = adb('install', old, check=False)
    if status and 'arm64-v8a' not in abis and 'INSTALL_FAILED_NO_MATCHING_ABIS' in output:
        receipt.update(status='skipped-incompatible-emulator-abi', installDiagnostic=output[-1200:])
        print('::warning::The emulator rejected normal installation of the production ARM64 APK. Signed update execution remains unqualified.')
        return
    assert status == 0 and 'Success' in output.splitlines(), 'baseline install failed: ' + output
    previous = installed(before)
    receipt['before'] = previous
    launch()
    receipt['signedLauncherResumedBeforeUpdate'] = True
    shell('am force-stop ' + PACKAGE)
    nonce = secrets.token_hex(12)
    files = fixture_files(nonce)
    expected = {}
    for name, relative in files.items():
        value = f'Esteria emulator-only signed update fixture {name} {nonce}'
        expected[name] = hashlib.sha256(value.encode()).hexdigest()
        path = str(Path(previous['dataDir']) / 'files' / relative)
        command = f'umask 077; mkdir -p {shlex.quote(str(Path(path).parent))} && test ! -e {shlex.quote(path)} && printf %s {shlex.quote(value)} > {shlex.quote(path)}'
        shell('su ' + str(previous['uid']) + ' sh -c ' + shlex.quote(command))

    def observe(package):
        observed = {}
        for name, relative in files.items():
            path = shlex.quote(str(Path(package['dataDir']) / 'files' / relative))
            owner, digest = shell('stat -c %u ' + path + ' && sha256sum ' + path).splitlines()
            assert int(owner) == package['uid'] and digest.split()[0] == expected[name], relative
            observed[name] = dict(path=relative, uid=int(owner), sha256=digest.split()[0])
        return observed

    receipt['fixturesBefore'] = observe(previous)
    _, output = adb('install', '-r', new)
    assert 'Success' in output.splitlines(), output
    current = installed(after)
    receipt.update(after=current, packageManagerUpdateExecuted=True)
    assert (current['uid'], current['dataDir']) == (previous['uid'], previous['dataDir'])
    launch()
    receipt['signedLauncherResumedAfterUpdate'] = True
    receipt['fixturesAfter'] = observe(current)
    assert receipt['fixturesBefore'] == receipt['fixturesAfter']
    receipt['status'] = 'passed'


if __name__ == '__main__':
    evidence = dict(formatVersion=1, scope='android13-emulator-signed-apk-filesystem-update',
                    status='failed', packageManagerUpdateExecuted=False, fixtureDataOnly=True,
                    databaseSchemaQualified=False, characterPersistenceQualified=False, thorQualified=False,
                    gameplayQualified=False)
    try:
        check_update(evidence)
    except Exception as error:
        evidence['failure'] = str(error)[-1600:]
        raise
    finally:
        (OUTPUT / 'signed-update-android13.json').write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')
        print('Android package update result:', evidence['status'])
