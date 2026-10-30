# Durable reconstructed client inputs

The selected provider is now client
`471ee42faadf4a97a1d0a86989cf1452621f2dc5`, build `41061576677.1`.
Its new release input lock selects `deps-client-arm64-33cf433-471ee42f` with
frozen recipe `33cf433a907a9181d27a6962b1f07516afc0773d` and two explicitly
hash-bound current input locks. The unchanged original 45,848,847-byte CI ZIP is
paired with a 23,449,963-byte complete source archive, SHA-256
`71f7bc4c3b1574de365418bffa2a8c74b299cf0635f45e292b30df20005259cd`.
The source receipt is 3,838 bytes, SHA-256
`e768b9dfec4cae999d6c4ca2b8d85a6ed998264b6f4779a57670e91f8533d615`.
All seven release files are prepared and read back locally; public publication
has not been verified. This is input preservation, not Android or gameplay
qualification. The app source lock advances the client only; archived server
build, SQL and source receipts retain their original identities.

## Preserved 0f release

The prior provider is client `0f931bbade36a4b197725d691b8eff7caea7b3be`,
build `41012726334.1`, paired with the seven-patch server source lock. The new
release metadata selects tag `deps-client-arm64-27446b5-0f931bba` at integration
packaging commit `27446b57e33e04d6fb11b0594d54d96b8bbd8ca6`. Its original
45,848,368-byte ZIP and 23,440,715-byte complete source companion passed actual
package reproduction, source readback, preservation and tamper checks. The
source archive SHA-256 is
`14b61f4fd5cdc6e7375297ae4a48d65240382ef2c18eed484808898373694821`.

The [separate prerelease](https://github.com/Russianranger/esteria_android/releases/tag/deps-client-arm64-27446b5-0f931bba)
is published. [Run41018243725](https://github.com/Russianranger/esteria_android/actions/runs/41018243725)
passed exact original-artifact recovery, source generation from the fixed packaging
checkout, draft upload and final read-only verification of the actual tag and all
seven complete asset bytes. Its downloaded publication receipt was hash-verified;
an independent anonymous fetch then repeated every asset, source, PE, descriptor
and notice check. Durable URLs are recorded in `dependency-release.lock.json`,
with publication/public-fetch evidence under `runtime/evidence/`. GitHub reports
`immutable=false`; publisher overwrite protection remains explicit. The existing
69cc release and its seven stored assets remain intact.

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

## Selecting new measured inputs with a frozen recipe

A new release can pin a committed packaging recipe before adopting a new client.
Its optional `selectedInputs` contains exactly the raw `sources.lock.json` and
`runtime/client/android-provider.lock.json` identities. Its `generationInputs`
then pins the ten unchanged helper/runtime/license recipe inputs at
`targetCommit`. The selected source and measured client locks must travel
together, match the exact revision/build/protocol contract, and be retained under
their normal `integration-recipe/` names in the source companion. The receipt
binds both raw input hashes; subsequent release checks revalidate those bytes.

`package_client_sources.py --source-lock <exact-app-lock> --client-input-lock
<exact-measured-client-lock>` selects those paired inputs explicitly. Omitting
both arguments retains the default behavior and receipt shape. Existing release
locks without `selectedInputs` continue using every original frozen generation
input, including their original source/client locks. No historical receipt,
published asset or server build source identity is relabeled.
