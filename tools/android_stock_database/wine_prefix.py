"""Measure the signed Wine first-use loader, including setup children that outlive its first command."""
import hashlib
import re
import json
try:
    from . import wine_windows
except ImportError:
    import wine_windows
import os
from pathlib import Path
import subprocess
import threading
import time

NAMES = ('wineboot', 'rundll32', 'services.exe', 'winedevice', 'rpcss', 'msiexec',
         'appwiz.cpl', 'cmd.exe', 'wowclient64.exe', 'wineserver', 'winemenubuilder')
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
    waits = {}
    for item in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            with item.open('rb') as f:
                command = f.read(1024).split(b'\x00',1)[0].lower()
            for name in NAMES:
                if name.encode() in command:
                    result.add(name)
                    if name in ('rundll32','wineboot'):
                        channels=[]
                        for path in (item.parent/'task').glob('[0-9]*/wchan'):
                            try:
                                w=path.read_text().strip()
                            except OSError:
                                w='unreadable'
                            if w not in ('0','unreadable','futex_wait_queue','futex_wait_queue_me','ep_poll','do_poll',
                                         'do_select','unix_stream_read_generic','ptrace_stop','do_wait','wait_woken',
                                         'pipe_read','__arm64_sys_ppoll','hrtimer_nanosleep','epoll_wait'):
                                w='sha256:'+hashlib.sha256(w.encode()).hexdigest()
                            channels.append(w)
                        waits[item.parent.name]={'name':name,'waits':sorted(set(channels))}

        except OSError:
            continue
    return sorted(result),waits


def observe(command,env,prefix,out):
    system32=prefix/'drive_c/windows/system32'
    started=time.monotonic()
    observed=set()
    samples=[]
    commands=[]
    output_lock=threading.Lock()
    consumed=[0]
    last_setup=[None]
    trace_env={**env,'WINEDEBUG':'-all,err+all,+process,+setupapi,+module'}
    def pump(pipe):
        with pipe:
            while True:
                line=pipe.readline(8192)
                if not line: break
                low=line.lower()
                with output_lock:
                    consumed[0]+=len(line)
                    match=re.search(rb'\b([0-9a-f]+):(?:trace|warn|err):setupapi:([a-z0-9_]+)',low)
                    if match:
                        # Only Wine's compile-time function name and diagnostic thread ID.
                        last_setup[0]={'tid':int(match[1],16),'function':match[2][:80].decode()}

                    observed.update(key for key,token in PATTERNS.items() if token in low)
    def launch():
        p=subprocess.Popen(command,env=trace_env,
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
            setup=last_setup[0]
            flags=sorted(observed)
            count=consumed[0]
        update_time=None
        try:
            marker=(prefix/'.update-timestamp').read_bytes()[:30].strip()
            if marker.isdigit():
                update_time=int(marker)
        except FileNotFoundError:
            pass
        names,waits=processes()
        try:
            windows=wine_windows.snapshot(env['DISPLAY'])
        except (OSError,AttributeError):
            windows=[]
        markers=dict(seconds=age,setup=setup,waits=waits,windows=windows,wineInfMtime=int(Path('/opt/wine/share/wine/wine.inf').stat().st_mtime),
                     updateTimestamp=update_time,system32Entries=len(members),systemRegBytes=(prefix/'system.reg').stat().st_size
                     if (prefix/'system.reg').is_file() else 0,installed=images,
                     processes=names,traceMarkers=flags,traceBytes=count,
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
            if code==0:
                if (system32/'kernel32.dll').is_file() and (prefix/'system.reg').is_file():
                    return
                raise RuntimeError('Windows command exited without installed prefix')
            if code is not None and not installers:
                raise RuntimeError('Actual PE first-use exited before verified Grunt receipt')
            time.sleep(10)
        raise TimeoutError('Windows first-use or owned setup children exceeded observation')
    finally:
        for child in commands:
            if child.poll() is None:
                child.kill()
                child.wait()
        snapshot()
