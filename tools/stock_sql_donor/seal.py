"""Stream a bounded inventory of quiescent laboratory files directly to the recipient's cipher."""
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile

from tools.stock_sql_donor.qualification import APK, NAMESPACE, PACKAGE, SOURCE, require

RECIPIENT='age1khh0jcytwfd98x8cqsp9wa0y5nr60vlrptc8rc5f4pkhrvenqseqahr2y7'
CAP=4<<30
CIPHER_CAP=2<<30
COUNT=50000
proof_names=('cold-reopen.json','package.json','stock-auth.json','world-startup.json')


def encoded(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()


def stamp(p):
    i=p.lstat()
    return (i.st_dev,i.st_ino,i.st_mode,i.st_nlink,i.st_size,i.st_mtime_ns,i.st_ctime_ns)


@contextmanager
def opened(path):
    with os.fdopen(os.open(path,os.O_NOFOLLOW|os.O_RDONLY|os.O_NONBLOCK),'rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode))
        yield stream


def walk(base):
    for top in ('evidence','work'):
        yield top,base/top
    for name in sorted(proof_names):
        yield 'evidence/'+name,base/'evidence'/name
    for name in ('mysql-sessions','state'):
        root=base/'work'/name
        require(root.is_dir() and not root.is_symlink())
        yield 'work/'+name,root
        for directory,folders,leaves in os.walk(root,followlinks=False):
            d=Path(directory)
            if name=='state' and d in (root/'logs',root/'run'):
                # Discard only expired logs/process scratch. SQL owns its independent datadir.
                folders[:]=[]; continue
            if name=='mysql-sessions' and d!=root:
                require(d.parent==root and re.fullmatch('[0-9a-f]{32}',d.name))
                folders[:]=[]
                leaves=['ready.json','stopped.json']
            for leaf in sorted(folders+leaves):
                path=d/leaf
                yield path.relative_to(base).as_posix(),path


def inventory(base):
    rows=[]; source={}; total=0
    for name,path in walk(base):
        require(len(rows)<COUNT and name not in source and len(name.encode())<=512)
        info=stamp(path); mode=info[2]
        require(stat.S_IMODE(mode)<=0o777)
        row=dict(path=name,mode=stat.S_IMODE(mode))
        if stat.S_ISDIR(mode):
            row['kind']='directory'
        elif stat.S_ISREG(mode):
            total+=info[4]
            require(info[3]==1 and total<=CAP)
            with opened(path) as stream:
                row.update(kind='file',bytes=info[4],sha256=hashlib.file_digest(stream,'sha256').hexdigest())
        elif stat.S_ISLNK(mode):
            target=os.readlink(path)
            require(name=='work/state/config/current' and re.fullmatch('generations/[a-f0-9]{64}',target))
            row.update(kind='symlink',target=target)
        else:
            raise ValueError('Unexportable SQL state type')
        require(stamp(path)==info)
        rows.append(row); source[name]=(path,info)
    rows.sort(key=lambda row:row['path'])
    return rows,source,total


def tar_stream(pipe,manifest,rows,sources):
    def member(name,mode,kind,size=0,link=''):
        m=tarfile.TarInfo(name)
        m.mode=mode;m.type=kind;m.size=size;m.linkname=link
        return m
    with tarfile.open(fileobj=pipe,mode='w|',format=tarfile.PAX_FORMAT) as archive:
        archive.addfile(member('manifest.json',0o600,tarfile.REGTYPE,len(manifest)),io.BytesIO(manifest))
        for row in rows:
            name=row['path']; path,expected=sources[name]; mode=row['mode']
            require(stamp(path)==expected)
            if row['kind']=='file':
                with opened(path) as stream:
                    archive.addfile(member(name,mode,tarfile.REGTYPE,row['bytes']),stream)
            elif row['kind']=='directory':
                archive.addfile(member(name,mode,tarfile.DIRTYPE))
            else:
                archive.addfile(member(name,mode,tarfile.SYMTYPE,link=row['target']))
            require(stamp(path)==expected)


def main():
    base,out=map(Path,sys.argv[1:])
    os.umask(0o077)
    require(base.resolve()==base and out.resolve()==out and not out.exists())
    require(json.loads((base/'evidence/package.json').read_bytes())==PACKAGE)
    cold=json.loads((base/'evidence/cold-reopen.json').read_bytes())
    require(cold['sourceCommit']==SOURCE and cold['scope']=='fresh-native-packaged-stock-sql-cold-reopen' and
            len(cold['cleanlyStoppedOperations'])==3 and cold['package']==PACKAGE and cold['namespace']==NAMESPACE)
    rows,sources,total=inventory(base)
    manifest=encoded(dict(formatVersion=1,scope='fresh-public-stock-sql-donor',sourceCommit=SOURCE,apkSha256=APK,
                          package=PACKAGE,namespace=NAMESPACE,files=rows))
    require(len(manifest)<=16<<20)
    out.mkdir(mode=0o700)
    temp=out/'donor.age.partial'
    zstd=age=None
    try:
        with temp.open('xb') as ciphertext:
            zstd=subprocess.Popen(['zstd','-q','-T2','-3','-c'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
            def limit():
                import resource
                resource.setrlimit(resource.RLIMIT_FSIZE,(CIPHER_CAP,CIPHER_CAP))
            age=subprocess.Popen(['age','-r',RECIPIENT],stdin=zstd.stdout,stdout=ciphertext,preexec_fn=limit)
            zstd.stdout.close()
            tar_stream(zstd.stdin,manifest,rows,sources)
            zstd.stdin.close()
            require(zstd.wait(timeout=120)==0 and age.wait(timeout=120)==0)
            ciphertext.flush();os.fsync(ciphertext.fileno())
        size=temp.stat().st_size
        require(0<size<=CIPHER_CAP)
        require(all(stamp(path)==expected for path,expected in sources.values()))
        require([r['path'] for r in rows]==sorted(n for n,_ in walk(base)))
        with temp.open('rb') as stream:
            cipher_sha=hashlib.file_digest(stream,'sha256').hexdigest()
        final=out/'donor.tar.zst.age'
        temp.rename(final)
        summary=dict(formatVersion=1,scope='encrypted-fresh-public-stock-sql-donor',sourceCommit=SOURCE,package=PACKAGE,
                     namespace=NAMESPACE,recipientSha256=hashlib.sha256(RECIPIENT.encode('ascii')).hexdigest(),
                     manifestSha256=hashlib.sha256(manifest).hexdigest(),logicalBytes=total,entryCount=len(rows),
                     cipherBytes=size,cipherSha256=cipher_sha,fourSchemasVerified=True,completedNativeColdReopen=True,
                     cleanStops=3,syntheticPublicFixtureOnly=True)
        (out/'qualification.json').write_bytes(encoded(summary))
    finally:
        for proc in (zstd,age):
            if proc is not None and proc.poll() is None:
                proc.kill();proc.wait()
        temp.unlink(missing_ok=True)


if __name__=='__main__':
    main()
