# Non-custom stock asset scope

The default branch profile is `stock-3.3.5a`. Supply complete original build12340 `Wow.exe` and `Data` with one complete locale/speech set, preserving Blizzard root and locale patch archives. Generate matching DBC/maps/vmaps/mmaps/Cameras and Vulkan shaders in-app. Extra Esteria/HD/challenge MPQs, custom catalogues/races/maps and Retail/Forever assets are deferred; none is a stock startup prerequisite.

Actual owner bytes have not been supplied here. Import structural reporting, decoded MPQ/DBC/UI/shader inspection and actual client/server/world execution are separate evidence levels. The retained custom inventory below applies only when those deferred features are deliberately restored. Keep original source files/realmlist/accounts unchanged and genuine UI signatures enabled.

# Esteria asset requirements

Audit updated: 2026-10-30 UTC; source availability remains distinct from runtime qualification. Client baseline
`471ee42faadf4a97a1d0a86989cf1452621f2dc5`; server baseline
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
| Optional private server Custom C++ scripts | Unavailable optional source: the pinned `src/server/scripts/Custom` tree contains only README; `.gitignore` excludes private additions. No `AddCustomScripts` implementation is supplied. | The build omits source-empty script directories and still requires a real loader for any populated directory. No empty loader is substituted. Qualify any later supplied custom scripts against the same server revision and content; this does not establish that private scripts were active in the deployed world. |
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
user's data yet. Its retained Android setup adapter compiles and passes owner/helper checks; actual full-data generation and rendering remain unqualified.

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

## Source-backed server content checkpoint

`runtime/SQL-PACKAGING.md` records the exact source inventory, compiled-module
binding check and GNU archive packager. The source-profile archive readback
passed for 4,060 entries / 654,046,522 bytes. It contains available updater SQL,
config templates and notices, not an initialized database or complete deployed
content. All 20 discovered server-Lua candidates have explicit dependency decisions
in `runtime/server-lua-map.json`; the intermediate profile disables Lua until
matching AIO, schemas, custom races/maps and appearances can be qualified.
The full Esteria script and custom-content requirements remain open.

## Generated local runtime inputs

The source-built X11 frame/XTest helpers and ALSA PCM plugin are under
`native/guest-bridges`, with pinned Debian12 ARM64 inputs and corresponding sources
in `runtime/bridges`. These are generated runtime components, not substitutes for
missing game assets. Their new CI build/execution gates remain separate from client
data, DBC, shaders, full-game audio and Adreno qualification. The Ubuntu ARM64
MySQL dependency archive has passed native image, archive readback, source capture
and host staging; `runtime/server/README.md` records its exact identities.


The exact source-backed shader tool provider is now generated and durably
published (`runtime/shaders/RELEASE.md`), including compiler originals/notices and
the pinned translator. Its APK installer is wired into client-runtime preparation.
This resolves tool availability only: no user MPQ shaders have been generated or
rendered. The optional Turnip driver also packages from verified source/build
receipts; native no-GPU loading is separate from actual Adreno execution. Neither
component supplies missing maps, DBC overlays, appearance banks or game data.


The seven-patch server content provider now preserves the exact source-selected
SQL/configuration/notices package (4,063files/654,243,888bytes), independently of
user client assets and mutable saves. Its original archive/receipt/module build
bindings and actual Java/APK readback are recorded in
`runtime/evidence/server-content-android-packaging-host.json`. This resolves
available source SQL packaging; it supplies no missing MPQs, DBC overlays, maps,
appearance banks or generated shaders. The Lua-disabled policy remains explicit.


Loose selection catalogs now receive bounded source-derived structural checks
during import, with failed overlays preserving the active generation. See
`runtime/client/CATALOG-IMPORT.md`. Binary MPQ contents, texture-bank decompression,
geometry/coverage and referenced-art completeness remain separate validation;
these checks do not resolve the missing actual catalog inputs.

The transactional data-generation helper now composes the ordered extractors and
original assembler/navigation tools in separate resumable phases. Available code
and passing host storage/process contracts do not resolve absent base/custom
MPQs. No maps, vmaps, mmaps, Cameras or matching DBC overlays have been generated
from user data. See runtime/server/DATA-PREPARATION.md for the supported classical
profile and remaining custom overlay/coverage/Android gates.

Completed generated data now retains its exact effective-provider manifest and
wire projection, with source/import/tool-selection identities. The APK includes
the preparation/preflight helper closure; this is code availability, not generated
world data. Real base/custom inputs and matching DBC overlays remain unavailable.

