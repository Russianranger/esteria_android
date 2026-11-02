# Esteria Stock v9 — preparation speed, resume and storage update pending

The v8 owner bundle records a memory-pressure pause after about 103 minutes, followed by another attempt that reached navigation meshes and was cancelled. It records no new low-memory kill. Visible runtime setup reused the same generations with zero copied bytes; repeated downloads are not established. The old phase code retained failed UUID navigation directories but started fresh on retry, which could repeat native work and grow storage.

V9 adds Gentle 8, Balanced 32 (default) and Fast 64 MiB/s preparation verification/copy profiles. Imports keep their existing 8 MiB/s policy. Real pressure retains 2 MiB/s backoff/pause, one native worker and the 4 GiB native address-space guard. A critical trim callback with verified healthy system/heap headroom now causes backoff instead of immediately aborting native preparation. Native navigation CPU time is separate from the chosen I/O rate.

Valid partial navigation tiles and reviewed compatible v8 work can resume after complete input/output checks. Recognized duplicate phase attempts are reclaimed; unknown data remains protected. Idle-only storage scan/trim removes obsolete immutable runtime generations and redundant owned archive copies while preserving imports, current/expected runtime, world checkpoints, databases and saves. Bounded rotating input-cache windows replace repeated whole-archive sweeps. Stage, native tile progress and operation/cancellation diagnostics distinguish continued work from a new attempt.

Local build/lint, storage filesystem and speed-policy checks passed. Full exact-producer APK, native/Android source-bound evidence, persistent signing and anonymous public readback remain release gates. Physical Thor preparation/world entry remain unqualified. Preserve the completed import and app data; no reimport or clear-storage procedure is requested.

## Published v8 baseline — historical

# Esteria Stock v8 handoff

[Signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.8/Esteria-Stock-3.3.5a-arm64.apk) · [Testing procedure](NON-CUSTOM-TESTING.md).

Install over the existing `io.github.russianranger.esteria.stock` app. Keep the completed import, app data, databases and saves, and retry **Prepare local runtime / world** with the same locale. Do not reimport or clear storage. Verification remains paced at 8 MiB/s, dropping to 2 MiB/s or pausing under pressure; one 15.6 GiB hash pass takes about 34 minutes, with later phases adding time. Export support before another retry after failure.

The v7 owner report stopped at DBC directory creation, with no new low-memory kill and about 8.6 GB available. The extractor truncated its absolute `-o` output argument to 127 bytes and tried to create a directory beneath that nonexistent truncated parent. V8 passes `-o .` inside the same verified private phase working directory. The v7 ordered native tools, input bounds, provider priority, cleanup and memory controls remain unchanged.

