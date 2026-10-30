// Adapted from Russianranger/fta-launcher 7a9ce45988f295824d20c9ff7436a77a0baa4f07.
// Copyright (c) 2026 Russianranger; MIT license in FTA-MIT-LICENSE.txt.
#include "process_owner.h"
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <fcntl.h>
#include <map>
#include <memory>
#include <mutex>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdexcept>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>

namespace esteria {
namespace {
constexpr std::size_t log_limit = 8 * 1024 * 1024;
struct Owned {
    pid_t pid;
    std::atomic<int> status{running};
    std::mutex mutex;
    std::timed_mutex input_mutex;
    std::atomic<bool> input_closing{false};
    int input_fd = -1;
    bool interactive_input = false;
    std::atomic<bool> finish_logs{false};
    std::atomic<bool> diagnostics_consumed{false};
    std::atomic<bool> logs_joined{false};
    std::atomic<std::int64_t> observed[2]{}, stored[2]{}, io_failures{0};
    std::thread output_thread, error_thread;
    explicit Owned(pid_t p) : pid(p) {}
    ~Owned() {
        if (input_fd >= 0) close(input_fd);
        finish_logs = true;
        if (output_thread.joinable()) output_thread.join();
        if (error_thread.joinable()) error_thread.join();
    }
};
std::mutex registry_mutex;
// Keep finished statuses so stop/wait are idempotent. Bound caller resource use.
std::map<std::int64_t, std::shared_ptr<Owned>> registry;
std::int64_t next_handle = 1;
[[noreturn]] void fail(const char* message) { throw std::runtime_error(message); }
void close_fd(int& fd) { if (fd >= 0) { close(fd); fd = -1; } }
void close_owned_input(Owned& owned) {
    owned.input_closing = true;
    std::lock_guard<std::timed_mutex> guard(owned.input_mutex);
    close_fd(owned.input_fd);
}
// Never change the JVM's process-wide SIGPIPE disposition. Block only this
// writing thread and consume only a new EPIPE signal produced by our own write.
class PipeSignal {
    sigset_t previous{}, blocked{};
    bool pending = false;
public:
    PipeSignal() {
        sigemptyset(&blocked); sigaddset(&blocked,SIGPIPE);
        if (pthread_sigmask(SIG_BLOCK,&blocked,&previous)) fail("Cannot protect process input write");
        sigset_t signals{};
        if (sigpending(&signals)) { pthread_sigmask(SIG_SETMASK,&previous,nullptr); fail("Cannot inspect process input signal state"); }
        pending = sigismember(&signals,SIGPIPE) == 1;
    }
    void broken() {
        if (!pending) {
            timespec zero{};
            while (sigtimedwait(&blocked,nullptr,&zero)<0 && errno==EINTR) {}
        }
    }
    ~PipeSignal() { pthread_sigmask(SIG_SETMASK,&previous,nullptr); }
};
int regular_file(const std::string& path, bool write) {
    int fd = open(path.c_str(), (write ? O_WRONLY | O_CREAT : O_RDONLY) | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK, 0600);
    if (fd < 0) fail("Cannot open private process IO");
    struct stat st{};
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_uid != getuid() || st.st_nlink != 1 ||
            (write && (fchmod(fd, 0600) || ftruncate(fd, 0)))) {
        close(fd); fail("Process IO must be an owned regular file");
    }
    return fd;
}
void drain(int fd, int target, Owned* owned, int stream) {
    std::size_t written = 0;
    std::size_t finished_bytes = 0;
    char buffer[16384];
    while (true) {
        pollfd watched{fd, POLLIN, 0};
        const int ready = poll(&watched, 1, 100);
        if (ready < 0 && errno == EINTR) continue;
        if (ready > 0) {
            const ssize_t got = read(fd, buffer, sizeof(buffer));
            if (got < 0 && errno == EINTR) continue;
            if (got < 0) ++owned->io_failures;
            if (got <= 0) break;
            owned->observed[stream] += got;
            std::size_t count = std::min(static_cast<std::size_t>(got), log_limit - written);
            std::size_t offset = 0;
            while (offset < count) {
                ssize_t done = write(target, buffer + offset, count - offset);
                if (done < 0 && errno == EINTR) continue;
                if (done <= 0) { ++owned->io_failures; count = offset; break; }
                offset += static_cast<std::size_t>(done);
            }
            written += count;
            owned->stored[stream] += count;
            if (owned->finish_logs) {
                finished_bytes += static_cast<std::size_t>(got);
                if (finished_bytes >= 128 * 1024) break;
            }
        } else if (ready < 0 || owned->finish_logs) break;
    }
    close(fd); if (close(target)) ++owned->io_failures;
}
std::shared_ptr<Owned> lookup(std::int64_t handle) {
    std::lock_guard<std::mutex> guard(registry_mutex);
    auto found = registry.find(handle);
    if (found == registry.end()) fail("Unknown owned process handle");
    return found->second;
}
int poll_owned(Owned& owned) {
    if (owned.status != running) return owned.status;
    // Observe termination without releasing the leader PID. Its reserved PID
    // prevents a recycled process group being targeted while we end descendants.
    siginfo_t info{};
    if (waitid(P_PID, static_cast<id_t>(owned.pid), &info, WEXITED | WNOHANG | WNOWAIT)) {
        if (errno == EINTR) return running;
        fail("Owned process could not be observed");
    }
    if (!info.si_pid) return running;
    close_owned_input(owned);
    if (kill(-owned.pid, SIGKILL) && errno != ESRCH) fail("Owned process group could not be completed");
    int value = 0;
    pid_t result;
    do { result = waitpid(owned.pid, &value, 0); } while (result < 0 && errno == EINTR);
    if (result < 0) fail("Owned process could not be reaped");
    owned.status = WIFEXITED(value) ? WEXITSTATUS(value) : 128 + WTERMSIG(value);
    owned.finish_logs = true;
    return owned.status;
}
void bounded_strings(const std::vector<std::string>& strings, std::size_t maximum) {
    if (strings.size() > maximum) fail("Too many process arguments");
    for (const auto& value : strings) if (value.size() > 16384 || value.find('\0') != std::string::npos) fail("Invalid process argument");
}
}

