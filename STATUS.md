# Esteria Stock v7 — bounded extraction update published

[Signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.7/Esteria-Stock-3.3.5a-arm64.apk) · [Testing procedure](NON-CUSTOM-TESTING.md).

Install over the existing `io.github.russianranger.esteria.stock` app. Keep the completed import, app data, databases and saves; retry **Prepare local runtime / world** with the same locale. Do not reimport or clear data. Verification remains paced at 8 MiB/s (2 MiB/s or paused under pressure); one 15.6 GiB hash pass takes about 34 minutes, with later work adding time. Export support before another retry after failure.

The v6 owner report passed graphics readback in 243 ms, then `map_extractor` failed at `ordered effective file count bound`, with no new low-memory exit and about 9.9 GB available. V7 selects `DBFilesClient/*.dbc` before retaining archive names and avoids redundant listfile copies. Input/selected-count bounds, provider priority, tombstones, path validation and existing memory controls remain enforced.

Producer `31e306fa0d243e850ccfdfed50fc0d400a2ab577`; publisher `86b82a348f91cd1c2b9c1e372c89381dc752ec85`, run/job `41331836047` / `124923385734`. Release `430741271`, APK asset `699011971`. APK 336,808,704 bytes, SHA-256 `d0c307a23bc77efa0a6fb6d13a905552fda35e9e3622713e7437f4f8638a1016`; certificate `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.

All five exact-producer ARM64 package/native SQL/launcher/tooling/Android gates passed. Android 13 x64 passed 14 components with 37 source identities and 33 artifact members verified. Actual ARM64 rebuilt readers passed all 26 lookup cases without skips; four-tool CLI/configuration and complete source/debug checks passed. These fixtures do not establish owner-data conversion or Thor world entry.

Complete source/debug ZIPs remain public in `non-custom-data-tools-v7` (release `430726308`); all four component assets and complete provider proof passed independent anonymous readback. Unaffected programs/content/assembler/navigation remain original.

All six public APK release assets passed full anonymous length/hash readback. The exact tag, SDK v2/v3 signatures, certificate, stock version 7 manifest and local signed-byte equality passed. Update-7 receipts retain their baseline-6 binding; future updates require a higher code, the same certificate and the exact public v7 APK. Preserve historical releases and transports.

Local validation passed 109 Gradle tasks, 39 actual SDK release tests and 1,532 host tests (1,428 passed, 104 dependency/environment skips). The old enumeration behavior fails the new regression. Physical Thor preparation, rendering/world entry, controls/audio, persistence and offline gameplay remain unqualified until the owner retry.

Records: `runtime/releases/non-custom-v0.1.0-non-custom.7.json`, `runtime/evidence/non-custom-v7-public-apk-readback.json`, `non-custom-v7-release-gates.json`, `non-custom-v7-android13.json` and the native/component evidence under `runtime/evidence/non-custom-v7-*`. Client/server/Eluna pins remain unchanged.

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
