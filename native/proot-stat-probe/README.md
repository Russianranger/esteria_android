# Isolated Android/PRoot stat qualification

The production prepared-data stat cache stays disabled. This fixture tests one
necessary condition on a disposable Android13 x86_64 emulator; it does not qualify
Android ARM64, the Thor, a Python runtime, gameplay, or cache activation.

The unchanged, byte-pinned PRoot/glibc probe supplies its tracer, loader and
Debian2.36 mini-root. A separate small C executable is built from this directory
against that exact sysroot and packaged only as generated AndroidTest assets.
No production native library, PRoot patch, provider pin or Gradle file changes.
The new source companion includes the entire original probe source companion.

The real guest compares libc `stat`/`lstat` and raw `newfstatat` results through
`/work/server-data/generations/<64hex>` and `/esteria-data`, which bind the same
app-private generation. Every observation retains `dev`, `ino`, `mode`, `uid`,
`gid`, `nlink`, `size`, `mtimeNs` and `ctimeNs` as exact decimal strings.
Generation/data roots, regular files, directories and symlinks are covered.

Mutations include hardlink creation/removal with observed link counts, chmod,
same-length writes followed by restoration of the exact
original mtime, same-content inode replacement, and directory entry addition and
deletion with directory mtime restored. These must remain distinguishable by
mode, inode or ctime. A fixed `123456789` nanosecond mtime tests subsecond
preservation. A symlink ancestor shows why checking only a leaf tuple is
insufficient; no-follow directory opening must reject that ancestor. A second
actually reaped guest must observe the same final tuples through both aliases.

This qualifies only metadata-visible changes in privately owned immutable data.
It does not detect byte corruption which preserves every observed metadata
field. Filesystem timestamp granularity or PRoot translation which hides a
required mutation fails qualification; no substitute success flag is emitted.

The workflow builds the ordinary probe using its existing script, then runs:

```sh
python3 tools/build_android_proot_stat_probe.py build \
  --proot-work /absolute/proot-probe --ndk /absolute/android-ndk-r28c \
  --work /absolute/new-stat-work --source-revision <full-commit> \
  --test-assets app/src/androidTest/assets/proot-stat-probe
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest \
  -PnativeRuntimeBridge=true -PnativeBridgeAbi=x86_64 \
  -PprootProbeProviderDir=/absolute/proot-probe/provider -PsourceRevision=<full-commit>
python3 tools/qualify_android_proot_stat.py \
  --apk app/build/outputs/apk/debug/app-debug.apk \
  --test-apk app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk \
  --proot-provider /absolute/proot-probe/provider --stat-provider /absolute/new-stat-work/provider \
  --source-revision <full-commit> --output /absolute/new-evidence
```

The harness refuses physical/remote devices and preexisting app installations.
Local C tests exercise real host filesystem mutations and strict receipt refusal
rules; they cannot replace Android/PRoot alias qualification. Build receipts
record raw source/compiler/fixture hashes and whether all fixture sources match
the selected committed revision. Dirty-source builds remain build-only.