std::int64_t start(const StartOptions& options) {
    bounded_strings(options.arguments, 128); bounded_strings(options.environment, 64);
    bounded_strings({options.executable, options.cwd, options.input, options.output, options.error}, 5);
    if (options.executable.empty() || options.executable[0] != '/' || options.cwd.empty() || options.cwd[0] != '/') fail("Process paths must be absolute");
    if (options.output == options.error) fail("Process log paths must differ");
    if (options.interactive_input && !options.input.empty()) fail("Interactive process input cannot use a file");
    std::vector<std::string> values{options.executable};
    values.insert(values.end(), options.arguments.begin(), options.arguments.end());
    std::vector<char*> argv, env;
    for (auto& value : values) argv.push_back(value.data());
    argv.push_back(nullptr);
    for (const auto& value : options.environment) env.push_back(const_cast<char*>(value.c_str()));
    env.push_back(nullptr);
    int input = -1, output = -1, error = -1;
    int in_pipe[2]{-1,-1}, out_pipe[2]{-1,-1}, err_pipe[2]{-1,-1}, exec_pipe[2]{-1,-1};
    pid_t child = -1;
    try {
        if (options.interactive_input) {
            if (pipe2(in_pipe,O_CLOEXEC) || fcntl(in_pipe[1],F_SETFL,O_NONBLOCK) ||
                    fpathconf(in_pipe[1],_PC_PIPE_BUF)<4096) fail("Cannot create bounded process input pipe");
            input=in_pipe[0]; in_pipe[0]=-1;
        } else input = options.input.empty() ? open("/dev/null", O_RDONLY | O_CLOEXEC) : regular_file(options.input, false);
        if (input < 0) fail("Cannot open process input");
        output = regular_file(options.output, true); error = regular_file(options.error, true);
        if (pipe2(out_pipe, O_CLOEXEC) || pipe2(err_pipe, O_CLOEXEC) || pipe2(exec_pipe, O_CLOEXEC)) fail("Cannot create process pipes");
        std::lock_guard<std::mutex> guard(registry_mutex);
        // Reap/drop completed handles before imposing the outstanding-process cap.
        for (auto i = registry.begin(); i != registry.end();) {
            if (registry.size() >= 64 && i->second->status != running && i->second->diagnostics_consumed) i = registry.erase(i); else ++i;
        }
        if (registry.size() >= 64) fail("Owned process limit reached");
        const pid_t parent = getpid();
        const long descriptor_limit = sysconf(_SC_OPEN_MAX);
        if (descriptor_limit < 0) fail("Cannot determine inherited descriptor bound");
        sigset_t empty_signals;
        sigemptyset(&empty_signals);
        struct sigaction default_signal{};
        default_signal.sa_handler = SIG_DFL;
        sigemptyset(&default_signal.sa_mask);
        child = fork();
        if (child < 0) fail("Cannot create native child");
        if (child == 0) {
            // Only async-signal-safe/syscall operations after forking the JVM.
            int problem = 0;
            if (sigprocmask(SIG_SETMASK, &empty_signals, nullptr) ||
                sigaction(SIGTERM, &default_signal, nullptr) || sigaction(SIGINT, &default_signal, nullptr) ||
                sigaction(SIGPIPE, &default_signal, nullptr) || sigaction(SIGCHLD, &default_signal, nullptr) ||
                prctl(PR_SET_PDEATHSIG, SIGKILL) || getppid() != parent || setpgid(0,0) || chdir(options.cwd.c_str())) problem = errno ? errno : ECHILD;
            umask(0077);
            if (!problem && (dup2(input, 0) < 0 || dup2(out_pipe[1], 1) < 0 || dup2(err_pipe[1], 2) < 0)) problem = errno;
            // Prevent inherited JVM/application fds leaking into the server.
            // close_range is optional on Android kernels; the fallback covers the
            // real descriptor limit, rather than silently leaking high JVM fds.
            bool closed_range = false;
#ifdef SYS_close_range
            closed_range = (exec_pipe[1] == 3 || syscall(SYS_close_range, 3u, static_cast<unsigned>(exec_pipe[1]-1), 0u) == 0) &&
                syscall(SYS_close_range, static_cast<unsigned>(exec_pipe[1]+1), ~0u, 0u) == 0;
#endif
            if (!closed_range) for (long fd = 3; fd < descriptor_limit; ++fd) if (fd != exec_pipe[1]) close(static_cast<int>(fd));
            if (!problem) execve(options.executable.c_str(), argv.data(), env.data());
            if (!problem) problem = errno;
            const auto ignored = write(exec_pipe[1], &problem, sizeof(problem));
            (void)ignored;
            _exit(127);
        }
        close_fd(input); close_fd(out_pipe[1]); close_fd(err_pipe[1]); close_fd(exec_pipe[1]);
        int problem = 0;
        pollfd exec_ready{exec_pipe[0], POLLIN | POLLHUP, 0};
        int ready;
        do { ready = poll(&exec_ready,1,5000); } while (ready < 0 && errno == EINTR);
        if (ready <= 0) fail("Native executable startup timed out");
        ssize_t got;
        do { got = read(exec_pipe[0], &problem, sizeof(problem)); } while (got < 0 && errno == EINTR);
        close_fd(exec_pipe[0]);
        if (got != 0) { waitpid(child, nullptr, 0); child = -1; fail("Native executable did not start"); }
        auto owned = std::make_shared<Owned>(child);
        owned->interactive_input=options.interactive_input;
        owned->input_fd=in_pipe[1]; in_pipe[1]=-1;
        owned->output_thread = std::thread(drain, out_pipe[0], output, owned.get(), 0); out_pipe[0] = output = -1;
        owned->error_thread = std::thread(drain, err_pipe[0], error, owned.get(), 1); err_pipe[0] = error = -1;
        const auto handle = next_handle++;
        registry.emplace(handle, owned);
        child = -1;
        return handle;
    } catch (...) {
        if (child > 0) { kill(-child, SIGKILL); kill(child, SIGKILL); waitpid(child, nullptr, 0); }
        close_fd(input); close_fd(output); close_fd(error);
        for (int* pair : {in_pipe,out_pipe,err_pipe,exec_pipe}) { close_fd(pair[0]); close_fd(pair[1]); }
        throw;
    }
}

