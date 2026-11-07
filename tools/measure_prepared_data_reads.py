#!/usr/bin/env python3
"""Measure repeated prepared-data reads using the existing synthetic host fixture.

No MPQ assets, Android guest, actual extractor or server service is executed.
The production coordinator is unchanged; spies count real host file inventories,
hashes, links, copy fallbacks and metadata writes. Timings are fixture timings,
not preparation estimates. Output goes to stdout for review or a caller file.
"""
import argparse
import errno
import hashlib
import io
import json
import platform
import sys
import time
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime import server_data_generation as data
from tests.test_server_data_generation import ServerDataGenerationTests

def process_io():
    try:
        counters = dict(line.split(': ', 1) for line in Path('/proc/self/io').read_text().splitlines())
        return {name: int(counters[name]) for name in ('rchar', 'wchar', 'read_bytes', 'write_bytes')}
    except (OSError, KeyError, ValueError):
        return None


def main(vmap_mib=0, force_copy=False):
    case=ServerDataGenerationTests();case.setUp()
    rows=[]
    def fixture(command, cwd, log, timeout, **kwargs):
        case.fake_execute(command, cwd, log, timeout, **kwargs)
        if vmap_mib and Path(command[0]).name == 'vmap4_assembler':
            with (cwd / 'vmaps/000.vmtree').open('ab') as stream:
                block = bytes(1 << 20)
                for _ in range(vmap_mib):
                    stream.write(block)
    def measure(name, operation):
        info={'phase':name,'inventoryCalls':0,'inventoryPayloadBytesRead':0,'cloneCalls':0,'linkedPayloadBytes':0,'copiedPayloadBytes':0,'metadataBytesWritten':0,'extractorInvocations':0,'capabilityInvocations':0,'allTrackedHashBytesRead':0,'reuseReasons':[]}
        original_inventory,original_clone,original_atomic,original_identity,original_link,original_copy=(data.inventory,data.clone,data.storage.atomic,data.world_io.identity,data.os.link,data.world_io.copy_stream)
        inside_inventory=False
        def inventory(root,**kwargs):
            nonlocal inside_inventory
            inside_inventory=True
            try:
                info['inventoryCalls']+=1
                return original_inventory(root,**kwargs)
            finally:inside_inventory=False
        def clone(a,b,**kwargs):info['cloneCalls']+=1;return original_clone(a,b,**kwargs)
        def atomic(path,raw):info['metadataBytesWritten']+=len(raw);return original_atomic(path,raw)
        def identity(path,maximum):
            result=original_identity(path,maximum)
            info['allTrackedHashBytesRead']+=result['bytes']
            if inside_inventory:info['inventoryPayloadBytesRead']+=result['bytes']
            return result
        def link(source,target,**kw):
            result=original_link(source,target,**kw);info['linkedPayloadBytes']+=Path(source).stat().st_size;return result
        def copying(source,target,*a,**kw):
            start=source.tell();result=original_copy(source,target,*a,**kw);info['copiedPayloadBytes']+=source.tell()-start;return result
        def execute(command,*a,**kw):
            info['capabilityInvocations' if command[1:]==['--esteria-order-capabilities'] else 'extractorInvocations']+=1
            return fixture(command,*a,**kw)
        before_io=process_io()
        started=time.monotonic()
        with patch.object(data,'inventory',side_effect=inventory),patch.object(data,'clone',side_effect=clone),patch.object(data.storage,'atomic',side_effect=atomic),patch.object(data.world_io,'identity',side_effect=identity),patch.object(data.storage,'identity',side_effect=identity),patch.object(data.os,'link',side_effect=link),patch.object(data.world_io,'copy_stream',side_effect=copying),patch.object(data,'execute',side_effect=execute):
            result=operation(info)
        info['elapsedSeconds']=round(time.monotonic()-started,6)
        after_io=process_io()
        info['currentProcessProcIoDelta']=({name:after_io[name]-before_io[name] for name in before_io}
             if before_io is not None and after_io is not None else None)
        rows.append(info)
        return result
    try:
        receipt=measure('initial-preparation',lambda info:case.generate(progress=info['reuseReasons'].append))
        measure('unchanged-warm-preparation',lambda info:case.generate(progress=info['reuseReasons'].append))
        measure('session-admission-data-verification-only',lambda info:data.verify_completed(case.store/'generations'/receipt['generation'],receipt['inputs']))
        case.doCleanups();case=ServerDataGenerationTests();case.setUp()
        try:
            with redirect_stdout(io.StringIO()), patch.object(data.formats,'check_server_data',return_value={'checks_passed':False,'error_count':1,'errors':[{'path':'dbc/Map.dbc','error':'intentional fixture failure'}]}):
                with patch.object(data,'execute',side_effect=fixture):case.generate()
        except ValueError as error:
            if 'intentional fixture failure' not in str(error):raise
        else:raise AssertionError('Controlled preflight failure did not occur')
        measure('retained-completed-phases-and-final-assembly-retry',lambda info:case.generate(progress=info['reuseReasons'].append))
        for row in rows:row['reuseReasons']=[x for x in row['reuseReasons'] if 'reused' in x]
        out={'scope':'host-linux-instrumented-production-python-coordinator-synthetic-storage-fixture','realExtractorExecution':False,'ownerGameData':False,'syntheticVmapMiB':vmap_mib,'forcedPrivateCopyFallback':force_copy,'androidOrProotExecution':False,'nativeServiceStartupExecuted':False,'counts':'Inventory bytes count complete payload SHA reads. Tracked hashes include helper/import/order metadata. Small header reads are not included in tracked hashes. Optional /proc/self/io deltas include fixture and measurement I/O, exclude child processes, and reflect the current filesystem cache. Metadata writes exclude simulated extractor writes. Clone uses real host hardlinks or the explicitly selected EXDEV copy fallback. Session sample is data subphase only, excluding SQL and binaries.','preparedFixturePayloadBytes':sum(row['bytes'] for row in receipt['files'].values()),'environment':dict(system=platform.system(),machine=platform.machine(),python=platform.python_version()),'sourceSha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('runtime/server_data_generation.py','runtime/server_data_preflight.py','runtime/world_io.py','tests/test_server_data_generation.py','tools/measure_prepared_data_reads.py')},'measurements':rows}
        print(json.dumps(out,indent=2))
    finally:case.doCleanups()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vmap-mib', type=int, default=0, help='Append 0–256 MiB to the synthetic VMAP payload')
    parser.add_argument('--force-copy', action='store_true', help='Deny private hard links with EXDEV')
    args=parser.parse_args()
    if not 0 <= args.vmap_mib <= 256: parser.error('vmap-mib must be 0–256')
    with (patch.object(data.os, 'link', side_effect=OSError(errno.EXDEV, 'measured private copy fallback'))
          if args.force_copy else nullcontext()):
        main(args.vmap_mib, args.force_copy)
