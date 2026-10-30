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

## Java database-service lifecycle gate

The qualifier additionally invokes
`actualJavaServiceAdapterOwnsReadinessShutdownAndRestart` as a separate mandatory
instrumentation test. It owns another fresh runtime and the canonical private
`state/server-work` directory, refusing an existing directory. Exact source-bound
setup and service helpers are verified before execution. The existing bootstrap
and socket-only marker fixture initialize this new instance; no game schemas or
player state are adopted.

The real `ServerDatabaseService` Java lifecycle runs twice against that instance.
Each cycle requires authenticated readiness from the unchanged `mysql_service.py`,
the same instance UUID, a live native owner, rejection of a duplicate Java lease
without launching another process, and acknowledged command shutdown with an
unforced zero exit. A separate socket-only guest then restarts the database and
reads the original marker. Bootstrap receipt, both credentials and private marker
identity must remain unchanged, and the Java lease must be independently acquirable
after each stop.

A package-private `InstalledRuntime` seam supplies only this test's independently
verified x64 runtime and tracer. The public application entry point still constructs
the production `ServerRuntimeSetup`/`ProotProcess` implementation, with all ARM64
provider checks intact. Both paths use the same PRoot argument builder, actual JNI
process owner, interactive shutdown pipe, helper installer and readiness reader.
There is no launcher activation or alternate production provider configuration.

The persistent Python helper uses an exclusively created private `s-XXXXXXXX`
directory directly under `/work` for its UNIX socket. The Java adapter checks the
translated physical path bound before starting. Long operation UUIDs remain in
receipts and PID files; only empty directories still matching their original inode
are removed, and crash leftovers are preserved rather than reused.

The new receipt has scope `android-13-x86_64-java-mysql-service-lifecycle`.
`androidJavaDatabaseServiceLifecycleQualified` requires both actual instrumentation
success and exact receipt/input validation. ARM64, full production runtime,
application schema updates, worldserver and gameplay remain explicitly unqualified.
The Java/test source compiles and lint passes; actual execution of this new gate
is pending. The measured bootstrap result below predates this additional gate.

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
