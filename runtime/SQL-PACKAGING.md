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
from the compiled updater. The current three Eluna declaration/include patches are
recorded and do not alter SQL discovery or Lua ordering.

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
