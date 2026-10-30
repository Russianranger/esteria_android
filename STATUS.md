# Status

Updated 2026-10-30 UTC. This is an implementation checkpoint, **not a device-test candidate**.

## Sources and ownership

`sources.lock.json` is authoritative for application inputs. It pins client
`a3683cc3644d965bf0ed8d91946cd5d6b3f928e1`, server
`f35f04d01689f034778e3474b3c820092f51e461`, and Eluna
`58d7652138887783228b9727bd1fa4e08f00342b`. Digest-checked Eluna forward-declaration and map-manager include
patches are maintained here. Starting tips were client `800cdd2`, integration `6309c8f`,
and the same server revision. Work is on the two requested development branches;
no default merge, history rewrite or server push has occurred.

## Implemented and verified

| Area | Actual evidence | Limit |
| --- | --- | --- |
| Reconstructed client | Complete Windows ARM64 and x64 builds pass at `a3683cc`; newer `b335a3111cd64e69d5ceaebc73fb4daa57eed560` also passes and exercises the packaged Xvid DLL on both native Windows architectures. [CI 40983191169](https://github.com/Russianranger/wowdecomp_esteria/actions/runs/40983191169). Binary manifests verify PE architecture, hashes, revision, imports and descriptor settings. | Compilation and codec execution do not establish Wine or gameplay compatibility. |
| Client platform code | Real ARM64 CPU/math/crash implementations, portable LZNT1 catalog decoding, source-built Xvid codec and BGRA/VFLIP adapter. Six platform CTests, 17 runtime-manifest tests and 13 shader/archive tests pass in the relevant CI matrix. | The full client still uses Win32. This is a Windows ARM64 port, not native Android. |
| Protocol | All 215 player descriptors match selected server offsets/sizes. Containers are 254 slots/574 DWORDs; player layout is 1,326 DWORDs with 42 mask DWORDs; quests remain 25. Client class capacity is 32; server `MAX_CLASSES=12`. | Appearance transport, inventory behavior and custom races still need matched runtime tests. |
| Database bootstrap | Fresh MySQL initialization, secure provisioning, datadir promotion/recovery, authenticated readiness, locks, restart and persistence pass real-engine CI on MySQL 8.0.46 and pinned container 8.0.44. [CI 40983978344](https://github.com/Russianranger/esteria_android/actions/runs/40983978344). | Creates four empty databases; game schemas, upgrades and Android MySQL execution are not qualified. |
| Server configuration | Atomic generations, persistent private credentials, loopback binds, separate auth/world temporary directories, 128 MiB MySQL buffer, zero random-bot population and four controlled account-bot ceiling. | These are starting limits, not a measured device bot capacity. |
| Android application | Stable `io.github.russianranger.esteria` identity; direct SAF folder and ZIP imports, foreground progress/cancel, touch and launcher controller navigation, support ZIP export. Clean compile/lint and core behavior checks pass. Source pins are embedded in APK and support metadata. | Runtime startup is explicitly gated. Launcher controls are not game controls. No signed user update baseline exists. |
| Import/recovery | Immutable generations, pointer activation last, resumable journal, overlays, bounded metadata/copy, PE version/MPQ checks. 22 Java test groups pass with 32 MiB heap, including a 64 MiB streaming input. | Synthetic fixtures establish importer behavior, not complete real content compatibility. |
| Supervision/diagnostics | Seven process-supervisor tests pass. Startup dependencies/readiness, reverse stop and cleanup failures are observable. Bounded/redacted support logs include launcher memory/thermal/storage observations. | Process groups, graceful world saves and Android runtime adapter remain work. Launcher metrics are not game performance measurements. |
| Android process bridge | Two clean Bionic ARM64 PRoot/loader builds reproduce pinned hashes; the APK preserves exact bytes, passes assemble/lint, and declares native library extraction. Source/NDK/patch locks and corresponding sources are supplied. Eight focused checks pass. | No Android guest execution yet. Local Linux ownership execution is blocked by host ptrace policy; dedicated native Linux x64/ARM64 CI exercises the mandatory tracer-death patch. |
| Wine candidate | Exact archive/manifest/source pins; 613 MB archive streamed, safely staged and read back. 14,092 entries / 2,637,799,241 file bytes, 15 pinned binaries and 999 AA64 Windows modules audited. Runtime preparation has 12 tests. | Staged Debian 12 Wine is not an Android installation. Linux ARM64 execution qualification is separate. |

The supplied 7,702,016-byte `Wow.exe` passes structural PE VERSIONINFO inspection
for **3.3.5.12340**, SHA-256
`c4ea8503112878fa47d06580de9d936b184f9bb6b452f6931dfe793fe2f0a47e`.
It is kept outside Git. The complete client data has not been imported or qualified.

## Active work and remaining gates

- Native Linux ARM64 server [CI 40983190300](https://github.com/Russianranger/esteria_android/actions/runs/40983190300) progressed past the `AreaTrigger` fix, then failed because ElunaLoader omitted the AzerothCore `MapMgr.h` include. A second digest-checked patch supplies that real declaration; source-preparation tests and patch application pass. The next build can reuse the saved bounded compiler cache. Full server linking is not yet proven.
- Execute the actual packaged ARM64 movie DLL under pinned Wine on a native ARM64 Linux host, then qualify asset-free Vulkan presentation. A harness or a staged runtime alone is not a pass.
- Execute and integrate the built Android Bionic PRoot launcher/loader; install private runtime generations and qualify Android execution policy, display, audio, input, keyboard, lifecycle and process ownership.
- Package a matching server rootfs and MySQL. The Wine candidate has Debian 12/glibc 2.36; the server build uses Ubuntu 24.04/glibc 2.39, so those binaries cannot simply be combined.
- Prepare source-backed game SQL/module/Lua contents and safe versioned schema initialization/upgrades. Preserve existing accounts, characters and bots.
- Obtain/import full authentic build 12340 data and the matched custom content; prepare server extraction data and Vulkan shaders. Retail/Forever features stay disabled until complete offline inputs are prepared.
- Validate matched local login, character creation, world entry, combat/loot/quests, save/relog, small bots, audio, controller controls and network-disabled gameplay before one consolidated Thor test.

Historical server Z MPQs have inconsistent extents confirmed against raw Git blobs;
they are not accepted as a complete content pack. Appearance packers require absent
developer inputs. Exact scope is in [ASSET-REQUIREMENTS.md](ASSET-REQUIREMENTS.md).
These gaps do not prevent the active platform, packaging, database and tooling work.
