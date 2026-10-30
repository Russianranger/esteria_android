# Native process ownership

The Android adapter can execute a verified installed PRoot payload against a
verified runtime generation. It is not connected to the launcher play action.
There is no display, audio, game readiness or successful-save claim from launch.

`process_owner.cpp`, its header and native tests adapt the MIT-licensed
Russianranger/fta-launcher revision
`7a9ce45988f295824d20c9ff7436a77a0baa4f07`; the complete notice is adjacent.
No reference repository was changed. UO's real X11-to-Surface, ALSA-to-AudioTrack
and controller transport informed the process boundary, but are separate bridges.

The owner forks/execs with an explicit environment and argv; no shell is used by
the app adapter. It resets inherited signal masks/dispositions, owns a process
group, closes inherited descriptors, and checks the exec handshake before
publishing an opaque handle. Only owned handles can be observed or stopped.
`waitid(WNOWAIT)` reserves the exited leader PID until group cleanup is complete,
preventing signals to a recycled process group. Foreground commands must not
daemonize away from their owner. Detached PRoot tracees are covered by the
packaged tracer's required `PTRACE_O_EXITKILL`; native process-group ownership
alone is not a detached-descendant guarantee.

Linux `PR_SET_PDEATHSIG` follows the creating thread. `OwnedProcess` therefore
creates and waits on its native child on one dedicated lifetime thread. Returning
from an Android service task or rotating an Activity does not end that thread.
Killing the app/owner kills the tracer and, through EXITKILL, its traced guest
processes. This is crash containment, not a successful database/world save.

The service must retain the `SessionSupervisor.Child`, supply a real bounded
component shutdown request, and call `stop` off the main thread. Without a real
acknowledged shutdown and zero exit, signal termination is reported as failure.
Callback failures/timeouts trigger owned termination and remain visible.
Foreground lifecycle wiring and each server's save acknowledgement are pending.

Stdin defaults to `/dev/null`. Explicit `Specification.interactiveInput=true`
and `OwnedProcess.startInteractive` provide a private CLOEXEC pipe whose writer
remains attached to the opaque owned handle. `writeInput(bytes, timeout)` accepts
1–4,096 bytes and a timeout of zero to one second. The pipe's atomic-write bound
is checked; a timeout returns false with **zero bytes queued**, rather than
sending a partial console command. Concurrent callers serialize within that same
deadline. Reader closure raises an I/O error without changing the JVM's global
SIGPIPE handler. `closeInput()` sends EOF; normal completion, forced cleanup and
owner death also close the descriptor. Cleanup interrupts a blocked writer within
one 20-ms poll slice plus scheduling time. Input bytes are never included in owner
diagnostics or exceptions; child programs may still produce their own output.

`ProotProcess.startInteractive` exposes the same explicit opt-in for verified
guest launches. `WorldConsoleShutdown` queues the pinned server's
`server shutdown 1\n` command and keeps stdin open through process completion.
See [the source-backed shutdown contract](../../runtime/WORLD-SHUTDOWN.md).
Pipe acceptance is not command acknowledgment or character-save evidence.

Each pipe is continuously drained, storing at most 8 MiB in a private mode-0600
regular file. Excess output is counted/discarded, avoiding pipe deadlock without
unbounded disk growth. I/O failures are reported separately. Final drain is
bounded. Logs may contain runtime output, so support export still uses the
existing redaction policy; secrets must not be passed in command lines.

`ProotProcess` accepts only private canonical runtime/work/session directories.
The fresh session owns temporary files and logs; mutable home/prefix/database
data belongs under the persistent work directory, outside runtime generations.
The command environment is explicit. PRoot binds `/dev` and `/proc` for Linux
compatibility and is **not a network or security sandbox**. Imported rootfs
contents are not protected from guest writes by this adapter; setup integrity
verification will reject changed required components. Runtime write protection
and the actual guest launch profile remain qualification work.

Run real Linux native and JVM/JNI behavior checks:

```sh
JAVA_HOME=/path/to/jdk17 python3 tools/check_process_owner.py --output /tmp/owner-evidence
```

Add `--ndk /path/to/android-ndk-r28c` for an actual Android API26 ARM64
cross-build with static libc++ and 16 KiB ELF alignment. This emits a receipt with
distinct host execution and Android cross-build fields. For the APK, install SDK
packages `ndk;28.2.13676358` and `cmake;3.22.1`, then run:

```sh
./gradlew :app:assembleDebug :app:lintDebug -PnativeRuntimeBridge=true \
  -PprootProviderDir=/absolute/path/to/verified/proot/provider
```

The option builds the process owner and independent presentation JNI bridge;
their source license notices are embedded in APK assets. The normal build stays
unchanged. `-PnativeBridgeAbi=x86_64`, without the ARM64 PRoot provider, builds
only the process owner for Android emulator qualification; it cannot execute
the ARM64 guest. See [execution policy](../../runtime/ANDROID-EXECUTION.md).

The native suite executes success/nonzero exits, idempotence, TERM/KILL, blocked
signals, concurrent wait/stop, unrelated-child isolation, process-group cleanup,
abrupt parent death, 80-command churn, log bounds and rejected executable,
handle/symlink/hardlink inputs. Twelve JVM/JNI groups additionally exercise Unicode
paths/arguments, lifetime after the launching caller thread exits, a real
file-mediated graceful-save fixture, observable forced/request-failure cleanup,
both bounded pipe drains, interrupted-launch cleanup, exec failure and PRoot argv/state separation,
binary stdin/EOF, real full-pipe backpressure without partial messages, concurrent
input close, closed-reader EPIPE and exact console-command delivery to a normal-exit
fixture. The native owner-death fixture also enables the input pipe.
These are Linux host fixtures; neither Android execution nor guest/gameplay is
established by their success.

Final diagnostics must be consumed before a completed handle becomes eligible
for bounded-registry eviction. A 64-handle pressure/concurrent-start test ensures
completion cannot race a new launch into losing its final metrics.
