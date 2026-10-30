# Source-owned ARM64 Wine adoption preparation

The new archive `c0e13ed15a69fa72541684ac5cef49d71d5d95ee494146bc6e40d11b6977ab46`
is separately measured. Native run41069065089 passed all nine component gates
with exact client `471ee42faadf4a97a1d0a86989cf1452621f2dc5`, reusing the successful
Wine/FEX build and complete original sources from run41057900330. This result
remains distinct from that producer's older `0f931bba…` client cohort. See
[`../evidence/wine-arm64-selected471-41069065089.json`](../evidence/wine-arm64-selected471-41069065089.json).

The consumer downloaded and validated the entire original 1,681,474,721-byte
source ZIP before executing the new pairing. Local evidence review independently
recomputed all nine flags, reread original C++ entry/offline/loopback receipts,
checked Grunt positive/negative peer cleanup and reanalyzed both actual stereo
PCM captures. The large source ZIP was not downloaded locally.

`prepare_wine_arm64_adoption.py` produces a separate review-only Android runtime
profile and new bridge/Turnip build contexts. It verifies all six exact retained
package files, source/profile bindings and optional actual selected-client host
evidence. The proposed runtime lock is below the application's 128KiB bound.
Marker and os-release pins occur only in requiredMetadata, avoiding duplicate
installation requirements. Installation bounds use the measured 45-file hardlink
copy fallback and 2,333,910,717 maximum physical bytes. No current production file is changed. Outputs are
explicitly blocked from production selection pending publication and providers.

```sh
python3 tools/prepare_wine_arm64_adoption.py \
  --runtime-package /path/to/verified/runtime-package \
  --host-evidence runtime/evidence/wine-arm64-selected471-41069065089.json \
  --output /fresh/review-directory
```

The separate `x11-runtime.lock.json` was measured from the actual compressed
archive, with only 26,574,452 temporary bytes materialized and then removed.
All 49 ARM64 ELF images, 44 aliases, four loader configuration files and their
DT_NEEDED/interpreter closure were checked. The source-built XTest helper's
direct libXext dependency is an explicit additional root. Four library identities
changed from the previous runtime; hashes were measured again. Static inspection
does not qualify input execution. `inputQualified` and `androidQualified` remain
false. [`../evidence/wine-arm64-x11-closure-c0e13.json`](../evidence/wine-arm64-x11-closure-c0e13.json)
retains the measurement and dependency edges.

The provider-candidate workflow validates the entire retained runtime/source
companion, measures the closure again, rebuilds X11/PCM helpers and observer with
the new archive binding, and executes application-formatted missing/wrong/correct
cookie checks against the new rootfs. It separately rebuilds exact Turnip and
compiler inputs, then executes real valid/invalid GLSL/SPIR-V fixtures and an
exclusive ICD/no-GPU probe inside the retained runtime with network disabled.
It retains new binaries, original upstream/build sources, notices and receipts
even after a later check fails. Wine/FEX are never recompiled by this workflow.
These new provider gates are pending until an actual successful run is recorded.

Before selecting the proposed runtime, publish new write-once binary/source
assets; measure new guest bridge, client, shader and Turnip provider descriptors
and matching source companions; verify authenticated X11, the validated fixed
`WINE_ANDROID_PRIVATE_PE_COPY=1` application profile and the coherent all-provider
APK. Existing descriptors must keep rejecting mismatched archive hashes. Exact
client PE bytes can be reused when repackaging; a changed descriptor/source
binding requires actual package readback. Historical `f036c00a…` releases remain
unchanged. Android ARM64, Adreno, audible output, CommonMain, assets, compiled
server authentication, world entry and gameplay remain unqualified.
