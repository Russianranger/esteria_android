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
Changing an optional provider/ABI profile requires a clean app build. After
assembly, verify every selected provider against the final APK, including stored
archive bytes, original metadata/notices and exact source companions.

## Actual evidence boundaries

| Gate | Actual result | Does not establish |
| --- | --- | --- |
| Source/layout/client builds | Client0f all five jobs41012726334; all215 descriptors match254containers/25quests/32client class capacity. | Matched gameplay, appearance/inventory semantics. |
| Compiled six-patch server |41050050193: first/repeat SQL, original ledgers, restart, real SRP/M2 and40-byte persisted session key, loopback realm, credentials/trackers and clean shutdown. | Reconstructed client, world, bots or Android. |
| Current seven-patch derivatives |41050050294: actual stripped program hashes agree across native loader, first/repeat dbimport, ledgers/restart and compiled-auth receipts. | Complete source seal, playerbots/world or Android execution. |
| Appearance binary storage |49/132byte NUL/high-byte REPLACE/read/delete/restart; fixtures removed. Explicit source-derived schema provenance. | Actual game appearance transport, characters or original canonical schema. |
| Native full50 configurations |41041859706: real ConfigMgr parse/reload and preserved source templates; shared renderer produces byte-identical54files/proof/hash. | World/module initialization. |
| Android Wine x64 |41046942035: source-adapted reconstructed EXE entry/offline checks and real loopback transport. | ARM64, CommonMain, GPU/audio or full game. |
| ARM64 Wine host | Current0f controlled-peer Grunt plus source-specific codec/entry/software Vulkan/frame/texture/audio scopes pass historical pinned runtime. | Android/Adreno; the new source-built adaptation has its own pending gates. |
| MySQL service/backup | Native ARM64 persistent service and367,899,260byte restore/restart equality; Android13 x64 Java service41016293760 actual two live cycles. | Production ARM64 Android, existing game-save upgrades/restores. |
| Content install/package | Actual seven-patch4,063files/654,243,888bytes install on Java32MiB, zero-copy cached retry, complete product no-Git verification; local APK/AndroidTest/lint and final dependency/content APK bytes pass. | SQL or Android runtime execution through the new adapter. |
| Schema helper | Real subprocess SQL streaming/private bounded diagnostics, same-service identity rejection, journal cancellation boundaries and concurrent bounded service guard pass host tests. Nine exact helper APK files match source. | Android schema execution, compiled updater composition or gameplay. |
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

Initial partial baseline journals still refuse replay. Fresh-installation slot
and promotion recovery work is ongoing; never erase/reinitialize an active or
legacy database to make a test pass. Never claim clean saving after forced stop.

## Remaining acceptance

Matched reconstructed client/server authentication, actual server DBC/map loading,
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
