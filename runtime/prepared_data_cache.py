#!/usr/bin/env python3
"""Owner-scoped prepared-world-data byte verification and stat admission.

Only a source-owned Android owner may anchor the exact returned cache SHA in its
private index outside guest mounts. A cache file, caller boolean, or self-hash is
not authority. Reuse requires that independently trusted pin and a fresh complete
file/directory stat comparison after each import/data lease acquisition.

This detects metadata-visible changes to private immutable data. It cannot prove
against byte corruption that preserves every metadata field. Admission tests the local filesystem through PRoot under a retained Android owner.
"""
from __future__ import annotations
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import time
import tempfile
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
UNCONDITIONAL_FAST_PATH_ENABLED=False
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
        for block in data.world_io.chunks(incoming,128<<10):
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
        helperGeneration=helper_generation,installedReader=data.installed_helper_generation(),implementationSha256=implementation_sha256(),
        preflightSha256=hashlib.sha256(encoded(receipt['preflight'])).hexdigest(),
        generationRoot= node_stamp(root,'directory'),dataRoot=node_stamp(root/'data','directory'),
        expectedFiles=len(files),expectedFileBytes=total,
        statFields=list(STAT_FIELDS),payloadProducerQualified=False,worldQualified=False)


def seal(root,generation,receipt_pin,helper_generation,output,*,expected_inputs=None,cancelled=lambda:False,filesystem=None):
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
                    if actual!=receipt['files'][name]:
                        raise InvalidPayload('prepared-data bytes differ from the pinned receipt')
                    files+=1;total+=actual['bytes'];record['sha256']=actual['sha256']
                else:stats=node_stamp(path,'directory')
                record['stat']=stats;write(record);count+=1
            require(files==begin['expectedFiles'] and total==begin['expectedFileBytes'],'prepared-data file inventory differs')
            preflight=data.formats.check_server_data(root/'data',content_profile=receipt['inputs'].get('contentProfile','esteria-custom'))
            require(preflight['checks_passed'] and encoded(preflight)==encoded(receipt['preflight']),
                'prepared-data header preflight differs')
            write(dict(end=True,nodes=count,files=files,fileBytes=total))
            outgoing.flush();os.fsync(outgoing.fileno())
        candidate=dict(bytes=bytes_written,sha256=digest.hexdigest())
        # Recheck every captured file/directory after the complete hash pass.
        # The same reader later consumes an independently anchored cache pin.
        verify(root,generation,receipt_pin,helper_generation,temporary,candidate,expected_inputs=expected_inputs,
            cancelled=cancelled,filesystem=filesystem)
        # rename() can replace a path created after the first existence check.
        # Publish exclusively: another proof at this name must stay untouched.
        try:os.link(temporary,output,follow_symlinks=False)
        except FileExistsError as error:
            raise ValueError('existing cache preserved; candidate publication lost its exclusive name') from error
        temporary.unlink();data.storage.sync(output.parent)
        return dict(formatVersion=1,scope='full-byte-verified-prepared-data-cache-candidate',generation=generation,
            receipt=receipt_pin,helperGeneration=helper_generation,implementationSha256=begin['implementationSha256'],
            cache=candidate,nodes=count,files=files,fileBytes=total,fullStableFdHashesVerified=True,
            headerPreflightVerified=True,androidRuntimeQualified=False,unconditionalFastPathEnabled=False,
            worldQualified=False,gameplayQualified=False)
    finally:
        if temporary.exists():temporary.unlink()


class InvalidPayload(ValueError):
    pass


def verify(root,generation,receipt_pin,helper_generation,cache_path,trusted_pin,*,expected_inputs=None,cancelled=lambda:False,filesystem=None):
    """Compare every captured stat using an independently trusted private pin.

    No authority is learned from the cache's own contents. Callers must keep the
    source-owned import/data lease. A new lease requires a fresh invocation.
    """
    root,receipt=selected(root,generation,receipt_pin,helper_generation,expected_inputs)
    data.pin(trusted_pin);require(trusted_pin['bytes']<=MAX_CACHE,'prepared-data trusted cache exceeds bound')
    cache_path=data.storage.canonical(Path(cache_path),False)
    require(not cache_path.is_relative_to(root),'trusted cache must remain outside the immutable generation')
    wanted=header(root,generation,receipt_pin,helper_generation,receipt)
    if filesystem is not None:
        filesystem.require_node(wanted['dataRoot'],'directory')
        filesystem.require_node(wanted['generationRoot'],'directory')
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
            if filesystem is not None:filesystem.require_node(row['stat'],kind)
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
        everyCapturedFileAndDirectoryStatCompared=True,qualifiedFilesystem=filesystem is not None,unconditionalFastPathEnabled=False,
        androidRuntimeQualified=False,worldQualified=False,gameplayQualified=False)


