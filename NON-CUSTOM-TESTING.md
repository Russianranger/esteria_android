# Esteria Stock 0.1.0-non-custom.15 for AYN Thor

Install the signed ARM64 APK over the existing **Esteria Stock** app. Keep the existing import, locale (**enUS** for the reported device) and **Balanced** preparation speed.

1. Tap **Repair local component → Client runtime** to install the repaired reconstructed Windows ARM64 executable. This installs the corrected client and prepares its stock launch view. You can leave the original `Interface/AddOns` directory in place.
2. If shaders have never completed on this import, tap **Repair local component → Shaders**. This selects the current stock terrain shaders and this operation checks all 32 modern terrain variants. An already completed compatible shader generation can be used on **Start local game**.
3. Tap **Start local game**. If the launcher identifies **Database setup**, use **Repair local component → Database setup**, then start again. The existing import, prepared world, matching shaders, database and configuration remain selectable.

## Start with the existing preparation

1. Install the update in place. Retain the same imported client language and select **Balanced** under **Preparation speed** while idle.
2. Choose **Start local game**. It selects existing prepared components without replaying preparation. Status explains reuse or names the missing/invalid component. Admission still performs independent full world-data and shader checks; the metadata cache remains disabled.
3. If preparation never completed, choose **Prepare / fully verify local runtime and world** once to finish the missing stages. Compatible completed work is verified and reused. This is also the explicit full integrity audit, not a step required before every normal launch.
4. For a specifically reported missing component, **Repair local component** offers client runtime, server runtime, world data, shaders or database. It resumes/revalidates that component within existing ownership rules and does not reseed an existing database. Corrupt completed output is preserved and may require diagnosis rather than automatic regeneration; export support if the same rejection repeats.
5. After preparation succeeds, use **Start local game**. Admission has a 12-minute limit, separate from the 180-second auth/world readiness budget. Large data or pressure fallback can still exceed admission; record the phase/time and export support before retrying an unchanged failure.

## Verify the normal session and retained state

Use managed local login, not ChromieCraft credentials. Create an ordinary **Human Warrior**, enter the stock starting area, and check rendering, movement, camera, touch/controller input and basic interaction/combat. Keep the existing resolution.

Exit normally and wait for **Local session stopped**. Reopen the same character and confirm location/progress. Enable airplane mode and disable Wi-Fi, then perform **three cold relaunches**, stopping the app between cleanly closed sessions without clearing data. Each must preserve the same character and avoid extraction, client copying or runtime downloading. Full admission hashing remains expected until the cache path qualifies.

For cancellation/resume, press **Stop** during an explicit preparation/verification, wait for cleanup, then retry the same locale. Valid completed phases must remain reusable. Forced termination is not a successful character save. Compare the same phase when comparing speeds.

| Level | Normal governed Java/Python reads | Guidance |
| --- | ---: | --- |
| Gentle | 8 MiB/s | Lower activity; large admission may exceed its bound. |
| Balanced | 32 MiB/s | Default for this attempt. |
| Fast | 64 MiB/s | Optional comparison with adequate memory headroom. |

These are pacing limits, not total preparation estimates. Pressure may reduce reads to 2 MiB/s or pause work. Native conversion remains one worker with its existing memory guard. Changing speed alone does not invalidate the generation. Import copying retains its separate policy.

## Export a failure before retrying

Reopen Esteria Stock if necessary. Tap **Export support bundle**, choose a destination in Android's save picker, and tap **Save** for `Esteria-support-<timestamp>.zip`. Send the **whole ZIP** plus the selected speed, last displayed phase, elapsed time and whether Stop or Android interrupted the operation. Export before another attempt so retained diagnostics are not overwritten. The bundle excludes credentials, databases and game assets.

Only a fresh installation or genuinely missing import needs folder/ZIP import. Keep standard MPQs in their normal `Data` and locale directories. Custom assets, bots and optional MPQ authoring remain deferred until stock startup and persistence are demonstrated. Host fixtures, native SQL checks and Android emulator tests are component evidence; they do not establish Thor gameplay.
