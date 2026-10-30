#!/usr/bin/env python3
"""Gated prepared-world-data stat cache; production continues full verification.

Only a source-owned Android owner may anchor the exact returned cache SHA in its
private index outside guest mounts. A cache file, caller boolean, or self-hash is
not authority. Reuse requires that independently trusted pin and a fresh complete
file/directory stat comparison after each import/data lease acquisition.

This detects metadata-visible changes to private immutable data. It cannot prove
against byte corruption that preserves every metadata field. Actual Android/PRoot
stat semantics and the source-owned capability selftest remain separate gates.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

try:
    from . import server_data_generation as data
except ImportError:
    import server_data_generation as data

SCHEMA=1
SCOPE='private-prepared-world-data-stat-cache'
MAX_CACHE=128<<20
MAX_LINE=8192
MAX_NODES=300000
STAT_FIELDS=('dev','ino','mode','uid','gid','nlink','size','mtimeNs','ctimeNs')
PRODUCTION_FAST_PATH_ENABLED=False
require=data.require


def encoded(value):return data.storage.encoded(value)
def identity(raw):return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
def hash_pin(value):require(type(value) is str and data.storage.HASH.fullmatch(value),'exact cache hash required');return value


def stamp(value):
    return dict(zip(STAT_FIELDS,(value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_gid,
        value.st_nlink,value.st_size,value.st_mtime_ns,value.st_ctime_ns)))


def validate_stamp(value,kind):
    require(type(value) is dict and set(value)==set(STAT_FIELDS) and
        all(type(v) is int and 0<=v<1<<64 for v in value.values()),'invalid prepared-data stat tuple')
    require(stat.S_ISDIR(value['mode']) if kind=='directory' else stat.S_ISREG(value['mode']),
        'prepared-data cache has wrong file type')
    return value


def node_stamp(path,kind):
    value=stamp(path.lstat());validate_stamp(value,kind);return value


@contextmanager
def plain(path):
    data.storage.canonical(path,False)
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        require(stat.S_ISREG(os.fstat(descriptor).st_mode),'regular cache/data file required')
        with os.fdopen(descriptor,'rb') as stream:
            descriptor=None;yield stream
    finally:
        if descriptor is not None:os.close(descriptor)


def stable_hash(path,maximum,*,cancelled=lambda:False):
    with plain(path) as incoming:
        before=stamp(os.fstat(incoming.fileno()));require(before['size']<=maximum,'prepared-data file exceeds bound')
        total=0;digest=hashlib.sha256()
        while block:=incoming.read(128<<10):
            require(not cancelled(),'prepared-data verification cancelled')
            total+=len(block);require(total<=before['size'],'prepared-data file grew while hashing');digest.update(block)
        after=stamp(os.fstat(incoming.fileno()))
    require(total==before['size'] and before==after==node_stamp(path,'file'),
        'prepared-data inode, times, mode or identity changed while hashing')
    return dict(bytes=total,sha256=digest.hexdigest()),after


def implementation_sha256():
    return data.storage.identity(Path(__file__).resolve(),131072)['sha256']


def selected(root,generation,receipt_pin,helper_generation,expected_inputs):
    root=data.storage.canonical(root);hash_pin(generation);hash_pin(helper_generation)
    data.pin(receipt_pin)
    require(receipt_pin['bytes']<=64<<20,'prepared receipt exceeds bound')
    require(helper_generation==data.preparation_helper_generation(),'prepared-data cache helper generation differs')
    actual,_=stable_hash(root/'receipt.json',64<<20)
    require(actual==receipt_pin,'prepared-data cache receipt pin differs')
    receipt=data._completed_metadata(root,expected_inputs,expected_generation=generation)
    return root,receipt


def relative_name(name):
    data.order.safe(name,1024)
    require(len(name.split('/'))<=17,'prepared-data cache path depth exceeds bound')
    return name


def walk(root):
    """Sorted bounded-depth traversal; no payload bytes are retained."""
    count=0
    def at(directory,prefix,depth):
        nonlocal count
        require(depth<=16,'prepared-data cache directory depth exceeds bound')
        with os.scandir(directory) as stream:
            names=[]
            for entry in stream:
                count+=1;require(count<=MAX_NODES,'prepared-data cache node count exceeds bound');names.append(entry.name)
        for name in sorted(names):
            relative=relative_name(prefix+name);path=root/relative;info=path.lstat()
            require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode),'link or special prepared-data node')
            kind='directory' if stat.S_ISDIR(info.st_mode) else 'file'
            yield relative,path,kind
            if kind=='directory':yield from at(path,relative+'/',depth+1)
    yield from at(root,'',0)


def header(root,generation,receipt_pin,helper_generation,receipt):
    files=receipt['files'];require(type(files) is dict and 0<len(files)<=MAX_NODES,'bounded prepared file inventory required')
    total=0
    for name,row in files.items():
        relative_name(name)
        require(type(row) is dict and set(row)=={'bytes','sha256'} and type(row['bytes']) is int and
            0<=row['bytes']<=data.MAX_FILE,'invalid prepared file identity')
        hash_pin(row['sha256']);total+=row['bytes'];require(total<=data.MAX_TOTAL,'prepared file bytes exceed bound')
    return dict(formatVersion=SCHEMA,scope=SCOPE,generation=generation,receipt=receipt_pin,
        helperGeneration=helper_generation,implementationSha256=implementation_sha256(),
        preflightSha256=hashlib.sha256(encoded(receipt['preflight'])).hexdigest(),
        generationRoot= node_stamp(root,'directory'),dataRoot=node_stamp(root/'data','directory'),
        expectedFiles=len(files),expectedFileBytes=total,
        statFields=list(STAT_FIELDS),payloadProducerQualified=False,worldQualified=False)


def seal(root,generation,receipt_pin,helper_generation,output,*,expected_inputs=None,cancelled=lambda:False):
    """Full stable-FD SHA verification and preflight before a candidate exists.

    Returning this proof does not enable a fast path or write the trusted Android
    index. The retained Android data owner must validate and anchor it separately.
    """
    root,receipt=selected(root,generation,receipt_pin,helper_generation,expected_inputs)
    output=Path(os.path.abspath(output));data.storage.canonical(output.parent)
    require(not output.exists() and not output.is_symlink() and not output.is_relative_to(root),
        'existing cache preserved; cache candidate must be outside the immutable generation')
    begin=header(root,generation,receipt_pin,helper_generation,receipt)
    temporary=output.with_name('.'+output.name+'-'+uuid.uuid4().hex)
    count=files=total=0;digest=hashlib.sha256();bytes_written=0
    try:
        with temporary.open('xb') as outgoing:
            os.chmod(temporary,0o600)
            def write(value):
                nonlocal bytes_written
                raw=encoded(value);require(len(raw)<=MAX_LINE,'prepared-data cache record exceeds bound')
                bytes_written+=len(raw);require(bytes_written<=MAX_CACHE,'prepared-data cache byte limit')
                outgoing.write(raw);digest.update(raw)
            write(begin)
            for name,path,kind in walk(root/'data'):
                require(not cancelled(),'prepared-data verification cancelled')
                record=dict(path=name,kind=kind)
                if kind=='file':
                    require(name in receipt['files'],'unrecorded prepared-data file')
                    actual,stats=stable_hash(path,data.MAX_FILE,cancelled=cancelled)
                    require(actual==receipt['files'][name],'prepared-data bytes differ from the pinned receipt')
                    files+=1;total+=actual['bytes'];record['sha256']=actual['sha256']
                else:stats=node_stamp(path,'directory')
                record['stat']=stats;write(record);count+=1
            require(files==begin['expectedFiles'] and total==begin['expectedFileBytes'],'prepared-data file inventory differs')
            preflight=data.formats.check_server_data(root/'data')
            require(preflight['checks_passed'] and encoded(preflight)==encoded(receipt['preflight']),
                'prepared-data header preflight differs')
            write(dict(end=True,nodes=count,files=files,fileBytes=total))
            outgoing.flush();os.fsync(outgoing.fileno())
        candidate=dict(bytes=bytes_written,sha256=digest.hexdigest())
        # Recheck every captured file/directory after the complete hash pass.
        # The same reader later consumes an independently anchored cache pin.
        verify(root,generation,receipt_pin,helper_generation,temporary,candidate,expected_inputs=expected_inputs,
            cancelled=cancelled)
        # rename() can replace a path created after the first existence check.
        # Publish exclusively: another proof at this name must stay untouched.
        try:os.link(temporary,output,follow_symlinks=False)
        except FileExistsError as error:
            raise ValueError('existing cache preserved; candidate publication lost its exclusive name') from error
        temporary.unlink();data.storage.sync(output.parent)
        return dict(formatVersion=1,scope='full-byte-verified-prepared-data-cache-candidate',generation=generation,
            receipt=receipt_pin,helperGeneration=helper_generation,implementationSha256=begin['implementationSha256'],
            cache=candidate,nodes=count,files=files,fileBytes=total,fullStableFdHashesVerified=True,
            headerPreflightVerified=True,androidRuntimeQualified=False,productionFastPathEnabled=False,
            worldQualified=False,gameplayQualified=False)
    finally:
        if temporary.exists():temporary.unlink()


def verify(root,generation,receipt_pin,helper_generation,cache_path,trusted_pin,*,expected_inputs=None,cancelled=lambda:False):
    """Compare every captured stat using an independently trusted private pin.

    No authority is learned from the cache's own contents. Callers must keep the
    source-owned import/data lease. A new lease requires a fresh invocation.
    """
    root,receipt=selected(root,generation,receipt_pin,helper_generation,expected_inputs)
    data.pin(trusted_pin);require(trusted_pin['bytes']<=MAX_CACHE,'prepared-data trusted cache exceeds bound')
    cache_path=data.storage.canonical(Path(cache_path),False)
    require(not cache_path.is_relative_to(root),'trusted cache must remain outside the immutable generation')
    wanted=header(root,generation,receipt_pin,helper_generation,receipt)
    digest=hashlib.sha256();observed=0;nodes=files=total=0;previous=None;directories=[];ended=False
    with plain(cache_path) as incoming:
        before=stamp(os.fstat(incoming.fileno()))
        require(before['size']==trusted_pin['bytes'] and before['nlink']==1 and stat.S_IMODE(before['mode'])==0o600,
            'prepared-data cache size, private mode or link count differs')
        def read():
            nonlocal observed
            raw=incoming.readline(MAX_LINE+1)
            if not raw:return None
            require(len(raw)<=MAX_LINE and raw.endswith(b'\n'),'prepared-data cache record is oversized or truncated')
            observed+=len(raw);require(observed<=trusted_pin['bytes'],'prepared-data cache grew')
            digest.update(raw)
            value=json.loads(raw,object_pairs_hook=unique)
            require(encoded(value)==raw,'prepared-data cache record is not canonical')
            return value
        require(encoded(read())==encoded(wanted),'prepared-data cache source/helper/receipt/root binding differs')
        while (row:=read()) is not None:
            require(not cancelled(),'prepared-data verification cancelled')
            require(type(row) is dict,'prepared-data cache record must be an object')
            if row.get('end') is True:
                require(encoded(row)==encoded(dict(end=True,nodes=nodes,files=files,fileBytes=total)),
                    'prepared-data cache footer differs')
                ended=True;require(read() is None,'trailing prepared-data cache records');break
            require(type(row) is dict and set(row) in ({'path','kind','stat'},{'path','kind','stat','sha256'}),
                'prepared-data cache node fields differ')
            name=relative_name(row['path']);parts=tuple(name.split('/'))
            require(previous is None or previous<parts,'duplicate or unordered prepared-data cache node')
            previous=parts;kind=row['kind'];require(kind in ('file','directory'),'prepared-data cache node kind differs')
            while directories and not name.startswith(directories[-1]+'/'):directories.pop()
            parent=name.rpartition('/')[0]
            require(parent==(directories[-1] if directories else ''),'prepared-data cache directory closure differs')
            require(validate_stamp(row['stat'],kind)==node_stamp(root/'data'/name,kind),
                'prepared-data stat changed; full verification/recovery is required')
            nodes+=1;require(nodes<=MAX_NODES,'prepared-data cache node count exceeds bound')
            if kind=='directory':
                require(set(row)=={'path','kind','stat'},'prepared-data directory carries a file hash');directories.append(name)
            else:
                require(name in receipt['files'] and set(row)=={'path','kind','stat','sha256'} and
                    dict(bytes=row['stat']['size'],sha256=row['sha256'])==receipt['files'][name],
                    'prepared-data cache file identity differs from receipt')
                files+=1;total+=row['stat']['size']
        after=stamp(os.fstat(incoming.fileno()))
    require(ended and observed==trusted_pin['bytes'] and digest.hexdigest()==trusted_pin['sha256'] and
        before==after==node_stamp(Path(cache_path),'file'),'prepared-data trusted cache bytes or inode changed')
    require(files==wanted['expectedFiles'] and total==wanted['expectedFileBytes'] and
        wanted['generationRoot']==node_stamp(root,'directory') and wanted['dataRoot']==node_stamp(root/'data','directory'),
        'prepared-data final inventory/root changed')
    actual,_=stable_hash(root/'receipt.json',64<<20)
    require(actual==receipt_pin,'prepared-data receipt changed during stat verification')
    return dict(formatVersion=1,scope='private-prepared-data-stat-comparison-only',generation=generation,
        cache=trusted_pin,nodes=nodes,files=files,fileBytes=total,payloadBytesRead=0,
        everyCapturedFileAndDirectoryStatCompared=True,productionFastPathEnabled=False,
        androidRuntimeQualified=False,worldQualified=False,gameplayQualified=False)


def unique(pairs):
    result={}
    for key,value in pairs:
        require(key not in result,'duplicate prepared-data cache field');result[key]=value
    return result
