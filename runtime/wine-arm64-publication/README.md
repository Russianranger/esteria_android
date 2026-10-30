# Separate durable ARM64 Wine inputs

This publisher preserves producer `681b2e9f30b19e94bf8e8de44f67fedba5033c8a`,
successful workflow `41057900330`, and runtime archive
`c0e13ed15a69fa72541684ac5cef49d71d5d95ee494146bc6e40d11b6977ab46`.
It does not select this runtime in the application or change historical `f036`
releases. Native Linux client fixtures are separate evidence; Android and gameplay
remain unqualified by this release.

The stable new tag is `deps-wine-arm64-681b2e9-c0e13ed15a69`, derived from the
producer revision and runtime archive. Its `targetCommit` remains the exact real
published packaging recipe commit, with matching recipe inputs and tag-ref checks.

The 11 assets are the six unchanged original package files, the unchanged
`wine-arm64-corresponding-sources.zip` (1,681,474,721 bytes; SHA256
`38e16617545abb16f995ba75a8b52b8ca2bacad5d2688adf3646911f16c8fb06`),
the exact `runtime-input.lock.json`, `NOTICE.txt`, `release-manifest.json`, and
`SHA256SUMS`. Original notices and full Debian runtime/build, Wine, FEX, toolchain
and integration sources remain in the ZIP. No guest rootfs is expanded or run.

Publish the recipe first. Use that full, real packaging commit in a checkout with
matching recipe files; there is no guessed target or committed placeholder lock:

```sh
python3 tools/release_wine_arm64.py lock \
  --target-commit "$PACKAGING_COMMIT" \
  --runtime-input-lock runtime/wine-arm64-qualification/runtime-input.lock.json \
  --output out/wine-release-lock.json
python3 tools/release_wine_arm64.py body --release-lock out/wine-release-lock.json
python3 tools/release_wine_arm64.py stage \
  --release-lock out/wine-release-lock.json \
  --runtime-input-lock runtime/wine-arm64-qualification/runtime-input.lock.json \
  --inputs /path/to/existing-requalification-fetch-output \
  --output out/wine-release
python3 tools/release_wine_arm64.py verify \
  --release-lock out/wine-release-lock.json --output out/wine-release
```

The existing fetch directory supplies `runtime-package/` and the original
`sources.zip`. Staging copies their bytes without repacking. It then hashes the
entire source ZIP, reads every ZIP member, and invokes the retained-source consumer
validator, including Debian descriptor closure and toolchain Git-tree readback.
Verification repeats these checks; it needs temporary disk for source extraction.
These commands do not download inputs. Focused tests use small synthetic files.

Create the exact reviewable UI draft using the generated tag, packaging commit,
prerelease setting and printed body. In an owned development-branch Actions
context, `upload-draft --release-lock ... --inputs out/wine-release --output NEW`
uses the shared upload-only publication policy. It adds only missing assets and
checks complete stored bytes. It cannot create or finalize releases, move tags,
replace assets, or change settings. After UI publication,
`verify-published --release-lock ... --inputs out/wine-release --output NEW`
produces a separate publication receipt. Preserve that receipt and the exact
release lock beside the release; adoption remains a separate reviewed step.
