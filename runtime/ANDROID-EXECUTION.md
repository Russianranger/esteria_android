# Android execution policy and current gate

The app keeps **targetSdk 35** and targets Android 13 on Thor. Checked reference
sources also use 35: UO `app/build.gradle:10` and FTA
`android/app/build.gradle.kts:25`. A targetSdk 28 downgrade is not part of this
implementation, and no Android security policy is disabled.

## What actually executes

1. The app loads `libesteria_process.so` as a JNI library packaged in the APK.
2. That owner executes the hash-verified `libproot.so` from
   `ApplicationInfo.nativeLibraryDir`, where Android's package installer placed
   it. The loader is also installed there as `libproot-loader.so`.
3. The exact pinned PRoot source handles guest `execve` in
   `src/execve/enter.c:595`. It reads the ELF/interpreter metadata, chooses the
   path from `PROOT_LOADER` (`get_loader_path`, around line 562), and replaces the
   kernel exec path with that installed loader (`translate_execve_enter`, around
   line 709). The native AA64 path has no QEMU/foreign-binary runner.
4. `src/execve/exit.c:144` transfers the segment-loading program. The loader's
   `src/loader/loader.c:127` opens guest ELF/interpreter files read-only and maps
   their segments privately with the ELF protections, including executable
   segments, then enters the guest. Later Linux dynamic-library loading still
   needs real guest glibc/Android-policy qualification.

These line references refer to the source built by
`tools/build_android_proot.py`, locked by `runtime/proot/sources.lock.json`,
including its existing Android compatibility patches. They are not claims about
an arbitrary system PRoot. `InstalledProot.inspect` checks the packaged bytes
before process creation; the runtime installer verifies required guest binary
hashes and architectures before returning a generation.

## Policy evidence and limits

[Android's API29 behavior documentation](https://developer.android.com/about/versions/10/behavior-changes-10#execute-permission)
prohibits direct `execve` of files in an application's writable home directory.
It also distinguishes read-only executable mappings from modifying executable
file content through writable mappings. It recommends shipping executable code
inside the APK. Our kernel-executed tracer/loader and JNI bridges follow the
APK installation path; the large imported Linux runtime remains separate.

The exact AOSP Android 13 release policy makes the relevant distinction:

- [app_neverallows.te, android-13.0.0_r1](https://android.googlesource.com/platform/system/sepolicy/+/refs/tags/android-13.0.0_r1/private/app_neverallows.te)
  denies app-data `execute_no_trans` to current-target untrusted app domains.
  Older target compatibility exceptions do not apply here. Decoded source
  SHA-256: `38ede4cf649152ee826a80d8f1d1119930713540511b9b450907b2f7fb8d1717`.
- [untrusted_app_all.te, android-13.0.0_r1](https://android.googlesource.com/platform/system/sepolicy/+/refs/tags/android-13.0.0_r1/private/untrusted_app_all.te)
  separately permits app-data read/map/execute access, which is relevant to
  loading executable segments. Decoded source SHA-256:
  `a010d4aecb6df055c90e61f39684c4f99a69f637d80e68a55d1ea1cb53e06d7e`.

Inference: the installed-loader path is consistent with these distinct AOSP
permissions at target35; direct execution of the private guest ELF is not.
This is source/policy evidence, **not an Android execution pass**. Vendor SELinux
policy, Android seccomp, ptrace availability, loader mappings, memfd, Linux
dynamic loading and Wine's behavior must all be observed on the actual Android
runtime. `PROOT_NO_SECCOMP=1` disables only PRoot's optional acceleration filter;
it does not change Android's inherited syscall restrictions.

## Qualification required before launch integration

The existing Android13 x86_64 emulator installer/update test covers private
filesystem behavior, integrity and application data retention. It does not
execute this ARM64 PRoot or the ARM64 guest. Linux owner/JNI tests and successful
NDK compilation likewise cannot qualify Android execution policy.

Next, an Android ARM64 execution test must install the APK-owned native payloads,
load the JNI owner, run a pinned benign guest executable and a guest dynamic
library, verify exact output/exit, and exercise tracer/owner death. Capture app
targetSdk, Android build fingerprint, ABI, payload/runtime hashes, bounded logs,
exit status and any available denial diagnostics. Then qualify Wine prefix,
display, audio, input and service readiness separately. Keep gameplay gated
until these pass; preserve normal platform denials as failures.

If an Android build rejects a required mapping/syscall, inspect its actual
failure and choose a supported packaging/backend adaptation. Do not infer a
device-only failure from the current host's separate ptrace restriction, weaken
SELinux, silently lower targetSdk, or request a preliminary Thor installation
while independent implementation and emulator work remain useful.
