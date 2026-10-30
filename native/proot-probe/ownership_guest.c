/* SPDX-License-Identifier: GPL-3.0-only */
/* Three detached glibc processes, bounded by alarms, for tracer-death tests. */
#define _GNU_SOURCE
#include <errno.h>
#include <dirent.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>

static void check(int ok, const char *what) {
    if (!ok) { fprintf(stderr,"ownership fixture: %s: %s\n",what,strerror(errno));exit(70); }
}
static unsigned long long start_ticks(pid_t pid) {
    char path[64],line[4096];snprintf(path,sizeof(path),"/proc/%ld/stat",(long)pid);
    FILE *input=fopen(path,"re");check(input!=NULL,"open stat");
    check(fgets(line,sizeof(line),input)!=NULL,"read stat");check(fclose(input)==0,"close stat");
    char *cursor=strrchr(line,')');check(cursor!=NULL,"stat command");cursor+=2;
    char *save=NULL,*token=strtok_r(cursor," ",&save);
    for(int field=3;field<22;field++){check(token!=NULL,"stat field");token=strtok_r(NULL," ",&save);}
    check(token!=NULL,"start time");char *end;unsigned long long value=strtoull(token,&end,10);
    check(*end=='\0'&&value>0,"start time integer");return value;
}
static pid_t tracer_pid(void) {
    FILE *input=fopen("/proc/self/status","re");check(input!=NULL,"open status");
    char line[512];long tracer=0;
    while(fgets(line,sizeof(line),input))if(sscanf(line,"TracerPid: %ld",&tracer)==1)break;
    check(fclose(input)==0&&tracer>0,"kernel tracer identity");return (pid_t)tracer;
}
static int finish(pid_t child,const char *work,int graceful,unsigned char *armed,int slot) {
    alarm(30);
    pid_t tracer=tracer_pid();
    printf("ESTERIA_PROOT_OWNER_PID %ld %llu %ld %llu %ld\n",(long)getpid(),start_ticks(getpid()),
        (long)tracer,start_ticks(tracer),(long)getsid(0));check(fflush(stdout)==0,"flush identity");
    if(!graceful){
        /* Android may reject Linux pause() after the tracer is removed. An
           unpatched control must not die from that unrelated SIGSYS. Publish
           readiness only after the final syscall, then make no further calls.
           The existing alarm bounds this deliberately short CPU-only fixture. */
        __atomic_store_n(armed+slot,1,__ATOMIC_RELEASE);
        for(;;)__asm__ __volatile__("pause" ::: "memory");
    }
    char stop[4096],saved[4096];
    check(snprintf(stop,sizeof(stop),"%s/stop",work)>0,"stop path");
    while(access(stop,F_OK)!=0){check(errno==ENOENT,"stop access");usleep(10000);}
    int length=snprintf(saved,sizeof(saved),"%s/saved-%ld",work,(long)getpid());
    check(length>0&&(size_t)length<sizeof(saved),"save path");
    int fd=open(saved,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);check(fd>=0,"create save");
    const char content[]="graceful-persisted\n";
    check(write(fd,content,sizeof(content)-1)==(ssize_t)sizeof(content)-1,"write save");
    check(fsync(fd)==0&&close(fd)==0,"flush save");
    if(child>0){int status;check(waitpid(child,&status,0)==child&&WIFEXITED(status)&&WEXITSTATUS(status)==0,"graceful child exit");}
    printf("ESTERIA_PROOT_OWNER_SAVED %ld\n",(long)getpid());fflush(stdout);return 0;
}
int main(int argc,char **argv) {
    alarm(30);
    check(argc==3&&(strcmp(argv[2],"forced")==0||strcmp(argv[2],"graceful")==0||strcmp(argv[2],"verify")==0),"arguments");
    if(strcmp(argv[2],"verify")==0){
        alarm(10);DIR *directory=opendir(argv[1]);check(directory!=NULL,"verify directory");struct dirent *entry;int count=0;
        while((entry=readdir(directory))!=NULL){
            if(strncmp(entry->d_name,"saved-",6)!=0)continue;
            int fd=openat(dirfd(directory),entry->d_name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);check(fd>=0,"open saved record");
            const char expected[]="graceful-persisted\n";
            char data[64];ssize_t got=read(fd,data,sizeof(data));check(got==(ssize_t)sizeof(expected)-1&&memcmp(data,expected,sizeof(expected)-1)==0,"restored saved record");
            check(close(fd)==0,"close saved record");count++;
        }
        check(closedir(directory)==0&&count==3,"three restored saved records");
        printf("ESTERIA_PROOT_OWNER_SAVE_VERIFY 3\n");return 0;
    }
    /* The root tracee also detaches, so native process-group cleanup cannot
       manufacture an EXITKILL pass for any of the three observed processes. */
    check(setsid()>0,"root setsid");
    unsigned char *armed=NULL;
    if(strcmp(argv[2],"forced")==0){
        char path[4096];int length=snprintf(path,sizeof(path),"%s/armed",argv[1]);
        check(length>0&&(size_t)length<sizeof(path),"armed path");
        int fd=open(path,O_RDWR|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);check(fd>=0,"create armed flags");
        check(ftruncate(fd,3)==0,"size armed flags");
        armed=mmap(NULL,3,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);check(armed!=MAP_FAILED,"map armed flags");
        check(close(fd)==0,"close armed flags");
    }
    pid_t child=fork();check(child>=0,"fork");
    if(child>0)return finish(child,argv[1],strcmp(argv[2],"graceful")==0,armed,0);
    alarm(30);
    check(setsid()>0,"child setsid");
    pid_t grandchild=fork();check(grandchild>=0,"second fork");
    if(grandchild==0)check(setsid()>0,"grandchild setsid");
    return finish(grandchild,argv[1],strcmp(argv[2],"graceful")==0,armed,grandchild==0?2:1);
}
