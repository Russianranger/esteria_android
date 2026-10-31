# Version 4 import retry

Install v4 over the existing Esteria Stock app and keep its data. Retry the same complete ChromieCraft folder or ZIP with `Wow.exe` beside `Data`; MPQs stay inside `Data`.

Import is deliberately capped at 8 MiB/s with small forced write batches. Under pressure it slows to 2 MiB/s or waits for Android memory to recover. Each 1 GiB copy takes at least 128 seconds; a ZIP adds staging before extraction. Stop remains available. Sustained severe pressure pauses after 60 seconds and retains completed files for retry; folder reuse depends on reliable modification times.

First retry the route that failed, then follow preparation/start below. If Android closes it again, reopen and export the whole support bundle before another import with the last stage/file. New receipts include active speed, memory/headroom, Dirty/Writeback and cache-advice results alongside exit history.

# Esteria Stock 3.3.5a / non-custom — consolidated Thor procedure

This is the separate `io.github.russianranger.esteria.stock` app. Version `0.1.0-non-custom.3` (versionCode 3) updates stock versions 1 and 2 with the same persistent certificate. Install it over the existing stock app; do not uninstall either app or clear app data. Imports, completed preparation and saves remain app-owned. This app creates its own local account and private saves; it does not use a ChromieCraft account or public realm.

The release's `release.json`, signing receipt and `SHA256SUMS` identify the exact APK version, app/client/server revisions and certificate. Check the published APK hash before installing. World entry on actual client data and Android ARM64/Thor must be reported separately from host/build evidence.

## One preparation and play session

1. Install the signed ARM64 APK from the non-custom prerelease. Have adequate storage for an app-owned client copy, world/shader outputs and database; fresh database preparation reserves an additional 4 GiB. Folder import avoids an extra ZIP copy.
2. Choose **Import client folder** and select the client root containing `Wow.exe` and `Data`, or choose **Import client ZIP**. Use your complete ChromieCraft 3.3.5a installation. Keep base archives such as `common.MPQ` and standard `patch.MPQ`, `patch-2.MPQ`, `patch-3.MPQ` inside `Data`; keep locale/speech archives and locale patches inside `Data/<installed-locale>`. A normal enclosing client folder in the ZIP is supported, including sibling README and Apple ZIP metadata. Select one complete client; multiple complete clients are rejected. If you selected `Data` itself, reopen the picker and select its parent containing `Wow.exe`. Do not move MPQs beside `Wow.exe`, rename them or rebuild your ZIP. Keep the source unchanged until import completes.
3. Read the compatibility result. VERSIONINFO and archive checks are distinct from content/signature/runtime validation. If an essential input is missing or malformed, the report names it. Inactive ancillary archives remain in the original import and are recorded as excluded from the separate stock selection. Active unknown/modified patch providers still require inspection; do not remove every file with “patch” in its name. One normal folder or ZIP import is sufficient for this device test; both routes receive independent representative regression checks.
4. Select the installed client language and choose **Prepare local runtime / world**. The app installs its runtime and tools, inspects/selects stock data, generates dbc/maps/vmaps/mmaps/Cameras and graphics shaders, then initializes its local database. No pre-extracted world download or manual MySQL setup is required. Leave the app active during the first preparation; completed phases are retained and reused after interruption.
5. Choose **Start local game**. Allow the owned database/auth/world readiness checks and graphical client initialization to finish. Use the app's managed local login. Do not enter your ChromieCraft credentials. Create an ordinary **Human Warrior**, enter its normal starting area and confirm the world renders.
6. Check walking, turning, camera look/pan and basic object/NPC interaction using touch and the built-in controller. Record anything that fails and whether the failure is in the launcher, login, character creation or world.
7. Exit the client normally and allow the app to report **Local session stopped**. Avoid Force stop for this check. Start again and select the same character; verify its appearance, location and progress persist.
8. After initial preparation, enable airplane mode and disable Wi-Fi. Repeat startup, world entry, movement, a clean stop and relaunch. Gameplay must remain local and offline.

## If a stage fails

If Android kills the app during import, reopen it and export support BEFORE starting another import. The update records Android exit history (including reporting capability, reason/status/importance and sampled PSS/RSS), alongside the last import phase/file and observed Java heap. No new kill report was available during development, so synthetic stress success must not be treated as proof that the owner’s failure is eliminated. Select the same source on retry to reuse completed files when source metadata permits.

Use **Export support bundle** (also available from the game toolbar) immediately after the failure and choose a destination ZIP. Keep successful preparation and app data. For import failures the update records the route, phase, selected-root display label, detected relative root, observed/normalized path and exception chain; opaque document identifiers are represented by fingerprints. Include `status.txt` (the `import.last.*` fields) and `launcher.log` from the bundle together, plus the displayed error if possible. For preparation or startup failures export the whole bundle so the retained stock/world/runtime logs accompany the exact failing stage. The bundle excludes databases, passwords and client assets. A forced termination is recorded as recovery required rather than a successful save.

## Scope

No extra Esteria, HD or challenge-mode MPQ is required. Custom races/appearance catalogues, custom maps, Retail/Forever assets, Lua/AIO features and bot AI qualification are intentionally deferred. Their absence is not a reason to fail the stock milestone. Genuine essential stock data, generated runtime world files, shaders, signatures and normal client/server startup remain required.
