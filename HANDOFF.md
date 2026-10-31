# Esteria Stock — published low-memory import update

Updated 2026-10-31 UTC. Branch `non-custom`; package `io.github.russianranger.esteria.stock`, profile `stock-3.3.5a`. Version `0.1.0-non-custom.3` / versionCode **3** is published as an additive prerelease. Install over the existing stock app with its current data. No private key or generated APK belongs in Git.

## Published identity

- [Release](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.3) / [direct signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.3/Esteria-Stock-3.3.5a-arm64.apk). Release ID `430162393`; 336,759,229 bytes.
- APK SHA-256: `659bae66e2fcadaaad642dd02ba01564ca9724d2a5190cdf1922f4a9258fd9aa`.
- Persistent certificate SHA-256: `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`. Full anonymous public download, exact length/hash, stock package/code 3/nondebuggable manifest and APK v2/v3 signatures independently verified using Android SDK build-tools 35.0.0. Exact published version 2 was reverified as the previous signing baseline. Device install-over on Thor remains to be observed.
- APK producer/app source: `4b45fc004ce635ece9dc2e13ebeb5cf5f5f3d908`. Publisher: `2b3b1d867e2ed297a6b063e1e3352dc15f083a27`, successful run `41238092829`, job `124646006651`. Later documentation/evidence commits are not APK producers.
- Publication identities are recorded in `runtime/releases/non-custom-v0.1.0-non-custom.3.json`; full APK readback is `runtime/evidence/non-custom-v3-public-apk-readback.json`. All five smaller public assets passed anonymous full-byte hash checks and matched the successful CI artifact; see `runtime/evidence/non-custom-v3-public-assets-readback.json`. The official signing ledger now pins code 3. Future updates require a higher code and this exact public APK as their previous baseline; never use an initial-baseline signing option again. Historical releases/assets and update-2 inputs remain unchanged.

## Report and first-cause limits

The owner reports repeated Android low-memory kills during import after version 2. No new support bundle, exit record, route or exact failing phase accompanied that report. The two old uploaded text files describe version 1's provider-location rejection and contain no LMK evidence. A particular Java/Python allocation is therefore not the confirmed cause of this owner's kill. Import copying/automatic structural compatibility and Python stock preparation are separate phases; Python starts during Prepare/Start.

The update independently removes measured memory costs while retaining version 2's folder/ZIP path corrections. Normal `Wow.exe` + `Data` layout is preserved, as are base/locale/standard patch providers, bounded wrapper discovery, opaque SAF IDs, collision/root rejection, stock selection and ancillary-file decisions. A Data-only selection still needs its parent; correctly placed archives stay inside Data.

## Changes and verification

- Import copying reuses one 128 KiB buffer and ByteBuffer, eliminates duplicate source maps/root lists and temporary UTF-8/digest/length-encoding arrays, consumes resume records and reuses seed buffers. CRC/SHA/header validation, source-change detection, bounded metadata, cancellation and transactional promotion remain. A version-2 partial import resumed the same generation, reused 4 files and copied 7; its next retry reused all 11 and copied zero.
- SAF retains one shared entry per verification record, shares MIME values and releases the finished inventory. Filename/type/MIME/opaque-ID/alias/source checks remain. Progress formatting is capped at 5 Hz and unchanged UI text is reused. Neither IO nor the Android heap limit is increased or slowed to conceal pressure.
- Import diagnostics sample Java used/observed peak/limit/timestamp. Bounded own-package Android exit history includes reporting capability, reason/status/time/importance and last sampled PSS/RSS; trim/current importance/foreground-role facts accompany it. SIGKILL, crash or high RSS alone is not labeled a confirmed LMK/Java OOM. Fatal Java Errors preserve the interrupted-import recovery marker.
- Stock content inspection retains packed MPQ tables, preserving the exact pinned reader's header/lookup/member decoding. Per-provider extents are checked before allocation; the historical retained-provider budget and content-confirmed optional exclusions remain. One candidate gets bounded temporary headroom. Malformed oversized stored member reads are bounded before allocation. Provider bytes, source locks and archive semantics remain unchanged.
- All 42 importer groups pass. Short-read host allocation for 64/256 MiB formerly grew from 4,472,464 to 15,482,608 bytes; revised allocation stays near 482 KB for either size. Both public routes import 128 MiB at a 12 MiB host heap with matching SHA/CRC. See `runtime/evidence/non-custom-import-memory-host.json`.
- All 18 focused stock tests pass against configured JDK and the exact pinned reader, including six public folder/ZIP-to-preparation pipelines. Large-table fixture RSS fell from 279,588 to 36,564 KiB (86.9%), with identical reports; optional-over-budget data remained accepted/excluded correctly. See `runtime/evidence/non-custom-stock-inspection-memory-host.json`. This reduction covers stock inspection; later shader translation still uses its unchanged reader and is not covered by this figure.
- Final Python suite: **1,468 passed, 108 explicit dependency skips**. Strict Android-only Java/API compilation passed. Android 13 x64 run `41236388434`, job `124640956536`, artifact `13055781447` passed five memory/exit tests plus existing SAF/update/helper contracts. Independent readback checked all 33 artifact members, five named successes, three measurement records, nine source identities and the actual logged runner source. Evidence: `runtime/evidence/non-custom-import-memory-android13{.json,.log,-readback.json}`.

