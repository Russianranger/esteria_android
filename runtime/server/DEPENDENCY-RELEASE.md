# Durable measured dependency inputs

`preserve-server-dependencies.yml` preserves the measured server dependency
rootfs and its complete corresponding sources in this repository. This is a
dependency prerelease, not an application/device candidate. It contains no APK,
WoW data, compiled Esteria auth/world server, game SQL, account or save files.

The [published dependency prerelease](https://github.com/Russianranger/esteria_android/releases/tag/deps-server-arm64-b06de55-21a9e8020aac)
uses tag `deps-server-arm64-b06de55-21a9e8020aac`, pointing exactly to the original
integration commit `b06de55f5b17f27ae9659abcfdaf93a61b749a9e`. Publication completed
on 2026-10-30 and all nine uploaded assets were independently read back by the
workflow's final read-only job. `dependency-release.lock.json` records the actual
public URLs and exact hashes; clean-build fetching no longer needs expiring
Actions artifacts. GitHub reports `immutable: false`; only the publisher's own
write-once policy and pinned byte identities are asserted.

## Validation before publication

The workflow is restricted to `Russianranger/esteria_android` on
`android/client-server`. A read-only job downloads the exact original Actions
artifacts using its `GITHUB_TOKEN` and validates:

- Successful original run `40993458111`, branch, source SHA, artifact IDs/names,
  byte counts and complete ZIP SHA-256 identities.
- All four runtime files against the unchanged measured provider lock, including
  the full archive graph, executable header identities and source/runtime metadata.
- All 278 original source files against the exact 89-package source manifest.
  Each `.dsc` source/version and archive checksum must match the inventory.
- The source companion's exact recipe, license and metadata wrapper files.
  Unexpected files, traversal, special entries, duplicates and oversized metadata
  are rejected. Original source archives remain intact inside the original ZIP.
- A nonempty retained copyright notice for every installed binary package,
  resolving contained documentation symlinks where packages share notices.

The 954,236,077-byte source ZIP is below GitHub's 2 GiB per-asset limit. Validation,
downloads, uploads and stored-asset readback are streamed. Evidence logs and private
runtime state are never selected as release files. The release contains the
112,374,096-byte runtime archive, its three metadata files, original source ZIP,
source manifest, notices, a release manifest and `SHA256SUMS`.

Only the `upload-draft` job has `contents: write`; it has no administration
permission. An authorized GitHub UI publisher first creates a prerelease draft
with this exact tag, full original commit SHA as `target_commitish`, and the exact
body returned by `release_body(lock)` in the preservation tool. The workflow
discovers that existing draft, verifies its identity and any existing tag/assets,
uploads missing assets and reads back their actual bytes. It never creates a
tag/release or finalizes the draft. It emits `draft-assets-verified.json` only
after all dependency/source assets are verified, without claiming publication.

After that receipt is available, the authorized UI publisher publishes the same
draft. A separate `verify-publication` job has read-only permissions and waits up
to 20 minutes for publication, then verifies the actual original-commit tag, exact
release identity and every asset's stored bytes before producing the durable URL
receipt. A delayed publication simply fails this bounded read-only wait; rerunning
the workflow can verify a completed release without changing it.

The workflow never moves a tag, deletes anything, overwrites assets, repairs
incomplete published releases, or edits another repository. An interrupted owned
draft can resume; every existing asset must already match exactly. Rerunning
against a complete matching release performs verification without mutation. The
older combined `publish` CLI remains available only where its normal API token
is authorized; the Actions workflow no longer invokes it.

GitHub-enforced release immutability depends on repository settings. This workflow
does not change those settings. The publication receipt records GitHub's actual
`immutable` value as `githubImmutable`, separately from its own write-once policy.
Current GitHub documentation describes additional workflow permission requirements
for some release targets containing workflow changes. The split UI/asset workflow
uses each supported authorization path for its permitted operation, without
substituting a default-branch tag or broadening token permissions.

## Record successful publication without changing provider identities

The initial publication receipt is retained at
`runtime/evidence/server-dependency-publication-41003838795.json` and copied to
the release lock's `published` member. The following procedure also applies to
future independently pinned dependency releases.

After the workflow succeeds, retrieve its `server-dependency-publication-receipt`
artifact and inspect `published-release.json`. It contains the actual release ID,
public URLs and exact hashes after stored-byte verification. Copy that complete
JSON object to the `published` member of `dependency-release.lock.json`, commit it
on `android/client-server`, and retain the receipt as project evidence.

Do **not** add transport URLs to or rewrite `android-provider.lock.json` or
`sources.lock.json`. Their exact bytes are already bound into measured provider
descriptors and packages. The separate release lock is the transport catalog.
Once its `published` record exists, reruns use durable release assets and no
longer depend on the original Actions artifact lifetime.

Then a clean checkout can prepare the same optional APK provider without Actions
authentication:

```sh
python3 tools/release_server_dependencies.py fetch --output /private/new-server-package
python3 tools/provider_server_runtime.py build \
  --package /private/new-server-package --output /private/new-server-provider
./gradlew :app:assembleDebug -PserverRuntimeProviderDir=/private/new-server-provider
```

To retain the full source companion locally too, pass `--include-sources` to
`fetch`. Downloads require a new output directory, preserve partial outputs on
failure and verify expected byte counts/hashes. Normal gameplay does not use
this build-time downloader. Distributions containing the runtime must preserve
the matching sources, original licenses and recipe; the durable source URL is
recorded beside the runtime URL in the separate release lock.

## Evidence boundaries

Focused host tests exercise source inventory/descriptor checks, malicious ZIP
paths, copyright resolution, existing-tag/asset conflict rejection, complete
release verification and interrupted-draft resume without overwrites. The actual
measured runtime and its installed-package notice graph can be verified locally.
Full original source ZIP validation and actual publication require the workflow;
the connector's 512 MiB download cap prevented local recovery of that ZIP.
No release or clean-build URL is accepted until the successful receipt is recorded.

On 2026-10-30, [run 41002275307](https://github.com/Russianranger/esteria_android/actions/runs/41002275307)
at integration `ce45a79fb3786ab0e16ea8055a2c2bd0fbb7d444` completed the read-only
validation job successfully. This included downloading the complete 954,236,077-byte
source ZIP, checking all 278 original files and 89 source-package descriptors, and
checking notices for 133 installed binary packages (128 resolved copyright files).
The validated candidate was retained as a short-lived workflow artifact. This is
actual full-source validation evidence; the source ZIP still was not downloaded
through the connector's 512 MiB-limited endpoint.

The isolated publication job 123889454241 then failed at `POST /git/refs` with
HTTP 403 while requesting the exact original `b06de55...` target. Its recorded
token permissions included `Contents: write` and `Actions: read`. No release or
asset publication was reached, and `published` remains null. The response body
was not exported, so the specific backend denial reason is not asserted.

GitHub's current release API documentation separately states that release targets
whose workflows differ from the default branch need `Workflows: write`, which
Actions' `GITHUB_TOKEN` cannot receive. This documented restriction also applies
to a current packaging commit containing those workflow changes; changing the tag
target is not a documented solution. The exact original target and measured
provider/source lock bytes remain unchanged. The split authenticated UI and
asset-upload workflow above is the subsequent implementation; its success is
not inferred from these earlier validation results. Repository permissions/settings
are not changed by this workflow.

Subsequent [run 41003838795](https://github.com/Russianranger/esteria_android/actions/runs/41003838795)
at `3ae7b69412fec80dfe35f69e89a29d5eb728a665` passed all three jobs. Authorized UI
publication finalized release `428655644` at `2026-10-30T04:39:27Z`; final read-only
job `123894755853` verified the exact original tag and all stored assets, including
the complete corresponding-source ZIP. Receipt artifact `12955150760` was a
1,009-byte ZIP with SHA-256
`883f9f8bd86d30f8e35ff1487d9ac0a9b0ec1f41f0dcaa5fc86af3db66100b62`.
Provider and runtime source-lock bytes were not changed to add transport URLs.

A subsequent clean local `fetch` with `GITHUB_TOKEN` explicitly unset downloaded
and verified all four runtime inputs from those public release URLs. The public
source ZIP's unauthenticated HEAD returned its exact 954,236,077-byte size; its
full bytes had already been verified by the final workflow job. The local fetch
receipt is `runtime/evidence/server-dependency-public-fetch-41003838795.json`.

References: [GitHub release API](https://docs.github.com/en/rest/releases/releases),
[release immutability](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases).
