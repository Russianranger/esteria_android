# Packaged content and fresh schema setup

The application can verify the existing immutable `server-content.tar.gz` payload
after its bounded installer extracts it. A phone needs neither a Git checkout nor
Docker. No second SQL copy or alternate module inventory is introduced.

`runtime/server_content.py` exposes:

```python
verified = server_content.verify(
    extracted_content, package_receipt_path, expected_receipt_sha256,
    expected_full_server_source, expected_source_lock_sha256,
    original_compiled_module_object, progress=progress, cancelled=cancelled)
```

The expected receipt digest comes from the sealed application/provider descriptor;
the full original compiled-module object comes from the paired engine generation's
unchanged provenance. Its `serverBuild` binds the original build receipt. Derived
executable identities remain a separate engine selection. The external receipt
stays outside the extracted payload so the payload's exact file set is preserved.

The verifier checks every payload byte in bounded blocks, source/lock identities,
all four archived metadata documents, complete compiled selection, configuration
templates and source-selected SQL. It rejects additional, missing, linked, shared,
special or case-colliding files. The current product policy accepts only the
explicitly disabled Lua selection. Cancellation is checked during hashing and
does not mutate inputs. Receipt identities for original JSON inputs are distinct
from the archived, canonical JSON byte identities; both relationships are retained.

`runtime/server_schema_baseline.py` contains the exact fresh-baseline algorithm
shared with native qualification. `tools/initialize_server_schema.py` is now its
native adapter; its caller still verifies the original source/patch lock,
installed build and content package before invocation. Core file counts, the
canonical custom-race creator and the documented Nemesis prerequisite are
unchanged. The runtime module imports only the standard library.

The wrapper also consumes the separately audited
`server_schema_adaptations.py` contract and its unchanged
`server/appearance-schema-v1.sql` / `server/appearance-schema.lock.json` beside
the runtime helpers. These three inputs must accompany the same sealed helper
generation. They are integration-owned source-derived schema implementation,
not recovered canonical SQL or files added to the original content archive.
The original baseline receipt remains intact; `sourceDerivedAdaptations` records
the additional two empty tables, audit/SQL identities and exact source selection.

The product wrapper is:

```python
receipt = server_schema_setup.initialize(
    verified, authenticated_connection, state, expected_mysql_version,
    apply_source_sql, progress=progress, cancelled=cancelled)
```

The caller must hold the exclusive application database-service/session lease,
retain the owned engine, and supply `apply_source_sql(database, path)` with a
bounded SQL-client lifecycle. The wrapper independently checks the existing
bootstrap receipt, datadir UUID/path, authenticated version/account, loopback
endpoint and a connection-scoped SQL operation lock. It reads existing database
credentials without creating or resetting them. It never provisions an account.

Before any SQL, all selected source bytes and all four empty databases are
verified. A private atomic journal records instance, content, compiled selection,
credential identities and the exact file sequence. Each auto-committing SQL file
gets a durable in-flight intent before execution and completion afterward.
The source-derived appearance SQL is a separate final journaled step, rechecked
and applied only after proving both appearance tables absent. Its metadata/SQL
identities are also part of the journal binding and completed historical proof.
Cancellation is observed before work and between files; an executing file must
finish or fail through its existing owner. Credentials and account journals are
checked for preservation after each import.

A journal that never started SQL may retry only while all four databases remain
empty. An in-flight or partially imported journal is preserved and refused;
individual SQL files are never replayed to guess whether interrupted DDL committed.
A completed journal allows same-identity historical-baseline reuse without SQL.
Different source/content/instance/credentials require explicit future migration
work and cannot be adopted as a new installation. No live save is reseeded.

The result's scope is `owned-packaged-content-source-baseline-only`.
`baselineImportCompleted` describes the source baseline; it leaves live schema
readiness, compiled updates, full schemas, playerbots, authentication, world,
Android execution and gameplay false. Subsequent actual updater execution,
source-ledger checks, realm/account provisioning and clean-restart qualification
remain separate gates. Public diagnostics must keep raw SQL exceptions and the
private journal out of logs.

Fixture tests cover exact package binding, filesystem refusal, cancellation,
source-baseline ordering, four-empty guards, credential/account preservation,
same-identity reuse, and refusal of interrupted or changed state. These tests do
not execute MySQL, qualify the Android adapter, or establish gameplay. The current
native qualifier also calls this exact no-Git verifier after immutable archive,
source, installed build and complete compiled-selection validation, before an
engine or SQL. It consumes the actual extracted content and paired module object;
its separate `packagedRuntimeContent` receipt records full byte readback without
claiming Android execution. Native ARM64 run
[41046942015](https://github.com/Russianranger/esteria_android/actions/runs/41046942015)
at integration `1e2a0d1b2f51d31493820edfaa08eaed03723639` now passes this exact
consumer over 4,063 actual packaged files / 654,242,827 bytes, bound to the
retained six-patch installed build and full compiled object. Its original SQL,
same-revision reentry, ledger checks and clean restart also pass. The following
auth stage still fails on the earlier configuration-generation consumer mismatch.
Exact artifact/member bindings are in
`evidence/server-content-readback-41046942015.json`.

The same native adaptation and the phone journal call the same implementation.
Separate native binary-storage/restart and compiled database-pool startup now pass
as recorded in `server/APPEARANCE-SCHEMA.md`. No appearance rows or game assets are
seeded. The complete phone journal/adapter, current seven-patch application,
authentication/world gameplay and Android execution remain unqualified. Launcher
START remains gated.
