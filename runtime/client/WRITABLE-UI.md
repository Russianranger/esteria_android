# Writable loose Interface generations

`ImportedUiSource` and `ClientUiStore` implement the writable policy required by
`UIUtil/AddOns.cpp`: the game may write public-key/URL files and rename or remove
loose addon/UI directories. Every managed Interface tree is therefore an actual
private copy. It contains no links or hardlinks into imported assets. Existing
imported bytes, older UI generations and per-account WTF saved variables remain
untouched.

## Trusted source inventory

The source adapter accepts a private `GameDataImporter` store and an exact
completed import generation. It checks the completion marker's format,
`clientBuild=12340`, request generation, and source identifier. Overlay imports
seed base files without duplicating their hashes in the overlay's journal, so
the adapter follows `base-ready` records, rejects cycles, and resolves the latest
Interface file hashes from oldest to newest journals. Current-generation UI
files must all have matching recorded sizes/hashes. No hash is invented for a
file missing from that ancestry.

The adapter retains hashes of the completion, parent and journal metadata for
later revalidation. These are private importer ownership records, not a remote
signature or independent proof that the content package is complete. Its source
binding is separate from a UI inventory identifier: the latter hashes a sorted
relative-path/size/SHA-256 manifest. A Data-only import with unchanged Interface
inventory therefore reuses the existing mutable addon tree, while adding its
own immutable import-provenance receipt. It does not reset addon changes just
because the overall imported client generation changed.

A new inventory is copied with bounded buffers. Interrupted copies retain owned
partials and compare their prefix against the source before appending. The
source hash and copied-file readback must both match the imported baseline.
Completed staged copies can be reused, but unexpected or modified staged bytes
fail without truncation. Rebinding an existing UI inventory to a new import
requires that new source's actual UI files to match its declared inventory.
Repeated preparation for the same already-bound import avoids rehashing the
immutable source tree.

## Storage and activation

The store is below `work/client-state/UI`:

| Location | Purpose |
| --- | --- |
| `generations/<inventory-id>/Interface` | Writable real addon/UI files |
| `generations/<inventory-id>/inventory.tsv` | Immutable original source baseline |
| `generations/<inventory-id>/provenance/<import-generation>` | Separate exact source binding |
| `staging/<inventory-id>` | Owned incomplete copy and partials |
| `current` | Atomically selected UI inventory identifier |

Preparation never switches the active pointer. `assess(candidate)` hashes the
old and candidate mutable trees, validates both immutable baselines, and returns
structured added/modified/deleted/case-renamed paths. It separately identifies
source changes and paths changed both locally and by the new source. Reports
contain paths and change kinds, never file contents, credentials, Lua values,
URLs or public-key material.

Moving to another tree requires review when either retained tree has local
mutations. No automatic merge, old-tree removal, or overwrite occurs. The caller
can present the report and then explicitly accept that exact decision using
`activate(candidate, report.digest, acceptDivergence, cancellation)`. Activation
recomputes current tree and baseline identities under the store lock. A stale
report, changed source receipt, changed pointer, or changed candidate tree fails
before the pointer changes. An explicit decision retains the previous tree and
its changes for later recovery; it does not transfer or merge those changes.

Reusing the currently active inventory preserves its mutations without a new
update decision. Global `client-state/WTF` remains outside UI generations, so
account saved variables and settings survive UI changes. This policy protects
files; it does not assert that old saved variables are semantically compatible
with a new addon version.

## Launch-view connection

The intended stopped-session sequence is:

1. Resolve `ImportedUiSource.fromImportStore(...)` from the selected complete
   import, and call `ClientUiStore.prepare(...)`.
2. Inspect `assess(...)`; activate a clean update or obtain an explicit decision
   for a divergent report. Never turn a pending report into implied approval.
3. Obtain `selectedFor(source, cancellation)`, which returns a typed `Selection`
   only for the active owned UI inventory with its exact source provenance.
4. Pass that selection to the five-argument `ClientLaunchView.Plan` constructor.

The view links `Interface` only to the selected private guest path
`/work/client-state/UI/generations/<inventory-id>/Interface`. The selection is
bound to its work directory and exact imported root/generation. Preparation and
`Plan.arguments()` revalidate the selection; changing the active UI pointer
invalidates an old launch plan. A plan without a valid selection still reports
loose Interface as deferred and refuses gameplay arguments.

All operations require the client to be stopped. The app's session supervisor
must enforce that precondition; a file lock cannot stop a running game from
editing its own addon files. PRoot is not a security/read-only mount. Android
process qualification, offline network policy, real assets, and world entry
remain separate gates.

## Bounds and evidence

UI inventory is bounded to 8,192 files, 32 directory levels, 256MiB per file and
1GiB total. Its relative-path bound includes the Windows executable-view prefix
and `Interface` component. Metadata is bounded to 4MiB per UI inventory; importer
ancestry is bounded to 32 distinct generations and 64MiB aggregate journals.
Root/descendant symlinks, special files, Windows-unsafe names and case collisions
are rejected. Mutable UI hardlinks are rejected where the filesystem exposes
link counts; this store never creates them. Failure preserves existing data.

`ClientUiStoreTests` passes with a 32MiB Java heap. It covers inherited overlay
journals, interrupted copies, source-only Data updates retaining modified addons,
new-source conflict reports, both old/candidate stale-report rejection, explicit
retained-generation activation, unchanged imported bytes/WTF, source and baseline
mutation rejection, unsafe links/ownership/cycles, and the typed launch-view
integration. These fixtures are synthetic and execute no game or Android process.
The full app's pending-review presentation and session-stopped enforcement are
still required before exposing this API as a gameplay action.
