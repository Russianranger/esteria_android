# Separate Ubuntu ARM64 server dependency image

This build recipe prepares Linux ARM64 dependencies for the Ubuntu 24.04 server
build. It is independent of the Debian 12 Wine runtime. Docker is a **development
build tool**, not an on-device requirement. No Android execution, game-server
startup, content compatibility or gameplay is qualified by this recipe.

## Authenticated source inputs

`sources.lock.json` pins the official Ubuntu 24.04 ARM64 OCI manifest
`sha256:19cad59657037cffa0ac9a48107019b768900ff1071140965827513ac866bd5e`.
Its 28,940,126-byte rootfs layer was downloaded and SHA256-verified; the Ubuntu
archive keyring was recovered from those exact bytes. All three InRelease files
from snapshot `20261029T000000Z` passed `gpgv` verification with the Ubuntu 2018
archive signing key. Their exact sizes/hashes are pinned and checked again by
the Docker recipe after APT's authentication step.

The signed ARM64/source indexes select MySQL
`8.0.46-0ubuntu0.24.04.4`. The lock records exact archive sizes, SHA256 and
snapshot URLs for `mysql-server-core-8.0`, `mysql-client-core-8.0`,
`libmysqlclient21`, and the matching original/debian/source-control archives.
The original MySQL source archive is 492,495,969 bytes. Source metadata has
been verified; those source archives have not yet been downloaded in this
workspace. Snapshot inputs and the base OCI are reproducibly selected;
byte-identical rebuilt images are not claimed.

The official [Ubuntu snapshot service](https://snapshot.ubuntu.com/) documents
date-based archive selection and its retention policy. Long-term release
recovery must preserve the actual dependency image and corresponding-source
artifacts, rather than rely indefinitely on snapshot retention.

## Build and audit

Use a native ARM64 Linux host with Docker BuildKit, at least 10 GiB free space,
and ordinary Ubuntu archive access. The explicit CA secret supports both public
CI and the managed environment's proxy trust without baking session trust into
the runtime image. Preserve the environment's normal proxy configuration.

```sh
test "$(uname -m)" = aarch64
docker build --platform linux/arm64 --target runtime \
  --secret id=build_ca,src=/etc/ssl/certs/ca-certificates.crt \
  -t esteria-server-runtime:development runtime/server
```

The recipe uses `mysql-*-core` packages and prevents service startup during
package installation. It installs the five Boost components required by the
pinned server CMake files, Python 3 and the expected OpenSSL/readline/compression
dependencies. It does not include `authserver`, `worldserver`, SQL content,
accounts, game assets or a database. `/esteria-state`, `/esteria-content` and
`/esteria-server` are empty integration mount points.

`record_runtime.py` validates native ARM64 ELF images, runs `mysql`, `mysqld`
and Python `--version`, requires exact MySQL package/executable version strings,
and records all installed binary/source package versions in
`/etc/esteria-server-runtime.json`. It refuses an initialized `auto.cnf`.
`expectedMysqlSqlVersion` is a value to verify with a real engine, not a claim
that `SELECT VERSION()` was already run. The bootstrap test must confirm that
exact raw version, including the Ubuntu suffix.

This environment has no Docker executable/daemon available, so the recipe has
not been built locally. Unit tests cover architecture/source inventory and pin
consistency. Real native ARM64 build, database initialization/persistence and
the actual server ELF library closure remain required CI gates.

`.github/workflows/server-runtime.yml` builds this image on an ARM64 runner,
recovers measured metadata, and runs the existing fresh MySQL initialization,
atomic promotion, restart and persistence test inside the image with external
network disabled. It then builds the corresponding-source export. The authored
workflow has not yet supplied a passing run. Its artifacts are internal build
evidence/source companions; a final installable runtime archive still needs
packaging and Android qualification.

## Corresponding sources and notices

The optional source-export target downloads every installed package's exact
source version through the same authenticated, checksum-pinned snapshot. It
records every downloaded archive identity and separately rechecks the three
locked MySQL source archives. This is a substantial download.

```sh
docker build --platform linux/arm64 --target source-export \
  --secret id=build_ca,src=/etc/ssl/certs/ca-certificates.crt \
  --output type=local,dest=/private/new-server-sources runtime/server
```

Retain `SOURCE-MANIFEST.json`, `server-runtime.json`, the source lock, this exact
recipe/scripts and the project's license with the exported originals. Preserve
the image's `usr/share/doc/*/copyright` notices. MySQL uses GPL-2.0 with bundled
component notices; Ubuntu dependencies retain their individual licenses. No
source closure is claimed until the source-export target succeeds and the
release includes its original archives and recipe companion.

The final application needs a verified runtime archive/import contract, exact
server and SQL/module receipts, private persistent state and the Android PRoot
process path. This dependency-image recipe does not enable the launch button.
