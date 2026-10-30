# Source-owned playerbots schema phase

The fourth database has a separate production initializer. Standalone core
`dbimport` registers auth, characters and world; the pinned playerbots hook uses
its own `DatabaseLoader`, update bit 8, source directory and prepared statements.
This phase initializes that database without linking or running playerbot AI.

`runtime.server_playerbots_setup.prepare` consumes actual `VerifiedContent`, an
absolute helper executable, its externally pinned build-receipt SHA-256 and the
selected MySQL client. It binds the complete original build/module/source
selection, all 29 base and 31 released update SQL identities, and the separately
measured helper identity. Original three-program receipts remain unchanged.

`apply(plan, connection, state, version, *, profile, data, expected_uuid,
verify_service, state_lease=None, progress=None, cancelled=None)` requires the
completed production core updater and ready owned account on the same retained
service. Its first call refuses existing playerbots tables or characters. The
existing global four-empty-schema guard still precedes the earlier baseline.
State/configuration and bootstrap/realm/account SQL locks protect the phase.

The private `.server-playerbots-schema.json` intent is atomically written and
fsynced before the compiled helper can execute. Cancellation before intent does
no work; after intent the bounded owned process finishes the current SQL unit.
Failed or interrupted intent is preserved and refuses replay. No updater ledger
rows, bot accounts or character rows are synthesized by this initializer.

Completion requires successful real loader exit, its exact 52-statement marker,
the exact source update ledger, live table/column/index metadata, unchanged core
tables/ledgers/account rows/realm trackers, credentials and account intent. The
private journal binds source/content/modules, helper, MySQL UUID/version/datadir
and the unchanged completed core journal. It records no adoption or upgrade.

`verify_completed(content, connection, state, version, *, expected_uuid,
verify_service)` runs under the caller's retained state/service/bootstrap locks.
It reads and verifies; it acquires/releases no locks, writes no files, and starts
no executable. Completed `apply` reentry also performs no helper execution.
Completed core verification accepts a populated fourth schema only through this
separate completed proof. Any playerbots journal, even with an empty schema,
requires that proof; deleting tables cannot restore the earlier empty-pool path.
The standalone core updater's default snapshot continues to require emptiness.

The target-only build uses the archived seven-patch source lock
`5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1`
and original build `41019374697.1`, while validating the current app's full server
and compatibility objects against it. It reuses the retained asset-free source
archive, seven patches, supplemental header and original compiler environment.
The new helper/source/build payload is separate from the original program
archive and does not claim complete source-companion closure.

The native workflow consumes the exact already-qualified seven-patch runtime
and SQL package, then creates a fresh instance in the verified compiler-free
image. It calls the actual production installation composition and fourth-schema
APIs, verifies completed reentry, runs the real loader again with an explicit
disposable persistence table, and restarts MySQL cleanly. It removes that table
before final live product verification against the original completed journal.
Only typed receipts are exported; SQL logs and account/credential contents remain
private. Host journal/process fixtures are not native SQL qualification.

Actual native execution of this new phase is pending. The phone coordinator
remains staged pending playerbots; this code does not create a complete setup
marker, promote a slot or open normal START. Playerbot AI, bot characters, world
startup, existing-save upgrades, Android runtime and gameplay remain unqualified.
