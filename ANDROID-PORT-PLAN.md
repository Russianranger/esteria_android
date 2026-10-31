# Esteria Android implementation plan

## Objective and scope
AYN Thor Max (Snapdragon 8 Gen 2 / Adreno 740 / Android 13 / ARM64 / 16 GB), entirely local after setup. Reconstructed client, matching Esteria server and MySQL, persistent characters and a small controlled bot group. No streaming. The imported stock executable is version evidence, not the delivered reconstructed client.

## Starting points (2026-10-29 America/Chicago)
- Client `Esteria`: `800cdd272269570a9776d0c170e4828605fc1218`.
- Integration `main`: `6309c8fef382178e5c23cb44619fa801e0585f08` (GPL-3.0 license only).
- Server `main`: `f35f04d01689f034778e3474b3c820092f51e461`.
- Development only: client `android/arm64-port`, integration `android/client-server`. Defaults remain unchanged. Server is read-only; adaptation patches belong here.

## Selected first path
Build the reconstructed client as Windows ARM64, run it in a local ARM64 Wine runtime, and run the server/MySQL as Linux ARM64 in an app-managed PRoot environment. This is Windows ARM64 compatibility execution, not native Android. It keeps existing Win32 surfaces, fibers, input and multimedia working while replacing x86-specific implementation and library dependencies. A Windows x64 build remains the desktop reference and potential diagnostic comparison; it is not the final native-CPU goal.

Native Android is a later platform path: current root CMake deliberately rejects it, and removing that guard alone would not implement the Windows services, presentation, sound and input backends. Avoid doubling the platform rewrite before a reconstructed client reference build and protocol baseline exist. Wine/PRoot/display/audio payloads still need exact source pins, corresponding sources and device qualification; a proposed runtime is not a qualified one.

The complete reconstructed Windows ARM64 and x64 builds now pass, including the
source-built movie DLL's actual load/decode test. This supports the selected bring-up
path. Actual Linux ARM64 Wine codec and software Vulkan fixtures now pass; Android, hardware graphics, full game startup and game protocol behavior remain unqualified. The
pinned Debian 12 Wine candidate is staged and measured; the Ubuntu 24.04 server
needs a separate compatible dependency environment. No CPU translation should be
needed for the selected AA64 client/server code, but Wine/PRoot/display overhead,
combined memory and Thor thermals remain measurements to make, not assumed gains.

## Milestone state

The selected reconstructed client is now
`471ee42faadf4a97a1d0a86989cf1452621f2dc5`; all five jobs in41061576677
passed. Native Windows handoff-reader tests and the existing ARM64 Wine component
fixtures remain separate from normal asset-backed CommonMain/Glue login. The app
lock advances only this client; archived server build/SQL/source receipts retain
their original full-lock identity.

| Milestone | Current state | Next evidence |
| --- | --- | --- |
| 1. Reproducible references | Exact pins, full Windows ARM64/x64 client and linked ARM64 server/tools complete; protocol layouts match. | Passed41051669638/41078079045; preserve exact sources and paired debug. |
| 2. Client platform | Full Windows ARM64/x64 and actual ARM64 Wine entry/codec/software Vulkan/FMOD/transport pass. Complete Retail-ON builds pass atceb; latestc8 all-five checks pass. Android x64 Surface/AudioTrack/ownership components pass. | App still selects471. Normal asset-backed initialization, actual Android ARM64 graphics/audio and gameplay remain. |
| 3. Local services | Original seven-patch providers are public and source-preserved. Native ARM64 production typed Java/PRoot four-schema SQL/promotion/restart passes at84fa, including the shared lease changes; actual Android x64 MySQL service passes separately. | Original full x64 tools41119182502 and native SQL41139757153 pass; provider measurement41141559961 passes; Actual Android13 x64 four-schema41148736592 now passes with the fixed source; Android ARM64/auth/world remain. |
| 4. Matched gameplay | Current471/c0e/seven-patch SRP pairing passes41088546780; normal initialization/world remain untested. | Matched login, character/world/gameplay and actual persistence/bots. |
| 5. Android application | Import/runtime/data/shader/SQL/game ownership and controls implemented; complete public-input APK passes CI and local byte readback. Actual Android update preservation and six-case handoff/shared-lease process-death recovery pass. | Qualify complete asset-backed session, input, audio, lifecycle and actual character saves. Offscreen graphics setup check has no hardware result here. |
| 6. Thor candidate | Signed0.1.0-dev.1/build41149985842 published; persistent key/baseline1, complete release payload and Android SQL gates pass. | Run THOR-TEST-CANDIDATE.md with genuine Data; actual world/Thor/gameplay and custom-feature qualification remain. |

