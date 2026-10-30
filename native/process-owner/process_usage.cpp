#include "process_usage.h"
#include <algorithm>
#include <cerrno>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <dirent.h>
#include <fcntl.h>
#include <limits>
#include <map>
#include <memory>
#include <string>
#include <string_view>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

namespace esteria { namespace detail { namespace {
using Clock=std::chrono::steady_clock;
constexpr int directory_flags=O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW;
struct Fd {
    int value;
    explicit Fd(int value):value(value){}
    ~Fd(){if(value>=0)close(value);}
    Fd(const Fd&)=delete;Fd& operator=(const Fd&)=delete;
};
struct Stat {
    std::int64_t pid=0,group=0,start=0,cpu=0,rss=0;
    char state=0;
    bool cpu_valid=false,rss_valid=false;
};
struct Limits {int entries,members,millis;};
std::int64_t nanos(Clock::time_point value){return std::chrono::duration_cast<std::chrono::nanoseconds>(value.time_since_epoch()).count();}
bool number(std::string_view raw,std::int64_t& value) {
    if(raw.empty())return false;
    const auto result=std::from_chars(raw.data(),raw.data()+raw.size(),value);
    return result.ec==std::errc{}&&result.ptr==raw.data()+raw.size();
}
bool parse_stat(std::string_view raw,int expected_pid,Stat& result) {
    const auto open=raw.find('('),close=raw.rfind(')');
    if(open==std::string_view::npos||close==std::string_view::npos||open<2||close<=open||
            !number(raw.substr(0,open-1),result.pid)||result.pid!=expected_pid)return false;
    std::vector<std::string_view> fields;fields.reserve(32);
    std::size_t at=close+1;
    while(at<raw.size()) {
        while(at<raw.size()&&(raw[at]==' '||raw[at]=='\n'||raw[at]=='\t'))++at;
        if(at==raw.size())break;
        auto end=raw.find_first_of(" \t\n",at);if(end==std::string_view::npos)end=raw.size();
        if(fields.size()>=64)return false;
        fields.push_back(raw.substr(at,end-at));at=end;
    }
    // fields[0] is kernel stat field3; comm is deliberately never returned.
    if(fields.size()<22||fields[0].size()!=1||!number(fields[2],result.group)||result.group<=0||
            !number(fields[19],result.start)||result.start<0)return false;
    result.state=fields[0][0];
    std::int64_t user=0,system=0;
    result.cpu_valid=number(fields[11],user)&&number(fields[12],system)&&user>=0&&system>=0&&
        user<=std::numeric_limits<std::int64_t>::max()-system;
    if(result.cpu_valid)result.cpu=user+system;
    result.rss_valid=number(fields[21],result.rss)&&result.rss>=0;
    return true;
}
bool parse_pss(std::string_view raw,std::int64_t& bytes) {
    bool found=false;std::size_t at=0;
    while(at<raw.size()) {
        auto end=raw.find('\n',at);if(end==std::string_view::npos)end=raw.size();
        auto line=raw.substr(at,end-at);at=end+1;
        if(line.substr(0,4)!="Pss:")continue;
        if(found)return false;
        found=true;std::size_t begin=4;
        while(begin<line.size()&&(line[begin]==' '||line[begin]=='\t'))++begin;
        auto stop=line.find_first_of(" \t",begin);if(stop==std::string_view::npos)return false;
        std::int64_t kilobytes=0;if(!number(line.substr(begin,stop-begin),kilobytes)||kilobytes<0||
                kilobytes>std::numeric_limits<std::int64_t>::max()/1024)return false;
        while(stop<line.size()&&(line[stop]==' '||line[stop]=='\t'))++stop;
        if(line.substr(stop)!="kB")return false;
        bytes=kilobytes*1024;
    }
    return found;
}
void failure(GroupUsage& usage,int error,bool membership) {
    if(error==EACCES||error==EPERM){usage.flags|=GroupUsage::proc_denied;++usage.denied_entries;}
    else if(membership&&(error==ENOENT||error==ESRCH)){usage.flags|=GroupUsage::changed;++usage.changed_members;}
    else usage.flags|=GroupUsage::io_error;
    if(membership)usage.flags|=GroupUsage::membership_incomplete;
}
bool expired(GroupUsage& usage,Clock::time_point end) {
    if(Clock::now()<end)return false;
    usage.flags|=GroupUsage::limit|GroupUsage::membership_incomplete;return true;
}
bool read_at(int directory,const char* name,std::size_t bound,std::string& raw,int& error) {
    Fd file(openat(directory,name,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK));
    if(file.value<0){error=errno;return false;}
    struct stat metadata{};
    if(fstat(file.value,&metadata)||!S_ISREG(metadata.st_mode)){error=errno?errno:EINVAL;return false;}
    raw.clear();char buffer[4096];
    while(true) {
        ssize_t count=read(file.value,buffer,std::min(sizeof(buffer),bound+1-raw.size()));
        if(count<0&&errno==EINTR)continue;
        if(count<0){error=errno;return false;}
        if(!count)return true;
        raw.append(buffer,static_cast<std::size_t>(count));
        if(raw.size()>bound){error=EFBIG;return false;}
    }
}
bool read_stat(int fd,int pid,Stat& stat,GroupUsage& usage,bool membership) {
    std::string raw;int error=0;
    if(!read_at(fd,"stat",8192,raw,error)){failure(usage,error,membership);return false;}
    if(!parse_stat(raw,pid,stat)){failure(usage,EINVAL,membership);return false;}
    return true;
}
bool same(const Stat& left,const Stat& right){return left.pid==right.pid&&left.group==right.group&&left.start==right.start;}
bool live(const Stat& stat){return stat.state!='Z'&&stat.state!='X'&&stat.state!='x';}
bool leader_valid(int fd,const Stat& expected,GroupUsage& usage) {
    Stat current;
    if(!read_stat(fd,static_cast<int>(expected.pid),current,usage,true)||!same(expected,current)||!live(current)) {
        usage.flags|=GroupUsage::not_running|GroupUsage::membership_incomplete;return false;
    }
    return true;
}
void discard(GroupUsage& usage) {
    usage.members=usage.rss_members=usage.pss_members=usage.cpu_members=0;
    usage.rss_bytes=usage.pss_bytes=usage.cpu_ticks=0;
}
using Members=std::map<int,Stat>;
struct CloseDirectory {void operator()(DIR* value)const {closedir(value);}};
Members scan(int proc,int leader_fd,const Stat& leader,GroupUsage& usage,Clock::time_point end,const Limits& limits) {
    Members members;
    Fd enumeration(openat(proc,".",directory_flags));
    if(enumeration.value<0){failure(usage,errno,true);return members;}
    DIR* raw=fdopendir(enumeration.value);
    if(!raw){failure(usage,errno,true);return members;}
    enumeration.value=-1;std::unique_ptr<DIR,CloseDirectory> directory(raw);
    int entries=0;
    while(true) {
        if(expired(usage,end))break;
        errno=0;dirent* item=readdir(directory.get());
        if(!item){if(errno)failure(usage,errno,true);break;}
        std::string_view name(item->d_name);std::int64_t pid=0;
        if(!number(name,pid)||pid<=0||pid>std::numeric_limits<int>::max())continue;
        if(++entries>limits.entries){usage.flags|=GroupUsage::limit|GroupUsage::membership_incomplete;break;}
        ++usage.scanned_processes;
        if(!leader_valid(leader_fd,leader,usage))break;
        Fd process(openat(proc,item->d_name,directory_flags));
        if(process.value<0){failure(usage,errno,true);continue;}
        Stat stat;if(!read_stat(process.value,static_cast<int>(pid),stat,usage,true))continue;
        if(stat.group!=leader.pid||!live(stat))continue;
        if(members.size()>=static_cast<std::size_t>(limits.members)){usage.flags|=GroupUsage::limit|GroupUsage::membership_incomplete;break;}
        members.emplace(static_cast<int>(pid),stat);
    }
    return members;
}
bool accumulate(std::int64_t value,std::int64_t& total) {
    if(value<0||total>std::numeric_limits<std::int64_t>::max()-value)return false;
    total+=value;return true;
}
GroupUsage sample(int proc,int leader_fd,int pid,const Limits& limits,void(*hook)(void*),void* hook_state) {
    GroupUsage usage;const auto begin=Clock::now(),end=begin+std::chrono::milliseconds(limits.millis);
    usage.start_nanos=nanos(begin);usage.ticks_per_second=sysconf(_SC_CLK_TCK);
    const auto finish=[&](){usage.duration_nanos=std::max<std::int64_t>(0,nanos(Clock::now())-usage.start_nanos);return usage;};
    Stat leader;
    if(pid<=0||!read_stat(leader_fd,pid,leader,usage,true)||leader.group!=pid||!live(leader)) {
        usage.flags|=GroupUsage::not_running|GroupUsage::membership_incomplete;return finish();
    }
    if(proc<0){failure(usage,errno?errno:EIO,true);return finish();}
    if(usage.ticks_per_second<=0){usage.ticks_per_second=0;usage.flags|=GroupUsage::cpu_unavailable;}
    const long page_size=sysconf(_SC_PAGESIZE);
    if(page_size<=0)usage.flags|=GroupUsage::rss_unavailable;
    const auto initial=scan(proc,leader_fd,leader,usage,end,limits);
    if(hook)hook(hook_state);
    for(const auto& entry:initial) {
        if(expired(usage,end)||!leader_valid(leader_fd,leader,usage))break;
        const auto numeric=std::to_string(entry.first);
        Fd process(openat(proc,numeric.c_str(),directory_flags));
        if(process.value<0){failure(usage,errno,true);continue;}
        Stat before,after;
        if(!read_stat(process.value,entry.first,before,usage,true))continue;
        if(!same(before,entry.second)||!live(before)){usage.flags|=GroupUsage::changed|GroupUsage::membership_incomplete;++usage.changed_members;continue;}
        std::string rollup;int error=0;std::int64_t pss=0;
        bool pss_valid=read_at(process.value,"smaps_rollup",128*1024,rollup,error);
        if(!pss_valid)failure(usage,error,false);
        else if(!parse_pss(rollup,pss)){pss_valid=false;failure(usage,EINVAL,false);}
        if(!read_stat(process.value,entry.first,after,usage,true))continue;
        if(!same(before,after)||!live(after)||!leader_valid(leader_fd,leader,usage)) {
            usage.flags|=GroupUsage::changed|GroupUsage::membership_incomplete;++usage.changed_members;continue;
        }
        ++usage.members;
        if(before.rss_valid&&page_size>0&&before.rss<=std::numeric_limits<std::int64_t>::max()/page_size&&
                accumulate(before.rss*page_size,usage.rss_bytes))++usage.rss_members;
        else usage.flags|=GroupUsage::rss_unavailable;
        if(pss_valid&&accumulate(pss,usage.pss_bytes))++usage.pss_members;else usage.flags|=GroupUsage::pss_unavailable;
        if(before.cpu_valid&&usage.ticks_per_second>0&&accumulate(before.cpu,usage.cpu_ticks))++usage.cpu_members;
        else usage.flags|=GroupUsage::cpu_unavailable;
    }
    const auto final=scan(proc,leader_fd,leader,usage,end,limits);
    if(initial.size()!=final.size()||!std::equal(initial.begin(),initial.end(),final.begin(),[](const auto& left,const auto& right){return same(left.second,right.second);})) {
        usage.flags|=GroupUsage::changed|GroupUsage::membership_incomplete;++usage.changed_members;
    }
    if(usage.members!=static_cast<std::int64_t>(initial.size()))usage.flags|=GroupUsage::membership_incomplete;
    if(!leader_valid(leader_fd,leader,usage)){discard(usage);usage.flags|=GroupUsage::not_running|GroupUsage::membership_incomplete;}
    return finish();
}
}
GroupUsage sample_group(int leader_fd,int pid) {
    Fd proc(open("/proc",directory_flags));return sample(proc.value,leader_fd,pid,{8192,128,100},nullptr,nullptr);
}
#ifdef ESTERIA_USAGE_TESTING
GroupUsage sample_group_fixture(int proc,int leader,int pid,int entries,int members,int millis,void(*hook)(void*),void* state) {
    return sample(proc,leader,pid,{entries,members,millis},hook,state);
}
bool parse_stat_fixture(const char* raw,int pid,std::int64_t* group,std::int64_t* start,std::int64_t* cpu,std::int64_t* rss) {
    Stat stat;if(!parse_stat(raw,pid,stat)||!stat.cpu_valid||!stat.rss_valid)return false;
    *group=stat.group;*start=stat.start;*cpu=stat.cpu;*rss=stat.rss;return true;
}
bool parse_pss_fixture(const char* raw,std::int64_t* bytes){return parse_pss(raw,*bytes);}
#endif
}}
