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
EOF and helper-only signal shutdown.

Native ARM64 execution passed in [run 41013380186](https://github.com/Russianranger/esteria_android/actions/runs/41013380186)
at integration `14b71f3357f31af5ef091003d50e90ef7b7ead61`, using MySQL
`8.0.46-0ubuntu0.24.04.4`. All 18 host guards and the three-cycle real-engine
fixture passed. The downloaded artifact `12958164479` contains only six evidence
files, with ZIP size 11,341 bytes and SHA-256
`f8f13f82b44c04df5a1463a0c871606ceca0261ee895173a45fe2e1d4f5b8cf9`.
Its source/runtime envelope and qualification receipt were independently read
back and their hashes matched. The earlier run also passed the engine fixture,
but failed evidence export because `sudo` removed the source revision variable;
the corrected workflow restores file ownership before binding that envelope.

The short-socket correction also passed the unchanged native three-cycle fixture
in [run 41015153591](https://github.com/Russianranger/esteria_android/actions/runs/41015153591)
at `2df6c813f60d1ab50874b092226ce0baac792ba9`. Its artifact `12958689902`
is 11,366 bytes, SHA-256
`c6c67df48907ef4609300a5de46c2cbdb1459f354938dadb76eb84eb2b5d0a66`;
downloaded source/runtime envelope and qualification hashes were verified.
This proves native service behavior after the path change. Android's translated
socket address still requires the separate emulator execution gate.

Android adapter execution is a separate follow-on gate. This result does not
qualify game schema/module updates, character saves, bots or world gameplay.
