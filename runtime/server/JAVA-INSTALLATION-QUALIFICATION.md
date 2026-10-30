# Native Java installation and promotion gate

`.github/workflows/java-server-installation-native.yml` executes the production
Java installation coordinator on a native Linux ARM64 runner with real MySQL,
the measured compiled updater and the original source-qualified playerbots
schema helper. It does not rebuild worldserver or require game assets.

The selected original providers undergo full corresponding-source and paired
debug verification before use. The qualification installs their actual archives
using `ServerRuntimeSetup`, `ServerProgramsSetup`, `ServerContentSetup` and the
real bounded Java installer. It then runs `ServerInstallationSetup.beginFresh`,
the core SQL phase, the fourth-schema finish and `stopAndPromote`. The actual
coordinator rechecks the four-schema result, stops its real owned MySQL engine,
validates its stopped receipt and promotes with `FreshServerInstallations`.

The gate reads the active proof back through `completed`, refuses fresh
initialization over that active database, starts the promoted database again
through `ServerDatabaseService.startActive`, observes the same live SQL UUID,
compares actual account/realm/core/playerbots SQL and private journals, and
requires a second real clean stop. SQL comparison uses the shipped production
account/playerbots functions in read-only mode. Its raw rows and comparison
digests stay private. No character, inventory or in-world bot is created.

The qualification compiles the real production `ProotProcess`, `ProotLaunch`,
`NativeProcessBridge`, `OwnedProcess`, native JNI and owner implementations. It
substitutes only file-backed `Context`/asset facades and a qualification-only
`InstalledProot` locator. That locator accepts the same source-pinned PRoot and
talloc implementation built for glibc by `qualify_proot_ownership.py`. Before
every launch it verifies the complete original source-component hashes, the
exact exit-kill adaptation hash, actual baseline/positive detached-child
ownership results, canonical tracer/loader paths, ARM64 ELF headers and streamed
payload hashes. There is no arbitrary PID control or simulated process backend.
The Android APK payload locator, Bionic execution and Android API behavior are
outside this Linux gate; they retain separate evidence requirements.

The JVM uses the real JSON-java20240303 source at
`f9b5587c87aaf02e4a5ed1991d48d6c05993624a` from its original repository. The
build receipt records every compiled production/qualification source, that
dependency's source/license identities, every class output and the actual JNI
library. These test-only sources never enter the application APK. The workflow
uses the same fixed JDK17 build as existing Android CI.

An empty `unavailable-game-data/data` directory is an explicit configuration
namespace for SQL-only setup. It supplies no synthetic map, DBC, camera or shader
input, and no worldserver starts. `serverDataQualified`, Android, auth/world,
character saving, bot AI and gameplay flags stay false even after this gate
passes. Compilation and the metadata guard tests alone establish none of its
actual SQL/promotion/restart claims.

The workflow performs acquisitions and builds first, then runs the test in the
verified compiler-free dependency image with external networking disabled,
read-only container root and a separate private MySQL state mount. Linux ptrace
is explicitly available for the real tracer. Only typed public receipts and
pre-SQL build/acquisition tails are uploaded. Account files, credentials,
databases, prefixes and executed SQL/process logs remain private.

To build locally, use a clean exact JSON-java checkout and an installed JDK17:

```sh
python3 tools/qualify_java_server_installation.py build \
  --json-source /absolute/pinned-json-java --java-home /absolute/jdk17 \
  --output /absolute/new-harness-build
python3 -m unittest tests.test_java_server_installation_qualification -v
```

The `prepare` subcommand requires verified dependency, helper-augmented programs
and content providers. The `run` subcommand refuses non-ARM64 execution and
requires an actual native PRoot ownership build, fresh private paths and the
recorded class/JNI closure. The workflow contains the complete mount and run
commands. The three bounded host input/receipt groups and actual JDK17/glibc JNI
compilation pass; the x64 JVM refuses native qualification before creating
private storage.

Actual native ARM64 run41109643068 at application
`4fd32df287961b9cc5175213a6fe85eac1c6d868` passes the full Java SQL/promotion/
restart gate: real core and fourth-schema initialization, completed proof
readback, refusal to reinitialize the active save, the same live SQL UUID after
restart, unchanged actual account/realm/core/playerbots rows and private
journals/credentials, and two clean database stops. The original bot schema has
30tables and31updates. Its19-member evidence artifact is45,297bytes, SHA256
`134efe85d03727937da320b8a43fcac529f2854bc49321f3a9068e0ab3f3453c`.
Independent readback verifies every member and all55 recorded project source
inputs, including both native headers, against that exact Git revision. The
native runner also verifies all170 compiled classes before execution. See
`runtime/evidence/native-java-installation-41109643068.json`.

The actual job log completes evidence upload and cleanup, while Actions run/job
metadata still reports `in_progress` with an older update time. The proof records
this discrepancy and leaves workflow completion unconfirmed. The positive
retained execution result does not qualify the Android/Bionic locator, Android
SQL, authserver/worldserver, game data, character saving, bot AI or gameplay.
