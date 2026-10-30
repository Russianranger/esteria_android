# Building Esteria Android

Build from `android/client-server`. `sources.lock.json` is authoritative; its branch labels never choose build inputs. Existing GPL-3.0 LICENSE is unchanged.

## Pinned sources
```
python3 tools/fetch_sources.py all
python3 tools/verify_protocol.py --client sources/client --server sources/server
```
Source preparation requires Git and Python 3.10+. It verifies full commit IDs and Eluna's gitlink, rejects modified or differently pinned checkouts, and never resets developer changes. Use `--offline` once all sources are prepared. To change a pin, review the source change, update the lock and use a fresh output directory. Server patches must be listed in order with SHA-256 in the lock.

## Windows reconstructed client
The passing reference matrix uses Visual Studio 2026 on Windows ARM64 and Visual
Studio 2022 on Windows x64, with matching C++ desktop tools, Windows SDK, CMake
3.24+ and Python. The ARM64 job runs natively on `windows-11-arm` with the
`Visual Studio 18 2026` generator. See client platform instructions for the pinned
source-built movie codec and architecture-specific optional integrations.

```sh
cmake -S sources/client/Tools/PlatformTests -B out/platform-arm64 -G "Visual Studio 18 2026" -A ARM64
cmake --build out/platform-arm64 --config Release --parallel 2
ctest --test-dir out/platform-arm64 -C Release --output-on-failure
```

```sh
cmake -S sources/client -B out/client-arm64 -G "Visual Studio 18 2026" -A ARM64 -DWOWDECOMP_EXTENDED_LIMITS=ON -DWOWDECOMP_CONTAINER_SLOTS=254 -DWOWDECOMP_QUEST_LOG_SLOTS=25 -DWOWDECOMP_MAX_CLASSES=32 -DWOWCLIENT_CRASH_LOG=ON
cmake --build out/client-arm64 --config RelWithDebInfo --target WowClient --parallel 2
```

ARM64 outputs are under `sources/client/bin/Win/ARM64`. For x64 use the VS 2022
generator, `-A x64` and separate build directories; outputs are `bin/Win`. Both
complete executables now compile/link in CI. Run `Tools/RuntimeManifest/generate.py`
with the exact source SHA, CI build identifier, binary directory, architecture and
generated `limits.json` before packaging. The client workflow contains the exact
invocation and packaged-DLL test. Shaders require matching imported data; see
[ASSET-REQUIREMENTS.md](ASSET-REQUIREMENTS.md).

## Linux ARM64 server
First build environment: Ubuntu 24.04 ARM64 with GCC, CMake, Ninja, Boost development packages, OpenSSL, MySQL 8 client development package, readline, bzip2 and zlib. Eluna uses the source revision in the lock and Lua 5.2.4. `.github/workflows/server.yml` provides the concrete build. It retains static scripts/modules and builds extraction tools. Two compiler jobs bound peak build memory.

MySQL 8 is required by the selected source. MariaDB is not a drop-in qualified substitution: both compile-time and runtime version checks reject it. Server artifacts do not include a seeded database, extracted game data or an Android runtime.

The three locked Eluna patches supply the missing `AreaTrigger` declaration,
`MapMgr.h` include and standalone integer/size type includes exposed by clean builds; `fetch_sources.py` verifies and applies it inside the exact
submodule. Compiler caches include actual compiler/package and source/patch
fingerprints and use two jobs/2 GiB. The cache can accelerate a failed build but
does not replace the source checks.

The separate dependency-image recipe in [runtime/server/README.md](runtime/server/README.md)
pins Ubuntu snapshot packages, MySQL and corresponding sources. Docker is used for
development builds and offline native ARM64 database qualification, not on-device execution.

## Android toolchain
JDK 17, Android SDK platform 35 / build-tools 35.0.0, Gradle 8.9 / AGP 8.7.3. The app and core are Java; host core tests require no game data. The Gradle wrapper pins its distribution hash. APK compilation initially validates the launcher and core only. The runtime and gameplay gates must pass before calling it a device candidate.

```sh
sha256sum --check gradle/wrapper/SHA256SUMS
./gradlew --no-daemon :core:check :app:assembleDebug :app:lintDebug
```

Set `ANDROID_HOME` and `JAVA_HOME` to installed toolchains. CI explicitly downloads
Android command-line tools 12.0 with a checked SHA-256 rather than assuming
`sdkmanager` exists on the runner. Use `-PsourceRevision=<full-application-commit>`
for recorded build provenance. Gradle embeds the complete source lock as well.

## Android native process bridge

[runtime/proot/README.md](runtime/proot/README.md) provides the exact source/NDK
inputs, one-job Bionic ARM64 build, corresponding-source companion, provider
validation and APK byte check. Pass `-PprootProviderDir=<verified-provider>` to
include the real PRoot/loader executables. Run `:app:clean` when changing provider
inputs to discard previously merged native/compressed assets. Plain launcher builds remain valid
without that provider. Build success does not qualify Android guest execution.

## Runtime staging and database qualification

[runtime/PACKAGING.md](runtime/PACKAGING.md) describes the pinned Wine candidate
and streaming, verified, offline-capable staging tool. A prepared rootfs is a host
artifact, not an Android runtime installation. Do not execute Ubuntu 24.04 server
binaries in that Debian 12 rootfs without a compatible dependency environment.

[runtime/WINE-QUALIFICATION.md](runtime/WINE-QUALIFICATION.md) describes the isolated
native ARM64 Linux codec, Vulkan and optional actual-EXE entry fixtures. It needs a real Windows ARM64 build artifact and
does not require proprietary game data. [runtime/LOCAL-SERVER.md](runtime/LOCAL-SERVER.md)
documents guarded MySQL initialization and authenticated readiness. Dedicated
database CI tests real engines; ordinary Python discovery skips those fixtures.

[runtime/ANDROID-INSTALLATION.md](runtime/ANDROID-INSTALLATION.md) documents the
app setup adapter and bounded Java installer. [runtime/SQL-PACKAGING.md](runtime/SQL-PACKAGING.md)
documents the source-backed module selection and reproducible GNU content archive.

## Android instrumentation builds

`./gradlew :app:assembleDebugAndroidTest` builds the pinned AndroidX runner and
reuses the core installer test source directly. `-PbuildVersionCode=<positive-integer>`
selects an increasing application version for update qualification. The emulator
workflow tests versions 1 and 2 with the same job-local debug key; these are internal
checks, not user-deliverable update candidates.

## Signing and reproducibility
Keep `*.jks`, `*.keystore`, private runtime configurations and game assets out of Git. A user-deliverable development APK must use one persistent privately stored key and carry the application/client/server source revisions and runtime hashes. This is not yet a bit-identical reproducible APK promise: SDK/compiler/runtime package locks and release signing qualification remain to be completed.
