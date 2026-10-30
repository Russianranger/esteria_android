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
consistency. The actual server ELF library closure and Android execution remain required
gates. Native ARM64 CI run `40989666380` at integration commit
`9ee80cd31b079e6dab8b41de2429030447665cf5` passed the real image build and
offline MySQL initialization, promotion, restart and persisted-row test. It
also completed authenticated corresponding-source export. These results
establish dependency/database behavior in a Linux container only.

`.github/workflows/server-runtime.yml` builds this image on an ARM64 runner,
recovers measured metadata, and runs the existing fresh MySQL initialization,
atomic promotion, restart and persistence test inside the image with external
network disabled. It then builds the corresponding-source export. Its artifacts are internal build evidence/source companions. The first
passing combined artifact was 948,408,822 bytes; evidence, runtime and sources
are now separate artifacts so inspection does not require the large source
download. Native ARM64 run `40993458111` at integration commit
`b06de55f5b17f27ae9659abcfdaf93a61b749a9e` subsequently passed rootfs
normalization, full archive readback, offline MySQL initialization/persistence
and corresponding-source export. Android execution remains unqualified.

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

## Portable archive

`tools/package_server_runtime.py` consumes `docker export` from a **fresh,
stopped dependency-image container**, together with its measured JSON and the
exact source lock. Never export an initialized game or database container.
The tool emits `server-runtime-arm64.tar.gz`, a receipt, and source/runtime
metadata into a new output directory. It never runs guest binaries or SQL.

The input reader bounds Docker PAX/GNU metadata, members, paths and total bytes.
The output uses only the GNU tar subset accepted by the runtime installer; it
removes uid/gid, timestamps and setuid/setgid bits. Container hostname, hosts,
resolver and machine-id files receive explicit portable/offline values. Device
nodes, logs and ephemeral-tree contents are excluded. Database, state, game
content and server mount points must be empty; MySQL credentials/history cause
a failure. Every retained package copyright notice stays in the archive.

After streaming compression, a separate full archive readback verifies the
member/link graph, exact runtime receipt, Ubuntu version and measured native
ARM64 executable hashes. Publication is atomic and refuses an existing target.
The archive receipt does not assert Android installation, PRoot execution,
server inclusion, game login or a full ELF dependency closure. Corresponding
sources travel in the separate source artifact and must accompany a release.

```sh
container=$(docker create esteria-server-runtime:development)
trap 'docker rm -f "$container" >/dev/null' EXIT
docker export "$container" > /private/server-export.tar
docker cp "$container:/etc/esteria-server-runtime.json" /private/server-runtime.json
python3 tools/package_server_runtime.py \
  --docker-export /private/server-export.tar \
  --runtime-metadata /private/server-runtime.json \
  --output /private/new-server-runtime-package
```

## Measured package checkpoint

Run `40993458111` produced `server-runtime-arm64.tar.gz`: 112,374,096 bytes,
SHA-256 `21a9e8020aac3c780114e2b3e368a643a6e830d35b6406ed99135dec9ba03ce5`.
Its 6,263 entries contain 385,051,708 regular-file bytes and 546 links. The
1,915-byte package receipt has SHA-256
`05153c6c03856071f0c0452f6075ae4b9ea2e1f1d0fbcc32f33319a9599adb9f`.
The matching runtime metadata records 133 binary packages and 89 source packages;
the corresponding-source export contains 278 files totaling 954,006,914 bytes.

An independent host download verified the Actions ZIP identity, inner archive
identity and receipt, then extracted and reread every staged regular file with
the bounded runtime reader. This validates archive transport and filesystem
content only. No host-stage executable was run and no Android server-runtime
qualification is implied. MySQL execution evidence comes from the separate
native ARM64 container test.

Artifacts for this checkpoint:

- [Small evidence](https://github.com/Russianranger/esteria_android/actions/runs/40993458111/artifacts/12949992985).
- [Dependency runtime archive](https://github.com/Russianranger/esteria_android/actions/runs/40993458111/artifacts/12949858359).
- [Corresponding source companion](https://github.com/Russianranger/esteria_android/actions/runs/40993458111/artifacts/12950466782).

Actions artifacts have a 14-day retention period. A release must retain these
exact runtime bytes and their source/recipe companion at durable URLs before an
application build pins them for setup. No release download URL or enabled Android
installation profile is established by this checkpoint.
