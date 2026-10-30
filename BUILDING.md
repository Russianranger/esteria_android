# Building Esteria Android

Build from `android/client-server`. `sources.lock.json` is authoritative; its branch labels never choose build inputs. Existing GPL-3.0 LICENSE is unchanged.

## Pinned sources
```
python3 tools/fetch_sources.py all
python3 tools/verify_protocol.py --client sources/client --server sources/server
```
Source preparation requires Git and Python 3.10+. It verifies full commit IDs and Eluna's gitlink, rejects modified or differently pinned checkouts, and never resets developer changes. Use `--offline` once all sources are prepared. To change a pin, review the source change, update the lock and use a fresh output directory. Server patches must be listed in order with SHA-256 in the lock.

## Windows reconstructed client
Visual Studio 2022 C++ desktop tools, Windows SDK, ARM64 C++ toolset, CMake and Python. Build both architectures (see client platform instructions for codec source prerequisites):
```
cmake -S sources/client -B out/client-arm64 -G "Visual Studio 17 2022" -A ARM64 -DWOWDECOMP_EXTENDED_LIMITS=ON -DWOWDECOMP_CONTAINER_SLOTS=254 -DWOWDECOMP_QUEST_LOG_SLOTS=25 -DWOWDECOMP_MAX_CLASSES=32
cmake --build out/client-arm64 --config Release --target WowClient --parallel 2
```
Replace ARM64 with x64 and use a separate build directory for the desktop reference. Full executable compilation is tracked separately from portable component tests. Shaders require user-supplied matching client data; see ASSET-REQUIREMENTS.md.

## Linux ARM64 server
First build environment: Ubuntu 24.04 ARM64 with GCC, CMake, Ninja, Boost development packages, OpenSSL, MySQL 8 client development package, readline, bzip2 and zlib. Eluna uses the source revision in the lock and Lua 5.2.4. `.github/workflows/server.yml` provides the concrete build. It retains static scripts/modules and builds extraction tools. Two compiler jobs bound peak build memory.

MySQL 8 is required by the selected source. MariaDB is not a drop-in qualified substitution: both compile-time and runtime version checks reject it. Server artifacts do not include a seeded database, extracted game data or an Android runtime.

## Android toolchain
JDK 17, Android SDK platform 35 / build-tools 35.0.0, Gradle 8.9 / AGP 8.7.3. The app and core are Java; host core tests require no game data. The Gradle wrapper pins its distribution hash. APK compilation initially validates the launcher and core only. The runtime and gameplay gates must pass before calling it a device candidate.

## Signing and reproducibility
Keep `*.jks`, `*.keystore`, private runtime configurations and game assets out of Git. A user-deliverable development APK must use one persistent privately stored key and carry the application/client/server source revisions and runtime hashes. This is not yet a bit-identical reproducible APK promise: SDK/compiler/runtime package locks and release signing qualification remain to be completed.
