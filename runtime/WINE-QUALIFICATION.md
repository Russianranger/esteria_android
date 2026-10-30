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

Pass requires display readiness, successful Wine initialization, the driver's
zero exit and exact success message, successful Wine stop and observed namespace
exit. It establishes **Linux ARM64 Wine + real Xvid DLL** execution only. The
client executable is hashed for matched-build provenance but is not started.
The fixture does not validate other client imports, Vulkan rendering, Android
process policy, presentation, input, audio, server startup, login or gameplay.
Reports explicitly keep those qualifications false.

The actual client build `a3683cc3644d965bf0ed8d91946cd5d6b3f928e1` imports
MSVCP140 and VCRUNTIME140, whose measured Wine files are AA64. It does not import
VCRUNTIME140_1. The latter's x64 machine value in the candidate is not a blocker
for an unused import. CRT API-set forwarding still needs loader execution.

Run the nine host guard/manifest/capture tests with:

```sh
python3 -m unittest tests.test_wine_qualification -v
```

Host unit tests do not execute ARM64 Wine. The first real CI result remains a
separate required evidence item; an authored harness alone is not a pass.
