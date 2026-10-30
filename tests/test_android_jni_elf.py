import struct
import unittest
from tools import android_jni_elf

def fixture(name='libesteria_process.so'):
    data=bytearray(2048); data[:7]=b'\x7fELF\x02\x01\x01'
    names=sorted(android_jni_elf.DEPENDENCIES[name])+[name]; strings=b''; indices=[]
    for value in names: indices.append(len(strings)); strings+=value.encode()+b'\0'
    data[1024:1024+len(strings)]=strings
    tags=[(1,index) for index in indices[:-1]]+[(14,indices[-1]),(5,0x4400),(10,len(strings)),(0,0)]
    for i,pair in enumerate(tags): struct.pack_into('<qQ',data,600+i*16,*pair)
    segments=[(1,5,0,0,0,512,512,16384),(1,6,512,0x4200,0,1536,1536,16384),
              (2,6,600,0x4258,0,len(tags)*16,len(tags)*16,8),(0x6474e551,6,0,0,0,0,0,16)]
    struct.pack_into('<HHIQQ',data,16,3,183,1,0,64);struct.pack_into('<HHH',data,52,64,56,len(segments))
    for i,segment in enumerate(segments):struct.pack_into('<IIQQQQQQ',data,64+i*56,*segment)
    return data

class JniElf(unittest.TestCase):
    def test_both_source_bridge_contracts(self):
        for name in android_jni_elf.DEPENDENCIES:
            self.assertEqual(android_jni_elf.inspect(fixture(name),name)['minimumLoadAlignment'],16384)
    def test_foreign_arch_entry_stack_alignment_wx_and_interpreter_rejected(self):
        for offset,fmt,value in [(18,'<H',62),(24,'<Q',384),(64+3*56+4,'<I',7),
                                  (64+48,'<Q',4096),(64+4,'<I',7),(64+2*56,'<I',3)]:
            data=fixture();struct.pack_into(fmt,data,offset,value)
            with self.subTest(offset=offset),self.assertRaises(ValueError):android_jni_elf.inspect(data,'libesteria_process.so')
    def test_runtime_search_path_text_relocation_and_unknown_name_rejected(self):
        for tag in (15,22,29):
            data=fixture();struct.pack_into('<qQ',data,600,tag,0)
            with self.subTest(tag=tag),self.assertRaises(ValueError):android_jni_elf.inspect(data,'libesteria_process.so')
        for name in ('libother.so','libesteria-presentation.so'):
            with self.assertRaises(ValueError):android_jni_elf.inspect(fixture(),name)

if __name__=='__main__':unittest.main()
