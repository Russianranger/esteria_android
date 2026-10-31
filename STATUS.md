# Non-custom stock package status

Updated 2026-10-31 America/Chicago. Profile `stock-3.3.5a`; branch `non-custom`; separate package `io.github.russianranger.esteria.stock`.

## Signed candidate

Version `0.1.0-non-custom.1`, versionCode `1`; 336,746,941 bytes.
APK SHA-256: `802cb3f8575f4413e19ddef937e75394370ec9682c3f71631fff3579976df718`.
Certificate: `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`; actual SDK v2/v3 signature, nondebuggable manifest and complete payload preservation verified. Published additive prerelease: https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.1. Public anonymous HTTP200, filename,336,746,941B and the complete SHA-256 readback match the SDK-verified signed APK. All six release assets have recorded digests. Backup download saved. Official stock signing baseline is versionCode1; future updates require>=2.

- Exact app producer: `8d31e4fa832cd8ef0f738d36088fb9e64ae3aa41`; full ARM64 build `41213324528`, job `124572722479`.
- Reconstructed ARM64 client: `471ee42faadf4a97a1d0a86989cf1452621f2dc5`.
- Server: `f35f04d01689f034778e3474b3c820092f51e461`, unchanged seven pinned integration adaptations; Eluna source `58d7652138887783228b9727bd1fa4e08f00342b`.
- `sources.lock.json` and native provider locks remain unchanged. Wine/Debian12 and server/MySQL/Ubuntu24 PRoot roots remain separate. No x86 Wow.exe substitution.

The separate stock app installs beside custom Esteria and owns its client copy, database, shaders and mutable state. Original client files/realmlist/accounts, custom app saves, `main`, `android/client-server`, custom branches and the previous published assets remain untouched.

## Implemented stock behavior

Import → Prepare local runtime / world → Start local game. The import report reads actual PE VERSIONINFO, base MPQ structure, installed/effective locale and speech. Content inspection checks effective archive members, authentic UI closure/signature structure, 238 source-derived client DBC layouts and shader inventory. Cryptographic UI validation remains in the reconstructed client. It preserves standard Blizzard root/locale patches, refuses unclassified overlays precisely, and removes only content-confirmed optional overlays plus known loose UI/custom trees in a separate app-owned stock generation.

Preparation uses that same selection for client launch, ordered DBC/maps/vmaps/mmaps/Cameras extraction and Vulkan shaders. Profile, importer ancestry, exact tools and app helper identities bind reuse. It retains completed stages, diagnostics and saves on failure without repeated full-client hashing on ordinary launches.

Stock SQL policy `stock-world-source-selection-v2` projects authentic source files and excludes custom race/map/classless/progression world changes. All 3,219 policy-v1 retained world SQL source identities were audited; the real SQL failure exposed Individual Progression's outfit/Vanilla rewrites, now excluded with its source-supported runtime switches disabled. No fabricated rows, cleared-all-DBC shortcut or blanket success return. Normal startup cannot reapply the full custom SQL tree. Fresh setup/clean stop/restart preserve ownership and refuse reseeding active saves.

## Actual evidence

| Check | Result | Boundary |
| --- | --- | --- |
| Full ARM64 app/build | `41213324528` passed native compilation, core tests, lint, complete provider/source/debug checks, bounded Java installation, SDK signing fixtures, nondebug release and final APK byte verification. Unsigned artifact `13046713724`:336,750,863B, SHA `f0892de3928c0cc413786cb67f48def535b457ab62f7cd17e79dc7226ffca706`. | Actual packaging; no game execution. |
| Native ARM64 stock SQL | `41213324577` on the exact app producer passed live empty race/class/map/outfit overlays, Human Warrior Northshire row, four schemas, finish/reentry without replay, same-UUID restart and two clean stops. 3,070 world updates selected/270 excluded;31 bot-schema updates/30 tables. | Actual SQL/setup; no DBC files/auth/world/character-save/bot-AI/Android execution. |
| Android13 x64 | `41213324526` on the exact producer passed19 filesystem/update contract groups and exactly2 stock-helper/receipt tests. Artifact `13047332325` and all29 files read;7 source hashes match. | Actual Android component behavior; tiny test APK, no full ARM64/client/world/rendering claim. |
| Input/content/source checks | 34 low-heap importer groups;8 tests with selected471's actual MPQ reader over encrypted-table synthetic archives;238 layouts reproduced from479 source inputs; source/fixture and tooling CI pass. | Source support and synthetic behavior, not the owner's assets or gameplay. |
| Signing | The existing persistent certificate verifies the signed APK with SDK35; payload and manifest preserved. | Signature/package integrity; actual delivered install-over and gameplay unqualified. |

Both failed native SQL runs `41211067232` and `41211577406`, the exact guard reason, source audits and successful receipts remain under `runtime/evidence/non-custom-*`.

## Remaining real validation

No complete owner ChromieCraft client folder/archive or Thor was accessible here. No actual stock MPQ extraction/game shader generation, normal graphical startup/login, character creation/world entry, character saves, real controller/audio or offline gameplay was executed. Run the one `NON-CUSTOM-TESTING.md` procedure with the existing complete12340 client. This needs no custom MPQ bundle, pre-extracted world download, ChromieCraft credentials or manual MySQL administration.

Full Esteria MPQs/catalogues/races/appearance, HD art, custom maps, Retail/Forever, Lua/AIO/custom gameplay and bot AI qualification are deferred and never stock acceptance gates. All custom sources remain recoverable.

Publication run `41215249412` at metadata commit `35310cd093aae28239ac6b35d5f69c854865341e` independently reverified source-run/artifact/nativeSQL provenance, reconstructed the exact signed APK, verified SDK certificate/manifest/payload, then published. See runtime/releases/non-custom-v0.1.0-non-custom.1.json and runtime/evidence/non-custom-public-apk-readback.json. The APK producer remains8d31; later commits only retain evidence/publication/signing-ledger metadata.
