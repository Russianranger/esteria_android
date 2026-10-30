# Explicit private PE image copy

This source adaptation is restricted to the separate Wine qualification build.
`WINE_ANDROID_PRIVATE_PE_COPY=1` selects it; an unset variable or any other value
keeps the original Wine mapping path. It changes neither Android policy nor the
application target SDK. The production ARM64 Wine provider remains unchanged.

## Measured failure and source explanation

Android13 x64 run41017052972 measured `EACCES` (13) only when a modified private
file mapping changed from RW to RX. Anonymous modified RW to RX, direct file RX,
direct file RWX and unmodified private file RW to RX succeeded. The matrix did
not execute mapped bytes. Wine then repeated its `ntdll.dll` executable-section
protection failure. Exact observations are retained in
`../evidence/android-wine-mappings-41017052972.json`.
The downloaded evidence artifact is 12960078291, 69,032 bytes, SHA-256
`93d248b066a28773d8eb860f0e30f4fd4093e64733f31d7792b90e2611cf07be`.

Primary source inspection supports the distinction:

- AOSP `system/sepolicy` commit
  `6f6029407a5e7059e2ae2ac2e6cfd0c9b4e00509` grants app `execmem` in
  [private/app.te](https://android.googlesource.com/platform/system/sepolicy/+/6f6029407a5e7059e2ae2ac2e6cfd0c9b4e00509/private/app.te),
  and file `execute` in
  [private/untrusted_app_all.te](https://android.googlesource.com/platform/system/sepolicy/+/6f6029407a5e7059e2ae2ac2e6cfd0c9b4e00509/private/untrusted_app_all.te).
  [public/domain.te](https://android.googlesource.com/platform/system/sepolicy/+/6f6029407a5e7059e2ae2ac2e6cfd0c9b4e00509/public/domain.te)
  forbids `execmod` except for the two older application domains.
- The official Android13 5.15 kernel
  [SELinux hook](https://github.com/aosp-mirror/kernel_common/blob/android13-5.15/security/selinux/hooks.c),
  inspected Git blob `087d2d970964838ee68c688b0e01ee573393767b`, requests
  `FILE__EXECMOD` when execute permission is added after a file-private mapping
  has undergone copy-on-write. Anonymous executable mappings instead use
  `PROCESS__EXECMEM`. This is source corroboration, not an assertion that the
  emulator's entire running kernel/policy binary was independently reproduced.
- The exact Wine source is `a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29`.
  `dlls/ntdll/unix/virtual.c` is 244,516 bytes, SHA-256
  `79dba34fbafbac07719e974b4210c9a3a2f6ed515915c469374783dad9085aab`.
  Its ordinary PE sections initially use private file mappings, can be modified
  by zero-filling or relocation, then acquire execute permission. The exact
  original archive and Git blob were both checked against these bytes.

## Adaptation contract

The opted-in path copies the header and private sections into Wine's existing
anonymous image reservation before any file-backed image mapping. Reads use
bounded 1 MiB calls, retry interruption and partial progress, and reject errors
or EOF before the captured file length. Only legitimate sector/page padding is
zero-filled. Non-flat images reject overlapping or misaligned virtual sections,
out-of-image extents and more than 256 sections before shared mappings are made.
This prevents a later private copy from modifying an earlier shared mapping.

Shared writable sections and their import-subrange mapping retain the original
Wine code. Their unusual executable variants may still fail the platform's
permissions and are not declared supported. Final protection failures fail the
opted-in load instead of continuing with inaccessible code. Existing instruction
cache support is used after copied executable contents are prepared.

One fixed `ESTERIA_PRIVATE_PE_COPY mapped` line is emitted per process after a
successful opted-in image load, under the existing virtual-memory mutex. It
contains no paths or user data. The reference fixture requires this marker in
the selected mode and its absence in the default mode, alongside actual DLL
execution, forced relocation, protection changes, zero-fill, private data
isolation and writable shared-section communication. The marker alone cannot
qualify execution.

Anonymous copies may increase resident memory and reduce file-page sharing.
Actual combined memory, rendering, thermal behavior and ARM64 instruction-cache
behavior remain separate measurements.

## Evidence and next gate

Six host groups execute the actual added C helper functions and check clean
application of the patch against the exact upstream file:

```sh
ESTERIA_WINE_VIRTUAL_SOURCE=/absolute/path/to/wine/dlls/ntdll/unix/virtual.c \
  python3 -m unittest tests.test_wine_private_pe_copy -v
```

The checked-read fault, shrinking-file, interruption, bounded real anonymous-copy,
zero-tail, overlap/alignment and original-input preservation tests pass. A
separate read-only scan of703 actual Wine/client x64 PE headers found no conflicts
with the new non-flat bounds. These checks do not execute the adapted Wine.

The full source build and actual default-versus-selected PE reference passed in
run41040860418 at `824ca6df8ff158e4e38c9a7e9adc67405876f19b`, followed by fresh
runtime archive readback and complete source export. Independent host receipt
readback verified both executed modes, zero/two branch markers, all image/shared
checks and clean teardown. The exact new runtime is now selected only for the
separate x64 Android fixture. Its complete source ZIP must pass the existing
Android CI consumer before APK construction or execution; full local source-ZIP
readback was unavailable at the connector's download limit. See
[`../evidence/wine-private-pe-host-41040860418.json`](../evidence/wine-private-pe-host-41040860418.json).

A fresh Android prefix and reconstructed-client diagnostics remain pending.
Production ARM64, normal game initialization, hardware graphics and gameplay
remain unqualified; the production ARM64 provider is unchanged.
