# Android graphics component readiness

`TurnipReadinessProbe` owns a short, asset-independent graphics check for explicit
setup. It uses the existing verified Wine glibc 2.36 runtime and installed Turnip
generation. It installs or downloads nothing, starts no game/server and accepts
no caller-selected command, environment, receipt path or process ID. The setup
coordinator can run it before costly server-data extraction and shader setup.

The selected Wine root includes the measured `/usr/bin/python3.11` executable
(6,616,880 bytes, SHA256
`2ceb9199570aaf34a254b9ea88b1d77f38530833e2a12688d002a59c905b51b2`).
Python is not needed here: the original `run_probe.py` expects its build receipt
at a different payload layout and has a 20-second wrapper deadline. Java directly
supervises the already packaged C executable instead of copying graphics code or
changing a provider/cohort pin.

## Exact existing component

The selected provider's source revision is
`75f50445112818c97f8d8e575d2b1c21e59af6e5`, matched to Wine archive
`c0e13ed15a69fa72541684ac5cef49d71d5d95ee494146bc6e40d11b6977ab46`.

| Component | Bytes | SHA256 |
| --- | ---: | --- |
| Existing C probe |74,368|`f8786b9906a2e9753eaa73d75de849d2fc31872d5781ee73821c3cd9f2476f92`|
| Existing KGSL driver |15,957,640|`a373ecc89b6c5bcb53f117c52328389891902fe56b71c3195af888717a003b58`|
| Original build receipt |20,904|`bf283d2674459fb0dbd2d5feb8452c86a3f2284f7234a78fd2b864818a788220`|

The packaged C source matches `runtime/turnip/probe.c` exactly. Its fixed command
inside the sanitized PRoot guest is:

```text
/esteria-turnip/bin/esteria-turnip-probe /esteria-turnip/lib/libvulkan_freedreno.so /work/probe.json --gpu-readback
```

Only the exact driver generation is bound at `/esteria-turnip`. Both Vulkan ICD
variables name its fixed manifest; external layers are disabled, XDG directories
are empty and the shader disk cache is disabled. A global loader preload is
refused. No imported client data, account, database, Wine prefix or X11 endpoint
is mounted. `MESA_VK_WSI_DEBUG=sw` retains the existing image-presentation choice;
it cannot make a software Vulkan device pass the C probe's hardware checks.

The original C path requires a real KGSL character device, the Mesa Turnip
driver, Qualcomm integrated Adreno 740 hardware and one graphics queue. It draws
embedded shaders into a 64x64 image, reads back all 4,096 pixels, verifies their
expected colors and destroys its Vulkan resources before exclusively writing
the bounded receipt. Its no-GPU CI mode is never selected or accepted by this
application owner.

## Ownership and result boundary

Use `begin(context,wine,turnip)` off the main thread, retain its `Handle`, register
`diagnosticLogs()` and invoke `run(progress,cancellation)`. Close the handle on
every path. The caller serializes this with its other setup operations; the owner
also holds a fixed private `ExclusiveFileLease`. Admission reserves the canonical
lease name before opening an FD, avoiding POSIX duplicate-descriptor lock loss.

The actual child has a five-second deadline. Cancellation, timeout or startup
failure uses the existing owned auxiliary TERM/KILL/reap mechanism. Cleanup is
bounded separately. A delayed cleanup retains the handle, native owner, lease
and static registry entry; close/retry never reports a still-owned child as
finished. `retryPendingCleanup(context)` addresses only this application's known
failed owner and does not replay the probe. Lease-close failures are retained for
another cleanup attempt. No saved-state shutdown protocol is implied.

Before allocating a new probe, the Service asks `pendingCleanup(context)` for its
known failed or stop-requested handle and drives the same retained cleanup loop.
An active caller's handle is refused. A prior cleanup timeout must not publish
the Service idle or clear its diagnostic ownership. The compatibility
`retryPendingCleanup` convenience method alone is not a Service retry loop.

Success requires a natural zero exit, no forced termination or ownership/log
error, unchanged selected providers and the exact 4,096-byte-bounded C receipt.
Strict field/type checks require the hardware readback result and retain false
X11/Android/gameplay claims from the original component format. The returned
facts bind the Wine/driver generations, archive identities, original driver source
and build receipt. They report only this completed offscreen component check.
There is no persisted positive readiness cache or automatic permission to reuse
the result for a later session.

The two fixed support roles are `setup.turnip.stdout.log` and
`setup.turnip.stderr.log`, under
`state/turnip-probe-operations/<owned-32-hex>/logs/`. The receipt, work directory,
configuration and arbitrary paths remain excluded from log export.

## Evidence and remaining validation

`runtime/evidence/turnip-readiness-owner-host.json` records the actual host checks
and exact source identities. Contract fixtures check fixed PRoot argv, exclusive
ICD selection, GPU-only receipt refusal and false broad claims. Owner fault
injection executes real Java ownership and filesystem leases, including delayed
native-backend cleanup and confirmed-reap retry. It does not execute Vulkan,
Android APIs, a PRoot guest, KGSL, a GPU or a game. Application Java/lint pass.

```sh
./gradlew :core:turnipProbeContractTest :core:supportLogSelectionTest \
  :app:turnipProbeOwnerTest :app:compileDebugJavaWithJavac :app:lintDebug
```

Root setup integration and actual Android ARM64 execution remain distinct gates.
No preliminary user/device probe is requested. A later automatically run success
can establish this graphics component's pixel readback, while Wine/client surface
presentation, audio, input, performance and normal world gameplay still require
their own validation.
