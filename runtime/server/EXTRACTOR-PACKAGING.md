# Exact seven-patch extractor packaging

`tools/package_server_extractors.py` packages the four original native ARM64
executables from build `41019374697.1`: `map_extractor`, `mmaps_generator`,
`vmap4_assembler`, and `vmap4_extractor`. `extractors-packaging.lock.json` binds
their original installed bytes, original build/module receipts, source lock,
reviewed CLI sources, and the existing exact artifact acquisition lock. No
server patch or original receipt is changed.

The same pinned NDK objcopy used for the server programs produces separate
stripped executables and paired debug files. The existing verifier compares
mapped bytes, allocated sections, program headers, build IDs and GNU debuglink
CRC. The runtime archive contains the four executables, the original 7,888-byte
mmaps YAML at `etc/mmaps-config.yaml`, original provenance, the packaging pin,
and all 66 original source/Lua notice files. The YAML moves from the original
`bin/mmaps-config.yaml` location without changing bytes; callers must pass its
path with `--config`. Debug files and packaging recipes remain in a separate
debug archive, outside an APK. The intended mount is
`/esteria-server-extractors`.

The engine packaging workflow reuses its already verified original install,
source inputs and NDK. It records measured derivative identities after actual
packaging, transfers the externally pinned receipt, and runs five bounded checks
in the exact published Ubuntu/MySQL image on native ARM64. Each check uses a
fresh empty working directory and rejects created output. Standard input is
closed, the environment contains no user paths, and process cleanup retains the
owned group identity.

| Program | Arguments | Expected status | Boundary |
| --- | --- | --- | --- |
| map_extractor | `-i` | 1 | Usage before data lookup; input operand is missing |
| vmap4_extractor | `-?` | 1 | Documented usage before output directory access |
| vmap4_assembler | `--usage unused unused` | 1 | Too many operands; usage before assembler construction |
| mmaps_generator | `--silent --help` | 255 | Invalid map argument before configuration/data lookup |
| mmaps_generator | `--config <packaged YAML> --silent` | 253 | Original YAML parses; missing maps stops before output creation |

These nonzero statuses are exact source-derived contracts. They establish native
loader and bounded argument/configuration entry only. They do not perform MPQ,
map, DBC, camera, vmap or mmap conversion. No proprietary client data is supplied.

The selected complete corresponding-source companion is shared with the server
programs: the isolated source workflow builds all four targets from the same
seven-patch server/Eluna/Lua inputs without Git repositories or static asset
trees. Extractor packaging remains explicitly unsealed until that actual full
isolated gate and source-archive readback pass. A successful native CLI check
does not set source completeness, Android execution or gameplay flags.

## Custom client data remains unqualified

The pinned `src/tools/map_extractor/System.cpp` uses a hardcoded
`CONF_mpq_list` for the stock common/common2/lichking/expansion and patch through
patch-5 archives. `src/tools/vmap4_extractor/vmapexport.cpp` separately discovers
and orders patches. Neither establishes the reconstructed Esteria client's
arbitrary archive suffixes, loose-folder providers or exact provider precedence.
The current tools must not be described as matched custom Esteria extraction.

Custom extraction requires a separately reviewed, reproducible ordered-manifest
adaptation with loose-provider parity while preserving the desktop default.
That future adaptation must have its own source/patch identities and actual
conversion evidence. This packaging work adds no eighth patch and does not
invalidate the active seven-patch source rebuild. Base extraction and subsequent
server overlays also require independent verification before use by a world
process. Until then, `clientMpqConversionQualified`,
`customEsteriaDataLoadOrderQualified`, `androidRuntimeQualified`, and
`gameplayQualified` remain false.
