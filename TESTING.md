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
emulator. It reuses the same 18 installer contracts in app-private storage, stages
a runtime and separate persistent-state marker, installs version 2 with `adb
install -r`, and verifies both survive with zero runtime recopy. The harness
refuses a physical device or preexisting app and requires an explicit completed
JUnit result for each phase. It records APK hashes and emulator properties.

Local instrumentation compile and Android lint pass. First emulator run
`40990723608` failed because Android rejects `Files.getFileStore`; runtime download,
runtime extraction, game import, ZIP staging and storage diagnostics now use
`File` storage queries. Free-space reserves remain enforced. The second emulator run `40991448984` then exposed app-private hardlink denial.
The explicit verified-copy fallback adds an 18th contract. Run
`40995925492` at `e22b8d30a053a4afbcd6d78ca28e80f8dc0c697a` passes all contracts,
seed, update and retained-pointer/copied-hardlink/sentinel assertions. Evidence
artifact SHA256 is `03eadc7a72f54f9a861ee5d11b0eb3f17d780cbc7508c7970ff7042de4a167d1`.
This qualifies Android filesystem/update behavior, not ARM64 PRoot/Wine,
audio/display, gameplay, or the user's persistent signing key.
Both test versions use one isolated CI debug key.

## Native presentation, input and process gates

`tools/check_process_owner.py` builds and executes the native C++ owner and real
JVM/JNI adapter fixtures. The separate Android owner workflow requires x86_64 JNI
on an Android13 emulator and executes `/system/bin/sh`; it does not skip a missing
bridge or claim ARM64 guest execution. Host owner, JNI, NDK ARM64 build, native
APK validation and Android compile/lint pass. Actual emulator execution passes
all six owner groups in run `40994809786`; see `runtime/ANDROID-OWNER-QUALIFICATION.md`.

Six bounded JVM PCM/input protocol groups and the production native Surface decoder
with host socketpairs/test-only ANativeWindow stubs pass. Guest helper ARM64 builds
use pinned Debian12 inputs and source companions and pass native ARM64 CI
`40995565147`. Actual Android Surface/AudioTrack
playback and Wine guest input/audio remain separate gates. `runtime/CONTROLS.md`
describes the initial internal controller/IME router and remaining device checks.

The actual engine frame readback passed in Wine run `40992315512`: receipt SHA256
`69bfe354c777abf78e54ed033849235928edf742efdfce3371bca4c1e01379c4`.
This includes exact BGRA/partial-clear pixels and embedded engine presentation,
using llvmpipe LLVM15.0.6 with validation layers unavailable. It is not world rendering.

Actual Android PRoot/glibc run `40998008458` at integration `69b6b9e` passes the
two-launch native x64 fixture at API33/target35. It verifies private ELF loading,
glibc2.36 dlopen/TLS/pthreads, fork/exec, loopback and persisted bytes, with empty
guest stderr. Artifact SHA256 is
`9f08e7cc1461f04467730d7b25e1513b1284d91a9041c3bae187b7a1e176f2a9`.
See `runtime/ANDROID-PROOT-QUALIFICATION.md`; production ARM64, Wine and
tracer/app-death behavior are explicitly outside this result.

The real ARM64 owned-account qualification passes run `40998008509`, receipt
SHA256 `6c67ff662a12c1165bdad9b6b3330feeb5452af0f99c9365776d52e25c9bc0fa`.
It uses a separate fresh exact-MySQL8.0.46 fixture, not a replay over saved game
state. `runtime/LOCAL-ACCOUNT.md` records source-matched SRP and recovery scope.

Android Surface/AudioTrack run `40999380046` passes all ten required assertions,
including real RGBA readback, recreation,4,992 accepted/played frames and shutdown
with an idle connected audio peer. Artifact SHA256 is
`590f6c7373728be0e13e0907d8a3d0d037cf5ab469e4050c7a99c5e92e2a75e7`.
Native ARM64 Wine FMOD run `40998295147` also passes both actual backend/signal
checks; receipt SHA256 is
`663bdfd114d8440098556f5e475a4024224b28b8c5700a903d58308762131ffd`.
These remain separate host/emulator component results, not an end-to-end game pass.


The latest host checkpoints add six Android database-adapter preservation tests,
32MiB writable UI generation/selection tests, twelve real native JNI groups with
bounded stdin, and eleven backup guard tests including the actual kernel output
size limit. Full MySQL dump/restore, expanded Android process tests and corrected
tracer-death control still require their CI results. See the scoped qualification
documents; none of these host checks establishes login, world saving or Thor use.
