# Application identity and signing

The stable package ID is `io.github.russianranger.esteria`. Imported game data,
databases, settings and logs stay under the app's private files directory. No
application update deletes or recreates this directory. Uninstalling or clearing
app storage still removes it; a database backup/export flow is required before
any migration that can affect persistent accounts and characters.

CI debug APKs exist only for compilation and emulator work. Their disposable
debug certificates are not an update strategy and must not be delivered as the
first Thor gameplay candidate.

The checked-in `app/development-signing.lock.json` pins the owner-provisioned
development certificate SHA-256
`5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa`.
On 2026-10-30 the owner provisioned the RSA-4096 `esteria` identity and retained
its private recovery backup outside the repository. Only the public DER
certificate was independently read to confirm this fingerprint. No private key
or password was imported into this repository or CI. `lastPublished` remains
`null`: no signed device baseline or delivered candidate exists. The prior
repository inspection found no established Esteria key that this replaces.
Do not adopt a debug certificate, generate a replacement key, or infer a signing
identity from a random existing APK. Retain the provisioned key and its recovery
backup outside the repository. The lock records only the public certificate
SHA-256 (lowercase, 64 hexadecimal characters) checked independently above. Never commit the key,
password files, or any exported private certificate material.

`tools/sign_android_apk.py` is the preferred local signing boundary. It uses SDK
Build Tools **35.0.0** `aapt`/`apksigner` and JDK 17. CI may produce internal debug
APKs or unsigned release APKs; internal debug APKs cannot pass the normal signing
gate. Build the same verified runtime profile with `:app:clean
:app:assembleRelease`, `-PbuildVersionCode=<positive-integer>`, the exact
`-PsourceRevision=<commit>`, and the required provider properties. With no signing
environment configured, Gradle produces `app-release-unsigned.apk`. Carry the
matched source companions and build receipt forward alongside its signing
receipt; a signature alone is not source/runtime qualification. The current
combined workflow produces an internal **debug** APK, not this release input.

Keep the external keystore and two **distinct** single-line password files owned
by the signing user with permission `0600`. Passwords are passed as `file:`
arguments, never their values in the command line or environment. The two files
may contain equal passwords; apksigner consumes successive lines if the same
file is reused, so that ambiguous arrangement is rejected. Disable shell tracing
while preparing these inputs. The tool does not create, copy, rotate, or modify
the private key and never emits SDK error text containing private paths.

With the public pin provisioned, the first signing invocation is explicit:

```sh
python3 tools/sign_android_apk.py sign \
  --build-tools "$ANDROID_SDK_ROOT/build-tools/35.0.0" \
  --apk /private/build/app-release-unsigned.apk --version-code 1 \
  --keystore /private/signing/esteria.jks --alias esteria \
  --store-password-file /private/signing/store-password \
  --key-password-file /private/signing/key-password \
  --initial-baseline --output /private/build/signed-version-1
```

The output directory must not exist. It receives `esteria-development.apk` and
`signing-receipt.json` only after verification succeeds, using atomic no-replace
publication on Linux. The source APK is retained. All application ZIP entry
bytes and ZIP compression methods must remain identical apart from old signature
records. SDK stdout/stderr are bounded while running, the owned process group is
cleaned before its leader is reaped, and errors expose only fixed reason codes. Verification
requires exactly the stable package, requested version code, minSdk 26/targetSdk
35, one pinned certificate, and valid v2/v3 signatures. Signing emits v2/v3 and
disables v4 sidecars. Debuggable APKs and the Android Debug certificate are
rejected. The tool does not implement signing-key rotation or multiple signers.

Before the first APK is delivered, record its exact public `apkSha256` and
`versionCode` under `lastPublished` in the public lock. Keep that APK. Each later
delivery updates this public baseline after review; signing never advances it
automatically. Every update requires `--previous-apk /path/to/last-delivered.apk`
instead of `--initial-baseline`, the exact recorded previous APK bytes with the
same pinned certificate, and a strictly larger `versionCode` (maximum
2,100,000,000). A previous version/name/hash is not inferred from filenames.
Never reset this ledger to bypass a downgrade or replace a lost private key.

The independent read-only check is:

```sh
python3 tools/sign_android_apk.py verify \
  --build-tools "$ANDROID_SDK_ROOT/build-tools/35.0.0" \
  --apk /private/build/signed-version-1/esteria-development.apk --version-code 1
```

The existing optional CI/Gradle signing route remains available for compatibility,
but is not a substitute for the pinned final-byte verification above. CI accepts
these
repository secrets: `ESTERIA_KEYSTORE_BASE64`, `ESTERIA_KEYSTORE_PASSWORD`,
`ESTERIA_KEY_PASSWORD`, and optionally `ESTERIA_KEY_ALIAS` (default `esteria`).
The workflow materializes the key only in the runner temporary directory, removes
it on exit, and does not print it. A missing key produces only an internal debug
build. Never silently replace a missing key with a newly generated key.

The older local Gradle route uses `ESTERIA_KEYSTORE_PATH` plus password/alias
environment variables. No CI secrets were introduced by this tooling change.

Qualification: ten focused tests pass with the real SDK 35.0.0 signer and an
already-existing disposable Gradle debug key copied into a temporary private
fixture. They compile tiny test manifests, sign versions 1 and 2, verify payload
preservation, reject a wrong fingerprint/password/package, and reject reused
version codes and debug credentials in the persistent path. No key is generated.
`--qualification-only` requires a separate test-only public lock and labels its
receipt nonpersistent; the production lock cannot enter this mode. Without
`ESTERIA_SIGNING_TEST_BUILD_TOOLS` and `ESTERIA_SIGNING_TEST_DEBUG_KEY`, the two
actual-SDK groups are explicitly skipped and eight guard groups still run.

These are host signing/identity tests. The public identity is provisioned, but no
stable-key APK, install-over test, save-preserving device update, or Thor gameplay
candidate is established by these tests. The
main candidate still needs actual installation/update and saved-data preservation
qualification with its final stable certificate before delivery.

References: Android's [apksigner documentation](https://developer.android.com/tools/apksigner)
and [version-code rules](https://developer.android.com/studio/publish/versioning),
plus the exact installed Build Tools 35.0.0 `apksigner sign --help` password-file
and debug-APK options.
