# Android presentation, audio and input bridges

These are implemented component adapters, not an enabled game launch or an
Android qualification. The launcher continues to gate gameplay. The guest
helpers must be built, verified and added to a replaceable runtime generation;
the Android process owner must supervise the X server and both helpers.

## Source and runtime boundary

The read-only reference is `Russianranger/uo-android-launcher` commit
`922d0bbc702db2a1f5a46d8dfc14f77a8fdb712c`. `runtime/bridge-reference.json`
records exact original hashes. Its MIT `native/pcm_trasc.c` is reused as
`native/guest-bridges/pcm_esteria.c`, with the plugin/environment names changed,
a little-endian build guard and zero-length transfer handling. Preserve
`native/guest-bridges/AUDIO-LICENSE` with its source and binary.

The Java adapters, JNI frame receiver and X11 helpers here are new GPL-3.0-only
implementations under this repository's existing LICENSE. They implement the
reference's documented PCM/full-frame protocols. We do not assign an invented
MIT license to reference presentation/Java files that lacked individual notices.
No VirGL, Turnip, DXVK, RFB decoder, game binary, texture or sound is copied.

The exact Debian12 Wine archive is SHA-256
`f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e`.
It already contains Xtigervnc, libX11, libXfixes, libXext, libasound, and Wine's
AA64 `winealsa.drv`/`aarch64-unix/winealsa.so`. It contains neither our helpers
nor the ALSA plugin, and has no libXtst. The input helper therefore statically
links the selected Debian libXtst; its complete original/debian source archives
and distribution copyright notice accompany the build. Other guest libraries
remain dynamically supplied by that pinned runtime.

## Wire contracts and Android ownership

All endpoints are filesystem Unix sockets in a caller-created **0700** session
directory beneath application files. Android checks socket type, private mode
and same-UID peer credentials. A new audio listener refuses an existing path;
cleanup removes only its measured inode. A session owner must resolve previous
process ownership before reusing a directory. Use separate private directories
for simultaneous or replacement sessions.

| Endpoint | Producer/consumer | Contract |
| --- | --- | --- |
| `frame.sock` | Owned `esteria-x11-frame` → `SurfaceBridge` | Request byte 1. Eight network-order uint32 words: `0x54524631,width,height,stride,capture_us,sequence,bytes,flags`. Packed little-endian XRGB pixels; flag 2 means unchanged. Dimensions ≤1280×768 and total ≤1280×720 pixels. Full frames establish a fresh baseline, sequence must advance, resize resets geometry. Region packets are explicitly rejected. |
| `audio.sock` | ALSA `esteria` plugin → `AudioBridge` | Five little-endian uint32 handshake words: `0x50414c54,1,48000,2,capacity`. Capacity 64–48000 stereo S16 frames. Commands 1 start, 2 stop, 3 real AudioTrack playback head, 4 write≤4096 frames, 5 reset. Every command replies; partial writes return only accepted frames for producer retry. |
| `input.sock` | `InputBridge` → owned `esteria-x11-input` | `ESTRIN01` greeting, then four network-order uint32 words. Type 0 absolute(x,y,mask), 1 relative(dx,dy,mask), 2 buttons(0,0,mask), 3 physical key(keysym,down,0). Reply uint32 0 accepted/1 rejected after XSync. Mouse mask ≤31; coordinates/deltas ±4096. |

`SurfaceBridge` posts decoded pixels through the real public ANativeWindow API
with BGRA→RGBA conversion. It closes socket I/O on detach, serializes surviving
workers before a replacement surface starts, bounds retained workers, and reports
failure if shutdown misses its deadline. Its fixed cache is about 3.7 MiB;
diagnostics retain numeric counters only. The helper captures XGetImage and the
XFixes cursor at 30/60 fps and suppresses unchanged payloads. This is local X11
CPU readback, not a zero-copy Android Vulkan surface. Region transport and device
performance optimization remain work.

`AudioBridge` accepts at most eight playback streams, uses nonblocking AudioTrack
writes, actual playback-head position, audio focus/ducking and a start threshold
that fits the producer's buffer. No microphone/capture path exists. Initial
handshakes time out; idle established audio can wait until its owner closes it.
Shutdown closes every socket/track and reports surviving workers instead of
silently declaring successful cleanup.

`InputSink` is the boundary for controller/touch/keyboard policy. `InputBridge`
serializes at most 256 queued events off the UI thread and waits for each guest
acknowledgment. `keySequence` validates and reserves an entire ≤256-event batch
before enqueueing it; this is atomic queue acceptance, not an X11 transaction.
On transport disconnect, the guest releases every injected key/button.
Keysyms are physical **base-level** symbols: text must emit explicit Shift/base
pairs. Shifted/unmapped symbols and Unicode outside this initial contract fail
visibly. No silent upper-to-lowercase substitution or clipboard assumption is
made. Runtime keyboard-map execution still needs qualification.

## Integration order

1. Prepare one private session directory and validate installed guest helper
   hashes/ELF receipts. Keep these replaceable binaries separate from saved data.
2. Start a privately bound Xtigervnc with depth 24, 1280×720 geometry, no TCP X11
   listener and RFB disabled (`-rfbport -1`). Its X11 Unix socket directory belongs
   to this session; do not share a global unauthenticated display.
3. Supervise `esteria-x11-frame /session/frame.sock 30` and
   `esteria-x11-input /session/input.sock` with that DISPLAY. A printed ready line
   alone is not a successful frame or input acknowledgment.
