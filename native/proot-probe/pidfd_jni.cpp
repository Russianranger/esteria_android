// SPDX-License-Identifier: GPL-3.0-only
// Emulator-only process identity observer. No arbitrary PID is ever signalled.
#include <jni.h>
#include <cerrno>
#include <climits>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <map>
#include <mutex>
#include <poll.h>
#include <signal.h>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

namespace {
std::mutex mutex;
std::map<jlong,int> handles;
jlong next_handle=1;
void require(bool ok,const char *message){if(!ok)throw std::runtime_error(message);}
struct Fd { int value; ~Fd(){if(value>=0)close(value);} };
std::string text(JNIEnv *env,jstring value){
    require(value!=nullptr,"Missing probe path");
    const char *raw=env->GetStringUTFChars(value,nullptr);require(raw!=nullptr,"Probe string unavailable");
    std::string result(raw);env->ReleaseStringUTFChars(value,raw);
    require(result.size()<=4096,"Oversized probe path");
    for(unsigned char item:result)require(item>=32&&item<127,"Probe paths must be fixed ASCII paths");
    return result;
}
std::string proc(int pid,const char *name){return "/proc/"+std::to_string(pid)+"/"+name;}
std::string read(const std::string &path,size_t maximum){
    Fd fd{open(path.c_str(),O_RDONLY|O_CLOEXEC)};require(fd.value>=0,"Cannot read owned process identity");
    std::string result;char buffer[4096];
    for(;;){ssize_t count=::read(fd.value,buffer,sizeof(buffer));if(count<0&&errno==EINTR)continue;
        require(count>=0,"Owned process identity read failed");if(!count)break;
        require(result.size()+static_cast<size_t>(count)<=maximum,"Owned process identity exceeds bound");result.append(buffer,static_cast<size_t>(count));}
    return result;
}
bool exited(int fd,int timeout){
    require(timeout>=0&&timeout<=5000,"Invalid probe wait bound");
    timespec now{};require(clock_gettime(CLOCK_MONOTONIC,&now)==0,"Monotonic clock failed");
    const long long deadline=static_cast<long long>(now.tv_sec)*1000+now.tv_nsec/1000000+timeout;
    int left=timeout;
    for(;;){pollfd item{fd,POLLIN,0};int result=poll(&item,1,left);
        if(result<0&&errno==EINTR){require(clock_gettime(CLOCK_MONOTONIC,&now)==0,"Monotonic clock failed");
            left=static_cast<int>(deadline-(static_cast<long long>(now.tv_sec)*1000+now.tv_nsec/1000000));
            if(left<=0)return false;
            continue;}
        require(result>=0&&!(item.revents&(POLLERR|POLLNVAL)),"Owned process descriptor polling failed");
        return result>0&&(item.revents&(POLLIN|POLLHUP));}
}
void identity(int pid,long long ticks,int tracer,const std::string &expected_exe,const std::string &mapping){
    struct stat info{};require(stat(proc(pid,"").c_str(),&info)==0&&info.st_uid==getuid(),"Process belongs to another UID");
    const auto state=read(proc(pid,"stat"),4096);auto end=state.rfind(')');require(end!=std::string::npos,"Invalid process stat");
    std::istringstream fields(state.substr(end+2));std::string value;long long actual_ticks=0,session=0;
    for(int field=3;field<=22;field++){
        require(static_cast<bool>(fields>>value),"Incomplete process stat");
        if(field==6)session=std::stoll(value);
        if(field==22)actual_ticks=std::stoll(value);
    }
    require(actual_ticks==ticks&&ticks>0,"Process start time changed");
    const auto status=read(proc(pid,"status"),65536);std::istringstream lines(status);int actual_tracer=-1;
    while(std::getline(lines,value))if(value.rfind("TracerPid:",0)==0)actual_tracer=std::stoi(value.substr(10));
    require(actual_tracer==tracer,"Kernel tracer identity differs");
    char link[PATH_MAX+1];ssize_t length=readlink(proc(pid,"exe").c_str(),link,PATH_MAX);
    require(length>0&&length<PATH_MAX,"Process executable is unavailable");std::string executable(link,static_cast<size_t>(length));
    require(executable==expected_exe,"Process executable differs");
    if(!mapping.empty()){
        require(session==pid,"Guest did not detach its session");
        std::istringstream maps(read(proc(pid,"maps"),128*1024));bool matched=false;
        while(std::getline(maps,value)){
            std::istringstream parts(value);std::string range,permissions,offset,device,inode,path;
            if(!(parts>>range>>permissions>>offset>>device>>inode))continue;
            std::getline(parts,path);auto first=path.find_first_not_of(' ');if(first==std::string::npos)continue;
            matched|=permissions.size()==4&&permissions[2]=='x'&&path.substr(first)==mapping;
        }
        require(matched,"Guest executable mapping differs");
    }
}
int find(jlong handle){auto found=handles.find(handle);require(found!=handles.end(),"Unknown probe process handle");return found->second;}
void failure(JNIEnv *env,const std::exception &error){if(!env->ExceptionCheck())env->ThrowNew(env->FindClass("java/io/IOException"),error.what());}
}

