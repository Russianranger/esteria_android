# Esteria asset requirements

Audit date: 2026-10-29 (America/Chicago). Client baseline
`800cdd272269570a9776d0c170e4828605fc1218`; server baseline
`f35f04d01689f034778e3474b3c820092f51e461`.
This inventory distinguishes source availability from usable, matched content. No complete imported
client/server data set has been qualified in this project. The user's existing 3.3.5a client has not
been imported here; the previously provided `Wow.exe` alone does not contain the game data.

| Requirement | Classification and evidence | Acquisition or generation |
| --- | --- | --- |
| Base WoW 3.3.5a build 12340 client data | User-owned input; not in either source repository. Engine identifies the 12340 protocol, but an executable version cannot authenticate all MPQ contents. | Import the user's complete existing client, including `Data`, its active locale, and source `Wow.exe` for version inspection. The Java importer checks the PE version resource, archive structure and conventional full-client filenames; content compatibility remains unqualified until effective DBC/data checks and runtime loading. |
| Current complete Esteria custom MPQ set | Blocked by unavailable matched inputs. Historical source docs describe `Patch-6.MPQ`, `Patch-7.MPQ`, root/locale Z archives and many later custom providers in the developer's `G:\3.3.5a - Dev` installation. That entire winning stack is not committed. | The smallest eventual custom-content request is a manifest plus the actual effective MPQ/folder-provider set from one working Esteria installation, together with its matching server data. Do not combine historical snapshots blindly. |
| Historical custom MPQ snapshots | Present/publicly obtainable in the pinned server: `assets/archives/patch-Z.MPQ`, `patch-enUS-Z.MPQ`, `assets/Arakkoa-race/client/patch-ZR.MPQ`; module packages `mod-Faction-Free/mpq/Patch-F.mpq`, `mod-fly-anywhere/data/patch/client/Patch-O.mpq`, `mod-loyal-steed/client/patch-LoyalSteed.mpq`. Presence is not qualification. | Obtain through the pinned server checkout. The two archived Z blobs fail the bounded classic-MPQ extent check; details below. Other packages still require individual integrity and matched-data validation. |
| Appearance selection catalogs | Blocked by unavailable inputs. No loose `Esteria*.bin` blobs appear in either pinned repository tree. `WoW/Common/ComponentCore/EsteriaAppearance.cpp` reads `Esteria\<name>` from the effective MPQ stack, falling back to files beside the executable. | Obtain the current catalogs from the working installation or regenerate each from its original input sets. `tools/pack_appearance_catalogs.py` in the server merely packages existing files; it does not create missing catalogs. |
| Appearance texture banks and geometry/coverage | Blocked by unavailable inputs. Source contains real readers and packer logic, not all generated bank/model bytes. | Match the same catalog generation and original art. Do not substitute placeholder appearances or claim unsupported races work. |
| Server DBC base, custom overlays and continuations | Partial source inputs present; complete matched runtime data absent. There is no committed `data/dbc` tree. Various `assets` and `Harvested` snapshots contain DBCs; these are not the full active overlay. Server `mod-wxl-dbc` scans `Table.dbc1-project` through tier 9. SQL DBC overlays also affect effective rows. | Extract base data using this server's tools, then install the corresponding custom DBCs/continuations and SQL updates from the same content generation. Preserve continuation order/manifests. Validate effective rows, not just file names or a stock DBC checksum. |
| Maps, vmaps, mmaps and Cameras | Generated from available base input once supplied; custom map closure blocked by absent custom providers. Runtime formats are MAPS version 9/build12340, VMAP_4.8 and mmap version20/Detour7 at this server revision. | Build and run the pinned server's extractors against the exact effective client stack. Supply custom-map data from that same generation. No random AzerothCore data download is assumed compatible. `tools/check_assets.py` performs small header/length reads; it does not establish geographical coverage. |
| Server SQL, modules and Lua | Source is present under `data/sql`, `modules`, and applicable module Lua directories; Eluna is a pinned submodule. Current deployed database contents and custom external scripts are not established by the source tree. | Reproduce schema/base/update order from the pinned source and import matched custom data. Package only enabled module runtime inputs. Keep account/character/bot databases persistent and separate from replaceable runtime. |
| Retail native assets | Acquisition tools/source are present. Complete enabled dependency graphs are not supplied. The example configuration is online and therefore unsuitable as a gameplay configuration. | During explicit setup, use the client `Tools/RetailAssets` acquisition/verification tools against a pinned product/build and source the user can access. Prepare models, skins, textures, external animations and tables. Install original decoded bytes under the local `Data/Retail` store or packed `EsteriaRetail/<product>-<build>/<locale>/<id>.bin`. Use verified `mode=files`/offline configuration for gameplay. Availability of every old CDN object is unverified. |
| Forever assets (including Skyborne) | Separate pinned-source inputs required; not interchangeable with Retail. `config/ForeverCasc.example.ini` uses product `wow_classic_beta`, build `dd3dfc2881c407299f46c2aaf34c130b`, online mode. | Obtain from the matching local source or an explicitly initiated acquisition while available. Preserve independent product/build/cache namespaces. Convert to a complete local source before enabling affected features offline. Do not ship the online example as an active runtime config. |
| Vulkan shader modules | Generated from effective client inputs. No extracted/generated shader outputs are committed by design. Translator source is present in client `Tools/VulkanShaders`. | Run the pinned translator with glslang during setup against the fully installed provider stack and active locale. Keep `VulkanShaders/manifest.txt`, `index.txt`, and referenced `vertex/*.spv`/`pixel/*.spv` with the matching data generation. Source-side precedence tests do not qualify actual shaders. |

