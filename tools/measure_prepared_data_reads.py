#!/usr/bin/env python3
"""Measure repeated prepared-data reads using the existing synthetic host fixture.

No MPQ assets, Android guest, actual extractor or server service is executed.
The production coordinator is unchanged; spies count real host file inventories,
hashes, links, copy fallbacks and metadata writes. Timings are fixture timings,
not preparation estimates. Output goes to stdout for review or a caller file.
"""
import hashlib
import io
import json
import platform
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime import server_data_generation as data
from tests.test_server_data_generation import ServerDataGenerationTests

def main():
    case=ServerDataGenerationTests();case.setUp()
    rows=[]
    def measure(name, operation):
        info={'phase':name,'inventoryCalls':0,'inventoryPayloadBytesRead':0,'cloneCalls':0,'linkedPayloadBytes':0,'copiedPayloadBytes':0,'metadataBytesWritten':0,'extractorInvocations':0,'capabilityInvocations':0,'allTrackedHashBytesRead':0,'reuseReasons':[]}
        original_inventory,original_clone,original_atomic,original_identity,original_link,original_copy=(data.inventory,data.clone,data.storage.atomic,data.world_io.identity,data.os.link,data.world_io.copy_stream)
        def inventory(root):
            result=original_inventory(root);info['inventoryCalls']+=1;info['inventoryPayloadBytesRead']+=sum(x['bytes'] for x in result.values());return result
        def clone(a,b):info['cloneCalls']+=1;return original_clone(a,b)
        def atomic(path,raw):info['metadataBytesWritten']+=len(raw);return original_atomic(path,raw)
        def identity(path,maximum):
            result=original_identity(path,maximum);info['allTrackedHashBytesRead']+=result['bytes'];return result
        def link(source,target,**kw):
            result=original_link(source,target,**kw);info['linkedPayloadBytes']+=Path(source).stat().st_size;return result
        def copying(source,target,*a,**kw):
            start=source.tell();result=original_copy(source,target,*a,**kw);info['copiedPayloadBytes']+=source.tell()-start;return result
        def execute(command,*a,**kw):
            info['capabilityInvocations' if command[1:]==['--esteria-order-capabilities'] else 'extractorInvocations']+=1
            return case.fake_execute(command,*a,**kw)
        started=time.monotonic()
        with patch.object(data,'inventory',side_effect=inventory),patch.object(data,'clone',side_effect=clone),patch.object(data.storage,'atomic',side_effect=atomic),patch.object(data.world_io,'identity',side_effect=identity),patch.object(data.storage,'identity',side_effect=identity),patch.object(data.os,'link',side_effect=link),patch.object(data.world_io,'copy_stream',side_effect=copying),patch.object(data,'execute',side_effect=execute):
            result=operation(info)
        info['elapsedSeconds']=round(time.monotonic()-started,6);rows.append(info);return result
    try:
        receipt=measure('initial-preparation',lambda info:case.generate(progress=info['reuseReasons'].append))
        measure('unchanged-warm-preparation',lambda info:case.generate(progress=info['reuseReasons'].append))
        measure('session-admission-data-verification-only',lambda info:data.verify_completed(case.store/'generations'/receipt['generation'],receipt['inputs']))
        case.doCleanups();case=ServerDataGenerationTests();case.setUp()
        try:
            with redirect_stdout(io.StringIO()), patch.object(data.formats,'check_server_data',return_value={'checks_passed':False,'error_count':1,'errors':[{'path':'dbc/Map.dbc','error':'intentional fixture failure'}]}):
                with patch.object(data,'execute',side_effect=case.fake_execute):case.generate()
        except ValueError as error:
            if 'intentional fixture failure' not in str(error):raise
        else:raise AssertionError('Controlled preflight failure did not occur')
        measure('retained-completed-phases-and-final-assembly-retry',lambda info:case.generate(progress=info['reuseReasons'].append))
        for row in rows:row['reuseReasons']=[x for x in row['reuseReasons'] if 'reused' in x]
        out={'scope':'host-linux-instrumented-production-python-coordinator-synthetic-storage-fixture','realExtractorExecution':False,'ownerGameData':False,'androidOrProotExecution':False,'nativeServiceStartupExecuted':False,'counts':'Inventory bytes count complete payload SHA reads. Tracked hashes include helper/import/order metadata. Small header reads are not included. Metadata writes exclude simulated extractor writes. Clone uses real host hardlinks; no fallbacks forced. Session sample is data subphase only, excluding SQL and binaries.','preparedFixturePayloadBytes':sum(row['bytes'] for row in receipt['files'].values()),'environment':dict(system=platform.system(),machine=platform.machine(),python=platform.python_version()),'sourceSha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('runtime/server_data_generation.py','runtime/server_data_preflight.py','runtime/world_io.py','tests/test_server_data_generation.py','tools/measure_prepared_data_reads.py')},'measurements':rows}
        print(json.dumps(out,indent=2))
    finally:case.doCleanups()


if __name__=='__main__':main()
