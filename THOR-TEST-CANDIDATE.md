# Esteria Android 0.1.0-dev.1 — Thor test candidate

Install `Esteria-Android-0.1.0-dev1-8c1e63d-arm64.apk` (336,697,265 bytes).
Package `io.github.russianranger.esteria`, versionCode 1. Application source:
`8c1e63d43ee0b552d796b862a2c1b1c146a0a7c4`; build 41149985842.
Reconstructed client 471ee42faadf4a97a1d0a86989cf1452621f2dc5;
server f35f04d01689f034778e3474b3c820092f51e461, with seven pinned adaptations.
SHA-256: `8b953bc5e959a4feb716abed3ff7083ee85a2fdedafa44105fc1caeef2e25baa`.

This candidate bundles the rebuilt Windows ARM64 client under ARM64 Wine and
Linux ARM64 server/MySQL under PRoot. Gameplay is intended to run locally after
setup. Imported game files are supplied separately. Full runtime packaging,
native ARM64 SQL and Android13 x64 four-schema setup/restart checks pass. Real
content-backed world play, the complete ARM64 Android session and Thor hardware
qualification are pending. This is the consolidated content/device test.

## Install and prepare

1. Install the APK. Keep this package and signing identity for future updates;
   install updates over it without uninstalling or clearing app storage.
2. Choose **Import client folder** and select the complete existing client root
   containing original `Wow.exe` and `Data`, including one complete installed
   locale and its speech archives. The importer checks original Wow.exe build 12340 and archive structure. A ZIP is
   also supported but needs an additional archive copy. Keep source files
   unchanged until import finishes. Leave room for the imported copy, runtime
   files and generated world data; fresh database setup additionally reserves 4 GiB.
3. Use **Prepare client runtime**, then **Prepare server dependencies · bundled**.
   Select the imported language and use **Prepare local world**. The app prepares
   extraction, shaders and the database. Keep the device powered during this
   potentially long first preparation; completed stages are reused.
4. Use **Start local game**. The app prepares the managed local account and
   loopback services. No manual database/server administration is required.

## One consolidated test

1. Create two Human Warriors with ASCII names. Enter the alt once, log out
   normally, then enter the main at the same starting area. Confirm character
   creation/selection and world entry.
2. Move with the left stick and look with the right. **A** jumps, **LB** targets,
   **B/RB** use action slots 1/2, **X** opens bags. **Y** toggles pointer mode;
   there **A** clicks. Point and use the right trigger to interact with NPCs or
   loot; touch is available. Check basic combat, looting, inventory, quest
   acceptance/progress/turn-in and audible world/combat sound.
3. In pointer mode, **RB** sends Enter to open chat; use the toolbar keyboard
   to enter `.playerbots bot list`, then
   `.playerbots bot add Altname`. Wait for the visible party member and
   `+Altname` roster entry. Use `/p follow`, then target an enemy and `/p attack`.
   `/p add all loot` requests eligible nearby loot. Remove with
   `.playerbots bot remove Altname`, wait for `-Altname`, and relog the alt to
   inspect saved XP/items/position. Start with this one bot; the configured
   ceiling is four and random population is off. Re-add explicitly after relog.
4. Return to the main, use the app's **Stop** control and wait for shutdown.
   Start again and verify character, inventory, quest and setting persistence.
   Briefly leave/return to the app and check input/audio recovery.
5. Stop, install this same APK over the app, and confirm imported data and saves
   remain. Disable Internet access and repeat world entry, a short fight and
   save/relog. All required runtime components are bundled.
6. Use **Support bundle** in-game or **Export support bundle** in the launcher.
   Save the ZIP and return it with a short pass/fail note for the steps above.
   If a step fails, export the bundle while retaining the existing data.

## Material limits

The full gameplay sequence above has not been executed here: complete build 12340
MPQs were unavailable, and no Thor was attached. Missing matched Esteria custom
catalogs/textures/DBC/maps and Retail/Forever assets leave their affected features
unqualified. The first input is a complete stock client; custom packages can be
imported later. Software-keyboard text currently supports printable ASCII;
physical controller behavior, combined memory and thermals need this device test.
Use the ordinary Stop path for saving; forced termination is not a save result.
See ASSET-REQUIREMENTS.md, TESTING.md and runtime/CONTROLS.md for exact boundaries.
