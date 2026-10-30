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
   is `08e6d453733cff08f47eeb76dec5211749594753`; full ARM64/x64 builds and
   native ARM64 Wine software Vulkan passed in `40986534025`. Codec also passed
   `40985737329`. Neither starts the full game.
2. Publish/run the pending actual-EXE entry check from the client branch using
   the newly pinned integration Wine harness. Verify Windows ARM64/x64 and native
   Linux ARM64 receipts, namespace completion and actual process exit. Entry check
   deliberately does not call CommonMain or consume game assets.
3. Inspect server run `40987376145` after the third Eluna include patch. Continue
   real compile/link fixes as digest-checked patches in this repository. The next
   workflow also binds enabled modules to actual binaries and emits a verified
   GNU SQL/config/notice package. Source-profile package alone is unqualified.
4. Android PRoot CI `40986376389` passed Bionic build/APK byte verification and
   Linux x64/ARM64 descendant ownership. Actual Android execution remains open.
   The Java runtime installer has passed the full pinned archive on Linux with
   64 MiB heap. Continue process-owner adapter and Android filesystem/execution
   qualification; see `runtime/ANDROID-INSTALLATION.md` and `runtime/proot/README.md`.
5. Inspect the new CI build of the reviewed, separately pinned Ubuntu 24.04 server/MySQL rootfs.
   Do not combine its glibc 2.39 binaries with Debian 12 Wine's glibc 2.36.
   Keep all mutable databases outside replaceable runtime generations.
6. Qualify actual fresh game schemas with dbimport and the separate playerbots
   loader, then versioned upgrades with validated backup/restore. Real empty-DB
   bootstrap and loopback realm repair pass; `40987376123` runs all eight realm
   tests on MySQL 8.0.44. Repair advertised realm only after all module updates.
7. Integrate actual display/audio/input, controller and keyboard, lifecycle and
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
