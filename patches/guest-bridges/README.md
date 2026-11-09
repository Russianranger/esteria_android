# Proposed guest bridge changes

These patches are **not applied**. The shipped guest helpers are part of the published
Wine cohort, and the APK build checks that `native/guest-bridges/*` and
`native/presentation/frame_*.h` still match the bytes recorded in
`runtime/bridges/android-provider.lock.json`. Changing those files on `non-custom`
without a new cohort would stop the APK build at `bridge-source-input-changed`.

## 0001-x11-frame-fewer-copies.patch

`esteria-x11-frame` currently copies every captured frame twice before sending it: once
from the `XImage` into a packed buffer, and once more into a `previous` buffer used to
detect unchanged frames. The patch sends directly from the `XImage` when its rows are
tightly packed, which is always true for 32-bpp ZPixmap, and keeps the previous
`XImage` for the comparison instead of copying it. Padded rows still work through two
alternating packed buffers. The wire protocol and `frame_protocol.h` are unchanged.

Host evidence (x86-64 Xvfb, no PRoot, not Thor) is recorded in
`runtime/evidence/non-custom-v26-frame-helper-copies.json`: identical wire output on a
16-frame sequence with 6 unchanged replies, and 26% less helper CPU for changed frames
and 20% less for static frames.

### Adopting it

1. Apply the patch on a branch that drives the guest bridge build, run
   `.github/workflows/guest-bridges.yml`, then the Wine cohort workflows
   (`android-wine-cohort.yml`, `preserve-wine-cohort.yml`) to publish a new cohort.
2. Update the provider locks to the new cohort and confirm the APK build verifies
   the new corresponding source.
3. Compare `presentation.changedCaptureMs` per posted frame in a Thor support bundle
   before and after.
