# Status

Updated 2026-10-30 UTC. This is an implementation checkpoint, **not a device-test candidate**.

## Sources and ownership

`sources.lock.json` is authoritative for application inputs. It pins client
`0f931bbade36a4b197725d691b8eff7caea7b3be`, server
`f35f04d01689f034778e3474b3c820092f51e461`, and Eluna
`58d7652138887783228b9727bd1fa4e08f00342b`. Three digest-checked Eluna declaration/include patches plus a server-root
attunement stat-API compatibility patch, real grid-template includes, source-empty script-directory filtering, and module-config paths relative to the selected main config are maintained here (seven patches). Starting tips were client `800cdd2`, integration `6309c8f`,
and the same server revision. Work is on the two requested development branches;
no default merge, history rewrite or server push has occurred.

## Latest implementation checkpoint

Android13 x64 Wine run41046942035 now executes the reconstructed client entry,
offline component diagnostics and real loopback transport after the source-owned
private-PE mapping adaptation. All original source inputs were verified before
execution. This is an emulator component result, not ARM64, CommonMain, rendering,
audio or world gameplay. The separate production ARM64 Wine adaptation is underway.

Native ARM64 retained-server run41045808679 passes fresh compiled SQL, exact
original updater ledgers, reentry and restart. Appearance49/132-byte binary
storage also survives restart. Run41046942015 additionally verifies all4,063
phone-side source-content files without Git. Authentication then stopped before
the engine because the realm reader still expected the old four-file config
layout; the reviewed fix now accepts the exact complete50-module generation.
Client/auth qualification separately receives an owned MySQL initialization
TMP directory and bounded numeric-only diagnostics; actual results are pending.

The measured server runtime is21,996,594bytes with all126program/config/provenance/
notice files. Native executable loading and bounded Java installation/reuse pass.
The optional Android programs installer is integrated but remains source-gated:
its clean isolated ARM64 source rebuild must succeed before packaging is enabled.
This checkpoint publishes that reproducible build workflow. No user-test APK is ready.

The full reconstructed EXE's offline diagnostics pass Windows x64/ARM64 and
native Linux ARM64 Wine in run41003225299, client
`e2718f647a7f1efb9219106c7501f88a0bf06e4f`. New client tip
`97b347ee034551ea78dc905c3e209667534e6283` passes all five actual transport jobs
in41007244092, including Windows x64/ARM64 and native ARM64 Wine.
Strict shader source926a6f73253720283ead9d7621ffd6d7d9c040cd also passes all five
jobs41007556042 and25 actual host compiler tests. Development tip
3f9389ccfdb0431d281e281c49193c8064c70b62 passes real Grunt/SRP positive and
negative controlled-peer tests on Windows ARM64/x64 in41010223296. The compiled
server pairing is implemented separately and awaits its actual runtime gate.
Client0f931bbade36a4b197725d691b8eff7caea7b3be passes all five jobs41012726334,
including the actual ARM64 Wine Grunt positive/negative controlled-peer gate.
The preceding3e9 run41006100154 passed real x64 short/extended packet reads,
queued sends, stream I/O and both connect/disconnect pairs after repairing lost
network timer wakes; it then exposed the fixture's missing WDataStore Finalize().
The complete transport receipt and Wine transport gate now pass.
The application now selects the measured0f provider and seven-patch server source.
The exact new provider/source companion pass eight host groups. Its new seven-file
dependency release at packaging27446b5 is published and independently fetched
without credentials, with full source/PE/descriptor checks. The historical69
release remains unchanged. The current combined APK must pass its own new build;
dependency publication alone is not an application build result. Source-lock SHA256 is
`5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1`.

