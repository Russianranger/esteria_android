"""Read-only original prefix and canonical production helper input on a standalone signed QA install."""
import hashlib,json,os,shutil,stat,sys
from pathlib import Path
mode=sys.argv[1];base=Path('/work');original=Path('/esteria-client/home/.wine');target=base/'home/.wine'
def snapshot(p):
    h=hashlib.sha256()
    for f in sorted(p.rglob('*')):
        st=f.lstat();row=[str(f.relative_to(p)),st.st_mode,st.st_ino,st.st_size,st.st_mtime_ns]
        if f.is_symlink(): row.append(os.readlink(f))
        elif stat.S_ISREG(st.st_mode):
            with f.open('rb') as source:
                item=hashlib.sha256()
                for chunk in iter(lambda:source.read(1<<20),b''):item.update(chunk)
            row.append(item.hexdigest())
        h.update(json.dumps(row,separators=(',',':')).encode()+b'\n')
    return h.hexdigest()
assert original.is_dir() and (original/'drive_c/esteria-qa-prior-state.bin').is_file()
ref=base/'qa-original.sha256'
if mode=='clone':
    assert not target.exists() and not ref.exists()
    ref.write_text(snapshot(original)+'\n');shutil.copytree(original,target,symlinks=True)
assert ref.read_text().strip()==snapshot(original)
assert (original/'drive_c/esteria-qa-prior-state.bin').read_bytes()==(target/'drive_c/esteria-qa-prior-state.bin').read_bytes()
assert original.stat().st_ino!=target.stat().st_ino
(base/'qa-original-check.json').write_text(json.dumps({'originalSnapshot':ref.read_text().strip(),'sourceInode':original.stat().st_ino,'copyInode':target.stat().st_ino,'sentinelRetained':True,'originalTreeUnchanged':True}))
