# Durable reconstructed client inputs

The selected provider is client `0f931bbade36a4b197725d691b8eff7caea7b3be`,
build `41012726334.1`, paired with the seven-patch server source lock. The new
release metadata selects tag `deps-client-arm64-27446b5-0f931bba` at integration
packaging commit `27446b57e33e04d6fb11b0594d54d96b8bbd8ca6`. Its original
45,848,368-byte ZIP and 23,440,715-byte complete source companion passed actual
package reproduction, source readback, preservation and tamper checks. The
source archive SHA-256 is
`14b61f4fd5cdc6e7375297ae4a48d65240382ef2c18eed484808898373694821`.

Publication of this separate prerelease is pending; no new download URL is
claimed yet. `prepare` recovers and validates the exact original artifact and
regenerates sources from the fixed packaging checkout. Anonymous `fetch` refuses
until a verified publication receipt is recorded. The existing 69cc release and
its seven stored assets remain intact.

## Preserved initial release

The original durable release retains client 69cc, selected before the later
offline, loopback and authentication fixture changes were qualified.
The exact original 45,120,553-byte Actions ZIP is retained without repacking it.
It includes compiler diagnostics and PDB symbols as well as WowClient64.exe and
XvidDecoder.dll. A separate 23,401,759-byte source companion retains the complete
pinned client Git tree, original Xvid source, integration recipes and licenses.
The client tree includes its committed addon source/assets. No separately
imported game data or private runtime state is added. Existing component
licenses are preserved; the integration GPL license does not relicense client
code, which has no top-level license at the selected pin.

Its original input-lock bytes and historical release metadata remain in the
release, Git history and publication evidence. They identify integration provider
packaging revision `ae5534d0a9d7fb72c8e5a03dcfc65420c354e7bb`, and client source
revision `69ccfaa6a0dd01607d0a99be9b27b7b25dafc5aa` remains separately explicit.
The initial corresponding-source receipt binds the six-patch integration source lock.
Future published fetch checks the retained source lock instead of requiring
unrelated server patch records in the current checkout to remain unchanged.

The [public prerelease](https://github.com/Russianranger/esteria_android/releases/tag/deps-client-arm64-ae5534d-69ccfaa6)
is published. [Run41006572426](https://github.com/Russianranger/esteria_android/actions/runs/41006572426)
passed actual cross-repository Actions-token recovery, exact frozen-recipe source
generation, draft upload and final read-only verification of the tag and seven
complete assets. An independent host download with no GitHub token verified all
seven files and source/PE/descriptor/import/notice checks. Raw publication and
public-fetch evidence are retained under `runtime/evidence/`. GitHub reports
`immutable=false`; the publisher does not overwrite assets or move tags.
Initial source generation uses a separate clean checkout of the exact provider
packaging revision and checks every generator input hash before executing its
packager. Later server-lock edits therefore cannot change the retained source
companion. Changed inputs fail rather than silently repin.

The workflow performs read-only client artifact recovery and source validation,
then uploads only missing assets to an exact authorized UI-created draft in
`Russianranger/esteria_android`. It cannot create/move tags, finalize releases,
replace assets or change repository settings. Exact existing assets are read
back before any extension; published incomplete releases cannot be repaired.
Only the upload job has contents-write permission. Client-repository API access
has fixed GET-only Actions routes; signed download redirects receive no token.

Print the exact prerelease body, create the UI draft with the exact full target
SHA/tag in the release lock, and publish only after its complete verified-assets
receipt is available:

```sh
python3 tools/release_client_inputs.py body
```

Record the final read-only publication receipt in `dependency-release.lock.json`
only after every stored asset and actual tag have passed verification. GitHub
immutability is recorded as observed, independently of the no-overwrite policy.
After publication, clean builds use a normal pinned Git checkout plus public,
hash-verified release inputs, with no historical Actions artifact dependency:

```sh
python3 tools/fetch_sources.py client --output sources
python3 tools/release_client_inputs.py fetch \
  --client-source sources/client --output /cache/client-release
python3 tools/provider_client_runtime.py build \
  --artifact /cache/client-release/reconstructed-client-arm64-original.zip \
  --client-source sources/client --provider /cache/client-provider
```

Keep the source companion and source receipt with any redistributed binary
package. Windows ARM64 execution needs the separately qualified local Wine
runtime; this release does not establish native Android execution or gameplay.
