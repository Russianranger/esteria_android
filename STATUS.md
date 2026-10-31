# Version 4 import memory-pressure update

The active update is versionCode 4 on `non-custom`, package `io.github.russianranger.esteria.stock`, preserving v3 certificate/data and exact client/server/runtime pins. It is undergoing validation/publication; historical v3 identities below remain the published baseline until verified readback.

Both public routes share an 8 MiB/s I/O governor. ZIP staging/extraction, folder copy, fallback overlay copy and nonseekable resume consumption are paced. Output is forced every 2 MiB before advisory clean-cache release; regular SAF input windows receive advice too. Android memory/headroom/heap/trim observations reduce copying to 2 MiB/s or wait before more I/O. Sustained severe pressure pauses safely after 60 seconds; Stop is checked in at most 100 ms sleep slices. UI-hidden callbacks alone are not pressure.

This addresses sustained I/O/cache/writeback pressure outside the previous Java-allocation measurements. No fresh owner kill bundle accompanies this report; the Thor exit cause is not confirmed. Receipts retain policy, system memory, Dirty/Writeback and cache-advice facts. Advisory acceptance does not guarantee reclaimed bytes. Existing validation, transactional publication and resume fingerprints remain.

Host checks cover pacing, pressure recovery/pause, interruption, sync-before-advice and actual folder/ZIP cancellation/resume with unchanged generation/hash. JNI/libc advice preserves synced-file bytes and descriptor ownership; the bridge cross-builds for Android ARM64. Android 13 tests build the x64 bridge and exercise the actual controller with 1 GiB folder/ZIP fixtures and timing/cache/hash assertions. Final results/publication identities follow after verification; fixtures are not Thor qualification.

Install the eventual v4 over the existing app, retain data and retry the same full client source. Keep `Wow.exe` beside `Data`. Each 1 GiB copy takes at least 128 seconds; ZIPs need staging plus extraction. On a memory pause, retry after recovery. If Android closes the app again, reopen and export the whole support bundle before another import, including last stage/file.

# Esteria Stock — version 3 published

Updated 2026-10-31 UTC. `non-custom` now has a signed low-memory import update: **0.1.0-non-custom.3**, versionCode **3**, package `io.github.russianranger.esteria.stock`. The same persistent certificate permits updating the existing stock installation while keeping app data.

- [Direct ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.3/Esteria-Stock-3.3.5a-arm64.apk) / [prerelease and instructions](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.3).
- APK: 336,759,229 bytes; SHA-256 `659bae66e2fcadaaad642dd02ba01564ca9724d2a5190cdf1922f4a9258fd9aa`.
- Certificate: `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.
- APK source: `4b45fc004ce635ece9dc2e13ebeb5cf5f5f3d908`; publisher: `2b3b1d867e2ed297a6b063e1e3352dc15f083a27`, run `41238092829` / job `124646006651` succeeded. Full anonymous public APK download, hash, manifest, v2/v3 signatures and prior-version certificate continuity were independently checked. Device install-over is still to be observed.
- Release record: `runtime/releases/non-custom-v0.1.0-non-custom.3.json`; public APK verification: `runtime/evidence/non-custom-v3-public-apk-readback.json`. The five smaller public assets also matched their CI artifact and public hashes; see `runtime/evidence/non-custom-v3-public-assets-readback.json`. Signing ledger advanced to code 3 after that readback. Old releases/assets and update-2 inputs remain preserved.

## What was fixed

Import copying now avoids per-read wrapper/encoding allocations, duplicate source inventories and retained consumed resume entries. SAF shares verification metadata, releases settled inventories and limits progress-formatting churn. Existing CRC/SHA/source/path/header checks, bounded memory, streamed copying, cancellation, transactional promotion and version-2 resume remain. Normal client Data layout and all version-2 folder/ZIP fixes are preserved.

Stock content inspection now keeps MPQ tables packed and checks extents before allocation while retaining archive/optional-provider semantics. A representative large-table fixture used 86.9% less peak host RSS with identical results. That measurement does not cover later shader translation, which retains its existing reader.

Support bundles now include sampled import Java memory, bounded own-package Android process-exit history/reporting capability and trim/importance/foreground facts. Fatal Java Errors preserve the interrupted marker. An unexplained SIGKILL is not presented as confirmed low memory.

## Validation

- All 42 importer groups; both public routes at a 12 MiB host heap with 128 MiB payloads; old-generation resume reused completed files correctly.
- 18 focused stock tests, including six actual folder/ZIP-to-preparation pipelines; final Python suite 1,468 passed / 108 dependency skips; strict Android-only API compilation.
- Actual Android 13 x64 tests: five memory/exit successes, 1 GiB folder and nonseekable ZIP routes with matching payload SHA, plus 3,210 opaque files. Observed Java growth was 1,071,432 / 1,230,648 bytes; native growth 64,080 / 291,936 bytes. Measurements, source checks and independent artifact readback are in `runtime/evidence/non-custom-import-memory-android13*`.
- Exact-source full ARM64 package `41236388424`, native ARM64 SQL `41236388396`, Android `41236388434`, launcher/core/owner/lint `41236388456` publisher launcher/lint `41238092798`, tooling `41238093155` and publication `41238092829` all passed. Native SQL checks cover stock setup/Human start row/reentry/restart/clean stop, not world entry.

## Remaining evidence and device test

No fresh kill bundle or exact failing phase was supplied. The old uploaded v1 reports contain no LMK record. The owner's Thor failure has therefore not been reproduced or proved eliminated; measurements are representative component fixtures, not owner assets or total-memory guarantees. Actual data preparation, Thor graphical startup/world entry/controller/audio/saves remain unqualified.

Update app → retry one import with the same source and normal `Wow.exe` + `Data` layout → Prepare local runtime / world → Start local game → Human Warrior/world entry → clean stop/relaunch and offline repeat. Keep all app data and completed work. If killed again, reopen and **Export support bundle before another import**, including the last stage/file, `status.txt` and `launcher.log`.

Client remains `471ee42faadf4a97a1d0a86989cf1452621f2dc5`; server `f35f04d01689f034778e3474b3c820092f51e461` with the existing seven adaptations; Eluna `58d7652138887783228b9727bd1fa4e08f00342b`. Reconstructed ARM64 client/local server architecture and stock/offline objective remain unchanged. See `HANDOFF.md` and `NON-CUSTOM-TESTING.md` for complete identities, evidence and the single device procedure.
