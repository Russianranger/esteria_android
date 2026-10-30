# Complete local server component preservation

This separate dependency prerelease preserves the source-qualified local
server profiles without relying permanently on expiring Actions artifacts.
The stock server providers and their existing locks remain unchanged.

The fixed release has12 assets:

| Asset | Preserved contents |
| --- | --- |
| `server-programs-playerbots-provider.tar.gz` | Complete optional helper provider, including its original stock provider, three original programs, original complete sources/paired debug, the original SQL-qualified b7 helper, its source companion, receipts and notices. |
| `server-data-tools-provider.tar.gz` | Four composed tools, exact configuration, complete ordered source companion, native CLI/lookup and strip receipts, ordered and original stock debug. |
| `server-extractors-original-provider.tar.gz` | Unchanged original four-tool provider, complete corresponding sources and original paired debug. |
| `server-content-provider.tar.gz` | Unchanged source-derived SQL/module/runtime content provider. No imported client assets or initialized database. |
| `providers-receipt.json` | Exact inventories and SHA256 identities for every file in those four bundles. |
| `integration-recipe.tar.gz` | Every regular tracked file at the exact packaging commit, including source locks, adaptations, provider scripts, tests, documentation and license. |
| `integration-recipe-receipt.json` | Full recipe inventory, archive identity and exact commit. |
| `server-dependency-release.lock.json` | Exact separate Ubuntu ARM64/MySQL runtime and complete source release selection. |
| `server-dependency-publication.json` | Its retained actual public release receipt; GitHub immutability remains reported as observed. |
| `NOTICE.txt` | Component preservation and qualification boundaries. |
| `release-manifest.json` | Complete payload identities, exact recipe and selected source inputs. |
| `SHA256SUMS` | Payload and manifest checksums. |

Bundle files use GNU tar in stored gzip with normalized ownership/time/modes.
Every original nested runtime, debug and source archive stays byte-identical.
Each bundle's expanded payload is capped at1900MiB; every individual release
asset must remain below2GiB. Sources/debug remain outside APK assets. Full
original provider verification runs before staging, after archive extraction,
before upload and during public consumption. No compiler or packaged code runs.

## Two-phase publication

First publish the preservation recipe and pending lock on the authorized
development branch. `preserve-local-server-components.yml` then checks out that
exact commit, acquires the retained measured inputs, invokes the original full
source/debug admission guards and creates one completely read-back candidate.
Its bounded measurement artifact contains `measured-release.lock.json`, all12
asset identities and the exact `release-body.txt`; no UI draft is needed for
this first phase. A failed measurement cannot enable upload.

Create an owned UI draft only after that concrete candidate passes. Use the
measured tag, exact target commit, prerelease setting and body. Record its
actual numeric ID in `ownedDraftReleaseId`, change state to `owned-draft-bound`
and preserve all measured identities and recipe inputs unchanged. Commit that
explicit lock. The workflow reproduces the candidate in a separate checkout of
the original packaging recipe and uploads only missing exact assets to that
specific draft ID. A matching tag/body with another release ID is refused.

The uploader never creates or finalizes a release, moves a tag, replaces an
asset, changes release metadata or changes repository settings. It fully reads
back every stored asset before issuing draft readiness. After the authorized
UI publication, the read-only job verifies the exact tag/ID/body, reads back all
stored bytes and then independently downloads every public asset anonymously,
again verifying the complete source/debug closure. Preserve the resulting
publication and public-readback receipts before changing application consumers.

## Reproduction and public consumption

The initial authenticated preservation job needs Python3.10+, Git and at least
20GiB free scratch storage. It does not compile the server or need Android SDK,
Docker, game data, credentials or a seeded database.

```sh
python3 tools/release_local_server_components.py prepare --output out/preservation-inputs
python3 tools/release_local_server_components.py stage --inputs out/preservation-inputs \
  --target <exact-published-recipe-commit> --output out/release-candidate
```

The measured release lock is external to the frozen recipe to avoid a hash
cycle. After publication, check out the exact recipe commit and supply the
later owned release lock explicitly. Public consumption requests no Actions
artifact and requires no token:

```sh
env -u GITHUB_TOKEN python3 tools/release_local_server_components.py fetch-published \
  --release-lock /absolute/owned-release.lock.json --output out/public-release
python3 tools/release_local_server_components.py consume --inputs out/public-release \
  --release-lock /absolute/owned-release.lock.json --output out/server-providers
```

The restored directories are `programs`, `data-tools`, `extractors` and
`content`. The integrated local-game APK selects the optional helper `programs`
and composed `data-tools`; the original `extractors` directory remains an
archived comparison/provider input. The separate Ubuntu dependency release is
still required and is already pinned durably with its complete source ZIP.

Passing preservation qualifies stored bytes, corresponding sources, debug,
notices and provider packaging. It does not qualify Android runtime execution,
normal client login, world entry, bot AI or gameplay. No user client files,
accounts, private credentials, initialized databases/prefixes, saves or signing
keys belong in this release. No APK from this job is a Thor test candidate.
