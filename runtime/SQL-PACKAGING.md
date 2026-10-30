# Pinned server SQL and Lua packaging

`tools/manifest_server_content.py` inventories the exact server revision in
`sources.lock.json`. It reads Git objects, never modified/untracked working files,
and therefore works with sparse checkouts without accidentally collecting private
configuration or temporary files. It does not execute SQL, create a database, copy
scripts into a live runtime, or claim database/gameplay qualification.

The contract is reviewed against server
`f35f04d01689f034778e3474b3c820092f51e461` and Eluna
`58d7652138887783228b9727bd1fa4e08f00342b`. A changed server/Eluna revision or an
unreviewed adaptation patch fails explicitly so this model cannot silently drift
from the compiled updater. The three Eluna declaration/include patches and the
server-root attunement, grid-template and source-empty script-directory patches
are individually digest- and scope-checked. They do not alter SQL/Lua inputs,
`AC_MODULES_LIST` selection or updater ordering. The sixth patch explicitly changes
script-loader generation to omit directories with no collectable source inputs;
populated custom scripts remain selected. `sourceAdaptations`
records each reviewed scope and effect; unknown or moved patches fail explicitly.
Its `scriptRegistrationPolicyChanged` field distinguishes that CMake policy change
from the unrelated module SQL-selection flag. See the
[linkage audit](../patches/server/LINKAGE-AUDIT.md).
The attunement patch preserves historical display-only primary-stat behavior and
does not qualify that gameplay feature; see
[the semantic audit](../patches/server/ATTUNEMENT-API-AUDIT.md).

## Generate a manifest

```sh
python3 tools/manifest_server_content.py --server sources/server \
  --all-source-modules --output out/server-content.json
```

This streams SHA-256 over each selected SQL/config/Lua/notice file in bounded
128 KiB chunks and retains exact Git blob IDs, modes, lengths and source/patch
pins. Output publication never replaces previous evidence. A full source checkout
needs no network. For a partial clone, unavailable blobs fail before hashing unless
`--allow-source-fetch` explicitly enables a batched Git fetch during setup.
`--metadata-only` avoids payload hashing and retains exact source blob identities;
its output sets `contentSha256Complete=false` and is not a verified file package.

`--all-source-modules` models the current static source profile using the server's
`GetModuleSourceList` rule: immediate `modules/*` directories containing `src`.
It does **not** establish the enabled list inside an actual server binary and
records that unresolved comparison. Once the exact compiled module list has been
captured, pass a reviewed JSON array with `--modules-json <file>` instead. Keep
that input with the build receipt. A supplied array alone still does not qualify
the build or database.

The output is a reproducible inventory and execution-order description, not an SQL
runner. Package source paths intact under the configured `SourceDirectory`; the
server updater remains authoritative for applied filenames, hashes and states in
an existing database. Never use a fresh-database source manifest as an upgrade
plan for an existing character/account/bot database.

## Actual updater contract

| Stage | Source behavior |
| --- | --- |
| Base population | `DBUpdater::Populate` first runs `SHOW TABLES`. Only an empty database is populated. It enumerates immediate files ending exactly `.sql`, sorts full paths, and applies them sequentially. It does not recurse into base subdirectories. |
| Core include roots | The literal base `updates_include.sql` seeds directories/states. `$` resolves relative to that database's source root. Core databases use the server source root. Missing custom directories are skipped by the server and listed explicitly in the manifest. |
| Module discovery | For enabled module names, immediate directories under `modules/<name>/data/sql/` are selected when their name contains `auth`, `characters`, or `world`, respectively. Names are matched case-sensitively by substring. Recursion is bounded to depth 10. |
| Update identity | The updater compares **basenames**, not full paths. A duplicate basename anywhere in one database's discovered set aborts. The manifest reports duplicates and withholds its ordered plan. |
| Update order | All discovered SQL is sorted globally by basename. Released/archived entries run first. Pending/custom/module entries run second, again in basename order. Folder order is not application order. |
| Existing databases | The compiled updater consults `updates` and the live `updates_include` table, checks hashes and may reapply changed updates. The manifest describes fresh source discovery only. MySQL DDL is not transactionally rolled back by a generic wrapper. |
| Startup order | `worldserver` opens/populates/updates/prepares auth, characters, then world. `OnDatabasesLoading` subsequently invokes the playerbots module's separate loader. |
| `dbimport` | This tool handles auth, characters and world. `Updates.AllowedModules` defaults to the compiled list. It does **not** initialize the playerbots database. |
| Playerbots | Its source root is `modules/mod-playerbots`, base directory `data/sql/playerbots/base`, and includes are relative to that module root. Its database loader does not receive the compiled module list. |

