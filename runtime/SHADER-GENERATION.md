# Local shader generation

`shader_generation.py` prepares a separate, persistent output generation from a
completed build12340 import. It calls the exact client repository's
`Tools/VulkanShaders` translator in strict mode and a measured glslang executable.
There is no alternate translator, fabricated replacement shader, CDN request or
write into the imported data. The compiler/tool bundle is a separate setup input;
the currently pinned69cc application provider does not yet include this strict
setup integration.

## Transaction and provenance

The caller must serialize imports and keep client execution stopped throughout
preparation and activation. A nonblocking private file lock serializes shader
setup itself. These are trusted app-owned directories, not an isolation boundary
against a hostile same-UID process.

Inputs bind the full client revision, explicit locale, exact shader-tool manifest,
current import ID and SHA-256 of completion/journal/overlay metadata through at
most32 ancestors. Metadata totals are bounded to64MiB. Existing MPQs are not
rehashed by this helper; their imported hashes and immutability are the importer's
contract. The translator still validates the effective MPQ/folder shader inputs
and uses the source-confirmed locale/load order. Private importer completion is
not a signature or a claim that missing Esteria assets are present.

Each attempt writes a new private staging directory. The translator runs serially
with `--strict`, `--client`, `--locale`, `--glslang` and `--out`, never `--deploy` or
a selective `--names` invocation. Captured logs cannot exceed8MiB, setup has a
bounded deadline, and the subprocess group is stopped before reaping its leader.
The retained zombie prevents signalling a recycled process-group identity.
Cleanup itself has a5second reap deadline; failure does not activate output.
The Android adapter must additionally own the complete PRoot process tree.

The output checker rejects partial/refused translation, missing stages/modules,
bad manifest paths, missing fixed-function companions, unexpected files, symbolic
links, malformed SPIR-V word bounds and mismatched entry-point stages. Modules
must target SPIR-V1.0 for the existing Vulkan1.0 compile contract. These structural
checks supplement the real compiler's `--spirv-val`; they do not establish shader
semantic equivalence or successful rendering. Limits are32768 modules,16MiB per
module/auxiliary file and2GiB for the complete output tree.

After generation, source/tool metadata is checked again. Every output is hashed
and fsynced, a receipt is written, the completed directory is renamed, its parent
is synced, and only then is `current` atomically replaced. Failure leaves the
previous pointer and output intact and retains staging for diagnosis. Repeating
setup with unchanged inputs verifies/reuses the completed generation without
rerunning the compiler. Setup output checks are not intended for every frame or
normal launch; a future launcher adapter must resolve the committed generation.

## Tool bundle and launch integration

The executable tool root must contain exactly seven pinned translator Python
files, `bin/glslangValidator`, and `shader-tools.json`. The helper rejects extra
Python files and bytecode caches: `-B` alone prevents writes but does not prevent
loading existing caches. Source archives, licenses, build receipts and setup
recipes are retained outside this exact executable closure.

Example guest invocation after import and tool verification:

```sh
python3 -B -s -E /work/helpers/shader_generation.py \
  --store /work/shader-store --game /work/import-store \
  --generation FULL_IMPORT_SHA256 --tools /work/shader-tools \
  --client-revision FULL_CLIENT_COMMIT --locale enUS
```

Those paths are an API example, not an enabled launcher mount contract. Android
packaging, the final mount at `/esteria-shaders`, progress/cancellation UI, and the
matching client update are still pending. The launcher must bind the selected
generation to its client/import/locale before providing
`GX_VULKAN_SHADERS=Z:\\esteria-shaders`.

## Evidence boundary

Eight host test groups cover real subprocess exit/deadline/output bounds and
storage transactions using explicitly synthetic structural SPIR-V fixtures.
The fixtures are not semantically valid shaders and are never distributed as
game assets. Actual glslang source-build qualification is recorded separately by
the Turnip build. No complete base/custom MPQ stack is available here, so no game
shader generation, Android shader setup, Adreno rendering or gameplay is claimed.
The receipt keeps all rendering/Android/gameplay qualification flags false.
