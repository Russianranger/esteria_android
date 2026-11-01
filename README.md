# Esteria Stock Android

Local Wrath 3.3.5a build 12340 client/server bring-up for AYN Thor Max: Android 13 ARM64, Snapdragon 8 Gen 2, Adreno 740. The reconstructed ARM64 client uses pinned Wine/PRoot with local server/MySQL; gameplay is intended to remain offline after setup.

**V5 preparation memory update:** [signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.5/Esteria-Stock-3.3.5a-arm64.apk) · [release](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.5) · [testing procedure](NON-CUSTOM-TESTING.md).

Install over the existing `io.github.russianranger.esteria.stock` app. The owner's v4 folder import succeeded: **keep that import/data, do not reimport**, and retry Prepare local runtime / world. V5 paces Java/Python verification, limits native child virtual memory and shader retention, and preserves preparation diagnostics. One 15.6 GiB hash pass takes roughly 34 minutes at 8 MiB/s; later work adds time. Native extraction is not speed-capped by this policy.

Complete ARM64 packaging, native SQL, Android 13 components and public APK/signature readback passed at source `4adb12f9502af7d734174a94fb8233226d9b4c60`. **Physical Thor v5 preparation and gameplay remain unqualified.** The reported preparation `LOW_MEMORY` exits have not been reproduced or proved eliminated. [STATUS.md](STATUS.md) records exact identities and evidence limits.

- [Implementation plan](ANDROID-PORT-PLAN.md)
- [Build instructions](BUILDING.md)
- [Asset requirements](ASSET-REQUIREMENTS.md)
- [Validation gates](TESTING.md)
- [Developer handoff](HANDOFF.md)
- [Runtime packaging](runtime/PACKAGING.md)

This branch is `non-custom`; original custom branches/releases remain preserved. `sources.lock.json` pins client/server inputs; branch labels never select binaries. Extra Esteria/HD assets, custom races and bot AI qualification are deferred.

Original GPL-3.0 [LICENSE](LICENSE) is preserved. Imported assets, databases, credentials, private signing material and generated binaries do not belong in Git.