The baseline source contains complete base directories: **22 auth**, **108
character**, **309 world**, and **29 playerbots** SQL files. The source-profile
inventory finds **52 modules**, **4,617 input files**, and respectively
**25 / 105 / 3,340 / 31** discovered updates for auth / characters / world /
playerbots. No duplicate update basenames were found in this exact profile.
These counts establish source inventory only; they do not prove a successful
MySQL import, custom content closure, or compatible live data.

The full content-hash pass read **742,445,314 bytes** across those 4,617 inputs,
plus four Eluna extension/license inputs. A second pass succeeded with source
fetching disabled. The recorded manifest SHA-256 is
`bc7ad42e71b8d2cbf8e90e5fe3a27be8db2bbea1e4873e1149e8184985bca136`
for the source lock with client `a3683cc` and both documented Eluna patches.
Its three blockers remain unresolved; hashing source inputs is not schema loading.

There is no selected external stock base-database download: the committed SQL is
the starting baseline. The original developer's complete deployed Esteria custom
DB/DBC/Lua/content set is not established by that fact. Preserve this distinction
when requesting missing inputs.

## Module SQL that is not automatically discovered

The initial profile has **535 SQL files outside updater discovery**. The manifest
records their owners and hashes under `sqlNotDiscoveredByUpdater`. Many are manual,
uninstall, diagnostic, optional, integration-original, or historical modpak inputs.
Some directories that appear plausible are also missed by the literal loader:
for example `mod-custom-server/data/sql/updates/pending_db_world` is below immediate
child `updates`, whose name does not contain `world`.

Do not concatenate or apply this exclusion set. Review each intended feature's
source/README and current base data; implement explicit, tested adaptations where
an actually required update is not reached. Preserve original SQL identities and
applied-state history rather than renaming blindly to resolve collisions.

One automatically discovered auth update,
`modules/mod-custom-server/data/sql/db-auth/u_custom_server_2026_09_03_public_realm.sql`,
changes the address of realm 1 named Esteria to a public host. Local provisioning
must set and authenticate the desired loopback realm **after** all core/module
updates, before starting the client. Configuring worldserver to bind loopback does
not change the auth database's advertised realm address.

## Lua and configuration boundaries

The manifest hashes each enabled module's immediate `conf/*.conf.dist`, matching
`modules/CMakeLists.txt`. These are templates, not active settings; stage the local
configuration overlays and retain private credentials separately.

Eluna's script path defaults to `lua_scripts` and is configurable with
`Eluna.ScriptPath`. It processes `.ext`, `.lua` and `.moon`; extensions execute
before scripts, with each group sorted by full path. Compiled Eluna support does
not automatically install every module's Lua folder.

The source profile contains 17 server-Lua candidates under
`mod-worgoblin-high-elf/lua_scripts` and three Eluna extension files. They are
inventoried at source paths, not activated. Client-addon Lua is deliberately not
misclassified as server code. The separate `mod-Faction-Free/lua` directory is
outside the selected source-module profile (it has no `src` directory); its legacy
installation instructions need independent review. Copying both variants may
install duplicate handlers. A runtime package still needs an explicit script
installation map, collision policy, matching client AIO inputs where required,
and real startup/behavior qualification. Missing deployed scripts remain a
content requirement; placeholders are not substitutes.

