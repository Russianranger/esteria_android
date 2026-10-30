# Android PRoot process bridge

This builds real Android Bionic ARM64 PRoot and its freestanding ARM64 loader from
pinned source. It is a build/packaging foundation, not qualified Android guest
execution. No gameplay flag is enabled and neither binary is executed on the host.

## Reproduction

Python 3.11+, Bash, GNU make, Git, binutils/readelf, unzip support, at least 512 MiB
available memory and 6 GiB disk are required on Linux x86_64. The build uses one
compiler job. `sources.lock.json` here pins Android NDK r28c, Termux PRoot commit
`7266fb3e8516535682f5a9c8f3a7e70f6506eddb`, talloc 2.4.3, the public UO corresponding
source bundle, its exact recipe and two patches. Downloads are an explicit setup
step; the transformed build recipe uses only verified local inputs.

```sh
curl --fail --location --retry 2 https://github.com/Russianranger/uo-android-launcher/releases/download/v0.2.0/runtime-corresponding-sources.tar.gz -o /tmp/esteria-proot-sources.tar.gz
curl --fail --location --retry 2 https://dl.google.com/android/repository/android-ndk-r28c-linux.zip -o /tmp/android-ndk-r28c-linux.zip
python3 tools/build_android_proot.py --sources /tmp/esteria-proot-sources.tar.gz \
  --ndk-zip /tmp/android-ndk-r28c-linux.zip --work /tmp/esteria-proot-build
python3 tools/verify_android_proot.py --provider /tmp/esteria-proot-build/provider
./gradlew :app:assembleDebug :app:lintDebug -PprootProviderDir=/tmp/esteria-proot-build/provider
python3 tools/verify_android_proot.py --provider /tmp/esteria-proot-build/provider \
  --apk app/build/outputs/apk/debug/app-debug.apk
```

The builder rejects incorrect archive sizes/hashes, mismatched recipe fragments,
wrong patches, existing output directories and unsafe toolchain members. It copies
licenses, emits build evidence, and creates `proot-corresponding-source.tar.gz`
containing original component sources/patches, Esteria build code, license notices
and relinkable talloc objects. Keep that source companion with any distributed APK
containing these payloads. Build artifacts stay outside Git.

## Source adaptations

The recipe and ownership approach are adapted from read-only
[fta-launcher at 7a9ce45988f295824d20c9ff7436a77a0baa4f07](https://github.com/Russianranger/fta-launcher/tree/7a9ce45988f295824d20c9ff7436a77a0baa4f07),
under its retained MIT notice. Upstream source licenses remain GPL-2.0-or-later
for PRoot and LGPL-3.0-or-later for statically linked talloc. The existing Esteria
GPL-3.0 license remains unchanged.

The UO recipe supplies real Android memfd-backed SysV shared memory, a diagnostic
for observed seccomp acceleration, the missing modern-Clang string declaration,
and a portable loader-offset generator. The local patch requires
`PTRACE_O_EXITKILL` for every traced descendant, including the upstream retry.
Unsupported kernels fail before guest entry instead of dropping ownership.
The build uses NDK r28c and explicit 16 KiB loader/tracer segment alignment.

## APK installation contract

`libproot.so` is an AArch64 **PIE executable**, not a JNI shared library. It uses
`/system/bin/linker64` and only `libc.so`/`libdl.so`; talloc is static.
`libproot-loader.so` is an AArch64 freestanding **ET_EXEC** with no interpreter or
shared dependencies. Both require a non-executable stack, no writable executable
load segments, valid entry points and at least 16 KiB load alignment. The ELF
validator checks these properties and rejects search-path/SONAME surprises.

The optional Gradle `prootProviderDir` installs exact bytes as APK native libraries
with extraction enabled and AGP stripping disabled. `verify_android_proot.py`
checks provider provenance and the APK's exact payloads/notices after assembly.
`InstalledProot.inspect(context)` locates only `ApplicationInfo.nativeLibraryDir`
and checks the packaged hashes/execute access. It never downloads, copies an
executable into writable app storage, invokes `System.loadLibrary`, or starts a
guest. A plain launcher build remains possible without this provider.

Android guest execution still needs real process-owner integration, private runtime
installation, loader/temp environment, controlled bind mounts and startup/stop
qualification. Wine/display/audio, local server/database, game controls and saving
remain separate gates. Linux host or ELF checks must not be reported as Thor tests.

## Native Linux process ownership fixture

`tools/qualify_proot_ownership.py --sources <same-pinned-bundle> --work <new-dir>`
builds baseline and patched PRoot with one native GCC job. Its synthetic C process
tree includes two detached session leaders. It verifies PIDs against the actual
mapped fixture executable, keeps pidfd identities for cleanup, and compares a
negative control (three survivors after baseline tracer SIGKILL) with the mandatory
EXITKILL patch (zero survivors). Normal exit also has to pass. Outputs record the
host architecture, source/patch hashes and separate qualification scope.
The fixture has deadlines and alarms; it never signals an unverified PID. CI runs
this on Linux x64 and native ARM64. This specifically tests Linux tracer-death
ownership, not Android PRoot, saved-game shutdown or the complete client/server.
