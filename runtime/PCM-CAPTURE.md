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

Two host clock/spectral tests pass locally. This workspace denies AF_UNIX socket
creation, so three real socket tests explicitly skip here; CI makes those tests
mandatory and must establish their result. The real guest plugin build and
paired FMOD/Wine run are pending. No runtime audio pass is claimed by these
source-level checks.
