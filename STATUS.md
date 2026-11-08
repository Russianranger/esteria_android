# Current non-custom implementation

[Esteria Stock v18](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.18) is the current signed update. Producer `075ed711bd8be7aaeac8bdfca2be8c607afb8f4b`, version `0.1.0-non-custom.18` (18), 336,899,353 bytes, APK SHA-256 `60a90c58dfc211c53928853dbbebd04929668da69d46d4c0a027c143f6857eb6`. The published release passed six-asset readback and SDK v2/v3 signature verification against v17. [Published bytes](runtime/evidence/non-custom-v18-public-apk-readback.json) · [APK contents](runtime/evidence/non-custom-v18-apk-asset-continuity.json) · [Build and test gates](runtime/evidence/non-custom-v18-release-gates.json).

V18 corrects a reproduced SQL readiness failure. A newly started MySQL CLI took 7.510 s to return the authenticated identity on ARM64 Linux under full-system QEMU. The v17 service discarded it at 3.003 s. The same query took 0.023 s on the established connection. First responses now use their bounded startup or admission allowance and remain cancellable. Subsequent checks keep their three-second limit. Imports, world/shader receipts, providers, the SQL profile and database identity stay compatible. [Reproducer and timing controls](runtime/evidence/stock-mysql-cold-first-response.json).

On emulated ARM64 Android 13, two separate processes using installed v17 verified every byte of the complete import’s 4,742 shader outputs. The first rejected the older genuine receipt from a different import. Both selected generation `9d5f8a86c2ef253bd5ad9cde6b493e34e789cc5ab6b9a1f49008485b34b969f1` with zero compiler calls. The v18 APK preserves these shader assets. [Installed Android receipt and full readback](runtime/evidence/non-custom-v17-full-stock-installed-android-shaders.json).

## Published v17 qualification

[Esteria Stock 0.1.0-non-custom.17](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.17) is the v17 signed update. Producer `2149ae6001b68d896a1fef61f905aeb5fb3115c6`, version code 17, 336,899,353 bytes, APK SHA-256 `dc68c5ced8f0f4a155d86135f70a8522766e483957df06e0ce5544d488ac2ace`. All six public files passed independent download verification. The APK has the same package and v2/v3 signing certificate as v16. All 123 assets and four native libraries matched v16 byte for byte. [Public readback](runtime/evidence/non-custom-v17-public-apk-readback.json) · [Device procedure](NON-CUSTOM-TESTING.md).

The v17 launcher removes the first-launch Wine Mono prompt for the selected native PE. It can finish a source-matched interrupted prefix in place and report the updater phase, exit and bounded native reason. Android ARM64 reproduced a PRoot socket bind failure in the new repair process and passed with its shorter temporary path. Cancelling, resuming, verifying an already finished update and reopening the same prefix passed in separate owners. The ordinary client path passed its own control. The public v17 subsequently installed over v16 with the same Android UID, passed the interrupted repair and verified the warm no-op using its installed classes. The disposable prefix and sentinel survived. [Android repair controls](runtime/evidence/non-custom-v17-android-wine-prefix-repair.json) · [Signed in-place update and repair](runtime/evidence/non-custom-v17-installed-prefix-update.json).

In an offline Android 13 ARM64 package update, v16 installed all four real MySQL schemas. The public v17 retained the UID, first installation time, database UUID and slot, account and configuration. Two clean reconstructed-client authentication diagnostics verified fresh SRP session keys against SQL. First use took 30.742 s and relaunch took 9.253 s. Neither launch recopied server providers. Worldserver with the empty control data mount reached its first starting-area MAP/VMap check. The full-data server run, normal graphical login and physical Thor character persistence remain open. [Installed signed v17 authentication and restart](runtime/evidence/non-custom-v17-native-android-grunt.json).

On the independent full-source run, the production Java importer recovered from cancellation, published all 188 original files and reused them in a fresh process in 0.138 s with zero copied bytes. An independent audit checked every normalized CRC and SHA-256. The signed ARM64 map extractor produced 5,744 maps, 246 DBCs and 14 camera files under Linux QEMU user emulation. An intentional cancellation after sealing that phase left it selectable on reentry. The real Coldridge and Northshire map headers and hashes passed. The outstanding server gate is full-data admission and worldserver readiness. [Original source and import](runtime/evidence/stock-complete-source-and-import.json) · [Map extraction, cancellation and starting tiles](runtime/evidence/stock-complete-world-maps.json).

