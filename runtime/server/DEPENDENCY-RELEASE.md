# Durable measured dependency inputs

`preserve-server-dependencies.yml` preserves the measured server dependency
rootfs and its complete corresponding sources in this repository. This is a
dependency prerelease, not an application/device candidate. It contains no APK,
WoW data, compiled Esteria auth/world server, game SQL, account or save files.

The planned tag is `deps-server-arm64-b06de55-21a9e8020aac`, pointing exactly to
the original integration commit `b06de55f5b17f27ae9659abcfdaf93a61b749a9e`.
Publication has **not** been established merely by adding this workflow.
`dependency-release.lock.json` initially has `published: null`; clean-build
downloads deliberately fail until an actual successful publication is recorded.
The original artifacts expire on 2026-11-13, so the initial preservation run must
complete before they disappear. Expired/missing originals fail closed.

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

Only the publication job has `contents: write`; it has no administration permission.
It creates or verifies the exact original-commit tag, creates an owned draft,
uploads all missing assets and reads back their actual bytes, then publishes the
prerelease. The publisher never moves a tag, deletes anything, overwrites assets,
repairs incomplete published releases, or edits another repository. An interrupted
owned draft can resume; every existing asset must already match exactly. Rerunning
against a complete matching release performs verification without mutation.

GitHub-enforced release immutability depends on repository settings. This workflow
does not change those settings. The publication receipt records GitHub's actual
`immutable` value as `githubImmutable`, separately from its own write-once policy.
If token permissions deny the exact tag/release operation, the job fails without
substituting a misleading default-branch tag or broadening permissions. Current
GitHub documentation describes additional workflow permission requirements for
some release targets containing workflow changes; the normal authorized API path
is attempted and any denial remains a concrete access blocker.

## Record successful publication without changing provider identities

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
No release or clean-build URL is claimed until the successful receipt is recorded.

References: [GitHub release API](https://docs.github.com/en/rest/releases/releases),
[release immutability](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases).