extern "C" JNIEXPORT jlong JNICALL
Java_io_github_russianranger_esteria_runtime_ProbeProcessHandles_watch(JNIEnv *env,jclass,jint pid,jlong ticks,jint tracer,jstring executable,jstring mapping){
    try{
        require(pid>1&&pid!=getpid()&&tracer>=0,"Invalid probe process identity");
        char self[64];ssize_t self_size=readlink("/proc/self",self,sizeof(self)-1);
        require(self_size>0&&static_cast<size_t>(self_size)<sizeof(self)-1,"Cannot identify procfs namespace");
        require(std::string(self,static_cast<size_t>(self_size))==std::to_string(getpid()),"Procfs PID namespace does not match syscalls");
        const auto exe=text(env,executable),mapped=text(env,mapping);
        require(!exe.empty()&&exe[0]=='/'&&(mapped.empty()||mapped[0]=='/'),"Absolute probe identities required");
        Fd fd{static_cast<int>(syscall(SYS_pidfd_open,pid,0))};require(fd.value>=0,"Android pidfd_open unavailable");
        require(!exited(fd.value,0),"Process exited before identification");identity(pid,ticks,tracer,exe,mapped);
        require(!exited(fd.value,0),"Process exited during identification");
        std::lock_guard<std::mutex> lock(mutex);require(handles.size()<16,"Too many probe process handles");
        const jlong handle=next_handle++;handles.emplace(handle,fd.value);fd.value=-1;return handle;
    }catch(const std::exception &error){failure(env,error);return 0;}
}
extern "C" JNIEXPORT jboolean JNICALL
Java_io_github_russianranger_esteria_runtime_ProbeProcessHandles_exited(JNIEnv *env,jclass,jlong handle,jint timeout){
    try{std::lock_guard<std::mutex> lock(mutex);return exited(find(handle),timeout)?JNI_TRUE:JNI_FALSE;}
    catch(const std::exception &error){failure(env,error);return JNI_FALSE;}
}
extern "C" JNIEXPORT void JNICALL
Java_io_github_russianranger_esteria_runtime_ProbeProcessHandles_kill(JNIEnv *env,jclass,jlong handle){
    try{std::lock_guard<std::mutex> lock(mutex);int result;do{result=static_cast<int>(syscall(SYS_pidfd_send_signal,find(handle),SIGKILL,nullptr,0));}while(result&&errno==EINTR);
        require(result==0||errno==ESRCH,"Cannot terminate verified probe process");}
    catch(const std::exception &error){failure(env,error);}
}
extern "C" JNIEXPORT void JNICALL
Java_io_github_russianranger_esteria_runtime_ProbeProcessHandles_close(JNIEnv *env,jclass,jlong handle){
    try{std::lock_guard<std::mutex> lock(mutex);int fd=find(handle);handles.erase(handle);require(::close(fd)==0,"Cannot close probe process handle");}
    catch(const std::exception &error){failure(env,error);}
}