With the complete enUS source, the signed v17 ARM64 shader compiler produced 1,580 modules under QEMU user emulation. Production Java admitted 4,742 outputs and 102,132,134 bytes. Reopening took 7.020 s with zero compiler calls and no source copying. All 3,162 runtime-facing files matched the earlier guard-bounded stock run byte for byte. Both starting-area collision tiles also passed the assembled VMap checks. [Full-source shaders and warm reuse](runtime/evidence/stock-complete-source-shaders.json) · [Sealed map and collision phases](runtime/evidence/stock-complete-world-maps.json).

## Historical v16 checkpoint

[Esteria Stock 0.1.0-non-custom.16](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.16) introduced the stock shader repair. Producer `b12fe53270a62677a625564582e264a8e5733d8b`, APK SHA-256 `de9d108a725aeb7a8eea1041bd1a72eb7a5acde811595cf71c886f6937f74ab4`, 336,887,065 bytes. All six public assets matched their original bytes. SDK v2/v3 verification preserved the stock certificate and package. [Publication readback](runtime/evidence/non-custom-v16-public-apk-readback.json) · [Build and test gates](runtime/evidence/non-custom-v16-release-gates.json).

V16 selects reconstructed PE `fa3e74b7f332fef0f212e954a0de18f685ead8bd`. Its complete Wine front-end replay exited with zero Vulkan validation errors. The reviewed world-data reader `06ede7399445e1aace7566a0c584d6fba2c005703393afd2f7ba0fd9e5c4fe29` keeps the v10–v15 output recipe `c911baddd7c49fa21fa4a3bc022d75c69fa66daddde3a6970129cf652dad18ff`. Preparation can reuse verified hashes within one uninterrupted ownership period. The selected import, receipt, prepared generation and interrupted work keep their identities. Each new owner tests its volume and verifies the selected generation again. Matching qualified metadata can avoid another full world payload read. [Renderer replay](runtime/evidence/stock-client-forwarded-loader-linux-arm64.json) · [Measured reader behavior and compatibility](runtime/evidence/prepared-operation-inventory.json).

The named shader repair previously returned `prepared shader generation changed` every time a current output had changed, and invoked the compiler zero times. The new repair holds import and shader ownership, validates a replacement before activating it and can recover an already completed replacement. Its separate driver leaves the seven shader recipe files and generation keys intact. Native ARM64 qualification compared 1,580 initial compiles, 1,580 repair compiles and zero warm compiles against authenticated stock inputs. The same-size damaged module was restored. [Source-bound repair evidence](runtime/evidence/non-custom-v16-native-shader-repair.json).

The public v16 APK also completed cold shader preparation (214.422 s), normal warm admission (1.531 s, zero MPQ reads/copies/compiles), pointer repair (21.650 s) and a fresh same-size SPIR-V corruption repair (221.359 s) on offline native ARM64 Android 13. The source-bound test used 16 original MPQ providers through authenticated read-only ranges. All 3,162 runtime-facing file hashes were restored. [Installed shader owner and repair](runtime/evidence/non-custom-v16-installed-android-named-shader-repair.json).

On the same Android platform, the stock installation created and promoted all four real MySQL schemas, including the Playerbots ledger. A new process selected the same promoted database in 263 ms with zero provider copies. The packaged authserver returned a build-12340 realm twice and both negotiated session keys matched the owned SQL rows. These tests used a disposable store and an empty world-data mount. [Android database and auth](runtime/evidence/non-custom-v16-native-android-db.json).

Enforcing Android 13 denied the server owner's read of its own child's TCP tables. The session can now duplicate and inspect the retained child's socket descriptors. The ordinary Android app rejected foreign, wildcard and extra IPv6 listeners. Native ARM64 proved the exact authserver endpoint across two authenticated sessions and a clean database restart. The Thor's latest reported shader failure still needs its matching support export. Physical world entry, saving and three cold offline relaunches remain open. [Android findings](runtime/evidence/stock-server-listener-enforcing-android13.json) · [Native handshakes](runtime/evidence/stock-auth-owned-fd-native-arm64.json).

# Stock v15 signed startup candidate

[Signed stock v15 release](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.15) · version `0.1.0-non-custom.15` (15), produced at `d5e7715587b980d9e41f9070c21e0fc21c543101`. The 336,862,047-byte APK has SHA-256 `f6aa8c4ad674e71d3aed59099f0b952efc44a0ae2333a77efdbff81188489510`. All six published assets matched their staged bytes. Android SDK v2/v3 verification matched the stock signing identity. [Public readback](runtime/evidence/non-custom-v15-public-apk-readback.json) · [Packaged asset comparison](runtime/evidence/non-custom-v15-apk-asset-continuity.json).

