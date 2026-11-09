# Esteria Stock on AYN Thor

## v27 heat and frame-rate check

Install the v27 APK from the v27 release over the existing Esteria Stock app. Keep the existing import, world, shaders, database and character. V27 turns on **PRoot acceleration**, which lets most guest system calls run without stopping in the tracer. It also requests the next frame while Android shows the current one.

1. Start the local game as usual. If any step that worked in v26 fails, export the support bundle first. Then open **Play → PRoot acceleration**, choose **Off**, start again and report both results.
2. **Same conditions as your v26 bundle:** 60 FPS, the same resolution, location, camera view, brightness, fan mode and charging state, for ten minutes. Take readings around minutes 2, 5 and 10, with the sensor label. Your v26 bundle's hottest zone was `socd` at 73.0 °C. Run `/run print(GetFramerate())` in chat for the engine's frame rate and note how smooth the game looks.
3. **Heat target:** repeat step 2 at 30 FPS. A frame limit change applies at the next game start.
4. After each run, log out normally and wait for **Local session stopped**. Then choose **Tools → Export support bundle → Downloads → Save**. Send both ZIPs with the readings, sensor name, fan mode and frame limit. The bundle records per-process CPU, including PRoot tracers, as well as the PRoot acceleration setting and the kernel release.

## Earlier v26 heat check

Install the v26 APK from the [v26 release](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.26) over the existing Esteria Stock app. Keep the existing import, world, shaders, database and character. V26 slows the local server's update tick, asks Android for a display refresh that matches the frame limit, and turns on Android's sustained performance mode during play when the device supports it. **Sustained performance** in the gear menu turns that mode on or off immediately.

1. Use the same conditions as your last hot reading: **30 FPS**, the same resolution, location, camera view, brightness, fan mode and charging state. Note the name of the temperature sensor you are reading, for example the overlay's CPU, GPU or SoC label.
2. Play for ten minutes and take readings around minutes 2, 5 and 10. If the reading stays above 65 °C, repeat once with **Sustained performance** off so the two runs can be compared.
3. Log out normally, wait for **Local session stopped**, then **Tools → Export support bundle → Downloads → Save**. Send the ZIP with the sensor name, readings, fan mode and whether sustained performance was on. The new `game.lastSession.thermal` field records per-process CPU, CPU and GPU frequencies, thermal zones Android allows the app to read, and the display refresh observed during play.

## Update a working installation

Install the signed update over the existing Esteria Stock package. Open **Play → Start local game** with the existing enUS import and character. Keep the prepared world, shaders and database. For a first installation only, use **Setup** to import and prepare.

On the first normal v25 session, time **Start local game** to the login screen. Export after logout and a clean stop. The bundle gives separate server-ready and client-process timestamps for comparison with your v23 times of 309 and 336 seconds. Your v23 repeat start had already reused the prepared 7.3 GB world.

In game, tap the gear or press Android Back for settings. Drag the gear to move it. **Reset gear position** restores the upper-right placement. A swipe from the display edge reveals the Android system bars. The game fits the screen with its original aspect ratio.

**Frame limit** defaults to 30 FPS. 24 and 60 FPS are also available. Right-stick sensitivity applies immediately to camera and pointer controls. A frame limit change applies at the next ordinary game start at the same render resolution. Compare temperatures at the same location, brightness and fan setting over the same duration. Android thermal status and the selected cap are included in support.

1. Note the installed stock version in Android App info. In the world, try taps at the four corners of the game image. Drag the gear, tap it to open settings, adjust right-stick sensitivity and try the stick immediately. Check **Reset gear position**, Android Back, **Open keyboard**, dismissal and input after returning from Home.
2. For a repeatable heat check, use **30 FPS**, the existing resolution, the same location and camera view, and ten minutes with unchanged brightness, fan mode and charging state. Record those settings. The stock chat command `/run print(GetFramerate())` displays the engine's recent frame rate. Take readings around minutes 2, 5 and 10. If you use a temperature overlay, include its sensor label. Android thermal severity, battery temperature, engine FPS and Android surface posts measure different things.
3. Log out normally, stop the local session from the gear if needed and wait for **Local session stopped**. Choose **Tools → Export support bundle → Downloads → Save** before starting another session. Send the ZIP with the observed FPS and fan setting. V25 records idle readback counts, the observed Vulkan adapter when available, battery temperature and Android thermal severity.
4. Turn on airplane mode and explicitly turn Wi-Fi off. After each clean stop, close Esteria from Recents. Cold-open **Play → Start local game** three times. On each launch, time **Start local game → character selection**, select the same saved character, check its quest and position, then log out and stop cleanly. The support log separately records **server-session-owned-listeners-ready** and **client-started** for comparison with v23 (309 s and 336 s on the last reported Thor run). Note any preparation, download or fallback message verbatim. If the app reports recovery, export before retrying and leave that cycle out of the success count.

## Earlier v22 recovery procedure


1. Install the [signed v22 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.22/Esteria-Stock-3.3.5a-arm64.apk) over Esteria Stock v21. Keep the existing import, enUS, Balanced, world data, shaders and saves.
2. On the Thor that stopped at `creature_loot_template.sql`, choose **Repair local component → Database setup** once. Let the installer verify the four schemas and stop MySQL cleanly. The two earlier failed slots are retained. A completed source-matched database is reused.
3. Choose **Start local game** offline. If repair or Start stops, wait for cleanup, then use **Export support bundle → Downloads → Save**. Preserve the complete ZIP before retrying.

## Subsequent launches and verification

Use **Start local game** on subsequent launches. The session selects the completed import, world, shaders and database. A new owner checks shader bytes. For world data, it compares the selected receipt and all recorded filesystem metadata when the current volume and ownership qualify. Otherwise, the session performs a full world-data byte and header audit. Startup reports the phase and reason for fallback. Only observed reads of the selected inventory extend the admission allowance. Twelve minutes without progress stops admission. The native auth/world readiness timer starts separately and allows 180 seconds.

Use **Prepare / fully verify local runtime and world** for an explicit full audit or initial preparation. For a missing or damaged component, choose the component named in the error. If that repair fails, export support before retrying.

## Verify the normal session and retained state

Use the managed local login and the existing saved character on a working installation. New-character creation belongs to disposable validation realms. Keep the existing resolution.

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
