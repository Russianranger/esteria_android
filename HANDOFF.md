# Autonomous development handoff

Continue toward one nearly complete local client/server Thor package, or the
user's reported50% weekly usage threshold. No supported meter is exposed; never
invent a reading. Branch pushes, workflows, builds, dependencies, signing and
agents are authorized. Do not stop at a PR/build. No default merges, force pushes,
server-repository writes or preliminary Thor APK requests.

## Exact source and delivery identity

- App:Russianranger/esteria_android, android/client-server. Published reference checkpointf44f854099f9abd70fd722633663e587278d5c0d; functional runtime changes84fa637867ad6c2c916a455c703e577cd60a298c. Fetch current state before editing.
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

1. Inspect original x64 setup-tool build41119182502/job124281186151. Full original
   dbimport/script-module closure and actual Playerbots helper have compiled since
   19:58:42UTC; internal3h bound22:58:42, job bound23:55. It was genuinely running
   at22:08. Do not launch a duplicate or substitute a reduced/no-op loader.
2. On success read bounded build/source/debug/DSO receipts; bind native SQL input
   lock only to actual measured build/MySQL/content outputs. Its committed default
   remains disabled/null. Run actual four-schema SQL/reentry/ledger/clean restart.
3. Complete the currently uncommitted Android x64 provider/fixture group. Review
   exact full905MB original MySQL sourceZIP preservation/readback, fixed source-
   owned helper closure, frozen817 verifier, P→Q measurement/activation distinction
   and retained observer cleanup BEFORE DB/coordinator cleanup. Do not stage it
   until its owner supplies a reviewed exact freeze. No positive measurements or
   Android four-schema qualification exist yet.
4. Complete the new Android input-widget instrumentation group. It uses real
   SurfaceView/InputConnection/KeyEvent/touch and a bounded recording sink; no Wine
   or game claim. Register a real emulator uinput InputDevice only if supported;
   preserve MotionRange admission. Coordinate the shared SDK, then freeze/publish
   and run the real Android13x64 presentation workflow.
5. Continue real data/gameplay gates below; do not request a basic Thor startup test.

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