4. Start `AudioBridge` before the client. In the guest session write:

   ```text
   </usr/share/alsa/alsa.conf>
   pcm_type.esteria { lib "/esteria-bridges/libasound_module_pcm_esteria.so" }
   pcm.esteria { type esteria }
   pcm.!default { type plug slave { pcm "esteria" format S16_LE rate 48000 channels 2 } }
   ```

   Set `ALSA_CONFIG_PATH` to this session file and `ESTERIA_AUDIO_SOCKET` to its
   guest-visible `audio.sock`. Disable Wine's Pulse driver for this session so
   its ALSA driver is selected. Preserve other required DLL overrides. Do not
   alter the immutable runtime's global ALSA configuration.
5. Attach `SurfaceBridge` to the caller-owned SurfaceHolder surface and connect
   `InputBridge` off the UI thread. Map touch coordinates to delivered framebuffer
   dimensions. A SurfaceBridge never owns/releases the application's Surface.
6. During lifecycle stop, neutralize input, close these adapters off the UI
   thread, and stop owned guest processes. This does not imply world-server save
   completion; graceful game persistence remains the server owner's contract.

## Reproducible builds and actual evidence

`native/presentation/CMakeLists.txt` builds `libesteria-presentation.so` with NDK
r28c, Android API26, ARM64 and 16 KiB load-segment alignment. The optional native
Gradle provider also compiles this target. No native binary is committed.

`runtime/bridges/` pins the official Debian12 ARM64 OCI digest plus the exact
`20261029T000000Z` signed snapshot, primary dev/compiler package hashes/versions
and original source archive hashes. These match the existing Wine ABI (glibc
2.36, ALSA1.2.8, X11 1.8.4). APT still authenticates the indexes; their exact
InRelease hashes are checked. Historical expiry is disabled only for these
checksum-pinned snapshot entries. The named source build context contains only
`native/`; it does not send app data or signing material to Docker.

```sh
docker build --platform linux/arm64 --target guest-export \
  --build-context bridge-src=./native \
  --secret id=build_ca,src=/etc/ssl/certs/ca-certificates.crt \
  --build-arg INTEGRATION_REVISION="$(git rev-parse HEAD)" \
  --output type=local,dest=/private/new-guest-bridges runtime/bridges
```

`.github/workflows/guest-bridges.yml` builds on native ARM64, inspects the actual
ELF images/interpreters/dependencies/GLIBC requirements without executing them,
and exports measured source hashes, package inventory, notices and corresponding
original archives. The artifact remains explicitly unqualified. This source
companion covers the locked direct build/static-link inputs; it does not claim
the entire existing Wine rootfs's Debian source closure.

Evidence at this checkpoint:

- Six JVM protocol groups pass with a 32 MiB heap: fragmented PCM, partial/zero
  acceptance, malformed/truncated commands, clock bit preservation, and bounded
  input encoding. `PcmProtocolTests` is a standalone Java main.
- The production JNI frame decoder/copy passes a real host socketpair test with
  **stub Android window calls**: colour, stride, resize, unchanged baseline,
  sequence, invalid geometry and truncated data. Run
  `JAVA_HOME=/path/to/jdk python3 -m unittest tests.test_presentation_native -v`.
- All new Android Java compiles with JDK17 `-Xlint:all -Werror`; the actual
  ARM64 Android26 JNI library compiles with NDK r28c `-Wall -Wextra -Werror`.
- The three guest C targets compile on host x64 against checksum-verified Ubuntu
  development packages. Native ARM64 CI
  [40995565147](https://github.com/Russianranger/esteria_android/actions/runs/40995565147)
  passed compilation, actual ELF verification and source export at integration
  `61bf8a134845276cb78430884d557e477ff286aa`. Artifact `12951430269` has SHA256
  `f3365863da63074fb18bf9809cb7df38c161d47e5efe40f2f32c1fe5f6847e3b`.
  The PCM plugin is 71,088 bytes, SHA256
  `bb2f32c2def9e712630ea282aca06fe38bf563b03b07d0672ddf273a18ebb16c`,
  with maximum GLIBC 2.17 and only `libasound.so.2`, `libc.so.6` and the exact
  AArch64 loader as shared dependencies. The two X11 helpers require at most
  GLIBC 2.34. Compilation does not qualify execution.
- A real reconstructed FMOD/Wine/ALSA transport
  fixture with a bounded simulated PCM receiver. That does not qualify audible
  Android output.

The `android-presentation.yml` workflow builds an explicit debug/test-only x64
JNI profile using `-PnativeRuntimeBridge=true -PnativeBridgeAbi=x86_64
-PpresentationEmulatorTest=true`. Production remains ARM64. Its disposable
Android 13 emulator fixture drives the real native decoder from private Unix
sockets into an offscreen `ImageReader` Surface, verifies actual RGBA pixels and
surface recreation, and streams PCM through real `AudioTrack` while checking
accepted frames, playback-head progress and reset. Malformed frames/handshakes,
socket cleanup, and Android's trusted app-directory alias are also checked.
`tools/qualify_android_presentation.py` binds the receipt to the measured APK/JNI
images, source revision and emulator fingerprint. This newly authored gate is
not yet reported as passed. It does not exercise the guest X11 producers, Wine,
ARM64 execution, on-screen presentation, audible hardware output, or Adreno.

Docker and filesystem Unix socket creation are unavailable in the current host;
native ARM64 guest execution, actual Android Surface/AudioTrack/lifecycle,
controller game behavior, sound, and Thor performance remain unpassed gates.
No preliminary device installation or gameplay success is requested or claimed.
