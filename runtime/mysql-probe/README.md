# Android13 x86_64 MySQL execution fixture

This is a separate, explicit debug qualification profile. It uses Ubuntu24.04
x86_64, Python3 and the same MySQL `8.0.46-0ubuntu0.24.04.4` source version as the
production ARM64 dependency package. It does not relax the production provider's
architecture, source, archive or executable checks. `ServerDatabaseSetup` remains
unavailable from launcher actions until its production runtime is qualified.

## Reproducible inputs

The OCI amd64 manifest comes from the same pinned Ubuntu24.04 multiarch index as
the ARM64 package. `sources.lock.json` retains its manifest/config/layer descriptors
and the exact20261029 snapshot. APT verifies the pinned archive keyring and the
three hash-pinned signed InRelease files. The three MySQL amd64 package hashes
were resolved from the binary-amd64 index covered by that InRelease. The recipe
checks package hashes before installation and records actual executable hashes,
ELF machine62, package/source inventories and measured version outputs.

`Dockerfile` builds only dependencies. It never initializes a database. Its
specific `.dockerignore` excludes unrelated project outputs from the build
context. The separate source-export target reuses the existing APT source
collector, downloading exact source versions for **every installed package** and
checking the original MySQL source archive pins. This source companion, project
recipes/tests and PRoot corresponding-source companion must remain available
with any distributed fixture; source URLs alone are not a retained source bundle.
CI uploads them separately even if the emulator test fails after image creation.
Actions artifacts expire and are not a durable release strategy.

Example native x64 host commands, from the repository root:

```sh
docker build --platform linux/amd64 --target runtime -f runtime/mysql-probe/Dockerfile \
  --secret id=build_ca,src=/etc/ssl/certs/ca-certificates.crt -t esteria-mysql-probe:qualification .
# Export a fresh container; never export a database-test container.
container=$(docker create esteria-mysql-probe:qualification)
docker cp "$container:/etc/esteria-mysql-probe.json" runtime.json
docker export "$container" > mysql-export.tar
docker rm "$container"
python3 tools/build_android_mysql_probe.py --docker-export mysql-export.tar \
  --runtime-metadata runtime.json --output mysql-provider
```

Build the existing source-pinned x64 PRoot probe provider separately. Then set
`-PnativeRuntimeBridge=true -PnativeBridgeAbi=x86_64`,
`-PprootProbeProviderDir=<that-provider>` and
`-PmysqlProbeProviderDir=<mysql-provider>` for an APK build. This combination
rejects all production providers and presentation-test mode, disables release
variants, and defines `MYSQL_PROBE_PACKAGED=true`. Ordinary builds define it false
and contain no MySQL probe provider.

The provider uses the existing streaming rootfs normalizer and independently
reads back the complete archive/link graph. It rejects database state, credentials,
unsafe links, special files and architecture mismatches. The real Java
`RuntimeInstaller` installs its own `mysql-probe-x86-64` generation with bounded
buffers and reserves space for copied hardlinks where Android denies hardlinks.
The `.archive` APK asset must be stored without ZIP compression. The composite
APK verifier has a512MiB ceiling and checks all native/PRoot/helper bytes; the
ordinary PRoot probe APK's64MiB ceiling is unchanged.

## Actual execution contract

The emulator qualifier refuses physical devices, non-Android13/x64 environments
and a preexisting application installation. The app test requires targetSDK35,
a debug build and the explicit fixture flag. It creates fresh private work and
session directories. No production saves, imports or databases are adopted.

Four separately owned PRoot guest processes execute:

1. The **unchanged** bundled `android_database_setup.py` CLI and
   `mysql_bootstrap.py` initialize the datadir and stop their temporary MySQL.
   Their result must explicitly make no live-readiness claim.
2. `guest_check.py` checks the fixture owner and exact bootstrap UUID/version,
   starts only that MySQL datadir with TCP/MySQLX disabled, authenticates root and
   the application account, confirms all four empty application schemas, writes
   one owned InnoDB marker row and stops cleanly.
3. The original bootstrap CLI runs again and must return `already-initialized`
   for the same instance, without reseeding or claiming a live service.
4. A fresh guest invocation then restarts the same datadir, authenticates again,
   checks the same UUID and credential identities, reads the exact marker row,
   and stops cleanly. Any unrelated table or changed credential fails. Performing
   this verification after the repeated bootstrap establishes that the repeat
   preserved actual SQL contents and credentials, rather than only its receipt.

Every process uses the real native owner and pinned x64 Bionic PRoot/loader.
Initialization/restart timeouts preserve private state and are failures; force
termination never establishes a pass. The global test has a bounded deadline.
Only bounded process logs, Java-redacted engine logs, hashes/version receipts
and emulator properties are exported. Credentials, SQL dumps, private configs,
marker contents and datadir files are never exported.

`androidMysqlBootstrapQualified` is set only after the instrumentation success,
exact source/provider/native receipt checks and owned test-app shutdown succeed.
Production adapter, ARM64, game schema, worldserver and gameplay flags stay false.
Even a successful x64 emulator result cannot establish that the ARM64 binaries
or the production `ServerDatabaseSetup`/`ProotProcess` adapter execute correctly.

## Current evidence

Native CI run [41010011663](https://github.com/Russianranger/esteria_android/actions/runs/41010011663)
completed successfully at `43ccce4fe5ef8f5df79397e849c1aabf498f7cd5`.
Android13/API33 x86_64 executed all four launches with MySQL
`8.0.46-0ubuntu0.24.04.4`: fresh initialization, root/application SQL
authentication, socket-only service, exact instance identity, marker/credential
preservation after repeated bootstrap and restart, and clean owned shutdown.
The production installer installed the exact fixture runtime and all bootstrap
helper hashes matched. This qualifies the stated x64 emulator bootstrap scope;
production adapter, ARM64, game schemas, worldserver and gameplay remain false.

The independently downloaded early evidence ZIP is46,799 bytes, SHA-256
`5d6c206cc145aa30203bdeec2cfd236016597378097926c71882e1a6e7552772`.
Its qualification receipt SHA-256 is
`c105a95c93966e393a7a94601b4f90134adbd994c28ec46f178e2c807b55f471`.
[The recorded evidence](../evidence/android-mysql-43ccce4.json) retains the exact
receipt, APK/provider/native hashes and separately identified final/source
artifact transport metadata. The latter two artifacts have not been downloaded
for independent readback. Three engine-log inventories were omitted because
Toybox `ls` emitted multiple columns; the qualifier now requests `ls -1`.
The actual execution receipt is complete; diagnostic log coverage is limited.

The preceding real Android failure was `errno=38` in Python `os.replace` while
writing the initial initialization journal. The reviewed, separately pinned x64
PRoot legacy-rename-to-renameat adaptation resolved it without changing the
bootstrap helper or adding a destructive recovery path. Native ARM64 PRoot and
the production provider were unchanged. Host archive/provenance guard tests
remain useful but are separate from this measured emulator result.
