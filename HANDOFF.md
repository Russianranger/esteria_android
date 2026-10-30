# Next-session handoff

Continue toward a nearly complete local client/server APK for AYN Thor. User
explicitly authorizes implementation, commits, branch pushes and CI. Push only
client `android/arm64-port` and integration `android/client-server`; preserve
both defaults and shared history. Server is read-only. No preliminary APK or
Thor startup-test request. Do not imply execution continues without a real job.

## Current inputs and outcome

The application lock pins client69ccfaa6a0dd01607d0a99be9b27b7b25dafc5aa,
serverf35f04d01689f034778e3474b3c820092f51e461 and
Eluna58d7652138887783228b9727bd1fa4e08f00342b, with six hashed server patches.
The newer client development tip is97b347ee034551ea78dc905c3e209667534e6283.
Fetch both branches and inspect Actions before interpreting pending results.

The chosen path is reconstructed Windows ARM64 under local ARM64 Wine, plus a
separate Ubuntu24 ARM64 MySQL/server guest. It is not native Android. Do not mix
Ubuntu glibc2.39 server binaries into Debian12 Wine's glibc2.36 rootfs. The x64
Android fixtures are component qualifications, not production ARM64 evidence.

The app has resumable immutable imports, verified optional runtime providers,
writable client/UI generations, review/activation, native presentation/input/audio
bridges, process ownership, persistent bootstrap source packaging and diagnostics.
Gameplay START remains gated. Latest all-four-provider ARM64 build passes core,
APK/AndroidTest/lint and exact final-byte inventory checks. No user signing/update
baseline, Android ARM64 execution, client/server login or world entry is qualified.

## Actual latest evidence and next work

1. Full EXE offline checks passed all5 jobs41003225299 (cliente2718f6).
   Positive transport run41006100154 passed actual x64 packet/stream I/O after
   the timer-wake fix, then exposed a diagnostic-only missing Finalize() call.
   Client97b347 fixes that; wait for complete Windows/Wine receipts before repinning.
2. Server41005048019 compiles six-patch source using saved cache. Prior run linked
   authserver/dbimport but failed final worldserver link after2,257objects. Patches5/6
   repair real template visibility and README-only Custom registration. Complete
   package, compiled SQL updater and real authentication harness remain unqualified.
3. Proposed patch7 derives module configs from the selected main config's parent,
   preserving defaults. Actual source-linked host ConfigMgr reference passes and
   original-source negative control fails. It is not in sources.lock yet. Activate
   after current link evidence; then materialize/check every enabled module config,
   not just playerbots.conf. ConfigMgr success alone does not prove modules loaded.
4. Base/account SQL runs pass. Backup41006179962 fails before dumping on a mysqldump
   option accepted only by mysql. The corrected command and real host preflight
   are implemented; actual ARM64 dump/restore/restart and repeat-wrapper must rerun.
   Playerbots fourth-schema readiness reference is under development; no AI claim.
5. Android stdin41003838802 passes9 groups; native stdin41003838751 passes12.
   Tracer41003838793 passes3survivors versus0 protected plus saved-file relaunch.
   Remote-owner41006180061 passes owner/tracer/guest exit and independent control
   survival in4,115ms with nine pidfds. Whole-app death/ARM64/Wine remain open.
6. Android MySQL41006572364 builds a separate exact x64 debug fixture. Require real
   initialize→seed→repeat→verify SQL/UUID/credential evidence before enabling the
   normal bootstrap adapter. Preserve /work/state and private secrets across updates.
7. Turnip41006180058 builds Linux ARM64 Mesa KGSL plus X11 software WSI and real
   glslang/SPIRV tools. A source build is not GPU/Android qualification. Existing
   Debian22 Mesa DRM driver does not establish Adreno KGSL support.
8. Shader staging helper uses strict pinned client translation, bounded processes,
   exact input/tool provenance and atomic output promotion. Eight host groups pass;
   synthetic structural SPIR-V tests are not real shaders. Complete tool packaging,
   app setup adapter and actual data-based generation remain work.
9. Durable server41003838795, guest41006572380 and client41006572426 dependency
   releases are published and read-only/public-fetch verified. Scoped release locks
   contain exact URLs/hashes; GitHub immutable=false is explicit. Unified clean
   all-provider APK automation is next; never depend on expiring Actions artifacts.

## Missing content and acceptance

Only the supplied Wow.exe established3.3.5.12340. Full base MPQs, current custom
provider stack/catalogs, matched DBC overlays/maps/vmaps/mmaps/Cameras and generated
shaders are absent. See ASSET-REQUIREMENTS.md. Continue independent platform work;
request precise files only when unavailable inputs prevent all remaining progress.
Keep Retail/Forever disabled until complete local closure is prepared. Start bot
qualification at a small measured population; current random population is zero.

Read the scoped runtime qualification documents for exact hashes and limits. Do
not infer world saves from a file fixture, game input from XTest, or Adreno rendering
from Lavapipe. Main device testing requires one coherent expected-playable package.
