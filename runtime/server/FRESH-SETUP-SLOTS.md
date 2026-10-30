# Fresh setup slots and promotion

`FreshServerInstallations` provides storage transactions for a future complete
first-run coordinator. It does not itself execute or qualify SQL. No launcher
START action uses it yet.

Each attempt owns one short private `files/db/<16hex>` work directory and a
separate journal below `files/state/server-installations`. The 16-character slot
name is allocated with exclusive directory creation. The complete operation UUID
is recorded in its journal. Short paths preserve the physical Android MySQL UNIX
socket bound: the expected package's socket path is 88 bytes, compared with 139
bytes for a nested UUID/work layout. The service still checks its actual path
against the 100-byte bound before launch.

The guest always sees `/work/state`; promotion never renames the datadir. A
successful promotion publishes an atomic active-slot pointer. Reopening the
same source selection resolves that slot without rewriting its pointer. A
changed source selection is refused and retained pending a separately qualified
upgrade. Existing `state/server-work` is preserved and requires explicit future
migration; it is never adopted or overwritten by first-run setup.

A setup attempt holds an exclusive file lease. Typed workspace tokens retain
ownership for database bootstrap and the live database service. Abandonment,
promotion and closing an attempt are refused while tokens remain held. A failed
or cancelled attempt is retained intact for diagnosis; the next attempt allocates
a different fresh work directory. No SQL is replayed over the prior partial
instance, and no retained slot or user data is automatically deleted. The caller
must supply a measured free-space reserve before a slot can be allocated.

Promotion requires a complete declared proof bound to the exact application
source, dependency runtime, programs, content receipt and compiled modules; MySQL
UUID/version; and exact bootstrap, setup-completion and clean-stop receipt
hashes. Required phase flags cover the source baseline, compiled updater/core
ledgers, same-revision reentry, local loopback realm, local account, playerbots
schema and clean engine shutdown. The storage layer verifies binding/file bytes;
the coordinator validates real component receipt semantics before constructing
this proof. Its guarded fourth-schema/clean-stop path remains unavailable to the
current three-program provider. Baseline-only completion cannot promote; no
production provider or Main START action is enabled by this code checkpoint.
The full exact MySQL 8 version string, including the Ubuntu release suffix, is
retained in the proof and reconstructed without normalization. The public active
setup-receipt hash is copied from that validated proof, and marker changes refuse
reopening.

Durable completion before pointer publication, and pointer publication before
final journal update, both recover to the same complete slot. An uncommitted
proof alone cannot activate it. Receipt changes, incomplete flags, legacy state,
source mismatches and linked workspace paths are refused. Retained active saves
are never reseeded.

`ServerDatabaseSetup.prepareFresh` accepts a store-issued caller-retained token.
Both fresh bootstrap and service start verify the runtime archive against the
attempt's immutable source selection before using the workspace.
`ServerDatabaseService.startFresh` retains its own token until process completion;
`startActive` starts promoted storage directly and checks the exact dependency
archive without running bootstrap again. `ServerSchemaSetup` uses the retained
handle's fixed validated workspace. The normal legacy APIs retain their paths.

A reviewed shared process race was also fixed: an observed launch failure now
waits for native-owner cleanup to finish before propagating. This prevents
startup-error paths from releasing database/workspace leases while termination
is still running. Returning a retained handle remains valid when failure occurs
after launch returns.

Host evidence is `runtime/evidence/fresh-server-installations-host.json`. Tests
use real filesystem atomic writes, locks, retained sentinel bytes and injected
interruption boundaries under a 32 MiB heap. Receipts are explicitly synthetic
fixtures; no SQL or game server runs. A 200-trial real owner-thread/backend race
suite observed 59 retained handles and 141 settled exceptions, with no exception
escaping before cleanup. Fresh/guard/mount tests, application/test Java
compilation and Android lint pass. Actual Android fresh setup, production complete proof
construction and playable persistence remain unqualified. New coordinator host
tests cover source-bound fourth-schema/config transition and cancellation/reentry;
actual native qualification of that new composition remains separate.
