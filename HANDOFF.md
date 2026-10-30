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

1. Fetch both development tips and read their instructions. Confirm the current
   source/runtime locks and exact CI/artifact identities. Client full-build/DLL
   smoke pass is `b335a3111cd64e69d5ceaebc73fb4daa57eed560`, run `40983191169`.
   Application source lock currently uses full-build-proven `a3683cc`.
2. Complete native ARM64 Wine codec execution and asset-free Vulkan fixture.
   Use the pinned preparer and `runtime/WINE-QUALIFICATION.md`; keep external
   networking isolated and distinguish native Linux ARM64 from Android.
3. Inspect the latest server run after `40983190300`, which exposed the missing
   `MapMgr.h` include now fixed by patch 0002. Fix any further compile/link error
   via ordered digest-checked patches here. Package the installed binaries plus SQL,
   modules/Lua, extractors, configs and notices; install target alone is incomplete.
4. Inspect the new Android PRoot CI and Linux ownership matrix. Two local clean
   Bionic builds and APK payload checks already pass. Continue actual Android
   execution, runtime installation and process-owner integration; see
   `runtime/proot/README.md`. Preserve nativeLibraryDir packaging and source notices.
5. Pin a matching server rootfs/MySQL package. Ubuntu 24.04 server binaries cannot
   be assumed to run in the Debian 12 Wine rootfs. Keep mutable databases outside
   replaceable runtime trees. MySQL 8 is required; MariaDB is not qualified.
6. Extend the tested empty-database bootstrap with source-backed game schema and
   module initialization/version checks, then guarded upgrades and server readiness.
   Never reseed live character/account/bot data. Real bootstrap CI `40983978344`
   passed on 8.0.46 and 8.0.44; this does not prove game schemas or Android MySQL.
7. Integrate display/audio/input and real client/server launch. Continue host and
   available emulator qualification before requesting hardware work.
8. Import authentic complete build 12340/custom data; generate shaders with the
   corrected provider precedence, extract matched server assets, validate local
   login/world/save/relog/bots/offline. Missing content scope is in the asset inventory.

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
