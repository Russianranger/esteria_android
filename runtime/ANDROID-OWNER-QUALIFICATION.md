# Android native owner qualification

`.github/workflows/android-process-owner.yml` builds the JNI process owner for
x86_64 and runs one mandatory instrumentation method on a disposable Android 13
emulator. It uses the existing stable application ID, targetSdk35 and a CI debug
key. It refuses to overwrite an existing app installation or operate on a
physical/remote device. The unchanged installer/update workflow selects only
its own instrumentation methods.

This job deliberately has no ARM64 PRoot provider and no presentation JNI
library. `-PnativeRuntimeBridge=true -PnativeBridgeAbi=x86_64` builds the actual
owner source. The test asserts that its library exists, loads it through the
real app class, and executes `/system/bin/sh` through the native fork/exec path.
A missing library or skipped/zero-test result is a failure.

The original six groups establish Unicode paths/arguments and nonzero exit, creator-thread
lifetime with a file-mediated graceful-save fixture, forced-stop failure,
failed-shutdown-request cleanup, continuously drained independent stdout/stderr
(9,000,000 bytes each, capped at 8 MiB stored), and missing-executable rejection.
The shell snippets are test fixtures; production PRoot commands remain explicit
argv without a shell wrapper. This does not initialize or save a real database.

The expanded nine-group fixture also requires binary stdin/EOF, a real full-pipe
timeout with no partial command, close/write cancellation, closed-reader EPIPE
without host termination, and exact `server shutdown 1` delivery to a normal-exit
shell fixture. All nine groups passed actual emulator execution in the run recorded
below. Receipts must explicitly retain false
world-shutdown and character-persistence fields. See [WORLD-SHUTDOWN.md](WORLD-SHUTDOWN.md).

The harness requires one completed successful JUnit result, then retrieves the
app-generated receipt via `run-as`, verifies its exact source revision,
fingerprint, SDK, ABI, counts and booleans, and preserves bounded diagnostics.
It records both APK hashes. Cleanup stops only the application installed by this
disposable test. Failure retains a false qualification flag and useful logs.

Scope remains **Android13 x86_64 JNI + system-process ownership**. App-process
death, foreground-service/Activity lifecycle, Android ARM64 PRoot/private ELF
loading, Wine, display, audio, database saves and gameplay remain separate gates.
The receipt explicitly keeps their qualification fields false.

Local reproduction needs the pinned SDK35/build-tools35.0.0, NDK28.2.13676358,
CMake3.22.1 and a disposable API33 x86_64 emulator:

```sh
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug \
  -PnativeRuntimeBridge=true -PnativeBridgeAbi=x86_64 -PsourceRevision=<full-commit>
python3 tools/qualify_android_owner.py \
  --apk app/build/outputs/apk/debug/app-debug.apk \
  --test-apk app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk \
  --source-revision <full-commit> --output /tmp/new-android-owner-evidence
```

The managed development host's inability to run its own Android emulator does
not count as an Android failure. The hosted emulator result is the execution
gate, and must be read before this workflow is marked qualified.

Run [40994809786](https://github.com/Russianranger/esteria_android/actions/runs/40994809786)
passed all six groups on the Android 13 x86_64 emulator at integration revision
`1f19c3abe5722ac06ab58f9af4e54b2f27f54ec8`. Its receipt reports targetSdk35,
9,000,000 bytes drained and 8,388,608 retained per pipe. The evidence artifact
SHA-256 is `555d4665600634db0fe54b9818e556a1da9e0ef4706b58516518823796f6d1d6`.
This qualifies the stated system-process scope only; the separate gates above
remain open.

Run [41003838802](https://github.com/Russianranger/esteria_android/actions/runs/41003838802)
passed all nine groups on Android13 x86_64 at integration
`3ae7b69412fec80dfe35f69e89a29d5eb728a665`. The receipt requires true binary
stdin/EOF, backpressure/close, EPIPE and console-command fixture checks, while
world shutdown and character persistence remain false. Artifact `12954512975`
is 46,859 bytes with SHA-256
`557633efe5b3f16b0a1bb02031fc1a8dd20a11f78f8c77a7099067d28899aae6`.
At the same revision, native Linux x64 and ARM64
[run 41003838751](https://github.com/Russianranger/esteria_android/actions/runs/41003838751)
passed the native ownership suite and all 12 real JVM/JNI groups.