Server40994809596 compiled all2,257 objects and linked authserver/dbimport, then
failed final worldserver linking on three missing grid-template instantiations
and the README-only Custom directory's nonexistent loader. Minimal source-backed
patches5/6 supply real template definitions and omit only source-empty directories.
Corrected run41005048019 linked all application/tools executables and passed
loader/module/source-package checks. Its first runtime gate rejected a content
consumer provenance mismatch before MySQL or SQL started. The corrected consumer
now requires all five producer identity fields; a separate exact-binary runtime
job tests the retained six-patch payload without recompilation. No auth/world
success is claimed. Native ARM64 backup41013086447 now
passes complete 367,899,260-byte dump equality after fresh restore and restart,
including account journal and repeated setup preservation. Harness-only charset
normalization was corrected without changing server tables or comparison gates.
Native ARM64 persistent-service41013380186 passes three live SQL cycles,
UUID/credentials/four-schema persistence, duplicate-owner rejection and clean
command/EOF/signal shutdown. Android13 x64 run41016293760 now passes the actual Java application-service
wrapper: two live SQL cycles, duplicate-start refusal, typed readiness/clean-stop
receipts and unchanged UUID/credentials/markers. This uses the explicitly verified
x64 test seam; production ARM64, real schema upgrades and game saving remain open.

Writable UI selection/review is integrated into the app with explicit divergence
decisions and retained prior versions. Actual adapter32MiB tests, independent
review, combined all4-provider APK, instrumentation compilation, lint and final
provider byte checks pass. Android database preparation is implemented but is
not launched by normal setup until its platform qualification succeeds.

Native Linux x64/ARM64 stdin tests pass12 real JNI groups in41003838751. Android13
x64 passes9 real owner groups in41003838802. Corrected tracer-death run41003838793
observed3 control survivors versus0 protected survivors before alarms, plus3
saved files read by a fresh guest. These are component results, not world saves,
Android ARM64 guest execution or gameplay. Remote-owner run41006180061 now
passes: owner/tracer/three guests exited within4,115ms while all separately owned
controls survived; nine pidfds established exact identities. This is combined
Android OS/ownership behavior, not isolated parent-death-signal causality.

Dependency release41003838795 passed full original/source validation, upload to
an exactb06 UI draft and independent read-only post-publication verification of
all9 assets. The durable prerelease URL and per-file hashes are recorded in
`runtime/server/dependency-release.lock.json`; GitHub immutable=false is explicit.
Guest and client input releases also pass actual public verification in
41006572380/41006572426, including independent credential-free host downloads.
Exact source companions and original license notices are retained. No default
branch, credential scope or repository security setting was changed.

The prior six-patch combined ARM64 APK passed clean core checks, application/instrumentation
compilation, lint and all four final provider byte checks with six-patch source
lock SHA256 `dbbf8983cfa2b429f7dd0c3308a2795ffbecd29e8019adf35348447e1eab41b0`.
Hosted all-provider builds41009954235 and41010011668 also pass complete source
sealing and APK readback. A nondebug43cc release is signed with the persistent
RSA4096 certificate and passes v2/v3 plus all provider-byte checks. Its private
recovery backup is retained outside Git; no delivered baseline exists.
Android MySQL41010011663 now passes actual initialization, authenticated SQL,
repeat setup and restart with the same UUID, credentials and four-schema marker
data. The x64 PRoot rename adaptation separately passes41010011745. These are
Android13 x64 component results, not production ARM64/gameplay qualification.
Turnip ARM6441009954190 passes direct exact-ICD zero-device loading and the pinned
loader's corresponding result. Its real shader tools pass compilation/validation.
No Adreno execution, Android GPU compatibility or hardware rendering is claimed.
Transactional shader-generation staging passes eight host groups, with actual
subprocess bounds and explicitly synthetic storage fixtures. Real game MPQs,
shader generation, Adreno rendering and launcher activation are still absent.
The exact926a translator/8a compiler provider and Android transactional setup
adapter now compile and pass core/lint plus all five final APK provider checks.
The original sources and notices are retained. A separately verified seven-file
durable dependency release is being published; real imported-game generation
remains unqualified.

Android x64 Wine run41015479987 passed complete original-source sealing and APK
validation, then failed prefix initialization while making ntdll executable.
No reconstructed-client execution occurred. The five-case diagnostic in41017052972
now establishes errno13 for adding execute permission after modifying a private
file mapping; clean/direct file mappings and anonymous RW→RX pass. It executes no
mapped bytes. A source-owned Wine private-image mapping adaptation is in progress;
Android policy and target SDK stay unchanged. The owned display/input/audio coordinator now
builds with authenticated shared X11 endpoints, lifecycle mute and reverse cleanup.
It has not executed as a complete Android presentation session.

## Implemented and verified

