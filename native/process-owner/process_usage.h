// Esteria process ownership observations. No PID-based public measurement API.
#pragma once
#include <cstdint>

namespace esteria {
struct GroupUsage {
    enum Flag : std::int64_t {
        proc_denied=1, membership_incomplete=2, changed=4, limit=8,
        rss_unavailable=16, pss_unavailable=32, cpu_unavailable=64,
        not_running=128, unsupported_backend=256, io_error=512,
        owner_busy=1024, native_error=2048, visibility_unverified=4096
    };
    std::int64_t start_nanos=0, duration_nanos=0, flags=visibility_unverified;
    std::int64_t scanned_processes=0, members=0, rss_members=0, pss_members=0, cpu_members=0;
    std::int64_t rss_bytes=0, pss_bytes=0, cpu_ticks=0, ticks_per_second=0;
    std::int64_t changed_members=0, denied_entries=0;
};
namespace detail {
// Internal only: the opaque owner must first bind this directory fd to its
// live, reserved leader under its mutex. The caller owns/closes the fd. This
// helper never opens a replacement numeric leader path or accepts a Java PID.
// The caller must recheck its opaque owner status after sampling and discard
// the result if concurrent native cleanup reaped/exited that owner.
// It samples only visible members of the native PGID. Enumeration cannot
// authenticate visibility of all members; visibility_unverified is always set.
// Detached PRoot tracees are outside scope.
GroupUsage sample_group(int bound_leader_fd,int expected_pid);
#ifdef ESTERIA_USAGE_TESTING
// Synthetic-proc fixtures only; not compiled into production libraries.
GroupUsage sample_group_fixture(int proc_root_fd,int bound_leader_fd,int expected_pid,
        int maximum_entries=8192,int maximum_members=128,int budget_millis=100,
        void (*after_first_scan)(void*)=nullptr,void* hook_state=nullptr);
bool parse_stat_fixture(const char* raw,int expected_pid,std::int64_t* group,
        std::int64_t* start,std::int64_t* cpu,std::int64_t* rss);
bool parse_pss_fixture(const char* raw,std::int64_t* bytes);
#endif
}
}
