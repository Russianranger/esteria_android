# Authenticated native ARM64 X11 input fixture

`guest-bridges.yml` extends the existing measured Linux ARM64 XTest event gate.
This extension has host guard coverage; its actual authenticated ARM64 run is
pending publication and CI. The earlier unauthenticated event result does not
qualify this new boundary.

The host compiles the application's exact `X11SessionPlan.java` with the small
`tests/fixtures/X11AuthorityFixture.java` caller. That caller uses `SecureRandom`
to create a private 16-byte cookie, calls the real application's authority-file
formatter, and writes a second validly formatted but incorrect cookie. Both
files are exclusively created with mode 0600 in a fresh mode 0700 runtime
session. They are never arguments, logs, repository files, or uploaded evidence.
The archive's existing empty `/session` directory remains a mountpoint; only
inside the owned mount namespace is the new private session bound onto it.
Existing contents or a symlink at that mountpoint are rejected.
The public receipt records both source hashes and the host Java executable
hashes. This is measured host tooling, not a pinned Java runtime dependency of
the APK.

The fixture also calls the actual application's server-command formatter. The
qualifier requires its exact `-auth /session/Xauthority`, display 64, no TCP or
RFB listeners, and no `-ac`. The pinned Xtigervnc executes that command inside
the existing owned, offline PID/mount/network namespace. The production input
helper's source and measured AArch64 ELF remain unchanged.

Two real negative launches explicitly select a missing authority file and the
incorrect file. Each must exit with the source-confirmed XOpenDisplay/XTest
rejection code 3, create no input endpoint, and emit no ready marker. This exit
occurs before the helper's listener creation in its measured source. The X11
server must remain alive through both checks. The correct cookie must then
allow the production helper's private listener and ready marker, followed by
the existing independent observer's 16 actual X events, 15 acknowledgments,
key/button release on EOF, unsupported-key rejection, and neutral reconnect.

The existing process-exit, socket-removal, bounded-log, namespace-cleanup and
exact observer-receipt requirements remain mandatory. Both
`linuxArm64X11InputQualified` and the new
`linuxArm64AuthenticatedX11InputQualified` stay false if authentication, events,
or cleanup fail. Neither flag claims PRoot operation, Android integration,
controller mapping, Wine/client execution, Adreno rendering, or gameplay.

Run the focused host checks with JDK17 on `PATH`:

```sh
ESTERIA_REQUIRE_JAVA_TESTS=1 python3 -m unittest tests.test_x11_input_qualification -v
```

The workflow makes the Java execution mandatory. Local tests without a host
JDK explicitly skip that one group; they cannot establish formatter execution.
No private runtime session is included in the artifact paths.
