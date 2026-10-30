# Linux ARM64 Wine component qualification

`tools/qualify_wine_arm64.py` runs the real reconstructed-client
`XvidDecoder.dll` through the native ARM64 `test_xvid_adapter.exe` driver. It
verifies the same build's `client-build.json`, hashes and AA64 PE headers before
running. The smoke test checks real DLL loading/exports, synthetic compressed
frame decoding, BGRA channel order, vertical orientation, bounds and decoder
slot lifecycle. No game data or original executable is used.

Use a dedicated **native ARM64 Linux** CI job, not an x86 host with transparent
emulation. It needs Python 3.11+, util-linux (`unshare`, `mount`, `chroot`),
iproute2 (`ip`), root/sudo, and enough space for the 613 MB archive plus a fresh
2.64 GB tree. Checkout this integration repository at an exact commit and use
the same source revision's Windows ARM64 artifact containing:

- `bin/Win/ARM64/client-build.json`, `WowClient64.exe`, `XvidDecoder.dll`.
- `build/platform/Release/test_xvid_adapter.exe`.

```sh
python3 tools/prepare_runtime.py --download --cache "$RUNNER_TEMP/wine-cache" \
  --stage "$RUNNER_TEMP/wine-codec-runtime"

sudo -n python3 tools/qualify_wine_arm64.py \
  --runtime "$RUNNER_TEMP/wine-codec-runtime" \
  --client-dir /path/to/artifact/bin/Win/ARM64 \
  --driver /path/to/artifact/build/platform/Release/test_xvid_adapter.exe \
  --output "$RUNNER_TEMP/wine-codec-evidence"
```

To qualify the software Vulkan reference in the same isolated session, add
either or both optional drivers from the **same workflow's ARM64 artifact**:

```sh
  --presentation-driver /path/to/artifact/build/vulkan/Release/presentation_device.exe \
  --texture-driver /path/to/artifact/build/vulkan/Release/texture_device.exe
```

Each driver is checked as an ARM64 PE executable and its exact hash is included
in the report. The lock separately pins the measured Lavapipe ICD JSON, native
Vulkan loader, Mesa library and Wine Vulkan Unix bridge. Their hashes and ELF
architecture are checked before execution. The selected ICD's API declaration
is 1.1.230. Only that ICD is offered through `VK_ICD_FILENAMES`; an observed
`Vulkan adapter: llvmpipe...` line is also required. Environment selection alone
cannot pass the software-device check. These additions do not alter the base
package identity used by the initial codec-only CI run.

The presentation driver uses the real engine Win32 surface/swapchain path and
clears, submits and presents 16 frames across a resize. The texture driver uses
the real Vulkan image tracking implementation for 20,000 simultaneous images
and 30,000 total create/destroy operations. Each needs zero exit and its exact
success marker. Presentation and texture flags are separate from codec; a
later graphics failure does not erase an earlier qualified codec result when
owned cleanup and logs remain valid. The worker records its intended zero or
handled-failure exit; the observed namespace exit must match that completed
receipt before any component can qualify. Abnormal death cannot retain a pass.
The command still exits nonzero if any
requested check fails. Validation callback availability is recorded separately;
an unavailable layer never becomes a validation-layer pass.

Newer presentation drivers also exercise the real engine frame module: two
full-target clears, two in-pass green rectangles, exact BGRA readback of the
resulting 4x4 scene regions, and two presentations through the engine's embedded
SPIR-V shaders. Add `--require-engine-frame-readback` with the presentation driver
to make this additional scope mandatory. The harness records
`linuxArm64VulkanEngineFrameReadbackQualified` only when that driver's exact
additional success line, the ordinary presentation success marker, software
adapter identity, zero process exit and normal owned cleanup all pass. Earlier
drivers can still qualify basic presentation; they cannot acquire the new flag
without the additional marker. Missing the required marker fails the command.

