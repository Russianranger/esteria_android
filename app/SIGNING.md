# Application identity and signing

The stable package ID is `io.github.russianranger.esteria`. Imported game data,
databases, settings and logs stay under the app's private files directory. No
application update deletes or recreates this directory. Uninstalling or clearing
app storage still removes it; a database backup/export flow is required before
any migration that can affect persistent accounts and characters.

CI debug APKs exist only for compilation and emulator work. Their disposable
debug certificates are not an update strategy and must not be delivered as the
first Thor gameplay candidate.

Provision one persistent development signing key before delivering that candidate.
Store it outside source control with a recoverable owner backup. CI accepts these
repository secrets: `ESTERIA_KEYSTORE_BASE64`, `ESTERIA_KEYSTORE_PASSWORD`,
`ESTERIA_KEY_PASSWORD`, and optionally `ESTERIA_KEY_ALIAS` (default `esteria`).
The workflow materializes the key only in the runner temporary directory, removes
it on exit, and does not print it. A missing key produces only an internal debug
build. Never silently replace a missing key with a newly generated key.

Local release signing uses the equivalent `ESTERIA_KEYSTORE_PATH` environment
variable plus passwords and alias. Run `./gradlew :app:assembleRelease`.
Increment versionCode for each deliverable update. Before delivering an update,
compare `apksigner verify --print-certs` certificate SHA-256 and application ID
against the previously delivered APK, then test install-over and saved-data
preservation. No signed APK has yet been established as the device baseline.
