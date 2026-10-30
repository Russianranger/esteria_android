# Retained Android installation coordinator

`ServerInstallationSetup.beginFresh` validates prepared sealed dependencies,
programs and content, a separate private server-data directory and the caller's
free-space reserve. It returns a retained owner before any native setup work.
Its typed fresh selection uses `content.sourceLockSha256()` from the archived
server build, together with runtime/program/content/module identities. A
client-only application source update does not change this database selection.

The owner retains the fresh attempt, workspace and live database handle while
`prepare` initializes a fresh database, awaits live SQL identity and invokes the
new fixed guest entrypoint. The guest runs the available real source baseline,
compiled updater, completed updater reentry, full configuration, local realm and
owned account APIs on the same UUID/service and state lease. Final realm/account
verification must succeed. Credentials remain private; only public component
identities and journal/receipt hashes enter its staged report.

The initial result remains `STAGED_PENDING_PLAYERBOTS` and writes only
`server-installation-staged.json`. The original three-program provider cannot
satisfy the new measured-helper namespace gate. Production activation and every
Main START action remain closed while a complete helper/source provider is pending.

The guarded `finishPlayerbots` path requires the sealed provider to contain the
measured ARM64 helper and its exact build/native SQL receipts, preserving the
original three-program identities. The fixed guest `--phase playerbots` invokes
`finish_playerbots` on the same retained service and UUID. It validates the
private staged source/baseline/core/account/credential bindings, writes a durable
configuration-transition intent, and explicitly renders and verifies the complete
configuration with `DataDir=/esteria-data/data`. The whole prepared generation
is mounted once at `/esteria-data`; the earlier staged `/esteria-data` config and
marker remain recorded as historical inputs. No baseline or compiled updater
is replayed.

The shared PB initializer and live core/PB/realm/account verifiers must finish
before `SCHEMAS_VERIFIED` and `server-installation-verified.json` are returned.
That receipt still reports engine stopped, complete setup, promotion, world,
server-data qualification and gameplay as false. A cancelled known config
transition can reenter only its exact old/final generations; uncertain PB intent
continues to refuse replay.

`stopAndPromote` repeats the completed live checks immediately before shutdown,
then requires the actual owned stop acknowledgment to match UUID, service
operation and full MySQL version, with started/ready/clean-exit true. Only then
can it write the SQL-only `server-setup-complete.json`, release all workspace
users and atomically promote the fixed slot. A timeout preserves its owner;
promotion failure preserves the recovery records. This is initialization proof,
not game-data, world, AI or Android qualification.

`completed(...)` resolves the exact promoted source selection and validates the
stored setup, helper, stop and private journal identities. The returned
`FreshServerInstallations.Active.setupReceiptSha256` comes from the validated
promotion proof, never by trusting the current marker. A later session may render
its own verified config generation and refresh public realm/account receipts;
the setup proof and private source/account journals remain unchanged. Live SQL
and separately verified game-data readiness still precede any session launch.

Cancellation before a phase is immediate. A source SQL file or compiled updater
that already committed execution intent finishes its own safe boundary; then the
next phase refuses to start. The Java owner signals a private cancellation marker
and retains control while that work finishes. A close timeout keeps the owner
available for retry.

Both bootstrap and installation guest children remain on the owner, with their
own typed workspace token, until actual Java process ownership settles. Bootstrap
also transfers its real database FileChannel/FileLock to the retained owner before
native launch. Cleanup timeouts cannot release that lock, stop the database,
abandon the attempt or allow another setup over its state. Close retries settle
the helper first, then request database shutdown, then abandon and retain the
failed fresh slot. Forced or failed cleanup remains an error, never a successful
save. Existing active/legacy databases are not initialized through this API.

The older public database-bootstrap API also retains process/file ownership in a
strong per-workspace registry before launch. Concurrent retry refuses an active
operation, including its prelaunch window. A cleanup timeout leaves that registry
and FileLock intact. A later bounded `retryPendingCleanup` (also invoked before
the next public prepare) signals only the retained process and releases ownership
only after it stops. It does not initialize SQL, discover PIDs or label a failed
cleanup as successful recovery. Thus a legacy caller discarding an exception
cannot allow garbage collection to release a live child's database lease.

The current source helper package has 18 files, including all 15 local Python modules,
the sealed public profile and nested appearance SQL/audit resources. The bounded
helper installer limit is 32 and its exact declared closure remains mandatory.
Combined APK packaging explicitly checks these source bytes and manifest, with
strict missing/extra/tampered/profile/duplicate-JSON rejection. Unknown APK
assets remain rejected. An Android helper filesystem test is scheduled in the
existing disposable-emulator workflow.

Historical `runtime/evidence/server-installation-coordinator-host.json` records
the earlier 17-file source package and phase mocks; its APK hashes and source
claims remain unchanged. Current focused Python suites pass 43 tests, including
real host-child/PB-journal fixtures and config-transition/reentry/cancellation
checks. These emulate SQL rows and do not qualify native or phone execution.
Three Java owner/file-lock fault cases run at 32 MiB, checking retained cleanup,
missing-helper/pending-promotion refusal and retry/new-slot allocation. Real
filesystem tests verify proof-bound setup hashes, tamper rejection and exact
suffix-bearing MySQL version reconstruction. SDK Java compilation and these
focused owner/storage tasks pass.

The prior actual seven-patch PB loader/core composition is recorded separately in
[run 41076505231](../evidence/server-playerbots-schema-41076505231.json). It does
not exercise this new finish/config-transition/clean-stop coordinator path.
The [reuse-only ARM64 gate 41088296041](NATIVE-INSTALLATION-FINISH.md) subsequently
passed the actual portable finish, nested DataDir transition, completed reentry,
production service restart and bound SQL-only clean-stop receipt on one UUID.
It reused the registered helper and retained runtime without compiling C++.
That gate exercised Python production helpers on native Linux, with Java and
slot promotion explicitly false in its outer qualification.
Android execution, sealed helper-provider activation, world and gameplay remain
unqualified. No Main START action or device-test package is delivered here.
