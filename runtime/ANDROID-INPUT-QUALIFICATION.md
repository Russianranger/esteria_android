# Android input component qualification

The existing `android-presentation.yml` emulator job builds source-owned x64
presentation JNI and a separate instrumentation APK, then runs the Surface/audio
case followed by `GameInputAndroidTest#actualImeTouchAndControllerCallbacks`.
Both tests require Android13/API33, target35, x86_64 and the explicit presentation
test build. The qualifier refuses physical/remote devices and existing app installs.
No initial Thor test or APK delivery is involved.

The new case attaches the actual `GameInputView` to an ordinary `MainActivity`,
using the existing synthetic frame producer and real `SurfaceBridge`. Android
must post a frame before controls are admitted. A touch injected through Android
opens a test toolbar's keyboard button; the actual software keyboard must become
visible and active before the real widget creates the tested `InputConnection`.
This test toolbar does not bind a production `GamePresentationPanel` session.

Eight groups cover pending text plus Done/soft Enter/IME_NULL, unchanged rejected
256-event batches and exact retry, replaced/closed/accepted connections, the
64-character/shifted event limit, Back/pause draft invalidation, constructed
gamepad KeyEvents and removal/pause release, optional registered joystick motion,
and touch coordinate conversion/cancel. Every accepted keyboard sequence releases
its keys; the recording sink has a fixed256-event capacity and never connects to
X11. Its explicit drain models consumer progress, not transport acknowledgement.
The real `InputBridge` queue policy retains separate host evidence.

The optional helper runs only fixed `/system/bin/uinput -` through Android's
shell automation API. Its fixed registration advertises eight axes and gamepad
keys. It waits for the real `InputDeviceListener`, checks actual joystick ranges,
and constructs Android `MotionEvent` objects using that registered device ID.
The actual view must emit movement keys, camera button state and relative motion
through real Choreographer ticks. Closing the owned stdin sends EOF; the helper
requires output EOF and observed framework device removal within a four-second
cleanup budget. It does not chmod `/dev/uinput`, obtain root, inject evdev packets,
adopt an unrelated device or accept caller commands, paths or PIDs.

Android13's [interactive protocol](https://github.com/aosp-mirror/platform_frameworks_base/blob/android-13.0.0_r1/cmds/uinput/README.md),
[device lifetime](https://github.com/aosp-mirror/platform_frameworks_base/blob/android-13.0.0_r1/cmds/uinput/src/com/android/commands/uinput/Device.java)
and [axis mapping](https://github.com/aosp-mirror/platform_frameworks_base/blob/android-13.0.0_r1/data/keyboards/Generic.kl)
are the reference for that fixture. The actual emulator image remains the
capability authority. If no device registration is observed and owned cleanup
completes, the receipt records `registration-not-observed` and false stick/camera
flags. A registered device with wrong ranges or incomplete cleanup fails the case.

The qualifier temporarily enables `show_ime_with_hard_keyboard` on the disposable
emulator and restores its prior value, retaining bounded diagnostics on failure.
The separate input receipt contains counters and booleans, never composed text.
Its validator requires all IME/touch/button checks, exact source/API/fingerprint
identity, and conditional joystick/removal agreement. Wine, X11 socket transport,
kernel/physical controller delivery, production panel/session binding, ARM64,
hardware and gameplay flags must remain false.

Local Python admission tests and Java/Android compilation are preparatory evidence.
An actual workflow result is required for Android IME/widget qualification; that
result still cannot establish in-game typing, camera usability, combat or Thor
controls.
