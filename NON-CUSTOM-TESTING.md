# Version 9 preparation speed, resume and storage controls

Install the signed `0.1.0-non-custom.9` / versionCode 9 ARM64 update over the existing Esteria Stock app. The package and persistent certificate are unchanged. **Keep the completed client import and all app data. Do not uninstall, clear storage or reimport the client.** Check `SHA256SUMS`, `release.json` and the signing receipt for the exact APK/source identity.

The latest v8 support report reached navigation-mesh generation. One attempt paused for memory pressure after about 103 minutes; a later attempt was cancelled. It records no new Android low-memory kill. The visible runtime preparations reused the same generations with zero copied bytes. Failed navigation attempts could leave separate partial directories that were not reused on retry. V9 retains valid partial navigation output and migrates compatible v8 work after checking its inputs and outputs.

## Choose a preparation speed

Select **Preparation speed** while the app is idle, then use the same imported client language and choose **Prepare local runtime / world**. The selection is remembered after reopening the app.

| Level | Normal Java/Python verification rate | Use |
| --- | ---: | --- |
| Gentle | 8 MiB/s | Compare with the earlier pacing or use when other apps need memory. |
| Balanced (default) | 32 MiB/s | Start here for the next preparation attempt. |
| Fast | 64 MiB/s | Try after Balanced if the device has sufficient memory headroom. |

These are verification/copy pacing limits, not total-world completion estimates. Actual storage can be slower, and repeated validation, extraction, navigation meshes, shaders and database work add time. Native conversion stays at one worker with the existing 4 GiB virtual-address guard. Bounded buffers and cache windows remain in use at every level; selecting Fast does not increase worker count or remove memory checks. Import copying keeps its separate 8 MiB/s policy.

Memory pressure still reduces governed reads to 2 MiB/s or pauses preparation. An isolated trim signal with verified healthy headroom backs off instead of immediately cancelling a long native phase. Genuine low-memory observations remain a pause condition. Clean-input cache advice now works through bounded windows rather than repeatedly advising every complete archive in each short interval.

## Resume without discarding useful work

1. Install v9 over the current app and retain the existing import. Select its installed locale and **Balanced**.
2. Choose **Prepare local runtime / world**. The status identifies the current phase, so a transition from maps to collision or navigation work is distinguishable from a restart. Provider checks still run before reused outputs are accepted.
3. Leave the operation running while it makes progress. Completed compatible phases and valid partial navigation tiles are reused. Malformed or incomplete partial tiles are regenerated; a stopped phase is never reported as complete.
4. To compare speeds, press **Stop** and wait for cleanup to finish before changing the level. Retry with the same locale. Changing only speed does not change the data generation or require reimporting the client.
5. If a memory pause occurs, wait for headroom to recover, choose a slower level if appropriate, and retry. If a stage fails or Android closes the app, export support before another preparation attempt.

A speed comparison made across different phases is not a benchmark: hashing, model extraction and navigation mesh generation have different workloads. Include the chosen level and last displayed phase when reporting results. The support bundle records the selected rate, pressure/headroom observations and operation outcome.

## Trim obsolete files

Use the storage scan while the app is idle to see recognized reclaimable files, then use the trim action. Maintenance is unavailable during preparation or gameplay. It preserves the imported client, current and expected runtime generations, mutable database, character saves, client configuration and usable world work. It removes only recognized obsolete immutable runtime generations and redundant runtime archive caches. It does not delete normal Blizzard MPQs or ask you to move files out of `Data`.

Compatible v8 world staging is kept until it can be checked and migrated. The preparation helper then removes recognized abandoned duplicate phase directories after the child process has stopped. This avoids deleting potentially useful long-running work merely because it was created by the previous version. Unknown files are retained rather than guessed to be disposable. The reported reclaimable byte count is a file inventory, not a promise of an identical increase in Android free-space accounting.

## Complete the local game test

After world preparation succeeds, choose **Start local game**. Allow database/auth/world readiness and graphics initialization to finish. Use the app's managed local login rather than ChromieCraft credentials. Create an ordinary **Human Warrior**, enter its stock starting area and check world rendering, movement, camera, touch/controller input and basic interactions.

Exit normally and wait for **Local session stopped**. Start the same character again and verify location and progress. Then enable airplane mode and disable Wi-Fi, and repeat startup, world entry, movement, clean stop and relaunch. Gameplay must remain local and offline.

Only a fresh installation or a missing completed import needs **Import client folder** or **Import client ZIP**. Select the complete ChromieCraft 3.3.5a build 12340 root containing `Wow.exe` beside `Data`, including one installed locale/speech set. Preserve root patch MPQs and locale MPQs in their normal locations. No extra Esteria/HD/custom archive is required for the stock milestone.

## If preparation stops

Reopen the app and **Export support bundle before another attempt**. Include the whole ZIP, selected speed, last displayed phase and whether you pressed Stop or Android interrupted it. Do not clear data or reimport. The bundle includes bounded retained logs and observations while excluding databases, credentials and client assets. Accepted cache advice does not measure pages actually reclaimed, and visible child RSS/PSS is not whole-guest memory coverage. Forced termination is never a successful character save.

This remains the separate stock app with the reconstructed ARM64 client, local server/database and offline objective. Custom races/appearances/maps, HD/Retail/Forever content, Lua/AIO and bot AI qualification are deferred. Genuine stock world/shader data and normal signed UI remain required. Component, host and emulator checks do not establish actual Thor preparation, rendering, controls/audio, persistence or gameplay; those still need this device session.
