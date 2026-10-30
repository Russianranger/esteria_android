"""Execute the exact new Wine copy helpers; full Wine/Android gates are separate."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'runtime/wine-probe/android-private-pe-copy.patch'
UPSTREAM_SHA256 = '79dba34fbafbac07719e974b4210c9a3a2f6ed515915c469374783dad9085aab'


def added_function(name):
    added = '\n'.join(line[1:] for line in PATCH.read_text().splitlines()
                      if line.startswith('+') and not line.startswith('+++'))
    start = added.index('static NTSTATUS ' + name + '(')
    opening = added.index('{', start)
    depth = 0
    for end in range(opening, len(added)):
        if added[end] == '{': depth += 1
        elif added[end] == '}':
            depth -= 1
            if not depth: return added[start:end + 1]
    raise AssertionError('Missing complete actual patch helper')


PREFIX = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
typedef uint32_t NTSTATUS;
typedef uint64_t ULONGLONG;
typedef size_t SIZE_T;
typedef struct { union { uint32_t VirtualSize; } Misc; uint32_t SizeOfRawData, VirtualAddress; } IMAGE_SECTION_HEADER;
#define STATUS_SUCCESS ((NTSTATUS)0)
#define STATUS_INVALID_IMAGE_FORMAT ((NTSTATUS)0xc000007b)
#define min(a,b) ((a) < (b) ? (a) : (b))
#define ROUND_SIZE(a,b,m) (((SIZE_T)(b) + ((uintptr_t)(a) & (m)) + (m)) & ~(uintptr_t)(m))
static int mode, calls;
static size_t largest;
static ssize_t controlled_pread(int fd, void *buffer, size_t count, off_t offset)
{
    calls++;
    if (count > largest) largest = count;
    if (mode == 1 && calls == 1) { errno = EINTR; return -1; }
    if (mode == 2) { errno = EIO; return -1; }
    if (mode == 3 || (mode == 4 && calls > 1)) return 0;
    if ((mode == 1 || mode == 4) && count > 3) count = 3;
    return pread(fd, buffer, count, offset);
}
#define pread controlled_pread
'''

SUFFIX = r'''
static void reset(int selected) { mode=selected; calls=0; largest=0; }
static int fixture(void)
{
    int fd=open("source.bin",O_CREAT|O_EXCL|O_RDWR,0600);
    assert(fd>=0 && write(fd,"0123456789abcdef",16)==16);
    return fd;
}
int main(int argc,char **argv)
{
    assert(argc==2);
    if (!strcmp(argv[1],"copy"))
    {
        char out[20];int fd=fixture();reset(1);
        memset(out,0xa5,sizeof(out));
        assert(read_private_pe_file(out,18,fd,0,16,2)==STATUS_SUCCESS);
        assert(calls==7 && !memcmp(out,"0123456789abcdef\0\0",18));
        assert((unsigned char)out[18]==0xa5 && (unsigned char)out[19]==0xa5);
        reset(0);assert(read_private_pe_file(out,6,fd,4,16,0)==STATUS_SUCCESS);
        assert(!memcmp(out,"456789",6));close(fd);
    }
    else if (!strcmp(argv[1],"failures"))
    {
        char out[20];int fd=fixture();
        for(int selected=2;selected<=4;selected++)
        {
            reset(selected);memset(out,0xa5,sizeof(out));
            assert(read_private_pe_file(out,16,fd,0,16,0)==STATUS_INVALID_IMAGE_FORMAT);
            assert(calls <= 2 && (unsigned char)out[19]==0xa5);
        }
        reset(0);assert(ftruncate(fd,8)==0);
        assert(read_private_pe_file(out,16,fd,0,16,0)==STATUS_INVALID_IMAGE_FORMAT);
        close(fd);
    }
    else if (!strcmp(argv[1],"bounds"))
    {
        char out[20];int fd=fixture();reset(0);memset(out,0xa5,sizeof(out));
        assert(read_private_pe_file(out,1,fd,-1,16,0)==STATUS_INVALID_IMAGE_FORMAT);
        assert(read_private_pe_file(out,1,fd,17,16,0)==STATUS_INVALID_IMAGE_FORMAT);
        assert(read_private_pe_file(out,1,fd,0,-1,0)==STATUS_INVALID_IMAGE_FORMAT);
        assert(read_private_pe_file(out,20,fd,0,16,3)==STATUS_INVALID_IMAGE_FORMAT);
        assert(read_private_pe_file(out,1,fd,16,16,1)==STATUS_INVALID_IMAGE_FORMAT);
        assert(calls==0 && (unsigned char)out[0]==0xa5);
        assert(read_private_pe_file(out,0,fd,16,16,0)==STATUS_SUCCESS && calls==0);
        close(fd);
    }
    else if (!strcmp(argv[1],"anonymous"))
    {
        size_t size=3*1024*1024+7;int fd=fixture();reset(0);
        assert(ftruncate(fd,size)==0);
        unsigned char *memory=mmap(NULL,size,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
        assert(memory!=MAP_FAILED);
        assert(read_private_pe_file(memory,size,fd,0,size,0)==STATUS_SUCCESS);
        assert(calls==4 && largest==1024*1024 && !memcmp(memory,"0123456789abcdef",16));
        memset(memory,0x5a,size);char original[16];
        assert(controlled_pread(fd,original,16,0)==16 && !memcmp(original,"0123456789abcdef",16));
        assert(munmap(memory,size)==0);close(fd);
    }
    else if (!strcmp(argv[1],"sections"))
    {
        IMAGE_SECTION_HEADER s[257]={0};
        s[0].VirtualAddress=4096;s[0].Misc.VirtualSize=4096;
        s[1].VirtualAddress=8192;s[1].SizeOfRawData=4096;
        assert(validate_private_pe_sections(s,2,4096,12288,4095)==STATUS_SUCCESS);
        s[1].VirtualAddress=4608;
        assert(validate_private_pe_sections(s,2,4096,12288,4095)==STATUS_INVALID_IMAGE_FORMAT);
        s[1].VirtualAddress=0;
        assert(validate_private_pe_sections(s,2,4096,12288,4095)==STATUS_INVALID_IMAGE_FORMAT);
        s[1].VirtualAddress=12289;
        assert(validate_private_pe_sections(s,2,4096,20480,4095)==STATUS_INVALID_IMAGE_FORMAT);
        s[1].VirtualAddress=8192;s[1].SizeOfRawData=4097;
        assert(validate_private_pe_sections(s,2,4096,12288,4095)==STATUS_INVALID_IMAGE_FORMAT);
        assert(validate_private_pe_sections(s,257,4096,12288,4095)==STATUS_INVALID_IMAGE_FORMAT);
        assert(validate_private_pe_sections(s,0,4096,12288,(size_t)-1)==STATUS_INVALID_IMAGE_FORMAT);
        assert(validate_private_pe_sections(s,0,4096,12288,4094)==STATUS_INVALID_IMAGE_FORMAT);
    }
    else abort();
    puts("Checked private PE helper passed; no Wine/Android execution claimed");
    return 0;
}
'''


class CheckedPrivateCopy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='esteria-wine-copy-')
        cls.root = Path(cls.temporary.name)
        source = cls.root / 'helper.c'
        source.write_text(PREFIX + added_function('read_private_pe_file') + '\n' +
                          added_function('validate_private_pe_sections') + SUFFIX)
        cls.binary = cls.root / 'helper'
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-O2',str(source),'-o',str(cls.binary)],
                       check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def run_case(self, case):
        with tempfile.TemporaryDirectory(dir=self.root) as raw:
            result = subprocess.run([str(self.binary),case],cwd=raw,check=True,capture_output=True,timeout=5)
            self.assertIn(b'Checked private PE helper passed',result.stdout)

    def test_partial_reads_eintr_offset_and_legal_zero_tail(self): self.run_case('copy')
    def test_io_error_early_eof_and_shrinking_file_fail(self): self.run_case('failures')
    def test_invalid_extent_fails_without_reading_or_writing(self): self.run_case('bounds')
    def test_bounded_real_anonymous_copy_preserves_original_file(self): self.run_case('anonymous')
    def test_overlapping_shared_or_private_sections_and_excess_count_rejected(self): self.run_case('sections')


@unittest.skipUnless(os.environ.get('ESTERIA_WINE_VIRTUAL_SOURCE'), 'requires the exact pinned Wine virtual.c')
class ActualPatchApplication(unittest.TestCase):
    def test_exact_source_applies_without_fuzz_and_preserves_shared_mapping_calls(self):
        original=Path(os.environ['ESTERIA_WINE_VIRTUAL_SOURCE']).read_bytes()
        self.assertEqual(hashlib.sha256(original).hexdigest(),UPSTREAM_SHA256)
        with tempfile.TemporaryDirectory(prefix='esteria-wine-patch-') as raw:
            root=Path(raw);path=root/'dlls/ntdll/unix/virtual.c';path.parent.mkdir(parents=True)
            path.write_bytes(original)
            subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(PATCH)],cwd=root,check=True,
                           capture_output=True,timeout=10)
            changed=path.read_text();before=original.decode()
            start='        if ((sec[i].Characteristics & IMAGE_SCN_MEM_SHARED) &&'
            end='        TRACE_(module)( "mapping %s section'
            self.assertEqual(changed[changed.index(start):changed.index(end)],
                             before[before.index(start):before.index(end)])
            self.assertIn('BOOL private_pe_copy = copy_setting && !strcmp( copy_setting, "1" );',changed)
            self.assertIn('if (private_pe_copy) goto done;',changed)


if __name__=='__main__': unittest.main()
