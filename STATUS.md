# Esteria Stock — version 5 preparation update pending

Version `0.1.0-non-custom.5` / code **5** is an implementation checkpoint on `non-custom`; it is **not published yet**. Fresh complete ARM64 packaging, native SQL, Android 13 execution, signing and public download verification remain release gates. Package `io.github.russianranger.esteria.stock`, the persistent certificate and existing app data are retained.

## Owner evidence and current failure

The two supplied v4 support bundles both confirm a completed **folder import**, 14 archives and zero import cache-advice errors. Android history contains **three unique `LOW_MEMORY` exits** during subsequent local-world preparation. The last completed launcher stage was the graphics component check. Missing private helper logs and a rejected retained log selection prevent identifying the exact preparation child, allocation or input member. Launcher PSS does not include preparation children or kernel cache.

The original input contains 16,742,408,801 archive bytes, approximately 15.6 GiB. Preparation previously hashed these at storage speed after import. This is a concrete unpaced I/O path, not proof of which allocation caused an owner exit. The normalized evidence is `runtime/evidence/non-custom-v5-owner-world-failure.json`. Successful owner import is now confirmed; owner ZIP import, successful world preparation and gameplay remain separate evidence boundaries.

## Version 5 changes

- Java runtime verification and APK-owned Python preparation hashing use an explicit 8 MiB/s policy, reducing to 2 MiB/s under pressure, with bounded cancellation checks and clean-input cache advice. Full hashes, source identities and metadata checks remain required. Existing import controls continue unchanged.
- Native extraction/translation children receive a **4 GiB virtual-address-space limit per process**, repeated advice for clean MPQ inputs and a pressure guard that stops and reaps the child before returning a pause. This is not a native I/O speed cap, a resident-memory measurement or a total app-plus-children budget.
- The shader adapter keeps packed MPQ tables and bounded record/bytecode inventories, retaining expanded shader IR only while needed. The original verified decoder, emitter and compiler paths remain; source-pinned recipe modules and published provider bytes stay unchanged. The APK helper closure includes every adapter dependency.
- Memory pauses use the distinct child exit **75**, propagate through supervisors and Android owners, and retain completed phases. A transient pause does not become a cached failed stock-content report. Stop during parent verification is recorded as preparation paused.
- Durable preparation receipts retain the last phase, observed parent memory and explicitly partial child observations. Fixed owned logs survive interruption; individually invalid log selections are excluded while independently validated roles remain available. Private paths are still rejected by the original strict validator.

A first full 15.6 GiB hash pass takes roughly **34 minutes at 8 MiB/s**, before later extraction, repeated verification, shaders and database work. Pressure can make it substantially longer. Native extraction retains its own throughput. Keep completed import and preparation state; this update does not require reimporting the client.

## Checkpoint validation

Focused host checks passed for governed hashes, unchanged fingerprints, native child limits/reaping, pause/retry, log recovery and bounded shader equivalence. The final focused Python preparation set ran **74 tests successfully**. Java runtime installer tests passed 20 groups; the final local Gradle run passed core checks, all owner fixtures, app/test assembly and lint (120 tasks, 2 minutes 18 seconds). SDK-backed signing/publication tests passed 39 cases. Synthetic shader fixtures produced matching outputs with a structural compiler fixture; these are not real shader compiler/GPU or owner-data execution evidence.

Final full host discovery passed: **1,504 run, 1,396 passed, 108 explicit dependency skips**, no failures. Fresh exact-producer complete APK, native SQL and Android 13 runs are pending. No v5 APK, signature or public artifact identity is claimed here. Host success does not reproduce the Thor kill or establish world entry.

## Published v4 update baseline — historical

The current public package is [v4 ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.4/Esteria-Stock-3.3.5a-arm64.apk), [release](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.4), release ID `430186739`.

- APK: 336,767,421 bytes; SHA-256 `af4b77d9ad183e8a4855a9bcce0644da2276e1d6309bb86d0727691ad79e1b29`.
- Certificate: `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.
- Producer `2c8eeb08a3079edf7354cd373b7cbaf94d859365`; publisher `8d0ba78bed3256b5eee3340b62fe1c8de41c3d52`; successful publication run `41241976822`. Full APK/all-six-asset public readback passed. Historical records remain in `runtime/releases/non-custom-v0.1.0-non-custom.4.json` and `runtime/evidence/non-custom-v4-*`.
- Test-only correction `7c38f27756eac24821cd848ee59d475acfba0bdc` passed tooling run `41242372352`; preserve it and its evidence. Historical failed tooling run `41241976734` is retained as diagnosis evidence.

The signing ledger pins v4. Sign v5 against this exact previous APK with the same certificate; preserve historical releases and `update-4` transport. Use new `update-5` metadata and advance the ledger only after verified public readback.

## Next device session after publication

Install v5 over the existing stock app, keep app data and the successful import, then retry **Prepare local runtime / world** with the same installed locale. If paused for memory, allow recovery and retry preparation. If Android closes the app, reopen and export the whole support bundle **before another preparation attempt**. Include the last displayed stage and the `preparation.last.*` observations. Continue startup, Human Warrior world entry, clean-stop persistence and offline repeat only after preparation succeeds. See `NON-CUSTOM-TESTING.md`.

Client stays `471ee42faadf4a97a1d0a86989cf1452621f2dc5`; server stays `f35f04d01689f034778e3474b3c820092f51e461` plus seven pinned adaptations; Eluna stays `58d7652138887783228b9727bd1fa4e08f00342b`. Custom/HD content and bot AI remain deferred. Actual Thor preparation, graphical startup/world entry, controller/audio and persistence remain unqualified.

Shader supervision keeps the original two-hour translator budget and allows 150 minutes in the Android owner, including paced validation of up to 2 GiB of generated output. Focused Java compilation and presentation-owner cleanup checks passed after this allowance change.

Android execution rejected an intermediate checkpoint: 11 of 13 components passed; raw SharedPreferences XML appended spaces after the legacy log record, and a test fixture used unavailable Android 13 `Path.of`. Retained selections now use a canonical single-line Base64 preference envelope, with backward recovery limited to outer ASCII spaces after the final legacy newline. Strict role/path validation is unchanged. The fixture uses `Paths.get`. Focused core checks, app/test compilation and lint passed; the fresh Android run is still a release gate. Evidence: `runtime/evidence/non-custom-v5-android13-rejected-checkpoint.json`.