## Execution order
1. Pin sources and Eluna, create repeatable source preparation and field-layout tests. Build x64 + ARM64 client and Linux ARM64 server continuously.
2. Remove x86 assumptions with real portable kernels, CPU discovery, decompression and movie codec. Keep desktop behavior. Inspect every compile failure; do not silently disable audio/gameplay.
3. Prepare local MySQL 8, server schema/module SQL and DBC/map assets. Bootstrap only an empty database; backup and authenticate migration of existing saves. Bound bots and process memory.
4. Import base build 12340 and later Esteria packages as atomic, resumable generations. Generate shaders from effective archive order. Prepare enabled Retail/Forever data at setup; prevent CDN requirements during gameplay.
5. Integrate verified runtime packages, display/input/audio, foreground supervision, readiness and orderly shutdown in the Android app. Controllers must work in game, not merely the launcher.
6. Validate host and emulator login/world entry/save/relog, small bots and offline behavior. Only then produce one signed update-compatible Thor candidate and consolidated test.

## Fixed protocol configuration
`WOWDECOMP_EXTENDED_LIMITS=ON`, `WOWDECOMP_CONTAINER_SLOTS=254`, `WOWDECOMP_QUEST_LOG_SLOTS=25`, `WOWDECOMP_MAX_CLASSES=32`. The class setting is client capacity; the server currently has `MAX_CLASSES=12`. Do not enable 1,000 quests or 254-class wire format.

## Persistent boundaries
Application: `io.github.russianranger.esteria`. Immutable imported generations are separate from replaceable runtime generations and mutable databases/config/accounts/WTF/cache/logs. Never initialize over a live database. Release signing must use a persistent private keystore outside Git; ephemeral debug APKs are internal build checks, not update candidates.

## Evidence gates
A passed component test, compiled EXE, built APK or listening TCP port does not prove world playability. Keep compilation, host component tests, emulator tests and physical Thor tests separate in STATUS.md and TESTING.md. Missing content blocks only affected runtime qualification while independent work proceeds.


Current order: original x64 dbimport/helper41119182502 passed its full1850-object
closure. Its actual native four-schema SQL41139757153 now passes; provider measurement41141559961 now passes; actual Android four-schema run41143986520 now builds/installs but fails before
its old collector can preserve the private assertion. The measured fixture is
enabled. Rerun with bounded failure diagnostics, fix the observed cause, then
qualify real Android four-schema promotion/restart. The c441 diagnostic run now
isolates equal JSON Integer/Long byte counts. The exact comparator fix is
published at651; fresh651 provider measurement41148040884 now passes and its
exact selectors are activated. Actual Android SQL/promotion/restart41148736592
now passes. Full-profile release packaging and persistent signing precede the
main coherent content/hardware test. Historical817 MySQL bytes
must be admitted from their exact frozen source; current Java inherits no old
runtime proof. Keep production ARM64 admission and the five save-selection fields.

Runtime lease duplication now reserves canonical names before opening a file
descriptor; actual Linux and Android process-death tests cover the POSIX hazard.
Shaders/server data use the same effective locale. An explicit setup graphics
check uses the existing pinned C probe before costly extraction. These changes
do not provide missing MPQs/catalogs/DBC/maps or qualify normal world entry.
After source/platform gates, validate real imported-data shaders, matched normal
login, character/world play, audio, saves, one-to-four bots and offline lifecycle.
Do not substitute synthetic fixtures for those asset-backed gates.
