# Internal real-client startup capture

`ClientStartupSession` starts the selected reconstructed ARM64 client, Wine,
matching prepared shaders, imported content, Turnip and production presentation
bridge without database/world readiness. It keeps `--local-offline`, omits
`--local-login`, refuses a retained account handoff, and holds the same import
and writable-view leases as `GameSession`. It does not prepare missing content.
No release activity, intent or launcher control exposes this lifecycle.

On an authorized ARM64 development/device runner with the real full provider
APK, matching-signature instrumentation APK and an existing prepared import:

```sh
adb shell am instrument -w \
  -e class io.github.russianranger.esteria.runtime.RealClientStartupCaptureTest \
  -e esteria.realClientCapture true -e esteria.locale enUS \
  io.github.russianranger.esteria.stock.test/androidx.test.runner.AndroidJUnitRunner
```

Use the locale of the retained import. Do not replace the installed app with
an unrelated debug-signed build, clear data, uninstall, or reimport to run this.
Absent full providers, ARM64 or prepared shader pointer cause an explicit skip.
A malformed selected receipt fails rather than being replaced. The test bounds
admission with cancellation after five minutes and captures production 1280×720
frames after 5, 15 and 30 seconds; it neither changes display resolution nor
requires a database. Shutdown attempts normal client close, then reaps the
diagnostic process; forced cleanup is recorded and never described as a save.

The instrumentation status names the private `real-client-capture-*` directory.
Title mode enables Wine file tracing; each native log stream remains bounded
to 8 MiB and may truncate. Inspect successful open/read activity on the selected
MPQs and SPIR-V files; an attempted or failed open is not proof of a real read.
Its `observation.json` contains exact selected source/provider/import/shader
identities, fixed process-log paths, PNG hashes and cleanup state. Collect that
directory and the named logs using the authorized runner's app-private access.
Keep these private; they may contain rendered game data and must not enter Git.

Inspect the actual images and client logs to establish the last real stage.
`commonMainQualified`, `contentReadsQualified`, `shaderLoadsQualified`,
`titleFrameQualified` and `gameplayQualified` deliberately remain false: an X11
background, synthetic frame, Wine process or frame count cannot qualify them.
The selected client has no generic CommonMain success receipt. A genuine title
frame must be traced to this exact reconstructed client and its content/shader
reads before recording title success. Then exercise normal `GameSession` for
login, world entry and persistence.

`:app:clientStartupOwnerTest` exercises argument isolation and delayed cleanup
with real filesystem leases and a controlled host process backend. It supplies
no native ARM64, Android, content, shader or rendering evidence. Ordinary
instrumentation suites skip the real capture unless explicitly selected.
