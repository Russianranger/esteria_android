"""Package-private signed Wine guest. Only closed-set milestones and loader diagnostics leave Android."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import wine_prefix

work = Path('/work')
mode = sys.argv[1]
assert mode in {'cold', 'warm'}
os.umask(0o077)
out = work / mode
out.mkdir(mode=0o700, exist_ok=False)
start = time.monotonic()
env = {**os.environ, 'DISPLAY': ':77', 'WINEPREFIX': '/work/home/.wine',
       'WINEDLLOVERRIDES':'winepulse.drv=', 'WINEESYNC':'0', 'WINEFSYNC':'0',
       'WINEDEBUG': '-all,err+all'}
prefix = Path(env['WINEPREFIX'])
wine = '/opt/wine/bin/wine'
server = '/opt/wine/bin/wineserver'


def status(phase, **fields):
    data = dict(phase=phase, elapsedMs=int((time.monotonic()-start)*1000), **fields)
    temp = out / 'phase.tmp'
    temp.write_text(json.dumps(data))
    temp.replace(out / 'phase.json')


def checked(phase, command, timeout):
    status(phase)
    path = out / (phase+'.private.log')
    with path.open('xb') as log:
        rc = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout).returncode
    if rc:
        with path.open('rb') as log:
            sample = log.read(1 << 20).lower()
        status(phase, returnCode=rc, loaderStatus135=b'c0000135' in sample,
               kernel32Mentioned=b'kernel32' in sample,
               prefixKernel32=(prefix/'drive_c/windows/system32/kernel32.dll').is_file(),
               prefixWineboot=(prefix/'drive_c/windows/system32/wineboot.exe').is_file())
        raise RuntimeError('signed guest command failed')


def run():
    assert env['HOME']=='/work/home' and env['WINE_ANDROID_PRIVATE_PE_COPY']=='1'
    if mode=='cold':
        assert not prefix.exists()
    else:
        assert (prefix/'system.reg').is_file()
    status('display')
    with (out/'display.private.log').open('xb') as log:
        x = subprocess.Popen(['/usr/bin/Xtigervnc',env['DISPLAY'],'-geometry','1920x1080','-depth','24',
                              '-rfbport','-1','-SecurityTypes','None','-nolisten','tcp','-ac'],
                             env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+25
            sock = Path('/tmp/.X11-unix/X77')
            while x.poll() is None and time.monotonic()<deadline:
                if sock.exists() and stat.S_ISSOCK(sock.lstat().st_mode): break
                time.sleep(.1)
            else: raise RuntimeError('private X11 startup failed')
            status('wait-owned-authserver')
            deadline = time.monotonic()+110
            while time.monotonic()<deadline:
                if (work/('ready-'+mode+'.json')).is_file(): break
                time.sleep(.1)
            else: raise RuntimeError('credential handoff not ready')
            command=[wine,r'Z:\work\bin\WowClient64.exe','--auth-check','--local-offline']
            if mode=='cold':
                status('reconstructed-grunt-first-use')
                wine_prefix.observe(command,env,prefix,out)
            else:
                checked('reconstructed-grunt',command,120)
        finally:
            try:
                for flag in ('-k','-w'):
                    result = subprocess.run([server,flag],env=env,stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL,timeout=30)
                    if result.returncode not in (0,1): raise RuntimeError('wineserver cleanup failed')
            finally:
                if x.poll() is None: x.terminate()
                try: x.wait(10)
                except subprocess.TimeoutExpired:
                    x.kill()
                    x.wait()
                    raise
    status('grunt-exited')
    (out/'exited').touch(exist_ok=False)


if __name__=='__main__':
    run()
