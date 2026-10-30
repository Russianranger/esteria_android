# Local server integration contract

This is a source-verified setup contract and host-tested configuration renderer.
It is not an installed or qualified Android runtime. No database has been initialized.

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
3. Initialize a new database in staged storage with MySQL 8's supported procedure;
   provision the persistent local `esteria` user and privileges for `acore_auth`,
   `acore_world`, `acore_characters`, `acore_playerbots`. Secure root before opening
   normal TCP service. Never rerun initialization over an existing data directory.
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

## Evidence

`tools/verify_protocol.py --client sources/client --server sources/server` compares
all 215 generated player descriptors against the actual server offsets and sizes.
At the starting pins, 25 quests / 254 bag slots / one class-mask word pass:
player 1326 dwords, container 574 dwords, update masks 42. One explicit spelling
alias covers upstream `HONORBALE` versus server `HONORABLE`; no field is silently
ignored. Server `MAX_CLASSES=12` denotes its stock playable range; the client's 32
is mask capacity, not 32 implemented classes. This is layout evidence, not login,
appearance transport, custom-race, inventory, or persistence qualification.
