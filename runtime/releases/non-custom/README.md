# Current update transport

Version2 uses `update-2/signature-recipe.json`, `update-2/signing-receipt.json` and `update-2/publication-inputs.json`. The signer requires exact published version1 as `--previous-apk`; never use `--initial-baseline` for an update. The publisher validates the unchanged stock certificate/package, exact prior ledger and increasing version, then independently rechecks source/native SQL/provider/SDK/payload proof. Preserve the historical files below; future updates should use their own directory. Update the official signing ledger only after public signed download readback.

The following original version1 transport record remains historical.

# Detached public signing transport

The owner signs the exact verified full ARM64 release APK locally with the
existing persistent project key. Only its public APK v2/v3 signature block,
bounded zero alignment, central-directory offset change and public signing
receipt enter this directory. No private key, password or APK enters Git.

Export only after the existing signer has verified the original persistent
certificate and unchanged payload against the exact unsigned CI APK:

```sh
python3 tools/export_apk_signature.py export \
  --unsigned /absolute/path/app-release-unsigned.apk \
  --signed /absolute/path/signed/esteria-development.apk \
  --output runtime/releases/non-custom/signature-recipe.json
cp /absolute/path/signed/signing-receipt.json runtime/releases/non-custom/signing-receipt.json
```

The exporter preserves the original file prefix and central directory except
canonical SDK ZIP alignment fields and their derived header offsets (format2,
explained below). It also permits at most4095 all-zero page-alignment bytes,
the bounded public v2/v3 signing block and the canonical EOCD offset patch. Both complete APK byte lengths and SHA-256 hashes are pinned. Reapplying
the recipe must reconstruct the exact already-signed bytes; arbitrary replacement
bytes, changed payloads, nonzero padding and existing output files are refused.

The publication inputs are written only after actual build artifacts exist:

- `signature-recipe.json`: `tools/export_apk_signature.py export` output.
- `signing-receipt.json`: the unchanged `tools/sign_android_apk.py sign` receipt.
- `publication-inputs.json`: exact package/native SQL run, job, source revision,
  artifact ZIP identity and local metadata hashes.

Print the canonical required fields without inventing any identifiers:

```sh
python3 tools/publish_detached_non_custom.py schema
```

Save the complete GitHub `GET /repos/Russianranger/esteria_android/actions/artifacts/ID`
metadata for each actual unsigned-package and successful native-SQL artifact to
temporary JSON files. After the public recipe and signing receipt are present,
prepare the selection with the actual job IDs:

```sh
python3 tools/publish_detached_non_custom.py inspect \
  --package-artifact-metadata /absolute/path/package-artifact-metadata.json \
  --native-sql-artifact-metadata /absolute/path/native-artifact-metadata.json \
  --package-job-id ACTUAL_PACKAGE_JOB_ID --native-sql-job-id ACTUAL_NATIVE_SQL_JOB_ID \
  --output runtime/releases/non-custom/publication-inputs.json
```

`inspect` reads the real artifact IDs, names, ZIP lengths, SHA-256 digests and
source revisions from those metadata files. Missing local inputs are reported;
an incomplete selection cannot be written. This command prepares metadata only.
The publication job independently re-reads live runs/jobs/artifacts and verifies
every selected byte and proof before any release mutation.

Push the final public metadata on `non-custom` with the commit marker
`[publish detached non-custom]`. The isolated publication workflow requires a
successful full provider package and successful actual native stock SQL setup,
stock SQL closure, same-instance restart and clean stop. A diagnostic-only SQL
rerun at a later revision is accepted only when an exact Git comparison proves
all production runtime/profile/provider inputs remained unchanged.

The workflow reconstructs exactly the APK already signed locally, checks its
full SHA-256, verifies its persistent certificate and v2/v3 signatures using
Android SDK 35, checks the stock package/version/manifest and unchanged payload,
then stages the existing consolidated instructions. It creates a new draft
prerelease, uploads verified assets and publishes it. Existing tags/releases
and published assets are never replaced. A failed upload leaves a draft and a
public draft identity receipt for diagnosis; it is not a published candidate.

The `appRevision` and release tag target identify the original APK producer.
The later publisher revision carries public signatures, provenance and publication
code; it is not substituted as the app revision. A locally or separately run
publication stage uses the same invocation as CI:

```sh
python3 tools/publish_detached_non_custom.py stage \
  --build-tools /absolute/path/android-sdk/build-tools/35.0.0 \
  --output out/detached-publication --publish
```

This requires the repository-bound CI environment and token. Omitting `--publish`
performs all acquisition/reconstruction/verification/staging without creating a
release.

These packaging, signing and native SQL results do not qualify actual user
client data, graphical client startup, world entry, Android ARM64 or Thor.

After the new release is published and its downloaded APK hash and certificate
have been verified, record `lastPublished` in `app/stock-signing.lock.json` with
the released versionCode and signed APK SHA-256. Make that a separate metadata
commit without a publication marker. Preserve the original selection, public
signature recipe, signing receipt and their original lock hash; the producer
and publication commits retain the initial null-baseline lock used for signing.
The updated official ledger intentionally retires replay of this first-release
publisher. Its existing-release guard remains in force as well.

Later signed updates must increase versionCode (at least 2 after this release)
and supply the exact previous published stock APK to the signer. Do not use
`--initial-baseline` again. The persistent certificate and package stay the same;
the update ledger does not rewrite historical signing or build evidence.

The actual Gradle-built APK needs transport format2: apksigner adds canonical
Android ZIP alignment fields (`0xd935`, alignment4) to stored entries and adjusts
the central-directory local-header offsets. The recipe lists affected source
entry names only. The tool derives the field bytes and offsets from the exact
unsigned APK, preserves every other prefix/CD byte and all compressed payload
bytes, and then inserts the public signing block and zero page alignment. The
reconstructed complete signed SHA-256, original payload comparison and actual
SDK signature/certificate verification remain mandatory. No arbitrary ZIP
replacement bytes or private material are included in the recipe.