## Verification and remaining work

```sh
python3 -m unittest tests.test_server_content -v
```

Tests cover exact two-phase order, duplicate detection, depth 10, module path
matching, separate playerbots roots, strict literal include parsing, raw Git
content provenance despite local edits, symlink rejection and non-overwriting
manifest publication. They execute no SQL.

Next: compare with the exact compiled module list, package verified file bytes
with source paths/notices, review required excluded SQL and Lua mappings, then
run real MySQL schema loading using the compiled updater. Capture schema version,
prepared-statement validation, authenticated loopback realm state and the distinct
playerbots readiness result. Existing-save upgrades additionally require validated
backup/restore and an explicit version transition; never reseed live saves.

## Bind module selection to the built artifacts

```sh
python3 tools/manifest_server_modules.py \
  --compile-commands out/server/compile_commands.json \
  --install out/server-install --server-build out/server-install/server-build.json \
  --output out/server-modules.json
```

The extractor streams the CMake compile database with bounded entries and never
executes compiler commands. It requires matching `AC_MODULES_LIST` and
`CONFIG_FILE_LIST` definitions for the actual worldserver/dbimport `Main.cpp`
translation units. It then hashes the installed executables against the existing
ARM64 build receipt and finds the exact terminated module string in **both**
binaries. Worldserver also must contain the config-list literal it consumes;
dbimport does not consume that macro, so an optimized-away config string is not
required there. Duplicate, mismatched or missing definitions fail explicitly.

Only the C string's trailing NUL is required. A compiler may pool suffixes or
place nonzero read-only data immediately before it. Binary string presence is a
consistency check alongside generated compile options and the source-verified,
hash-matched build receipt; it is not standalone reverse-engineering evidence.

The resulting receipt identifies the compile database, server build receipt,
source lock and exact binary bytes. It establishes the built module selection,
not successful module startup. The server CI workflow records the compile database,
runs this check after binary verification, and uses the resulting module names
for the content inventory and package. A source-profile package without this
receipt remains marked `moduleSelectionVerified=false`.

## Reproducible content archive

```sh
python3 tools/package_server_content.py --server sources/server \
  --manifest out/server-content-manifest.json --module-receipt out/server-modules.json \
  --lua-map runtime/server-lua-map.json --output out/server-content
```

The input must be a full SHA-256 inventory matching the current source lock. The
packager reconstructs discovery from exact Git objects and rejects altered file
sets, identities, update order or duplicate/depth-limited SQL. It fetches nothing.
Selected payload bytes stream from Git and must match the inventory before they
can enter the archive. A second pass reads every archive member and verifies its
hash, regular-file type, length and fixed metadata. Failed attempts leave existing
packages untouched. On Linux, `renameat2(RENAME_NOREPLACE)` publishes a complete
new output directory atomically; there is no weaker overwrite fallback.

The directory contains `server-content.tar.gz` and `package-receipt.json`:

- `source/` preserves exact base/update/config/notice source paths for the updater.
  Config files remain `.conf.dist` templates; no private settings are packaged.
- Excluded/manual SQL is retained only as identities and review decisions inside
  `metadata/content-manifest.json`. It is absent from executable SQL payload paths.
- `lua_scripts/` contains only explicitly mapped, dependency-cleared script files.
  An unmapped source candidate is never activated by a broad directory copy.
- `metadata/` retains the content/module/Lua receipts and package plan, including
  the post-update local-realm verification gate and unresolved gameplay gates.

The archive uses GNU tar format, including GNU long-name records when required;
it does not emit PAX extended headers. This matches the bounded importer format,
but actual installation of this content package on Android remains untested.
Archive entries are sorted; owner/group, timestamps, modes and gzip timestamp are
fixed. Tests produce identical archive bytes from repeated inputs. The receipt
records Python/zlib versions and packaging-tool hashes, so reproducibility is
scoped to the recorded producer inputs. The package contains **no initialized
database**, binaries, account credentials, game maps or client assets. Every
schema/gameplay/Android qualification flag remains false until real qualification.

