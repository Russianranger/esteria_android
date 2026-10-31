# Autonomous development handoff

Continue toward one nearly complete local client/server Thor package, or the
user's reported50% weekly usage threshold. No supported meter is exposed; never
invent a reading. Branch pushes, workflows, builds, dependencies, signing and
agents are authorized. Do not stop at a PR/build. No default merges, force pushes,
server-repository writes or preliminary Thor APK requests.

## Exact source and delivery identity

- App:Russianranger/esteria_android, android/client-server. Published diagnostic checkpointc441c0c8f8dc8a7ff7008e388cd26684c58c5365; functional runtime changes84fa637867ad6c2c916a455c703e577cd60a298c. Fetch current state before editing.
- Package:io.github.russianranger.esteria. Private stable signing is backed up; public certificate:app/development-signing.lock.json. No delivered update baseline.
- Selected client binary:471ee42faadf4a97a1d0a86989cf1452621f2dc5.
- Client development:Russianranger/wowdecomp_esteria, android/arm64-port atc8b0ab201f52e18ffaba1e6c55aad6e26c740251. Allfive41131932778 jobs pass. Complete Retail-ON Windows ARM64/x64 passes41127220146 atceb; source readback retained. Do not advance app/cohort pins without deliberate requalification.
- Server:f35f04d01689f034778e3474b3c820092f51e461; Eluna:58d7652138887783228b9727bd1fa4e08f00342b; seven hashed adaptations.
- App source lock:dd2d5e3f8d9de412caf931de74f19b3746d3065dced8353e10beee212c91fc90. Archived server-build lock:5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1.
- Windows ARM64/Wine/Debian12 plus Linux ARM64 server/MySQL/Ubuntu24 in separate PRoot roots. Compatibility execution, not native Android. No Docker requirement on the device.

A single root publishes explicit reviewed/frozen paths. CLI fetch works; if push
is unavailable, use GitHub Git-object API with expected-head lease. API commit
hash differs from local temporary commit: fetch canonical ref and update-ref
without resetting another agent's working files. Preserve all receipts, source
locks, notices, original binaries/paired debug and historical failures.

GitHub run-job wrapper responses can be stale. For current evidence use approved
GitHub fetch on /actions/runs/RUN/jobs?per_page=100 and inspect actual conclusion,
step timestamps and artifacts. Never infer completion from an uploaded early
artifact. Tools cannot download artifacts over512MiB; do not bypass that cap.
Large source/build artifacts are fully verified in CI; label local-read boundaries.

## Immediate execution

The first signed candidate is published and its download/digests verified:
https://github.com/Russianranger/esteria_android/releases/tag/android-v0.1.0-dev.1
Tag points exactly to8c1e63d43ee0b552d796b862a2c1b1c146a0a7c4/build41149985842.
One APK336,697,265B SHA8b953bc5e959a4feb716abed3ff7083ee85a2fdedafa44105fc1caeef2e25baa;
packageio.github.russianranger.esteria/versionCode1/persistent certificate5e6921a0….
All4public asset digests and HTTP200 APK filename/length match. Preserve assets/tag.

1. Use THOR-TEST-CANDIDATE.md as the one consolidated content/Thor procedure.
   Complete original12340 Data/one locale and Wow.exe is the practical first
   input. Import/setup are in-app; no manual database administration. Main
   world/gameplay, actual AndroidARM64 session, physical input/audio, character
   saves, botAI, combined resources and offline behavior await this test. Keep
   full custom Esteria inputs/features active and separately unqualified.
2. Actual Android13x64 four-schema41148736592@1d181/P651 PASSES all13 flags:
   30bot tables/31updates, promotion, reseed refusal, same-instance/private-state
   preservation and two clean stops.952.488s instrumentation, real Android JSON
   parser regression. Exact1122 Q files/82P/Q pins independently checked.
   Raw304228B071bf175… and compact15481B287995ad… are retained. No hardware/
   auth/world/character/AI proof transfers from this typed x64 fixture.
3. Native ARM64 Java41148040872@651 PASSES actual SQL/promotion/restart with
   63exact Git inputs/192classes and parser regression before setup. Full debug
   APK651 and full8provider nondebug release8c both pass. Original source/debug
   companions and bounded/local-versus-CI read boundaries are preserved.
4. Release signing uses the existing external key; public lock now records
   baseline1. Future signed updates require a higher workflow_dispatch
   build_version_code and the previous published APK/certificate/hash. Never
   regenerate the key or use qualification-only signing for distribution.
   Private key/password files stay outside Git and CI; no private data shipped.
5. Resume from the returned support bundle or real available content. Begin
   with one same-account Human Warrior alt; random population is OFF/max4.
   Do not mark normal world entry or custom appearances qualified from source
   audits, SQL receipts or compiled APKs. This final metadata checkpoint changes
   no runtime code or payload; the immutable delivered build remains8c.

Historical original x64 build41119182502, native x64 SQL41139757153 and measured
providersfff/651 remain preserved. Current651 descriptor SHA909b0dcd00c24289cf2bf59e1a36b075885cec62de008fc1cbb47e37eeb5c573;
complete1,969,319,740B product13022260387 is CI-read/local-metadata-only. Do not
rebuild original1850-object tools or transfer old caller proof to changed code.

## Completed evidence to preserve

- Native ARM64 Java84fa:41132702177 passes actual four-schema SQL, promotion,
  active reseed refusal, same UUID persistent restart, two clean stops,
  30bot tables/31updates. Full small artifact and62compiled Git inputs/191classes
  checked in runtime/evidence/native-java-installation-84fa6378-readback.json.
  Linux payload locator only; Android/world/character-save/bot-AI are false.
