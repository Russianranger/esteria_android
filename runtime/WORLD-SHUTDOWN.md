# Local world console shutdown

The pinned server `f35f04d01689f034778e3474b3c820092f51e461` supports the exact
console command `server shutdown 1` followed by a newline. It rejects a zero or
negative delay (`src/server/scripts/Commands/cs_server.cpp`, shutdown command
registration and handler). `WorldConsoleShutdown` sends that fixed command through
the opt-in owned stdin pipe with a 500-ms bound. It throws if the whole command
cannot be queued. It never writes command text or credentials to diagnostics.

The local renderer explicitly sets `Console.Enable=1`,
`Wintergrasp.DeferShutdownTimer=0`, `Ra.Enable=0` and `SOAP.Enabled=0`.
The Wintergrasp setting prevents an active battle from postponing the timer.
The Linux console uses GNU readline, strips CR/LF and queues the command for
execution on the world thread (`apps/worldserver/CommandLine/CliRunnable.cpp` and
`game/Chat/Chat.cpp`). No leading dot is required. Stdin must remain open while
waiting: EOF independently calls `World::StopNow(0)` and is not an acknowledgment
that the console command ran.

The intended caller is `ProotProcess.startInteractive(...,
new WorldConsoleShutdown())`, retaining the returned `OwnedProcess` for the
session lifetime. Stop it off the UI thread with a reasonable shutdown budget
(up to 30 seconds), keep MySQL alive until the owned world process has exited,
then request MySQL's authenticated clean shutdown separately. A full stdin pipe,
failed command callback, nonzero shutdown exit or exhausted deadline remains an
error. Signal-based termination is reported as forced cleanup, never a save.
No application gameplay action invokes this adapter yet.

The source supports this intended cleanup sequence:

- `apps/worldserver/Main.cpp` shuts down IO, marks the realm offline, kicks
  sessions, updates their removal, stops networking and unloads maps before
  database teardown through its RAII handles.
- `WorldSessionMgr::KickAll`, `WorldSession::LogoutPlayer(true)` and
  `Player::SaveToDB(false, true)` initiate character persistence, including
  inventory, quests and spells. Save failures still require runtime validation.
- `DatabaseWorkerPool::Close`, `MySQLConnection` destruction and
  `DatabaseWorker` joining drain queued operations before connection teardown.
  The playerbots database closes through its module database-closing hook.
- The playerbots shutdown hook invokes `LogoutAllBots` and bot save/logout
  paths. Some bot group cleanup is queued after the world loop, so this source
  trace does not establish complete bot persistence.

Host evidence: the real native owner suite and 12 Linux JVM/JNI groups pass,
including exact binary stdin, EOF, bounded backpressure with zero partial writes,
close/write races, EPIPE, handle closure and the exact shutdown line delivered to
a fixture that exits normally. Android API26 ARM64 cross-compilation passes.
The Android13 x64 owner instrumentation now requires equivalent stream and
console-fixture checks; execution of those new checks is pending CI. These
fixtures execute no world server and prove neither character saving nor bot
persistence. Actual world shutdown, authenticated database shutdown, restart and
character/bot relog remain required integration gates.
