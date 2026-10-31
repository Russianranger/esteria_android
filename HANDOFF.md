# Esteria Stock v4 handoff

Version `0.1.0-non-custom.4` / code 4 is published. Package `io.github.russianranger.esteria.stock`; retain data and update over v3. [Download](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.4/Esteria-Stock-3.3.5a-arm64.apk). Full publication and verification identities are in STATUS.md and `runtime/releases/non-custom-v0.1.0-non-custom.4.json`.

## Producer and update identity

APK source `2c8eeb08a3079edf7354cd373b7cbaf94d859365`; publisher `8d0ba78bed3256b5eee3340b62fe1c8de41c3d52`; successful package run/job `41240790028` / `124654094771`; native SQL `41240789998` / `124654064489`; Android 13 `41240790022` / `124654064524`; publication `41241976822` / `124657555352`. Public release `430186739`, APK asset `696483916`. APK bytes 336,767,421; SHA-256 `af4b77d9ad183e8a4855a9bcce0644da2276e1d6309bb86d0727691ad79e1b29`; certificate `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.

Anonymous full APK and all six public assets passed readback. The SDK reverified the downloaded nondebug stock code 4 manifest and v2/v3 signatures. The exact previous v3 APK was checked before signing. The ledger advances to v4 only after this verification; future updates must increase the code and use the exact published v4 baseline. Never use initial-baseline or overwrite historical release assets. Public update-4 signature/receipt/selection files are immutable historical transport; their producer/publisher retain the old baseline-3 lock binding.

## Import implementation

`ImportIoGovernor` applies a shared 8 MiB/s budget, 2 MiB sync thresholds, final durable sync, pressure waits and cancellable 100 ms sleep slices. `ImportIoController` samples actual Android system/heap/trim pressure at most once per second, selects 2 MiB/s or waits, and retains bounded diagnostics. Sustained severe pressure raises a distinct memory pause after 60 seconds. The production service explicitly supplies this controller to folder and ZIP paths; existing unpaced constructors serve host fixtures. ZIP pre-copy and nonseekable resume reads use the same governor; fallback overlay copying is covered.

`NativeImportCache` uses source-built JNI `posix_fadvise(DONTNEED)` in `esteria_process` after sync. Unsupported advice preserves pacing/sync. Regular SAF descriptors receive source advice with origin offsets and terminal close ownership. No file bytes are truncated by advice. Acceptance is not an actual reclaimed-page measurement. Existing path/CRC/hash/source checks, metadata limits, save ownership and resume identities remain.

## Evidence and boundaries

Host: six governor groups, 42 importer groups, allocation/metadata suites, full core check, Android compilation/lint, actual Linux JNI byte-preservation and Android ARM64 bridge compilation. Python producer suite ran 1,468: 1,360 passed, 108 explicit skips. Complete provider package and native stock SQL setup/reentry/restart/clean-stop passed at the exact producer.

Android 13 x64: artifact 13058135177, all 33 members, 14 source identities and 9 named successes independently checked against the logged runner and producer workflow. 1 GiB folder 142.432 s, 521 accepted advice calls; ZIP 272.448 s, 1,007 accepted calls; zero advice errors and matching payload hashes. Java growth 2,306,200/429,048 bytes. The separate 3,210-document fixture remains unpaced. These are generated fixtures; no owner LMK or actual Thor gameplay was reproduced.

A post-publication tooling run failed because an existing whole-file substring assertion mistook digits in a random fixture password for a bot count. Test-only commit 7c38f27756eac24821cd848ee59d475acfba0bdc makes the generated credential deterministic and checks exact bot setting lines. Runtime and distributed APK bytes are unchanged; focused 29 tests pass. Preserve the historical failed run 41241976734 as diagnosis evidence.

## One device retry

Install v4 over the existing app, retain data and choose the same complete ChromieCraft source. Keep `Wow.exe` beside `Data` and MPQs inside `Data`. Copying is deliberately slower;1 GiB takes at least 128 s per pass and ZIPs add staging. Memory waits keep Stop available; sustained pressure pauses with completed files retained. Reuse depends on reliable source metadata. If Android closes the app, reopen and export the whole bundle before another import, including last phase/file. Follow `NON-CUSTOM-TESTING.md` after import succeeds.

Client 471ee42/server f35f04d/Eluna 58d7652 and the existing ARM64 Wine/PRoot/local-server architecture remain pinned. No client/server repository modification, x86 substitution, custom/HD dependency, save reseeding or signing-key rotation occurred. Actual owner data, preparation, Thor rendering/world entry/controller/audio/persistence remain the device qualification boundary.

The corrected full tooling CI run `41242372352` passed at test-only revision `7c38f27756eac24821cd848ee59d475acfba0bdc`; see `runtime/evidence/non-custom-v4-tooling-fixture-fix.json`.
