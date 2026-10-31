# Esteria Stock — low-memory import update (version 3)

Updated 2026-10-31 America/Chicago. Branch `non-custom`; package `io.github.russianranger.esteria.stock`, profile `stock-3.3.5a`; signed candidate `0.1.0-non-custom.3`, versionCode3. Full provider build, Android memory stress and signing passed; additive publication/public download readback are pending this checkpoint. No private key or generated APK belongs in Git.

## Exact candidate identity

- APK producer/app source: `4b45fc004ce635ece9dc2e13ebeb5cf5f5f3d908`. Full package run `41236388424`, job `124640987755`; unsigned ZIPartifact `13055367592` SHA`cb0942d4fcf6be0daff760ae42e35b2f43d97943e1900cef4455c45db8716113`.
- Signed APK 336,759,229 bytes; SHA256 `659bae66e2fcadaaad642dd02ba01564ca9724d2a5190cdf1922f4a9258fd9aa`; certificate `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`. SDK35 verifies package/version/nondebug manifest, v2/v3 signatures and unchanged payload. Exact published version2 was verified as previous baseline; local public-recipe reconstruction also matches byte-for-byte. Actual Thor install-over is unqualified here.
- Native ARM64 SQL run `41236388396`, job `124640956699`, artifact `13055467841` passes exact same producer, stock policy/Human starting row, reentry/restart/clean stop; worldserver/gameplay remain unqualified.
- Android13 x64 run `41236388434`, job `124640956536`, artifact `13055781447` passed all5 memory/exit tests plus existing SAF/update/helper contracts. Independent readback verified 33members,5named successes,3measurements and9source hashes.
- Generic launcher/core/owner/lint `41236388456` passed all42importer groups and low-heap import/ZIP regressions. FinalPython1468 passed/108dependency skips; focusedstock18 passed with configuredJDK and exact reader source.

## Report and evidence boundary

The owner reports repeated Android low-memory kills during import after version2. No new support bundle, exit record, route or exact failing phase accompanies this report. The two old uploaded text files describe version1's provider-location rejection and contain no LMK evidence. Do not label a particular Java/Python allocation as the confirmed cause of this owner's kill. Import copying/automatic structural compatibility and Python stock preparation are separate phases; Python starts only during Prepare/Start.

## Implemented reductions

- Core import still streams through one128KiB buffer, verifies SHA256/ZIP CRC, enforces the16MiB metadata budget, source changes and paths, and promotes transactionally. The transfer ByteBuffer is reused instead of allocated for every read. Duplicate original-source lookup maps and root-discovery lists are removed; UTF8 budget/length encoding and digest formatting avoid temporary arrays/Formatter objects. Consumed resume records and fallback seed buffers are released/reused. ZIP name scratch storage is reused.
- SAF shares the original InputEntry with its retained verification record instead of duplicating file metadata; MIME values are shared and the finished inventory is released. Exact filename, MIME, type, opaque-ID, alias and source-change checks remain. Status formatting is capped at5Hz and unchanged text is not rebuilt in TextViews; IO speed is not throttled. The Android heap limit is unchanged.
- Import receipts record sampled Java heap, observed peak/limit and timestamps. Support export records bounded own-package Android exit history, explicit LMK reporting capability, reason/status/importance and last sampled PSS/RSS. SIGKILL/crash/large RSS alone are not claimed as LMK or Java OOM. Memory-trim/current importance/foreground-role facts accompany them. A fatal Java Error no longer clears the interrupted recovery marker.
- Stock preparation retains MPQ tables as packed decoded bytes with the exact pinned reader handling header discovery, lookup and member decoding. Cipher/endian/v0/v1/high-word behavior remains tested. Per-provider extents are checked before table allocation; the old retained-provider count policy is preserved, including content-confirmed optional exclusions. One bounded candidate has temporary headroom; closed optional candidates are released. Malformed oversized stored member reads are bounded before allocation. Frozen provider bytes and all source locks remain unchanged.

