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
not FMOD or Wine. The real guest plugin build and paired FMOD/Wine run remain
pending; this is receiver behavior evidence only.

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
and Android qualifications remain false. The new harness path has not yet run;
its guard tests do not establish actual FMOD, plugin or Wine execution.
