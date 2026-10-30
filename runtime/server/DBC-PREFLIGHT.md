# Pinned server DBC header preflight

The offline data preflight now rejects a supplied known table with the wrong
field count or on-disk record stride before conversion or generation promotion.
For example, a self-consistent one-field/four-byte `Map.dbc` previously passed
its WDBC signature and length checks. The selected server expects66 fields and
264 bytes per input record. A file's WDBC signature has no build-number field;
these checks alone still cannot identify all of build12340 or qualify its rows.

The generated block in `runtime/server_data_preflight.py` comes from the exact
f35f04d server and the seven adaptation identities in `sources.lock.json`.
It retains hashes of the active store declarations, format strings, file
loader/type definitions, SQL-overlay adapter and continuation registry. There
is no extra file to omit from the Android helper bundle. The existing helper
manifest hashes the changed preflight source as part of its preparation identity.

```sh
python3 tools/generate_server_dbc_layouts.py --server sources/server --check
# After deliberately updating the pinned source and reviewing its formats:
python3 tools/generate_server_dbc_layouts.py --server sources/server
```

The generator reads canonical Git blobs and verifies their checkout bytes.
It refuses a different revision, modified schema source, changed patch hash,
an adaptation touching these schema files, or an active declaration it cannot
parse. A future schema adaptation therefore requires explicit generator support.

## File layout and SQL data are different requirements

There are112 active `LOAD_DBC` stores. Every one supplies a named SQL overlay
(`*_dbc`). `LoadDBC` loads a file if available, applies its SQL table and then
requires a nonempty combined store. It is incorrect to infer that all112 files
must exist independently of the database. This preflight validates known tables
that are present; it does not infer missing-table success or failure from SQL
that it has not queried.

The server subsequently requires known build-era IDs in seven combined stores:
AreaTable4987, CharTitles177, GemProperties1629, Item56806,
ItemExtendedCost2997, Map724 and Spell80864. Offline header checks do not qualify
those rows, their SQL replacements, custom race rows or cross-table references.
Actual database/world startup remains the combined-content gate.

The continuation registry contains111 of those stores; TaxiPathNode is not
registered there. Existing continuation ordering and base/header agreement
checks remain in place. A structurally valid unknown custom continuation still
does not establish that this server consumes it. No new custom schema or rows
are synthesized.

## Input bytes versus decoded structures

The file loader treats `b` and `X` columns as one input byte and its other
supported columns as four bytes. `DBCFileLoader::GetFormatRecordSize` instead
measures the decoded native structure: string fields use native pointers,
skipped fields disappear and index-only fields have different treatment.
It must not be used as the WDBC disk stride.

| Present known table | Fields | Disk record bytes |
| --- | ---: | ---: |
| Map.dbc |66 |264 |
| ChrRaces.dbc |69 |276 |
| CharStartOutfit.dbc |77 |296 |
| SpellItemEnchantmentCondition.dbc |31 |64 |
| CinematicCamera.dbc |7 |28 |

The same base-table schema applies to locale copies and recognized
`Table.dbcN-project` continuation files, including when no base file was supplied.
Unknown table names retain bounded structural checks because their schema is
not established by the selected server source. Checks still read only the
20-byte DBC header and file length, not whole table payloads.

Successful report fields stay unchanged so a valid existing v1 generated-data
receipt does not become stale merely because this check was strengthened.
A malformed known table is refused; existing imported data and active generated
pointers are preserved. Available host fixtures qualify this refusal and source
projection only. Real client data extraction, Android execution, full SQL/DBC
parity, world entry and gameplay remain unqualified.
