# Persistent mutable client launch view

`ClientLaunchView` prepares a private writable executable directory without
modifying the reconstructed-client provider or the imported asset generation.
It copies and reads back the exact ARM64 `WowClient64.exe` and `XvidDecoder.dll`
bytes from `RuntimePackagePlan`, validates their PE signatures, architecture,
executable/DLL flags and hashes, and retains each previous launch generation.
This is filesystem preparation. It neither executes the client nor establishes
asset, network, renderer or gameplay compatibility.

## API and lifetime

The class is in `core.runtime.install` so it can reuse the existing private-file,
lock, hashing and atomic-publication helpers. Construct it with an existing
canonical private `work` directory. Construct `ClientLaunchView.Plan` with the
verified client rootfs, its immutable `RuntimePackagePlan`, the verified imported
root and the import generation SHA-256. The caller must have validated both
source generations using their own receipts. Root Data/Fonts/Interface names are
resolved uniquely without case sensitivity, matching the importer; view names
are canonical while guest link targets retain actual imported spelling. This view does not rehash multi-GB
MPQs; it bounds and validates directory metadata, then copies only two PEs.

`prepare(plan, progress, cancellation)` requires a stopped client. It locks its
owned launch store, resumes an interrupted executable copy after matching its
prefix to the pinned source, reuses completed verified copies, and publishes the
owned stage with one atomic directory rename. A mismatching partial, foreign
owner, modified executable/configuration, or changed guest link fails while
preserving the files. Cancellation never deletes existing settings or views.
The class reports directory-fsync support instead of assuming durability support.

`Plan.arguments()` produces `-datadir`, the Windows form of its private view
path, and `-vulkan`. This method **refuses gameplay arguments when loose Interface
content is present without an active reviewed writable UI selection**.
`deferredLooseTrees` exposes that pending requirement. The five-argument Plan
constructor accepts only a typed `ClientUiStore.Selection`; it binds the exact
import/root/work store and is revalidated before preparation and argument use.
See [WRITABLE-UI.md](WRITABLE-UI.md). A preparation result alone is not permission
to skip this gate. Client revisions
that implement a separately reviewed local-offline policy will need their own
qualified launch-argument addition; the current pinned 69cc client has no such
mode and the view does not invent an unsupported flag.

The layout is:

| Host location below work | Guest use |
| --- | --- |
| `launch/<generation>/WowClient64.exe`, `XvidDecoder.dll` | Exact private copied images |
| `client-state/WTF`, `Cache`, `Logs`, `Screenshots` | Persistent state across provider/data updates |
| `launch/<generation>/Data` | Real directory overlay, with guest-only file links |
| `launch/<generation>/Fonts` when supplied | Same bounded guest file-link overlay |
| `launch/<generation>/Esteria*.bin` when supplied | Guest file links for loose catalog fallback |
| `launch-staging/<generation>` | Owned interrupted preparation retained for resume |

Launch views use fixed guest-only absolute symlink targets. Persistent-directory
links point to `/work/client-state/...`; asset links point to
`/esteria-data/Data/...`, `/esteria-data/Fonts/...`, or an explicitly admitted
`/esteria-data/Esteria*.bin`. The host never follows these links while checking or
preparing the view. An absolute link such as `/work/...` may intentionally be
broken outside the guest. The supervisor must bind the corresponding exact work
and imported generations using `ProotLaunch`'s disjoint fixed mount destinations.
PRoot is not a read-only security mount: same-UID guest code remains trusted, so
source analysis and qualification must still establish that linked assets are
only read.

The two copied PEs are deliberately beside their mutable logs. Source code
creates/deletes `WowClient_crash.log` beside the executable and appends to
`EsteriaDecomp.log` there. Existing per-generation logs remain in that view when
another client/data revision is prepared. No old view is automatically removed.
`EsteriaOff.txt` is never imported or created; any casing of this disabling marker
in a managed view causes verification to fail.

`Plan.environment()` returns `GX_VULKAN_SHADERS=Z:\esteria-shaders`. The selected
shader generation must be separately verified and mounted at `/esteria-shaders`.
It is not generated or fabricated by this class. The supervisor retains Wine's
other environment settings, prefix, home and display/audio session locations.

## Source audit and loopback configuration

Audit reference: reconstructed client
`69ccfaa6a0dd01607d0a99be9b27b7b25dafc5aa`.

