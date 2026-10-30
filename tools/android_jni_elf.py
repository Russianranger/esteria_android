"""Strict ELF contract for the two source-built ARM64 Android JNI bridges."""
import struct

DEPENDENCIES={
    'libesteria_process.so': {'libc.so','libdl.so','libm.so'},
    'libesteria-presentation.so': {'libandroid.so','libc.so','libdl.so','libm.so'},
}

def require(condition,reason):
    if not condition: raise ValueError(reason)

def inspect(data,name):
    require(name in DEPENDENCIES and 64<=len(data)<=16*1024*1024 and data[:7]==b'\x7fELF\x02\x01\x01','invalid-jni-elf')
    kind,machine,version,entry,phoff=struct.unpack_from('<HHIQQ',data,16)
    ehsize,phsize,count=struct.unpack_from('<HHH',data,52)
    require((kind,machine,version,entry,ehsize,phsize)==(3,183,1,0,64,56) and
            1<=count<=32 and phoff>=64 and phoff+count*56<=len(data),'invalid-jni-target')
    loads=[]; dynamic=[]; stacks=[]
    for i in range(count):
        typ,flags,offset,virtual,physical,size,memory,alignment=struct.unpack_from('<IIQQQQQQ',data,phoff+i*56)
        require(offset<=len(data) and size<=len(data)-offset,'jni-segment-bounds')
        require(typ!=3,'jni-must-not-have-interpreter')
        if typ==1:
            require(size<=memory and alignment>=16384 and alignment&(alignment-1)==0 and
                    virtual%alignment==offset%alignment and flags&3!=3,'jni-load-contract')
            loads.append((offset,virtual,size,alignment))
        elif typ==2:
            require(0<size<=65536 and size%16==0,'jni-dynamic-bounds'); dynamic.append((offset,size))
        elif typ==0x6474e551: stacks.append(flags)
    require(loads and len(dynamic)==1 and len(stacks)==1 and not stacks[0]&1,'jni-segment-contract')
    tags={}; offset,size=dynamic[0]; ended=False
    for pos in range(offset,offset+size,16):
        tag,value=struct.unpack_from('<qQ',data,pos)
        if tag==0: ended=True;break
        tags.setdefault(tag,[]).append(value)
    require(ended and not any(t in tags for t in (15,22,29)) and len(tags.get(5,[]))==1 and
            len(tags.get(10,[]))==1 and len(tags.get(14,[]))==1,'jni-dynamic-contract')
    address,length=tags[5][0],tags[10][0]
    require(0<length<=1024*1024,'jni-string-limit')
    mapping=[off+address-virt for off,virt,size,align in loads if virt<=address and address+length<=virt+size]
    require(len(mapping)==1,'jni-strings-not-file-backed'); strings=data[mapping[0]:mapping[0]+length]
    def string(index):
        require(0<=index<length,'jni-string-index'); end=strings.find(b'\0',index)
        require(end>index,'jni-string-termination'); return strings[index:end].decode('ascii')
    needed=[string(index) for index in tags.get(1,[])]
    require(string(tags[14][0])==name and len(needed)==len(set(needed)) and set(needed)==DEPENDENCIES[name],'jni-dependency-contract')
    return dict(machine='AArch64',type='DYN',soname=name,needed=sorted(needed),minimumLoadAlignment=min(x[3] for x in loads),executableStack=False)