| Android 13 generated fixture | Elapsed | Observed Java growth | Native growth | PSS growth |
| --- | ---: | ---: | ---: | ---: |
| 1 GiB folder import | 10.710 s | 1,071,432 B | 64,080 B | 2,421,760 B |
| 1 GiB nonseekable ZIP staging + import | 26.229 s | 1,230,648 B | 291,936 B | 474,112 B |
| 3,210 opaque documents | — | 155,712 B | 408,752 B | 2,628,608 B |

Both 1 GiB payload hashes match. These are observed component deltas from representative fixtures, not total process memory, owner-data execution, maximum accepted inventory or proof that a Thor kill was eliminated.

## Build and architecture

Full ARM64 package run `41236388424`, job `124640987755`, artifact `13055367592` passed at the exact APK producer. Unsigned package ZIP SHA-256 `cb0942d4fcf6be0daff760ae42e35b2f43d97943e1900cef4455c45db8716113`. Public signature recipe reconstruction reproduced the signed bytes exactly; CI independently rechecked provider/payload/native/SDK proof before publication.

Native ARM64 SQL run `41236388396`, job `124640956699`, artifact `13055467841` passed the stock policy, Human starting row, reentry/restart and clean-stop checks at the same producer. Generic launcher/core/owner/lint runs `41236388456` (producer) and `41238092798` (publisher) passed. Publication tooling run `41238093155` passed. These checks do not qualify graphical startup, worldserver/gameplay or Thor behavior.

Client remains `471ee42faadf4a97a1d0a86989cf1452621f2dc5`; server `f35f04d01689f034778e3474b3c820092f51e461` plus its seven pinned adaptations; Eluna `58d7652138887783228b9727bd1fa4e08f00342b`. The reconstructed ARM64 client/Wine in Debian 12 PRoot and Linux ARM64 server/MySQL in Ubuntu 24 PRoot remain. No original x86 client substitution, custom/HD dependency, source-file mutation or save reseeding.

## One substantial owner test

Update app → retry one import route using the same complete client source → Prepare local runtime / world → Start local game → Human Warrior/world entry → clean stop/relaunch → offline repeat. Keep `Wow.exe` beside `Data`; ordinary MPQs remain beneath Data. Do not uninstall, clear data, move MPQs or rebuild the ZIP. Completed files are reused when source metadata supports resume. See `NON-CUSTOM-TESTING.md`.

If Android kills it again, **reopen and Export support bundle before starting another import** to preserve the last receipt. Include the whole bundle, last displayed stage/file, `status.txt` and `launcher.log`; the new exit-history and sampled-memory facts identify the recorded reason and its limits. Preserve completed import/preparation state. Actual owner data, Thor rendering/world entry/controller/audio/persistence remain the device qualification boundary.
