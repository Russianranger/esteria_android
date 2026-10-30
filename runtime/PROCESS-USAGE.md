# Owned process usage observations

`OwnedProcess.usage()` accepts no PID or path. It observes only its own private
opaque native handle and returns immutable `ProcessUsageSnapshot` metadata.
`OwnedProcess.logPaths()` separately returns an immutable map containing the
validated launch specification's `stdout` and `stderr` paths. It reads/exports
nothing and exposes no command, input, environment or credentials. Support
export must still whitelist fixed component roles and apply its redaction and
credential exclusions before reading those files.

The scope is always `visible-owned-native-group-members-only`. Native ownership
tracks one PGID, not an authenticated descendant table. PRoot tracees can detach
from that PGID and are covered for crash containment by the separately qualified
tracer's EXITKILL contract; that does not add them to this sampler. Even same-PGID
members may be hidden by a managed or Android proc projection. Every snapshot
therefore carries `VISIBILITY_UNVERIFIED` and
`wholeGroupMembershipVerified()` always returns false. No observation here
qualifies whole-group/whole-guest memory, combined client/server memory or a bot
population budget. Those require additional source-owned guest/process coverage.

The native entry point looks up the known handle, observes the child with
`waitid(WNOWAIT)`, and captures its proc directory descriptor while the leader PID
is reserved by the owner. It releases the owner mutex before proc reads. Every
member is opened relative to a proc directory descriptor, checked against its
initial PID/starttime/PGID, and checked again after resource reads. The bound
leader is rechecked throughout. A final actual owner status/`waitid` check after
sampling discards every counter if reaping won the race; a busy owner also
returns explicit unavailable data. Sampling never reaps, signals or changes
shutdown, failure or the existing five-element log-diagnostics ABI. Proc output
alone is not trusted to prove a reaped leader still exists.

Work is bounded to8,192 numeric entries per scan, two scans,128 sampled group
members,8KiB stat records and128KiB smaps_rollup records. The100ms scan budget is
cooperative between proc operations. A kernel proc read itself can take longer;
there is no hard100ms wall-clock guarantee. No process-owner/reap mutex is held
during that read. Call this API on one background sampling worker and avoid
concurrent polling; it currently has no per-owner single-flight guard. A missing
`smaps_rollup` is explicit unavailability; there is no expensive full-smaps
fallback.

Public fields give visible member counts, per-metric measured counts, flags,
scanned entries, denied attempts, changed identities and monotonic window timing.
Denied attempts may count the same hidden entry on both scans. `visibleSetStable`
means two bounded visible censuses matched with stable observed identities. It
never means all actual group members were visible or an atomic simultaneous
snapshot. The complete-for-observed-set getters are:

- `visibleMembersRssBytes()`: approximate kernel stat RSS pages times the actual
  page size. Shared pages may be counted once per visible member.
- `visibleMembersPssBytes()`: smaps_rollup Pss in bytes, only if every observed
  member supplied PSS. Missing or denied members yield an empty OptionalLong.
- `visibleMembersCpuNanos()`: accumulated user+system ticks of currently visible
  members, excluding child-time counters, converted using actual clock ticks.
  This is not CPU percentage, whole-tree time or session lifetime CPU.

A census change/limit/denial that prevents a stable visible set makes all sum
getters empty. Individual PSS denial can leave separately complete visible RSS
and CPU observations available. Raw partial sums remain private. Unsupported
backends, old JNI linkage, native errors, busy cleanup and a non-live leader all
have explicit flags; they do not modify process failure or its shutdown policy.
Do not add these observations into a total combined-memory/PSS figure.

Validation is deliberately split:

- The Linux C++ fixture verifies actual leader+fork same-PGID identities,
  unrelated owner isolation, unchanged reaping/stop behavior and public
  post-reap NOT_RUNNING/zero observations. Synthetic proc fixtures verify exact
  stat/PSS parsing, denied/missing fields, identity replacement, omitted members
  and byte/entry/member/time limits.
- The managed host actually omits or mismatches the known same-PGID child in
  procfs, can hide the leader path, and denies PSS. Its real JNI observation is
  flags4610 with no RSS/PSS/CPU sum. This is an unavailable observation, not a
  successful memory measurement. The actual EACCES fixture skips here because
  root cannot switch to the unmapped test UID; normal unprivileged CI executes
  that check.
- The real host JNI suite has15 groups, including usage/reap concurrency,
  unknown/dead opaque handles, immutable log paths and typed denial semantics.
- `NativeProcessOwnershipTest#ownedGroupUsageObservation` is a separate Android13
  x86_64 instrumentation method using real system-shell children. Its existing
  qualifier collects a separate strict receipt, accepting explicit denied/null
  metrics while refusing full-group/combined/bot claims. Local compilation or
  ARM64 cross-compilation does not establish that method executed.

The separate native checker receipt and SDK build evidence record exact source
and artifact identities. No game data, Wine guest, server/database, bot AI,
Android ARM64, Thor hardware or gameplay execution is established by these host
fixtures or native library cross-builds.
