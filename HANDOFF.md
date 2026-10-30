# Next-session handoff

## Authorization and current result

Continue toward a nearly complete local client/server APK for AYN Thor. Push only
client `android/arm64-port` and integration `android/client-server`; server is read-only.
Preserve default branches and shared history. Do not send preliminary APKs or
claim background development without an actual running mechanism.

The reconstructed ARM64 and x64 Windows clients build successfully. Real MySQL
bootstrap/recovery/persistence tests pass on Linux. Android currently provides
verified import, launcher UI and diagnostics, with gameplay deliberately gated.
Read [STATUS.md](STATUS.md) and current Actions results before resuming; pending
server/Wine jobs must not be converted into successful evidence without logs.

## Next concrete work

1. Fetch both development tips and inspect current Actions. Application client pin
   is `69ccfaa6a0dd01607d0a99be9b27b7b25dafc5aa`; full ARM64/x64 builds and
   native ARM64 Wine entry/codec/software Vulkan passed in `40989834370`. Codec also passed
   `40985737329`. Neither starts the full game.
2. Actual-EXE entry CI `40989834370` passed all five jobs at client
   `f75c2c71d9bb76a6707bfb68b2bf615db544e5bf`, pinned to integration harness `9ee80cd`. Windows ARM64/x64 and native Linux ARM64 receipts, namespace completion and
   process exit pass. Engine framebuffer/readback also passed run `40992315512`; continue Android bridge integration. Entry check
   deliberately does not call CommonMain or consume game assets.
3. Server run `40987376145` passed the third Eluna fix and failed module stat APIs
   at 1,214/2,258 units. Inspect the new mod-attunement-plus semantic patch. Continue
   real compile/link fixes as digest-checked patches in this repository. The next
   workflow also binds enabled modules to actual binaries and emits a verified
   GNU SQL/config/notice package. Source-profile package alone is unqualified.
4. Android PRoot CI `40986376389` passed Bionic build/APK byte verification and
   Linux x64/ARM64 descendant ownership. Actual Android PRoot execution remains open.
   The Java runtime installer has passed the full pinned archive on Linux with
   64 MiB heap, including forced hardlink copies. Android13 x86_64 installer/update
   run `40995925492` passes all18 contracts and version-2 preservation. Android
   native owner run `40994809786` passes six real shell-process groups. PRoot/glibc
   run `40998008458` passes actual x64 private-ELF/dlopen/TLS/thread/fork/loopback
   and relaunch persistence. Continue tracer-death and ARM64 integration. See
   `runtime/ANDROID-INSTALLATION.md` and `runtime/proot/README.md`.
5. Dependency image/MySQL/source-capture CI `40989666380` and normalized rootfs
   package/readback run `40993458111` passed. Integrate the verified optional APK
   provider and setup action, then establish actual server library closure.
   Do not combine its glibc 2.39 binaries with Debian 12 Wine's glibc 2.36.
   Keep all mutable databases outside replaceable runtime generations.
6. Base SQL load/restart CI `40991449039` passed all 468 files; qualify the compiled dbimport and the separate playerbots
   loader, then versioned upgrades with validated backup/restore. Real empty-DB
   bootstrap and loopback realm repair pass; `40987376123` runs all eight realm
   tests on MySQL 8.0.44. Owned-account fresh create/recovery/restart passes native
   ARM64 MySQL run `40998008509`; actual pinned SRP C++ sources also pass locally
   on x64. Implement real auth challenge/proof/realm-list qualification when
   authserver is available. Repair advertised realm only after all module updates.
7. Native process/Surface/audio/input bridge implementations and internal controller/IME
   view are now present; guest ARM64 build `40995565147` and Android-owner CI pass. Integrate
   their qualified session lifecycle and
   graceful server-save shutdown. Inspect read-only reference launcher code where
   useful. Keep startup gated until component readiness is actually established.
8. Import authentic complete build 12340/custom data; generate shaders with the
   corrected provider precedence, extract matched server assets, validate local
   login/world/save/relog/bots/offline before any main Thor test.

## Invariants

- App identity: `io.github.russianranger.esteria`, minSdk 26/target 35,
  JDK 17/Gradle 8.9/AGP 8.7.3. Keep one persistent private signing key before the
  first user installation. Debug CI is not an update baseline.
- Imported immutable generations, replaceable runtimes and mutable data/config/
  WTF/cache/logs are separate. Direct SAF or ZIP imports stream with bounded
  metadata; activation is atomic. Old generations still need a retention policy.
- Core supervisor tracks dependencies and cleanup failures. Runtime-specific
  process groups and world-save shutdown are not yet supplied by generic tests.
  TCP listening alone is not authenticated/game readiness.
- Keep 25 quests/254 container slots/32 client class capacity. Server class count
  12 does not imply 32 playable classes. No 1,000-quest/254-class wire format.
- `Wow.exe` alone was verified as 3.3.5.12340; it does not establish complete MPQ
  compatibility. Do not execute the unchanged stock client as port completion.
- Runtime/SQL/package manifests must record exact inputs and genuine qualification
  scope. Missing custom content must not be fabricated or silently ignored.

## Reproduction and access

Clean builds use [BUILDING.md](BUILDING.md) and exact locks, not session paths.
Public Git/API access works; this session's Git CLI had no push credential.
The connected GitHub Git-object API can publish commits and fast-forward refs
with an expected old SHA. Check for concurrent changes, never force-push.

The working session has sibling `client-src`, `server-src`, `reference-fta`,
downloaded toolchains and staged runtime. They are caches, not required source
inputs. Proprietary user files, secrets and generated binaries remain outside Git.
