# Portable owned realm and account provisioning

The new `provision_verified` functions in `provision_local_realm.py` and
`provision_local_account.py` accept:

- Actual `server_content.VerifiedContent` and an already authenticated MySQL connection.
- Private state, exact MySQL version and `expected_uuid`.
- Explicit sealed `profile`, expected `data` directory and `mysql` executable path.
- A mandatory `verify_service` callback tied to the caller's retained service handle.
- Optional `verify_only=True` for read-only row/account verification.
- Optional `state_lease` issued by the caller's active `db.state_lock` scope.

They start no SQL client, engine or game server, and perform no Git/tool imports or
repository `ROOT` lookups. The caller retains its application/session service
lease throughout the operation. Existing host `provision` functions and CLIs keep
their repository policy checks and behavior.

Both runtime APIs take the existing state/configuration locks and named bootstrap
and realm SQL locks; account setup also takes the account SQL lock. Each function
releases only the acquisitions it made on the caller-owned connection, including
partial acquisition failures. Prior recursive caller acquisitions remain held.
An optional real state lease is reused through `db.state_scope`; this neither
reacquires nor releases the caller's file lock. Expired, forged or differently
owned capabilities are refused.
The completed updater verifier requires bootstrap SQL ownership, takes/releases
no locks and checks the actual private completed journal, baseline, source/module
bindings, owned UUID/credentials and live update ledgers. A caller boolean or
successful source-baseline import cannot authorize account or realm mutation.

The exact reviewed realmlist/account/tracker base hashes are checked against the
verified content's source inventory, archived payload and actual source bytes.
The complete active configuration is checked against a read-only computation of
the same private file dictionary used by the renderer. This compares every main,
module, MySQL and proof file, with explicit expected data/client paths and the
sealed fixed ports/four-account-bot policy. Rehashing an altered generation cannot
authorize changed modules, remote administration or SOAP. The expected dictionary
contains the private database password and must never enter public receipts or
support exports.

The existing schema checks and transactional realm/account implementations remain
shared. Realm setup changes only the local endpoint fields of realm 1. Account
setup journals its exact random SRP credentials before SQL, recovers an unknown
commit only from that same private intent, and refuses adoption, password resets,
privilege inheritance, missing completed accounts or missing character trackers.
No characters are created. Credentials, source/configuration and updater journal
identity are checked again after mutation while the same locks remain held.

`server_config` now shares one pure private-file builder between rendering and
verification. Historical comparison against commit
`5c6f8d26813128a4763506cf3e38d10997f1935a` produced identical 54-file complete
and 4-file legacy generation bytes and return values. The private read-only
computation makes no state/credential/pointer writes.

Host evidence is in `runtime/evidence/portable-local-provisioning-host.json` and
`portable-provisioning-renderer-parity-host.json`. The combined 53-test run passes
52 tests with one explicit real-MySQL fixture skipped. The new 11 runtime API tests
use actual metadata-verified synthetic content and row/metadata connection
fixtures. Positive row cases deliberately mock the independently tested completed
updater gate; an unpatched incomplete-updater case verifies rejection before row
mutation. These establish API/source/ownership behavior, not actual SQL execution.

Actual native ARM64 execution of these new portable APIs, Android setup and
complete fresh-slot promotion remain pending. No launcher or production setup
coordinator is activated by this checkpoint. The next native integration should
exercise these functions after the actual compiled updater gate, then verify
private credential/account preservation, exact local realm and relogging.