bool write_input(std::int64_t handle, const void* bytes, std::size_t size, std::int64_t timeout_ms) {
    if (!bytes || !size || size>4096 || timeout_ms<0 || timeout_ms>1000) fail("Invalid bounded process input request");
    auto owned=lookup(handle);
    if (!owned->interactive_input) fail("Owned process input is not interactive");
    const auto end=std::chrono::steady_clock::now()+std::chrono::milliseconds(timeout_ms);
    std::unique_lock<std::timed_mutex> guard(owned->input_mutex,std::defer_lock);
    if (!guard.try_lock_until(end)) return false;
    PipeSignal signal;
    while (true) {
        if (owned->input_closing || owned->status!=running || owned->input_fd<0) fail("Owned process input is closed");
        // Nonblocking writes <=PIPE_BUF are all-or-nothing, including a timeout.
        const ssize_t count=write(owned->input_fd,bytes,size);
        if (count==static_cast<ssize_t>(size)) return true;
        const int problem=errno;
        if (count<0 && problem==EPIPE) {
            signal.broken(); owned->input_closing=true; close_fd(owned->input_fd);
            fail("Owned process input is closed");
        }
        if (count>=0 || (problem!=EAGAIN && problem!=EWOULDBLOCK && problem!=EINTR)) fail("Owned process input write failed");
        const auto now=std::chrono::steady_clock::now();
        if (now>=end) return false;
        const auto remaining=std::chrono::duration_cast<std::chrono::milliseconds>(end-now).count();
        pollfd watched{owned->input_fd,POLLOUT,0};
        const int ready=poll(&watched,1,static_cast<int>(std::clamp<std::int64_t>(remaining,1,20)));
        if (ready<0 && errno!=EINTR) fail("Owned process input wait failed");
    }
}