## Validation to date

- All42 importer groups pass. A64/256MiB short-read fixture formerly allocated4,472,464/15,482,608B, now approximately482KB for either size. This is host total allocation, not Android peak RSS.
- Real public folder/ZIP128MiB fixtures pass at12MiB heap with matching SHA256/CRC. An interrupted version2 import resumes its exact generation, reuses4 completed files and copies7; the following retry reuses all11/copies zero. See `runtime/evidence/non-custom-import-memory-host.json`.
- Stock inspection's final18tests pass, including six actual Java folder/ZIP-to-preparation pipelines and exact baseline/fixed reports. Large-table host RSS falls279,588→36,564KiB (86.9%),3.19→2.66s. Optional-over-budget data remains accepted/excluded correctly, with identical238DBC/UI/shader/provider reports. See `runtime/evidence/non-custom-stock-inspection-memory-host.json`. These are encrypted synthetic MPQs, not owner assets.
- Full final Python suite:1468tests passed,108 explicit dependency skips. Strict Android-only Java/API compilation passed production and SAF/exit tests; the memory fixture also compiles against the actual Android API.
- Added actual Android13 tests for1GiB generated pipe-folder and nonseekableZIP imports,3200 extra opaque documents (3210files), Java/native/PSS samples and real persisted import diagnostics. No whole-client bytearray is generated. All five memory/exit tests and three measured records passed in CI. These component tests do not claim a real LMK was reproduced or eliminated on Thor.

Full ARM64 packaging and Android stress execution passed; the signed candidate is ready for additive publication. Android measured1GiB folder import10.710s with1,071,432B Java/64,080B native/2,421,760B PSS observed growth;1GiB nonseekableZIP staging+import26.229s with1,230,648B Java/291,936B native/474,112B PSS growth;3210files stayed bounded. Both payload hashes match. See `runtime/evidence/non-custom-import-memory-android13.json`, `.log` and `-readback.json`. These are observed component deltas, not total process memory, real owner-data execution or proof that a Thor kill was eliminated. Keep prior version2 available: https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.2 (APK SHA8caaeb58ccb658fa6fd13d0c7ba77f43c2285dd487cbbcdcd9503e4bff34823a).

## Architecture and continuity

Client remains `471ee42faadf4a97a1d0a86989cf1452621f2dc5`; server `f35f04d01689f034778e3474b3c820092f51e461` plus its seven pinned adaptations; Eluna `58d7652138887783228b9727bd1fa4e08f00342b`. Retain ARM64 reconstructed client/Wine in Debian12 PRoot and Linux ARM64 server/MySQL in Ubuntu24 PRoot. No original x86 Wow.exe substitution, custom/HD dependency, source-file mutation or save reseeding. Ordinary client layout and all version2 import-path fixes remain active.

Sign code3 with the persistent certificate5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa and exact published version2 APK as prior baseline. The official ledger remains code2 until public version3 readback succeeds. New public signatures/provenance use `runtime/releases/non-custom/update-3/`; update-2 and earlier assets remain unchanged. Later publication/test/evidence commits must not be substituted as the APK producer.

## One owner test after publication

Install the final signed update over the stock app; keep app data and select the same source to reuse completed work where provider metadata supports resume. Do not uninstall, clear data, move MPQs or rebuild a ZIP. Retry one import route, then Prepare local runtime/world → Start local game → Human Warrior/world entry → clean stop/relaunch and offline repeat. Actual owner client data, extraction, Thor rendering/world entry/controller/audio/persistence remain unqualified here.

If Android kills it again, reopen and export the whole support bundle BEFORE starting another import, preserving the last receipt. Provide the last displayed stage/file plus status.txt/launcher.log; the exit-history and sampled memory fields distinguish reported reasons and their limits. Avoid manually clearing completed import/preparation state. No developer task is considered complete merely because compilation passes.
