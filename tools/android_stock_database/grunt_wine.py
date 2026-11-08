"""Package-private signed Wine guest. Only closed-set milestones and loader diagnostics leave Android."""
import json
import hashlib
import shutil
import stat as fsstat
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import wine_prefix
import fingerprint

work = Path('/work')
mode = sys.argv[1]
assert mode in {'reference','interrupt','reentry','copy-force','copy-warm','warm'}
os.umask(0o077)
out = work / mode
out.mkdir(mode=0o700, exist_ok=False)
start = time.monotonic()
env = {**os.environ, 'DISPLAY': ':77', 'WINEPREFIX': '/work/home/.wine',
       'WINEDLLOVERRIDES':'winepulse.drv=', 'WINEESYNC':'0', 'WINEFSYNC':'0',
       'WINEDEBUG': '-all,err+all'}
if mode!='interrupt':
    env['WINEDLLOVERRIDES']+=';mscoree='
original_prefix = Path(env['WINEPREFIX'])
if mode.startswith('copy-'):
    env['WINEPREFIX']='/work/home/.wine-repair-copy'
prefix = Path(env['WINEPREFIX'])

def tree_hash(root):
    stream=hashlib.sha256()
    for path in sorted(root.rglob('*')):
        st=path.lstat();record=[str(path.relative_to(root)),st.st_mode,st.st_size,st.st_mtime_ns,st.st_ino]
        if fsstat.S_ISREG(st.st_mode):
            with path.open('rb') as file:
                digest=hashlib.sha256()
                for block in iter(lambda:file.read(1<<20),b''):digest.update(block)
            record.append(digest.hexdigest())
        elif path.is_symlink(): record.append(os.readlink(path))
        stream.update(json.dumps(record,separators=(',',':')).encode()+b'\n')
    return stream.hexdigest()

def report_prefix(path):
    timestamp=path/'.update-timestamp'
    marker=path/'drive_c/esteria-qa-prior-state.bin'
    return dict(prefixInode=path.stat().st_ino,timestamp=timestamp.read_text().strip() if timestamp.is_file() else None,
                markerHash=hashlib.sha256(marker.read_bytes()).hexdigest() if marker.is_file() else None,
                markerInode=marker.stat().st_ino if marker.is_file() else None)

def actual_registry(env):
    queries=[('postRegistrationDirectX',r'HKLM\Software\Microsoft\DirectX','Version','4.09.00.0904'),
             ('postRegistrationAeDebug',r'HKLM\Software\Microsoft\Windows NT\CurrentVersion\AeDebug','Debugger','winedbg --auto')]
    result={}
    for label,key,name,expected in queries:
        cmd=subprocess.run([wine,'reg.exe','query',key,'/v',name],env={**env,'WINEDEBUG':'-all'},stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL,timeout=70)
        data=cmd.stdout.replace(b'\x00',b'').lower()
        result[label]={'returnCode':cmd.returncode,'expectedValuePresent':cmd.returncode==0 and expected.encode().lower() in data}
    return result
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
    source_hash=None
    if mode in ('interrupt','reference'): assert not prefix.exists()
    elif mode=='copy-force':
        assert not prefix.exists() and original_prefix.is_dir()
        source_hash=tree_hash(original_prefix)
        shutil.copytree(original_prefix,prefix,symlinks=True)
        assert report_prefix(prefix)['markerHash']==report_prefix(original_prefix)['markerHash']
    elif mode=='copy-warm': source_hash=tree_hash(original_prefix)
    else: assert prefix.is_dir() and (prefix/'.update-timestamp').is_file()
    proof={'mode':mode,'before':report_prefix(prefix) if prefix.is_dir() else None,'registry':None}
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
            status('windows-first-use')
            command=[wine,'wineboot.exe','-u'] if mode=='copy-force' else [wine,'cmd.exe','/c','ver']
            wine_prefix.observe(command,env,prefix,out,mode)
            if mode=='interrupt':
                state=prefix/'drive_c/esteria-qa-prior-state.bin'
                with state.open('xb') as file: file.write(os.urandom(64))
            else: proof['registry']=actual_registry(env)
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
    proof['after']=report_prefix(prefix)
    raw=(prefix/'.update-timestamp').read_bytes();assert len(raw)<=32 and raw.strip().isdigit()
    proof['rawTimestampHex']=raw.hex()
    proof['images']={}
    for name in ('ntdll.dll','kernel32.dll','wineboot.exe'):
        prop={}
        for kind,base in (('prefix',prefix/'drive_c/windows/system32'),('wine',Path('/opt/wine/lib/wine/aarch64-windows'))):
            f=base/name;prop[kind]={'link':f.is_symlink(),'exists':f.exists(),'bytes':f.stat().st_size if f.exists() else None,'sha256':fingerprint.digest(f) if f.is_file() else None}
        proof['images'][name]=prop
    try:
        proof['signedWitnesses']=fingerprint.save(prefix,out)
    except Exception as exc:
        import traceback
        proof['witnessError']={'type':type(exc).__name__,'line':traceback.extract_tb(exc.__traceback__)[-1].lineno}
    if source_hash is not None:
        proof['originalPrefixAuditUnchanged']=tree_hash(original_prefix)==source_hash
        assert proof['originalPrefixAuditUnchanged']
    (out/'prefix-proof.json').write_text(json.dumps(proof))
    status('grunt-exited')
    (out/'exited').touch(exist_ok=False)


if __name__=='__main__':
    run()
