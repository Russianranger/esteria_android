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

The first actual hosted run [41009954235](https://github.com/Russianranger/esteria_android/actions/runs/41009954235)
at `46a54a223720cdc230074aa6a43f10370718af71` passed all phases, including anonymous
durable-input acquisition, PRoot source rebuild, core tests, native ARM64 app and
instrumentation compilation, lint, and final source/byte sealing. The generated
APK is 120,881,379 bytes, SHA-256
`29502f16e300a5072a32420cd4e03855670068eab821d4b1199ba8074edb0da2`.
Its matched source artifact is 980,099,765 bytes. The small binary artifact was
downloaded, checked against the service digest, and the APK/native/provider bytes
independently read back. The full source artifact was validated by the CI sealer;
its outer ZIP was not downloaded locally because it exceeds the connector limit.
Exact artifact IDs, hashes and the source-bound receipt are retained in
`runtime/evidence/combined-android-build-41009954235.json`.

This run uses client `69ccfaa6a0dd01607d0a99be9b27b7b25dafc5aa`, pinned server
`f35f04d01689f034778e3474b3c820092f51e461` and six reviewed server patches.
It compiles the combined app but does not run it on Android. Focused guards also
exercise preservation and source-object validation using explicitly synthetic,
unexecuted objects. Neither result establishes login, world entry, gameplay,
audio, character persistence, bot behavior, or persistent-key installation.
