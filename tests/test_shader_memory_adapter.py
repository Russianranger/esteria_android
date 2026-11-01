"""Pinned-reader/emitter memory/equivalence fixtures, without owner data or GPU proof."""
import contextlib
import gc
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import tracemalloc
import unittest
from unittest.mock import Mock, patch
from runtime import stock_content_inspection as stock
from runtime import stock_shader_translate as adapter

def tokens(*words): return struct.pack('<%dI' % len(words), *words)
# The pinned source's tests/test_translate.py bytecode fixtures.
VERTEX=tokens(0xfffe0200,0x0200001f,0x80000000,0x900f0000,0x02000001,0xc00f0000,0x90e40000,0xffff)
PIXEL=tokens(0xffff0200,0x02000001,0x800f0800,0xa0e40000,0xffff)
WEATHER=tokens(0xfffe0200,0x0200001f,0x80000000,0x900f0000,0x02000001,0xc00f0000,0x90e40000,0x02000001,0xc0010001,0xa0000000,0xffff)
def container(*codes):
    data=bytearray(struct.pack('<3I',0x47585348,0x10003,len(codes)))
    for code in codes:
        data.extend(struct.pack('<IIHHI',0,0,0,0,len(code)));data.extend(code);data.extend(b'\0'*(-len(data)%4))
    return bytes(data)