The v13 Thor support export reached a complete world receipt before ten legacy terrain shaders failed translation. The v14 shader selection passed the complete native ARM64 stock corpus. With all 1,580 generated modules present, the real reconstructed client reached its first frame and issued 210 invalid Vulkan compressed-image clears. The software renderer crashed before showing the title. [Reproducer and validation](runtime/evidence/stock-client-bc1-initialization-linux-arm64.json).

The v15 runtime selects corrected client `807c4384ef28f4da51d3c50eec5082627cad36ea` and retains prepared client `471ee42faadf4a97a1d0a86989cf1452621f2dc5`. The six-file client diff affects texture initialization, its test and the build workflow. The executable and provider archive change. The stock world helper, seven server patches, SQL, shader inputs and compiler retain their exact identities. An APK-owned digest binds the measured executable to its reviewed prepared identities. Existing generation `cdf2eec23f3bea5f7036f57c307ae7c91300fd059bcc716ba65b2733bd0b3d7e` stays selectable. [Executable pairing](runtime/client/renderer-compatibility.json) · [GPU readback](runtime/evidence/non-custom-v15-compressed-clear-readback.json).

The stock launch-view adapter also rejected a normal loose `Interface` directory in the official ZIP. The stock selection now leaves that directory in the immutable import and loads signed UI from the selected MPQs. A regression exercises the production adapter through first launch-view preparation and warm reuse, and verifies that a custom UI selection retains its preservation rules.

On offline Linux ARM64 the repaired PE rendered the animated Northrend front end, read 17 external SPIR-V files and scrolled the first-run license screen through the selected input bridge. A separate native ARM64 run authenticated two fresh instances of the PE against the packaged authserver on loopback, with a clean MySQL restart between them. The packaged native worldserver opened all four database pools and entered world initialization. With an empty diagnostic data mount it reached the first starting-area MAP/VMAP check and exited 1 after 0.486 seconds. Production readiness with the complete selected data is still open. [Measured worldserver startup](runtime/evidence/stock-native-world-starting-area-boundary.json). The physical Thor report ends at v13 shader translation. [Graphical execution](runtime/evidence/stock-client-bc1-initialization-linux-arm64.json) · [Grunt authentication](runtime/evidence/stock-client-packaged-grunt-linux-arm64.json) · [Installation and support export](NON-CUSTOM-TESTING.md).

The public v15 installed over signed v14 on offline Android 13 ARM64. The existing UID, private directory, configuration and disposable database row survived. The installed Java shader consumer authenticated all 4,742 outputs of the independently compiled generation, and the corrected renderer provider was reused with zero copied bytes on reentry. The packaged Linux Turnip ICD found no KGSL character device on this emulator. The Thor has yet to run this candidate. [Signed upgrade and Android execution](runtime/evidence/non-custom-v15-signed-update-renderer.json) · [Test and release gates](runtime/evidence/non-custom-v15-release-gates.json).

## Historical v14 checkpoint

# Stock v14 terrain shader repair

[Signed stock release](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.14) · `0.1.0-non-custom.14` (14) · producer `6b37bfe4b75bf298fe765ec9667e92e739c4e53e` · APK SHA-256 `fdeac1008d4fbac4d0b3e9b16d0106b877cf92541705f2e7a45ce16c454f4c32`. All six public assets matched their staged bytes. The public APK passed v2/v3 verification with the v13 signing certificate. [Build and execution evidence](runtime/evidence/non-custom-v14-release-gates.json).

On the Thor, v13 reused the completed world receipt after 31 seconds and then failed strict translation on ten legacy terrain records. The v14 Vulkan selection checks the five exact legacy containers, winning effect files and all 32 active Terrain1 permutations. A native ARM64 Linux run strictly translated 2,778 real stock records and compiled and validated 1,580 SPIR-V modules in 122 seconds. A separate native run prepared all four database schemas, verified an authserver build-12340 SRP session key and cleanly reopened the same MySQL instance. [Native shader run](runtime/evidence/non-custom-v14-native-shaders.json) · [Database and authserver](runtime/evidence/non-custom-v14-packaged-stock-auth.json).

The selected client, server, seven patches, SQL and eight native archives keep their previous identities. The world helper manifest `c911baddd7c49fa21fa4a3bc022d75c69fa66daddde3a6970129cf652dad18ff` continues to select Thor generation `cdf2eec23f3bea5f7036f57c307ae7c91300fd059bcc716ba65b2733bd0b3d7e`. V14 can fully revalidate compatible completed v12/v13 shaders. Session admission retains its independent integrity check. [Asset continuity](runtime/evidence/non-custom-v14-apk-asset-continuity.json).

