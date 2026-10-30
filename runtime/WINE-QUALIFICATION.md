# Linux ARM64 Wine codec qualification

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
This new scope is implemented but awaits the paired client CI execution.

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
zero exit and exact success message, successful Wine stop and observed namespace
exit. It establishes **Linux ARM64 Wine + real Xvid DLL** execution only. The
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
