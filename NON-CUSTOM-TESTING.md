# Esteria Stock on AYN Thor

## Update a working installation

Install the signed update over the existing Esteria Stock package. Open **Play → Start local game** with the existing enUS import and character. Keep the prepared world, shaders and database. For a first installation only, use **Setup** to import and prepare.

In game, tap the gear or press Android Back for settings. Drag the gear to move it. **Reset gear position** restores the upper-right placement. A swipe from the display edge reveals the Android system bars. The game fits the screen with its original aspect ratio.

**Frame limit** defaults to 30 FPS. Choose 24 FPS for a lower render workload or 60 FPS for higher motion detail. Right-stick sensitivity applies immediately to camera and pointer controls. A frame limit change applies at the next ordinary game start at the same render resolution. Compare temperatures at the same location, brightness and fan setting over the same duration. Android thermal status and the selected cap are included in support.

Check movement and camera at all four screen edges. After logging out, use the gear's **Stop session** if the client is still running. From **Tools → Export support bundle**, save the ZIP. Reopen the same character offline three times and check the saved quest and position. If Start reports a component issue, use **Tools → Repair local component** for the named component only.

## Earlier v22 recovery procedure


1. Install the [signed v22 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.22/Esteria-Stock-3.3.5a-arm64.apk) over Esteria Stock v21. Keep the existing import, enUS, Balanced, world data, shaders and saves.
2. On the Thor that stopped at `creature_loot_template.sql`, choose **Repair local component → Database setup** once. Let the installer verify the four schemas and stop MySQL cleanly. The two earlier failed slots are retained. A completed source-matched database is reused.
3. Choose **Start local game** offline. If repair or Start stops, wait for cleanup, then use **Export support bundle → Downloads → Save**. Preserve the complete ZIP before retrying.

## Subsequent launches and verification

Use **Start local game** on subsequent launches. The session selects the completed import, world, shaders and database. A new owner checks shader bytes. For world data, it compares the selected receipt and all recorded filesystem metadata when the current volume and ownership qualify. Otherwise, the session performs a full world-data byte and header audit. Startup reports the phase and reason for fallback. Only observed reads of the selected inventory extend the admission allowance. Twelve minutes without progress stops admission. The native auth/world readiness timer starts separately and allows 180 seconds.

Use **Prepare / fully verify local runtime and world** for an explicit full audit or initial preparation. For a missing or damaged component, choose the component named in the error. If that repair fails, export support before retrying.

## Verify the normal session and retained state

Use the managed local login. Create an ordinary **Human Warrior**, enter the stock starting area, and check rendering, movement, camera, touch/controller input and basic interaction/combat. Keep the existing resolution.

Exit normally and wait for **Local session stopped**. Reopen the same character and confirm location/progress. Enable airplane mode and disable Wi-Fi, then perform **three cold relaunches**, stopping the app between cleanly closed sessions without clearing data. Each must preserve the same character and avoid extraction, client copying or runtime downloading.

For cancellation/resume, press **Stop** during an explicit preparation/verification, wait for cleanup, then retry the same locale. Valid completed phases must remain reusable. Forced termination is not a successful character save. Compare the same phase when comparing speeds.

| Level | Normal governed Java/Python reads | Guidance |
| --- | ---: | --- |
| Gentle | 8 MiB/s | Lower governed read rate. |
| Balanced | 32 MiB/s | Default for this attempt. |
| Fast | 64 MiB/s | Optional comparison with adequate memory headroom. |

These limits apply to governed I/O. Pressure may reduce reads to 2 MiB/s or pause work. Native conversion remains one worker with its existing memory guard. Changing speed alone does not invalidate the generation. Import copying retains its separate policy.

## Export a failure before retrying

Reopen Esteria Stock if necessary. Tap **Export support bundle**, choose **Downloads** in Android's save picker, and tap **Save** for `Esteria-support-<timestamp>.zip`. Send the **whole ZIP** plus the installed version, selected speed, last displayed phase, elapsed time and whether Stop or Android interrupted the operation. Export before another attempt so the bundle retains the failed run. The bundle excludes credentials, databases and game assets.

Only a fresh installation or genuinely missing import needs folder/ZIP import. Keep standard MPQs in their normal `Data` and locale directories. Custom assets, bots and optional MPQ authoring remain deferred until stock startup and persistence are demonstrated. Host fixtures, native SQL checks and Android emulator tests are component evidence; they do not establish Thor gameplay.
