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

| Milestone | Current state | Next evidence |
| --- | --- | --- |
| 1. Reproducible references | Exact pins, full Windows ARM64/x64 client and linked ARM64 server/tools complete; protocol layouts match. | Isolated exported-source server rebuild/source seal. |
| 2. Client platform | Native ARM64 Wine entry/codec/software Vulkan/PCM and Android x64 entry/offline/loopback pass. | New source-owned production ARM64 Wine build, Android presentation and full initialization. |
| 3. Local services | Native compiled SQL/auth/SRP/ledger/restart passes for retained six-patch reference; Android x64 persistent MySQL service passes. | Phone updater/account/realm composition, fresh staging/recovery and production ARM64 execution. |
| 4. Matched gameplay | Client controlled-peer authentication passes; real compiled-server pairing remains blocked before SQL. | Matched login, character/world/gameplay and actual persistence/bots. |
| 5. Android application | Verified runtime/source import, UI review, controls/bridges, source-gated programs installer and content/schema adapters build. | Complete owned session, readiness, lifecycle and graceful saves. |
| 6. Thor candidate | Not ready; stable signing identity provisioned. | One coherent offline playable, update-compatible APK with available data and consolidated test. |

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


Latest integration priorities: follow actual production ARM64 Wine and isolated
server source builds; pass matched compiled authentication; compose portable
updater/config/account/realm setup on the owned MySQL service; finish fresh-slot
promotion/recovery and server data extraction; then complete client presentation
and matched world/gameplay gates. Exact current evidence is in STATUS.md.
