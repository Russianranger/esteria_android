#include "process_owner.h"
#include "process_usage.h"
#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <fcntl.h>
#include <signal.h>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace {
using esteria::GroupUsage;
constexpr int directory_flags=O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW;
std::string stat_text(int pid,int group,std::int64_t start=500,std::int64_t rss=4,std::int64_t cpu=7) {
    // Kernel fields1..24 with intentionally tricky comm containing spaces and ).
    return std::to_string(pid)+" (name ) with spaces) S 1 "+std::to_string(group)+
        " 1 0 0 0 0 0 0 0 "+std::to_string(cpu)+" 3 0 0 0 0 1 0 "+std::to_string(start)+" 50000 "+std::to_string(rss)+"\n";
}
void text(const std::filesystem::path& file,const std::string& value){std::ofstream out(file);out<<value;out.close();assert(out.good());}
void member(const std::filesystem::path& root,int pid,int group,std::int64_t start=500) {
    std::filesystem::create_directory(root/std::to_string(pid));
    text(root/std::to_string(pid)/"stat",stat_text(pid,group,start));
    text(root/std::to_string(pid)/"smaps_rollup","000-fff ---p 000 00:00 0 [rollup]\nRss: 20 kB\nPss: 11 kB\nPss_Anon: 2 kB\nSwapPss: 7 kB\n");
}
struct Fixture {
    std::filesystem::path root;
    int proc,leader;
    Fixture(){char name[]="/tmp/esteria-usage-XXXXXX";const auto created=mkdtemp(name);assert(created);root=created;member(root,101,101);member(root,202,101,510);member(root,303,303,520);proc=open(root.c_str(),directory_flags);leader=open((root/"101").c_str(),directory_flags);assert(proc>=0&&leader>=0);}
    ~Fixture(){close(leader);close(proc);std::filesystem::remove_all(root);}
    GroupUsage sample(int entries=8192,int members=128,int millis=100,void(*hook)(void*)=nullptr,void* state=nullptr){return esteria::detail::sample_group_fixture(proc,leader,101,entries,members,millis,hook,state);}
};
void parser_checks() {
    std::int64_t group=0,start=0,cpu=0,rss=0;
    const auto valid=stat_text(101,101);
    assert(esteria::detail::parse_stat_fixture(valid.c_str(),101,&group,&start,&cpu,&rss));
    assert(group==101&&start==500&&cpu==10&&rss==4);
    assert(!esteria::detail::parse_stat_fixture(valid.c_str(),202,&group,&start,&cpu,&rss));
    assert(!esteria::detail::parse_stat_fixture("101 (cut) S 1",101,&group,&start,&cpu,&rss));
    assert(esteria::detail::parse_pss_fixture("Pss: 123 kB\nSwapPss: 9 kB\n",&rss)&&rss==123*1024);
    assert(!esteria::detail::parse_pss_fixture("Pss: 123 MB\n",&rss));
    assert(!esteria::detail::parse_pss_fixture("Pss: 1 kB\nPss: 2 kB\n",&rss));
    assert(!esteria::detail::parse_pss_fixture("Pss: 9223372036854775807 kB\n",&rss));
    assert(!esteria::detail::parse_pss_fixture("Rss: 123 kB\n",&rss));
    Fixture fixture;auto usage=fixture.sample();
    assert(usage.flags==GroupUsage::visibility_unverified&&usage.members==2&&usage.rss_members==2&&usage.pss_members==2&&usage.cpu_members==2);
    assert(usage.rss_bytes==8*sysconf(_SC_PAGESIZE)&&usage.pss_bytes==22*1024&&usage.cpu_ticks==20&&usage.ticks_per_second>0);
    assert(usage.scanned_processes==6&&usage.start_nanos>0&&usage.duration_nanos>=0);
    std::filesystem::rename(fixture.root/"202",fixture.root/"hidden-member");usage=fixture.sample();
    assert(usage.members==1&&(usage.flags&GroupUsage::visibility_unverified));
    assert(!(usage.flags&GroupUsage::membership_incomplete)); // A stable visible set cannot prove whole-group membership.
    std::filesystem::rename(fixture.root/"hidden-member",fixture.root/"202");
    std::filesystem::remove(fixture.root/"202/smaps_rollup");usage=fixture.sample();
    assert(!(usage.flags&(GroupUsage::membership_incomplete|GroupUsage::changed|GroupUsage::limit)));
    assert((usage.flags&GroupUsage::pss_unavailable)&&usage.members==2&&usage.rss_members==2&&usage.pss_members==1&&usage.cpu_members==2);
    std::cout<<"PASS synthetic stat/PSS parsers, exact group isolation and per-metric unavailable semantics\n";
}
void bound_leader_and_races() {
    Fixture fixture;
    const auto change=[](void* raw){auto* item=static_cast<Fixture*>(raw);text(item->root/"202/stat",stat_text(202,101,999));};
    auto usage=fixture.sample(8192,128,100,change,&fixture);
    assert((usage.flags&(GroupUsage::changed|GroupUsage::membership_incomplete))==(GroupUsage::changed|GroupUsage::membership_incomplete));
    assert(usage.members==1&&usage.cpu_ticks==10&&usage.pss_bytes==11*1024&&usage.changed_members>0);
    const auto replace_leader=[](void* raw){auto* item=static_cast<Fixture*>(raw);std::filesystem::rename(item->root/"101",item->root/"old-leader");member(item->root,101,101,999);std::filesystem::remove(item->root/"old-leader/stat");};
    usage=fixture.sample(8192,128,100,replace_leader,&fixture);
    assert((usage.flags&GroupUsage::not_running)&&usage.members==0&&usage.pss_bytes==0&&usage.cpu_ticks==0);
    std::cout<<"PASS synthetic changed-member and bound-dirfd numeric leader replacement refusal\n";
}
void bounded_work() {
    Fixture fixture;auto usage=fixture.sample(1);
    assert((usage.flags&GroupUsage::limit)&&(usage.flags&GroupUsage::membership_incomplete)&&usage.scanned_processes<=2);
    usage=fixture.sample(8192,1);assert((usage.flags&GroupUsage::limit)&&usage.members<=1);
    usage=fixture.sample(8192,128,0);assert((usage.flags&GroupUsage::limit)&&usage.members==0);
    text(fixture.root/"202/stat",std::string(9000,'x'));usage=fixture.sample();assert((usage.flags&GroupUsage::membership_incomplete)&&(usage.flags&GroupUsage::io_error));
    text(fixture.root/"202/stat",stat_text(202,101,510));text(fixture.root/"202/smaps_rollup",std::string(128*1024+1,'x'));usage=fixture.sample();
    assert((usage.flags&GroupUsage::pss_unavailable)&&usage.members==2&&usage.pss_members==1);
    assert(!(usage.flags&GroupUsage::membership_incomplete));
    std::cout<<"PASS synthetic entry/member/time/byte limits and fail-closed oversized metrics\n";
}
bool denied_fixture() {
    Fixture fixture;
    // Real EACCES on synthetic proc files, in a privilege-dropped child when the
    // host itself runs as root. This is not Android SELinux/proc qualification.
    assert(chmod(fixture.root.c_str(),0755)==0);
    assert(chmod((fixture.root/"202/smaps_rollup").c_str(),0000)==0);
    int report[2];assert(pipe(report)==0);pid_t child=fork();assert(child>=0);
    if(!child) {
        close(report[0]);
        if(geteuid()==0&&setuid(65534)){const unsigned char skipped=2;const auto done=write(report[1],&skipped,1);(void)done;_exit(0);}
        auto usage=fixture.sample();
        const bool okay=(usage.flags&GroupUsage::proc_denied)&&(usage.flags&GroupUsage::pss_unavailable)&&
            !(usage.flags&GroupUsage::membership_incomplete)&&usage.members==2&&usage.rss_members==2&&usage.pss_members==1;
        if(!okay)std::cerr<<"denial fixture flags="<<usage.flags<<" members="<<usage.members<<" rss="<<usage.rss_members<<" pss="<<usage.pss_members<<" denied="<<usage.denied_entries<<" scanned="<<usage.scanned_processes<<"\n";
        const unsigned char value=okay?1:0;const auto done=write(report[1],&value,1);(void)done;_exit(okay?0:3);
    }
    close(report[1]);unsigned char result=0;assert(read(report[0],&result,1)==1);close(report[0]);int status=0;assert(waitpid(child,&status,0)==child&&WIFEXITED(status)&&WEXITSTATUS(status)==0);
    if(result==2){assert(chmod((fixture.root/"202/smaps_rollup").c_str(),0644)==0);std::cout<<"SKIP actual EACCES synthetic-file fixture: managed root cannot drop to an unmapped UID\n";return false;}
    assert(result==1);
    assert(chmod((fixture.root/"202/smaps_rollup").c_str(),0644)==0);
    assert(chmod((fixture.root/"202/stat").c_str(),0000)==0);assert(pipe(report)==0);child=fork();assert(child>=0);
    if(!child) {
        close(report[0]);if(geteuid()==0&&setuid(65534)){const unsigned char skipped=2;const auto done=write(report[1],&skipped,1);(void)done;_exit(0);}auto usage=fixture.sample();
        const bool okay=(usage.flags&GroupUsage::proc_denied)&&(usage.flags&GroupUsage::membership_incomplete)&&usage.denied_entries>0;
        if(!okay)std::cerr<<"denial fixture flags="<<usage.flags<<" members="<<usage.members<<" rss="<<usage.rss_members<<" pss="<<usage.pss_members<<" denied="<<usage.denied_entries<<" scanned="<<usage.scanned_processes<<"\n";
        const unsigned char value=okay?1:0;const auto done=write(report[1],&value,1);(void)done;_exit(okay?0:3);
    }
    close(report[1]);result=0;assert(read(report[0],&result,1)==1&&result==1);close(report[0]);assert(waitpid(child,&status,0)==child&&WIFEXITED(status)&&WEXITSTATUS(status)==0);
    assert(chmod((fixture.root/"202/stat").c_str(),0644)==0);
    std::cout<<"PASS actual EACCES against synthetic proc files distinguishes hidden membership from denied PSS\n";return true;
}
int worker(const std::string& root,int megabytes) {
    const auto busy=[&](const char* marker){
        std::vector<unsigned char> memory(static_cast<std::size_t>(megabytes)*1024*1024,1);
        text(std::filesystem::path(root)/marker,std::to_string(getpid())+" "+std::to_string(getpgrp()));std::uint64_t count=0;
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(15);
        while(!std::filesystem::exists(std::filesystem::path(root)/"stop")&&std::chrono::steady_clock::now()<deadline) {
            for(std::size_t i=0;i<memory.size();i+=4096)memory[i]=static_cast<unsigned char>(memory[i]+1);
            ++count;if(count%10==0)std::this_thread::yield();
        }
        return memory[0]==255?1:0;
    };
    const pid_t second=fork();if(second<0)return 4;
    if(!second)_exit(busy("member-ready"));
    busy("leader-ready");int status=0;if(waitpid(second,&status,0)!=second)return 5;return 0;
}
void real_group(const char* self) {
    char raw[]="/tmp/esteria-real-usage-XXXXXX";const auto created=mkdtemp(raw);assert(created);std::filesystem::path root(created);
    const auto first=root/"first",other=root/"unrelated";std::filesystem::create_directory(first);std::filesystem::create_directory(other);
    std::int64_t owned=0,unrelated=0;
    try {
        owned=esteria::start({self,{"--worker",first.string(),"12"},{},root.string(),"",(root/"out").string(),(root/"err").string()});
        unrelated=esteria::start({self,{"--worker",other.string(),"64"},{},root.string(),"",(root/"other-out").string(),(root/"other-err").string()});
        const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(5);
        while((!std::filesystem::exists(first/"leader-ready")||!std::filesystem::exists(first/"member-ready")||!std::filesystem::exists(other/"leader-ready")||!std::filesystem::exists(other/"member-ready"))&&std::chrono::steady_clock::now()<end)std::this_thread::sleep_for(std::chrono::milliseconds(2));
        assert(std::filesystem::exists(other/"member-ready"));
        const auto pid=esteria::process_id(owned);
        auto usage=esteria::usage(owned);
        assert(!(usage.flags&GroupUsage::not_running));
        // Independently establish that the actual fork child exists in this
        // owned PGID before comparing it with the potentially projected procfs.
        std::ifstream reported(first/"member-ready");int member_pid=0,member_group=0;reported>>member_pid>>member_group;
        if(member_pid<=0||member_group!=pid||getpgid(member_pid)!=pid)throw std::runtime_error("Actual fork member identity unavailable");
        std::ifstream direct("/proc/"+std::to_string(member_pid)+"/stat");std::string row;std::getline(direct,row);
        std::int64_t direct_group=0,direct_start=0,direct_cpu=0,direct_rss=0;
        const bool visible=esteria::detail::parse_stat_fixture(row.c_str(),member_pid,&direct_group,&direct_start,&direct_cpu,&direct_rss)&&direct_group==pid;
        assert(usage.flags&GroupUsage::visibility_unverified);
        if(visible&&!(usage.flags&GroupUsage::membership_incomplete)) {
            if(usage.members!=2||usage.rss_members!=2||usage.cpu_members!=2)throw std::runtime_error("Visible known group member disappeared during stable fixture");
            if(usage.rss_bytes<20*1024*1024||usage.rss_bytes>=100*1024*1024||usage.cpu_ticks<=0)throw std::runtime_error("Visible group RSS/CPU fixture counters unavailable");
            assert(usage.pss_members==2||(usage.flags&GroupUsage::pss_unavailable));
        } else {
            // The managed host can expose an actual task through getpgid yet
            // omit its /proc/PID path. Never reinterpret that omission as all
            // members measured; the visibility flag prohibits that claim.
            if(!(usage.flags&GroupUsage::membership_incomplete)&&usage.members>=2)throw std::runtime_error("Unexpected projected-group identity mismatch");
            std::cout<<"OBSERVED managed proc projection/denial: actual same-PGID fork verified, proc census missing/mismatched or unavailable; flags="<<usage.flags<<"; no full-member measurement claim\n";
        }
        text(first/"stop","stop");assert(esteria::wait_for(owned,5000)==0);
        auto after=esteria::usage(owned);assert((after.flags&GroupUsage::not_running)&&after.members==0&&after.rss_bytes==0&&after.pss_bytes==0);
        assert(esteria::wait_for(unrelated,0)==esteria::running);text(other/"stop","stop");assert(esteria::wait_for(unrelated,5000)==0);
        assert(esteria::diagnostics(owned)[4]==0&&esteria::diagnostics(unrelated)[4]==0);
        std::filesystem::remove_all(root);
        std::cout<<"PASS real owned-group identity, visible/projection scope, unrelated isolation and post-reap opaque owner refusal\n";
    }catch(...){if(owned)esteria::stop(owned,0);if(unrelated)esteria::stop(unrelated,0);std::filesystem::remove_all(root);throw;}
}
}
int main(int count,char** arguments) {
    if(count==4&&std::string(arguments[1])=="--worker")return worker(arguments[2],std::stoi(arguments[3]));
    parser_checks();bound_leader_and_races();bounded_work();const bool denied=denied_fixture();
    char executable[4096];const auto length=readlink("/proc/self/exe",executable,sizeof(executable)-1);assert(length>0&&length<static_cast<ssize_t>(sizeof(executable)));executable[length]=0;
    real_group(executable);std::cout<<"Owned-group usage:"<<(denied?5:4)<<" groups PASS,"<<(denied?0:1)<<" permission fixture SKIP; native Linux host, no Android/guest/combined/bot qualification\n";
}