Install in place, keep **enUS** and **Balanced**, then select **Repair local component → Shaders** followed by **Start local game**. Repair **Database setup** if the launcher names it. The next physical gate is completion of shader preparation on the retained import. The reference graphics guest ran the real client through its first frame callback on software Vulkan. Its no-generated-shader control exited 139 with a black frame and pointer. A visible login, stock world entry and saved-character relaunch still need proof. [Reference client](runtime/evidence/non-custom-v14-stock-client-reference.json) · [Testing and support export](NON-CUSTOM-TESTING.md).

## Historical v13 checkpoint

# Stock v13 shader repair

[Signed v13 release](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.13) · `0.1.0-non-custom.13`, version code 13 · producer `2a9daba045da516a6ae7212d7bac94262f559d59` · APK SHA-256 `9d9809d5e04b4bac5d1f0826d4fb0255a53318fe3220f5a7d19e8a077b01dbae`. All six public assets matched the staged bytes. The public APK passed SDK v2/v3 verification against the v12 stock signing certificate and package identity.

Android 13 x86_64 instrumentation passed both production receipt consumers and its same-key debug update. The separate signed-production update attempt stopped at baseline installation because the emulator supports x86_64 only. Exact-signer continuity is verified. In-place installation and saved-character persistence on the Thor remain open. [Build, test and support evidence](runtime/evidence/non-custom-v13-release-gates.json).

The November 7 Thor report from v12 reached the production shader translator. Android accepted world generation `cdf2eec23f3bea5f7036f57c307ae7c91300fd059bcc716ba65b2733bd0b3d7e`. The full verification read 7,309,202,449 bytes in the preparation helper. A named shader repair selected the same world receipt at 32 seconds and started the shader worker at 39 seconds. Both workers exited 2 on a winning delete marker in `Data/patch.MPQ`.

The v13 APK-owned shader reader treats a winning deleted BLS member as absent for that exact path. A lower shader profile or a newer live replacement can still supply the shader. The compiler, executable, client/server revisions, world-data helpers, providers and stock SQL profile retain their v12 identities. The v12 support export contains neither the private MPQ payload nor a shader receipt. First complete shader translation on that import is the next physical-device gate.

The exact packaged compiler passed on a native ARM64 Linux runner with synthetic encrypted patch archives. In a separate offline x86 Linux/QEMU test, cancellation during the first compile preserved the import. A fresh process resumed and compiled four modules. Three subsequent cold processes took 0.344, 0.343 and 0.345 seconds, invoked the compiler zero times, and preserved the receipt and every output byte and mtime. Three separate offline JVMs admitted the resulting receipt through production ShaderSetup and verified all 44,313 bytes and 14 files each time. [Measured runs](runtime/evidence/non-custom-v13-offline-shader-reuse.json).

Install over the existing stock app. Keep **enUS** and **Balanced**, then select **Repair local component → Shaders**. If the next reported component is **Database setup**, select **Repair local component → Database setup**. Once ready, choose **Start local game**. Keep the existing import and app data. See [device testing and support export](NON-CUSTOM-TESTING.md).

## Historical v12 handoff

# Esteria Stock v12 — signed startup candidate published

Producer `7f556ff7bec24cdb6472efb0af7b319116dfae4f` on `non-custom`; version `0.1.0-non-custom.12`, code 12, package `io.github.russianranger.esteria.stock`. [Published release](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.12); APK 336,849,664 bytes, SHA-256 `255d3157f0b251b810b9087bbe2c12937927d8cc1a1e0c99cda346716f259fd7`. Android SDK v2/v3 signature and manifest checks passed against the exact v11 baseline; the original certificate is unchanged. All six public assets passed complete anonymous byte readback. Release `437249264`, APK asset `719252553`. [Testing procedure](NON-CUSTOM-TESTING.md).

**Active functional blocker:** the real reconstructed client/title and subsequent stock session cannot be exercised here: no authorized Thor/ARM64 Android runner with the retained imported assets is attached. Last real Thor success remains the v10 Python world-data format check; the next unqualified stages are Android receipt acceptance, shader completion and database/service/client startup. The available support ZIP has bounded logs, not the genuine data/shader receipt or its import-journal preimages. Host Python-produced schema fixtures exercise the actual Android consumers but are not that missing device evidence.

V12 removes preparation orchestration from normal Start. Typed, source-bound selections reuse installed runtime/data/shader/database components under actual ownership. Initial/full preparation and named component repair remain explicit. Fresh session ownership still requires full payload validation; no proof is carried across a released lease. The measured removed cost is one preparation-time full world inventory/hash pass before session admission, not all verification. Host read accounting is in `runtime/evidence/non-custom-prepared-read-baseline-host.json`; its 109-byte synthetic data is not a Thor performance measurement.