## Explicit initial Lua policy and source findings

`runtime/server-lua-map.json` records an identity-bound decision for all 20 source
candidates (17 module scripts and three Eluna extensions). The initial SQL/runtime
bring-up policy is explicitly **disabled**, and its package requires
`Eluna.Enabled=false`. This is an intermediate setup profile; the full Esteria Lua
objective remains active. It must not be presented as a complete feature package.

A mapped policy must account for every candidate, preserve file hashes, reject
unsafe paths and case-insensitive destination collisions, and have no outstanding
dependencies on any activated file. Mapped files are not themselves runtime
qualification; the package continues to report `luaRuntimeQualified=false`.

| Source group | Actual dependency or behavior |
| --- | --- |
| `AIO_Server/AIO.lua` and its nine dependency scripts | The source declares AIO **1.75** and explicitly requires the same client version/file. No matching client AIO package is established by the selected module tree. Preserve the relative library paths when eventually mapping them. |
| `transmog.lua` | Registers AIO `Transmog` handlers and uses account/character persistence tables (`account_transmog`, removed appearances, `character_transmog`, weapon enchants), plus world appearance/item queries. Matching AIO client UI, schema readiness and custom appearance closure are required. It is not a cosmetic optional example to omit silently. |
| `racials.lua`, `teach_riding_worgen.lua` | Register Worgen race 12 riding/spell/login/level handlers. They need matching race/spell DBC behavior and tests; both scripts are intentional source inputs, not interchangeable duplicates. |
| `FactionFreeTeleports_Gnome.lua`, `FactionFreeTeleports_Goblin.lua` | Bind NPC IDs **600001/600000**, respectively. Matching NPC/gossip data and valid map destinations must be verified. Do not install a second copy from the legacy Faction Free module. |
| `open-azeroth/continent_bridge.lua` | Source assumptions explicitly require extended ocean terrain and flight on maps **0, 1 and 571**. Its 500 ms scan teleports across custom coordinate thresholds; stock-map presence alone does not satisfy this requirement. |
| `chat_probe.lua` | Comment-only unused placeholder. Do not count it as functioning diagnostics or gameplay. |
| Eluna `.ext` files | Framework extensions are available but held with the disabled policy. When enabled, retain the engine's extensions-before-scripts ordering and actual relative paths. |

The module README is historical installation guidance, not proof that the current
client archive stack or deployed Lua set is complete. The packager does not fetch
CDN content, fabricate missing client code, patch signatures, or activate scripts
with unmet data dependencies.

Additional focused checks:

```sh
python3 -m unittest tests.test_server_modules tests.test_server_package -v
```

They cover command parsing/stream bounds, actual binary hash/literal checks,
selection mismatches, deterministic archives, notice preservation, exclusion of
manual SQL, explicit Lua decisions, failed-hash rollback and atomic no-replace
publication. Actual compiled-module evidence still awaits a completed server build.

The GNU-format source-profile package was generated entirely offline with the
three reviewed Eluna patches: **4,060 archive entries / 654,046,522 uncompressed
bytes**, compressed to **167,542,391 bytes**, SHA-256
`4df26d28f4c367a3d17706006e37e9d780133c986760c58f0958afbebd16276d`.
Every archived payload was read back and checked. Its receipt explicitly leaves
compiled-module selection unverified and Lua disabled; it is a packaging result,
not a successfully initialized server or Android candidate.

## Disposable base-schema qualification

`tools/qualify_base_sql.py` separates host source preparation from engine execution:

```sh
python3 tools/qualify_base_sql.py prepare --server sources/server \
  --output out/base-sql-fixture
python3 tools/qualify_base_sql.py qualify --fixture /fixture \
  --fixture-sha256 EXACT_PREPARED_MANIFEST_SHA256 \
  --mysql /usr/bin/mysql --mysqld /usr/sbin/mysqld \
  --expected-version EXACT_PINNED_MYSQL_VERSION --output /state/new-fixture
```