## Catalog names consumed by the current client

Selection catalogs: `EsteriaNaga.bin`, `EsteriaTuskarr.bin`, `EsteriaVrykul.bin`,
`EsteriaThinHuman.bin`, `EsteriaSethrak.bin`, `EsteriaGnoll.bin`, `EsteriaSaberon.bin`,
`EsteriaTarasek.bin`, `EsteriaDrakonid.bin`, `EsteriaDarkfallen.bin`, `EsteriaVulpera.bin`,
`EsteriaHighmountain.bin`, `EsteriaEarthen.bin`, `EsteriaHaranir.bin`, `EsteriaKyrian.bin`,
`EsteriaVenthyr.bin`. The reader expects little-endian magic `0x314D4845`, version1,
at most16,384 fixed156-byte selection records, with bounded selectors and terminated paths.

Texture banks: `EsteriaVulperaTextures.bin`, `EsteriaHaranirTextures.bin`,
`EsteriaNagaTextures.bin`, `EsteriaTuskarrTextures.bin`, `EsteriaVrykulTextures.bin`,
`EsteriaThinHumanTextures.bin`, `EsteriaSethrakTextures.bin`, `EsteriaGnollTextures.bin`,
`EsteriaSaberonTextures.bin`, `EsteriaTarasekTextures.bin`, `EsteriaDrakonidTextures.bin`.
These use magic `0x31544845`, version1 and bounded LZNT1-compressed RGBA layers.
Also required for affected appearances: `EsteriaDrakonidCoverage.bin`,
`EsteriaSaberonCoverage.bin`, `EsteriaAppearanceGeometry.bin`.

Historical helper documentation additionally names `EsteriaAppearance.bin`,
`EsteriaAppearanceMaterials.bin`, and `EsteriaCosmeticWings.bin`; do not treat historical helper
requirements as evidence that every current reconstructed-client feature consumes those formats.
The initial custom-content manifest must derive its enabled requirements from the pinned client.

## Effective provider order and shader preparation

The engine's normal full-client mode assigns descending priorities to the base archive table in
`WoW/Source/Client.cpp::OpenArchives`. `common-3.MPQ` is appended at the table's end and has the lowest
base priority. Plain locale/root patches follow the bases. Named root `patch-*.MPQ` and locale
`patch-<locale>-*.MPQ` providers then sort by their full relative paths, case-insensitively, with the
larger path winning. This includes arbitrary suffixes and folder MPQs. It is not sufficient to sort
only `patch-2` through `patch-Z`, nor to assume all locale archives win over all root archives.

The original shader translator omitted arbitrary suffixes, locale archives, folder providers and
`common-3`; the Android client branch now derives provider order from these engine rules. It also
selects MPQ locale entries with neutral fallback. Unsupported alternate archive views, incomplete
listfiles, malformed providers, case collisions and symlinks stop shader preparation explicitly.
It never silently ignores a failed winning provider and emits shaders from older data.

The setup integration must stage shader outputs before activating a content generation and retain
provenance (client revision, translator/tool version, locale and provider fingerprints). It must run
after custom package changes, not every launch. No shader generation has been performed on the
user's data yet. Its Android setup adapter and actual full-data qualification remain outstanding.

## Historical archive integrity evidence

Two public server snapshots cannot currently be accepted as valid classic MPQ inputs:

| File | Actual bytes | Header-declared archive bytes | Raw Git blob SHA-1 |
| --- | ---: | ---: | --- |
| `assets/archives/patch-Z.MPQ` | 24,661,489 | 24,662,061 | `195736b9209ad7750ab88c2c5a7a7e4b0df4b6db` |
| `assets/archives/patch-enUS-Z.MPQ` | 24,726,208 | 24,726,791 | `a555e7784d796caef36e54a753efd88bd058cd87` |

The declared block-table ends exceed the actual files. Local bytes were checked with raw Git blob
hashing (`git hash-object --no-filters` and independent Python SHA-1) and match the repository's
object IDs; this is not a partial local download. The repository's `.gitattributes` forces `* text
eol=lf` and excludes only lowercase `*.mpq`, while these names end in uppercase `.MPQ`. Newline
normalization is a plausible cause, not proven recovery information. Do not attempt speculative
binary repair. Obtain unmodified originals or regenerate from authentic inputs. Other committed
binary packages have not been comprehensively audited here.

The Android integration repository uses `* text=auto` plus case-insensitive binary extension patterns
in `.gitattributes`, including `.mpq`, `.MPQ` and mixed-case spellings. The corresponding server-side
repair would change its forced-text default to `text=auto` and use `*.[mM][pP][qQ] binary` (and other
binary extensions). That server repository is read-only for this assignment; no attributes changes
were pushed there. Changing attributes alone cannot recover bytes already altered in historical blobs.

## Existing checks and remaining gates

`python tools/check_assets.py --server-data <directory>` reports format failures and exits2 when a
required data family is absent or malformed. It reads at most56 header bytes per inspected file,
never hashes entire map sets and never mutates content. Its success means only those format checks
passed. It does not check every DBC field, map coverage, model references, custom appearance closure,
shader rendering, SQL overlay parity, offline cache completeness or in-world behavior.

Missing inputs block only their affected runtime qualification. Continue client platform work,
reproducible builds, import/recovery, process supervision, protocol checks and UI without fabricated
assets. Request the precise missing custom set only after independent implementation is exhausted.