| Area | Actual evidence | Limit |
| --- | --- | --- |
| Reconstructed client | Complete Windows ARM64 and x64 builds pass at `f75c2c71d9bb76a6707bfb68b2bf615db544e5bf`, including the actual packaged Xvid DLL on both native Windows architectures. [CI 40989834370](https://github.com/Russianranger/wowdecomp_esteria/actions/runs/40989834370). Binary manifests verify PE architecture, hashes, revision, imports and descriptor settings. | Actual Wine codec execution also passes at client `61ad13e`, below; full-game compatibility remains unqualified. |
| Client platform code | Real ARM64 CPU/math/crash implementations, portable LZNT1 catalog decoding, source-built Xvid codec and BGRA/VFLIP adapter. Six platform CTests, 17 runtime-manifest tests and 13 shader/archive tests pass in the relevant CI matrix. | The full client still uses Win32. This is a Windows ARM64 port, not native Android. |
| Protocol | All 215 player descriptors match selected server offsets/sizes. Containers are 254 slots/574 DWORDs; player layout is 1,326 DWORDs with 42 mask DWORDs; quests remain 25. Client class capacity is 32; server `MAX_CLASSES=12`. | Appearance transport, inventory behavior and custom races still need matched runtime tests. |
| Database bootstrap | Fresh MySQL initialization, secure provisioning, datadir promotion/recovery, authenticated readiness, locks, restart and persistence pass real-engine CI on MySQL 8.0.46 and pinned container 8.0.44. [CI 40983978344](https://github.com/Russianranger/esteria_android/actions/runs/40983978344). | Creates four empty databases; game schemas, upgrades and Android MySQL execution are not qualified. |
| Server configuration | Atomic generations, persistent private credentials, loopback binds, separate auth/world temporary directories, 128 MiB MySQL buffer, zero random-bot population and four controlled account-bot ceiling. | These are starting limits, not a measured device bot capacity. |
| Android application | Stable `io.github.russianranger.esteria` identity; direct SAF folder and ZIP imports, foreground progress/cancel, touch and launcher controller navigation, support ZIP export. Clean compile/lint and core behavior checks pass. Source pins are embedded in APK and support metadata. | Runtime startup is explicitly gated. Launcher controls are not game controls. No signed user update baseline exists. |
| Import/recovery | Immutable generations, pointer activation last, resumable journal, overlays, bounded metadata/copy, PE version/MPQ checks. 22 Java test groups pass with 32 MiB heap, including a 64 MiB streaming input. | Synthetic fixtures establish importer behavior, not complete real content compatibility. |
| Supervision/diagnostics | Seven process-supervisor tests pass. Startup dependencies/readiness, reverse stop and cleanup failures are observable. Bounded/redacted support logs include launcher memory/thermal/storage observations. | Native owned groups and bounded console input are implemented; actual world saves and complete application-session readiness remain unqualified. Launcher metrics are not game performance measurements. |
| Android process bridge | Two clean Bionic ARM64 PRoot/loader builds reproduce pinned hashes; the APK preserves exact bytes, passes assemble/lint, and declares native library extraction. Source/NDK/patch locks and corresponding sources are supplied. Eight focused checks pass. | Production ARM64 execution remains open; minimal Android x64 glibc execution passes as recorded below. [CI 40986376389](https://github.com/Russianranger/esteria_android/actions/runs/40986376389) passes Android build/APK verification and native Linux x64/ARM64 ownership: all three detached test descendants die with the patched tracer; all three survive the unpatched control. |
| Linux ARM64 Wine execution | The actual packaged AA64 movie DLL passes under the pinned Wine runtime with a fresh prefix, isolated network, bounded logs and clean namespace teardown. [CI 40985737329](https://github.com/Russianranger/wowdecomp_esteria/actions/runs/40985737329), client `61ad13eb90c9d3c5db2c45d06f6c9da63a04cc81`. | The full client executable was not started. Prefix setup emits nonfatal COM/USB/Bluetooth diagnostics. Audio and Android remain separate gates. |
| Linux ARM64 Wine graphics | Actual engine Win32 surface/device/swapchain presents 16 frames and resizes; texture fixture holds 20,000 textures and performs 30,000 create/destroy operations. [CI 40986534025](https://github.com/Russianranger/wowdecomp_esteria/actions/runs/40986534025), client `08e6d45`, pinned Lavapipe / observed llvmpipe LLVM 15.0.6. | Software Vulkan only; validation layer unavailable. No Adreno, Android, full game or audio qualification. |
| Android runtime installation | Android13 x86_64 emulator passes all 18 installer groups and version-2 APK update preserving the runtime, copied hardlinks and persistent-state marker, [CI 40995925492](https://github.com/Russianranger/esteria_android/actions/runs/40995925492). The full 613 MB Wine archive also passes Linux extraction/readback with a 64 MiB heap, including all 45 denied-hardlink copies; cached retry copies zero. | Emulator fixtures establish Android filesystem/update behavior; the full archive ran on Linux. No ARM64 guest execution or user signing baseline. See `runtime/ANDROID-INSTALLATION.md`. |
| Loopback realm provisioning | Eight focused real MySQL 8.0.44 tests pass, [CI 40987376123](https://github.com/Russianranger/esteria_android/actions/runs/40987376123). Authenticated, owned database repair updates only realm 1 network/build fields after module updates and preserves other rows/settings. | Does not establish complete schema loading, login or world readiness. |
| Server source content | GNU tar package readback verifies 4,060 entries / 654,046,522 payload bytes; 24 module/package tests pass. Binary module selection is checked against compile options and hash-verified executables when available. | Actual source-profile package is not yet bound to a successful server build. Initial Lua is explicitly disabled pending matching dependencies; no schema execution or gameplay pass. |
| Actual reconstructed EXE entry | Native Windows ARM64/x64 and native Linux ARM64 Wine pass CRT, FP control, Storm allocation/reallocation/free, C++ unwind/destructor and fiber return in [CI 40989834370](https://github.com/Russianranger/wowdecomp_esteria/actions/runs/40989834370). Receipt confirms all seven checks and clean namespace exit. | Diagnostic opt-in returns before CommonMain/assets. Wine DbgHelp captured only one stack frame; complete Wine stack unwinding remains unqualified. |
| Native Android bridge implementation | Android13 x86_64 executes all six native process-owner groups, [CI 40994809786](https://github.com/Russianranger/esteria_android/actions/runs/40994809786). Pinned Debian12 ARM64 frame/input/ALSA helpers build with ELF/dependency/source checks, [CI 40995565147](https://github.com/Russianranger/esteria_android/actions/runs/40995565147). ARM64 JNI/APK, Linux owner/JNI, PCM/input and decoder fixtures also pass. | Owner emulator uses Android shell processes. Android x64 PRoot and synthetic frame/audio pass separately below. No Android ARM64 Wine, active gameplay session or Thor controls yet. |
| Wine candidate | Exact archive/manifest/source pins; 613 MB archive streamed, safely staged and read back. 14,092 entries / 2,637,799,241 file bytes, 15 pinned binaries and 999 AA64 Windows modules audited. Runtime preparation has 12 tests. | Staged Debian 12 Wine is not an Android installation. Linux ARM64 execution qualification is separate. |
| Bundled server dependencies | Optional provider validates the measured 112,374,096-byte Ubuntu/MySQL archive, exact metadata/source identities, complete archive graph and ARM64 headers. APK assembly/lint and byte-for-byte uncompressed asset verification pass. Setup/cancel/resume and support metadata are wired separately from Wine. | Provides dependency rootfs only; Android MySQL execution, compiled server payload and game database are not qualified. |
| Android PRoot/glibc execution | Android13 x86_64 at target35 passes actual private-ELF loading, glibc2.36 dynamic loading/TLS/threads, fork/exec, loopback and two-launch persistence in [CI 40998008458](https://github.com/Russianranger/esteria_android/actions/runs/40998008458). Direct app-private Bionic exec is rejected as expected; the APK-installed tracer/loader succeeds. | Minimal x64 fixture, not production ARM64, Wine, complete rootfs, tracer-death recovery or gameplay. |
| Owned local account | Exact server SRP6/BigNumber/normalization C++ sources pass locally on x64. Fresh native ARM64 MySQL account create/repeat, interrupted-commit recovery, collision/schema rejection and restart pass [CI 40998008509](https://github.com/Russianranger/esteria_android/actions/runs/40998008509). Credentials remain private and existing account rows are not adopted/reset. | Real authserver protocol, module updates, existing-save upgrades and Android server execution remain unqualified. |
| Bundled guest helpers | Exact 469,031-byte package contains 30 pinned source/notice/binary files. Full Java install and cached reuse pass under32MiB heap. Combined ARM64 APK includes verified PRoot, server dependency and guest-helper providers; core checks, instrumentation compile, lint and all three final APK verifiers pass. | Separate immutable helper generation is installed by client setup; actual Android guest presentation/input/audio and gameplay remain gated. |
| Reconstructed client package | Exact 7,290,039-byte package contains the matched EXE/Xvid DLL, descriptors, provenance and original notices. All30 files/21,445,584 bytes and both AA64 PEs install/read back with32MiB heap; cached reuse opens no archive. Combined APK with all four providers builds/lints and each provider verifies its final APK bytes. | Windows ARM64 binaries, separately installed from user assets. No active Android client session; the writable launch view is prepared separately from immutable binaries and imported data. |
| Captured reconstructed audio | WinMM and DirectSound both pass real native ARM64 Wine PCM transport in client [CI 40998295147](https://github.com/Russianranger/wowdecomp_esteria/actions/runs/40998295147), revision `243b6c4`. Correct stereo signals, 122,414/123,344 frames, exact END callbacks, clean EOF and Wine teardown are required. | Synthetic FMOD sound, not game music/audio on Android or Thor. |
| Android Surface and AudioTrack | Actual native pixels/recreation and AudioTrack clock/reset/private-socket cleanup pass Android13 x64 [CI 40999380046](https://github.com/Russianranger/esteria_android/actions/runs/40999380046). Audio accepted and played both4,992 frames. | Offscreen synthetic socket producers; no guest X11, Wine, Adreno, audible hardware or game presentation qualification. |
| ARM64 host XTest input | Real pinned X11 server/helper passes seven groups,16 observed input events and15 acknowledgements with normal cleanup in [CI 41000334310](https://github.com/Russianranger/esteria_android/actions/runs/41000334310). Production helper bytes match the packaged61bf build. | Host X11 behavior, not Android controller/game input. |
| Mutable client view | Exact PE copies/resume, persistent WTF/cache/logs/screenshots, loopback locale overlays, canonical view over case-insensitive imported names, guest-only links and preservation checks pass32MiB tests. Service prepares the view after verified client installation when imported data exists. | No client execution. Writable Interface preservation and typed selection are implemented; app review/activation is implemented and host-tested; generated shaders and actual content still required. |

The supplied 7,702,016-byte `Wow.exe` passes structural PE VERSIONINFO inspection
for **3.3.5.12340**, SHA-256
`c4ea8503112878fa47d06580de9d936b184f9bb6b452f6931dfe793fe2f0a47e`.
It is kept outside Git. The complete client data has not been imported or qualified.

## Active work and remaining gates

- Native Linux ARM64 server [CI 40983190300](https://github.com/Russianranger/esteria_android/actions/runs/40983190300) progressed past the `AreaTrigger` fix, then failed because ElunaLoader omitted the AzerothCore `MapMgr.h` include. A second digest-checked patch supplies that real declaration; source-preparation tests and patch application pass. The follow-up build progressed to `Hooks.h`, whose missing integer/size includes are fixed by patch 0003; standalone compilation against the actual patched header passes. Run `40987376145` progressed to 1,214/2,258 units and then exposed mod-attunement-plus calls to removed stat APIs. The reviewed fourth patch preserves legacy primary-stat display behavior and real armor/AP modifiers, with a targeted module-object check first in the next build; the saved cache contains 1.216 GB. Full server linking is not yet proven.
- Actual reconstructed EXE entry, codec and software Vulkan fixtures pass. Engine framebuffer BGRA pixels/partial clears and real presentation counters also pass [CI 40992315512](https://github.com/Russianranger/wowdecomp_esteria/actions/runs/40992315512), client `69ccfaa6`. Continue Android bridge execution, audio and full game initialization; no world rendering yet.
- Android13 installer/update, native owner, PRoot/glibc and Surface/AudioTrack qualification pass with x64 emulator fixtures; real native ARM64 XTest also passes. A new paired patched/unpatched tracer-death test and real graceful-save fixture are compiled/reviewed, awaiting actual emulator execution. Preserve distinct ARM64 guest, keyboard/controller and Thor gates.
- Dependency-only release preservation first run `41000334420` failed during artifact download before publication. Safe endpoint/status diagnostics and corrected Actions media type are queued; no durable release is yet claimed. Tags/assets are never overwritten, and full corresponding sources must validate before publication.
- Build the reviewed, pinned Ubuntu 24.04 ARM64 server dependency recipe in `runtime/server/`, including MySQL 8.0.46-0ubuntu0.24.04.4, offline initialization/persistence and corresponding-source capture. Four pin-contract tests pass; native ARM64 image build, offline MySQL initialization/restart/persistence and corresponding-source capture passed [CI 40989666380](https://github.com/Russianranger/esteria_android/actions/runs/40989666380). Actual archive packaging/full readback passed run `40993458111`: 112,374,096-byte archive, 6,263 entries / 385,051,708 payload bytes. Independent host staging/readback also passed. Actual server library closure and Android execution remain open. The Debian 12/glibc 2.36 Wine tree cannot host these Ubuntu/glibc 2.39 server binaries.
- Run the new fresh base-SQL qualification: 468 pinned files / 381,481,395 bytes are staged and read back; 12 guard tests pass. Real ARM64 import and restart passed [CI 40991449039](https://github.com/Russianranger/esteria_android/actions/runs/40991449039) on MySQL 8.0.46-0ubuntu0.24.04.4, with 22/108/309/29 tables and persistent markers. Compiled updater, module migrations and live-save upgrades remain open. Bind the source-backed SQL/module package to the actual server build, qualify fresh game schemas and playerbots loading, then guarded upgrades. Preserve existing accounts, characters and bots; resolve the explicit Lua dependencies.
- Obtain/import full authentic build 12340 data and the matched custom content; prepare server extraction data and Vulkan shaders. Retail/Forever features stay disabled until complete offline inputs are prepared.
- Validate matched local login, character creation, world entry, combat/loot/quests, save/relog, small bots, audio, controller controls and network-disabled gameplay before one consolidated Thor test.

Historical server Z MPQs have inconsistent extents confirmed against raw Git blobs;
they are not accepted as a complete content pack. Appearance packers require absent
developer inputs. Exact scope is in [ASSET-REQUIREMENTS.md](ASSET-REQUIREMENTS.md).
These gaps do not prevent the active platform, packaging, database and tooling work.


## Current resume checkpoint

The current0f/seven-patch combined build41019374657 passes all packaging/source
checks; actual Android Surface lifecycle41019374598 passes its six groups. Exact
receipts and deliberately false game/hardware fields are retained in runtime/evidence.
Seven-patch server41019374697 is linked and installed. Its fresh baseline and
Nemesis prerequisite import passed; the real updater then exposed the source's
race-table creator ordering. The narrow canonical prerequisite is implemented,
with native rerun pending. Authentication has not reached its completed gate.

The source-owned Wine private-image adaptation is published824ca6d and now
building in41040860418. Its original-versus-opt-in host fixture must pass before
runtime export/repin and the next Android test. The APK still uses the previous
production ARM64 Wine dependency; no adapted Android execution is claimed.

The preparatory server-program packager can derive a stripped runtime plus paired
debug archive from verified linked inputs. Complete source sealing, measured
server derivative, Android provider installation and service composition are next.
Durable native dependency images avoid re-resolving the same Ubuntu snapshot on
every runtime-only gate. The full local game remains the active objective.

Wine source41040860418 now passes actual default/opt-in PE loading, shared/private
section/protection/relocation tests and complete source export. The exact new x64
runtime/source pin is selected for the next mandatory Android qualifier; no
adapted Android execution or production ARM64 runtime swap is claimed.

Actual server derivative41043905821 is21.35MB compressed/62.89MB installed,
including three programs,53templates and4provenance files. Its native ARM64
loader checks pass. Debugs and source/notices remain outside the runtime; complete
isolated-source rebuild and Android provider are next. A separate fresh-only
source-derived schema implements the two49/132-byte appearance stores required
by exact C++ bind/read contracts, with no invented asset rows or updater ledgers.
Actual storage/restart/fullprepared-statement tests are running separately.
