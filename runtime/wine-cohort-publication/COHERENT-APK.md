# Atomic adoption and coherent internal APK

`tools/plan_wine_cohort_adoption.py` is read only. It checks the original native
producer and distinct source recovery identities, then lists exactly seven raw
file replacements: main Wine runtime profile, bridge binary/source locks, Turnip
binary/source locks, shader provider lock and X11 runtime closure. The unchanged
client input remains471ee42f. The legacy f036 releases remain unchanged.

Apply these seven files together only after actual cohort publication and the
public cohort/full original Wine source consumer have passed. The separately
verified proof is stored as `public-source-readback.json`, binding the immutable
release lock identity. The coherent workflow requires this proof and exact
byte equality for every adopted file before building.

The new client provider archive5997af5a was generated with explicit runtime
selection. Its marker records the canonical `runtime/runtime-sources.lock.json`
key and raw selected profile identity; the command line input pathname is not
serialized. AppBuild and the existing combined caller select that same explicit
runtime only for the fixed string profile `WINE_ANDROID_PRIVATE_PE_COPY=1`.
Absence and the empty historical profile preserve their previous calls.

The standalone checker uses the exact retained producer checkout for the new
cohort/source validator. It requires the complete new three input client source
receipt, all19 public cohort assets and every expected provider asset byte in
the actual APK. It additionally checks the source, runtime and X11 locks embedded
verbatim in that APK. It never feeds the new source companion to the historical
`release_client_inputs` two input validator.

`android-wine-cohort.yml` adds the qualified stock server programs, content and
extractors using `qualify_server_providers acquire/build` and all four existing
server APK byte checks. It fetches the public database dependencies once, builds
pinned native PRoot and all current app/native code, then checks the complete
asset/helper/native ABI inventory. The composed data tools profile remains a
separate gate and is not silently substituted for stock extractors.

The workflow acquires the stock artifacts while the required16GiB is still free,
removes only their reproduced input copies after verified provider/source/debug
creation, and removes only the already verified expanded Wine source tree while
retaining the unchanged complete ZIP. Full Wine, cohort and database sources,
stock program/extractor complete sources and paired debug files, PRoot sources
and current integration sources are exported in separate named artifacts. Debug
and source payloads stay outside APK assets.

The historical combined workflow routes an adapted Wine profile to this separate
workflow and skips its legacy job. Its old two input sealer is unchanged. Until
atomic adoption, the new coherent build job is skipped explicitly.

This produces an internal APK with verified package/source bytes. It does not
execute Android guests or server programs, initialize SQL, qualify device
hardware/audio, import game assets, start CommonMain, or qualify world entry,
gameplay or persistent signing. Those remain separate measured gates.
