# Esteria Stock v5 implementation handoff — publication pending

Branch `non-custom`; package `io.github.russianranger.esteria.stock`. Defaults now select `0.1.0-non-custom.5` / code 5. The code is an implementation checkpoint, **not a published v5 APK**. Complete package/native SQL/Android 13 evidence, persistent signing and public readback must follow the final producer commit. Preserve the existing successful import, completed phases, databases and saves.

## Owner evidence

`runtime/evidence/non-custom-v5-owner-world-failure.json` records the two original v4 support bundles and their hashes. Both report completed folder import, 14 archives and zero import cache errors. Deduplicated Android history records three `LOW_MEMORY` exits after import during world preparation. The last completed launcher stage is graphics component readback. Private preparation logs were absent and retained log metadata was rejected, so the exact child/phase/member or first allocation remains unknown. No exit is attributed to a particular Java, Python or native allocation without evidence.

The archive set totals 16,742,408,801 bytes (about 15.6 GiB). The old preparation path hashes that set without the import governor. Parent PSS excludes children and cache. V4 solved the reported owner folder import; the new work targets preparation and preserves that import. Owner ZIP success is not established by these two folder reports.

## Implementation and ownership

`RuntimeReadPolicy` installs a worker-local observer around explicit preparation, including the preparation portion of Start. `RuntimeFiles` and embedded-resume verification still hash the actual bytes and enforce original lengths/pins; the observer adds pacing, cancellation and clean-cache advice. Scopes close on success, pause and failure, do not leak to another worker and do not authorize skipping verification.

The Android controller is shared with import: 8 MiB/s normally, 2 MiB/s under low headroom, and cancellable waits for severe parent pressure. Durable `WorldPreparationDiagnostics` records admissions before provider verification and child launch, later phase changes, system/heap observations and scoped child RSS/PSS coverage. A memory pause during a running helper throws through existing owner cleanup. The service remains busy/foreground and retains import/provider leases until the actual children stop. Native group observations explicitly do not prove every guest member was seen.

`world_io.py` owns Python hash/copy adapters and child supervision. Published extractor/shader provider bytes and the byte-pinned `extractor_order.py` / `shader_generation.py` recipe modules remain unchanged; adapters are installed temporarily in the APK-owned preparation coordinator. Android mode is explicitly requested with `--android-low-memory`. The native child gets a 4 GiB `RLIMIT_AS` before exec; descendants inherit the limit. This is a per-process virtual-address limit, not an RSS/aggregate budget. Repeated clean-MPQ advice does not impose a native speed cap or measure reclaimed pages. Severe pressure stops/reaps the native operation instead of waiting while it continues allocating.

`stock_shader_translate.py` uses the verified original reader/decoder/emitter/compiler, packed MPQ tables and bounded shader metadata/bytecode. Expanded IR is short-lived. Strict validation and refusal behavior remain, and helper identities bind the full seven-file stock closure into shader reuse. Java/Gradle/final-APK checks agree on stock-client 7, server-data 6 and server-session 24 inputs. No floating source or substituted provider is accepted.

Transient pressure returns fixed exit 75 and a bounded marker, which propagates through nested supervisors and Android owners as `paused-memory`. Stock inspection must not publish a failed content report for this outcome; unchanged inputs can retry. Ordinary cancellation records `paused` and preparation instructions. Genuine content errors remain failures. Partial outputs and completed phase journals are retained; existing save ownership and shutdown rules remain.

`SupportLogSelection.recover` salvages each role through the original strict fixed-path validator. It does not scan directories, widen the allowlist or admit private paths. Previous valid fixed logs remain until a new owner supplies replacement paths. Rejection counts and bounded reasons accompany exported facts.

## Timing and consolidated owner retry

At 8 MiB/s, one complete 15.6 GiB verification pass takes about 34 minutes with overhead. Other provider checks, extraction, shader generation and SQL add time; pressure may reduce hashing to 2 MiB/s or pause it. Do not present 34 minutes as the total setup duration or a cap on native throughput.

After the final signed v5 publication: update the existing app, retain its data and **do not reimport** the already completed client. Retry Prepare local runtime / world using the same installed locale. Let admission/hash phases progress while the app remains active. A memory pause retains completed work; retry after recovery. After any Android closure, reopen and export support before another preparation attempt, preserving last phase, exit history and fixed helper logs. Only after preparation succeeds proceed through startup, Human Warrior world entry, clean-stop persistence and offline repeat in `NON-CUSTOM-TESTING.md`.

