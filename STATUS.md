# Esteria Stock v7 — native fix verified; APK build pending

The owner v6 support bundle `Esteria-support-1793550413267.zip` confirms graphics readback passed in 243 ms. Map/DBC extraction then failed at `ordered effective file count bound`; no new low-memory exit was recorded and about 9.9 GB remained available. Preserve the completed import and all app data.

V7 selects DBFilesClient/*.dbc before retaining archive names, parses bounded listfiles without redundant all-name copies, and checks decoded metadata size before allocation. Provider priority, deletion markers, path checks and selected-count bounds remain enforced. Host regression: 120,238 distinct synthetic names, 238 selected DBCs, 34 tests passed; the old behavior failed the regression.

Actual ARM64 rebuild passed at `bad963b8ae2edd0c8bcfe0db852ac4557f1cc700`, followed by complete source sealing and four-tool qualification at `8d016467af4d23ab88303ed8ec877f28334e1049`. All 26 actual native reader tests passed without skips. The new runtime archive is `e80d1d731902907297ae89f68d8241bca0aa79b8a281521c669353654ce5b436`. Its complete source/debug package is public in `non-custom-data-tools-v7` (release 430726308); all four public assets and complete provider proof passed independent anonymous readback. Unaffected programs/content/assembler/navigation and client/server/Eluna pins remain unchanged.

The complete v7 APK build, Android components, native SQL, persistent signing and public APK verification remain required before delivery. No v7 APK is published at this checkpoint. Local validation passed 109 Gradle tasks, 39 actual SDK release tests and 1,532 host tests (1,428 passed, 104 dependency/environment skips). Actual Thor preparation and gameplay remain unqualified. See `NON-CUSTOM-TESTING.md` and the `non-custom-v7-*` evidence.

## Published v6 baseline — historical

# Esteria Stock v6 — graphics deadline update published

[Signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.6/Esteria-Stock-3.3.5a-arm64.apk) · [Testing procedure](NON-CUSTOM-TESTING.md).

Install over the existing `io.github.russianranger.esteria.stock` app, keep data and the completed import, then retry **Prepare local runtime / world** with the same locale. Do not reimport. One 15.6 GiB full hash pass still takes about 34 minutes at 8 MiB/s; later phases and pressure add time. Export support before another retry after failure. Physical Thor v6 preparation, GPU/world rendering, controls/audio and persistence remain unqualified.

The latest owner report was a five-second Turnip graphics timeout with about 9 GB available and no new low-memory kill. V6 completes paced provider/specification admission before starting the unchanged five-second native execution budget, which still includes native startup. GPU receipt/provider validation, cancellation and owned cleanup remain required. Existing preparation memory controls remain active.

Producer `cca8f81abe412b65f0c85da2902f24848a694fd2`; publisher `79c9b8e5744daefcbe4b108652ba26297876bc11`, run/job `41277919602` / `124763764353`. Release `430387223`, APK asset `697446059`. APK 336,796,416 bytes, SHA-256 `11dc96d63d9cf2f00774804216dc9ec45a0785654f40c6a08030ffb91c70ffce`; certificate `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.

All five exact-producer ARM64 package/native SQL/launcher/tooling/Android gates passed. Android 13 x64 passed 14 named components; readback verified 33 artifact members and 37 source identities. A real paced 48 MiB admission took 6.146 seconds before a 26 ms JNI fixture child; hung/late/launch-budget/cancellation/mutation checks passed. This timing fixture executes no PRoot, Vulkan/KGSL driver or owner game data. Local validation passed 109 Gradle tasks, 1,504 host tests (1,373 passed, 131 dependency skips) and 39 actual SDK tests.

All six public assets passed anonymous length/hash downloads. Exact producer tag, SDK v2/v3 signatures/certificate/stock version 6 manifest and local signed-byte equality passed. The official signing ledger advanced to v6 afterward. Update-6 receipts retain their baseline-5 binding; future updates require a higher code, the same certificate and exact public v6 as previous APK. Preserve all historical releases/transports/evidence.

Records: `runtime/releases/non-custom-v0.1.0-non-custom.6.json`, `runtime/evidence/non-custom-v6-public-apk-readback.json`, `non-custom-v6-release-gates.json`, `non-custom-v6-android13.json`, `non-custom-v6-host-timing.json` and `non-custom-v6-owner-turnip-timeout.json`. Client/server/Eluna pins remain unchanged.

## Published v5 update baseline — historical

# Esteria Stock v5 — preparation memory update published

[Download signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.5/Esteria-Stock-3.3.5a-arm64.apk) · [Release](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.5) · [Testing procedure](NON-CUSTOM-TESTING.md).

Version `0.1.0-non-custom.5`, code 5, package `io.github.russianranger.esteria.stock`. **Keep the successful import and app data; install over the existing app and retry Prepare local runtime / world. Do not reimport.**

V5 extends 8 MiB/s verification pacing, 2 MiB/s pressure backoff and clean-cache advice to Java/Python preparation. Native extraction/translation children have a 4 GiB virtual-address limit per process and supervised cleanup; native I/O is not speed-capped. The shader adapter bounds retained tables/bytecode/IR. Typed pauses preserve completed phases without caching transient content failures. Durable phase/partial child observations and strict fixed-log recovery survive reopening.

One full hash pass over 15.6 GiB takes about **34 minutes at 8 MiB/s**. Later checks, extraction, shaders and SQL add time; pressure may slow or pause work. Neither this timing nor the per-process virtual limit is a total setup/RAM guarantee.

Two v4 owner bundles confirm completed folder import and three unique later preparation `LOW_MEMORY` exits. Missing helper logs did not identify the exact child/allocation. **Physical Thor v5 preparation, gameplay, controls/audio and persistence remain unqualified; tests do not prove the kill is eliminated.** Export support before retrying after any Android closure.

## Verified identity and evidence

- APK: 336,796,416 bytes; SHA-256 `55a00a604d622c90e1d95a104512f9a9a0e085dbd7ed587a1b8ee93ebdca515f`.
- Certificate: `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.
- Producer `4adb12f9502af7d734174a94fb8233226d9b4c60`; publisher `46bf279d0283c31132c0752df3450d5a0612608b`, run/job `41269263210` / `124738460624`; release `430339293`, APK asset `697210840`.

All exact-producer ARM64 package/native SQL/launcher/tooling gates passed. Android 13 x64 passed 13 components; readback checked 33 artifact members and 32 source identities. Host discovery: 1,504 run, 1,396 passed, 108 dependency skips. Shader equivalence uses a structural compiler fixture, not owner-data/GPU proof.

Anonymous full APK/all-six-asset length/hash checks, exact tag, SDK v2/v3 signatures/certificate/manifest and local signed-byte equality passed. Ledger advanced to v5 afterward. Exact identities and limitations: `runtime/releases/non-custom-v0.1.0-non-custom.5.json`, `runtime/evidence/non-custom-v5-public-apk-readback.json`, `non-custom-v5-release-gates.json`, `non-custom-v5-android13.json`, `non-custom-v5-host-preparation.json` and `non-custom-v5-owner-world-failure.json`.

Client/server/Eluna pins and offline architecture remain unchanged; historical v4/releases/transport remain preserved. See `HANDOFF.md` for exact gate IDs and next-update rules.
