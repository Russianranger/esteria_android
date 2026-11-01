# Esteria Stock Android

Local Wrath 3.3.5a build 12340 client/server bring-up for AYN Thor Max: Android 13 ARM64, Snapdragon 8 Gen 2, Adreno 740. The reconstructed ARM64 client uses pinned Wine/PRoot with local server/MySQL; gameplay is intended to remain offline after setup.

**V8 output-path fix:** [signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.8/Esteria-Stock-3.3.5a-arm64.apk) · [testing procedure](NON-CUSTOM-TESTING.md).

Install over the existing stock app, preserve the completed import and all data, and retry **Prepare local runtime / world** with the same locale. Do not reimport. V8 uses a short relative output argument inside the verified private phase directory, avoiding the native extractor's 127-byte path truncation. Existing v7 native tools, archive bounds and memory controls remain active.

Complete ARM64 packaging, native SQL, 14 named Android tests, real shipped ARM64 extractor output/DBC fixtures and public APK/signature readback passed. Physical Thor preparation/world entry and gameplay remain unqualified; export support before another retry after failure. [STATUS.md](STATUS.md) records exact identities and limits.

- [Implementation plan](ANDROID-PORT-PLAN.md)
- [Build instructions](BUILDING.md)
- [Asset requirements](ASSET-REQUIREMENTS.md)
- [Validation gates](TESTING.md)
- [Developer handoff](HANDOFF.md)
- [Runtime packaging](runtime/PACKAGING.md)

This branch is `non-custom`; original custom branches/releases remain preserved. `sources.lock.json` pins client/server inputs; branch labels never select binaries. Extra Esteria/HD assets, custom races and bot AI qualification are deferred.

Original GPL-3.0 [LICENSE](LICENSE) is preserved. Imported assets, databases, credentials, private signing material and generated binaries do not belong in Git.
