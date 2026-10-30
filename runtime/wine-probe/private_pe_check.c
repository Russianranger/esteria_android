/* Real source-built EXE/DLL loader, relocation, protection and shared-section checks. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PREFERRED ((void *)(uintptr_t)0x180000000ULL)
#define SHARED_INITIAL 0x11223344
#define SHARED_PARENT 0x10203040
#define SHARED_CHILD 0x10203041
#define SHARED_FINAL 0x10203042
#define PRIVATE_INITIAL 0x13579bdf
#define PRIVATE_CHANGED 0x55667788

typedef unsigned long (*Answer)(void);
typedef struct {
    HMODULE module;
    volatile LONG *private_value, *shared;
    const unsigned char *readonly;
    unsigned char *zero;
    volatile LONG **relocated;
    Answer answer;
} Fixture;

static int failure(const char *stage) {
    fprintf(stderr,"ESTERIA_PE_CHECK_FAIL stage=%s error=%lu\n",stage,(unsigned long)GetLastError());
    return 1;
}
static int protect_is(Fixture *f,const void *address,DWORD a,DWORD b) {
    MEMORY_BASIC_INFORMATION info;
    SIZE_T bytes=VirtualQuery(address,&info,sizeof(info));
    return bytes==sizeof(info)&&info.State==MEM_COMMIT&&info.Type==MEM_IMAGE&&
        info.AllocationBase==(void *)f->module&&(info.Protect==a||info.Protect==b);
}
static int load_fixture(Fixture *f) {
    char path[MAX_PATH];DWORD n=GetModuleFileNameA(NULL,path,sizeof(path));
    if(!n||n>=sizeof(path))return failure("executable-path");
    char *slash=strrchr(path,'\\');if(!slash)return failure("executable-directory");
    if((size_t)(slash-path)+1+strlen("private-pe-fixture.dll")>=sizeof(path))return failure("dll-path-bound");
    strcpy(slash+1,"private-pe-fixture.dll");
    memset(f,0,sizeof(*f));f->module=LoadLibraryA(path);if(!f->module)return failure("load-dll");
    f->private_value=(volatile LONG *)(void *)GetProcAddress(f->module,"fixture_private");
    f->shared=(volatile LONG *)(void *)GetProcAddress(f->module,"fixture_shared");
    f->readonly=(const unsigned char *)(void *)GetProcAddress(f->module,"fixture_readonly");
    f->zero=(unsigned char *)(void *)GetProcAddress(f->module,"fixture_zero");
    f->relocated=(volatile LONG **)(void *)GetProcAddress(f->module,"fixture_relocated_pointer");
    FARPROC proc=GetProcAddress(f->module,"fixture_answer");
    _Static_assert(sizeof(proc)==sizeof(f->answer),"Function pointer size");memcpy(&f->answer,&proc,sizeof(proc));
    if(!f->private_value||!f->shared||!f->readonly||!f->zero||!f->relocated||!f->answer)return failure("exports");
    IMAGE_DOS_HEADER *dos=(IMAGE_DOS_HEADER *)f->module;
    if(dos->e_magic!=IMAGE_DOS_SIGNATURE||dos->e_lfanew<64||dos->e_lfanew>4096)return failure("dos-header");
    IMAGE_NT_HEADERS64 *nt=(IMAGE_NT_HEADERS64 *)((unsigned char *)f->module+dos->e_lfanew);
    if(nt->Signature!=IMAGE_NT_SIGNATURE||nt->FileHeader.Machine!=IMAGE_FILE_MACHINE_AMD64||
       nt->OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR64_MAGIC)
        return failure("pe-header");
    IMAGE_SECTION_HEADER *sections=IMAGE_FIRST_SECTION(nt);int shared=0;
    if(!nt->FileHeader.NumberOfSections||nt->FileHeader.NumberOfSections>64)return failure("section-count");
    for(unsigned i=0;i<nt->FileHeader.NumberOfSections;i++)if(!memcmp(sections[i].Name,".shared",7)){
        DWORD required=IMAGE_SCN_MEM_READ|IMAGE_SCN_MEM_WRITE|IMAGE_SCN_MEM_SHARED;
        shared=(sections[i].Characteristics&required)==required&&sections[i].SizeOfRawData>0;
    }
    if(!shared)return failure("real-shared-section");
    if(*f->private_value!=PRIVATE_INITIAL||memcmp(f->readonly,"Esteria image mapping fixture",29)||*f->relocated!=f->private_value)
        return failure("initialized-and-relocated-data");
    for(unsigned i=0;i<8192;i++)if(f->zero[i])return failure("zero-fill");
    if(f->answer()!=((unsigned long)PRIVATE_INITIAL^'E'))return failure("executable-text");
    if(!protect_is(f,f->module,PAGE_READONLY,PAGE_READONLY)||
       !protect_is(f,(const void *)f->answer,PAGE_EXECUTE_READ,PAGE_EXECUTE_READ)||
       !protect_is(f,f->readonly,PAGE_READONLY,PAGE_READONLY)||
       !protect_is(f,(const void *)f->private_value,PAGE_READWRITE,PAGE_WRITECOPY)||
       !protect_is(f,f->zero,PAGE_READWRITE,PAGE_WRITECOPY)||
       !protect_is(f,(const void *)f->shared,PAGE_READWRITE,PAGE_WRITECOPY))return failure("image-protections");
    return 0;
}
static void event_names(DWORD pid,char *ready,char *release) {
    snprintf(ready,80,"Local\\EsteriaPeReady-%lu",(unsigned long)pid);
    snprintf(release,80,"Local\\EsteriaPeRelease-%lu",(unsigned long)pid);
}
static int child_check(DWORD parent) {
    Fixture f;char ready_name[80],release_name[80];event_names(parent,ready_name,release_name);
    HANDLE ready=OpenEventA(EVENT_MODIFY_STATE,FALSE,ready_name),release=OpenEventA(SYNCHRONIZE,FALSE,release_name);
    if(!ready||!release)return failure("child-open-events");
    if(load_fixture(&f))return 1;
    if(*f.shared!=SHARED_PARENT)return failure("child-observed-parent-shared-write");
    if(InterlockedExchange(f.shared,SHARED_CHILD)!=SHARED_PARENT||!SetEvent(ready))return failure("child-share-update");
    if(WaitForSingleObject(release,30000)!=WAIT_OBJECT_0||*f.shared!=SHARED_FINAL)return failure("child-observed-final-shared-write");
    if(*f.private_value!=PRIVATE_INITIAL||f.zero[0]||f.zero[8191])return failure("private-data-isolation");
    if(!FreeLibrary(f.module))return failure("child-unload");
    CloseHandle(ready);CloseHandle(release);
    puts("ESTERIA_PE_CHILD_SHARED_PASS");return 0;
}
static int parent_check(void) {
    int result=1;Fixture f;memset(&f,0,sizeof(f));PROCESS_INFORMATION child;memset(&child,0,sizeof(child));
    HANDLE ready=NULL,release=NULL;void *reserved=VirtualAlloc(PREFERRED,4*1024*1024,MEM_RESERVE,PAGE_NOACCESS);
    if(reserved!=PREFERRED)return failure("reserve-preferred-image-base");
    if(load_fixture(&f))goto done;
    if((void *)f.module==PREFERRED){failure("forced-relocation");goto done;}
    if(*f.shared!=SHARED_INITIAL){failure("shared-initial-data");goto done;}
    DWORD old=0,restored=0;
    /* Same-value write deliberately dirties the executable file's private page.
       Linux control and opt-in anonymous-image implementation must both retain it. */
    if(!VirtualProtect((void *)f.answer,1,PAGE_READWRITE,&old)){failure("text-to-writable");goto done;}
    volatile unsigned char *text=(volatile unsigned char *)(void *)f.answer;unsigned char instruction=*text;*text=instruction;
    if(!VirtualProtect((void *)f.answer,1,old,&restored)||(restored!=PAGE_READWRITE&&restored!=PAGE_WRITECOPY)||
       !FlushInstructionCache(GetCurrentProcess(),(void *)f.answer,1)||
       !protect_is(&f,(const void *)f.answer,PAGE_EXECUTE_READ,PAGE_EXECUTE_READ)||
       f.answer()!=((unsigned long)PRIVATE_INITIAL^'E')){failure("dirty-text-to-executable");goto done;}
    if(!VirtualProtect((void *)f.readonly,1,PAGE_READWRITE,&old)){failure("readonly-to-writable");goto done;}
    ((volatile unsigned char *)f.readonly)[0]='X';
    if(!VirtualProtect((void *)f.readonly,1,old,&restored)||(restored!=PAGE_READWRITE&&restored!=PAGE_WRITECOPY)||
       !protect_is(&f,f.readonly,PAGE_READONLY,PAGE_READONLY)||((const volatile unsigned char *)f.readonly)[0]!='X')
        {failure("readonly-protection-restore");goto done;}
    *f.private_value=PRIVATE_CHANGED;f.zero[0]=17;f.zero[8191]=31;InterlockedExchange(f.shared,SHARED_PARENT);
    char ready_name[80],release_name[80];event_names(GetCurrentProcessId(),ready_name,release_name);
    ready=CreateEventA(NULL,TRUE,FALSE,ready_name);if(!ready||GetLastError()==ERROR_ALREADY_EXISTS){failure("owned-ready-event");goto done;}
    release=CreateEventA(NULL,TRUE,FALSE,release_name);if(!release||GetLastError()==ERROR_ALREADY_EXISTS){failure("owned-release-event");goto done;}
    char executable[MAX_PATH],command[2*MAX_PATH];DWORD n=GetModuleFileNameA(NULL,executable,sizeof(executable));
    if(!n||n>=sizeof(executable)){failure("child-executable-path");goto done;}
    int length=snprintf(command,sizeof(command),"\"%s\" --child %lu",executable,(unsigned long)GetCurrentProcessId());
    if(length<1||(size_t)length>=sizeof(command)){failure("child-arguments");goto done;}
    STARTUPINFOA startup;memset(&startup,0,sizeof(startup));startup.cb=sizeof(startup);
    if(!CreateProcessA(executable,command,NULL,NULL,FALSE,0,NULL,NULL,&startup,&child)){failure("child-create");goto done;}
    HANDLE waits[2]={ready,child.hProcess};
    if(WaitForMultipleObjects(2,waits,FALSE,30000)!=WAIT_OBJECT_0||
       WaitForSingleObject(child.hProcess,0)!=WAIT_TIMEOUT||*f.shared!=SHARED_CHILD)
        {failure("parent-observed-child-shared-write");goto done;}
    if(*f.private_value!=PRIVATE_CHANGED||f.zero[0]!=17||f.zero[8191]!=31)
        {failure("parent-private-data-retained");goto done;}
    InterlockedExchange(f.shared,SHARED_FINAL);
    if(!SetEvent(release)||WaitForSingleObject(child.hProcess,30000)!=WAIT_OBJECT_0){failure("child-finish");goto done;}
    DWORD exit_code=99;if(!GetExitCodeProcess(child.hProcess,&exit_code)||exit_code!=0){failure("child-exit");goto done;}
    result=0;
done:
    if(child.hProcess){if(WaitForSingleObject(child.hProcess,0)!=WAIT_OBJECT_0){TerminateProcess(child.hProcess,70);WaitForSingleObject(child.hProcess,5000);}
        CloseHandle(child.hProcess);CloseHandle(child.hThread);}
    if(ready)CloseHandle(ready);
    if(release)CloseHandle(release);
    if(f.module&&!FreeLibrary(f.module)){failure("parent-unload");result=1;}
    if(!VirtualFree(reserved,0,MEM_RELEASE)){failure("release-reserved-base");result=1;}
    if(!result)puts("ESTERIA_PE_IMAGE_CHECK_PASS relocation=1 protections=1 data=1 bss=1 dirty-text=1 shared-cross-process=1");
    return result;
}
int main(int argc,char **argv) {
    if(argc==1)return parent_check();
    if(argc==3&&!strcmp(argv[1],"--child")){
        char *end=NULL;unsigned long pid=strtoul(argv[2],&end,10);
        if(pid&&end&&!*end&&pid<=0xffffffffUL)return child_check((DWORD)pid);
    }
    return failure("arguments");
}
