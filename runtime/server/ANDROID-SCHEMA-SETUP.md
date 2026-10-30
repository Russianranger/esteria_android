# Android source baseline adapter

`ServerSchemaSetup.prepare` now joins the separately installed immutable server
programs, content and Ubuntu dependencies to an already running
`ServerDatabaseService.Handle`. It performs no database engine startup or shutdown.
The handle retains the same Android file lease and runtime generation throughout
setup; service shutdown requests cancellation and waits only its caller's deadline.
If an executing SQL file has not finished by then, shutdown explicitly fails
and retains the live process/lease; its owner retries after the safe boundary.
New schema work is rejected once shutdown has been requested.
A dead service or changed instance is an error, including after helper completion.

The adapter mounts only the fixed `/esteria-server-programs` and
`/esteria-server-content` locations. It copies the exact externally pinned content
receipt and public source/module selection into a fresh private operation folder.
The guest's standard-library verifier reads every selected content file, without
Git or Docker. Before SQL and between files, it authenticates the live service's
version, UUID, datadir, loopback endpoint, application user and owned PID-file path.
Database credentials stay in private option files, outside arguments, environment
and public diagnostics.

`android_server_schema_setup.py` calls the existing source-derived appearance and
original source baseline algorithm. A persistent schema journal records intent
before auto-committing DDL. Completed reentry does not replay SQL; partial/in-flight
setup is preserved and refused. Cancellation before the first durable file intent
is retryable. Once intent is durable, that file finishes even if cancellation
arrives during the journal write or started-progress callback. Cancellation
between completed files currently preserves a partial fresh baseline and refuses
reentry; automatic fresh-setup recovery/promotion is not implemented. This
limitation must be resolved before exposing first-run cancellation in a playable
application. Existing credentials, account intent and database
identity remain bound to the journal. This is the original baseline plus the two
explicit empty appearance tables; canonical updater ledgers remain unchanged.

SQL input streams directly from the immutable file into a MySQL child. No archive
or SQL file is loaded in memory wholesale. Each child's private output is capped
at 1 MiB and execution at five minutes. Cancellation before SQL is immediate;
cancellation after a file starts waits for that file to finish. Forced termination
or errors preserve the in-flight journal and private diagnostics. Setup never
reports successful save/recovery from forced termination.

Nine APK helper resources include the exact nested appearance SQL/audit files.
`GuestHelperAssets` accepts only declared resource directories and rejects extra
Python modules, caches, linked directories and foreign files. Interrupted private
helper writes remain available and matching completed files are reused.

Host evidence is in `runtime/evidence/android-schema-adapter-host.json`: eight
entrypoint tests include actual child-process streaming, bounded diagnostics,
secret-free launch arguments/environment, cancellation and foreign service
identity checks. The existing schema-journal suite now passes fourteen tests, including a real
atomic-journal-write cancellation race. A concurrent host guard test verifies
bounded shutdown, cancellation visibility and retry after a simulated SQL file
finishes, without terminating the retained operation. Core fixed-mount
checks, Android application/test Java compilation, lint and APK assembly pass;
the APK's nine helper files match the original source bytes. Three new Android
helper filesystem tests compile and are required by the existing installer
emulator workflow; their actual Android result remains pending.

This does **not** qualify actual Android SQL execution, the compiled updater,
account/realm setup, auth/world servers, character saves or gameplay. The default
APK contains the helper sources without server programs/content. Activating
`MainActivity` START remains a separate matched-runtime qualification gate.
The next integration phase must run the pinned compiled updater on the same owned
engine, verify schemas/module updates, then provision the local realm/account.
