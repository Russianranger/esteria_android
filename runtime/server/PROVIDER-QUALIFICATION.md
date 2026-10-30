# Stock server provider installation profile

`server-provider-qualification.yml` is a separate Linux x64 packaging and host
installer gate. It acquires the five exact retained artifacts in
`provider-qualification.lock.json`, after a 16 GiB free-space check. It streams
and hashes the approximately 1 GiB program debug companion on CI; it does not
download the original 1.1 GiB server installation archive or compile the server
again. All selected artifact members have fixed size/SHA256 identities.

The corresponding-source input is the retained archive recovered in run
`41078079045` at `880d6a54`. Its 24,619,647 bytes and SHA256
`9f76881f06a7c998e0dba9d4a226c623021ed6ad8b87074aa7a861eafbb96d80`
match the archive originally sealed after the successful native isolated build
in run `41051669638`. The original qualification and sealing receipts remain
unchanged. Recovery repeated configuration and revision metadata generation;
it supplied no new full-build claim. See `SOURCE-RETENTION-RECOVERY.md`.

`qualify_server_providers.py build` reproduces the original notice-bearing
program archive and constructs the stock programs, four stock extractors and
source-content providers. It verifies the complete source archive, original
receipts, native loader/CLI evidence and the actual runtime/debug pairs.
`release_server_dependencies.py prepare` separately recovers the published
Ubuntu/MySQL dependency package for its existing provider builder. No database
is initialized, and no packaged native program executes in this job.

The reviewed current application source lock is checked separately from the
archived seven-patch server build lock. The full server selection and typed
compatibility profile must still match. This permits a reviewed client-only
advance without rewriting original server receipts or source identities.

The workflow uses Temurin `17.0.13+11`, the existing SHA256-pinned Android command
line tools, platform 35 and build tools 35.0.0. It checks the Gradle wrapper,
runs `:core:check`, assembles the debug application and instrumentation package,
and runs Android lint with exactly these optional providers:

| Gradle property | Provider output |
| --- | --- |
| `serverRuntimeProviderDir` | `out/dependency-provider` |
| `serverProgramsProviderDir` | `out/providers/programs` |
| `serverExtractorsProviderDir` | `out/providers/extractors` |
| `serverContentProviderDir` | `out/providers/content` |

This is a server installation profile. The workflow adds no Wine, client,
PRoot or native presentation provider selection. It does not execute Android
instrumentation or launch an Android guest.

For each of the four components, `java-manifest` binds the actual provider
descriptor and archive. `ServerArchiveInstallReference` runs the core Java
installer with `-Xmx32m`, performs a fresh installation, then proves cached reuse
with no archive input and zero copied bytes. The stores are temporary host
directories outside retained artifacts. The final `verify-apk` gate repeats
source/debug/provider verification and checks every selected APK asset byte,
including the required uncompressed `.archive` entries.

Successful provider construction retains the programs and extractor `sources/`
directories as separate curated artifacts, including the large debug companion,
complete source archive, original notices and receipts. These uploads explicitly
include hidden files. They remain outside APK assets. Successful final checks
retain the debug installation profile APK, its instrumentation APK and the four
provider asset directories separately. Bounded diagnostic tails and typed
receipts are retained even after a later gate fails. No private SQL, initialized
database, account state or signing material is collected.

Actual native server version smoke tests and stock extractor CLI checks are
earlier, separately pinned evidence. The separately adapted ordered extractors
are not selected here. This workflow proves host installation and APK byte
binding only after an actual successful run. It does not qualify custom client
data conversion, Android guest execution, server database authentication, world
entry or gameplay, and it does not activate a production package.
