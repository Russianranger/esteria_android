# Disposable database backup and restore qualification

`tools/qualify_mysql_backup.py` tests logical backups of all four game databases
with the exact ARM64 MySQL tools from the pinned dependency image. It cannot
attach to an existing installation or accept an external SQL dump. Its output
directory must not exist. This is a qualification harness, not an application
backup feature, save migration implementation, or Android execution claim.

The source is created solely by `qualify_base_sql.run`: authenticated bootstrap,
468 hash/Git-verified source files, exact table sets, and a clean restart. The
harness then provisions the owned local account and loopback realm, and adds
explicit disposable probes containing binary bytes, UTF-8 text, empty strings
and SQL NULL in each database. These probes are not characters or bots.
Before provisioning, the separately hashed account fixture supplies the exact
server configuration templates. Its complete provenance is checked, and the
existing renderer creates the active private configuration while preserving the
database secret already created by bootstrap. No account SQL is replayed from
that second fixture.

Only the harness's own engine runs. An authenticated root socket connection must
match the bootstrap UUID/datadir/version before taking a global read lock.
`mysqldump` streams SQL directly to a new private file, bounded to 4 GiB and
15 minutes, with a separately drained 64-KiB private error tail. It dumps only
`acore_auth`, `acore_characters`, `acore_world`, and `acore_playerbots`; MySQL
system accounts and instance identity are excluded. Binary values use hex;
routines, events and triggers are included explicitly. No password appears in
argv, environment, public logs or receipts.

MySQL's [official 8.0 mysqldump documentation](https://dev.mysql.com/doc/refman/8.0/en/mysqldump.html)
describes the snapshot and object-selection options. A transactional snapshot
alone does not protect nontransactional tables or concurrent schema changes, so
this isolated test retains `FLUSH TABLES WITH READ LOCK` throughout export.
All writers are owned by this fixture; this is not evidence of application-wide
writer quiescence or a hot backup of a running game.

A successful dump is fsynced, hashed and published without replacing any name.
Failed/partial dumps remain private and cannot become completed backups. The
source is stopped cleanly before a second instance is initialized with separate
database credentials and a distinct UUID. Before restore, the dump digest and
all four empty destination schemas are checked. Existing or partial restores
are preserved, never overwritten or automatically retried.

Fresh destination initialization calls the exact `android_database_setup.setup`
wrapper, then repeats it before starting a live engine. Both private credentials,
the bootstrap receipt and UUID must remain identical on the repeated call.
This is native Linux validation of the packaged Python entry point; Android
execution and the Java adapter remain separate gates.

The restored instance must preserve the original account salt/verifier and
realm-character trackers, all probe values and table sets. A full canonical
dump must match every SQL byte, both immediately and after a clean restart.
The original instance is restarted separately to verify that its account,
credential journal and probes remain unchanged. The account journal is bound
to the original UUID and is deliberately not rebound or copied into the new
instance. A future production recovery flow must implement and qualify that
ownership transfer explicitly.

## Exact tool evidence

`mysql-backup-tools.lock.json` pins the runtime source lock, MySQL package
identity, and the actual ARM64 ELF hashes of `mysql`, `mysqld` and `mysqldump`.
The additional dump binary was independently read from the fully verified
runtime archive: 6,817,992 bytes, SHA-256
`5af8762a118d391e0710b68b149e10c9139b33d7848e725cfc5f24c8ac06eb52`.
It comes from `mysql-client-core-8.0_8.0.46-0ubuntu0.24.04.4_arm64.deb`, SHA-256
`641eb958b07497de25a9e7a14fa3fbbdb193a3445d2fcd36686f5788e16639b3`.
The package is already included in the existing dependency image; this adds
no unpinned runtime package or replacement binary.

## Validation boundary

Thirteen focused host guard tests pass, including real bounded subprocess output
draining/deadline cleanup, digest rejection before SQL, all-four-empty gating,
partial-file preservation, no-replace publication and regular-file/link checks.
The file-size limiter starts an isolated Python interpreter that applies the
kernel cap then execs the fixed target. Both this harness and base SQL imports
use that launcher: no thread-unsafe Python `preexec_fn` runs while the engine
diagnostic reader is active. A real subprocess test verifies the kernel cap.
The `base-sql.yml` workflow runs the complete harness in the native ARM64 image
with external networking disabled and publishes only the bounded public progress
log, qualification receipt and runtime/environment identity. SQL dumps, SQL
errors, all account rows, credentials, and private database/configuration trees
are never artifact inputs.

The first actual ARM64 run, `41003838768` at `3ae7b694`, passed the full source-base
load/restart inside this harness, then stopped before dumping because the initial
composition had not rendered the configuration required by realm/account helpers.
The corrected composition now verifies the account fixture and renders those
templates before provisioning. Full backup/restore execution is pending rerun; no
dump, restore or setup-wrapper success is inferred from the earlier base-only pass.
No current result qualifies live saved-game restoration, upgrades across revisions,
character saving/relogging, bot persistence, the Android helper, or gameplay.
