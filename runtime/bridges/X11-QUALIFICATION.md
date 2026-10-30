# Actual ARM64 X11 input qualification

The `guest-bridges.yml` workflow builds an additional **test-only** observer with
the same pinned Debian12 ARM64 compiler/dev packages. `x11-test-export` exports
that fixture under `x11-test/`, with its source hash, measured ELF requirements,
exact integration revision and the production bridge receipt hash. The normal
`guest-export` target and three production helper inputs are unchanged.

`tools/qualify_x11_input.py` requires a fresh, fully prepared Wine runtime,
source-matched production `esteria-x11-input`, source-matched observer and a
native ARM64 Linux root host. The X server is the pinned runtime's Xtigervnc;
Wine itself is not launched. Forty-nine actual X11/loader/library ELF hashes,
their 44 loader/SONAME aliases and the loader cache/configuration are checked
against `x11-runtime.lock.json` before execution. The lock records the exact
runtime archive and static shared-library closure, not every possible dynamically
loaded X11 module. Global preload is required to remain absent.

The owner creates private mount, PID and network namespaces with loopback as the
only interface. Xtigervnc has no TCP X11 listener or RFB port. A C observer opens
and focuses a real X window, selects events on its own X connection, and sends
commands through the production helper's private Unix socket. The observer never
calls XTest itself. It requires these actual observations:

- Absolute and relative motion events and queried pointer coordinates.
- Button press/release events and queried button masks.
- Physical key press/release and explicit Shift+1 yielding `!` via XLookupString.
- Held key/button releases after the command socket closes, verified by events,
  XQueryKeymap and XQueryPointer.
- Rejection acknowledgment and connection close for an unsupported shifted
  keysym, with no injected event, then a working neutral reconnect.

Exactly 16 observed events and 15 command acknowledgments must match the fixture.
Its exclusive receipt is parsed strictly. Qualification also requires the helper
to exit normally, remove its owned socket, stop the X server, drain bounded logs,
and exit the owned namespace. A killed or incomplete namespace cannot qualify.
No Android, controller mapping, Wine-client or gameplay qualification is implied.

The standalone invocation after `x11-test-export` and runtime preparation is:

```sh
sudo python3 tools/qualify_x11_input.py --runtime /private/new-runtime \
  --bridge-dir /private/source-built-bridges --bridge-revision FULL_COMMIT_SHA \
  --output /private/new-x11-evidence
```

Current evidence: the observer compiles with `-Wall -Wextra -Werror` on host x64;
six focused receipt/build-input guards pass. All 49 runtime ELF images, aliases
and loader metadata were independently read and verified against the previously
qualified archive. Native ARM64 run `40999380088` built and executed the fixture:
motion/buttons passed, then an unexpected event preceded the first key check.
The observer now handles X11 administrative `MappingNotify` events separately,
refreshes the keyboard map, and logs unexpected event types. All 16 input-event
assertions remain mandatory; the corrected execution gate is still pending.
Filesystem Unix listener creation and Docker are unavailable on this local host;
host compilation and source review do not substitute for that execution.
