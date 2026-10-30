# SQL and configuration qualification checkpoint

This records actual component evidence and the next implementation task. It does
not qualify a complete game installation or an Android world session.

## Preserved source and execution scopes

The archived seven-patch server remains `f35f04d01689f034778e3474b3c820092f51e461`
with its original source lock SHA-256
`5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1`.
Client-only application updates must preserve that archived build/content/module
provenance. Runtime providers expose the archived server-build lock separately
from the current APK source lock; neither original receipt is rewritten.

The independently retained six-patch server is build `41005048019.1` under
`dbbf8983cfa2b429f7dd0c3308a2795ffbecd29e8019adf35348447e1eab41b0`.
Its exact binary is deliberately requalified independently of the current app.

- [Six-patch product composition](../evidence/server-product-composition-41058676309.json),
  run `41058676309`, passed the real no-Git content consumer, 442 journaled
  initialization files, compiled updater, completed repeat/read-only verification,
  all 50 selected configurations, local realm and ordinary owned account on one
  UUID. The 442 files comprise 441 original-source SQL files and one separately
  identified source-derived appearance adaptation. Account intent/rows survived
  a second actual updater and restart; the compiled authserver passed SRP6,
  persisted session-key and clean-shutdown checks.
- [Seven-patch engine/product evidence](../evidence/server-engine-product-composition-41058676543.json)
  records the separately verified seven-patch derivative/build/content scope.
  Its original build, modules and source-lock receipts remain unchanged. This
  must not be conflated with the six-patch executable identities above.
- [Actual reconstructed-client exchange](../evidence/client-auth-41060555263.json),
  run `41060555263`, passed normally without tracing: Windows ARM64 client
  `0f931bbade36a4b197725d691b8eff7caea7b3be`, build `41012726334.1`, authenticated
  against the retained six-patch authserver. Actual Grunt workers/timer/parser,
  server proof, persisted 40-byte session key, realm callback and joined teardown
  passed. `CommonMain`, game assets, version checksum and world entry were not
  exercised; this is not a seven-patch client/server-pair claim.

The earlier client initialization failure is retained in
[its separate diagnostic proof](../evidence/client-auth-initialization-41058676745.json):
normal initialization failed, while a distinct fresh diagnostic observed
`openat`/`EACCES` on its staging directory before fallback `mkdirat`/`EEXIST`.
No security mechanism was established. The successful retry mounted the same
private fixture under MySQL's intended data directory and retained the binary,
read-only root, external-network isolation and owned namespaces.

## Actual playerbots fourth schema and remaining phone gate

Standalone `dbimport` registers auth, characters and world only. Its default
compiled-updater snapshot deliberately requires playerbots to remain empty.
The phone coordinator remains staged pending a measured, packaged playerbots
helper/provider and composition; no complete installation marker or promotion
is authorized by the component proofs above.

At the pinned server source, playerbots owns 29 base SQL files, 31 released
updates and 52 prepared statements. Its real `DatabaseLoader` adds update bit 8,
uses the module's source directory, sorts original base filenames, applies its
own updater and prepares the actual connection statements. `Updates.AutoSetup`
controls creating a missing database, not populating an existing empty one.

The exact real database/common reference was built and provenance-bound in run
`41041859706`, but its executable was not retained in the uploaded artifacts.
Its build-only receipt is not database execution evidence. The target-only
workflow now built that database/common helper from the archived seven-patch source and explicit original lock. [Run `41076505231`](../evidence/server-playerbots-schema-41076505231.json)
passed actual production core/PB journals, 52 prepared statements, completed
repeat without execution, real loader reentry, restart persistence, probe removal
and final four-schema checks without rebuilding or repinning the original three
server programs. It retained the separate helper/build/native proofs; see
[the production phase contract](PLAYERBOTS-SCHEMA.md).

The implemented production phase uses a private same-UUID/source/content/module/credential-bound
playerbots intent before the compiled helper can run, refusal of uncertain
partial state, exact source-ledger verification and core/account preservation.
Completed core verification accepts a nonempty fourth database only through
its matching completed playerbots journal and live source checks. Arbitrary
nonempty databases continue to fail. Portable realm/account and final
fresh-installation composition must use this shared gate.

No playerbot AI, bot characters, existing-save upgrades, complete world startup,
matched imported game assets or Android gameplay pass is implied.
