# Validation gates

## Focused local checks

```sh
python3 -m unittest discover -s tests -v
python3 tools/verify_protocol.py --client ../client-src --server ../server-src
./gradlew :core:check :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug
```

Use documented SDK/JDK/NDK dependencies and exact source locks from BUILDING.md.
Run focused affected groups first. Real-MySQL and native/emulator fixtures require
explicit disposable environments; skipped tests are not execution evidence.
The importer now passes24 behavior groups under32MiB, including selection-catalog
validation and failed-overlay/corrected-retry preservation. Changing an optional
provider/ABI profile requires a clean app build. After
assembly, verify every selected provider against the final APK, including stored
archive bytes, original metadata/notices and exact source companions.

## Actual evidence boundaries

| Gate | Actual result | Does not establish |
| --- | --- | --- |
| Source/layout/client builds | Client0f all five jobs41012726334; all215 descriptors match254containers/25quests/32client class capacity. | Matched gameplay, appearance/inventory semantics. |
| Matched client/auth |41060555263: real reconstructed client0f + retained compiled six-patch server SRP/session key, loopback realm, unchanged credentials/ledgers and clean shutdown. | CommonMain/assets/world, seven-patch pairing or Android. |
| Compiled six-patch server |41050050193: first/repeat SQL, original ledgers, restart, real SRP/M2 and40-byte persisted session key, loopback realm, credentials/trackers and clean shutdown. | Reconstructed client, world, bots or Android. |
| Current seven-patch derivatives |41050050294: actual stripped program hashes agree across native loader, first/repeat dbimport, ledgers/restart and compiled-auth receipts. | Complete source seal, playerbots/world or Android execution. |
| Appearance binary storage |49/132byte NUL/high-byte REPLACE/read/delete/restart; fixtures removed. Explicit source-derived schema provenance. | Actual game appearance transport, characters or original canonical schema. |
| Native full50 configurations |41041859706: real ConfigMgr parse/reload and preserved source templates; shared renderer produces byte-identical54files/proof/hash. | World/module initialization. |
| Android Wine x64 |41046942035: source-adapted reconstructed EXE entry/offline checks and real loopback transport. | ARM64, CommonMain, GPU/audio or full game. |
| ARM64 Wine host |41057900330: source-built Wine/FEX, complete corresponding sources and actual0f codec/entry/offline/transport/Grunt/software Vulkan/frame/texture/captured WinMM+DirectSound pass. | New471 pairing, CommonMain/assets, Android/Adreno and audible hardware. |
| MySQL service/backup | Native ARM64 persistent service and367,899,260byte restore/restart equality; Android13 x64 Java service41016293760 actual two live cycles. | Production ARM64 Android, existing game-save upgrades/restores. |
| Content install/package | Actual seven-patch4,063files/654,243,888bytes install on Java32MiB, zero-copy cached retry, complete product no-Git verification; local APK/AndroidTest/lint and final dependency/content APK bytes pass. | SQL or Android runtime execution through the new adapter. |
| Schema helper | Real subprocess SQL streaming/private bounded diagnostics, same-service identity rejection, journal cancellation boundaries and concurrent bounded service guard pass host tests. Nine exact helper APK files match source. | Android schema execution or gameplay; native product composition passes separately41058676309/41058676543. |
| Android filesystem/update |40995925492:18installer groups, same-CI-key install-r update preserving runtime/persistent marker. | Stable-key user update baseline or game saves. |
| Input/display/audio/ownership | Actual Android x64 Surface/AudioTrack lifecycle, native ARM64 authenticated X11/XTest, Wine FMOD PCM capture and Android owned-process cleanup pass separately. | Complete guest/client presentation, actual Thor controls/audio or Adreno. |

Public JSON under runtime/evidence and scoped qualification documents retain exact
run/artifact/source hashes and narrowly typed claims. Preserve original failure
receipts; later component success does not rewrite historical observations.

## New schema and recovery checks

`tests.test_android_server_schema_setup` runs actual subprocess fixtures that
stream SQL without exposing credentials in argv/environment and bound private
failure logs. `tests.test_runtime_server_schema_setup` tests exclusive source/UUID
journal ownership, no unsafe SQL replay, and durable intent as the commit-to-file
cancellation boundary. `:core:serviceOperationGuardTest` executes real concurrent
stop/operation races; a timeout retains the owned live engine/lease for retry.

`tools/qualify_android_installer.py` now requires three ServerSchemaAssetsTest
methods in addition to the existing database helper contracts. Their actual
emulator results are pending publication/CI; local compilation and APK closure
alone do not qualify Android behavior.

Initial partial baseline journals still refuse replay. The staged fresh-installation coordinator retains all bootstrap/guest/database
and workspace owners through errors; three Java timeout/retry tests and strict17-
helper APK readback pass. Actual Android SQL and complete promotion remain open; never erase/reinitialize an active or
legacy database to make a test pass. Never claim clean saving after forced stop.

