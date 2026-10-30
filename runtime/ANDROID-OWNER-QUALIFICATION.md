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

Six groups establish Unicode paths/arguments and nonzero exit, creator-thread
lifetime with a file-mediated graceful-save fixture, forced-stop failure,
failed-shutdown-request cleanup, continuously drained independent stdout/stderr
(9,000,000 bytes each, capped at 8 MiB stored), and missing-executable rejection.
The shell snippets are test fixtures; production PRoot commands remain explicit
argv without a shell wrapper. This does not initialize or save a real database.

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
