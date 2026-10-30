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
through Android's `nativeLibraryDir`, streams/readbacks the four exact Linux
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
Current implementation is compiled; the hosted execution result must be inspected
before claiming Android PRoot qualification. Native Linux fixture tests establish
the diagnostic program's logic only.

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