## Shutdown and Android API regression checks

`:core:hostTest` includes a real host stdin child whose first stop fails while
alive. The supervisor retains that child and its database dependency; a subsequent
close retries cleanup while preserving the original failure. Concurrent close
waits for the current retry, and a stop method returning with a live child cannot
report success. Ten host groups pass; this is not game-save qualification.

The first handoff emulator run41064257662 exposed unsupported Android13
`Path.of` in the shared test fixture. The fixture and two production launch-view
uses now use Android-compatible `Paths.get`; the actual emulator rerun is pending.
A later actual run reached file consumption/cleanup, then Android denied creating
a hard-link fixture. The shared contract now records that policy separately from
the host multi-link rejection case; single-link/mode enforcement is unchanged.
Its complete emulator rerun must pass before claiming Android handoff support.
Fresh-slot low-storage tests inject a measured-zero space report against real
filesystem transactions, avoiding any assumption about the host disk capacity.
The production free-space calculation and32GiB reserve bound remain unchanged.

## Remaining acceptance

Selected current-client/seven-patch authentication, normal game login and actual server DBC/map loading,
character creation/selection, world entry, gameplay rendering/input/audio,
combat/loot/inventory/quest interaction, save/relog, small supported bots, offline
play, combined memory/CPU/thermal behavior, Android ARM64 lifecycle and stable-key
user updates remain end-to-end gates. Missing MPQs/custom data block their affected
checks; continue independent implementation.

## Consolidated Thor test

Do not ask the owner to install foundation probes. The normal test comes with one
nearly complete signed APK, working download, exact revisions/build identifier,
update-safe instructions and one support-export action. Procedure: import verified
content; start local play; create/select a character; move/look with controller;
fight/loot/equip/quest; use a small bot group; verify audio; exit/relaunch/relog and
confirm saves; repeat with networking disabled; export one support bundle.
A device-only diagnostic exception requires evidence that independent work is blocked.

## New integration checks

The18-file installation helper inventory now includes `server_playerbots_setup.py`.
45 focused combined-package and playerbots helper/build/qualification tests pass
locally. They establish contracts and rejection behavior, not native SQL or AI.
The previous17-file Android run41070183970 passed actual private installation,
local-login handoff and install-r preservation; its historical receipt is retained.
Future receipts observe the completed runtime filesystem group count from the
instrumentation result rather than assuming18.

`:core:prootMountTest` checks the exact selected Wine adaptation after guest
`env -i`, absence from the Android-owner environment, and type/override rejection.
New runtime/provider native gates pass41069065089 and41073499555; no full
CommonMain/world, Android ARM64/Adreno or audible-device claim follows.

## Confirmed native cleanup and data generation

The presentation/shader owner fixtures cover delayed cleanup, actual Java file
leases and concurrent prelaunch stop. Two hundred launch races and a repeated
throwing/RUNNING native-backend cleanup case verify bounded caller timeouts with
retained creating-thread ownership until confirmed reap. Separate real Linux
C++/JNI12 groups pass; no Android-native cleanup equivalence is inferred.

`python3 -m unittest tests.test_server_data_generation tests.test_assets` passes19
checks: real Linux bounded child output/nonzero exit/cancellation/group cleanup,
and synthetic generation interruption/retry/mutation/input-change contracts.
The writing-descendant case may finish through immediate group cleanup or the
deadline; it establishes bounded completion, not that both branches execute on
every run. Actual MPQ conversion, map coverage and Android extraction are false.

The newer completed-data/API/asset checkpoint passes44 Python checks (23 data/format,15 combined-package
and6 provider helper-closure checks), Java fixed-command/path/import/tool-selection guards,
APK/AndroidTest compilation and lint. All five APK helper source files match
their generated hashes. The new emulator data-helper method is required by the
installer qualifier but has not yet run in this checkpoint. See
runtime/evidence/server-data-binding-host.json.

The actual pinned C++ Bootstrap/libmpq fixture separately accepts the exact
ordered map/vmap conversion arguments and rejects legacy -i/-d selectors. The
bootstrap test executes no extractor main and converts no game assets. Completed
data binding tests also enforce fixed-mount alias generation identity and typed
preflight booleans. The server install-profile APK verifier now invokes the
shared exact helper-closure check, including server-data5.

Current matched authentication41088546780 and native installation finish41088296041
pass with exact new inputs. The Android server-session slice ran39 Python
groups:38 passed and one managed-proc check skipped, three real Java owner/lease fixtures and
APK/AndroidTest/lint/source-helper readback. These are not actual server world or
Android execution gates. ServerDataToolSelection also matches the Python canonical
fixture exactly; the composed provider's source/native positive gate is pending.
