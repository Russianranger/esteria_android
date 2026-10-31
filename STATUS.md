# Esteria Stock — version 4 published

Updated 2026-10-31. Branch `non-custom`; package `io.github.russianranger.esteria.stock`. Signed **0.1.0-non-custom.4**, versionCode **4**, installs over the existing stock app with the same persistent certificate and app data.

- [ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.4/Esteria-Stock-3.3.5a-arm64.apk) / [release and instructions](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.4).
- APK: 336,767,421 bytes; SHA-256 `af4b77d9ad183e8a4855a9bcce0644da2276e1d6309bb86d0727691ad79e1b29`.
- Certificate SHA-256: `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.
- APK producer `2c8eeb08a3079edf7354cd373b7cbaf94d859365`; publisher `8d0ba78bed3256b5eee3340b62fe1c8de41c3d52`, successful run `41241976822`. Release ID `430186739`. Anonymous complete APK download, hash, manifest and SDK v2/v3 signature/certificate checks passed. All six public assets were read and checked.

## Import change

Both folder and ZIP routes share an 8 MiB/s governor, including ZIP staging/extraction, nonseekable resume consumption and fallback overlay copies. Small output batches are forced before advisory clean-cache release. Regular SAF sources also receive cache advice. Android memory/headroom/heap/trim observations reduce copying to 2 MiB/s or wait before further I/O; sustained severe pressure produces a resumable pause after 60 seconds. Cancellation is checked within 100 ms sleep slices. UI-hidden callbacks alone do not count as pressure. Existing validation, transactional promotion and source/resume fingerprints remain unchanged.

This targets sustained I/O/cache/writeback pressure outside v3's Java-allocation changes. No fresh owner kill bundle was supplied, so the Thor exit cause is not confirmed. Diagnostics retain speed, system memory/headroom, Dirty/Writeback and advice results. Kernel acceptance of advice does not guarantee a number of reclaimed pages.

## Validation

- Six governor groups; 42 existing importer groups; bounded allocation/ZIP metadata tests and actual folder/ZIP cancellation/resume/hash continuity. Core checks, Android compile/lint, JNI/libc byte-preservation tests and Android ARM64 bridge cross-build passed.
- Full host Python discovery: 1,468 run, 1,360 passed, 108 dependency skips, no failures. Exact producer complete ARM64 package `41240790028`, native SQL `41240789998`, Android13 `41240790022`, launcher `41240789955` and tooling `41240790024` passed.
- Android13 x64 readback checked 33 artifact members, 14 source identities and nine named test successes. The 1 GiB folder route took 142.432 s with 521 accepted cache calls; nonseekable ZIP staging/import took 272.448 s with 1,007 accepted calls. Both had zero advice errors and identical payload hashes. Representative fixtures are not owner data or a real LMK reproduction.
- Publication checks, exact signed reconstruction and public readback passed. A later publisher-revision tooling run exposed an unrelated flaky assertion matching digits in a generated test password; the test-only correction is `7c38f27756eac24821cd848ee59d475acfba0bdc`, preserving APK/runtime bytes.

Evidence: `runtime/evidence/non-custom-v4-*`; publication identities: `runtime/releases/non-custom-v0.1.0-non-custom.4.json`. The signing ledger now pins the verified public v4. Future updates require a higher version and this exact APK as the previous baseline; preserve historical releases and update-4 transport.

## Device boundary

Install over the existing app, retain data, and retry the same complete client source with `Wow.exe` beside `Data`. Each 1 GiB copy takes at least 128 seconds; ZIPs add staging. On a memory pause retry after recovery. If Android closes it again, reopen and export support before another import, including last stage/file. Continue preparation/start only after import succeeds; see `NON-CUSTOM-TESTING.md`.

Actual Thor import, graphical startup/world entry, controller/audio and persistence remain unqualified. Client stays `471ee42faadf4a97a1d0a86989cf1452621f2dc5`; server stays `f35f04d01689f034778e3474b3c820092f51e461` plus seven pinned adaptations. Custom/HD content and bot AI remain deferred.

The corrected full tooling CI run `41242372352` passed at test-only revision `7c38f27756eac24821cd848ee59d475acfba0bdc`; see `runtime/evidence/non-custom-v4-tooling-fixture-fix.json`.