Server admission has its own fixed 12-minute budget, separate from the 180-second native auth/world readiness budget. Operation-bound phase receipts expose phase/process/condition/elapsed time; hashing now obeys the selected read policy and cancellation. Large or pressure-throttled admission may still exceed its bound. The internal title-only harness uses the selected reconstructed executable, matching shaders/providers and owned cleanup without requiring local account/service readiness; no real title frame has yet been observed.

**Retained compatibility:** client `471ee42faadf4a97a1d0a86989cf1452621f2dc5`, server `f35f04d01689f034778e3474b3c820092f51e461` plus the same seven hashed patches, Eluna `58d7652138887783228b9727bd1fa4e08f00342b`, all providers and stock SQL selection remain frozen. Six generation-bound helper bytes remain identical to v10/v11: helper identity `c911baddd7c49fa21fa4a3bc022d75c69fa66daddde3a6970129cf652dad18ff`. The reported completed generation `cdf2eec23f3bea5f7036f57c307ae7c91300fd059bcc716ba65b2733bd0b3d7e` remains eligible for checked selection; no migration or new extraction is imposed by this APK change. Imports, mutable databases/configuration and saves are not reset.

The existing cache stays disabled. Actual Android 13 x64/PRoot testing exposed denied hardlink creation; the Java NIO probe also exposed timestamp rounding to whole seconds. Followup run `42324899164` at qualifier `05b656272f58a06bb2fbefd40c9d10c4a9f8cf13` completed all observations, but the same-size/restored-mtime Java edit also left ctime unchanged. Overall qualification remains false; this is no physical Thor or production cache proof. Full verification fallback remains authoritative. Named repair preserves corrupt completed output and may require diagnosis rather than automatically replacing it.

Exact-producer CI passed complete ARM64 packaging (run `42323699677`), launcher/core/lint (`42323699791`), tooling (`42323699763`: 1,519 passed, 101 environment/dependency skips), native ARM64 SQL installation/reentry/restart/clean stop (`42323699722`), Android 13 installation/update/receipts (`42323699667`) and native extractor output (`42323699775`). Native SQL did not execute authserver/worldserver. Clean CI rebuilt the APK/native bridge from declared inputs while restoring and verifying frozen provider/source/debug archives; it did not rebuild every external engine. Local ownership, cancellation, fresh shader integrity, production receipt consumer and instrumentation compilation checks also passed. Real-client capture remains opt-in and unexecuted because the required runner/assets are absent.

Next action: use the signed in-place candidate on the retained device state; Start if prepared, otherwise finish missing shader/database stages once. Collect the first failing phase before changing any pin. Continue through genuine title/login, Human Warrior world entry, saving and three cold offline relaunches. The M2 material guard and later creature-height upstream candidate were inspected and deferred because neither matches a reproduced failure here; native extractor trees were unchanged. No optional MPQ work began before stock acceptance.

Publication staging independently verified the exact signed payload, but both CI creation attempts returned HTTP403 for POST release creation. Authorized browser publication completed additively at the exact producer tag; no repository permission change was made. The signing ledger now records v12; preserve update-12's original baseline-11 transport. Latest publisher-diagnostic launcher/tooling checks passed. No execution task remains running at this handoff. Records: `runtime/evidence/non-custom-v12-release-gates.json`, `non-custom-v12-android13.json`, `non-custom-v12-native-sql.json`, `non-custom-v12-android-stat.json`, `non-custom-v12-public-apk-readback.json` and `runtime/releases/non-custom-v0.1.0-non-custom.12.json`.

## Published v11 baseline — historical

# Esteria Stock v11 — completed-data receipt update published

[Signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.11/Esteria-Stock-3.3.5a-arm64.apk) · [Testing procedure](NON-CUSTOM-TESTING.md).

Install v11 over the existing `io.github.russianranger.esteria.stock` app. Keep the completed import, world/navigation output, app data, databases and saves. Use the same locale and **Balanced** speed, then retry **Prepare local runtime / world**. Matching completed v10 data receives full byte verification before reuse; unchanged valid output does not require another extraction. Hashing still takes time. Do not uninstall, clear storage, reimport or delete the completed output. Export support before another retry after failure.

The v10 owner attempt passed Python world-data checks and activated generation `cdf2eec23f3bea5f7036f57c307ae7c91300fd059bcc716ba65b2733bd0b3d7e`, then Android returned `Prepared data source/import selection differs` after 2,513 seconds. Android JSON escaped forward slashes in mandatory import-ancestry keys and tool paths, while Python generated the fingerprint with literal slashes. V11 fixes that byte contract in both completed-data and shader receipt consumers. Source/import/tool/helper checks remain enforced.

