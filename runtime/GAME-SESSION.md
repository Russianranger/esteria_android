# Retained local game session adapter

`GameSession.begin` accepts only a `LocalWorldSetup.Result` and the sealed,
prepared reconstructed-client/presentation providers. The result constructor is
private. Source hashes or caller booleans cannot create a completed installation
or prepared data binding. This adapter has no Main/Service activation of its own.

Before any child starts, the owner acquires both the actual `game/import.lock`
used by `GameDataImporter` and the writable client's
`state/client-work/.client-launch-setup.lock`. It retains those locks, the exact
runtime providers and every started child until confirmed cleanup. View
preparation runs under the typed retained client lease without release/reclaim.
The current import, shader receipt/output metadata, source-matched shader tools,
promoted database proof and immutable providers are checked again after setup.
Shader readback checks every listed output path and size; it does not rehash all
shader bodies or establish GPU correctness.

Startup is ordered: the promoted database's authenticated owned readiness,
`LocalServerSession`'s four-schema/source/UUID/account/listener/protocol/console
verification, presentation, then the reconstructed client. The lower server
owner's retained cancellation predicate follows outer startup only. A
synchronized irreversible handoff drains/latches pending cancellation before a
client may start; later outer close/cancel cannot stop world/auth ahead of the
client. Only the ordered `servers.close` initiates that shutdown. No baseline/schema
initialization is replayed over promoted saves. Only after those real services
are ready does the owner read the mode0600, single-link private account journal,
recheck its exact hash against `Active.setupReceiptSha256`, and create the strict
one-use handoff. No password is placed in argv, environment, UI, errors or new
public receipts. Transient source arrays are cleared. The existing private
account journal remains unchanged.

The client command is fixed `/opt/wine/bin/wine` plus the matched launch view's
Windows executable, `Plan.arguments()` and the source-capability-verified
`localLoginArguments()`. Imported data and prepared shaders receive their fixed
guest mounts. Optional Turnip selection reuses its typed Wine compatibility and
selected environment contract. This remains rebuilt Windows ARM64 execution
inside Wine, not native Android execution.

The lifecycle monitor reports client exit or dependency failure to the central
caller; that caller performs cleanup on its retained worker. The monitor does
not compete for the close guard. `CLIENT_STARTED` records actual process
ownership only. It is not a login/world-entry/rendering/audio/gameplay signal.

Normal close releases held input and sends one atomic Alt_L/F4 down/up sequence.
The pinned client471 Windows input source maps Alt+F4/WM_CLOSE into the normal
engine close event. Input queue acceptance is not acknowledgment: the exact
owned client must exit0 without force or ownership errors. Client presentation
refuses to destroy display, input, audio or authority while this client lives.
A graceful failure/timeout retains the client and every lower dependency,
records `needsForceStop`, and returns a bounded error. No automatic kill follows.
Only a separate explicit user action may call `requestForceStop`; the next close
uses the actual opaque process owner to kill/reap, records `recoveryRequired`,
and still retains all resources if native cleanup remains active. Force never
reports a normal client exit or a successful save.

After confirmed client reap, cleanup removes only an unchanged/unconsumed
handoff, then closes presentation, gracefully stops world/auth, and shuts down
the database before releasing both file leases. Any live dependent owner keeps
all later dependencies. Before initiating world/auth shutdown at least10s of the
current close budget must remain, and database shutdown needs at least5s.
An exhausted earlier client/display phase returns a retained error and requires
a fresh close attempt; it cannot select an immediate forced SQL shutdown.
A foreign/changed handoff is preserved verbatim. Once
all actual children have stopped, that condition records
`handoffRecoveryRequired`, closes playing/import ownership with a visible error,
and requires explicit local-login recovery. Reusing the same view fails its
existing CREATE_NEW writer before another client launch. No automatic deletion,
quarantine or credential reset is implemented. A support report must describe
this condition without including the handoff or private account journal.

`clientExitAcknowledged` proves only that the observed client process stopped
normally. Neither this field nor clean world/database shutdown qualifies actual
character saving/relogging. World coverage, gameplay, bot AI, audible output,
controller usability, Android/Adreno execution and the Thor candidate remain
separate open checks.

The host fixture uses actual Java process owners, real filesystem/importer/view
locks and controlled backend/input fixtures. Its private handoff mutation test
uses the production strict writer/cleanup. No actual Wine, MySQL, server/client
binary, game data, Android runtime or GPU executes in that fixture. APK/test
compilation and lint are recorded separately in the evidence JSON. The new
fixture class and host Looper stub must never enter the APK.
