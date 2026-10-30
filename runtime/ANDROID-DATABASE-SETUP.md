# Android database preparation adapter

`ServerDatabaseSetup` runs the existing `mysql_bootstrap.py` through the installed
PRoot owner and the separate pinned Ubuntu server runtime. The APK includes the
two original Python helpers and a generated SHA-256 inventory; it does not keep
a second bootstrap implementation. Each helper generation is copied, verified
and retained under private `state/server-work/helpers`.

The guest state path is always `/work/state`, mapped to private
`state/server-work/state`. Keep this path stable across app and runtime updates.
Accounts, credentials, datadir, bootstrap journals and private MySQL logs remain
there. They must never be included in support exports or runtime replacements.
The separately owned native operation has bounded stdout/stderr logs and a
unique session directory. No credentials appear in arguments or result reports.

Fresh preparation creates the same persistent application credential used by
the configuration renderer, under the existing bootstrap lock. Missing secrets
for an existing/partial database are errors, never an instruction to regenerate
them. The unchanged bootstrap initializes visible staging, checks real engine
version/UUID and SQL authentication, stops its temporary server cleanly, then
promotes persistent data and its receipt. Interrupted or unknown data is retained
for recovery. A repeat checks the completed filesystem receipt and UUID only.

The result explicitly does not establish current live service state or SQL
readiness. `bootstrapPopulatedApplicationSchemas` describes the bootstrap receipt,
not the current contents of a database subsequently populated by the server.
The final session must start the owned persistent engine and run authenticated
`verify`, followed by matched schema and auth/world readiness checks.

Cancel before process launch is immediate. Once initialization starts, ordinary
cancellation waits for its safe completion; it does not kill a half-initialized
database. A 12-minute deadline or thread interruption forcibly stops the owned
chain and reports failure with staging retained. Android process death has the
same preservation/recovery requirement. There is no automatic deletion or retry
over unknown initialization state.

The adapter is compiled into the app but is not yet called by a launcher action.
Android MySQL execution remains an explicit qualification gate. The six focused
host tests exercise actual completed receipts, missing-secret rejection, partial
state preservation, link rejection and UUID mismatch; they do not start MySQL.
The native ARM64 backup workflow additionally calls the exact wrapper for a
fresh disposable destination and repeats it to check credential/receipt identity.
That real-engine result remains pending until its workflow succeeds.

Validation checkpoint: ARM64 Android app and instrumentation compilation plus
lint passed locally. This is not Android runtime, world-server or gameplay proof.