The report separately records a low-memory exit about 4h18m before this attempt, at Android cached-process importance 400. No operation is logged at that timestamp and its trigger is unknown. The reported preparation ended with an explicit Java exception, pressure zero and about 34.7 MB Java heap use. Existing memory guards and speed controls remain active.

All production Python helpers remain byte-identical to v10. The six-file data helper generation remains `c911baddd7c49fa21fa4a3bc022d75c69fa66daddde3a6970129cf652dad18ff`; this Java-only compatibility fix preserves the completed generation key. Client/server/Eluna pins, native providers, one-worker extraction and the offline architecture are unchanged.

Producer `22ef2c726abbd4414c88be19cae921a70d4535c2`; publisher `c174d6f8d9bb4a652c816a5751c99453be35c2c3`, run/job `41557382781` / `125659464379`. Release `432139507`, APK asset `703775893`. APK 336,837,376 bytes, SHA-256 `80bb686f779878d9c9dd459eb642a45fabe55ffb59d2a4d94f0964520e531a80`; certificate `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.

All six exact-producer gates passed: complete ARM64 package, native SQL, Android 13, launcher/core/lint, tooling and shipped ARM64 extractor output. Android readback verified all 37 artifact members and 60 unique source identities, preserving the earlier import/update/helper/shader/SAF/control checks and adding three Python-produced receipt tests. Those new tests exercise both Java consumers and canonical byte vectors through Android's own JSON implementation. Native SQL backing/restart and the unchanged native extractor proof retain their separate component scopes.

All six public assets passed complete anonymous length/hash readback. The exact producer tag, SDK v2/v3 signatures, persistent certificate, version 11 manifest and equality with the locally signed APK passed. Update-11 receipts retain their baseline-10 binding. Future publication requires a higher version code and the exact public v11 APK; preserve historical releases and transports. Publisher validation jobs also passed.

Actual Thor shader completion, SQL preparation, normal local client/world startup, controls/audio, persistence and offline relaunch still require the owner retry. Host synthetic formats, native component checks, emulator receipts and package/signature checks do not qualify those device results.

Records: `runtime/releases/non-custom-v0.1.0-non-custom.11.json`, `runtime/evidence/non-custom-v11-public-apk-readback.json`, `non-custom-v11-release-gates.json`, `non-custom-v11-owner-binding.json`, `non-custom-v11-canonical-json-audit.json`, `non-custom-v11-python-receipt-host.json`, `non-custom-v11-host-validation.json`, `non-custom-v11-native-sql.json`, `non-custom-v11-native-output.json` and `non-custom-v11-android13.json`.

## Published v10 baseline — historical

# Esteria Stock v10 — post-navigation preflight update published

[Signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.10/Esteria-Stock-3.3.5a-arm64.apk) · [Testing procedure](NON-CUSTOM-TESTING.md).

Install v10 over the existing `io.github.russianranger.esteria.stock` app. Keep the completed import, app data, databases and saves. Use the same locale and **Balanced** speed, then retry **Prepare local runtime / world**. Compatible completed navigation and the failed final assembly are verified for reuse. Hash verification still takes time; a verification stage is not a fresh extraction. Do not reimport or clear storage. Export support before another retry after failure.

The v9 owner bundle reached final generated-data preflight after about 140 minutes and returned a generic format error, with no new low-memory kill recorded. The exact offending filename is unknown because the old diagnostic omitted it. Source review found eleven stock disk layouts rejected by a server SQL-layout check: ten single-float GT tables and packed PowerDisplay. V10 admits only these exact client471 variants in the explicit stock profile, without rewriting payloads. Malformed headers/lengths, custom profiles, continuation fragments and unrelated tables remain strict.

The ten GT variants use the pinned server's SQL loading path. PowerDisplay is read natively from the original packed client file; its source SQL table is empty, so that client file remains required. Reviewed v8/v9 checkpoints and compatible final assemblies survive retry. Bounded diagnostics retain offending group/path/reason and distinguish phase hashing, final assembly and preflight. Existing speed levels, memory controls, one native worker, source pins and the v7 native data provider remain unchanged.

Producer `a7e9f6354f557c0ac52b756a602cbeeaafa7b789`; publisher `ea0f7c416786b5f881b07a66cde61ae04e191aee`, run/job `41388591990` / `125094812270`. Release `431071858`, APK asset `700505644`. APK 336,837,376 bytes, SHA-256 `a18be108682833e7d3efbc1bf6ae2a2722641127e0dda6c5f57211991a4a991d`; certificate `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.

