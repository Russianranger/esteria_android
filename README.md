# Esteria Stock Android

Local Wrath 3.3.5a build 12340 client/server bring-up for AYN Thor Max: Android 13 ARM64, Snapdragon 8 Gen 2, Adreno 740. The reconstructed ARM64 client uses pinned Wine/PRoot with local server/MySQL; gameplay is intended to remain offline after setup.

[Signed stock v15 release](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.15) · [Device testing and support export](NON-CUSTOM-TESTING.md).

Install over Esteria Stock and retain the selected import and completed world data. Use **Repair local component → Client runtime** once for the corrected ARM64 executable, then **Shaders** if the previous attempt failed there. Choose **Start local game**. [Current startup evidence](STATUS.md).

- [Implementation plan](ANDROID-PORT-PLAN.md)
- [Build instructions](BUILDING.md)
- [Asset requirements](ASSET-REQUIREMENTS.md)
- [Validation gates](TESTING.md)
- [Developer handoff](HANDOFF.md)
- [Runtime packaging](runtime/PACKAGING.md)

This branch is `non-custom`; original custom branches/releases remain preserved. `sources.lock.json` pins client/server inputs; branch labels never select binaries. Extra Esteria/HD assets, custom races and bot AI qualification are deferred.

Original GPL-3.0 [LICENSE](LICENSE) is preserved. Imported assets, databases, credentials, private signing material and generated binaries do not belong in Git.
