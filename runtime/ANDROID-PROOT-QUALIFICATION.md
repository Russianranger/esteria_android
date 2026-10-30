# Android PRoot and private glibc qualification

The opt-in `.github/workflows/android-proot-execution.yml` builds a separate
**x86_64 emulator-only** PRoot provider from the pinned Termux/talloc sources,
existing adaptations and mandatory EXITKILL patch. Its tracer and freestanding
loader have their own exact binary hashes. Production ARM64 provider locks,
verification and application selection are unchanged.

`native/proot-probe/glibc.lock.json` pins Debian 12 amd64 glibc 2.36-9+deb12u14,
development objects, Linux headers and the complete glibc source archives. The
package identities came from the frozen Debian snapshot's authenticated
InRelease/Packages chain. Only libc, ld.so and two newly compiled diagnostics
enter the minimal runtime. This fixture is independent of the Wine/server trees.
The NDK version and actual compiler hash are recorded. NDK clang/lld compile
against the pinned Debian sysroot, so host headers and glibc are not build inputs.
Corresponding-source output contains original archives, patches, integration
code, licenses and relinkable talloc objects; NDK proprietary tools are excluded.

The mandatory instrumentation installs the real native owner, tracer and loader
through Android's `nativeLibraryDir`, streams/readbacks the exact Linux
files into private storage, and invokes PRoot using `PROOT_LOADER`. It verifies:

- Direct execution of the identical Bionic tracer copied into private storage
  is rejected; positive execution then uses its installed APK location. This
  control avoids mistaking a missing Linux interpreter for execution denial.
- Private Linux ELF startup through the freestanding loader and real glibc2.36.
- `dlopen`/`dlsym`, separate thread-local state in an actual plugin, and pthreads.
- `fork`, child `exec`, loopback request/reply, and exact child exit status17.
- A flushed private file survives a second complete guest invocation unchanged.

The harness requires Android13/API33, targetSdk35, x86_64, an emulator serial,
and a fresh application installation. It refuses physical devices and existing
app data. One passing JUnit test, exact guest markers, normal process exits,
source/build-bound receipt and bounded logs are required. Missing native payloads
fail; they never become skipped passes. Only this test's app is force-stopped.
No SELinux/seccomp policy is changed, and the target SDK is not downgraded.