- `WoW/Source/Client.cpp`, `SetPaths`, sets both OS current directory and SFile
  base path from `-datadir`. `InitializeGlobal` loads `Config.wtf` and RunOnce
  files before `OpenArchives` calls `InitLoginServerCVars`.
- `WoW/Source/WowSvcs/WowSvcsClient/ClientServices_CVar.cpp` loads
  `data/<locale>/realmlist.wtf` and `realmlistbn.wtf`, with root-file fallback.
  Therefore a direct Data-directory link plus root configuration would leave an
  imported locale realmlist authoritative.
- `Engine/Source/ConsoleBase/ConsoleVar.cpp`, `CVar::Load`, reads ordinary OS
  files, falling back through `WTF/`, and executes `SET` lines. The owned overlay
  supplies real locale files and root fallbacks; it leaves persistent
  `WTF/Config.wtf` and all imported realmlists untouched.
- `WoW/Source/WowServices/Grunt.cpp`, `ClientLink::Connect`, explicitly accepts
  host:port, otherwise defaulting to 3724. Managed configuration contains only
  `realmList=127.0.0.1:3724`, empty `realmListbn`, empty `portal`, and empty
  `serverAlert`. It contains no account or password.
- The current C++ source does not define `patchlist`, `loginserver`, or
  `patchprompt` CVars. Adding those strings would not implement an offline
  policy. `CGlueMgr.cpp` attempts a server-alert URL download, and other streaming,
  patch, Battle.net and extension paths require explicit local-offline controls.
  Empty configuration values alone do **not** prove zero external traffic.
- Root `WoW.mfil`, updater executables and imported `Config.wtf` are not added to
  the view. This avoids silently importing a root streaming setup, but it does
  not qualify all other code paths or incomplete MPQ content.
- `WoW/Common/ComponentCore/EsteriaAppearance.cpp` prefers packed `Esteria/name`
  catalog content and falls back beside the executable; the view only provides
  supplied loose `Esteria*.bin` paths. Missing catalogs remain missing.
- `Engine/Source/Gx/CGxDeviceVulkan/CGxDeviceVulkanShader.cpp`, `IShaderFolder`,
  honors `GX_VULKAN_SHADERS`; otherwise it uses executable-relative folders.

Locale/root override files are atomically created as private managed files. On
reuse, changed contents, an extra realm filename or any case-colliding file or
directory cause a preserving failure. This prevents an unplanned `Realmlist.wtf`
from shadowing the checked lowercase file under Wine's case-insensitive lookup.
No credential is read into receipts or progress messages.

## Loose UI and filesystem limits

Loose `Interface` is an explicit deferred feature, not silently omitted gameplay
content. `WoW/Source/UIUtil/AddOns.cpp` writes `.pub` and `.url` files and can
rename/delete `GlueXML`, `FrameXML` and Blizzard addon directories. A simple
link into immutable imported content is therefore inappropriate. The separately implemented
`ClientUiStore` policy preserves imported originals, prior generations and user
changes, and supplies a typed selection after assessment and activation. Until
that selection is supplied, the gate remains closed. Packed MPQ UI content continues
to be reachable through the Data overlay. Fonts are exposed through individual
validated guest file links; the audited font consumers request those asset paths
for reading, with no font-file writer introduced here.

The metadata walk admits at most 8,192 entries, a depth of 32, and supported ASCII
Windows filenames. It rejects symlinks/special files at every traversed level,
case collisions, reserved DOS device names, traversal, backslashes, trailing
spaces/dots, and names exceeding the reconstructed client's `MAX_PATH` buffers.
The actual 80-character `Z:\work\launch\<64-hex-generation>\` prefix counts
toward the limit. Oversized/unsupported loose trees fail explicitly; no asset is
silently renamed or synthesized. These bounds do not impose a byte limit on the
imported MPQs because they are neither loaded nor copied here.

## Evidence

`ClientLaunchViewTests` exercises synthetic pinned PE copy/resume, wrong paths
and links, case-shadowing rejection, long-path rejection, mandatory loose-UI
gating, per-file Fonts exposure, preserved logs/settings/old views, unowned
content rejection, and corrupted-partial preservation under a 32MiB Java heap.

The actual 69cc client provider also passed a separate host installation and view
check: all 30 packaged files/21,445,584 bytes were verified, both actual ARM64 PEs
were copied/read back, and completed provider/view generations were reused.
That run deliberately used an identified synthetic Data fixture and executed no
PE process; it is not a real asset, Android, login or gameplay test.
