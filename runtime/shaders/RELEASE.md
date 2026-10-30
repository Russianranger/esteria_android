# Durable offline shader tool inputs

The selected dependency is the exact source-backed compiler/translator/helper
provider introduced at integration `c77db0854c79f2829c0e3394b99609f5455e5bd6`.
It contains no APK, game assets, generated game shaders or private state.

The published prerelease tag is `deps-shader-tools-c77db08-7937274c8379`, targeting
that full commit. `dependency-release.lock.json` binds the original compiler
artifact, exact provider input lock and archive. The seven prepared public files
are the 10,635,594-byte archive, original input lock, provider descriptor, bundle
provenance receipt, scope/license notice, release manifest and SHA256SUMS.
The archive SHA-256 is
`7937274c8379882a045fb93c50ea9bb8575e25d5f769f7d8a3077d1518522c57`.

## Initial preservation

`preserve-shader-tools.yml` selects exact client
`926a6f73253720283ead9d7621ffd6d7d9c040cd` and compiler recipe
`8a42261db0413ce10ce9a01cd669264a5d5b90fc` checkouts. It downloads the one pinned
original Actions ZIP, verifies its length/hash and run identity, and extracts
only the bounded compiler, original sources, recipe, notices and shader fixture
receipt consumed by the packager. Every selected file is hashed during extraction.
The package is rebuilt using actual committed Git blobs and exact working-tree
bytes. The publisher independently rereads all70 regular files and the ARM64 ELF.

The original whole workflow concluded with failure in its separate driver probe
on a host without a GPU. This recorded failure is not treated as compiler success:
the independently pinned successful native GLSL/SPIR-V fixture and compiler build
receipt remain mandatory. Android execution, imported-MPQ translation and game
rendering are unqualified. The three complete original glslang, SPIRV-Tools and
SPIRV-Headers archives and their license notices are retained. Complete build-tool
and separate Wine rootfs source closure is outside this selected package.

The same preparation has been run locally against the measured267,867,656-byte
original ZIP and both exact source checkouts. It recreated the expected provider
archive and all seven release files. Exporting those validated release files back
to an Android provider produced the same archive and descriptor. This readback
is packaging evidence only. The actual publication receipt has now been
obtained, independently downloaded and recorded in the release lock.

For a local reproduction, with Python3.11+, Git and readelf:

```sh
python3 tools/release_shader_tools.py stage-original \
  --inputs /absolute/pinned-original-artifact.zip \
  --client-source /absolute/client-at-926a6f7 \
  --compiler-source /absolute/integration-at-8a42261 \
  --output /absolute/new-release-candidate
python3 tools/release_shader_tools.py verify --output /absolute/new-release-candidate
python3 tools/release_shader_tools.py body
```

The reviewed `DraftPublication` policy only uploads missing files into the exact
authorized UI-created draft. It does not create tags/releases, finalize releases,
change settings, overwrite assets or repair an already published incomplete set.
It re-downloads stored bytes before issuing an upload/publication receipt. The
draft must be a prerelease, use the exact tag and target commit above, and contain
the exact body printed by the final command. GitHub-reported immutability is
recorded separately from the publisher's write-once behavior.

## Normal clean-checkout acquisition after publication

Once the actual publication receipt is recorded, these commands need only public
release URLs pinned by size and SHA-256. They require no Actions token, temporary
signed URL, original Actions archive or second client checkout:

```sh
python3 tools/release_shader_tools.py fetch --output /absolute/new-shader-release
python3 tools/release_shader_tools.py export-provider \
  --inputs /absolute/new-shader-release --output /absolute/new-shader-provider
python3 tools/provider_shader_tools.py verify --provider /absolute/new-shader-provider
./gradlew :app:clean :app:assembleDebug \
  -PnativeRuntimeBridge=true -PnativeBridgeAbi=arm64-v8a \
  -PshaderToolsProviderDir=/absolute/new-shader-provider
```

Before the receipt is recorded, `fetch` refuses rather than selecting an unpinned
or temporary alternative. Existing output directories are always preserved.
The Docker compiler recipe and every selected original input remain in the
archive and exact source revisions as the rebuild path; a changed compiler or
helper requires a new measured provider and release identity.

## Recorded publication

[The exact prerelease](https://github.com/Russianranger/esteria_android/releases/tag/deps-shader-tools-c77db08-7937274c8379)
is public as release428717546. Workflow41014702663 at
`188b24959752fa18241b1362eb407860fc055121` rebuilt the candidate, uploaded only
missing draft files, and re-downloaded/verified all seven stored assets after
publication. The884-byte publication receipt artifact SHA-256 is
`9aef9b7f95c5a58453f17885a5bfef7052d1c52699115e16d53899bf948339cc`;
its2,382-byte JSON SHA-256 is
`6d0e8e43e5204ae1e551f73a3564617ce9322f681cab940775e1e66f51ae9a3a`.
The downloaded receipt is retained in
[the scoped evidence record](../evidence/shader-dependency-publication-41014702663.json).
GitHub reports `githubImmutable=false`; the publisher's no-overwrite policy is
true. No server, Android, imported-content or gameplay qualification changed.

All public asset lengths, hashes and fixed URLs are now recorded, so normal
`fetch` needs no original Actions artifact. A separate credential-free public
fetch/export check is added to the preservation workflow; its actual result is
pending the next run and must not be inferred from the authenticated release API
readback above.
