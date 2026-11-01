# Esteria Stock Android

Local Wrath 3.3.5a build 12340 client/server bring-up for AYN Thor Max: Android 13 ARM64, Snapdragon 8 Gen 2, Adreno 740. The reconstructed ARM64 client uses pinned Wine/PRoot with local server/MySQL; gameplay is intended to remain offline after setup.

**V6 graphics-check timeout update:** [signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.6/Esteria-Stock-3.3.5a-arm64.apk) · [testing procedure](NON-CUSTOM-TESTING.md).

Install over the existing `io.github.russianranger.esteria.stock` app, keep data and the completed import, then retry **Prepare local runtime / world** with the same locale. Do not reimport. One 15.6 GiB full hash pass still takes about 34 minutes at 8 MiB/s; later phases and pressure add time. Export support before another retry after failure. Physical Thor v6 preparation, GPU/world rendering, controls/audio and persistence remain unqualified.

The latest owner report was a five-second Turnip graphics timeout with about 9 GB available and no new low-memory kill. V6 completes paced provider/specification admission before starting the unchanged five-second native execution budget, which still includes native startup. GPU receipt/provider validation, cancellation and owned cleanup remain required. Existing preparation memory controls remain active.

Complete ARM64 package/native SQL/14 Android components and public APK/signature readback passed at source `cca8f81abe412b65f0c85da2902f24848a694fd2`. The timing fixture executes no GPU driver; real Thor completion remains unqualified. [STATUS.md](STATUS.md) records exact identities and boundaries.

- [Implementation plan](ANDROID-PORT-PLAN.md)
- [Build instructions](BUILDING.md)
- [Asset requirements](ASSET-REQUIREMENTS.md)
- [Validation gates](TESTING.md)
- [Developer handoff](HANDOFF.md)
- [Runtime packaging](runtime/PACKAGING.md)

This branch is `non-custom`; original custom branches/releases remain preserved. `sources.lock.json` pins client/server inputs; branch labels never select binaries. Extra Esteria/HD assets, custom races and bot AI qualification are deferred.

Original GPL-3.0 [LICENSE](LICENSE) is preserved. Imported assets, databases, credentials, private signing material and generated binaries do not belong in Git.