Preparation reads exact Git objects for the pinned server, validates the individually reviewed
C++ patch scopes/digests, and records SHA-256 plus Git blob identities for **468 base
files / 381,481,395 bytes**. The counts are 22 auth, 108 characters, 309 world and
29 playerbots. Only immediate `.sql` files are selected, sorted exactly as the
base-population phase does. Local modified/untracked files never become inputs.
The prepared fixture can be mounted read-only into the server dependency image;
Git and build tools are not needed inside that runtime.

Qualification requires a completely new private output directory. It rechecks
the manifest digest, current source lock, safe paths, exact file counts and both
content identities before starting MySQL. An existing output, partial fixture or
save directory is preserved and rejected. It initializes its own authenticated
MySQL instance, verifies all four application databases are empty before the first
SQL file, and stops on the first SQL failure. After import it checks exact table
sets, writes disposable persistence markers, shuts down cleanly, restarts and
checks every table and marker again. A failed attempt is retained for inspection
and cannot be resumed by replaying bases.

The base SQL is a real intermediate compatibility check: upstream snapshots were
produced with MySQL 8.4.3, while the pinned dependency image currently provides
MySQL 8.0.46. Successful import must be observed; file presence alone is not
compatibility evidence. The `.github/workflows/base-sql.yml` job runs this test in
a native ARM64 container with external networking disabled. It exports only
receipts and bounded redacted diagnostics. Private credentials, option files,
initialized databases and SQL payloads are excluded from CI uploads.

The locally prepared fixture's manifest SHA-256 is
`dfb5b9a05f5a59e94efecff53e9e8f0bfbc50d46d30821d18429ff4d645739f1`.
Every staged SQL file was independently read back and verified against both
identities. This is source preparation evidence; actual MySQL base qualification
is reported by the dedicated workflow's receipt, not inferred from these hashes.

`qualification.json` deliberately retains `compiledUpdaterExecuted=false`,
`moduleUpdatesApplied=false`, `playerbotsRuntimeQualified=false`,
`databaseUpgradeQualified=false`, `gameSchemasQualified=false` and
`gameplayQualified=false`. Base import and disposable marker persistence do not
establish prepared-statement compatibility, applied module schemas, character
saving, bots or a valid deployed content set.

## Actual updater boundary and saved-state protection

**The pinned `dbimport --dry-run` is mutating. Never use it as a read-only preview
against saved games or a live database.** In `src/tools/dbimport/Main.cpp`, the
flag merely sets `sConfigMgr->setDryRun(true)`. `DBUpdater::ApplyFile` still invokes
the external MySQL client with the SQL file; dry-run suppresses prompts and normal
SQL-error throwing so processing can continue. The process reports the accumulated
failed-update count at exit. Likewise, dbimport's advertised `--version` does not
have an early-exit branch; use only the audited loader-smoke commands.

The actual `DatabaseLoader::Load()` order is open all registered pools, populate
all eligible empty databases, update all registered databases, then prepare SQL
statements. dbimport registers auth, characters and world in that order. Compiled
`AC_MODULES_LIST` controls allowed auto-discovered module SQL, and the populated
`updates` / `updates_include` tables govern the update ledger. A sorted list of
all historical SQL is not a valid existing-database migration plan.

Playerbots is a distinct loader invoked by the module's world-server
`OnDatabasesLoading()` hook. dbimport does not register that pool. Loading its 29
base files in the disposable test does not qualify this runtime hook or its update
ledger. The full updater test must exercise the actual compiled module and confirm
its prepared statements and persistent bot state.

For saved-state upgrades, first stop and verify ownership of all writers, produce
a verified backup, restore it into a separate staging instance, and run the exact
compiled updater there with recorded source/module/configuration identities.
Only an explicitly qualified version transition may later promote a staged copy;
failed imports and migrations must preserve the previous generation. No live-save
upgrade or promotion mechanism is enabled by this base-only tool. Reassert and
verify the authenticated loopback realm only after all core, module and playerbots
updates have completed, because module SQL can rewrite the endpoint.

