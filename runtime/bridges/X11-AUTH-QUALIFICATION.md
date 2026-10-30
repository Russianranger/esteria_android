# Authenticated native ARM64 X11 input fixture

The authenticated native Linux ARM64 execution passed in
[run 41041859781](https://github.com/Russianranger/esteria_android/actions/runs/41041859781)
at integration `e1341cf658d972d66bd05c90150eb7bf3c3db0df`.
The actual application Java formatter executed; missing and incorrect cookies
were rejected before listener creation, then the correct cookie passed all
seven event groups, 16 observed events and 15 acknowledgments. Normal helper,
display and namespace exits, socket removal and bounded log drainage passed.
This is a Linux ARM64 host component result; PRoot, Android, Wine/client and
controller execution remain separate gates.

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

## Verified retained evidence

Artifact `12971070587` is 142,444,010 bytes, SHA-256
`c6fc79a3437e01518184c4b3182f36858e33d14456b2f9ad7d17e10198a10ae7`.
It includes public build/source evidence as well as the small execution logs.
The archive was downloaded and checked against that complete identity. Its
3,948-byte qualification receipt has SHA-256
`3d46c1f194003be72d6f6a70186c38d00601ba5dfd5e84855a861b9c1d00e738`.
The public receipt and per-file identities are retained in
[`../evidence/x11-auth-arm64-41041859781.json`](../evidence/x11-auth-arm64-41041859781.json).

Independent readback matched both archived formatter sources to the measured
source hashes and checkout, inspected the actual AArch64 helper/observer ELF
bytes against their source-bound build receipts, and revalidated the strict
authentication, event and cleanup receipts. The helper is 73,392 bytes,
SHA-256 `1402acc34f52e33177d9bef1b57b46532d192a5ac3b2eb0675973c80e6b0a014`.
Both negative launches returned code 3 with no endpoint or ready marker.
The observer verified held-input release on EOF, unsupported-key rejection and
neutral reconnect. Neither helper nor display required forced termination.
The archive contains no authority files, private authentication session or
formatter class directory. The observer's recorded source-format receipt hash
was checked separately from the qualifier's indented public JSON export.