This checks pixels before the embedded presentation shader, not pixels displayed
by the compositor. It establishes neither data-derived game shader correctness
nor world rendering. The exact new marker is
`PASS: Engine Vulkan frame BGRA readback, partial clears and embedded-shader presentation`.
This scope passed in [client CI 40992315512](https://github.com/Russianranger/wowdecomp_esteria/actions/runs/40992315512)
at client `69ccfaa6a0dd01607d0a99be9b27b7b25dafc5aa`, harness
`32329e64f05d9c9734b7c55c3270fb1800c7aff6`. Both native Windows builds passed;
the actual native Linux ARM64 Wine run reported the exact additional marker,
zero exit, normal cleanup and bounded drained logs on llvmpipe LLVM 15.0.6.
[Evidence artifact 12949797521](https://github.com/Russianranger/wowdecomp_esteria/actions/runs/40992315512/artifacts/12949797521)
contains receipt SHA256
`69bfe354c777abf78e54ed033849235928edf742efdfce3371bca4c1e01379c4`.
The validation layer was unavailable; Android/Adreno and full game rendering
remain unqualified.

## Full executable entry check

Add `--client-entry-check` to copy the already-hashed `WowClient64.exe` into the
private fixture and launch it with its single exact `--esteria-entry-check`
argument. This executes the real Windows image entry, CRT/Storm initialization,
allocator, C++ exception/destructor unwind, FP-control read and main-fiber return
path. Its special mode returns before `CommonMain`; it does not load game data.
Normal client behavior when that argument is absent remains unchanged.

Pass requires exit zero and a new, regular, bounded `Esteria-entry-check.json`
with the exact ARM64/build12340/extension4 entry-only schema, all seven checks
true, and both `commonMainStarted` and `assetsLoaded` false. The client creates
that file exclusively; an existing receipt is refused. The harness exports its
verified contents and original SHA256. The stdout success marker is recorded
only as observed because the real crash logger's `AllocConsole` may redirect it.
`linuxArm64ClientEntryQualified`, `clientExecutableLaunchAttempted` and
`clientExecutableEntryReached` describe this explicit scope;
`gameInitializationStarted` and Android/gameplay qualifications remain false.

## Captured FMOD audio transport

The optional audio gate takes all three arguments together:

```sh
  --audio-driver /path/to/client-artifact/build/audio/Release/fmod_output_device.exe \
  --bridge-dir /path/to/guest-payload \
  --bridge-revision EXACT_INTEGRATION_COMMIT
```

Build that payload with the pinned `runtime/bridges/Dockerfile` from the same
exact integration checkout. The harness verifies current guest source hashes,
build-input lock, runtime archive, actual plugin ELF requirements and native
Wine/ALSA component hashes. `readelf` from binutils is required for this optional
path. It then selects the private ALSA endpoint and runs the real reconstructed
FMOD fixture with WinMM and DirectSound separately. Both process markers and
zero exits, actual captured 1 kHz-left/2 kHz-right PCM, clean receiver EOF and
owned Wine/namespace cleanup must pass. Raw bounded captures and hashes are
included in the evidence directory.

`linuxArm64FmodPcmTransportQualified` describes this separate Linux transport
scope. The receiver supplies a simulated monotonic playback clock: generic
`audioQualified`, Android audio, audible output and physical latency remain
unqualified. See [PCM-CAPTURE.md](PCM-CAPTURE.md) for the tested receiver behavior
and current execution status. The new FMOD/Wine path has not yet executed.

## Ownership and evidence

The output directory must be new. Logs, identities, per-import file/machine
diagnostics, worker exit status and `qualification.json` are retained on success
or a running-test failure. A sudo invocation hands the new evidence files back
to the calling CI account. Upload that directory even on failure. The prepared
runtime is consumed for this one test; a repeated attempt needs a fresh stage.
Do not modify or reuse an application runtime/prefix for qualification.

The owner starts a private mount/PID/network namespace. Its PID 1 mounts only
namespace-local `/dev`, `/proc` and read-only `/sys` views. Only loopback is
enabled; there is no external network interface. TigerVNC supplies a headless
X server with TCP/RFB listeners disabled. Wine uses a fresh prefix and explicit
environment, with HTML/.NET automatic setup disabled. Display, prefix, fixture
and cleanup have deadlines; capped pipe writers retain at most 16 MiB per log
while continuing to drain excess output. Guest files, including the large DLLs
Wine materializes into its prefix, have no process-wide file-size cap. Reader
cleanup is bounded separately because detached Wine services can retain their
output pipes. Overflow, write failure or an undrained stream fails the gate. The owning
`unshare --kill-child=SIGKILL` and PID namespace kill detached services when the
namespace exits. The host's mounts and network remain unchanged. Namespace
support failures are reported; there is no weaker silent fallback.

Codec pass requires display readiness, successful Wine initialization, the driver's
zero exit and exact success message, successful Wine stop and final wait, and
observed namespace exit. It establishes **Linux ARM64 Wine + real Xvid DLL** execution only. The
client executable is hashed for matched-build provenance and is started only
when the explicit entry-check option above is selected.
The codec fixture does not validate other client imports, Vulkan rendering, Android
process policy, presentation, input, audio, server startup, login or gameplay.
Reports explicitly keep those qualifications false.

The actual client build `a3683cc3644d965bf0ed8d91946cd5d6b3f928e1` imports
MSVCP140 and VCRUNTIME140, whose measured Wine files are AA64. It does not import
VCRUNTIME140_1. The latter's x64 machine value in the candidate is not a blocker
for an unused import. CRT API-set forwarding still needs loader execution.

The optional software Vulkan fixtures do not establish Adreno performance,
Android presentation, game-shader correctness, or world rendering. The generic
Android/game/rendering qualification fields remain false; Linux software
presentation, engine frame readback and texture lifecycle have explicit separate fields.

Run the host guard/manifest/capture/scope tests with:

```sh
python3 -m unittest tests.test_wine_qualification -v
```

Host unit tests do not execute ARM64 Wine. The first real CI result remains a
separate required evidence item; an authored harness alone is not a pass.


Both reconstructed FMOD output backends now have actual captured PCM evidence in
client run [40998295147](https://github.com/Russianranger/wowdecomp_esteria/actions/runs/40998295147),
client `243b6c4dd141976f043d1b1a0d465631c40890ec` and harness
`682f8c309365e7c8f4cd1a3503cc794275c73c8e`. The combined codec, entry, software
presentation/frame readback, texture lifecycle and FMOD transport gates all passed.
Exact capture counts, hashes and remaining audio scope limits are in
[PCM-CAPTURE.md](PCM-CAPTURE.md). Android audio and complete game startup remain
separate qualification work.

The optional `--client-offline-check` additionally requires `--client-entry-check`
and invokes the same verified full client twice as `--offline-check` with
`-local-offline` and `--local-offline`. Each invocation must exit zero and write
an exclusive, bounded receipt establishing actual SCmd parsing, both real HTTP
initiation refusals, tracker return, three refused nonlocal/invalid game connects,
three ordinary failure callbacks and released response refs. The checker requires
exact typed fields and keeps CommonMain/assets/loopback-gameplay flags false.
Both spellings plus all namespace, shutdown and log gates are required for
`linuxArm64ClientOfflineBoundariesQualified`. A prior entry/codec result cannot
substitute for this scope. Actual successful local login and full offline gameplay
are separate gates. The new diagnostic/harness is awaiting its paired execution.

The optional `--client-loopback-check` requires the entry and offline checks and
runs the same hash-verified full client executable with
`--loopback-check --local-offline` inside the owned, externally disconnected
namespace. Its separate `linuxArm64ClientLoopbackTransportQualified` flag requires
zero exit, an exclusive bounded receipt with every exact check/count, and the
existing complete namespace, Wine shutdown, log-drain and log-size gates.

This fixture starts the actual network manager and two workers, connects twice to
an ephemeral `127.0.0.1` peer, observes partial two/three-byte frame headers in the
actual parser, compares 17/32,768-byte frame payloads and queued `SendPacket`
output, and compares raw stream receive/send bytes. It verifies normal disconnect
callbacks, released connection references and actual joined worker handles. A
separate real blocked worker forces a ten-second stop timeout: its network,
event and pooled buffers must remain alive until explicit release and a second
successful shutdown. A 25-second causal bound excludes the fixture's 30-second
barrier timeout from establishing that result. The owned process has a
90-second watchdog and the harness a 120-second deadline.

Compilation and actual Windows/Linux ARM64 execution of this new loopback scope
are pending. No authentication, real server protocol, world entry, Android or
Thor qualification follows from this transport fixture.
