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
The newer client development tip is0f931bbade36a4b197725d691b8eff7caea7b3be;
its workflow pins integration0146ca89307eb3c00c09b7fbecdf3e301bd9bd53 for Wine Grunt.
Fetch both branches and inspect Actions before interpreting pending results.

The chosen path is reconstructed Windows ARM64 under local ARM64 Wine, plus a
separate Ubuntu24 ARM64 MySQL/server guest. It is not native Android. Do not mix
Ubuntu glibc2.39 server binaries into Debian12 Wine's glibc2.36 rootfs. The x64
Android fixtures are component qualifications, not production ARM64 evidence.

The app has resumable immutable imports, verified optional runtime providers,
writable client/UI generations, review/activation, native presentation/input/audio
bridges, process ownership, persistent bootstrap source packaging and diagnostics.
Gameplay START remains gated. Latest all-four-provider ARM64 build passes core,
APK/AndroidTest/lint and exact final-byte inventory checks. Stable development
signing identity is provisioned and privately backed up; the public fingerprint
is in app/development-signing.lock.json. No delivered update baseline, Android
ARM64 execution, client/server login or world entry is qualified.

## Actual latest evidence and next work

1. Full EXE offline checks passed all5 jobs41003225299 (cliente2718f6).
   Positive transport run41006100154 passed actual x64 packet/stream I/O after
   the timer-wake fix, then exposed a diagnostic-only missing Finalize() call.
   Client97b347 fixes that and all five jobs41007244092 pass. Strict shader source
   926a also passes all five jobs41007556042. Client3f9389 adds actual Grunt/SRP
   callbacks against a controlled local peer; Windows ARM64/x64 in41010223296 pass.
   Real compiled-server pairing is separate; the application still pins69cc.
2. Server41005048019 compiles six-patch source using saved cache. Prior run linked
   authserver/dbimport but failed final worldserver link after2,257objects. Patches5/6
   repair real template visibility and README-only Custom registration. Complete
   package, compiled SQL updater and real authentication harness remain unqualified.
3. Proposed patch7 derives module configs from the selected main config's parent,
   preserving defaults. Actual source-linked host ConfigMgr reference passes and
   original-source negative control fails. It is not in sources.lock yet. Activate
   after current link evidence; complete source-bound module rendering is now
   implemented. Qualifiers must pass both verified source inventory and actual
   compiled selection. ConfigMgr success alone does not prove modules loaded.
4. Base/account SQL and actual backup dump/restore/setup repetition pass. Strict
   complete dump equality in41009954140 identifies a harness-only text-column
   charset normalization. The fixture now declares that existing charset explicitly;
   the full-byte equality gate remains unchanged and requires a new ARM64 run.
   Playerbots fourth-schema source reference is implemented but not yet executed.
5. Android stdin41003838802 passes9 groups; native stdin41003838751 passes12.
   Tracer41003838793 passes3survivors versus0 protected plus saved-file relaunch.
   Remote-owner41006180061 passes owner/tracer/guest exit and independent control
   survival in4,115ms with nine pidfds. Whole-app death/ARM64/Wine remain open.
6. Android MySQL41007887632 fails first atomic journal rename with errno38 before
   database initialization. The x64-only PRoot rename adaptation passes actual
   Android13 atomic replacement/persistence in41010011745. MySQL41010011663 now
   passes initialize→seed→repeat→verify and live SQL/UUID/credential preservation.
   Production ARM64 execution remains open. Preserve /work/state across updates.
7. Turnip compiles all681objects; actual glslang/SPIRV compile/validate/disassembly
   and invalid-input checks pass. The pinned loader returns -3 when its ICD has no
   devices. Corrected41009954190 passes direct exact-ICD zero-device success
   before accepting that loader result. GPU/Android gates remain false.
8. Shader staging helper uses strict pinned client translation, bounded processes,
   exact input/tool provenance and atomic output promotion. Eight host groups pass;
   synthetic structural SPIR-V tests are not real shaders. Exact926a translator
   plus actual8a ARM64 compiler/source bundle packages and verifies successfully;
   optional APK provider/app setup adapter and actual data-based generation remain work.
9. Durable server41003838795, guest41006572380 and client41006572426 dependency
   releases are published and read-only/public-fetch verified. Scoped release locks
   contain exact URLs/hashes; GitHub immutable=false is explicit. Unified clean
   all-provider APK automation passes41009954235 and41010011668, with full paired
   source closure and independent APK readback. These remain internal builds.
10. New persistent MySQL service helper is source-reviewed: exact engine-version
    preflight, upgrade refusal, owned PID/UUID/loopback authentication, bounded
    logs, explicit shutdown and joined engine. Its new Android adapter has an
    exclusive setup/session lease and requires live and clean-stop receipts.
    The separate mysql-service.yml actual runtime gate remains pending; do not
    infer a live service from a setup receipt or enable gameplay prematurely.

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
