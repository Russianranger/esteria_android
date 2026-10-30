# Status

Updated 2026-10-30 UTC. Development continues; no Thor test candidate is ready.

## Exact inputs and architecture

Application `sources.lock.json` pins reconstructed client
`471ee42faadf4a97a1d0a86989cf1452621f2dc5`, server
`f35f04d01689f034778e3474b3c820092f51e461`, Eluna
`58d7652138887783228b9727bd1fa4e08f00342b`, and seven hashed server adaptations.
App lock SHA256: `dd2d5e3f8d9de412caf931de74f19b3746d3065dced8353e10beee212c91fc90`.
Archived server build lock remains
`5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1`.
Development branches are `android/arm64-port` and `android/client-server`.
Defaults and the server repository remain unchanged.

The selected client is rebuilt Windows ARM64 under local ARM64 Wine, with a
separate Ubuntu24 ARM64 MySQL/server guest. This is compatibility execution,
not native Android. Keep the Ubuntu glibc2.39 server root separate from Debian12
Wine/glibc2.36. APK identity remains `io.github.russianranger.esteria`.

## Current evidence

| Component | Observed result | Remaining boundary |
| --- | --- | --- |
| Reconstructed client471 | All five jobs pass in41061576677, including native Windows handoff-reader tests, full client builds and ARM64 Wine controlled-peer/graphics/audio regressions. | Earlier0f compiled-server SRP pairing passes41060555263 with retained six-patch server; new471 pairing and normal CommonMain/world remain untested. |
| Protocol | All215 player descriptors match; containers254/574DWORDs, quests25, player1326DWORDs/42mask words. Client class capacity32, serverMAX_CLASSES12. | Inventory/appearance/custom races need real matched gameplay. |
| Android Wine | Android13 x64 run41046942035 passes reconstructed entry, offline diagnostics and actual loopback transport with source-owned PE mapping adaptation. | Emulator component evidence; production ARM64, graphics/audio and full game remain open. |
| Production ARM64 Wine | Actual frozen-source Wine/FEX build, complete source closure and native client0f codec/entry/offline/transport/Grunt/software Vulkan/frame/texture/captured WinMM+DirectSound pass41057900330. Independent runtime readback covers14,180entries/1,325,744,204filebytes. | Selected471 pairing, Android ARM64/Adreno and complete game remain open. Production still uses oldf036; no provider relabel. |
| Server build | Seven-patch server links/installs all programs/tools; actual full50 ConfigMgr parse/reload passes41041859706. | A clean isolated exported-source rebuild is running after two exact input corrections. |
| Retained server SQL/auth | Native ARM64 run41050050193 passes compiled first/repeat SQL, exact ledgers/restart, real SRP/M2, persisted40-byte session key, owned loopback realm/listener, credentials/trackers and clean shutdown. | This measured input is six-patch build41005048019.1; no reconstructed client/world/Android execution. |
| Appearance storage | Exact source-derived49/132-byte binary tables pass NUL/high-byte roundtrip, REPLACE/read/delete and restart with fixture rows removed. | No canonical original creator was found; provenance remains explicit. Actual game saves/transport unqualified. |
| Server runtime packaging | Current seven-patch stripped SQL/auth/restart gates pass41050050294; native ARM64 loading of actual stripped auth/world programs passes; worldserver shrinks2.65GB→59MB, paired debug data retained outside APK. Runtime plus original notices is21,996,594bytes. | Programs provider stays disabled until complete corresponding-source rebuild proof. |
| Extraction tools | Native CLI/configuration gates pass41054451870 for all four actual source-matched tools;2,495,044byte archive/76files. Source-gated Android installer is integrated. | Real MPQ conversion, custom archive-order parity, source seal and Android execution remain open. |
| Phone-side server sources | Exact seven-patch content package:4,063 files/654,243,888bytes. Actual32MiB Java install, cached zero-copy reuse and complete no-Git product verification pass. | SQL execution through the Android adapter is not yet qualified. |
| Android schema adapter | Streams SQL using the caller's same owned database lease, verifies source/module/UUID identities and journals durable file boundaries. Host subprocess/concurrency tests and APK/AndroidTest/lint pass. | Actual native ARM64 composition passes41058676309 (six-patch) and41058676543 (seven-patch): baseline, updater/reentry,50configs, realm/account and restart share one UUID. Partial baselines currently refuse replay; fresh-slot storage/recovery and typed workspaces pass host checks; the staged phone coordinator now retains bootstrap/guest/database/workspace ownership with three host timeout/retry cases passing. Actual Android SQL and playerbots-complete promotion remain pending. |
| MySQL persistence | Native ARM64 service/restart/backup passes; Android13 x64 actual Java service41016293760 passes two live cycles, ownership and UUID/credential/marker preservation. | Production ARM64 and existing game-save upgrades/restores remain open. |
| Presentation and controls | Actual Android x64 Surface/AudioTrack lifecycle, native ARM64 authenticated X11/XTest, Wine FMOD capture, process ownership/remote cleanup pass separately. | Complete Wine/X11/audio/controller session and Adreno execution unqualified. |
| Application/import | Resumable SAF/ZIP imports,12340 PE/MPQ checks, immutable overlays, mutable UI review, runtime setup and support export build/lint. Android filesystem/update instrumentation passes. | Main START stays gated; launcher controls are not game controls. |

