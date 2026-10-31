# Status

Updated2026-10-31UTC. Signed candidate0.1.0-dev.1 is published for one consolidated
content/device test. No Thor/world gameplay result exists yet. No supported
weekly-usage meter is exposed; stop if the user reports the requested50% threshold.

APK/source/build identity and the procedure: THOR-TEST-CANDIDATE.md.
Release: https://github.com/Russianranger/esteria_android/releases/tag/android-v0.1.0-dev.1
Signed336,697,265B APK SHA8b953bc5e959a4feb716abed3ff7083ee85a2fdedafa44105fc1caeef2e25baa;
application8c1e63d43ee0b552d796b862a2c1b1c146a0a7c4, build41149985842, versionCode1.
Public download HTTP200/size and all four GitHub asset digests verified. Persistent
certificate matches the pinned5e6921a0… identity; v2/v3 and payload preservation
pass. Initial update baseline is recorded; future published versions must increase.

## Exact selection

- App:android/client-server; package:io.github.russianranger.esteria.
- Selected client binary:471ee42faadf4a97a1d0a86989cf1452621f2dc5.
- Client development:android/arm64-port atc8b0ab201f52e18ffaba1e6c55aad6e26c740251.
- Server:f35f04d01689f034778e3474b3c820092f51e461; Eluna:58d7652138887783228b9727bd1fa4e08f00342b; seven pinned adaptations.
- App source-lock SHA:dd2d5e3f8d9de412caf931de74f19b3746d3065dced8353e10beee212c91fc90. Archived server-build lock:5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1.
- Protocol:254 container slots,25 quests,32 client class capacity;215 player descriptors match. Do not enable1,000 quests/254 classes.

The client is rebuilt Windows ARM64 under ARM64 Wine/Debian12. Linux ARM64
server/MySQL run in separate Ubuntu24 PRoot processes. This is compatibility
execution; keep glibc2.36/2.39 roots separate. Android13x64 evidence does not
qualify Android ARM64, Adreno or Thor. Docker is for development only.

## Evidence

| Gate | Actual result | Boundary |
| --- | --- | --- |
| Client development | c8 ordinary41131932778 allfive jobs pass. ceb complete Retail-ON41127220146 ARM64/x64 pass; exact source/descriptor readback retained. | App stays471; normal asset-backed initialization untested. |
| Matched authentication |41088546780:471/c0e/seven-patch Grunt/SRP,13 checks, persisted session key, loopback realm, clean shutdown. | Synthetic entry/transport, no normal Glue/world. |
| Qualified runtime APK |41148040843@651:337,032,998B SHA187e07c2bd654005de47775adc01b7c91f42e300b87601b4dec5c26b5b5f2b22.122tasks/140s; full CI provider/helper/native validation. Independent1114 integration/30PRoot source files and15ARM64 relink objects checked. | Debug build; whole current APK read in CI, no signing/full-session claim. |
| Independent full APK bytes |41129893343@7c attempt2:337,019,318B SHA68c55d9ef700e73c39ba62caac818a7072be70bc86846b3e3de05735aaf843b0. All127APK entries/eight provider archives/10,743 entries/1,196,665,936 regular bytes read. | Same provider/helper cohort as84fa; current whole APK identity differs. |
| Public server preservation |41117618335:12assets/1,783,413,529B, complete source/debug and anonymous readback. Release429422570 at recipe7e498c50cdf55027e679d63e31f0a5e4b117f934. | GitHub immutable=false; pins/no replacement enforced. |
| Native ARM64 Java coordinator |41148040872@651: actual four schemas, promotion, active reseed refusal, two clean stops, same UUID/restart;30bot tables/31updates.63exact Git inputs/192classes checked; real parser regression runs before SQL. | Linux payload-locator seam; no Android/world/character-save/bot-AI claim. |
| Native x64 SQL |41139757153@7d4: actual original dbimport/52-statement helper,29base files/31updates,30bot tables, reentry, four-schema preservation, restart and clean stop pass in245s.58caller Git inputs/eight source-profile pins checked. | Native Linux x64; Android/world/AI remain false. |
| Android13x64 four-schema coordinator |41148736592@1d181/P651: all13 SQL/lifecycle flags pass;30bot tables/31updates; promotion, active reseed refusal, same-instance/private-state preservation and two clean stops. Actual parser regression passes;952.488s instrumentation. | Exact typed x64 fixture; no Android ARM64/auth/world/character/bot-AI claim. |
| Android13x64 MySQL |41109642918@4fd bootstrap/service lifecycle; fresh817 run41119182193 also passes. | Distinct runtime bytes; current code inherits no historical Java proof. |
| Android recovery |41129893390@7c five handoff deaths;41132701736@84fa adds actual generic lease death/reacquisition. | Component-only; source/APK readbacks separate from full app restart. |
| Android updates |41129893361 package/private-file/update contracts pass. | No delivered stable-key update baseline. |
| Canonical tooling |41148040883@651:1414checks/65.680s,1344passed/70explicit skips; syntax and pinned patch checks pass. | Host tooling; runtime/gameplay remain separate. |

Proofs are under runtime/evidence. The84fa APK provider/helper/native identities
match the fully read7c cohort. The first7c APK attempt failed an NDK HTTP/2
transfer before compilation; only failed jobs were retried. Source checks remain
mandatory. Public Wine consumption and atomic seven-pin adoption also pass;
original server266-member source/debug preservation remains retained.

