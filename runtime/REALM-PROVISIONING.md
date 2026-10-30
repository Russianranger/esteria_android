# Local realm endpoint provisioning

`provision_local_realm.py` reasserts and verifies **realm 1 only** as the local
build-12340 world endpoint after all schema and module updates. It does not load
game schemas, create player accounts, start a server or establish gameplay readiness.
The app runtime adapter must call this gate; the gated launcher does not yet do so.

## Source evidence and required order

At EsteriaWoW `f35f04d01689f034778e3474b3c820092f51e461`,
`modules/mod-custom-server/data/sql/db-auth/u_custom_server_2026_09_03_public_realm.sql`
changes realm 1's advertised address to a public address when its name is `Esteria`.
That enabled module's updates run after the base/released/archive SQL phases.
Configuring `BindIP` alone does not override the address sent in the realm list.

The startup owner must serialize these actions:

1. Start the owned MySQL instance and authenticate using the existing bootstrap receipt.
2. Complete **all** required base, released, archived and enabled-module updates.
3. Run this local realm provisioner, then perform live verification before allowing
   client launch. If auth/world startup runs any further updater, reassert and verify
   after that updater completes. Do not run schema updates concurrently with this gate.
4. Verify actual auth/world readiness separately, then launch the reconstructed client.

A previous `realm-loopback.json` records a past successful check. It is never a
substitute for a live authenticated query after updates or at startup. MySQL
advisory locks serialize cooperating bootstrap/realm tools; they do not force
upstream SQL updaters to participate in the same lock protocol.

## Exact scope

The realmlist schema is derived from pinned `data/sql/base/db_auth/realmlist.sql`,
full source SHA-256
`b5c6d72b407dddb070a2ee497aa0500175c02f1a5288ee2716513821de71e78c`.
The script requires its twelve exact columns, default values, primary/name keys,
InnoDB engine and absence of triggers. A changed source pin or schema requires
review rather than automatic adaptation.

The selected record must be:

| Field | Value |
| --- | --- |
| `id` | 1 |
| `address`, `localAddress` | `127.0.0.1` |
| `localSubnetMask` | `255.255.255.255` |
| `port` | 8085 |
| `gamebuild` | 12340 |

Existing `name`, `icon`, `flag`, `timezone`, `allowedSecurityLevel` and `population`
are preserved. Other realm rows, realm-character associations, accounts,
characters and bot data are untouched. If realm 1 is absent, insert only that row
with name `Esteria` and the source schema's defaults for remaining fields. An
existing unique-name collision fails; there is no REPLACE, UPSERT, deletion,
reseed or attempt to modify the conflicting realm.

`verify` performs no row repair. `provision` uses a transaction and row lock,
checks the row before committing and queries it again afterward. The startup
owner must treat any error as a launch failure and preserve the data for diagnosis.

## Authentication and configuration

The provisioner reuses `mysql_bootstrap.py` for the private option-file connection,
exact MySQL version, receipt UUID/datadir matching, local bind/port verification,
application-account check and installation lock. Passwords never appear in argv,
stdout, receipts or SQL error logs. It uses the restricted `esteria` application
account rather than root.

An intact active configuration generation is mandatory. The only accepted
`config/current` link is the renderer's contained `generations/<sha256>` pointer.
All four configuration files are rehashed to that generation ID; unsafe links,
corruption, duplicate/missing endpoint keys and generation changes fail. A shared
configuration lock prevents a cooperating renderer from changing the active
configuration mid-operation. Auth must bind `127.0.0.1:3724`, world must bind
`127.0.0.1:8085` with `RealmID=1`, and both must use the installation's exact local
auth database connection. No private config content is exported.

Run inside the eventual private runtime namespace, after rendering configuration
and successful database/bootstrap/schema preparation:

```sh
python3 runtime/provision_local_realm.py provision \
  --state-root /esteria/state --mysql /usr/bin/mysql --expected-version 8.0.44
python3 runtime/provision_local_realm.py verify \
  --state-root /esteria/state --mysql /usr/bin/mysql --expected-version 8.0.44
```

Pin the actual complete engine version, including any distribution suffix. The
example version is the dedicated CI fixture, not a packaged Android MySQL promise.
The result and private `state/realm-loopback.json` identify the config generation,
server/schema revision, MySQL UUID/version and precise endpoint-check scope.
Game-schema, server-start and gameplay qualification remain false.

## Tests and limits

```sh
python3 -m unittest tests.test_local_realm -v
```

Ordinary discovery runs seven guard tests and skips the real engine fixture. The
separate `realm` job in `.github/workflows/database.yml` starts a fresh MySQL 8.0.44
instance, uses a provenance-checked exact CREATE TABLE fragment from the pinned
source, and tests local insertion/reassertion, repeat verification, preservation
of other realms/settings/character-marker data, SQL lock rejection, receipt and
schema mismatch, and unique-name collision rollback. Public-address regression
data uses documentation addresses (`203.0.113.*`/`198.51.100.*`); the fixture
makes no connection to those addresses.

A checked-in fixture or green unit tests are not real-engine evidence. Record the
completed CI run before claiming SQL qualification. This focused test loads only
the realmlist table and a synthetic persistence marker, not the full game schemas.
No Android or game login/world test is implied.
