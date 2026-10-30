# Optional Turnip driver package

This provider installs the source-built ARM64 glibc Mesa 26.1.4 KGSL driver in a
separate immutable generation. Installation starts no process. The integrated
client session can explicitly select it. Native Linux loading on a host without KGSL passed; Adreno 740 execution,
Android execution, X11 presentation and gameplay remain unqualified.

The current selected source is 75f50445112818c97f8d8e575d2b1c21e59af6e5,
matched to Wine archive c0e13ed15a69fa72541684ac5cef49d71d5d95ee494146bc6e40d11b6977ab46.
Its original sources/runtime are also preserved by the public Wine cohort release.
The 46a reference packaging evidence below is historical and is not transferred to
different bytes. See [ANDROID-READINESS-PROBE.md](ANDROID-READINESS-PROBE.md) for
the new short source-owned component check; its host tests do not qualify hardware.

`android-provider.lock.json` pins successful build/probe run
[41009954190](https://github.com/Russianranger/esteria_android/actions/runs/41009954190)
at integration `46a54a223720cdc230074aa6a43f10370718af71`. Artifact `12958015255`
is 267,870,390 bytes with SHA-256
`7a84cde62abb837f8a2d0a066fd91adf58feb53b7916a3120c7ef2224438b706`.
Its name still starts `unqualified-adreno-`: the successful no-GPU test is not a
hardware qualification. Exact build and no-GPU receipts bind both measured ELF
files, source revision, original input lock and license inventory.

## Reproduction and source retention

With Python3.11+ and GNU readelf, obtain that exact original artifact through the
supported GitHub Actions download route, then use absolute canonical paths:

```sh
python3 tools/provider_turnip.py build \
  --artifact /absolute/verified-original.zip --output /absolute/new-turnip-provider
python3 tools/provider_turnip.py verify --provider /absolute/new-turnip-provider
./gradlew :app:assembleDebug :app:lintDebug \
  -PturnipProviderDir=/absolute/new-turnip-provider
python3 tools/provider_turnip.py verify --provider /absolute/new-turnip-provider \
  --apk /absolute/esteria_android/app/build/outputs/apk/debug/app-debug.apk
```

The provider contains two independently checked parts:

| Part | Contents |
| --- | --- |
| `assets/turnip` | Driver, component probe, fixed ICD manifest, all original notices, exact build recipe and component/source receipts, in a deterministic streaming archive |
| `sources` | Unmodified original build ZIP and source companion receipt, outside the APK asset tree |

Source verification streams all 68 locked original archives, totaling 260,796,568
bytes, against the exact source lock and source manifest. It retains the complete
Mesa original, compiler/build input originals and project recipe. It does not
extract a duplicate source tree or claim complete source closure for the separate
Wine rootfs. The companion is mandatory during provider verification and must
accompany any distribution of this optional runtime. It must not be omitted from
the final application source bundle merely because it is outside the APK.

The original Actions artifact has finite retention. The current selected cohort
has a separately verified durable release; this provider tool never publishes it.
`Dockerfile` and the pinned sources remain the rebuild path, but an
unmeasured rebuild is never silently substituted for this recorded binary.

All files have exact size/hash pins; the verifier rereads ELF architecture,
loader/dependency metadata and glibc symbol requirements without executing them.
Neither existing output directories nor imported game data are replaced.
The APK asset uses the `.archive` suffix and ZIP_STORED bytes, avoiding AAPT's
automatic `.gz` transformation. Every installed file is a required hash pin.

## Explicit session contract

`TurnipSetup.prepare` uses the shared bounded/resumable installer and cached
completed-generation checks. It installs only into `runtimes/turnip-arm64` and
keeps its asset cache separate. Before explicit selection,
`requireWineArchive(actualArchiveSha256)` must match the current provider lock's
Wine archive. The historical 46a provider required
`f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e`;
the current selected provider requires the c0e archive identified above.

Bind the resulting verified generation at `/esteria-turnip`. In the sanitized
guest environment, `selectedEnvironment` supplies both `VK_DRIVER_FILES` and
`VK_ICD_FILENAMES` pointing at `/esteria-turnip/etc/turnip-icd.json`, disables
implicit/explicit external Vulkan layers, and selects `MESA_VK_WSI_DEBUG=sw`.
The manifest names only `/esteria-turnip/lib/libvulkan_freedreno.so`. Preserve the
Wine runtime's standard library path. These settings choose software X11 image
presentation, not software Vulkan rendering; GPU support still needs the real
KGSL probe and pixel readback on an Android device. No device test is requested
at this stage, and no default driver or game-start action changes.

## Actual packaging evidence

The produced runtime archive is 3,276,348 bytes, SHA-256
`6d7617c7240876fd7f318ab313eff83b47ed691c5b1639a9f06fc34e913e323c`.
Its 70 regular files total 16,811,661 bytes. All 68 source originals and both actual
ARM64 ELF files passed independent readback. Six focused packaging guards cover
source mutation, exact archive/asset closure, unexpected sibling preservation,
deterministic output, existing-output refusal and APK compression policy.

The actual archive installed through the production Java installer under a 32 MiB
host heap, then reused all 70 files without reopening its archive. An optional
provider APK, AndroidTest Java compilation and Android lint passed; final APK
stored bytes matched the archive. Those are host/build checks. They do not
establish Android driver loading, Adreno rendering, audible output or gameplay.
