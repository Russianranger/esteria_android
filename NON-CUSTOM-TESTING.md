# Esteria Stock 0.1.0-non-custom.16 for AYN Thor

Install the signed ARM64 APK over the existing **Esteria Stock** app. Keep the existing import, locale (**enUS** for the reported device) and **Balanced** preparation speed.

1. Tap **Repair local component → Client runtime** once to select the updated Windows ARM64 executable and its stock launch view.
2. For the reported shader failure, tap **Repair local component → Shaders**. Wait for **Shaders are ready for the selected import**. The repair owns only the current import and shader store. It can reselect a verified generation, recover a completed staged replacement or compile a replacement for damaged output.
3. Tap **Start local game**. If the app specifically names **Database setup**, tap **Repair local component → Database setup**, then start again. Keep the same import, prepared world, configuration and saves.

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

Reopen Esteria Stock if necessary. Tap **Export support bundle**, choose a destination in Android's save picker, and tap **Save** for `Esteria-support-<timestamp>.zip`. Send the **whole ZIP** plus the selected speed, last displayed phase, elapsed time and whether Stop or Android interrupted the operation. Export before another attempt so retained diagnostics are not overwritten. The bundle excludes credentials, databases and game assets.

Only a fresh installation or genuinely missing import needs folder/ZIP import. Keep standard MPQs in their normal `Data` and locale directories. Custom assets, bots and optional MPQ authoring remain deferred until stock startup and persistence are demonstrated. Host fixtures, native SQL checks and Android emulator tests are component evidence; they do not establish Thor gameplay.
