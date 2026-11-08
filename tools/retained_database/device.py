"""Run only the signed installed package's classes in new processes under its own UID."""
import json
from pathlib import Path
import re
import subprocess
import sys

PACKAGE = 'io.github.russianranger.esteria.stock'
CONTAINER = 'esteria-android-qa'
BOOT = {'BOOTCLASSPATH', 'DEX2OATBOOTCLASSPATH', 'SYSTEMSERVERCLASSPATH', 'ANDROID_DATA',
        'ANDROID_ROOT', 'ANDROID_ART_ROOT', 'ANDROID_I18N_ROOT', 'ANDROID_TZDATA_ROOT',
        'ANDROID_RUNTIME_ROOT', 'ANDROID_SYSTEM_EXT_ROOT', 'ANDROID_ODM_ROOT', 'ANDROID_PRODUCT_ROOT',
        'ANDROID_VENDOR_ROOT', 'ANDROID_STORAGE', 'PATH'}


def shell(*command):
    return subprocess.check_output(['docker', 'exec', CONTAINER, *command], text=True).strip()


def install(name, version):
    path = '/data/local/tmp/esteria-signed-update.apk'
    shell('cp', '/esteria-qa/input/' + name, path)
    shell('chmod', '644', path)
    assert 'Success' in shell('pm', 'install', '-r', '--user', '0', path).splitlines()
    package = shell('dumpsys', 'package', PACKAGE)
    assert re.search(r'^\s*versionCode=' + str(version) + r'\b', package, re.M)
    return installed_uid()


def installed_uid():
    uid = shell('stat', '-c', '%u', '/data/user/0/' + PACKAGE)
    assert uid.isdecimal() and 10000 <= int(uid) < 100000
    return uid


def run(phase, uid):
    shell('cmd', 'activity', 'force-stop', PACKAGE)
    apk = shell('pm', 'path', PACKAGE).removeprefix('package:')
    assert re.fullmatch(r'/data/app/[A-Za-z0-9_./=+~-]+/base\.apk', apk)
    native = apk.rsplit('/', 1)[0] + '/lib/arm64'
    zygote = shell('pidof', 'zygote64')
    assert re.fullmatch('[1-9][0-9]*', zygote)
    environment = subprocess.check_output(['docker', 'exec', CONTAINER, 'cat', f'/proc/{zygote}/environ'])
    boot = [item.decode() for item in environment.split(b'\0') if item.partition(b'=')[0].decode() in BOOT]
    assert any(item.startswith('BOOTCLASSPATH=') for item in boot)
    classpath = '/esteria-qa/input/observer.jar:' + apk
    if phase.startswith('debug-'):
        test_apk = shell('pm', 'path', PACKAGE + '.test').removeprefix('package:')
        assert re.fullmatch(r'/data/app/[A-Za-z0-9_./=+~-]+/base\.apk', test_apk)
        classpath += ':' + test_apk
    command = ['docker', 'exec', '--user', f'{uid}:{uid}', CONTAINER, '/system/bin/env', '-i', *boot,
               'CLASSPATH=' + classpath, '/system/bin/app_process64',
               '-Djava.library.path=' + native + ':/system/lib64', '/system/bin',
               'io.github.russianranger.esteria.runtime.SignedDatabaseUpdate', phase]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1500)
    lines = [row[:1200] for row in result.stdout.splitlines() if row.startswith('ESTERIA_')]
    with Path(sys.argv[1]).open('a') as out:
        out.write(json.dumps({'phase': phase, 'uid': int(uid), 'returnCode': result.returncode, 'observed': lines}) + '\n')
    if result.returncode or 'ESTERIA_RESULT ' + phase + ' success' not in lines:
        for line in lines[-24:]:
            print(line)
        raise RuntimeError('installed APK observer failed at ' + phase)


if __name__ == '__main__':
    if sys.argv[2:] == ['debug']:
        uid = installed_uid()
        for phase in ('debug-seed', 'debug-repair', 'debug-cold', 'debug-cold', 'debug-cold'):
            run(phase, uid)
        sys.exit(0)
    if sys.argv[2:] == ['v23']:
        old = install('previous.apk', 22)
        run('seed21', old)  # Existing provider seeding fixture shared by modern baselines.
        run('baseline22', old)
        assert install('candidate.apk', 23) == old
        run('reopen23', old)
        sys.exit(0)
    if sys.argv[2:] == ['v22']:
        old = install('previous.apk', 21)
        run('seed21', old)
        run('masked21', old)
        new = install('candidate.apk', 22)
        assert new == old
        run('primary22', new)
        run('repair22', new)
        run('cold22', new)
        sys.exit(0)
    old = install('previous.apk', 19)
    run('seed19', old)
    run('fail19', old)
    new = install('candidate.apk', 21)
    assert old == new
    run('repair21', new)
    for _ in range(3):
        run('cold21', new)