All six exact-producer source gates passed: complete ARM64 package, native SQL, Android 13, launcher/core/lint, tooling and shipped ARM64 extractor output. Android readback verified all 35 artifact members, 14 existing named tests plus four preparation-control tests, and 46 unique source identities. Actual native SQL verified canonical nonempty backing for all eleven GT tables across restart; PowerDisplay retained its authentic zero SQL rows. Host C++ fixtures exercised packed PowerDisplay decoding and the GT disk/SQL distinction. The five-member ARM64 extractor proof covers synthetic DBC output and long-path/reentry behavior.

All six public release assets passed complete anonymous length/hash readback. The exact producer tag, SDK v2/v3 signatures, persistent certificate, version 10 manifest and equality with the locally signed APK passed. Publisher validation jobs also passed. Update-10 receipts retain their baseline-9 binding; future publication requires a higher code and the exact public v10 APK as its prior baseline. Preserve historical releases, transports and source/debug companions.

Physical Thor preparation, shader completion, normal client login/world entry, controls/audio, persistence and offline gameplay still require the owner retry. No host, SQL, emulator or packaging receipt establishes those device results.

Records: `runtime/releases/non-custom-v0.1.0-non-custom.10.json`, `runtime/evidence/non-custom-v10-public-apk-readback.json`, `non-custom-v10-release-gates.json`, `non-custom-v10-owner-preflight.json`, `non-custom-v10-preflight-review.json`, `non-custom-v10-native-format-host.json`, `non-custom-v10-resume-host.json`, `non-custom-v10-native-sql.json`, `non-custom-v10-native-output.json` and `non-custom-v10-android13.json`.

## Published v9 baseline — historical

# Esteria Stock v9 — preparation speed, resume and storage update published

[Signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.9/Esteria-Stock-3.3.5a-arm64.apk) · [Testing procedure](NON-CUSTOM-TESTING.md).

Install over the existing `io.github.russianranger.esteria.stock` app. Keep the completed import, app data, databases and saves. Start with **Balanced** preparation speed and retry **Prepare local runtime / world** with the same locale. To compare a different speed, Stop and wait for cleanup before changing it. While idle, use **Check reclaimable storage**, then **Trim obsolete files**. Do not reimport or clear storage; export support before another retry after failure.

The v8 owner bundle records a memory-pressure pause after about 103 minutes, followed by another attempt that reached navigation meshes and was cancelled. The exact cause of the first memory pause is unknown because the next attempt replaced its diagnostic sample; an automatic restart is not established. No new low-memory kill is recorded. Visible runtime setup reused the same generations with zero copied bytes. The old phase code retained failed UUID navigation directories but started fresh on retry, repeating native work and retaining additional partial copies.

V9 offers Gentle 8, Balanced 32 (default) and Fast 64 MiB/s preparation verification/copy limits. These are I/O pacing levels, not total-world ETAs; native navigation CPU time remains separate. Imports keep their existing 8 MiB/s policy. Real pressure still causes 2 MiB/s backoff or a pause. A critical trim signal with verified healthy system/heap headroom backs off instead of immediately aborting native preparation. Native conversion remains one worker with the 4 GiB address-space guard. Bounded rotating clean-input cache windows replace repeated whole-archive advice.

Exact input/output checks permit completed compatible phases and valid partial navigation tiles to resume, including reviewed v8 staging. Incomplete or incompatible tiles are rebuilt and a stopped phase is never marked complete. Recognized duplicate phase attempts are reclaimed after child cleanup. Idle-only storage maintenance removes obsolete immutable runtime generations and redundant owned archive copies while preserving the current/expected runtime, imported client, world checkpoints, databases and saves. Unrecognized objects remain protected. Stage, native tile and operation/cancellation diagnostics distinguish continued work from a new attempt.

