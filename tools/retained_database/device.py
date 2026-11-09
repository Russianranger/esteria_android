"""Run only the signed installed package's classes in new processes under its own UID."""
import json
from pathlib import Path
import re
import subprocess
import sys

from android_platform import CONTAINER, PACKAGE, interface_qualification, platform_environment, shell


def install(name, version):
    path = '/data/local/tmp/esteria-signed-update.apk'
    shell('cp', '/esteria-qa/input/' + name, path)
    shell('chmod', '644', path)
    assert 'Success' in shell('pm', 'install', '-r', '--user', '0', path).splitlines()
    package = shell('dumpsys', 'package', PACKAGE)
    assert re.search(r'^\s*versionCode=' + str(version) + r'\b', package, re.M)
    apk = shell('pm', 'path', PACKAGE).removeprefix('package:')
    assert re.fullmatch(r'/data/app/[A-Za-z0-9_./=+~-]+/base\.apk', apk)
    digest = shell('sha256sum', apk).split()[0]
    assert re.fullmatch(r'[a-f0-9]{64}', digest) and digest == shell('sha256sum', path).split()[0]
    uid = installed_uid()
    with Path(sys.argv[1]).open('a') as out:
        out.write(json.dumps({'phase': 'installed', 'versionCode': version, 'uid': int(uid),
                              'installedApkSha256': digest}) + '\n')
    return uid


def installed_uid():
    uid = shell('stat', '-c', '%u', '/data/user/0/' + PACKAGE)
    assert uid.isdecimal() and 10000 <= int(uid) < 100000
    return uid


def run(phase, uid):
    shell('cmd', 'activity', 'force-stop', PACKAGE)
    apk = shell('pm', 'path', PACKAGE).removeprefix('package:')
    assert re.fullmatch(r'/data/app/[A-Za-z0-9_./=+~-]+/base\.apk', apk)
    native = apk.rsplit('/', 1)[0] + '/lib/arm64'
    boot = platform_environment()
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
    if sys.argv[2:] == ['interface']:
        interface_qualification(sys.argv[1])
        sys.exit(0)
    if sys.argv[2:] == ['debug']:
        uid = installed_uid()
        for phase in ('debug-seed', 'debug-repair', 'debug-cold', 'debug-cold', 'debug-cold'):
            run(phase, uid)
        sys.exit(0)
    if sys.argv[2:] in (['v23'], ['v24']):
        candidate = int(sys.argv[2][1:])
        old = install('previous.apk', candidate - 1)
        run('seed-providers', old)
        run('prepare-baseline', old)
        assert install('candidate.apk', candidate) == old
        run('reopen' + str(candidate), old)
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