def unique(pairs):
    result={}
    for key,value in pairs:
        require(key not in result,'duplicate prepared-data cache field');result[key]=value
    return result

class OwnedFilesystem:
    """One bounded Android/PRoot stat and writer-exclusion trial on this volume."""

    def __init__(self, root, scratch):
        root = data.storage.canonical(root)
        scratch = data.storage.canonical(scratch)
        self.device = root.stat().st_dev
        require(self.device == scratch.stat().st_dev, 'cache trial and selected generation are on different volumes')
        with (scratch / 'owner.lock').open('r+b') as owner:
            require(os.fstat(owner.fileno()).st_nlink == 1, 'admission lock has external aliases')
            try:
                fcntl.lockf(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise ValueError('retained Android admission owner missing')
        with tempfile.TemporaryDirectory(dir=scratch) as trial:
            directory = Path(trial)
            leaf = directory / 'initial'
            before = directory.stat()
            time.sleep(.025)
            leaf.write_bytes(b'a')
            os.utime(directory,ns=(before.st_atime_ns,before.st_mtime_ns))
            require(directory.stat().st_ctime_ns > before.st_ctime_ns,'restored-mtime directory addition is invisible')
            initial = leaf.stat()
            time.sleep(.025)
            leaf.write_bytes(b'b')
            os.utime(leaf, ns=(initial.st_atime_ns, initial.st_mtime_ns))
            changed = leaf.stat()
            require(changed.st_mtime_ns == initial.st_mtime_ns and changed.st_ctime_ns > initial.st_ctime_ns,
                    'restored-mtime replacement is invisible')
            other = directory / 'replacement'
            other.write_bytes(b'b')
            os.replace(other, leaf)
            require(leaf.stat().st_ino != initial.st_ino, 'replacement inode is invisible')
            before = directory.stat()
            time.sleep(.025)
            leaf.unlink()
            os.utime(directory,ns=(before.st_atime_ns,before.st_mtime_ns))
            require(directory.stat().st_ctime_ns > before.st_ctime_ns,'restored-mtime directory deletion is invisible')
            self.boundary = directory.stat().st_ctime_ns
            probe=directory/'publish'
            probe.write_bytes(b'probe')
            with probe.open('r+b') as fd:os.fsync(fd.fileno())
            os.link(probe,directory/'published',follow_symlinks=False)
            probe.unlink()
            data.storage.sync(directory)
            require(node_stamp(directory/'published','file')['nlink']==1,'exclusive cache publication unavailable')


    def require_node(self, stats, kind):
        # Normal generation activation unlinks retained phase aliases. Until then
        # the file stays on the full verification path. Older ctimes exclude any
        # mutation in the filesystem timestamp tick used to establish this trial.
        require(stats['dev'] == self.device and stats['ctimeNs'] < self.boundary and
                (kind == 'directory' or stats['nlink'] == 1),
                'unqualified volume, timestamp or writable hard link')


def admit(root, expected_inputs, receipt_pin, scratch, trusted_pin, *, cancelled=lambda:False):
    """New comparison under the current owner; any lost proof falls back to the full audit."""
    generation = hashlib.sha256(encoded(expected_inputs)).hexdigest()
    stale = False
    if trusted_pin is not None:
        filesystem = None
        try:
            filesystem = OwnedFilesystem(root, scratch)
            verify(root, generation, receipt_pin, expected_inputs['preparationHelperGeneration'],
                   scratch/'cache.jsonl', trusted_pin, expected_inputs=expected_inputs,
                   cancelled=cancelled, filesystem=filesystem)
        except (OSError, ValueError, KeyError) as error:
            if cancelled():raise
            # Loss of the owner or filesystem capability says nothing about the
            # existing private cache. Only a metadata mismatch after a valid
            # trial and successful full audit requests replacement.
            stale = filesystem is not None and isinstance(error,ValueError)
            reason=type(error).__name__ if isinstance(error,OSError) else str(error)[:144]
            print('Prepared data full verification: ' + reason,flush=True)
        else:
            print('Prepared data reused: all selected file/directory stats compared, payloadBytesRead=0',flush=True)
            return data._completed_metadata(root, expected_inputs, expected_generation=generation)
    require(not cancelled(), 'prepared-data admission cancelled')
    receipt = data.verify_completed(root, expected_inputs, expected_generation=generation)
    if stale:
        try:(scratch/'stale').touch(exist_ok=False)
        except OSError:pass
    return receipt


def admission_progress(directory, operation, receipt_sha, role, emit, *, clock=time.monotonic):
    """Publish only advancing counters from this owned read policy. Never an integrity proof."""
    path = directory / (role + '-io.json')
    next_report, last_bytes, lowest_rate = 0, -1, None
    def report(line):
        nonlocal next_report, last_bytes, lowest_rate
        emit(line)
        metrics = json.loads(line.removeprefix('WORLD_IO '))
        if metrics['phase'] != 'server-session-admission':
            return
        rate = metrics['pressureBytesPerSecond'] if metrics['pressureLevel'] else metrics['normalBytesPerSecond']
        lowest_rate = rate if lowest_rate is None else min(rate, lowest_rate)
        now = clock()
        if now < next_report or metrics['readBytes'] == last_bytes:
            return
        last_bytes, next_report = metrics['readBytes'], now + 5
        data.storage.atomic(path, encoded(dict(operationId=operation, receiptSha256=receipt_sha,
            role=role, readBytes=last_bytes, normalBytesPerSecond=metrics['normalBytesPerSecond'],
            lowestBytesPerSecond=lowest_rate)))
    return report


def seal_for_session(operation, generation, receipt_sha):
    import re, sys
    require(re.fullmatch('[0-9a-f]{32}', operation), 'invalid private operation')
    directory = Path('/work/server-sessions') / operation
    selection = json.loads(data.storage.read(directory / 'selection.json', 128 << 10),
                           object_pairs_hook=unique)
    inputs = selection['dataInputs']
    require(hashlib.sha256(encoded(inputs)).hexdigest()==generation and selection['dataReceipt']['sha256']==receipt_sha,
            'selected input or receipt changed before cache seal')
    root, scratch = Path('/esteria-data'), Path('/esteria-data-admission')
    report = admission_progress(directory, operation, receipt_sha, 'cache-seal',
                                lambda value: print(value, file=sys.stderr, flush=True))
    with data.world_io.android_policy(progress=report):
        data.world_io.phase('server-session-admission')
        filesystem = OwnedFilesystem(root,scratch)
        # Reject unsupported mounts, very recent timestamps and retained hard
        # links before reading large payloads to produce a persistent cache.
        filesystem.require_node(node_stamp(root,'directory'),'directory')
        filesystem.require_node(node_stamp(root/'data','directory'),'directory')
        for _,path,kind in walk(root/'data'):
            filesystem.require_node(node_stamp(path,kind),kind)
        proof = seal(root,generation,selection['dataReceipt'],inputs['preparationHelperGeneration'],
                     scratch/'cache.jsonl',expected_inputs=inputs,filesystem=filesystem)
    # stdout belongs only to this short-lived selected sealer. A data file in a
    # writable guest directory cannot select its own trusted bytes or SHA.
    print(str(proof['cache']['bytes']) + ' ' + proof['cache']['sha256'],flush=True)


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 6: raise SystemExit(2)
    with data.reader_admission(sys.argv[4],sys.argv[5]):
        try:
            seal_for_session(*sys.argv[1:4])
        except InvalidPayload:
            print('Selected prepared data payload differs from the saved SHA; repair world data',file=sys.stderr)
            raise SystemExit(65)
        except (OSError,ValueError) as error:
            reason=type(error).__name__ if isinstance(error,OSError) else str(error)[:144]
            print('Prepared data cache unavailable: '+reason,file=sys.stderr,flush=True)
            raise SystemExit(78)
