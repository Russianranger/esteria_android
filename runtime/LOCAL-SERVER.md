# Local server integration contract

This is a source-verified setup contract, host-tested configuration renderer and
database bootstrap implementation. It is not an installed or qualified Android
runtime. Real MySQL behavior has a dedicated CI test; check that run before claiming
engine qualification. No game schemas or player accounts are populated by bootstrap.

## Pinned foundation

- EsteriaWoW `f35f04d01689f034778e3474b3c820092f51e461`; source stays unchanged.
- Eluna gitlink `58d7652138887783228b9727bd1fa4e08f00342b`.
- Lua 5.2.4 is selected explicitly; upstream `deps/lualib/lua/CMakeLists.txt`
  checks tarball SHA-256 `b9e2e4aad6789b3b63a056d442f7b39f0ecfca3ae0f1fc0ae4e9614401b69f4b`.
- Current source recognizes Linux ARM64 and SFMT NEON. Android Bionic compilation
  and PRoot execution remain separate, unqualified work.
- Use MySQL 8 for the first reference build. Current server requires client library
  version >=80000 and an exact runtime/header version match. Its server version
  parser rejects MariaDB 10.x; MariaDB is not an interchangeable dependency.

## Configuration and storage

`tools/render_server_config.py --server sources/server --state-root /esteria/state
--data-root /esteria/data --sql-source /esteria/source --mysql-client /usr/bin/mysql`
executes inside the runtime namespace. Pass actual mount paths as single arguments.
The state root must be private to this installation and shared by no other session.

The renderer writes persistent credentials to `state/accounts/database-secret`
(mode 0600), data to `state/database`, logs to `state/logs`, and versioned
configurations under `state/config/generations`. `state/config/current` changes
atomically only after all templates have rendered. Rerendering preserves credentials
and never clears databases. The runtime must exclude config/accounts/database from
support bundles. Private config uses semicolon-separated AzerothCore connection
strings; redact these as well as ordinary password/token fields.

Auth binds `127.0.0.1:3724`, world `127.0.0.1:8085`, MySQL `127.0.0.1:13306`.
RA and SOAP are off. `TempDir` is separate per auth/world process because the
upstream SQL updater uses a fixed `mysql_ac.conf` temporary filename. Set process
umask 0077. Keep working directories separate too: database creation uses a fixed
`create_table.sql` filename.

The initial bot profile enables controlled account bots with a four-bot ceiling,
no random auto-login and no random/addclass account-pool generation. It does not
create or qualify four bots automatically. The desktop defaults are 500 random
bots plus 50 addclass accounts; they must not become the device defaults. Existing
bot characters are not deleted by this configuration. Device memory/thermal
measurements are required before raising the ceiling.

## Required runtime packaging and bootstrap work

1. Package native Linux ARM64 authserver, worldserver, dbimport, required shared
   libraries, MySQL 8 server/client, Lua, module configs and notices in a pinned
   runtime. The Android APK must provide the executable PRoot entrypoint from its
   native library directory; writable app storage alone is not a valid Android
   executable installation strategy.
2. Package the complete matching `data/sql/base`, `data/sql/updates`, required
   module SQL and Lua paths beneath `SourceDirectory`. The compiled updater reads
   these local paths. `DBUpdater<PlayerbotsDatabaseConnection>` specifically reads
   `modules/mod-playerbots/data/sql/playerbots/base`. `cmake --install` alone does
   not establish this complete content package.
3. Use `runtime/mysql_bootstrap.py` to initialize a new staged MySQL 8 instance,
   secure root before TCP service, and provision the persistent local `esteria`
   account for four empty databases. See the command contract below. Dedicated CI
   exercises both fresh engine initialization and provisioning against a separately
   started MySQL service. Check completed CI results for actual qualification.
4. Execute schema initialization/update through the compiled updater with
   `AC_DISABLE_INTERACTIVE=1`; check exit and prepared-statement validation.
   Back up persistent databases before schema upgrades and record successful source
   revision. MySQL DDL is not made atomic by a transaction wrapper.
5. Provision local realm address/port/build 12340 and a local player account. Then
   qualify actual auth/realm/world responses, character save and relog, and four
   controlled account bots. Port availability by itself is not the acceptance test.
6. Start database, validate a SQL query, complete migrations, then auth/world,
   then client. Stop client/world/auth before MySQL. World installs SIGINT/SIGTERM
   handlers and its network teardown kicks/saves characters, but real shutdown and
   recovery must be tested before claiming persistence.

## Database bootstrap command contract

Run under the installation owner with umask 0077, after rendering configuration.
The Python 3 standard-library script is intended for the eventual glibc runtime;
Python, MySQL and that runtime are not yet packaged by the application. The example
pin below is the exact version used by `.github/workflows/database.yml`; a runtime
release must pin its MySQL binary and libraries separately too.
Distribution suffixes are supported and must be pinned verbatim, for example
`8.0.44-0ubuntu0.24.04.2`; bootstrap never strips them or compares only a prefix.