- Android generic lease84fa:41132701736 passes six Binder deaths/recreations,
  five handoff states and nine generic lease guards. Source/APK strict readback
  is being finalized. Historical five-case7c proof is unchanged and retained.
- Qualified functional-runtime APK84fa:41132701776 succeeds,337,031,390B
  SHA578546cdef502c8397255072e9f90f4cc73713977930a7149d32cb90278da1a2.
  Full payload read in CI; independent1058integration/30PRoot source files and
  15ARM64 relink objects checked. See local-game-profile-84fa6378 evidence files.
- Earlier7c APK41129893343 attempt2 has full independent local byte readback:
  337,019,318B SHA68c55d9ef700e73c39ba62caac818a7072be70bc86846b3e3de05735aaf843b0;
  127APK entries/eight provider archives/10,743entries/1,196,665,936regular bytes.
  Its provider/helper identities match84fa. Attempt1 NDK HTTP/2 failure is retained.
- Canonical toolingf44:41133823889 passes1346checks/46.019s,1276passed/70skips.
  The84fa failures were isolated-javac closure and test Git stat-cache assumptions;
  source admission remains byte-identical/strict. See tooling-f44f854-ci-confirmation.json.
- Actual Android updates41129893361, presentation/native ownership components and
  MySQL service runs pass separately. Older/fresh MySQL runtime bytes differ;
  historical817 consumer requires complete frozen-source admission and transfers
  no Java proof to current sources.
- Public local-server release429422570, tagdeps-local-server-f35f04d-21ce4e1b-b7d9b72c,
  targets exact recipe7e498c50cdf55027e679d63e31f0a5e4b117f934.41117618335 verifies
  all12assets/1,783,413,529B, sources/debug and complete anonymous readback.
  githubImmutable=false. Never replace assets/move tag. Full original server
  rebuild is unnecessary for packaging. Wine public source/cohort consumption
  and seven-pin atomic adoption also pass.

## Runtime invariants

- Service owns setup/game/presentation across Activity changes. Setup holds
  import/data leases through extraction/shaders/SQL. Game retains import/view,
  starts DB→auth/world readiness→presentation→one-use local login→client.
- Selected471 supports Alt+F4. Reap client before presentation/world/auth/DB
  shutdown. Deadline failure retains owners; explicit force marks recovery,
  never successful saving. Never reseed active/legacy saves.
- ExclusiveFileLease reserves canonical name BEFORE any FD open; remove only
  after FD close. Never unlink live lock files. Closing duplicate POSIX FDs can
  release another owner despite Java FileLock.isValid; negative/control tests
  reproduce this. Handoff uses its separately tested equivalent admission rule.
- Read runtime/client/LOCAL-LOGIN-RECOVERY.md before changing the fixed57B wire
  contract. Preserve unknown/pre-proof/tampered/linked records and save siblings.
- IME pending-text+Enter is atomic; typed zero-enqueue refusal preserves draft.
  Closed/replaced connections refuse callbacks. Actual widget coverage remains
  component-only; real Wine input/physical controller/world must be measured.
- Shader/data effective locales must agree; preserve requested locale separately.
  Winning enCN/enTW aliases are explicitly unsupported. Explicit world setup
  runs existing pinned offscreen C graphics probe; no hardware result here.
- Support export is separate/single-flight while busy; fixed bounded paths and
  redaction exclude accounts/config/private captures. Visible-owned usage is not
  whole guest/client-server/bot budget. No arbitrary PID/path authority.
- Cache fast path stays OFF. Android stat observations pass but hardlinks fail
  EACCES13; os.link publication/ARM64 semantics remain unqualified. Retain fresh
  source/provider/SQL checks and private SHA authority requirements.

## Content and final candidate

No complete base12340 MPQs/current Esteria catalogs/textures/DBC/custom map
closure or game-data shaders are available here. Imported Wow.exe is build/version
evidence; launch only the reconstructed source-built client. Do not fabricate
assets or convert synthetic component tests into world qualification.

Read ASSET-REQUIREMENTS.md and runtime/server/IMPORTED-SERVER-DATA.md. Prefer
MPQs+small matching DBC overlay; complete loose-world metadata has16MiB ceiling.
Keep strict seven-key server manifest, namespace replacement and continuation
ordering; server fragments alone are not matching full client tables. Known
112 DBC schemas all have SQL fallback; unknown/custom rows remain unqualified.
Modified unsigned GlueXML/FrameXML needs real signature/UI qualification; do not
change policy without evidence. Prepare enabled Retail/Forever data during setup.

After independent work is exhausted, request only the smallest precise missing
input set. Then validate extraction/shaders, matched normal login, character
selection/creation, world, movement/camera/combat/loot/inventory/quests/audio,
saves/relog, one-to-four supported bots and offline lifecycle/combined usage.
Random/autologin bots remain OFF; schema proof is not AI. Deliver one stable-key
signed APK with exact revisions, working link, update steps, consolidated test
and support export only when coherent. Do not imply autonomous agent work after
ending the session; identify any actual running CI separately.

The first native x64 SQL run6e7 and diagnostic54d run failed before initialization.
Actual diagnostic frames isolated lock.parent patch resolution: an archived lock
under runtime/server looked for patches there. The fix stages exact old lock and
seven digest-bound original patches together under fresh source-profile, retaining
unchanged locked_source verification.21focused real regressions pass. Corrected native SQL41139757153 now passes; do not rebuild original tools or weaken source checks.

Practical first game input is original12340 Wow.exe +complete Data with one
complete installed locale. No global Esteria-catalog fatal gate was found in471;
missing catalogs still block affected custom features. Keep signed UI policy,
stock DB requirements, listfile requirement and real world validation explicit.
Existing selected-speech refusal already precedes extraction. See source-bound
classic-asset-minimum-471-audit.json; do not invent assets or over-require optional
archives.
