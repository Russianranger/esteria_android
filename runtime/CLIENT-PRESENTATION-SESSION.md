# Local client presentation composition

`ClientPresentationSession` owns the prepared Wine runtime's ARM64 Linux X11
server, the exact guest frame/input helpers, and Android's `SurfaceBridge`,
`InputBridge` and `AudioBridge`. It is a component coordinator, not a client
launch button. It has no API for launching `WowClient64.exe`, modifying game
configuration, starting a database, or declaring gameplay ready. In particular,
the older packaged `69ccfaa...` client cannot be launched here with an unsupported
`--local-offline` option. Full activation must separately require the measured
new client, imported data/shaders, local server readiness and a persistent owner.

`Prepared.inspect(context, privateWork)` runs off the Android main thread. It
requires installed Wine and guest-bridge generations with matching archive pins,
then streams the existing `runtime/bridges/x11-runtime.lock.json` checks: 49 ELF
images, 44 library/loader aliases, four loader configuration files, and no global
preload file. The lock is packaged directly from its authoritative repository
path. Inspection performs no network access. Startup re-resolves both installed
generations and rejects a changed selection.

Use `begin(context, prepared, events)` off the main thread and retain the returned
owner in the service before calling its single-use `start()`. A startup exception
keeps that owner available for `close()` and subsequent cleanup retries. The
compatibility static `start(context, prepared, events)` also retains the owner
internally before starting anything; failed cleanup can be retried through
`retryPendingCleanup(context, prepared)`. Another session cannot replace the same
work directory while its previous owner remains retained. Each new session uses private canonical `files/s/<random>/` directories and a new 16-byte random
MIT-MAGIC-COOKIE-1 credential, stored as a mode-0600 Xauthority file. It starts:

1. Android's private audio socket listener.
2. The pinned Xtigervnc at 1280x720/24-bit with authenticated X11, no TCP X11
   listener, no RFB port, and a fresh private shared X11 socket directory.
3. Frame and XTest helpers after their real X11 connection, exact ready markers,
   and owned private listener sockets are observed.
4. The actual input protocol handshake and the surface bridge, whose connection
   begins when the owner supplies a valid Android Surface.

The fixed `/session` and `/tmp/.X11-unix` IPC bindings are typed separately from
immutable providers. Each child retains separate `/tmp`, PRoot scratch and logs.
Every source is canonical and disjoint from runtime, work, logs and providers.
PRoot remains a compatibility layer, not a network or same-UID security sandbox.
The session cookie prevents unrelated X11 clients from using the display; it is
never logged or included in diagnostic facts and is removed on shutdown.

The exact pinned Debian TigerVNC `1.12.0+dfsg-8`
[`vncExtInit.cc`](https://sources.debian.org/src/tigervnc/1.12.0%2Bdfsg-8/unix/xserver/hw/vnc/vncExtInit.cc/)
creates TCP RFB listeners only when `rfbport != -1` (source line 228). This command
also supplies no RFB Unix socket or inetd mode. Unlike the earlier isolated Linux
qualification fixture, the Android composition never supplies `-ac`.

The owner passes `input()` and `surface()` to the existing `GameInputView`.
`pauseInput()` attempts key release, always detaches the surface and mutes audio;
`resumeInput()` preserves the latest real audio-focus grant. The view must also
clear its controller state and reattach its current valid Surface when resuming.
Surface recreation does not stop the database. Events report frame dimensions
or fixed failure codes, never credentials or arbitrary guest log text.

`close()` runs off the main thread. It closes the input connection first (the
real guest helper releases held keys/buttons on EOF), joins the surface worker,
terminates/reaps guest helpers in reverse order and closes Android audio. Explicit
`OwnedProcess.terminateAuxiliary()` uses the same bounded native TERM/KILL/reap
ownership as normal shutdown, retains actual status and `wasForced`, and still
reports backend/log/timeout failures. It refuses any child with a graceful save
callback and cannot override a prior normal stop. It never claims a character or
database save. Unexpected helper exit is a session failure. Residual socket paths
are retained rather than blindly deleting an inode whose ownership changed.

Startup and shutdown share a safe-boundary guard. A concurrent close requests
cancellation before waiting, rejects new startup work, and preserves ownership if
the requested wait expires. `close(Duration)` accepts zero through30seconds for
that guard; each native child retains its existing additional seven-second reap
budget. Calls must stay off the Android UI thread. A live child, bridge worker or
interrupted cleanup keeps `isClosed()` false. Audio, Xauthority, exact IPC bindings,
provider identities and the strong owner remain retained while a guest is alive.
A later `close()` retries the same children and only removes Xauthority/registry
ownership after every producer has stopped. The original cleanup failure remains
available through `cleanupFailure()` even when a later retry releases resources.
The shared Java process owner now keeps its creating thread alive and retries
native cleanup when the backend throws or returns RUNNING. Neither status127 nor
a finished latch can stand in for a confirmed reap. Its public stop remains
bounded, failure history is capped, and final metrics publish only after actual
termination. Immutable runtime generations are retained by the installer; this
coordinator does not delete or replace them.

The fixed optional `/esteria-turnip` provider destination is reserved, but this
coordinator selects no Vulkan driver. A later verified Turnip adapter must select
its exact manifest explicitly. Likewise, actual Wine audio requires its prepared
prefix's `HKCU\\Software\\Wine\\Drivers` Audio value to be `alsa`, in addition to
these fixed ALSA socket/config paths and disabling `winepulse.drv`; this class
does not claim that prefix preparation has happened.

Validation is deliberately separated. Java host contracts cover Xauthority
encoding, mount isolation, fixed argument boundaries, auxiliary shutdown errors
and concurrent stop semantics. The `:app:presentationOwnerTest` host fixtures
exercise the real Java lifecycle owners with delayed controlled process backends,
real file locks, interrupted cleanup and prelaunch cancellation. They do not run
JNI, X11 or Android APIs; their Looper guard stub is excluded from every APK.
The existing Android presentation/audio and native
ARM64 guest-helper receipts cover individual components. This new combined
Android session, authenticated X11 connection, GPU hardware, game pixels/audio
and gameplay still require their own execution evidence. No Thor test is requested
at this stage.


## Replaceable Android view

`GamePresentationPanel` consumes an already started session. A session-owned
`SessionEvents` relay forwards frame geometry and failures to the currently
attached view without retaining a detached Activity. The owner handles Stop and
retains database/client processes independently of Activity or Surface recreation.
The panel exposes the software keyboard and the existing controller/touch router.

`GameInputView` separates Surface availability from an attached writer. Pause
neutralizes held input and detaches rendering; a Surface created while paused
cannot restart it. Resume attaches the current valid Surface once and waits for
new frame geometry. The panel also mutes presentation audio through the session.
No launcher action creates this panel yet; it does not admit an unqualified game
or establish Android X11/guest/client execution. The expanded synthetic Android
Surface fixture separately checks the view lifecycle.