```sh
python3 runtime/mysql_bootstrap.py initialize \
  --state-root /esteria/state --mysql /usr/bin/mysql --mysqld /usr/sbin/mysqld \
  --expected-version 8.0.44
```

Initialization uses an installation-specific staging directory and a private Unix
socket with TCP disabled. The server executable version, live SQL version/UUID and
SQL datadir must agree with the owned staging instance before credentials change.
Root credentials persist privately in `state/accounts/database-root-secret`; the
application account uses the renderer's existing `database-secret`. Passwords are
passed through mode-0600 temporary option files or SQL stdin, never argv or logs.
Bootstrap creates only `acore_auth`, `acore_world`, `acore_characters`, and
`acore_playerbots`, with local-only `esteria` accounts and per-database grants.
It imports no tables, realm, player accounts or bot accounts.

After a clean stop, staging is atomically renamed to `state/database`; an atomic
receipt records engine version, UUID, absolute datadir and the four database names. An interrupted
rename can finish its receipt only when the owned journal, staged receipt and
promoted datadir UUID agree. Interrupted `--initialize`, unowned nonempty datadirs,
unidentified sockets/PIDs, version changes and credential mismatches fail closed
and preserve storage for recovery. Do not remove these safeguards to retry.
Initialized staging can resume without calling `--initialize` again.

Start MySQL under the process supervisor using the rendered `mysql.cnf`, which
binds exclusively to `127.0.0.1:13306`. Then run:

```sh
python3 runtime/mysql_bootstrap.py verify \
  --state-root /esteria/state --mysql /usr/bin/mysql --expected-version 8.0.44
```

`verify` authenticates as the persistent application account, matches the stored
instance/version, verifies the loopback listener, and executes SQL in all four
databases. A completed initialization receipt alone never reports SQL readiness.
For a dedicated externally started empty instance, `provision --admin-options
/private/admin.cnf` uses the same rules, plus a server-side advisory lock. It
refuses to adopt preexisting Esteria databases/accounts without its own pending
receipt. The CLI's filesystem lock also serializes operations for one installation.

Host tests cover filesystem ownership, credentials, serialization and interrupted
promotion. A separate CI job installs Ubuntu's current MySQL 8 package, records the
full binary version/package versions, and exercises fresh initialization, private
SQL bootstrap, clean stop, promotion, reconstructed promotion-interruption recovery,
TCP readiness and marker-table persistence over two starts. This is host diagnostics
against recorded runner packages, not a reproducibly packaged runtime dependency.
The dedicated runner's system MySQL is stopped and its AppArmor profile unloaded
for the test's private temporary datadir; this is not an Android deployment step.

The explicit upstream MySQL 8.0.44 service test covers real authentication, empty DB
creation, interrupted pre-DDL ownership, repeat provisioning, lock rejection,
version/UUID/credential failure and preservation of a marker table. It runs only
when `ESTERIA_MYSQL_INTEGRATION=1`, with a disposable loopback instance. Ordinary
unit discovery reports both engine tests as skipped. Neither job qualifies Android
execution, application schemas, backups/upgrades, world-server persistence or
character saving.

## Evidence

`tools/verify_protocol.py --client sources/client --server sources/server` compares
all 215 generated player descriptors against the actual server offsets and sizes.
At the starting pins, 25 quests / 254 bag slots / one class-mask word pass:
player 1326 dwords, container 574 dwords, update masks 42. One explicit spelling
alias covers upstream `HONORBALE` versus server `HONORABLE`; no field is silently
ignored. Server `MAX_CLASSES=12` denotes its stock playable range; the client's 32
is mask capacity, not 32 implemented classes. This is layout evidence, not login,
appearance transport, custom-race, inventory, or persistence qualification.

## Schema qualification and the mutating dbimport preview flag

**Do not run the pinned `dbimport --dry-run` against live state as a preview: it
executes SQL.** Its flag changes prompting and SQL-error handling, while
`DBUpdater::ApplyFile` still runs the MySQL client. Its advertised `--version`
also lacks an early return. Use only source-audited process-smoke commands.

`tools/qualify_base_sql.py` and the `base-sql.yml` workflow provide an intermediate
fresh-base test using the pinned native ARM64 dependency image. Source preparation
stages 468 exact Git SQL files, then the engine-side command verifies their hashes
before creating a new private disposable MySQL instance. Existing or partial
output directories are rejected and preserved. The test checks all four databases
are empty before import, verifies exact table sets, and checks disposable markers
after a clean restart. It does not accept the application's live database path.
Only redacted bounded diagnostics and receipts may be exported; never upload its
private state or credentials.

This test does not run the compiled updater, apply module updates, prepare server
statements or qualify a saved-game upgrade. dbimport registers only auth,
characters and world; the playerbots loader runs from a world-server module hook.
Their real update ledgers and all post-update loopback realm checks remain required
before game launch. Existing saves require a verified backup/restore and a staged,
qualified version transition; base SQL must never be replayed over them. See
[SQL-PACKAGING.md](SQL-PACKAGING.md) for exact source behavior, commands and gates.
