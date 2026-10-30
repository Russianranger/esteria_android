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

The result is explicitly `STAGED_PENDING_PLAYERBOTS`. It writes
`server-installation-staged.json`; it does not write a complete setup receipt,
publish a slot pointer or launch auth/world/client processes. Playerbots schema,
complete setup, server-data qualification and gameplay flags remain false.
The actual source-bound playerbots loader and native qualification are the next
required phase before complete promotion can be implemented.

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

The source helper package has 17 files, including all 14 local Python modules,
the sealed public profile and nested appearance SQL/audit resources. The bounded
helper installer limit is 32 and its exact declared closure remains mandatory.
Combined APK packaging explicitly checks these source bytes and manifest, with
strict missing/extra/tampered/profile/duplicate-JSON rejection. Unknown APK
assets remain rejected. An Android helper filesystem test is scheduled in the
existing disposable-emulator workflow.

Host evidence is `runtime/evidence/server-installation-coordinator-host.json`.
Seven phase-orchestration tests use mocked runtime calls and are not SQL evidence.
The combined related Python suites pass 29 checks; packaging passes 15. Three real
Java owner/file-lock fault cases deliberately block backend cleanup beyond its
wait deadline, verify retained ownership, legacy startup exclusion and retry cleanup/new-slot allocation.
Those tests run with a 32 MiB heap and Java backend fixtures, without starting an
operating-system or SQL child. The main Android build workflow requires them.

A fresh default application/test APK build and lint pass. The final host build
used transient output directories outside workspace synchronization after an
earlier attempt hit a disappearing sync-temporary DEX file during packaging. The actual APK's
17 helper files and local import closure match repository sources, and stale
provider archives are absent. The owner/entrypoint has not yet run on Android or
native ARM64; separately recorded native source7 primitive composition and
matched reconstructed-client SRP checks do not qualify this new coordinator.
No Main START action is activated and no device-test package is delivered here.