Current matched authentication and native database setup succeed without game
assets; their receipts explicitly exclude CommonMain/world. No available-code or
source-provider result supplies absent base/custom MPQs, appearance banks, DBC
overlays, geographical coverage or generated shaders. These remain actual data
validation gates after the ongoing independent integration work.

The launcher setup pipeline can now compose data, shader and SQL adapters under
one retained import lease. This adds no game inputs or prepared content: real
12340/custom MPQs, matching overlays and actual conversion/coverage remain open.

The integrated service/client/control code and complete public runtime source
cohort add no game assets. Normal client initialization/world, actual generated
shaders/maps and Esteria content validation still require real imported inputs.

## Matched server-data injection

The Add custom content folder/ZIP route now accepts a strict reserved
`EsteriaServerData/manifest.properties` plus `EsteriaServerData/data/` namespace.
See `runtime/server/IMPORTED-SERVER-DATA.md` and the exact manifest example in
`config/server-data-inputs.example.properties`. This is a user-supplied data
declaration with format checks, not independent source or gameplay qualification.

Small DBC/continuation overlays are applied to generated data before atomic
promotion; complete supplied data can bypass conversion when all required
format families are present. Existing import metadata limits still apply, so
large precomputed full-world sets can be refused. Generating from imported MPQs
plus a small matched continuation package remains the bounded supported route.
A replacement namespace removes stale previous continuations; unrelated client
overlays retain the current server-data selection. Runtime inputs bind imported
ancestry, the exact manifest, optional client provider order and preparation
helper identity. No unavailable bytes are synthesized.

The actual server continuation path is `data/dbc-continuations/`, including its
optional `wxl-dbc.manifest`. Tier/manifest/project/table order and matching base
WDBC layouts are validated. This supplies the server module only. Current client
DBC loading consumes full effective DBC files from the client provider stack;
server continuation fragments alone do not qualify matching client rows. A
working custom package must supply those full client tables where required.

Misplaced root MPQs, wrapped custom MPQs and archives outside the actual engine
provider locations are rejected with corrective instructions. Loose catalogs
remain client-root Esteria*.bin or virtual Esteria paths inside effective MPQs.
All content compatibility, coverage and Esteria-specific behavior still require
the matched user assets and actual game execution.

Known supplied base/locale/continuation DBC files now receive exact field-count
and packed disk-stride checks derived from the112 active stores at pinnedf35.
All stores have SQL fallback, so absence is not converted into an invented
mandatory-file list. Unknown custom tables retain structural-only checks. These
checks reject incompatible layouts early; they do not qualify rows, SQL overlays,
world coverage or matched client/custom content. See runtime/server/DBC-PREFLIGHT.md.

## Minimum for a first classic validation

The practical first external input is the user's original build 12340 `Wow.exe`
and complete `Data/` directory, including one complete installed locale. Preserve
the original signed UI and ordinary model, texture, world, font and audio data.
Account folders, saved passwords, logs, an initialized database and precomputed
server maps are unnecessary for this first input. The app supplies its rebuilt
client/runtime and local account configuration separately.

At exact client `471ee42faadf4a97a1d0a86989cf1452621f2dc5`, conventional full-client
startup requires `Data/common.MPQ`, `Data/<effective-locale>/locale-<locale>.MPQ`
and `Data/<effective-locale>/speech-<locale>.MPQ`. `WoW/Source/Client.cpp` marks
these kind1/availability2; failed `OpenArchiveWithRetry` reaches the nonoptional
error branch and `StormExit` (lines 1445–1472). Other archive-table entries marked
kind2 are optional to this engine branch. The importer's existing seven root-MPQ
checks intentionally admit a conventional layout; they do not prove that every
later engine requirement is satisfied. Keep the complete stock set rather than
trimming it to that filename checklist.

The existing setup helper already rejects a missing speech archive for the
selected effective locale: `runtime/extractor_order.py` projects the same table
and required/optional rules, and `runtime/server_data_generation.py` creates that
plan before extractor processes. It selects the locale with the client's rotation
rules and does not require speech archives for unused locales. No additional
production check or optional-archive requirement was added by this audit.

Normal initialization also requires authentic virtual `signaturefile`, the stock
`DBFilesClient/*.dbc` stores and the signed `Interface/GlueXML/GlueXML.toc` and
`Interface/FrameXML/FrameXML.toc` content closures. These are supplied by genuine
client data, not reconstructed from code. The retained selected471 producer cache
confirms signature checks remain enabled and `WOWDECOMP_RETAIL_ASSETS=OFF`.
Retail/Forever data is therefore outside this selected binary's classic first
pass; later enabled features still require their complete offline dependencies.

