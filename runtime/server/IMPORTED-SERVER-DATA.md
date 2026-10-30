# Supplied server data

The existing **Add custom content folder/ZIP** action accepts a reserved
`EsteriaServerData/` directory at the package root. Its contents are imported
transactionally with the client generation, stay outside the client's launch
view, and are projected only into a prepared server-data generation.

The package contains `EsteriaServerData/manifest.properties` and
`EsteriaServerData/data/`. Copy the exact seven fields from
`config/server-data-inputs.example.properties`. The small manifest is strict
ASCII with LF or CRLF endings. Unknown, duplicate, missing or differently pinned
fields are rejected. `serverRevision` must name the pinned server; this is a
user declaration, not independent evidence of the data's producer.

In `mode=overlay`, the data directory may contain only `dbc/` and
`dbc-continuations/`. They are applied to freshly generated data before atomic
promotion. A later package that contains any `EsteriaServerData/` files replaces
the entire previous namespace, so supply every continuation that should remain
active. An ordinary client overlay without this namespace retains the existing
server-data selection.

In `mode=complete`, supply recognized files in all five directories `dbc/`,
`maps/`, `vmaps/`, `mmaps/` and `Cameras/`, plus optional `dbc-continuations/`.
The preparer then imports those data files without running conversion. A
completed source-qualified tool provider and client MPQs are still required by
the complete application profile. Formats alone establish neither geographical
coverage nor matching DBC rows or gameplay.

**The existing 16 MiB import metadata budget still applies.** Large complete
world datasets with tens of thousands of files can exceed that budget and are
refused before copying. Full-world precomputed-data import is not qualified by
the small synthetic fixtures. Generating data from the imported MPQs and adding
a small matched DBC/continuation package is the current bounded path.

`clientProviderOrderSha256=none` explicitly leaves the supplied data's client
matching unverified. An exact SHA256 of the canonical effective client provider
order can bind the package to that stack; a different hash stops preparation.
All packages additionally bind the exact imported ancestry/journals, raw
manifest identity, native tool selection and current preparation-helper
generation. Input or helper changes select a different prepared generation.

Continuation binaries belong under `data/dbc-continuations/`, matching the
actual `WxlDbc.ContinuationPath` default. Names use
`Table.dbc1-project` through `Table.dbc9-project`. Optional
`wxl-dbc.manifest` is kept byte-for-byte at that directory's root. The validator
mirrors the pinned module's tier, manifest-position, project and table ordering;
escaping or absent manifest references and ambiguous order ties are refused.
WDBC field counts and record strides must match a known base table. The
preparer does not invent, rewrite or merge DBC rows.

MAPS9/build12340, VMAP4.8, mmap20/Detour7, WDBC declared lengths and MD20 camera
headers are checked. Header checks do not replace the actual server loader or
world qualification. Every resulting data byte remains inventoried, and the
guest revalidates it before server startup. Interruption leaves the previous
active server generation intact; immutable previous generations remain stored.

Client custom content must remain relative to the client root:
`Data/patch-MyPack.MPQ`, locale patch paths, folder MPQs in that same location,
or loose `Esteria*.bin` files beside `Wow.exe`. Select the folder containing
`Data/`, rather than `Data/` itself. Misplaced MPQs, wrapped server namespaces,
known wrapped `Data/` layouts and a root `Esteria/` catalog directory are rejected
with corrective instructions. This does not establish that every arbitrary file
in an imported package is consumed by an enabled client feature.
