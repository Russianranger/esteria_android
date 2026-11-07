"""Runner-only mount/PID/network namespace. Mount only device nodes Wine actually needs."""
import ctypes
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import sys

def run(root, data, shaders, uid, gid):
    if os.getpid() != 1 or os.geteuid() != 0:
        raise RuntimeError('requires a private PID namespace')
    subprocess.run(['ip','link','set','lo','up'],check=True)
    interfaces=json.loads(subprocess.check_output(['ip','-j','link','show']))
    if [interface['ifname'] for interface in interfaces] != ['lo']:
        raise RuntimeError('guest has an external network interface')
    # The parent created the staged root under RUNNER_TEMP. Mount propagation is private.
    for name in ('proc','dev/shm','esteria-data','esteria-shaders'):
        (root / name).mkdir(parents=True, exist_ok=True)
    subprocess.run(['mount','-t','proc','proc',root/'proc'], check=True)
    for name in ('null','zero','urandom','random','full'):
        device = root/'dev'/name
        device.touch()
        subprocess.run(['mount','--bind','/dev/'+name,device], check=True)
    subprocess.run(['mount','-t','tmpfs','-o','mode=1777,size=96M','tmpfs',root/'dev/shm'], check=True)
    for source, mount in ((data,root/'esteria-data'),(shaders,root/'esteria-shaders')):
        subprocess.run(['mount','--bind',source,mount], check=True)
        subprocess.run(['mount','-o','remount,bind,ro,nosuid,nodev,noexec',mount], check=True)
    # Fanotify describes successful read activity; an open attempt does not count.
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.fanotify_init(1 | 2, os.O_RDONLY | os.O_CLOEXEC)
    if fd < 0:
        raise OSError(ctypes.get_errno(),'fanotify init')
    mark = libc.fanotify_mark
    mark.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_uint64, ctypes.c_int, ctypes.c_char_p]
    files = [(root/'work/client-state/WTF/RunOnce~EsteriaLocale.wtf','locale')]
    files += [(p,'mpq') for p in (root/'esteria-data/Data').rglob('*') if p.suffix.lower()=='.mpq']
    files += [(p,'spirv') for p in (root/'esteria-shaders').rglob('*') if p.suffix.lower()=='.spv']
    identities = {}
    for path,kind in files:
        # Mark the particular verified inode so private copies or unrelated source files do not count.
        if mark(fd,1,1,-100,os.fsencode(path)) != 0:
            raise OSError(ctypes.get_errno(),'fanotify mark')
        stat = path.stat()
        identities[(stat.st_dev,stat.st_ino)] = kind
    observed = {kind:set() for kind in ('mpq','spirv','locale')}
    client = subprocess.Popen(['chroot','--userspec='+uid+':'+gid,root,'/usr/bin/python3',
                               '/work/guest.py'], env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin'})
    polling = select.poll()
    polling.register(fd, select.POLLIN)
    try:
        while client.poll() is None:
            if not polling.poll(500):
                continue
            data = os.read(fd,65536)
            offset = 0
            while offset < len(data):
                length,version,_,_,mask,filefd,pid = struct.unpack_from('=IBBHQii',data,offset)
                offset += length
                if filefd < 0:
                    continue
                try:
                    if (root/f'proc/{pid}/comm').read_text().strip().lower() != 'wowclient64.exe':
                        continue
                    stat = os.fstat(filefd)
                    identity = (stat.st_dev, stat.st_ino)
                    if mask & 1 and identity in identities:
                        observed[identities[identity]].add(identity)
                except FileNotFoundError:
                    pass
                finally:
                    os.close(filefd)
    finally:
        os.close(fd)
    if client.returncode:
        raise RuntimeError('guest process failed')
    result = root/'work/result.json'
    record = json.loads(result.read_text())
    record['successfulClientAccesses'] = {name:len(items) for name,items in observed.items()}
    # The selected source reads its RunOnce via InitializeGlobal, called from CommonMain.
    record['commonMainLocaleRead'] = bool(observed['locale'])
    result.write_text(json.dumps(record))


if __name__ == '__main__':
    run(*map(Path,sys.argv[1:4]), *sys.argv[4:6])
