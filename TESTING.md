# Validation gates

## Host tooling
```
python3 -m unittest discover -s tests -v
python3 tools/verify_protocol.py --client ../client-src --server ../server-src
```
The actual-source protocol verifier generates the selected 25/254/32 descriptors and compares every player field to pinned server offsets and sizes. It also checks mask counts, container slots and server size-comment consistency. This verifies layout, not login, appearance transport or world behavior.

Java core tests use synthetic files and child processes, with no game data or
database required. Run `./gradlew :core:check :app:assembleDebug :app:lintDebug`.
The importer runs with a 32 MiB heap and a larger streaming input. Tests cover
interruption/reuse, immutable overlays, malformed archive/provider metadata,
bounded inventories, cancellation and prior-generation preservation. SAF Android
provider behavior remains a separate emulator/device check.

Runtime installer checks run with `:core:runtimeInstallerTest` (64 MiB heap).
Seventeen groups cover traversal, malformed GNU metadata, cancellation/resume,
closed staging inventories, required-file tampering, download caching and activation.
The actual pinned archive passed on Linux with 64 MiB heap: 14,092 entries, all
11,844 regular source files reused on retry, zero copied payload on retry. This is
not Android filesystem or execution evidence.

The client CI matrix separately builds full Windows x64 and ARM64 binaries,
validates PE provenance, and invokes the actual movie DLL through a synthetic
compressed-frame driver. Linux x64 and native ARM64 component tests cover portable
algorithms. None of these tests start the full game.

## Real database evidence

Database run [40983978344](https://github.com/Russianranger/esteria_android/actions/runs/40983978344)
passed both real-engine fixtures. The dedicated MySQL 8.0.44 service verifies
authentication/provisioning/locks/ownership/preservation. Host MySQL 8.0.46 verifies
fresh initialization, secure setup, datadir promotion/recovery, restart and SQL
persistence. The logs record exact engine versions. The bootstrap only creates
empty application databases. Game-schema load, migrations, character saves and
Android MySQL remain unqualified. Ordinary discovery reports these fixtures as
skipped unless their explicit environment and disposable engine are provided.

Realm repair run [40987376123](https://github.com/Russianranger/esteria_android/actions/runs/40987376123)
passes all eight dedicated MySQL 8.0.44 tests, including owned-instance checks and
preservation of unrelated rows/settings. Only realm network/build provisioning is qualified.

## Wine and Android evidence boundaries

The candidate Wine archive is measured and staged with checked file hashes and
architecture. Its actual client execution requires the separate native Linux ARM64
fixture in [runtime/WINE-QUALIFICATION.md](runtime/WINE-QUALIFICATION.md). Keep
its resulting qualification JSON and logs; authored tests or absent physical DLL
files for API-set names do not establish loader success or failure.

Native Linux ARM64 Wine codec run `40985737329` and software Vulkan run
`40986534025` pass. The latter presents/resizes 16 frames and exercises 30,000
texture lifetime operations using the pinned Lavapipe stack. Its receipt SHA-256 is
`26e27a5437dd2785ed6b8db05b7281b7a45306696c1f58360709052f515cefc0`.
Validation layers were unavailable; this is not hardware Vulkan or world rendering.
The actual-client entry fixture passes on Windows x64/ARM64 and native Linux
ARM64 Wine in run `40989834370`, with seven receipt checks and clean namespace exit.
Qualification SHA-256: `a7686069cd8e62eb8cb2075380e5cbb7390b2e42718c318413261cffc54141a6`.
It returns before CommonMain/assets; Wine DbgHelp unwinds only one frame.

Android APK compilation/lint and launcher host tests are passing checks. No Android
emulator or physical Thor gameplay result has been recorded. Display/audio/input,
PRoot execution, full local client/server startup and offline play need actual
runtime validation. Keep launcher memory/thermal diagnostics labeled as launcher
observations until the combined runtime can be measured.

## Not yet qualified
Game-schema initialization/migration, server data loading, full Wine client launch,
Vulkan world rendering, audio/input, character login/create/world entry,
combat/loot/quests, save/relog, bots, offline play, update-signature continuity and
Android low-memory recovery have not passed end-to-end validation.

Do not ask the owner to install a foundation APK. The main Thor test comes after one coherent candidate is expected to cover all requested gameplay. A narrow device-only diagnostic is allowed only when evidence shows useful independent work cannot continue.

## Future consolidated Thor test
Install/update with the stable signing identity; import verified data; start local play; create/select a character; move/look with controller; fight/loot/equip/quest; summon a small supported bot group; verify audio; exit/relaunch and confirm saves; repeat with networking disabled. Export one support bundle. Exact instructions and artifact identification must accompany the qualified candidate, not this preliminary gate description.

## Android filesystem and APK-update instrumentation

`.github/workflows/android-instrumentation.yml` builds an AndroidX instrumentation
APK and two application versions, then runs only on a fresh Android 13 x86_64
emulator. It reuses the same 17 installer contracts in app-private storage, stages
a runtime and separate persistent-state marker, installs version 2 with `adb
install -r`, and verifies both survive with zero runtime recopy. The harness
refuses a physical device or preexisting app and requires an explicit completed
JUnit result for each phase. It records APK hashes and emulator properties.

Local instrumentation compile and Android lint pass. First emulator run
`40990723608` failed because Android rejects `Files.getFileStore`; runtime download,
runtime extraction, game import, ZIP staging and storage diagnostics now use
`File` storage queries. Free-space reserves remain enforced. Rerun is pending. A successful run would qualify these Android filesystem/update behaviors, not
ARM64 PRoot/Wine, audio/display, gameplay, or the user's persistent signing key.
Both test versions use one isolated CI debug key.
