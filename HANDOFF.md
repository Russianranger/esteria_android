# Next-session handoff

## Authorized work
Lead development continues toward nearly complete local client/server APK on AYN Thor. Push only client `android/arm64-port` and integration `android/client-server`. Server repo read-only. Default branches untouched. Do not send preliminary test APKs. Do not imply background development without running jobs.

## Resume in this order
1. Fetch both development tips and read STATUS.md plus actual Actions results. Distinguish pending/failure from passes. This session can read public Git/API and write with connected GitHub Git-object APIs; CLI Git push has no credentials. Connector `update_ref` fast-forward with expected SHA preserved branch history. No access bypass is needed.
2. Finish exact-head reconstructed client Windows x64/ARM64 CI. First run 40980276079 passed Linux ARM tests but failed Windows codec generic assembly and ARM runner generator. Fixes followed; inspect newest run and compiler output before claiming full build.
3. Inspect native ARM64 server run 40979894616. It configured and started compilation successfully. Package installed server plus the pinned SQL, modules/Lua, config, tools and notices; install target alone lacks all runtime data. MySQL 8 required; MariaDB has not been adapted/qualified.
4. Run integration Python tests, Java host tests, Android clean assemble/lint. Confirm exact source lock embedded in APK. Current APK is only internal launcher validation; keep gameplay qualification false until real adapter/payloads work.
5. Finish MySQL bootstrap/readiness/persistence tests; separate create-empty-instance from existing-database migration. Never seed over existing saves. Then package source-pinned ARM64 Wine/PRoot+display/audio (other launchers read-only references) and implement launcher runtime adapter.
6. Feed authentic build 12340 full data/custom packages through importer and preflight; generate shaders using corrected engine archive precedence. Catalog input blockers are enumerated in ASSET-REQUIREMENTS.md. Supplied Wow.exe version was independently verified; no full client import yet.
7. Achieve host/emulator login/world/create/save/relog and small bot scene, then device-qualified controls/audio/offline. Ask owner for smallest missing inputs only when useful independent work is exhausted.

## Important implementation details
- Core importer package `io.github.russianranger.esteria.core.importer`; immutable generations + current pointer, file journal, bounded copy, source metadata detection. Mutable WTF/cache/config must live outside generations. ZIP staging costs extra disk space; generation cleanup policy still needed.
- Core supervisor owns one session, watches prior dependencies during startup, and propagates cleanup failures. Runtime-specific process groups and graceful server save/exit remain adapter work. TCP listening alone is not readiness.
- Support export tails bounded logs, discards partial first lines, redacts secrets, excludes private database/source files, and includes exact source pins.
- Source importer verifies executable resource version and MPQ envelope. It does not prove every archive's internal build/content compatibility.
- Match 25 quests/254 containers/32 client class capacity. Server MAX_CLASSES 12 does not imply 32 playable classes.
- Existing app package `io.github.russianranger.esteria`, minSdk 26/target 35, JDK 17/Gradle 8.9/AGP 8.7.3. Stable private signing key still needed before any user installation; debug CI is not that baseline.

## Local workspace notes (not required for reproduction)
This session has sibling client-src/server-src/reference-fta checkouts and toolchain JDK 17, SDK 35, Gradle 8.9. Do not depend on those paths; clean builds use sources.lock.json and BUILDING.md. The proprietary Wow.exe is outside repositories and must stay there.
