# Esteria Stock Android

Local Wrath 3.3.5a build 12340 client/server bring-up for AYN Thor Max: Android 13 ARM64, Snapdragon 8 Gen 2, Adreno 740. The reconstructed ARM64 client uses pinned Wine/PRoot with local server/MySQL; gameplay is intended to remain offline after setup.

**V7 bounded extraction update:** [signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.7/Esteria-Stock-3.3.5a-arm64.apk) · [testing procedure](NON-CUSTOM-TESTING.md).

Install over the existing stock app, preserve the completed import and all data, and retry **Prepare local runtime / world** with the same locale. Do not reimport. V7 filters the extractor's file inventory before retention, fixing the reported 100,000-name union failure while preserving input bounds, archive order and memory controls.

Complete ARM64 packaging, native SQL, 14 Android components, all 26 actual native reader cases and public APK/signature readback passed. New extractor sources/debug are preserved in the public component release. Physical Thor preparation/world entry and gameplay remain unqualified; export support before another retry after failure. [STATUS.md](STATUS.md) records exact identities and limits.

- [Implementation plan](ANDROID-PORT-PLAN.md)
- [Build instructions](BUILDING.md)
- [Asset requirements](ASSET-REQUIREMENTS.md)
- [Validation gates](TESTING.md)
- [Developer handoff](HANDOFF.md)
- [Runtime packaging](runtime/PACKAGING.md)

This branch is `non-custom`; original custom branches/releases remain preserved. `sources.lock.json` pins client/server inputs; branch labels never select binaries. Extra Esteria/HD assets, custom races and bot AI qualification are deferred.

Original GPL-3.0 [LICENSE](LICENSE) is preserved. Imported assets, databases, credentials, private signing material and generated binaries do not belong in Git.