## Implemented runtime behavior

The Service owns setup, presentation, input and game lifetime across Activity
changes. Import/data leases span extraction, shaders and SQL. Launch orders
DB→auth/world readiness→presentation→private one-use login→reconstructed client.
Shutdown requests Alt+F4, retains presentation until client reap, then world/auth
before DB. Deadlines retain ownership. Explicit force marks recovery, never a
successful save. Active/legacy databases are never reseeded.

Core ExclusiveFileLease reserves canonical names BEFORE opening a descriptor and
releases the reservation only after FD close. A real Linux negative control
reproduces the old POSIX lock-loss bug; app cross-JVM and Android tests cover the
fix. Never unlink a live lease file. Unknown/tampered/linked login records and
private account/config/save siblings are preserved through recovery.

IME Done/soft Enter atomically submits pending text+Enter; typed zero-enqueue
batch rejection retains the draft. Closed/replaced connections refuse callbacks.
Actual Android13x64 run41138732113 passes eight widget/IME groups and optional
registered-axis/camera/EOF cleanup with eight real ranges. Constructed events
remain distinct from kernel/physical delivery, full Wine input and gameplay.

Shader/data preparation selects the same source-defined effective locale while
retaining the requested locale. Unsupported winning enCN/enTW aliases fail
explicitly. Reusable client helper fixes are published atc8. A real local
glslang14.3 test compiles three synthetic vertex/pixel/companion modules, checks
SPIR-V/disassembly and rejects invalid GLSL; no game-data shaders were generated.
Explicit world setup now runs the existing pinned offscreen Turnip C probe before
costly extraction. Its retained cleanup/logs/strict receipt have host evidence;
no GPU/hardware result exists here.

SAF resume preserves file-slice origins, with real descriptors/5GiB sparse-offset
and bounded fallback checks. Known supplied DBC schemas use source-derived field
counts/packed strides for112 active stores; all have SQL fallback. See
runtime/server/DBC-PREFLIGHT.md and the MPQ+small-overlay import route in BUILDING.md.
Complete loose-world metadata still has a16MiB ceiling; do not raise the heap.

Support export is separate/single-flight while busy, with fixed bounded roles,
redaction and no account/config/engine-private captures. Usage sampling reports
visible owned groups, not whole-guest/client-server-bot budget. Prepared cache
remains OFF: actual Android hardlinks fail EACCES13; stat observations do not
qualify exclusive cache publication or ARM64 semantics.

## Active work and remaining gates

1. Original x64 build41119182502 and actual native SQL41139757153 pass. Source/
   debug/runtime preservation is complete; original868MB component is fully
   admitted in CI, while local readback is bounded to source/receipt evidence.
2. Fresh provider measurement41148040884@651 passes complete acquisition,
   construction and independent readback after the Integer/Long JSON comparison
   fix. All82 source pins match; descriptor SHA909b0dcd00c24289cf2bf59e1a36b075885cec62de008fc1cbb47e37eeb5c573.
   Six bounded receipts are fully read locally; complete1,969,319,740B product is
   read in CI and remains local-metadata-only. Actual Android41148736592@1d181
   now passes four-schema SQL, promotion, reseed refusal, same-instance restart,
   private-state preservation and two clean stops in952.488s. Independent Q
   source readback covers1122files and all82 P/Qcode pins. Original native SQL/
   ELF/runtime bytes are unchanged;995/c441 failures remain preserved. Native
   ARM64 Java651 and complete ARM64 debug APK651 also pass. Full8provider release
   compilation/lint and complete release byte/manifest checks at8c succeed. The
   non-debuggable APK is persistently signed and published as0.1.0-dev.1. Exact
   release metadata/signing proof are in runtime/releases and runtime/evidence.
   World/gameplay remains open.
3. Preserve actual Android input-widget41138732113 success and its prior test-
   toolbar failure. Physical controller/kernel input, Wine and gameplay remain
   separate gates.
4. Import real12340 MPQs and matched Esteria catalogs/textures/DBC/maps; generate
   shaders and validate normal login, characters/world, combat/loot/inventory/
   quests/audio/saves/relog. No complete base/custom data is available here.
5. Run the single THOR-TEST-CANDIDATE.md procedure with complete client data:
   normal world/gameplay, controller/audio, saves/relog, in-place update, one bot
   and offline lifecycle. Return one support bundle. Measure combined resources
   before increasing toward the four-bot ceiling; custom features remain open.

Private persistent RSA4096 signing baseline1 is published; public certificate is in
app/development-signing.lock.json. Defaults/server repository remain unchanged.
Assets, initialized databases/prefixes, saves, credentials and private keys stay
outside Git. See HANDOFF.md for the next concrete actions.

First x64 SQL attempts stopped before initialization. The diagnostic run isolated
a parent-relative source-lock/patch layout error. Exact historical lock bytes and
seven digest-pinned patches are now staged together; unchanged source admission
and real regression tests pass. The corrected actual native SQL41139757153 passes; earlier failures remain retained.

Selected471 normal startup needs authentic signed stock UI and stock ClientDB
content. Complete12340 Data plus one complete locale is the practical first input;
missing catalogs do not globally block classic-race bring-up. Existing setup
requires selected speech before extraction. Full Esteria custom features and
normal world content coverage remain separate validation gates.