void close_input(std::int64_t handle) {
    auto owned=lookup(handle);
    if (!owned->interactive_input) fail("Owned process input is not interactive");
    close_owned_input(*owned);
}

int process_id(std::int64_t handle) {
    auto owned = lookup(handle);
    std::lock_guard<std::mutex> guard(owned->mutex);
    if (owned->status != running) fail("Owned process has already exited");
    // Observation only: never reap or clean up descendants while taking identity.
    siginfo_t info{};
    int result;
    do { result = waitid(P_PID, static_cast<id_t>(owned->pid), &info, WEXITED | WNOHANG | WNOWAIT); }
    while (result && errno == EINTR);
    if (result) fail("Owned process could not be observed");
    if (info.si_pid) fail("Owned process has already exited");
    return owned->pid;
}

std::array<std::int64_t,5> diagnostics(std::int64_t handle) {
    auto owned = lookup(handle);
    const bool final = owned->logs_joined.load();
    const std::array<std::int64_t,5> result={owned->observed[0].load(), owned->stored[0].load(), owned->observed[1].load(),
        owned->stored[1].load(), owned->io_failures.load()};
    // Never evict a completed handle in the wait-for -> final metrics gap.
    // Live sampling cannot mark final diagnostics consumed.
    if (final) owned->diagnostics_consumed = true;
    return result;
}

int wait_for(std::int64_t handle, std::int64_t timeout_ms) {
    auto owned = lookup(handle);
    const auto end = std::chrono::steady_clock::now() + std::chrono::milliseconds(std::clamp<std::int64_t>(timeout_ms,0,600000));
    do {
        { std::lock_guard<std::mutex> guard(owned->mutex); const int value = poll_owned(*owned); if (value != running) {
            if (owned->output_thread.joinable()) owned->output_thread.join();
            if (owned->error_thread.joinable()) owned->error_thread.join();
            owned->logs_joined = true;
            return value;
        } }
        if (std::chrono::steady_clock::now() >= end) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    } while (true);
    return running;
}

int stop(std::int64_t handle, std::int64_t grace_ms) {
    auto owned = lookup(handle);
    close_owned_input(*owned);
    int completed;
    {
        std::lock_guard<std::mutex> guard(owned->mutex);
        completed = poll_owned(*owned);
        if (completed == running && kill(-owned->pid, SIGTERM) && errno != ESRCH) fail("Owned process shutdown failed");
    }
    if (completed != running) return wait_for(handle,0);
    const int value = wait_for(handle, std::clamp<std::int64_t>(grace_ms,0,30000));
    if (value != running) return value;
    {
        std::lock_guard<std::mutex> guard(owned->mutex);
        if (poll_owned(*owned) == running && kill(-owned->pid, SIGKILL) && errno != ESRCH) fail("Owned process forced shutdown failed");
    }
    return wait_for(handle,5000);
}
}