Producer `f39b52459d08fb85bf4fe6da5edddf8bccdea8bf`; publisher `92537ac872242efd0e5b20513c47136b65c2d3bc`, run/job `41369089018` / `125035452108`. Release `430963964`, APK asset `699999137`. APK 336,829,184 bytes, SHA-256 `5066512b124da61a8b6e662f91b3617720fd8f249824300c4e2f6afebfa386d2`; certificate `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.

All six exact-producer source gates passed: complete ARM64 APK, native SQL, Android 13, launcher/core/lint, tooling and shipped ARM64 extractor output creation. Android readback verified all 35 artifact members, the existing 14 named import/diagnostic/timing tests and four new preparation-control tests, with 46 unique source identities matched. The new component checks cover activity speed persistence, trim-only backoff versus real low memory, worker-scoped policy and owned-storage cleanup preservation.

Local validation passed 113 Gradle tasks and ran 1,564 host tests: 1,460 passed and 104 dependency/environment skips. Focused checks passed 50 resume tests, 28 speed-policy tests and nine storage filesystem tests. The real-clock host hash fixture exercised all three speed levels with unchanged bytes under a 96 MiB address-space limit; its timings do not measure Android conversion or owner-world preparation.

All six public release assets passed full anonymous length/hash readback. The exact producer tag, SDK v2/v3 signatures, persistent certificate, stock version 9 manifest and equality with the locally signed APK passed. Update-9 receipts retain their baseline-8 binding; future updates require a higher code, the same certificate and the exact public v9 APK. Preserve all historical releases and transports.

Physical Thor preparation, rendering/world entry, controls/audio, persistence and offline gameplay remain unqualified until the owner retry. Client/server/Eluna pins and the source/debug-qualified v7 native data provider remain unchanged. Native extractor evidence covers synthetic DBC output and long-path/reentry behavior; it converts no owner data, map tiles or camera models.

Records: `runtime/releases/non-custom-v0.1.0-non-custom.9.json`, `runtime/evidence/non-custom-v9-public-apk-readback.json`, `non-custom-v9-release-gates.json`, `non-custom-v9-android13.json`, `non-custom-v9-native-output.json`, `non-custom-v9-owner-preparation.json`, `non-custom-v9-resume-host.json`, `non-custom-v9-resume-review.json`, `non-custom-v9-speed-host.json` and `non-custom-v9-storage-host.json`.

## Published v8 baseline — historical

# Esteria Stock v8 — output-path fix published

[Signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.8/Esteria-Stock-3.3.5a-arm64.apk) · [Testing procedure](NON-CUSTOM-TESTING.md).

Install over the existing `io.github.russianranger.esteria.stock` app. Keep the completed import, app data, databases and saves, and retry **Prepare local runtime / world** with the same locale. Do not reimport or clear storage. Verification remains paced at 8 MiB/s, dropping to 2 MiB/s or pausing under pressure; one 15.6 GiB hash pass takes about 34 minutes, with later phases adding time. Export support before another retry after failure.

The v7 owner report stopped at DBC directory creation, with no new low-memory kill and about 8.6 GB available. The extractor truncated its absolute `-o` output argument to 127 bytes and tried to create a directory beneath that nonexistent truncated parent. V8 passes `-o .` inside the same verified private phase working directory. The v7 ordered native tools, input bounds, provider priority, cleanup and memory controls remain unchanged.

Producer `7c1755968afee2fc1ec5448ce7c853a815750b3f`; publisher `7b01584c8a7679536aa95831c0107a81bc0aca1d`, run/job `41341085661` / `124951043905`. Release `430800823`, APK asset `699278685`. APK 336,808,704 bytes, SHA-256 `cfd47c5f0cc921fef0fcceda12df664367471269fe77d4c846c0100defadb76f`; certificate `5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.

All six exact-producer gates passed: complete ARM64 APK, native SQL, Android 13 components, launcher/core/lint, tooling and shipped ARM64 extractor output creation. Android readback verified all 14 named tests, 37 source identities and 33 artifact members, including update preservation. Local validation passed 109 Gradle tasks, 39 actual SDK release tests, 51 focused adapter/storage/I/O tests and ran 1,539 host tests (1,435 passed, 104 dependency/environment skips). Restoring the old absolute-path argument fails the new regression.

The shipped ARM64 extractor reproduced the old absolute-path failure with a 152-byte output path. The fixed relative output succeeded for fresh and existing directories and emitted the exact synthetic DBC bytes, using the production execute and memory policies. Inputs remained unchanged. This is output-path/DBC-fixture evidence; it converts no owner data, map tiles or camera models and does not establish Android/Thor world preparation.

All six public release assets passed full anonymous length/hash readback. The exact producer tag, SDK v2/v3 signatures, persistent certificate, stock version 8 manifest and local signed-byte equality passed. Update-8 receipts retain their baseline-7 binding; future updates require a higher code, the same certificate and the exact public v8 APK. Preserve all historical releases and transports.

Physical Thor preparation, rendering/world entry, controls/audio, persistence and offline gameplay remain unqualified until the owner retry. Client/server/Eluna and native-provider pins remain unchanged.

Records: `runtime/releases/non-custom-v0.1.0-non-custom.8.json`, `runtime/evidence/non-custom-v8-public-apk-readback.json`, `non-custom-v8-release-gates.json`, `non-custom-v8-native-output.json`, `non-custom-v8-android13.json`, `non-custom-v8-owner-output-path.json` and `non-custom-v8-adapter-host.json`.

## Published v7 baseline — historical

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
