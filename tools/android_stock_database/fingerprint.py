"""Measure only runtime-authored system32 entries and exact signed-COM registry witnesses in a fresh disposable lab."""
import hashlib,json,os,re,stat
import safe_registry
from pathlib import Path
WINEDLL=Path('/opt/wine/lib/wine/aarch64-windows')
INF=Path('/opt/wine/share/wine/wine.inf')
CLASSES={'quartz.dll':'e436ebb3-524f-11ce-9f53-0020af0ba770','qedit.dll':'78530b75-61f9-11d2-8cad-00a024580902','wmvdecod.dll':'82d353df-90bd-4382-8bc2-3f6192b76e34'}
def digest(p):
 with p.open('rb') as f:
    h=hashlib.sha256()
    for block in iter(lambda:f.read(1<<20),b''): h.update(block)
 return h.hexdigest()
def save(prefix,out):
 assert 'esteria' not in str(prefix.name) or prefix.name=='.wine-repair-copy'
 full={};reg=(prefix/'system.reg').read_bytes(); rows={}; section=None
 for row in reg.decode('utf8').splitlines():
    if row.startswith('['):section=row.split(']',1)[0][1:].replace('\\\\','\\').lower()
    elif section and row.startswith('@='):
        for dll,guid in CLASSES.items():
            if section==f'software\\classes\\clsid\\{{{guid}}}\\inprocserver32':
                value=row.removeprefix('@="').removesuffix('"').replace('\\\\','\\').lower()
                rows[dll]={'guid':guid,'defaultValueMatches':value==f'c:\\windows\\system32\\{dll}', 'defaultBasenameMatches':value.rsplit('\\',1)[-1]==dll}
 for dll,guid in CLASSES.items(): rows.setdefault(dll,{'guid':guid,'defaultValueMatches':False,'defaultBasenameMatches':False})
 for path in (prefix/'drive_c/windows/system32').iterdir():
    name=path.name.lower(); assert re.fullmatch(r'[a-z0-9_. -]{1,100}',name)
    s=path.lstat();item={'type':'directory' if stat.S_ISDIR(s.st_mode) else 'symlink' if path.is_symlink() else 'regular','bytes':s.st_size}
    if item['type']=='regular':item['sha256']=digest(path)
    full[name]=item
 (out/'system32-private.json').write_text(json.dumps(full))
 trial=out.parent/'interrupt/system32-private.json'
 diff={}
 if trial.is_file():
    old=json.loads(trial.read_text());diff['added']={};diff['removed']=sorted(old.keys()-full.keys());diff['changedFileCount']=sum(1 for k,v in old.items() if k in full and v!=full[k])
    for name in sorted(full.keys()-old.keys()):
        file=WINEDLL/name; diff['added'][name]={**full[name], 'winePackageBytes':file.stat().st_size if file.is_file() else None,'winePackageSha256':digest(file) if file.is_file() else None}
 marker=(prefix/'.update-timestamp').read_bytes();assert len(marker)<=32 and marker.strip().isdigit()
 images={}
 for name in ('ntdll.dll','wineboot.exe','kernel32.dll'):
    installed=full[name];from_wine=WINEDLL/name
    images[name]={'prefixSha256':installed['sha256'],'prefixBytes':installed['bytes'],'winePackageSha256':digest(from_wine),'winePackageBytes':from_wine.stat().st_size}
 return {'safetyFacts':safe_registry.observe(prefix),'prefixWineIdentities':images,'timestampAscii':marker.decode(),'timestampBytes':len(marker),'timestampHex':marker.hex(),'registryClasses':rows,'wineInfSha256':digest(INF),'selectedWineInfMtime':int(INF.stat().st_mtime),'system32Count':len(full),'deltaFromInterrupt':diff}
