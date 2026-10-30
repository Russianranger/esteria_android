# Empty appearance schema adaptation

This is an explicitly **source-derived adaptation**, not recovered canonical SQL
from server `f35f04d01689f034778e3474b3c820092f51e461` and not gameplay evidence.
The actual fresh compiled qualification reached CharacterDatabase preparation and
failed because `character_body_shape` and `character_retail_look` were absent.
The original source package, SQL filenames, module selection and updater ledgers
remain unchanged. Existing saves and interrupted imports are never upgraded here.

`appearance-schema-v1.sql` creates two empty tables only. Each has an unsigned
32-bit `guid` primary key and a required binary `data` value: 49 bytes for body
shape and 132 bytes for retail look. There are no foreign keys, column defaults,
seeded rows or synthetic updater-ledger entries. `CREATE TABLE` deliberately lacks
`IF NOT EXISTS`: both tables must be absent immediately before this adaptation.

The source contracts are explicit:

| Contract | Exact source evidence at f35 |
| --- | --- |
| SQL reads/replaces/deletes only `guid,data` | `src/server/database/Database/Implementation/CharacterDatabase.cpp:90` through 115 |
| Character counters are unsigned 32-bit values | `src/server/game/Entities/Object/ObjectGuid.h:125`, 149 through 153 |
| Create/customize writes use counters and exact byte vectors | `src/server/game/Handlers/CharacterHandler.cpp:843` through 860; `src/server/game/Entities/Player/PlayerMisc.cpp:145` through 168 |
| Binary parameter binding | `src/server/database/Database/MySQLPreparedStatement.cpp:172` through 186 |
| Reads assert non-null, exact binary length | `src/server/database/Database/Field.cpp:146` through 149; `src/server/game/Entities/Player/Player.cpp:11967` through 12007 |
| Body format | `src/server/shared/BodyShapeWire.h:23` through 84: version 1 plus 48 signed bytes, 37 assigned slots, zero unused slots |
| Retail format | `src/server/shared/RetailLookWire.h:29` through 95: version/race/sex-form/count and 64 little-endian 16-bit indices; current code allows six forms |
| Missing rows have defined fallback behavior | `Player.cpp:11969` through 11976 and 11996 through 12014: zero body shape or stock appearance |

These constraints do not uniquely recover original DDL. Fixed `BINARY` storage,
primary keys, InnoDB and table charset/collation are explicit implementation
choices. The unchanged canonical `character_form_look` creator at
`data/sql/updates/pending_db_characters/rev_20261023233000000_character_form_look.sql`
uses the same 132-byte look with an unsigned integer primary key and InnoDB; it
is an analogy, not evidence that these missing creators were present. Appearance
values remain opaque source-defined bytes; no model choices or assets are inferred.

`appearance-schema.lock.json` records exact SHA-256/Git-blob identities of the
audited C++ sources and the analogous canonical form-table creator. The nine C++
working files were compared byte-for-byte with no-lazy-fetch Git objects at f35.
This audit metadata is immutable input; no C++ checkout or Git is needed on the
device. The runtime module pins both its separate SQL and audit metadata bytes.
It accepts only the exact current seven-patch source lock `5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1`
or retained six-patch lock `dbbf8983cfa2b429f7dd0c3308a2795ffbecd29e8019adf35348447e1eab41b0`,
with their corresponding complete server source objects.

The caller must already own and authenticate its MySQL instance. The adaptation
validates its selection before SQL, proves all four databases empty, invokes the
unchanged original baseline initializer, proves the two additional tables absent,
then applies its separate file. It verifies exactly two table additions and zero
rows. Its returned `sourceDerivedAdaptations` proof is separate from the original
baseline receipt: original `sourceFiles`, `appliedFiles` and ledgers are untouched.
A failure preserves partial tables; the next call refuses the nonempty instance.

Native ARM64 run [41045808679](https://github.com/Russianranger/esteria_android/actions/runs/41045808679)
at integration `8433a5d4e4bf943204f1159af21d4fbcf67e26b4` now passes the separate
MySQL `8.0.46-0ubuntu0.24.04.4` storage gate: exact 49/132-byte NUL/high-byte
`REPLACE`/read/delete, clean restart, byte-for-byte persistence and removal of all
fixture rows. Its receipt keeps C++ wire-payload parsing and character creation
false; raw binary storage is the measured scope.

The unchanged retained six-patch compiled importer from build `41005048019.1`
then passes actual database-pool/prepared-statement startup, all selected original
SQL/update-ledger checks, same-revision reentry, local realm reassertion and clean
restart. Source-derived table evidence remains separate from canonical SQL. The
workflow subsequently fails before authserver startup because its realm helper
still hashes only four legacy configuration files while the renderer hashes the
complete module selection. This later failure does not qualify authentication.

Public artifact `12973155745` is 706,752 bytes, SHA-256
`0e0069f94ce06e3256e0e189915f6f1ef5267ea0fba320401b5932912fc6656a`.
The compact receipt bindings are in
`runtime/evidence/server-schema-components-41045808679.json`. Seven-patch compiled
qualification, actual auth/client pairing, world entry, saved appearances and
Android remain separate gates. No gameplay result follows from these component
passes.
