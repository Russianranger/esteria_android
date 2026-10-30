# Persistent local database service

`mysql_service.py` owns an already initialized MySQL instance for a complete
local session. It never initializes, imports, repairs, migrates or deletes a
database. `ServerDatabaseService` supplies the Android PRoot/native-process
adapter; normal launcher START remains gated pending runtime qualification.

The helper checks the persistent bootstrap receipt, datadir UUID and existing
application credential, then runs a bounded exact `mysqld --version` preflight
before launching against that storage. `--upgrade=NONE` refuses engine-managed
upgrades; defaults and persisted-global overrides are disabled. The only TCP
listener is127.0.0.1:13306, with MySQL X disabled. Its initial resource profile
uses24connections and a128MiB InnoDB buffer pool; combined gameplay memory and
Thor thermals remain unmeasured.

Readiness requires authenticated SQL matching the pinned version, UUID, datadir,
listener, application account and all four schema names. The SQL `@@pid_file`
and the private pid-file bytes must identify this exact owned engine. A setup
receipt, open port or stale ready file cannot establish readiness. Each new
operation uses a fresh private session; the Android adapter also requires its
owned helper to remain alive before and after reading the result.

One guest service lock spans the entire engine lifetime. Bootstrap/configuration
locks are released after the startup snapshot so account and realm provisioning
can run while SQL is available. On Android, the existing setup lease remains
held by the service handle, preventing a concurrent setup or another session.
The helper's private logs are bounded to64KiB and never export SQL-client error
text, credentials or arbitrary exception messages. The two bundled Python files
are source/hash bound; extra importable files in their generation are rejected.

The owner writes the fixed `shutdown` command through its bounded native stdin
pipe. The helper closes its SQL client, requests MySQL's normal SIGTERM shutdown
and requires exit0 before writing a stopped acknowledgment. A20-second engine
deadline fits the native owner's30-second stop budget; forced cleanup is always
an error requiring recovery. Owner EOF or a helper-only SIGTERM also attempts
orderly shutdown, but exits with failure so an interrupted session cannot be
reported as an explicit successful stop. Cancellation before engine launch
records `engineStarted=false` and does not claim an engine exit. SQL-client
cleanup errors cannot skip engine cleanup.

The fixed CLI uses `/work/state` and `/work/mysql-sessions/<operation-id>`;
Android retains that work directory across application/runtime updates. MySQL
performs its ordinary InnoDB crash recovery on the next matching-engine launch.
No failure path deletes a datadir, substitutes credentials or silently upgrades
the engine. Java helper/receipt operations stay off the UI thread.

Local guard tests cover actual bounded child output, graceful versus forced
shutdown, ownership locks, cancellation, deadline enforcement and cleanup
failures. The dedicated `mysql-service.yml` runs the exact CLI on native ARM64,
inside the pinned Ubuntu dependency image without external networking, against
fresh disposable state. It requires three live SQL/restart cycles, preserved
four-schema marker data and private identity, second-owner rejection, and command,
EOF and helper-only signal shutdown. Actual execution is pending the first run;
Android adapter execution is a separate follow-on gate. Neither result qualifies
game schema/module updates, character saves, bots or world gameplay.