The production `ProotLaunch` uses a full guest `/usr/bin/env`; this minimal probe
passes explicit argv/environment directly because it contains no coreutils.
Passing this probe would establish the named Android x86_64 loader behavior.
It would **not** qualify Android ARM64, AYN Thor, Adreno, Wine, app-death recovery,
full rootfs services, database saves, or gameplay. Their receipt flags remain false.
Run [40998008458](https://github.com/Russianranger/esteria_android/actions/runs/40998008458)
passed on Android13 x86_64 at integration revision
`69b6b9e46ae91dac012dfb55463b81d0652191b8`. Both real guest invocations exited0,
reported glibc2.36 and every expected dynamic-library/thread/fork/exec/loopback
marker, retained the exact persistent file, and produced empty stderr. The
receipt confirms API33/targetSdk35, rejected direct private Bionic execution,
and successful execution through the installed tracer/loader. The evidence ZIP
SHA-256 is `9f08e7cc1461f04467730d7b25e1513b1284d91a9041c3bae187b7a1e176f2a9`.
This qualifies the stated x86_64 scope only. Native Linux fixture tests separately
establish diagnostic logic; they are not the Android evidence.

## Tracer-death and graceful-stop extension

The next qualification adds one source-built ownership guest and a separate
byte-pinned tracer control whose only source difference is omission of EXITKILL.
The probe profile disables release variants and requires a debug APK. Normal
native builds explicitly set the test CMake option OFF; production ARM64 provider
verification rejects these extra filenames. The control is never a selectable
application runtime.

The fixture forks twice and places each of three tracees in its own session,
outside the native owner's process group. Their bounded handshake reports PID,
kernel start time, kernel tracer PID/start time, and session identity. The
emulator-only JNI observer opens pidfds, checks app UID, matching procfs PID
namespace, exact start time, exact installed tracer/loader executable and the
private guest's executable mapping before retaining opaque handles. Signals
target only these descriptors; process names or recycled numeric PIDs are never
signal targets.

Forced-mode guests publish three separate shared-memory readiness bytes after
their final setup syscall, then wait in a bounded user-space CPU loop. The test
requires all three bytes before killing the tracer. This avoids an unrelated
Android syscall-policy failure after removing PRoot: the first actual extension
run [41002275287](https://github.com/Russianranger/esteria_android/actions/runs/41002275287),
at `ce45a79fb3786ab0e16ea8055a2c2bd0fbb7d444`, failed its unpatched control while
the guests called Linux `pause()`. Android logcat records SIGSYS (31) for all
three identities; the test correctly refused to count their deaths as EXITKILL.
No Android policy or production-runtime setting is changed by the correction.

The test kills only the verified tracer. The unpatched control must leave all
three detached tracees alive, whereas EXITKILL must terminate all three. Native
process-group cleanup cannot create this result because every observed tracee
has detached. `am force-stop` runs only after observations as final test cleanup,
and cannot establish the ownership result. All retained descriptors receive
explicit cleanup, poll and close; fixture alarms bound failures before a complete
identity handshake. A strict 25-second budget starts before process creation and
must contain all forced observations, so the 30-second guest alarms cannot create
a false ownership pass. Pidfd or procfs restrictions fail the gate explicitly.

A separate real graceful callback creates a stop request. Each guest writes and
fsyncs its save record, parents wait for normal child exits, and a fresh guest
invocation reads all three exact records back. This establishes fixture file
persistence, not database/world save correctness. Whole-application termination
and production ARM64 execution remain separate unqualified gates.

The corrected fixture passed on the actual Android13 x86_64 emulator in
[run41003838793](https://github.com/Russianranger/esteria_android/actions/runs/41003838793)
at `3ae7b69412fec80dfe35f69e89a29d5eb728a665`. Its verified receipt records
three unpatched survivors after 1,383 ms, zero patched survivors after 478 ms,
all three armed flags, three graceful save records and a successful fresh guest
readback. Six real guest invocations completed. Evidence ZIP 12954448262 has
SHA-256 `034527c4d8acb7bf17763b038ff9c6667fda1f5e8f6ccbc3851acb3d54900fcd`.
The checked APK is 2,262,394 bytes, SHA-256
`e98abdee2eb9282a5c0c9abb69769a7c9ab2cf59d680d409602f066c840dff5e`.
ARM64, Android Wine, whole-application death and gameplay remain unqualified.

`tools/check_proot_probe_pidfd.py` runs real Linux/JVM pidfd identity, isolated
termination and stale-handle tests in the normal CI VM. The managed development
host has different syscall/procfs PID namespaces (`getpid=5`, `/proc/self=133684`
was observed), so it cannot supply this execution evidence; the helper fails
closed there. The normal CI VM passed this host pidfd gate in run41002275287.
The corrected Android tracer result is recorded above.

## Remote Android owner-process death

The explicit probe profile additionally compiles a nonexported bound Service in
`:prootOwnerProbe`. Its manifest and Java source set are excluded from ordinary
APK builds; release variants remain disabled for the probe profile. A real
`OwnedProcess` in this separate Android process starts the pinned tracer/loader
and three detached guests. The surviving instrumentation process owns another
matching chain as a control. No arbitrary program/path is accepted by the Service.

Instrumentation checks the Service's UID, executable and kernel start time using
a retained pidfd, and verifies both tracers and all six guest identities/armed
flags. It kills only the exact Service descriptor, requires its tracer and three
guests to exit, and requires the instrumentation-owned tracer and three guests to
remain alive. All observations must finish within 25 seconds of the prelaunch clock;
cleanup signals only retained descriptors and then stops the owned control.
The complete test now requires eight guest launches and nine verified handles
for this additional case. The existing separate graceful-persistence case remains.

This measures combined Android and application ownership cleanup, **not isolated
PDEATHSIG behavior**. Android13's
[ActivityManagerService.appDiedLocked](https://github.com/aosp-mirror/platform_frameworks_base/blob/android-13.0.0_r1/services/core/java/com/android/server/am/ActivityManagerService.java#L3293)
also calls `ProcessList.killProcessGroup` after process/Binder death, so a control
spawned inside the killed Service could be removed by OS cgroup cleanup itself.
The surviving control instead demonstrates that the test did not kill the whole
app UID. Receipts keep `isolatedParentDeathSignalQualified` and whole-application
`appDeathQualified` false.

Actual Android13 x86_64 execution passed in
[run41006180061](https://github.com/Russianranger/esteria_android/actions/runs/41006180061),
at `73f694c35ffaa6f0f7f8e9bab9eb30b79c84b5d4`. The remote Service, its tracer and
all three detached guests exited while the instrumentation-owned control tracer
and all three control guests remained alive. Nine process descriptors were
verified and the observation completed in 4,115 ms, within the pre-alarm limit.
All eight guest launches, the earlier patched/unpatched tracer cases and graceful
save/relaunch checks passed. The separate clean ordinary APK build also passed
the bounded manifest, DEX, asset and native-library exclusion check.

Evidence ZIP 12956265170 has SHA-256
`927cfd8fd99688e0e5b4ac0270199de33cfd3bd94be68ae4518a87e4338c89d6`.
The actual probe APK is 2,271,150 bytes, SHA-256
`ec374bd6e322bd8931e560b9221bfac4a6ad837a8ed40a478ce164fd33e4dd92`.
This establishes Android emulator owner-process cleanup with the scope above;
ARM64 guest execution, Wine, database/world saves, whole-app termination and Thor
gameplay remain separate gates.

To reproduce with Python3.12+, dpkg-deb, JDK17 and the documented Android SDK:

```sh
python3 tools/build_android_proot_probe.py --sources /cache/runtime-corresponding-sources.tar.gz \
  --ndk "$ANDROID_HOME/ndk/28.2.13676358" --cache /cache/probe \
  --download --work /tmp/new-proot-probe
./gradlew :app:clean :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug \
  -PnativeRuntimeBridge=true -PnativeBridgeAbi=x86_64 \
  -PprootProbeProviderDir=/tmp/new-proot-probe/provider -PsourceRevision=<full-commit>
python3 tools/qualify_android_proot.py --provider /tmp/new-proot-probe/provider \
  --apk app/build/outputs/apk/debug/app-debug.apk \
  --test-apk app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk \
  --source-revision <full-commit> --output /tmp/new-proot-evidence
```

The probe provider is mutually exclusive with the production ARM64 provider and
the separate presentation emulator profile. Do not distribute its APK as a Thor
candidate or a normal application update. It uses only a disposable CI debug key.
