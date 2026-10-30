# Next-session handoff

Continue toward a nearly complete local client/server APK for AYN Thor. User
explicitly authorizes implementation, commits, branch pushes and CI. Push only
client `android/arm64-port` and integration `android/client-server`; preserve
both defaults and shared history. Server is read-only. No preliminary APK or
Thor startup-test request. Do not imply execution continues without a real job.

## Current inputs and outcome

The application lock pins client0f931bbade36a4b197725d691b8eff7caea7b3be,
serverf35f04d01689f034778e3474b3c820092f51e461 and
Eluna58d7652138887783228b9727bd1fa4e08f00342b, with seven hashed server patches. Source-lock SHA256 is
5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1.
The new client provider/source companion are measured and verified; publish their
new exact durable release next. The old69 release remains intact and is rejected
by current-pin fetch checks during this explicit dependency-preparation interval.
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
   Client0f all five jobs41012726334 pass including native ARM64 Wine Grunt.
   Real compiled-server pairing is separate; application pins now select0f.
2. Server41005048019 linked the complete six-patch source and passed loader,
   generated-module selection and source packaging. Its first runtime gate stopped
   before SQL because the consumer omitted three producer provenance fields.
   That strict consumer is fixed and regression-tested. server-requalification.yml
   now tests the retained exact linked artifact without another full compile.
   No actual compiled SQL/auth success is claimed yet.
3. Proposed patch7 derives module configs from the selected main config's parent,
   preserving defaults. Actual source-linked host ConfigMgr reference passes and
   original-source negative control fails. It is now in sources.lock with client0f.
   Complete source-bound module rendering is
   implemented. Qualifiers must pass both verified source inventory and actual
   compiled selection. ConfigMgr success alone does not prove modules loaded.
4. Native ARM64 backup41013086447 passes complete367,899,260-byte dump equality
   after fresh restore and restart, account journal preservation and repeated setup.
   The exact harness charset correction leaves server tables/strict gates intact.
   See runtime/MYSQL-BACKUP-QUALIFICATION.md for receipt/artifact identities.
   Existing-save restore/upgrades remain unqualified. Playerbots fourth-schema
   source reference is implemented but not yet executed.
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
   plus actual8a ARM64 compiler/source bundle packages and verifies successfully.
   Optional APK provider and Android transactional setup now build/lint and pass
   all five final-provider checks. Durable dependency publication is in progress;
   actual Android compiler execution/data-based generation remains unqualified.
9. Durable server41003838795, guest41006572380 and client41006572426 dependency
   releases are published and read-only/public-fetch verified. Scoped release locks
   contain exact URLs/hashes; GitHub immutable=false is explicit. Unified clean
   all-provider APK automation passes41009954235 and41010011668, with full paired
   source closure and independent APK readback. These remain internal builds.
10. New persistent MySQL service helper is source-reviewed: exact engine-version
    preflight, upgrade refusal, owned PID/UUID/loopback authentication, bounded
    logs, explicit shutdown and joined engine. Its new Android adapter has an
    exclusive setup/session lease and requires live and clean-stop receipts.
    Native ARM64 mysql-service.yml run41013380186 passes three SQL cycles and
    command/EOF/helper-signal shutdown with unchanged UUID/credentials/markers.
    The real Android adapter lifecycle fixture is in progress; PRoot expands socket
    paths, so its exclusive socket directory must remain short. Keep gameplay gated.

11. Android x64 Wine41015479987 passed full source/APK gates, then failed ntdll
    executable-page protection before client execution. Exact numeric memory-map
    diagnostics are running next; do not treat an inferred execmod restriction as
    established. No Android policy or target SDK is weakened. Owned authenticated
    X11/input/audio composition now builds; complete Android execution is separate.

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