Missing `Esteria*.bin` catalogs are not a global CommonMain/Glue abort condition.
At this same revision, `WoW/Common/ComponentCore/EsteriaAppearance.cpp` treats a
missing virtual `Esteria/<name>` or executable-adjacent `<name>` as an empty
catalog. The affected custom race can lack textures, coverage or required model
geometry; this is no assurance that it renders correctly. Classic races retain
their normal CharSections path. Existing packers mostly repackage external
catalog/model inputs. Drakonid coverage has a source recipe from the effective
`ItemDisplayInfo.dbc`, but it has not been generated from user data here.

The app can attempt maps/vmaps/mmaps/Cameras and Vulkan shader preparation from
the genuine imported stack. Supported formats, complete shader listfiles, matching
locale/provider order and actual conversion remain gates. It does not require
the user to send generated outputs in advance. Full Esteria validation still needs
the matched custom MPQ/model/catalog closure and any corresponding server DBC
overlays/continuations for the features and world content under test. The first
classic input permits that independent startup work while those custom features
remain unqualified. See `runtime/evidence/classic-asset-minimum-471-audit.json`.

The matching server's normal startup is also source-plausible with that complete
stock input, generated stock DBC/maps/vmaps/mmaps/Cameras and its initialized
matching database. At pinned `f35f04d01689f034778e3474b3c820092f51e461` plus the
seven bound adaptations, the audited fatal asset gates check stock starting-area
maps/vmaps and required base DBCs with stock12340 sentinel rows. The enabled WXL
hook explicitly accepts an absent or empty continuation directory; race/player
and bot creation filter available DBC/PlayerInfo/appearance entries. No globally
fatal custom-catalog/MPQ requirement was found in these inspected paths.

This adds a server source audit to the client-only minimum; it is no world-startup
or gameplay evidence, and it does not qualify custom races/maps or appearance
features. Keep the full Esteria objective and matching custom inputs active;
the unavailable custom bundle need not block a first coherent classic candidate.
Exact source and seven-patch bindings and the three findings are recorded in
`runtime/evidence/stock-server-minimum-f35f-audit.json`. No schema, source, feature
policy or module selection was changed by this audit.

## Recommended full Esteria input set

Use the complete build 12340 client with its original MPQs and the matching
Esteria client MPQ stack. Import the folder containing `Wow.exe` and `Data/`.
Add only the small matched server DBC/continuation overlay through
`EsteriaServerData/` in `mode=overlay`. Then let **Prepare local world** generate
maps, vmaps, mmaps, Cameras and Vulkan shaders from that effective client stack.
This route keeps the many generated world files outside the Java import
inventory and does not require the user to initialize or administer MySQL.

The 16 MiB limit is an estimated budget for concurrently retained import
metadata, not a game-data byte limit or a fixed supported file count. Path
length, provider document IDs, directories, validation maps and resume journals
all contribute. A few large MPQs can be streamed; tens of thousands of loose
precomputed world files or folder-MPQ members can exceed the budget before
copying. The existing `mode=complete` route remains available only within that
budget. A large loose-world importer with a disk-backed inventory is not
implemented; splitting a replacement server namespace into sequential packages
would remove earlier namespace files and is not a workaround.

Select the language actually installed in the client. The app now resolves the
client reader's twelve-locale availability rotation before invoking its older
pinned shader tool, retains the requested and effective locales separately and
requires server data and shaders to use the same effective locale/import.
The pinned shader tool supports ten locale encodings: a winning `enCN` or
`enTW` locale is explicitly unsupported, rather than silently selecting a
different provider stack. This source-level correction is not actual shader
or world qualification on supplied game data.

The selected client471 build keeps `WOWDECOMP_DISABLE_SIGNATURE_CHECKS=OFF`.
Its normal startup authenticates `signaturefile`, signed GlueXML/FrameXML TOCs
and their loaded content. Import/header success does not establish that a
modified or unsigned winning UI will load. Qualify the actual effective
`Interface/GlueXML` and `Interface/FrameXML` closure with this exact binary;
retain original signed UI when no custom UI is required. Missing, corrupt or
modified signatures can prevent Glue/world UI initialization. No failure on
the user's unavailable files has been observed, and no signature policy was
changed by the import or locale work.
