"""Measure the signed Wine first-use loader, including setup children that outlive its first command."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time

NAMES = ('wineboot', 'rundll32', 'services.exe', 'winedevice', 'rpcss', 'msiexec',
         'appwiz.cpl', 'cmd.exe', 'wineserver', 'winemenubuilder')
PATTERNS = {
    'preInstall':b'installhinfsection preinstall', 'defaultInstall':b'installhinfsection defaultinstall',
    'wineInf':b'wine.inf','c0000135':b'c0000135', 'kernel32LoadFailure':b'could not load kernel32',
    'bootEventTimedOut':b'boot event wait timed out','rpcssFailed':b'failed to open rpcss',
    'deviceFailed':b'winedevice1 failed to start','monoInstaller':b'wine mono installer',
    'geckoInstaller':b'wine gecko installer','socketNameTooLong':b'file name too long',
    'socketPermission':b'permission denied','mapProtection':b'change protection',
    'appwizGecko':b'installwinegecko','appwizMono':b'installwinemono',
    'setupCopyFile':b'setup_install_file','ntMapViewFailure':b'ntmapviewofsection failed',
}
DLLS = ('kernel32.dll','kernelbase.dll','ntdll.dll','cmd.exe','rundll32.exe','gdi32.dll',
        'user32.dll','shell32.dll','wineboot.exe','services.exe')


def processes():
    result = set()
    for item in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            with item.open('rb') as f:
                command = f.read(1024).split(b'\x00',1)[0].lower()
            for name in NAMES:
                if name.encode() in command:
                    result.add(name)
        except OSError:
            continue
    return sorted(result)


def first_use(wine,env,prefix,out):
    system32=prefix/'drive_c/windows/system32'
    started=time.monotonic()
    observed=set()
    samples=[]
    commands=[]
    output_lock=threading.Lock()
    consumed=[0]
    trace_env={**env,'WINEDEBUG':'-all,err+all,+process,+setupapi,+module'}
    def pump(pipe):
        with pipe:
            while True:
                line=pipe.readline(8192)
                if not line: break
                low=line.lower()
                with output_lock:
                    consumed[0]+=len(line)
                    observed.update(key for key,token in PATTERNS.items() if token in low)
    def launch():
        p=subprocess.Popen([wine,'cmd.exe','/d','/c','ver'],env=trace_env,
                           stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        t=threading.Thread(target=pump,args=(p.stdout,),daemon=True)
        t.start()
        commands.append(p)
        return p
    def snapshot():
        age=int(time.monotonic()-started)
        try: members=list(system32.iterdir())
        except FileNotFoundError: members=[]
        images=sorted(n for n in DLLS if (system32/n).is_file())
        with output_lock:
            flags=sorted(observed)
            count=consumed[0]
        markers=dict(seconds=age,system32Entries=len(members),systemRegBytes=(prefix/'system.reg').stat().st_size
                     if (prefix/'system.reg').is_file() else 0,installed=images,
                     processes=processes(),traceMarkers=flags,traceBytes=count,
                     commandExits=[p.poll() for p in commands])
        samples.append(markers)
        tmp=out/'first-use.tmp'
        tmp.write_text(json.dumps(dict(samples=samples[-100:])))
        tmp.replace(out/'first-use.json')
        return markers
    try:
        p=launch()
        deadline=started+900
        while time.monotonic()<deadline:
            state=snapshot()
            code=p.poll()
            installers=set(state['processes']) & {'wineboot','rundll32'}
            if code==0 and not installers:
                if (system32/'kernel32.dll').is_file() and (prefix/'system.reg').is_file():
                    return
                raise RuntimeError('Windows command exited without installed prefix')
            if code is not None and len(commands)==1 and not installers:
                p=launch()
            elif code is not None and len(commands)==2 and not installers:
                raise RuntimeError('Windows first-use command exited twice')
            time.sleep(10)
        raise TimeoutError('Windows first-use or owned setup children exceeded observation')
    finally:
        for child in commands:
            if child.poll() is None:
                child.kill()
                child.wait()
        snapshot()
