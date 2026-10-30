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
    // Opt-in stdin is a real binary stream. EOF is explicit and idempotent.
    options.arguments={"-c","cat"}; options.interactive_input=true;
    const auto echo=esteria::start(options);
    const unsigned char binary[]={0,255,1,'\n','x',0,'y'};
    assert(esteria::write_input(echo,binary,sizeof(binary),100));
    esteria::close_input(echo); esteria::close_input(echo);
    assert(esteria::wait_for(echo,5000)==0);
    { std::ifstream file(root+"/out",std::ios::binary); std::string bytes((std::istreambuf_iterator<char>(file)),{});
      assert(bytes==std::string(reinterpret_cast<const char*>(binary),sizeof(binary))); }
    bool closed_input=false;
    try { esteria::write_input(echo,binary,sizeof(binary),0); } catch (...) { closed_input=true; }
    assert(closed_input);
    // Fill a reader-paused pipe, verify bounded backpressure and zero partial
    // messages on timeout, then drain exactly the messages reported accepted.
    options.arguments={"-c","while [ ! -f drain ]; do sleep .01; done; cat"};
    const auto pressure_input=esteria::start(options);
    const std::string block(4096,'b'); std::size_t accepted=0;
    while (accepted<1024*1024 && esteria::write_input(pressure_input,block.data(),block.size(),0)) accepted+=block.size();
    assert(accepted>0 && accepted<1024*1024);
    const auto input_began=std::chrono::steady_clock::now();
    const std::string refused_block(4096,'r');
    assert(!esteria::write_input(pressure_input,refused_block.data(),refused_block.size(),80));
    assert(std::chrono::steady_clock::now()-input_began<std::chrono::milliseconds(500));
    { std::ofstream marker(root+"/drain"); marker << "go"; }
    esteria::close_input(pressure_input);
    assert(esteria::wait_for(pressure_input,5000)==0);
    { std::ifstream file(root+"/out",std::ios::binary); std::string bytes((std::istreambuf_iterator<char>(file)),{});
      assert(bytes==std::string(accepted,'b')); }
    unlink((root+"/drain").c_str());
    // Closing while a writer waits must cancel it; it cannot target a reused fd.
    options.arguments={"-c","exec sleep 30"};
    const auto closing_input=esteria::start(options);
    accepted=0;
    while (accepted<1024*1024 && esteria::write_input(closing_input,block.data(),block.size(),0)) accepted+=block.size();
    assert(accepted<1024*1024);
    bool write_closed=false;
    std::thread input_writer([&] { try { esteria::write_input(closing_input,block.data(),block.size(),1000); } catch (...) { write_closed=true; } });
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    const auto close_began=std::chrono::steady_clock::now();
    esteria::close_input(closing_input); input_writer.join();
    assert(write_closed && std::chrono::steady_clock::now()-close_began<std::chrono::milliseconds(500));
    assert(esteria::stop(closing_input,0)!=esteria::running);
    // EPIPE must not deliver a fatal SIGPIPE to the native host/JVM.
    options.arguments={"-c","exec 0<&-; printf ready; exec sleep 30"};
    const auto broken_input=esteria::start(options);
    bool reader_closed=false;
    for (int i=0;i<100 && !reader_closed;++i) {
        std::ifstream file(root+"/out"); std::string line; file >> line; reader_closed=line=="ready";
        if (!reader_closed) std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    assert(reader_closed); bool broken_rejected=false;
    try { esteria::write_input(broken_input,binary,sizeof(binary),100); } catch (...) { broken_rejected=true; }
    assert(broken_rejected && esteria::stop(broken_input,0)!=esteria::running);
    options.interactive_input=false; options.arguments={"-c","cat; printf eof"};
    const auto default_input=esteria::start(options); assert(esteria::wait_for(default_input,5000)==0);
    { std::ifstream file(root+"/out"); file >> value; assert(value=="eof"); }
    bool default_rejected=false;
    try { esteria::write_input(default_input,binary,sizeof(binary),0); } catch (...) { default_rejected=true; }
    assert(default_rejected);
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
        options.interactive_input=true;
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
    std::cout << "Native owner tests: PASS (exit, idempotence, TERM/KILL, concurrent stop/wait, unrelated child isolation, owner SIGKILL, group cleanup, 80-command churn, log bound, IO modes, rejected exec/handles/symlinks, binary stdin, EOF, atomic backpressure, close/write race, EPIPE, default stdin)\n";
}
