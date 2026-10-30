"""Build an explicit provider order from the reconstructed normal client reader.

This planner supports the owned, single-Data-root classical desktop profile.
It does not claim MPQ decoding, modern asset translation or map conversion.
The separate extractor adaptation consumes its highest-priority-first manifest.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
import stat

SCHEMA = 'esteria-classical-ordered-providers-v1'
LOCALES = ('deDE','enGB','enUS','esES','frFR','koKR','zhCN','zhTW','enCN','enTW','esMX','ruRU')
CHINESE = {'zhCN','enCN','zhTW','enTW'}
BASES = (
 ('alternate.MPQ',3,3), ('interface.MPQ',1,1), ('misc.MPQ',1,1), ('model.MPQ',1,1),
 ('texture.MPQ',1,1), ('terrain.MPQ',1,1), ('wmo.MPQ',1,1), ('sound.MPQ',1,1),
 ('fonts.MPQ',1,1), ('dbc.MPQ',1,1), ('speech.MPQ',1,1), ('expansionloc.MPQ',2,1),
 ('lichkingloc.MPQ',2,1), ('expansionspeech.MPQ',2,1), ('lichkingspeech.MPQ',2,1),
 ('expansion.MPQ',2,3), ('lichking.MPQ',2,3), ('common.MPQ',1,2), ('common-2.MPQ',2,2),
 ('****/locale-****.MPQ',1,2), ('****/speech-****.MPQ',1,2),
 ('****/expansion-locale-****.MPQ',2,2), ('****/lichking-locale-****.MPQ',2,2),
 ('****/expansion-speech-****.MPQ',2,2), ('****/lichking-speech-****.MPQ',2,2),
 ('development.MPQ',2,1), ('streaming.MPQ',4,1), ('streamingloc.MPQ',4,1), ('common-3.MPQ',2,2))
MAX_PROVIDERS, MAX_FILES, MAX_MANIFEST = 4096, 100000, 16 << 20
MAX_FILE = 16 << 30
BLOCK = 128 << 10


class OrderError(ValueError):
    pass


def require(value, reason):
    if not value: raise OrderError(reason)


def safe(value, maximum=259):
    require(isinstance(value,str) and 0<len(value.encode('ascii',errors='replace'))<=maximum and
            value.isascii() and all(32<=ord(c)<127 and c not in '\\:\t\r\n' for c in value) and
            not value.startswith('/') and all(p not in ('','.','..') for p in value.split('/')),
            'unsupported or unsafe extractor provider path')
    return value


def canonical(value):
    return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


def file_identity(path):
    info=path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_size<=MAX_FILE,'extractor input must be a bounded regular file')
    digest=hashlib.sha256()
    with path.open('rb') as source:
        while block:=source.read(BLOCK):digest.update(block)
    after=path.lstat()
    require((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)==
            (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'extractor input changed while hashing')
    return dict(bytes=info.st_size,sha256=digest.hexdigest())


class Inventory:
    def __init__(self,root):
        self.root=Path(os.path.abspath(root))
        require(self.root==self.root.resolve() and self.root.is_dir(),'owned canonical extractor input root required')
        self.entries={};self.identities={};self.children={}
        data=[p for p in self.root.iterdir() if p.name.lower()=='data']
        require(len(data)==1 and stat.S_ISDIR(data[0].lstat().st_mode),'one unlinked Data directory required')
        data_name=safe(data[0].name);self.entries[data_name]='directory';self.children['.']={'data':data_name}
        # Normal archive lookup does not consume screenshots, accounts or other
        # files outside Data. Their names cannot invalidate this scoped order.
        for parent,dirs,files in os.walk(data[0],followlinks=False):
            parent=Path(parent);children={}
            for name in sorted(dirs+files):
                path=parent/name;relative=safe(path.relative_to(self.root).as_posix());info=path.lstat()
                require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode),'linked or special extractor input refused')
                folded=name.lower();require(folded not in children,'case-insensitive extractor input collision')
                children[folded]=relative;self.entries[relative]='directory' if stat.S_ISDIR(info.st_mode) else 'mpq'
                require(len(self.entries)<=MAX_FILES,'extractor input inventory bound')
            self.children[parent.relative_to(self.root).as_posix()]=children

    def find(self,relative):
        parts=safe(relative).split('/');parent='.'
        for part in parts:
            parent=self.children.get(parent,{}).get(part.lower())
            if parent is None:return None
        return parent

    def identity(self,name):
        if name not in self.identities:self.identities[name]=file_identity(self.root/name)
        return self.identities[name]

    def provider(self,name,prefix='',role='base'):
        kind=self.entries[name]
        row=dict(kind=kind,path=name,prefix=prefix,role=role)
        if kind=='mpq':row.update(self.identity(name))
        else:
            members={}
            for path,typ in self.entries.items():
                if typ=='mpq' and path.startswith(name+'/'):
                    members[path[len(name)+1:]]=self.identity(path)
            row['files']=members
        return row


def plan(root,configured_locale,*,profile):
    require(canonical(profile)==canonical(dict(classical=True,trial=False,streaming=False,directAccess=False,
            retailVirtualProviders=False,parentDataVisible=False,installDataVisible=False)),
            'unsupported client extraction profile; no stock fallback is permitted')
    require(configured_locale in LOCALES,'unsupported configured locale')
    tree=Inventory(root);common=tree.find('Data/common.MPQ')
    require(common is not None and tree.entries[common]=='mpq','classical mode requires a regular common.MPQ')
    # CheckAvailableLocales rotates the configured locale through this exact
    # source order and considers only a regular locale archive, not a folder.
    start=LOCALES.index(configured_locale);locale=None
    for i in range(len(LOCALES)):
        candidate=LOCALES[(start+i)%len(LOCALES)];name=tree.find('Data/'+candidate+'/locale-'+candidate+'.MPQ')
        if name is not None and tree.entries[name]=='mpq':locale=candidate;break
    require(locale is not None,'no classical locale archive is available')
    suffix=[]
    for parent,pattern in (('Data','patch-*.MPQ'),('Data/'+locale,'patch-'+locale+'-*.MPQ')):
        found=tree.find(parent)
        for name in tree.children.get(found or '<absent>',{}).values():
            if fnmatch.fnmatchcase(Path(name).name.lower(),pattern.lower()):suffix.append(name)
    # PatchFiles pass0 sorts all full Windows paths descending, then pass1
    # appends plain root and locale patches. OpenArchives iterates in reverse.
    suffix.sort(key=lambda n:n.replace('/','\\').lower(),reverse=True)
    enumeration=suffix+[n for n in (tree.find('Data/patch.MPQ'),tree.find('Data/'+locale+'/patch-'+locale+'.MPQ')) if n]
    require(len(enumeration)==len({n.lower() for n in enumeration}),'ambiguous duplicate patch provider')
    opened=[];priority=64
    for name in reversed(enumeration):
        row=tree.provider(name,role='patch');row['priority']=priority;priority+=1;opened.append(row)
    patches=list(opened);alternate=tree.find('Data/alternate.MPQ')
    if alternate:
        row=tree.provider(alternate,role='alternate-base');row['priority']=priority;priority+=1;opened.append(row)
    if alternate or locale in CHINESE:
        for patch in patches:
            if patch['kind']=='directory':
                child=tree.find(patch['path']+'/alternate')
                if child is None:continue
                row=tree.provider(child,role='alternate-view')
            else:row=tree.provider(patch['path'],prefix='alternate',role='alternate-view')
            row['priority']=priority;priority+=1;opened.append(row)
    base_priority=63
    for pattern,kind,availability in BASES:
        if kind in (3,4):continue
        if availability&2:
            name=tree.find('Data/'+pattern.replace('****',locale))
            require(name is not None or kind==2,'missing mandatory client base provider:'+pattern)
            if name:
                row=tree.provider(name,role='base');row['priority']=base_priority;opened.append(row)
        base_priority-=1
    require(0<len(opened)<=MAX_PROVIDERS,'extractor provider count bound')
    rows=sorted(opened,key=lambda r:r['priority'],reverse=True)
    for rank,row in enumerate(rows):row['rank']=rank
    result=dict(formatVersion=1,scope=SCHEMA,configuredLocale=configured_locale,effectiveLocale=locale,
        profile=profile,providers=rows,priorityOrder='highest-first',archiveHashLocale=0,archiveHashPlatform=0,
        inputRootIncluded=False,clientMpqConversionQualified=False,customEsteriaDataLoadOrderQualified=False,
        androidRuntimeQualified=False,gameplayQualified=False)
    require(len(canonical(result))<=MAX_MANIFEST,'extractor order manifest byte bound')
    return result


def wire(document):
    """The C++ adapter consumes a bounded, hash-bound, tab-separated projection."""
    require(document.get('scope')==SCHEMA and document.get('priorityOrder')=='highest-first','extractor order scope')
    rows=['ESTERIA-ORDER-1\t'+document['effectiveLocale']+'\t'+str(len(document['providers']))]
    file_count=0
    for i,provider in enumerate(document['providers']):
        require(provider['rank']==i,'noncanonical extractor order rank')
        name=safe(provider['path']);prefix=provider['prefix'] or '-'
        rows.append('\t'.join(('P',provider['kind'],name,prefix,str(provider.get('bytes',0)),provider.get('sha256','-'))))
        for member,item in sorted(provider.get('files',{}).items()):
            file_count+=1;require(file_count<=MAX_FILES,'extractor ordered loose file count bound')
            rows.append('\t'.join(('F',safe(member),str(item['bytes']),item['sha256'])))
    raw=('\n'.join(rows)+'\n').encode('ascii')
    require(len(raw)<=MAX_MANIFEST,'extractor wire manifest byte bound')
    return raw