## Validation checkpoint and remaining gates

Focused host preparation checks passed 74 tests, including actual file hashing, typed pause/retry, real child virtual limits/reaping, immutable source fingerprints and source-derived shader fixtures. The bounded shader fixture used 2,177,553 peak traced bytes versus 46,701,725 for the original retained-object form across 96 generated records; record summaries match. Its compiler is a structural fixture, so neither those bytes nor output equivalence qualifies real shader compilation or rendering on owner assets.

Runtime installer checks passed 20 groups, including scoped read cancellation/hash preservation/worker isolation. The final local Gradle run passed core checks, all owner fixtures, app/test assembly and lint (120 tasks, 2 minutes 18 seconds); 39 SDK-backed signing/publication tests passed. Final full Python discovery passed **1,504 tests: 1,396 passed and 108 explicit dependency skips**, no failures. Fresh exact-producer complete ARM64 package, native stock SQL setup/reentry/restart/stop and Android 13 execution are pending. New Android tests add durable phase/log recovery, real owned-child observations, pause exit classification and governed preparation reads to the existing import suite. Do not describe them as executed on Android until the new run is read back.

No v5 install-over, real owner preparation, Thor rendering/world entry/controller/audio/persistence or actual LMK prevention is qualified yet. The owner reports establish v4 import success and the later Android `LOW_MEMORY` events only.

## Publication and historical baseline

Current public v4: [APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.4/Esteria-Stock-3.3.5a-arm64.apk), release `430186739`, APK asset `696483916`, 336,767,421 bytes, SHA-256 `af4b77d9ad183e8a4855a9bcce0644da2276e1d6309bb86d0727691ad79e1b29`. Persistent certificate: `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.

V4 producer `2c8eeb08a3079edf7354cd373b7cbaf94d859365`; publisher `8d0ba78bed3256b5eee3340b62fe1c8de41c3d52`. Package run/job `41240790028` / `124654094771`; native SQL `41240789998` / `124654064489`; Android 13 `41240790022` / `124654064524`; publication `41241976822` / `124657555352`. Anonymous full APK and all six assets passed public readback. Test-only correction `7c38f27756eac24821cd848ee59d475acfba0bdc` passed tooling `41242372352`; preserve the earlier failed tooling `41241976734` as historical diagnosis.

The ledger is already at verified v4. V5 requires the same certificate/package, increasing code 5 and the exact v4 APK as `--previous-apk`; never initial-baseline. Retain historical update-4 transport/releases/assets. New detached inputs belong in `runtime/releases/non-custom/update-5`. Select actual successful exact-producer package/native SQL metadata, sign the reviewed complete APK, reconstruct/check its public signature and publish additively. Advance the ledger only after complete public APK/hash/certificate readback. Record the new producer, jobs, artifacts and publication identities when they exist; no IDs have been invented for this checkpoint.

Client `471ee42faadf4a97a1d0a86989cf1452621f2dc5`, server `f35f04d01689f034778e3474b3c820092f51e461` with seven adaptations and Eluna `58d7652138887783228b9727bd1fa4e08f00342b` remain pinned. ARM64 Wine/PRoot/local server and offline goals remain. No client/server repository change, x86 substitution, custom/HD dependency, save reseeding or signing-key rotation is part of v5.

Shader supervision keeps the original two-hour translator budget and allows 150 minutes in the Android owner, including paced validation of up to 2 GiB of generated output. Focused Java compilation and presentation-owner cleanup checks passed after this allowance change.

Android execution rejected an intermediate checkpoint: 11 of 13 components passed; raw SharedPreferences XML appended spaces after the legacy log record, and a test fixture used unavailable Android 13 `Path.of`. Retained selections now use a canonical single-line Base64 preference envelope, with backward recovery limited to outer ASCII spaces after the final legacy newline. Strict role/path validation is unchanged. The fixture uses `Paths.get`. Focused core checks, app/test compilation and lint passed; the fresh Android run is still a release gate. Evidence: `runtime/evidence/non-custom-v5-android13-rejected-checkpoint.json`.

The next Android checkpoint passed 12 of 13 components, including actual new/legacy XML preference recovery. Its remaining failure was a test-only redundant shell argv token; both fixture invocations now begin with `-c`, matching the native owner contract. Actual native shell exits 75 and 0 and Android test compilation passed after correction. Production memory/serialization code is unchanged. The final all-component Android run remains required; see `runtime/evidence/non-custom-v5-android13-command-rejected-checkpoint.json`.