@unittest.skipUnless(os.environ.get('ESTERIA_CLIENT_SOURCE'),'exact pinned shader source not supplied')
class ShaderMemoryAdapter(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        source=Path(os.environ['ESTERIA_CLIENT_SOURCE'])/'Tools/VulkanShaders'
        self.tools=self.root/'tools';self.tools.mkdir()
        for name in stock.storage.TOOL_FILES:
            target=self.tools/name;target.parent.mkdir(parents=True,exist_ok=True)
            if name!='bin/glslangValidator':shutil.copyfile(source/name,target)
            else:
                # Structural compiler fixture: not real GLSL/SPIR-V validation.
                target.write_text('#!/usr/bin/env python3\nimport struct,sys\nout=sys.argv[sys.argv.index("-o")+1]\nstage=sys.argv[sys.argv.index("-S")+1]\nopen(out,"wb").write(struct.pack("<10I",0x07230203,0x10000,0,3,0,(5<<16)|15,0 if stage=="vert" else 4,1,0x6e69616d,0))\nprint("; SPIR-V structural fixture")\n');target.chmod(0o700)
        (self.tools/'shader-tools.json').write_bytes(stock.storage.encoded(dict(formatVersion=1,clientRevision=stock.CLIENT_REVISION,files={n:stock.storage.identity(self.tools/n,64<<20) for n in stock.storage.TOOL_FILES})))
        self.reader,self.manifest=stock.load_reader(self.tools,stock.CLIENT_REVISION)
        old=sys.dont_write_bytecode;sys.dont_write_bytecode=True;self.addCleanup(setattr,sys,'dont_write_bytecode',old)
        self.translate=importlib.import_module(self.reader.__package__+'.translate')
        namespace={'__name__':'_memory_fixture','__file__':str(source/'tests/test_archive.py')}
        with patch.dict(sys.modules,{'bls':sys.modules[self.reader.__package__]}):exec(compile((source/'tests/test_archive.py').read_text(),'pinned-mpq-fixture','exec'),namespace)
        self.make_mpq=namespace['make_mpq'];self.data=self.root/'client/Data';self.data.mkdir(parents=True)
    def archive(self,name,members,compressed=False):
        path=self.data/name;self.make_mpq(path,[(n,b,0) for n,b in members.items()],compressed=compressed);return path
    def prepare(self):
        self.archive('common.MPQ',{'Shaders\\Vertex\\vs_2_0\\Basic.bls':container(VERTEX,VERTEX),'Shaders\\Vertex\\vs_2_0\\Weather.bls':container(WEATHER),'Shaders\\Pixel\\ps_2_0\\Basic.bls':container(PIXEL)})
        self.archive('enUS/locale-enUS.MPQ',{})
        self.archive('patch-Z.MPQ',{'Shaders\\Pixel\\ps_2_0\\Override.bls':container(PIXEL)},True)
        folder=self.data/'patch-ZZZ.MPQ/Shaders/Vertex/vs_2_0';folder.mkdir(parents=True);(folder/'Folder.bls').write_bytes(container(VERTEX))
    @staticmethod
    def files(path):return {str(p.relative_to(path)):p.read_bytes() for p in path.rglob('*') if p.is_file()}
    def test_original_manifest_index_glsl_and_companion_bytes_match(self):
        self.prepare();original,changed=self.root/'original',self.root/'bounded'
        args=['--data',str(self.data),'--locale','enUS','--strict','--glslang',str(self.tools/'bin/glslangValidator')]
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.translate.main(args+['--out',str(original)]),0)
            with adapter.bounded_adapter(self.reader,self.translate):self.assertEqual(self.translate.main(args+['--out',str(changed)]),0)
        self.assertEqual(self.files(original),self.files(changed));self.assertIn('companion ',(changed/'manifest.txt').read_text())
        self.assertEqual(stock.storage.tool_identity(self.tools,stock.CLIENT_REVISION),self.manifest)
    def test_verified_original_entry_does_not_mutate_provider(self):
        self.prepare();out=self.root/'wrapped'
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            result=adapter.run(self.tools,stock.CLIENT_REVISION,['--strict','--client',str(self.data.parent),'--locale','enUS','--glslang',str(self.tools/'bin/glslangValidator'),'--out',str(out)])
        self.assertEqual(result,0);self.assertIn('record ',(out/'manifest.txt').read_text());self.assertEqual(stock.storage.tool_identity(self.tools,stock.CLIENT_REVISION),self.manifest)
    def test_strict_invalid_and_refused_records_preserve_failure_semantics(self):
        cases=[b'bad',container(VERTEX)[:-1],container(PIXEL),container(tokens(0xfffe0200,0x0000dead,0xffff))]
        for index,bad in enumerate(cases):
            with self.subTest(index=index):
                self.archive('common.MPQ',{'Shaders\\Vertex\\vs_2_0\\Bad.bls':bad,'Shaders\\Pixel\\ps_2_0\\Basic.bls':container(PIXEL)})
                outputs=[]
                for bounded in (False,True):
                    path=self.root/('failure-'+str(index)+'-'+str(bounded));path.mkdir();(path/'manifest.txt').write_text('previous synthetic output')
                    args=['--data',str(self.data),'--locale','enUS','--strict','--glslang',str(self.tools/'bin/glslangValidator'),'--out',str(path)]
                    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()),adapter.bounded_adapter(self.reader,self.translate) if bounded else contextlib.nullcontext():
                        rc=self.translate.main(args)
                    outputs.append((rc,(path/'manifest.txt').read_bytes() if (path/'manifest.txt').exists() else None))
                self.assertEqual(outputs[0],outputs[1]);self.assertNotEqual(outputs[0][0],0)
    def test_packed_stack_budget_precedes_table_decode(self):
        self.prepare()
        with adapter.bounded_adapter(self.reader,self.translate),patch.object(stock,'MAX_TABLE_ENTRIES',1),patch.object(stock,'read_decrypted_table') as decode:
            with self.assertRaisesRegex(ValueError,'table memory bound before allocation'):self.reader.archives(self.data,'enUS')
            decode.assert_not_called()
        with adapter.bounded_adapter(self.reader,self.translate):
            archives=self.reader.archives(self.data,'enUS')
            try:self.assertTrue(any(isinstance(m.hash_table,stock.PackedTable) for _,m in archives if hasattr(m,'hash_table')))
            finally:
                for _,m in archives:m.close()
    def test_listfile_limit_precedes_payload_allocation(self):
        self.archive('common.MPQ',{})
        with adapter.bounded_adapter(self.reader,self.translate):
            archives=self.reader.archives(self.data,'enUS');archive=archives[0][1]
            try:
                index=archive.find('(listfile)');struct.pack_into('<I',archive.block_table.raw,index*16+8,adapter.MAX_LISTFILE+1)
                actual=archive.f;archive.f=Mock(wraps=actual)
                with self.assertRaisesRegex(ValueError,'before allocation'):archive.read_file('(listfile)')
                archive.f.read.assert_not_called()
            finally:
                for _,m in archives:m.close()
    def test_record_bounds_and_emitter_ir_release(self):
        self.prepare()
        with adapter.bounded_adapter(self.reader,self.translate):
            records=self.reader.enumerate_records(self.data,'enUS',strict=True);self.assertTrue(records);self.assertFalse(any(hasattr(r.sh,'insts') for r in records))
            rec=records[0];rec.names=[rec.key];emitter=self.translate.Emitter(rec);self.assertTrue(hasattr(emitter.sh,'insts'));emitter.run();self.assertFalse(hasattr(emitter.sh,'insts'));self.assertFalse(emitter.body)
        with self.assertRaisesRegex(ValueError,'bounded 1 MiB'):list(adapter.container_records(container(b'\0'*(adapter.MAX_RECORD_BYTES+4)),True))
        with adapter.bounded_adapter(self.reader,self.translate),patch.object(adapter,'MAX_CODE_BYTES',1):
            with self.assertRaisesRegex(ValueError,'bytecode exceeds memory bound'):self.reader.enumerate_records(self.data,'enUS',strict=True)
    def test_wrapper_main_propagates_transient_memory_pause(self):
        arguments=['stock_shader_translate.py','--tools',str(self.tools),'--client-revision',stock.CLIENT_REVISION,'--client',str(self.data.parent),'--locale','enUS','--glslang',str(self.tools/'bin/glslangValidator'),'--out',str(self.root/'paused'),'--strict']
        with patch.object(sys,'argv',arguments),patch.object(adapter,'run',side_effect=adapter.world_io.PreparationPaused()),patch.object(adapter.world_io,'print_pause') as marker:
            self.assertEqual(adapter.main(),adapter.world_io.PAUSED_EXIT_CODE);marker.assert_called_once()
        self.assertFalse((self.root/'paused').exists())
    def test_permutation_ir_memory_is_not_retained(self):
        codes=[tokens(0xfffe0300,*([0]*2048),0x0001fffe,i,0xffff) for i in range(96)]
        self.archive('common.MPQ',{'Shaders\\Vertex\\vs_3_0\\Many.bls':container(*codes)})
        def measured(bounded):
            gc.collect();tracemalloc.start()
            try:
                with adapter.bounded_adapter(self.reader,self.translate) if bounded else contextlib.nullcontext():
                    records=self.reader.enumerate_records(self.data,'enUS',strict=True)
                    summary=[(r.key,r.md5,r.sh.kind if r.sh is not None else None) for r in records];current,peak=tracemalloc.get_traced_memory()
                return summary,current,peak
            finally:tracemalloc.stop()
        original,old_current,old_peak=measured(False);bounded,new_current,new_peak=measured(True)
        self.assertEqual(original,bounded);self.assertLess(new_peak,old_peak*.45);self.assertLess(new_current,old_current*.2)
        proof=dict(scope='host-pinned-reader-encrypted-synthetic-shader-memory',records=len(codes),recordBytes=len(codes[0]),baselinePeakBytes=old_peak,boundedPeakBytes=new_peak,baselineRetainedBytes=old_current,boundedRetainedBytes=new_current,recordSummariesEqual=True,compilerExecuted=False,ownerData=False,androidExecuted=False,gameplayQualified=False)
        print('SHADER_MEMORY_FIXTURE='+json.dumps(proof,sort_keys=True))
        if os.environ.get('ESTERIA_SHADER_MEMORY_EVIDENCE'):Path(os.environ['ESTERIA_SHADER_MEMORY_EVIDENCE']).write_text(json.dumps(proof,indent=2)+'\n')

if __name__=='__main__':unittest.main()