Producer `7c1755968afee2fc1ec5448ce7c853a815750b3f`; publisher `7b01584c8a7679536aa95831c0107a81bc0aca1d`, run/job `41341085661` / `124951043905`. Release `430800823`, APK asset `699278685`. APK 336,808,704 bytes, SHA-256 `cfd47c5f0cc921fef0fcceda12df664367471269fe77d4c846c0100defadb76f`; certificate `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.

| Gate | Run | Job |
| --- | ---: | ---: |
| Complete ARM64 package | 41339632720 | 124946725754 |
| Native SQL | 41339632739 | 124946691034 |
| Android 13 | 41339632718 | 124946691229 |
| Launcher/core/lint | 41339632703 | 124946691137 |
| Tooling | 41339632709 | 124946691205 |
| Native extractor output/DBC | 41339632774 | 124946691389 |

All six exact-producer gates passed: complete ARM64 APK, native SQL, Android 13 components, launcher/core/lint, tooling and shipped ARM64 extractor output creation. Android readback verified all 14 named tests, 37 source identities and 33 artifact members, including update preservation. Local validation passed 109 Gradle tasks, 39 actual SDK release tests, 51 focused adapter/storage/I/O tests and ran 1,539 host tests (1,435 passed, 104 dependency/environment skips). Restoring the old absolute-path argument fails the new regression.

The shipped ARM64 extractor reproduced the old absolute-path failure with a 152-byte output path. The fixed relative output succeeded for fresh and existing directories and emitted the exact synthetic DBC bytes, using the production execute and memory policies. Inputs remained unchanged. This is output-path/DBC-fixture evidence; it converts no owner data, map tiles or camera models and does not establish Android/Thor world preparation.

Native output run/job `41339632774` / `124946691389`; artifact `13096971824`, 4,013 bytes, SHA-256 `f1aad887dff91ef34e50442492363e8542b71b22565a977c7321158dc28bb004`. The same source/debug-qualified v7 data runtime remains selected: SHA-256 `e80d1d731902907297ae89f68d8241bca0aa79b8a281521c669353654ce5b436`, preserved in public component release `430726308` / `non-custom-data-tools-v7`. No native rebuild or provider reinterpretation is required for the adapter change.

All six public release assets passed full anonymous length/hash readback. The exact producer tag, SDK v2/v3 signatures, persistent certificate, stock version 8 manifest and local signed-byte equality passed. Update-8 receipts retain their baseline-7 binding; future updates require a higher code, the same certificate and the exact public v8 APK. Preserve all historical releases and transports.

Physical Thor preparation, rendering/world entry, controls/audio, persistence and offline gameplay remain unqualified until the owner retry. Client/server/Eluna and native-provider pins remain unchanged.

Records: `runtime/releases/non-custom-v0.1.0-non-custom.8.json`, `runtime/evidence/non-custom-v8-public-apk-readback.json`, `non-custom-v8-release-gates.json`, `non-custom-v8-native-output.json`, `non-custom-v8-android13.json`, `non-custom-v8-owner-output-path.json` and `non-custom-v8-adapter-host.json`.

## Published v7 baseline — historical

# Esteria Stock v7 handoff

[Signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.7/Esteria-Stock-3.3.5a-arm64.apk). Version `0.1.0-non-custom.7` / code 7.

Install over the existing `io.github.russianranger.esteria.stock` app. Keep the completed import, app data, databases and saves; retry **Prepare local runtime / world** with the same locale. Do not reimport or clear data. Verification remains paced at 8 MiB/s (2 MiB/s or paused under pressure); one 15.6 GiB hash pass takes about 34 minutes, with later work adding time. Export support before another retry after failure.

The v6 owner report passed graphics readback in 243 ms, then `map_extractor` failed at `ordered effective file count bound`, with no new low-memory exit and about 9.9 GB available. V7 selects `DBFilesClient/*.dbc` before retaining archive names and avoids redundant listfile copies. Input/selected-count bounds, provider priority, tombstones, path validation and existing memory controls remain enforced.

Producer `31e306fa0d243e850ccfdfed50fc0d400a2ab577`; publisher `86b82a348f91cd1c2b9c1e372c89381dc752ec85`, run/job `41331836047` / `124923385734`. Release `430741271`, APK asset `699011971`. APK 336,808,704 bytes, SHA-256 `d0c307a23bc77efa0a6fb6d13a905552fda35e9e3622713e7437f4f8638a1016`; certificate `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.

| Gate | Run | Job |
| --- | ---: | ---: |
| Complete ARM64 package | 41330323397 | 124918891769 |
| Native SQL | 41330323365 | 124918852586 |
| Android 13 | 41330323385 | 124918852542 |
| Launcher/core/lint | 41330323337 | 124918852502 |
| Tooling | 41330323383 | 124918852273 |

All five exact-producer ARM64 package/native SQL/launcher/tooling/Android gates passed. Android 13 x64 passed 14 components with 37 source identities and 33 artifact members verified. Actual ARM64 rebuilt readers passed all 26 lookup cases without skips; four-tool CLI/configuration and complete source/debug checks passed. These fixtures do not establish owner-data conversion or Thor world entry.

Native chain: build `bad963b8ae2edd0c8bcfe0db852ac4557f1cc700`, run/job `41327929457` / `124911701196`; source seal `ae905634a994216c676cb1e7739b0a7d52dce25e`, `41328465330` / `124913293701`; composed qualification `8d016467af4d23ab88303ed8ec877f28334e1049`, run `41328868562`, package/native jobs `124914523335` / `124914647426`. New data runtime: 2,913,905 bytes, SHA-256 `e80d1d731902907297ae89f68d8241bca0aa79b8a281521c669353654ce5b436`.

Complete source/debug preservation is public in component release `430726308` / `non-custom-data-tools-v7`; publisher `f57e02162006c14b275d70757f61c1605f7050e0`, run/job `41329589487` / `124916688467`. All four public component assets and full source/runtime/debug/native proof passed independent anonymous readback. The explicit update lock permits only the two measured data-input lock changes. Frozen old providers remain fully verified under their original recipe; old data tools are excluded from the APK, while programs/content/assembler/navigation remain unchanged.

All six public APK release assets passed full anonymous length/hash readback. The exact tag, SDK v2/v3 signatures, certificate, stock version 7 manifest and local signed-byte equality passed. Update-7 receipts retain their baseline-6 binding; future updates require a higher code, the same certificate and the exact public v7 APK. Preserve historical releases and transports.

Local validation passed 109 Gradle tasks, 39 actual SDK release tests and 1,532 host tests (1,428 passed, 104 dependency/environment skips). The old enumeration behavior fails the new regression. Physical Thor preparation, rendering/world entry, controls/audio, persistence and offline gameplay remain unqualified until the owner retry.

Records: `runtime/releases/non-custom-v0.1.0-non-custom.7.json`, `runtime/evidence/non-custom-v7-public-apk-readback.json`, `non-custom-v7-release-gates.json`, `non-custom-v7-android13.json` and the native/component evidence under `runtime/evidence/non-custom-v7-*`. Client/server/Eluna pins remain unchanged.

## Published v6 baseline — historical

# Esteria Stock v6 handoff

[Signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.6/Esteria-Stock-3.3.5a-arm64.apk). Version `0.1.0-non-custom.6` / code 6.

Install over the existing `io.github.russianranger.esteria.stock` app, keep data and the completed import, then retry **Prepare local runtime / world** with the same locale. Do not reimport. One 15.6 GiB full hash pass still takes about 34 minutes at 8 MiB/s; later phases and pressure add time. Export support before another retry after failure. Physical Thor v6 preparation, GPU/world rendering, controls/audio and persistence remain unqualified.

Producer `cca8f81abe412b65f0c85da2902f24848a694fd2`; publisher `79c9b8e5744daefcbe4b108652ba26297876bc11`, run/job `41277919602` / `124763764353`. Release `430387223`, APK asset `697446059`. APK 336,796,416 bytes, SHA-256 `11dc96d63d9cf2f00774804216dc9ec45a0785654f40c6a08030ffb91c70ffce`; certificate `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.

The latest owner report was a five-second Turnip graphics timeout with about 9 GB available and no new low-memory kill. V6 completes paced provider/specification admission before starting the unchanged five-second native execution budget, which still includes native startup. GPU receipt/provider validation, cancellation and owned cleanup remain required. Existing preparation memory controls remain active.

| Gate | Run | Job |
| --- | ---: | ---: |
| Complete ARM64 package | 41276822893 | 124760596520 |
| Native SQL | 41276822892 | 124760569790 |
| Android 13 | 41276822782 | 124760569339 |
| Launcher/core/lint | 41276822830 | 124760569469 |
| Tooling | 41276822878 | 124760569905 |

All five exact-producer ARM64 package/native SQL/launcher/tooling/Android gates passed. Android 13 x64 passed 14 named components; readback verified 33 artifact members and 37 source identities. A real paced 48 MiB admission took 6.146 seconds before a 26 ms JNI fixture child; hung/late/launch-budget/cancellation/mutation checks passed. This timing fixture executes no PRoot, Vulkan/KGSL driver or owner game data. Local validation passed 109 Gradle tasks, 1,504 host tests (1,373 passed, 131 dependency skips) and 39 actual SDK tests.

Package artifact `13071478297`; native SQL artifact `13071686390`; Android artifact `13072290437` (19,268 bytes, SHA-256 `7050d004541e3f02750eea65da0a32aa9f319ffe47707f939ba48eee7081b4d1`). Publisher-revision launcher `41277919562` / `124763764419` and tooling `41277919534` / `124763764284` also passed.

All six public assets passed anonymous length/hash downloads. Exact producer tag, SDK v2/v3 signatures/certificate/stock version 6 manifest and local signed-byte equality passed. The official signing ledger advanced to v6 afterward. Update-6 receipts retain their baseline-5 binding; future updates require a higher code, the same certificate and exact public v6 as previous APK. Preserve all historical releases/transports/evidence.

Records: `runtime/releases/non-custom-v0.1.0-non-custom.6.json`, `runtime/evidence/non-custom-v6-public-apk-readback.json`, `non-custom-v6-release-gates.json`, `non-custom-v6-android13.json`, `non-custom-v6-host-timing.json` and `non-custom-v6-owner-turnip-timeout.json`. Client/server/Eluna pins remain unchanged.

## Published v5 identities and evidence — historical

# Esteria Stock v5 handoff

Signed `0.1.0-non-custom.5` / code 5, package `io.github.russianranger.esteria.stock`. [APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.5/Esteria-Stock-3.3.5a-arm64.apk). **Update over the existing app, retain data and the completed import, and retry Prepare local runtime / world without reimporting.**

## Publication identity

Producer `4adb12f9502af7d734174a94fb8233226d9b4c60`; publisher `46bf279d0283c31132c0752df3450d5a0612608b`; successful publication run/job `41269263210` / `124738460624`. Release `430339293`, APK asset `697210840`.

APK 336,796,416 bytes, SHA-256 `55a00a604d622c90e1d95a104512f9a9a0e085dbd7ed587a1b8ee93ebdca515f`; persistent certificate `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`. Anonymous complete APK/all-six-asset readback, SDK v2/v3 signatures/certificate/manifest, exact tag and local signed-byte equality passed. Records: `runtime/releases/non-custom-v0.1.0-non-custom.5.json` and `runtime/evidence/non-custom-v5-public-apk-readback.json`.

Signing checked exact public v4 hash `af4b77d9ad183e8a4855a9bcce0644da2276e1d6309bb86d0727691ad79e1b29`. Update-5 receipts retain their baseline-4 binding. The official ledger advanced to verified v5 after public readback. Future updates require a higher code, the same certificate and exact v5 as previous APK. Never initial-baseline; preserve all historical releases/transport/evidence.

## Controls and evidence boundaries

The two owner v4 reports confirm successful folder import, followed by three unique preparation `LOW_MEMORY` exits. Exact child/allocation remains unknown; launcher PSS excludes children/cache. See `runtime/evidence/non-custom-v5-owner-world-failure.json`.

`RuntimeReadPolicy` preserves actual hashes/pins while pacing worker-local verification. APK-owned `world_io.py` adds Python hash/copy controls and supervised children without changing frozen recipes/provider bytes. Java/Python verification is 8 MiB/s, dropping to 2 MiB/s or pausing. Native children inherit a 4 GiB virtual-address limit per process and receive clean-input advice: native speed is not capped, reclaimed pages are not measured, and aggregate RAM is not bounded by that limit.

The bounded shader adapter retains packed tables and short-lived expanded IR around verified original decoder/emitter/compiler logic. Exact helper closures are stock-client 7, server-data 6, server-session 24. The translator retains its two-hour budget; the Android owner allows 150 minutes including paced output checks.

Exit 75 propagates as transient memory pressure, never a cached failed stock report. Ordinary Stop records paused preparation. Busy/foreground/import/provider ownership stays retained until child cleanup/reaping completes. Durable admission/child phases and partial RSS/PSS observations survive interruption. Fixed logs use canonical single-line preference encoding; bounded legacy XML recovery and per-role salvage retain strict path validation.

## Exact-producer gates

| Gate | Run | Job |
| --- | ---: | ---: |
| Complete ARM64 package | 41268215575 | 124735393777 |
| Native SQL setup/reentry/restart/stop | 41268215619 | 124735369772 |
| Android 13 components | 41268215574 | 124735369892 |
| Launcher/core/owners/lint | 41268215602 | 124735369719 |
| Tooling | 41268215573 | 124735369730 |

All passed. Android artifact `13068915124`: 18,501 bytes, SHA-256 `143c0d637c29e45dc049789b8ed622997aacb50e15b65e50cbc2cdeca8b469d3`. Readback verified 33 members, 32 source identities and 13 named successes, including real XML recovery, child exits 75/0, durable observations and governed reads. See `runtime/evidence/non-custom-v5-android13.json` and `non-custom-v5-release-gates.json`.

Host discovery: 1,504 run, 1,396 passed, 108 dependency skips. Core/all-owner/assembly/lint and actual child-limit/reaping/pause-retry checks passed. Shader equivalence uses source-derived data with a structural compiler fixture; it does not qualify real owner shader compilation/rendering. Retained detailed/intermediate evidence remains under `runtime/evidence/non-custom-v5-*`.

Publisher-revision launcher `41269263263` / `124738460724` and tooling `41269263255` / `124738460631` also passed; they are separate from the APK producer.

## One owner session

Keep the completed import and retry preparation with the same locale. One full 15.6 GiB hash pass takes about 34 minutes at 8 MiB/s; later verification/extraction/shaders/SQL add time and pressure may slow or pause it. This is not total setup time. Reuse requires matching source/helper identities.

After Android closes the app, reopen and export support before another attempt. Once preparation succeeds, follow `NON-CUSTOM-TESTING.md` for Human Warrior world entry, clean-stop persistence and offline relaunch. Physical Thor v5 preparation/rendering/controls/audio/persistence and prevention of the reported kill remain unqualified.

Client `471ee42faadf4a97a1d0a86989cf1452621f2dc5`, server `f35f04d01689f034778e3474b3c820092f51e461` plus seven adaptations, and Eluna `58d7652138887783228b9727bd1fa4e08f00342b` remain pinned. No engine substitution, custom/HD requirement, save reseeding or key rotation. Historical v4 identities remain in `runtime/releases/non-custom-v0.1.0-non-custom.4.json`.
