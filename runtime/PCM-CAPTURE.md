# FMOD/Wine PCM transport qualification

`tools/pcm_capture.py` is a bounded Linux receiver for the same playback-only
little-endian protocol used by `native/guest-bridges/pcm_esteria.c` and Android's
`PcmProtocol`. It supplies a simulated monotonic playback clock, accepts only
48 kHz stereo S16_LE, and retains the bytes actually accepted by each write.
Partial-write acknowledgments let the ALSA producer retry the remainder without
replaying accepted samples. Reset/stop clears the clock and queued-frame count;
an underrun cannot consume samples submitted later.

The receiver owns one new socket under an existing private directory. It refuses
stale endpoints, verifies peer UID, limits concurrent connections to eight and
total streams to 64, and retains at most 4 MiB per stream / 16 MiB in total.
Socket operations and shutdown are bounded. Cleanup checks the endpoint inode
before unlinking. Reports are written only after workers stop and include each
raw capture's size/hash plus spectral measurements. Malformed/truncated input,
overflow, incomplete EOF or failed cleanup cannot qualify a stream.

The client `Tools/AudioTests` fixture uses the reconstructed FMOD source with
explicit WinMM or DirectSound output. Its two-second signal is 1 kHz on the left
and 2 kHz on the right. The receiver requires substantial samples on both
channels, the expected frequency/amplitude and strong rejection of the other
channel's frequency. The fixture's own API/clock success marker and zero exit
must also pass; captured samples alone do not qualify its playback lifecycle.

This is **FMOD/Wine/ALSA PCM transport**, not Android audio qualification. The
receiver does not use AudioTrack or a physical output device, and reports
`androidAudioQualified`, `audibleOutputQualified` and `physicalLatencyQualified`
as false. Game assets, music decoding and game audio integration remain separate.

```sh
ESTERIA_REQUIRE_SOCKET_TESTS=1 python3 -m unittest tests.test_pcm_capture -v
```

All five capture tests passed in [integration tooling CI 40993458123](https://github.com/Russianranger/esteria_android/actions/runs/40993458123)
at `b06de55f5b17f27ae9659abcfdaf93a61b749a9e`, including real AF_UNIX partial-write
retry, exact captured signal, malformed input, storage caps and endpoint ownership.
This workspace denies AF_UNIX socket creation, so those three tests explicitly
skip locally; CI requires their execution. The tests exercise a synthetic sender,
not FMOD or Wine; those tests are receiver behavior evidence only.

The optional Wine harness accepts `--audio-driver`, `--bridge-dir` and
`--bridge-revision` together. The bridge payload must match that exact integration
commit, every current guest source hash, the pinned build-input lock, the Wine
runtime archive and the actual plugin's ARM64 ELF/hash/dependency report. Native
Wine ALSA libraries and system ALSA configuration are separately byte-pinned in
`runtime/runtime-sources.lock.json`; the existing base runtime identity is intact.

The harness selects the private plugin in a fresh configuration, explicitly
selects Wine's ALSA driver and disables PulseAudio for these fixture processes.
It runs WinMM and DirectSound separately, observes Wine shutdown, lets capture
workers drain EOF, then exports prefix-separated PCM files. Both backend markers,
zero process exits, successful owned cleanup and matching captured stereo signals
are required for `linuxArm64FmodPcmTransportQualified`. Generic `audioQualified`
and Android qualifications remain false.

The first real paired run [40995927216](https://github.com/Russianranger/wowdecomp_esteria/actions/runs/40995927216)
used client `7a226415d0ca34ac90f931b51890f7bfc6dad5be` and integration
`61bf8a134845276cb78430884d557e477ff286aa`. Both Windows builds passed. WinMM
actually delivered 98,422 stereo frames through the source-built ALSA plugin;
the capture matched the left/right signal and drained EOF after Wine stop/wait.
The fixture failed because polling a naturally finished FMOD channel returned
`FMOD_ERR_INVALID_HANDLE`. DirectSound was not reached, and the audio gate did
not pass. The correction registers the real END callback while paused and
requires exactly one callback plus prior observed playback/sample progress.
The independent PCM signal remains mandatory.

Each backend already stops and waits for the owned Wine server before inspecting
capture EOF. Final cleanup now reuses only the latest backend's observed successful
stop and wait, and performs another bounded wait. Otherwise it still issues the
normal stop followed by wait. This avoids interpreting a redundant stop of an
already absent server as a runtime failure. A failed or unobserved stop is never
accepted merely because its exit is 1; final wait failure prevents every scope
from qualifying.


The corrected run [40998295147](https://github.com/Russianranger/wowdecomp_esteria/actions/runs/40998295147)
passed all five jobs at client `243b6c4dd141976f043d1b1a0d465631c40890ec`, paired
with integration `682f8c309365e7c8f4cd1a3503cc794275c73c8e`. The native Linux
ARM64 Wine job123879322876 executed both real backends with zero exits, exact
lifecycle markers, clean PCM EOF and successful stop/final wait. WinMM captured
122,414 frames (489,656 bytes); DirectSound captured 123,344 frames (493,376 bytes).
Each contained 91,999 strong left samples and 87,999 strong right samples with
the required channel frequencies and rejection. Captures include the drain period.
`linuxArm64FmodPcmTransportQualified=true`; all earlier codec/entry/software
Vulkan scopes also passed. Generic audio, Android and game-login flags stay false.

[Evidence artifact12952801053](https://github.com/Russianranger/wowdecomp_esteria/actions/runs/40998295147/artifacts/12952801053)
has ZIP SHA-256 `b979a81a3fda1c0ece69c4f7492989495643215474f7076533b31d3a1a0e1b52`
and qualification receipt SHA-256
`663bdfd114d8440098556f5e475a4024224b28b8c5700a903d58308762131ffd`.
WinMM raw PCM SHA-256 is
`457f0eeccd12df48ee83915afb73bf63375b5f84dd62d4d9a8f2a2b797bf104d`;
DirectSound raw PCM SHA-256 is
`0348c923eebd4773a1c7027ad35a6f868f8ef1c063967c7445bb529e89de30be`.