Focused guard checks:

```sh
python3 -m unittest tests.test_base_sql -v
```

## Measured native ARM64 base result

[Base SQL run 40991449039](https://github.com/Russianranger/esteria_android/actions/runs/40991449039)
at integration `57b635e0abaf59c5a59becfca2a064640d8185fe` passed the real import and
clean restart test against **MySQL 8.0.46-0ubuntu0.24.04.4**. All 468 source files
completed; the exact expected table sets were auth 22, characters 108, world 309
and playerbots 29. Every disposable persistence marker survived restart. The
container had external networking disabled throughout initialization/import/restart.

Artifact `12949681239` was downloaded and its ZIP SHA-256 verified as
`15a98a60a52030d66b969a481ece84732273f2f7768e2328502823c9e1de1c96`.
The qualification receipt SHA-256 is
`b3ec7962d19bfe816a36e83b9d89a8362d5350f49e7e7ebe50d5e139246f2c03`;
the measured runtime manifest SHA-256 is
`3aa480f48fd36cea1253557976163dc2da0707eef72dbef18d028196888b05b1`.
This establishes base SQL compatibility on native ARM64 Linux, not complete game
schemas or Android execution. The base fixture for this run is bound to its exact
integration source lock; its manifest SHA differs from the earlier local staging
record because the pinned client revision advanced before publication.

## Compiled updater qualification

`tools/qualify_dbimport.py` is the subsequent disposable qualification. The server
workflow invokes it only after the actual ARM64 build, installed artifact check,
compiled-module receipt and source-content package complete successfully. It runs
inside the same pinned dependency image with external networking disabled.

```sh
python3 tools/qualify_dbimport.py \
  --install /qualification/out/server-install \
  --content /qualification/out/server-content \
  --content-receipt-sha256 EXACT_PACKAGE_RECEIPT_SHA256 \
  --mysql /usr/bin/mysql --mysqld /usr/sbin/mysqld \
  --expected-version EXACT_PINNED_MYSQL_VERSION --output /state/new-fixture
```

The tool requires a completely new private fixture. It verifies the external
package-receipt digest, archive digest, every archive member, source-selection
manifest and compiled module list before initializing MySQL. Archive extraction
uses the bounded GNU reader, accepts only the expected regular files, and excludes
manual SQL. Every installed ELF and the selected installed `dbimport.conf.dist`
template must match the exact server-build receipt; that receipt must match the
compiled-module proof and current source lock.

The actual dbimport executable performs base population, source-ledger updates,
auto-discovered module SQL and prepared-statement setup. The harness does not
manually replay these SQL files. It supplies loopback-only private configuration,
uses no inherited database environment overrides, never passes `--dry-run` or
`--version`, and treats a nonzero exit as a preserved failed fixture. Owned process
groups and bounded private logs cover the updater's external MySQL subprocesses.

After successful first import it checks every selected auth/character/world update
name and state, plus SHA-1 hashes for non-archived entries. The archived hash skip
matches the audited upstream default; it is not full archived-file revalidation.
It inserts disposable markers, reruns the same revision, requires unchanged table
sets and update ledgers, then checks markers and ledgers again after clean MySQL
restart. This is same-revision reentry evidence, never an upgrade to user saves.

The exact realmlist schema and loopback row are checked/reasserted after this
three-database updater has completed. This is only a fixture component check: the
final application gate remains false until all services, including the distinct
playerbots loader, complete their updates and the authenticated endpoint is checked
again. The harness verifies that playerbots stays empty because dbimport does not
register it. It does not start auth/world servers, activate Lua, create characters
or claim a complete schema/content set.

Only receipts and bounded redacted engine/updater logs are uploaded. Private
credentials, configuration, SQL copies and initialized databases remain outside
artifacts. The tool and focused guards are implemented; successful compiled-updater
execution remains pending the real server build and qualification run.

```sh
python3 -m unittest tests.test_dbimport_qualification -v
```
