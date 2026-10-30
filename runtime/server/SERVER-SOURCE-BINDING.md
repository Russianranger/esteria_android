# Current APK and archived server source identities

The three server providers distinguish the current APK source lock from the
original full source lock recorded by the server build. `appSourceLock` is the
reviewed current `sources.lock.json` identity. `serverBuildSourceLock` is the
unchanged archived lock identity used by the original build, compiled-module,
content, source and debug receipts. Both are `5f72e02c…` at this migration.

Each provider pin and descriptor preserves the exact original 2,170-byte lock
text. Its length and SHA256 must match `serverBuildSourceLock` before its server
selection and compatibility object can be used. The full current server object
must equal that archived selection, including URL, revision, patch order/hashes,
patch scopes and submodule revisions. The full current compatibility object
must also match, retaining JSON types. This rejects a changed server patch,
Eluna revision, capacity, protocol declaration, extra key or changed boolean
type. Updating both a declared profile and the current lock cannot relabel the
original build because the original lock text remains hash bound.

A later client-only change may update the reviewed `appSourceLock` fields and
regenerate provider descriptors while reusing the exact original archives and
receipts. The archived source lock inside server runtime archives is never
rewritten. Native source completeness and native executable receipt gates remain
independent and mandatory. This arrangement does not establish packet or runtime
compatibility for a new client; the existing generated field-layout/protocol and
client runtime qualification gates still apply before selecting that client.

`ServerSourceSelection` verifies the current embedded APK lock and both full
server/profile objects for all three Java adapters. It separately verifies the
archived lock text and hash. `sourceLockSha256()` returns the archived server
build hash for content/schema/FreshSelection use; `appSourceLockSha256()` exposes
the current APK binding for reporting. Callers must not use the current client
commit to choose an existing server database generation.

All three `RuntimePackagePlan` adapters use
`serverBuildSourceLockSha256` as the stable `sourcePinSha256`. A client-only
descriptor change therefore reuses the same installed server generation and
does not recopy the 654 MB content tree. The generation still binds archive hash,
archive size, complete expected counts/bytes and required file hashes/ELF pins;
changing those inputs or the server build source hash changes the generation.
Current development generations may change once when migrating from the former
whole-descriptor fingerprint.

Tests accept a simulated reviewed client-only source update for all three
providers, reject server/patch/submodule/profile/type drift, preserve archived
receipts, and run the actual Java installer at 32 MiB to show cached generation
reuse without an archive input. No client pin changes or new server qualification
claims are made by this migration.

`prepare_server_engine_inputs.py` applies the same binding before acquiring or
repacking original installed build inputs. It requires the exact archived build
lock in the original diagnostics/install, checks the current reviewed provider
binding and both full server/profile objects, and fetches the unchanged server
with that archived lock. A client-only current APK change does not require a
server rebuild or rewrite any original receipt. A new preparation receipt records
the current APK identity separately from its original `sourceLock` identity.
