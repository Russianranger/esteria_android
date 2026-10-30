// Adapted from Russianranger/fta-launcher 7a9ce45988f295824d20c9ff7436a77a0baa4f07.
// Copyright (c) 2026 Russianranger; MIT license in FTA-MIT-LICENSE.txt.
#include "process_owner.h"
#include <cassert>
#include <cerrno>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <signal.h>
#include <string>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>

int main() {
    char path[] = "/tmp/esteria-owner-XXXXXX";
    const auto* created = mkdtemp(path); assert(created);
    const std::string root(created);
    // Completed children retain their handles until final diagnostics are read,
    // even if another thread starts enough children to pressure the registry.
    esteria::StartOptions pressure_options{"/bin/true",{}, {},root,"",root+"/pressure-out",root+"/pressure-err"};
    std::vector<std::int64_t> pressure;
    for (int i=0;i<64;++i) { auto handle=esteria::start(pressure_options); assert(esteria::wait_for(handle,5000)==0); pressure.push_back(handle); }
    bool capped=false;
    std::thread pressure_starter([&] { try { esteria::start(pressure_options); } catch (...) { capped=true; } });
    pressure_starter.join(); assert(capped);
    for (const auto handle:pressure) { assert(esteria::wait_for(handle,0)==0); assert(esteria::diagnostics(handle)[4]==0); }
    esteria::StartOptions options{"/bin/sh", {"-c", "printf 'ok'; printf 'err' >&2; exit 7"},
        {"PATH=/usr/bin:/bin"}, root, "", root+"/out", root+"/err"};
    const auto done = esteria::start(options);
    assert(esteria::wait_for(done,5000) == 7);
    assert(esteria::wait_for(done,0) == 7);
    assert(esteria::stop(done,100) == 7);
    std::string value;
    { std::ifstream file(root+"/out"); file >> value; assert(value=="ok"); }
    { std::ifstream file(root+"/err"); file >> value; assert(value=="err"); }
    struct stat info{}; assert(stat((root+"/out").c_str(),&info)==0); assert((info.st_mode & 0777)==0600);
    options.executable="/bin/sleep"; options.arguments={"30"};
    const auto live=esteria::start(options);
    const auto live_pid=esteria::process_id(live);
    assert(live_pid>0 && live_pid!=getpid() && kill(live_pid,0)==0);
    assert(esteria::wait_for(live,10)==esteria::running);
    assert(esteria::stop(live,2000)==143);
    assert(esteria::wait_for(live,0)==143);
    bool dead_identity_refused=false;
    try { esteria::process_id(live); } catch (...) { dead_identity_refused=true; }
    assert(dead_identity_refused);
    sigset_t blocked, previous;
    sigemptyset(&blocked); sigaddset(&blocked,SIGTERM);
    assert(sigprocmask(SIG_BLOCK,&blocked,&previous)==0);
    const auto masked=esteria::start(options);
    assert(sigprocmask(SIG_SETMASK,&previous,nullptr)==0);
    assert(esteria::stop(masked,2000)==143);
    // A TERM-ignoring child must be forcibly killed and reaped within the bound.
    options.executable="/bin/sh";
    options.arguments={"-c","trap '' TERM; echo ready; exec /bin/sleep 30"};
    const auto stubborn=esteria::start(options);
    bool ready=false;
    for (int i=0;i<100 && !ready;++i) {
        std::ifstream file(options.output); std::string line; file >> line; ready=line=="ready";
        if (!ready) std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    assert(ready);
    const auto kill_started=std::chrono::steady_clock::now();
    assert(esteria::stop(stubborn,50)==137);
    assert(std::chrono::steady_clock::now()-kill_started<std::chrono::seconds(3));
    assert(esteria::wait_for(stubborn,0)==137);
    // Concurrent cancellation/wait must agree and may not target another child.
    options.executable="/bin/sleep"; options.arguments={"30"};
    const auto unrelated=esteria::start(options);
    options.output=root+"/parallel-out"; options.error=root+"/parallel-err";
    const auto shared=esteria::start(options);
    int stop_result=0, wait_result=0;
    std::thread stopper([&] { stop_result=esteria::stop(shared,1000); });
    std::thread waiter([&] { wait_result=esteria::wait_for(shared,5000); });
    stopper.join(); waiter.join();
    assert(stop_result==143 && wait_result==143);
    assert(esteria::wait_for(unrelated,0)==esteria::running);
    assert(esteria::stop(unrelated,1000)==143);
    options.output=root+"/out"; options.error=root+"/err";
    options.executable="/bin/sh"; options.arguments={"-c","head -c 10000000 /dev/zero"};
    auto loud=esteria::start(options); assert(esteria::wait_for(loud,10000)==0);
    assert(std::filesystem::file_size(root+"/out")==8*1024*1024);
    const auto metrics=esteria::diagnostics(loud);
    assert(metrics[0]==10000000 && metrics[1]==8*1024*1024 && metrics[4]==0);
    // A finished leader cannot leave children in its owned process group.
    assert(prctl(PR_SET_CHILD_SUBREAPER,1)==0);
    options.arguments={"-c","(trap '' TERM; exec /bin/sleep 30) & echo $!; exit 0"};
    auto descendants=esteria::start(options); assert(esteria::wait_for(descendants,5000)==0);
    pid_t descendant=0; { std::ifstream file(root+"/out"); file >> descendant; } assert(descendant>0);
    int descendant_status=0;
    assert(waitpid(descendant,&descendant_status,0)==descendant);
    assert(WIFSIGNALED(descendant_status) && WTERMSIG(descendant_status)==SIGKILL);
    // Abrupt parent death also terminates its direct native child.
    int report[2]; assert(pipe(report)==0);
    const pid_t owner=fork(); assert(owner>=0);
    if (!owner) {
        close(report[0]);
        options.output=root+"/orphan-out"; options.error=root+"/orphan-err";
        options.arguments={"-c","trap '' TERM; echo $$; exec /bin/sleep 30"};
        esteria::start(options);
        pid_t native_child=0;
        for (int i=0;i<100 && native_child<=0;++i) {
            std::ifstream file(options.output); file >> native_child;
            if (native_child<=0) std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        const auto ignored=write(report[1],&native_child,sizeof(native_child)); (void)ignored;
        if (native_child<=0) _exit(1);
        for (;;) pause();
    }
    close(report[1]); pid_t orphan=0;
    assert(read(report[0],&orphan,sizeof(orphan))==sizeof(orphan)); close(report[0]);
    assert(orphan>0);
    assert(kill(owner,SIGKILL)==0);
    int owner_status=0; assert(waitpid(owner,&owner_status,0)==owner && WIFSIGNALED(owner_status) && WTERMSIG(owner_status)==SIGKILL);
    int orphan_status=0; pid_t observed=0;
    for (int i=0;i<100 && observed==0;++i) {
        observed=waitpid(orphan,&orphan_status,WNOHANG);
        if (!observed) std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    assert(observed==orphan && WIFSIGNALED(orphan_status) && WTERMSIG(orphan_status)==SIGKILL);
    // More than the registry capacity of completed commands must not leak slots.
    options.executable="/bin/true"; options.arguments={};
    for (int i=0;i<80;++i) { const auto handle=esteria::start(options); assert(esteria::wait_for(handle,5000)==0); esteria::diagnostics(handle); }
    options.executable="/does/not/exist";
    bool refused=false; try { esteria::start(options); } catch (...) { refused=true; } assert(refused);
    refused=false; try { esteria::stop(99999999,0); } catch (...) { refused=true; } assert(refused);
    options.executable="/bin/true";
    unlink((root+"/out").c_str());
    assert(symlink((root+"/err").c_str(),(root+"/out").c_str())==0);
    refused=false; try { esteria::start(options); } catch (...) { refused=true; } assert(refused);
    // A private log must not alias another owned file via a hardlink.
    unlink((root+"/out").c_str());
    { std::ofstream keep(root+"/preserve"); keep << "preserve"; }
    assert(link((root+"/preserve").c_str(),(root+"/out").c_str())==0);
    refused=false; try { esteria::start(options); } catch (...) { refused=true; } assert(refused);
    { std::ifstream keep(root+"/preserve"); keep >> value; assert(value=="preserve"); }
    std::filesystem::remove_all(root);
    std::cout << "Native owner tests: PASS (exit, idempotence, TERM/KILL, concurrent stop/wait, unrelated child isolation, owner SIGKILL, group cleanup, 80-command churn, log bound, IO modes, rejected exec/handles/symlinks)\n";
}
