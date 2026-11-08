# Esteria Stock 0.1.0-non-custom.21 for AYN Thor

The November 8 signed v21 Thor repair reused world data at 32 s and shaders at 52 s. The core SQL helper launched at 113 s. The launcher observed 20 file completions and last saw `creature_loot_template.sql` start at 205 s. Cleanup reported forced helper termination at 208 s. MySQL recorded one clean stop in each abandoned slot. The export cannot recover the earlier exception that v21 discarded. Preserve both slots. On this Thor, wait for a signed update before another database attempt. [Physical evidence](runtime/evidence/non-custom-v21-thor-schema-interruption.json).

Install the [signed Esteria Stock v21 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.21/Esteria-Stock-3.3.5a-arm64.apk) over v19. Keep the imported ChromieCraft 3.3.5a client, **enUS**, **Balanced**, and existing saves.

1. For the November 8 Thor failure, choose **Repair local component → Database setup**. The device already selected the stock world and 4,742 shaders. Leave those selections in place.
2. Allow the database repair to finish. After bootstrap, the installer starts MySQL, runs the schema helper, verifies all four schemas, and waits for a clean MySQL stop before selecting the slot. An active source-matched slot is reused.
3. Tap **Start local game**. If a phase fails, wait for cleanup and use **Export support bundle → Downloads → Save** before retrying. Keep the entire ZIP. The report includes retained slot states and available bounded wrapper logs.

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
