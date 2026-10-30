# Source-verified combined ARM64 packaging

`.github/workflows/android-combined.yml` builds one internal APK containing all
four optional providers: Bionic ARM64 PRoot/loader, Ubuntu server dependencies,
ARM64 guest display/input/audio helpers, and the reconstructed Windows ARM64
client. Wine remains a separately pinned setup download. Authserver/worldserver
executables and game data are not included by these provider pins. This is a
packaging qualification, not a device-test candidate or gameplay milestone.

The job fetches the three durable integration releases without an Actions token,
including complete source companions, and fetches the exact client Git revision.
It rebuilds PRoot from hash-checked original sources and the exact NDK archive.
That same verified NDK is completed with its CMake/build files and reused for the
native JNI compilation. Java17, SDK35, build-tools35.0.0 and CMake3.22.1 match the
existing Android build. The client provider is regenerated for the current
integration source lock; an older provider's embedded server patch list cannot
silently survive a lock update. A clean app build prevents stale provider assets
when changing Gradle profiles.

The job runs core tests, compiles the app and instrumentation APK, and runs lint.
It then checks the final app's exact four native files, all provider payload
hashes, PE/ELF identities and imports, embedded source locks, helper source bytes
and helper manifest, and complete allowed asset inventory. The final NDK/LLVM/sysroot notices are
hash-compared against the exact pinned NDK archive, not just checked for presence. PRoot's corresponding
source archive accepts its producer's bounded PAX timestamps while rejecting
oversized metadata and sparse/link records; it is read back against every original
component, current tracked
recipe and build receipt, with ARM64 relocatable talloc objects retained for
relinking. Unexpected private files or links are rejected. The full server source
ZIP is checked against its package/descriptor inventory; guest and client source
closures retain their exact published scope.

The new sealer refuses existing output. It writes paired artifacts sharing one
identical receipt: the internal APK plus build evidence, and every complete source
companion plus the current integration Git archive. The receipt binds all bytes,
source revisions and validation scope. The generated debug signing key is
ephemeral: this does not qualify installation updates or replace the persistent
development-signing strategy. No private keys or application state are exported.
Build diagnostics are retained separately if any step fails. Actions artifacts
are outputs only; clean builds use durable release inputs rather than expiring
historical artifacts.

The individual providers and previous local combined build passed their existing
checks. The new workflow and final source sealer still need their first actual CI
run; focused tests exercise preservation, inventory and source-object guards with
explicitly synthetic, unexecuted objects. They do not establish Android execution,
login, world entry, gameplay, audio, character persistence or bot behavior.
