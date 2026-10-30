# Playerbots database loader qualification

The server's standalone `dbimport` registers auth, characters and world only.
Playerbots is a fourth pool registered by
`modules/mod-playerbots/src/Script/Playerbots.cpp::OnDatabasesLoading`. A passed
core updater therefore does not establish playerbots database readiness.

The isolated `esteria_playerbots_database_reference` calls that exact loader
sequence against the pinned server's real `database` and `common` targets. It
does not copy or replace the loader, connection, updater or prepared statements.
The database target must already have the selected module's `-DMOD_PLAYERBOTS`
definition; the reference refuses configuration otherwise. It loads its main
configuration and sibling `modules/playerbots.conf` through actual `ConfigMgr`,
requiring reviewed source adaptation 0007. No game scripts or bot AI are linked
into this reference. It closes the pool before ending the MySQL client library.

At server `f35f04d01689f034778e3474b3c820092f51e461`, the playerbots database plan
contains 29 base files and 31 released updates (73,695,906 source bytes). Its
loader has an empty extra-module list and `DBUpdater` selects the module's own
`data/sql/playerbots/base` and `updates_include` paths. The registered database
uses update bit 8; `SetUpdateFlags` adds that bit to the configured mask. Its
source declares 52 prepared statements. These are source facts, not execution
results. No external SQL or arbitrary glob order is substituted.

`verify_playerbots_reference.py` binds the helper ELF/hash to the source-verified
server build, exact compiled-module receipt and same compile-command inventory.
It checks the real loader/updater/playerbots-connection translation units and
reference command all carry the module definition, checks reference source
bytes against the integration revision, and records ELF dependencies without
executing it. The helper remains a CI qualification artifact and is not added
to the application runtime.

`qualify_playerbots_database.py` first verifies that receipt's independently
provided SHA-256. The existing compiled importer/auth harness is the sole
creator of a new disposable instance; a previous output or game save is never
adopted. After successful real auth qualification, it requires the fourth schema
to be empty and executes the real loader. It checks every released SQL filename,
SHA-1 and state against the content manifest, rejects extra ledger entries, and
requires the source-controlled completion after statement preparation and pool
shutdown. A second load must retain the same tables, ledger and a disposable
InnoDB marker. A clean MySQL restart must retain them again. Core table sets,
update ledgers, importer markers, all account columns including the authenticated
session key, realm trackers and private account journal are compared without
publishing their contents. Account columns use `HEX` in the private line-based
comparison, preserving arbitrary binary salt/verifier/session bytes.

The local realm is reasserted after this last database loader. This is not the
final application world-startup gate: other module hooks and actual world entry
still require qualification. Source upgrade behavior, playerbot character
creation, AI, saved-world persistence, Android execution and gameplay remain
explicitly false. The helper emits only a database qualification receipt;
private SQL diagnostics stay in the disposable fixture.

Eleven focused host guards pass, including exact compile-source selection,
module definitions, receipt rejection before database creation, real pinned
configuration-key rendering, exact ledger checks, binary-safe private account
comparison, existing-state preservation and completion-marker checks. Adaptation 0007 is now selected. The native server workflow builds this reference
from the actual database target, verifies its provenance after installed binaries
are checked, and executes the fresh updater/auth/playerbots composition inside the
pinned MySQL runtime with external networking disabled. It also gates all selected
world module configurations through real ConfigMgr before SQL qualification.
Public evidence includes the reference receipt and database qualification receipt;
raw playerbots SQL logs and database contents remain private. Native ARM64 build
`41041859706.1` now links this exact reference and passes its real database-source,
definition and compiled-module binding checks. Its public receipt identifies the
25,183,072-byte reference as SHA-256
`cbc7c5dc1b418e835b7778b73e5015284cf943b15e2b9fe2234db74aae230b07`;
its build-only receipt explicitly keeps `databaseExecuted` false. The same run
passes actual ConfigMgr parsing/reload of all 50 selected module configurations,
then fails the earlier snapshot's SQL/auth composition before playerbots database
execution. See `runtime/evidence/server-module-configurations-41041859706.json`.
Actual fourth-schema execution, prepared statements, reentry/persistence and bot
AI remain unqualified.