## Latest application checkpoint

The new optional server-content provider preserves the original archive, SQL,
configuration templates and notices. Dependency/content final APK bytes and nine
source-helper assets pass actual readback after a clean build. The local internal
APK is280,688,121bytes, SHA256
`1ab14bee98289a4d0d13cabd08c55069b9c3650292fe3edfa98109d39d60afa2`.
It is a packaging check without PRoot/programs, not a user installation candidate.
See `runtime/evidence/server-content-android-packaging-host.json` for exact inputs.

The persistent RSA4096 development certificate is provisioned, privately backed
up and recorded in `app/development-signing.lock.json`. No delivered update
baseline exists. Never commit signing keys, credentials, user MPQs or databases.
Durable server dependencies, guest helpers, reconstructed client0f and shader
tools have independently verified public release locks. Optional Turnip loading
without a GPU is separate from Adreno qualification.
Client471's separate durable release is published and all seven public downloads
pass actual byte/source readback. Publication workflow41066742791 passes; its
GitHub immutability flag remains false, independently of publisher no-overwrite checks.

## Blockers and next implementation

- Matched reconstructed ARM64 client authentication passes41060555263 after using
  the intended MySQL state layout. The normal untraced gate verifies real Grunt/SRP,
  persisted40-byte session key, loopback realm, unchanged credentials/ledgers and
  clean shutdown. It exits before CommonMain/assets/world; its server is the
  retained six-patch reference. The source-owned normal login handoff also passes
  all five client jobs41061576677; Android writer and actual Glue login remain separate gates.
- Finish the isolated seven-patch server rebuild, source seal and programs APK
  provider; qualify the new production ARM64 Wine archive before rebinding
  client/bridges/shader/Turnip packages to its exact hash.
- Finish phone-owned compiled updater/configuration/account/realm setup and
  the complete fresh-slot setup coordinator; then compose auth/world/client ownership,
  readiness and graceful saves.
- Prepare server maps/DBC/vmaps/mmaps/Cameras and shaders from imported12340
  client data. Full base MPQs and current matched Esteria content are absent.
  Retail/Forever stay disabled until complete local assets are prepared.
- Qualify world entry, combat/loot/inventory/quests, audio/controller, save/relog,
  four-or-fewer controlled bots, offline play and combined resource usage.

No preliminary APK is being requested on the Thor. See scoped runtime receipts
for host/emulator/hardware boundaries and HANDOFF.md for concrete continuation.
