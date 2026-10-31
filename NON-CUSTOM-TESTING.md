# Esteria Stock 3.3.5a / non-custom — consolidated Thor procedure

This is the separate `io.github.russianranger.esteria.stock` app. It installs beside the custom Esteria app. Neither uninstall the custom app nor clear its data. This app creates its own local account and private saves; it does not use a ChromieCraft account or public realm.

The release's `release.json`, signing receipt and `SHA256SUMS` identify the exact APK version, app/client/server revisions and certificate. Check the published APK hash before installing. World entry on actual client data and Android ARM64/Thor must be reported separately from host/build evidence.

## One preparation and play session

1. Install the signed ARM64 APK from the non-custom prerelease. Have adequate storage for an app-owned client copy, world/shader outputs and database; fresh database preparation reserves an additional 4 GiB. Folder import avoids an extra ZIP copy.
2. Choose **Import client folder** and select the parent containing `Wow.exe` and `Data`, or choose **Import client ZIP**. Use your complete ChromieCraft 3.3.5a installation. Keep standard Blizzard `patch.MPQ`, `patch-2.MPQ`, `patch-3.MPQ` and locale patches. Do not edit or delete any source files. Keep the source unchanged until import completes.
3. Read the compatibility result. VERSIONINFO and archive checks are distinct from content/signature/runtime validation. If an essential input is missing, the report names it. Unknown/modified overlays must be diagnosed; do not remove every file with “patch” in its name.
4. Select the installed client language and choose **Prepare local runtime / world**. The app installs its runtime and tools, inspects/selects stock data, generates dbc/maps/vmaps/mmaps/Cameras and graphics shaders, then initializes its local database. No pre-extracted world download or manual MySQL setup is required. Leave the app active during the first preparation; completed phases are retained and reused after interruption.
5. Choose **Start local game**. Allow the owned database/auth/world readiness checks and graphical client initialization to finish. Use the app's managed local login. Do not enter your ChromieCraft credentials. Create an ordinary **Human Warrior**, enter its normal starting area and confirm the world renders.
6. Check walking, turning, camera look/pan and basic object/NPC interaction using touch and the built-in controller. Record anything that fails and whether the failure is in the launcher, login, character creation or world.
7. Exit the client normally and allow the app to report **Local session stopped**. Avoid Force stop for this check. Start again and select the same character; verify its appearance, location and progress persist.
8. After initial preparation, enable airplane mode and disable Wi-Fi. Repeat startup, world entry, movement, a clean stop and relaunch. Gameplay must remain local and offline.

## If a stage fails

Use **Export support bundle** (also available from the game toolbar) and choose a destination ZIP. Keep successful preparation and app data. The bundle includes bounded redacted setup/runtime logs and profile/source identities; it excludes databases, passwords and client assets. Report the failing stage and the bundle together. A forced termination is recorded as recovery required rather than a successful save.

## Scope

No extra Esteria, HD or challenge-mode MPQ is required. Custom races/appearance catalogues, custom maps, Retail/Forever assets, Lua/AIO features and bot AI qualification are intentionally deferred. Their absence is not a reason to fail the stock milestone. Genuine essential stock data, generated runtime world files, shaders, signatures and normal client/server startup remain required.
