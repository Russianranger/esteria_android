"""Run Android framework shell commands in the boot environment of the offline Redroid fixture."""
from pathlib import Path
import re
import subprocess
import sys
import time

PACKAGE = 'io.github.russianranger.esteria.stock'
CONTAINER = 'esteria-android-qa'
BOOT = {'BOOTCLASSPATH', 'DEX2OATBOOTCLASSPATH', 'SYSTEMSERVERCLASSPATH', 'ANDROID_DATA',
        'ANDROID_ROOT', 'ANDROID_ART_ROOT', 'ANDROID_I18N_ROOT', 'ANDROID_TZDATA_ROOT',
        'ANDROID_RUNTIME_ROOT', 'ANDROID_SYSTEM_EXT_ROOT', 'ANDROID_VENDOR_ROOT', 'ANDROID_STORAGE', 'PATH'}


def shell(*command):
    return subprocess.check_output(['docker', 'exec', CONTAINER, *command], text=True).strip()


def platform_environment():
    # pidof can include newly forked children while they still carry the zygote title.
    # Android init owns the main zygote and its exported boot environment.
    for _ in range(10):
        for pid in shell('pidof', 'zygote64').split():
            if not re.fullmatch(r'[1-9][0-9]*', pid):
                continue
            try:
                status = shell('cat', f'/proc/{pid}/status')
                if not re.search(r'^PPid:\s+1$', status, re.M):
                    continue
                env = subprocess.check_output(['docker', 'exec', CONTAINER, 'cat', f'/proc/{pid}/environ'])
            except subprocess.CalledProcessError:
                continue
            values = [item.decode() for item in env.split(b'\0') if item.partition(b'=')[0].decode() in BOOT]
            if any(item.startswith('BOOTCLASSPATH=') for item in values):
                return values
        time.sleep(.25)
    raise RuntimeError('Android init-owned 64-bit zygote boot paths unavailable')


def android_tool(*command, timeout=90):
    result = subprocess.run(['docker', 'exec', CONTAINER, '/system/bin/env', *platform_environment(), *command],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{command[0]} returned {result.returncode}: {result.stdout[-1600:]}')
    return result.stdout


def interface_qualification(output):
    shell('pm', 'grant', PACKAGE, 'android.permission.POST_NOTIFICATIONS')
    android_tool('input', 'keyevent', 'KEYCODE_WAKEUP')
    shell('wm', 'dismiss-keyguard')
    result = android_tool('am', 'instrument', '-w', '-r', '-e', 'class',
                          'io.github.russianranger.esteria.RealmInterfaceTest',
                          PACKAGE + '.test/androidx.test.runner.AndroidJUnitRunner', timeout=150)
    Path(output).write_text(result)
    if 'OK (1 test)' not in result or 'INSTRUMENTATION_CODE: -1' not in result:
        raise RuntimeError('Android interface instrumentation failed: ' + result[-2400:])


if __name__ == '__main__':
    interface_qualification(sys.argv[1])
