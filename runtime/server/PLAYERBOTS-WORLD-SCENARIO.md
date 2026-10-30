# Unexecuted controlled-alt world scenario

This is a source-backed plan for a future world/gameplay gate. None of its world,
movement, combat, bot-character, save, Android, offline-device or thermal checks
has run. The actual native ARM64 evidence in
[PLAYERBOTS-SCHEMA.md](PLAYERBOTS-SCHEMA.md) qualifies the database loader and 52
prepared statements, not playerbot AI. This plan changes no production policy,
account, character, asset, database or provider selection and does not open START.

## Exact source and prerequisites

The audit streamed selected files from the retained source-input archive without
extracting its tree or executing source. The archive is 18,216,368 bytes, SHA256
`8c820a962947d2b8e2028c434ccedc969127716390f557626444d23ff8e15b99`.
It belongs to server `f35f04d01689f034778e3474b3c820092f51e461`, archived lock
`5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1`
and the seven retained integration adaptations. Those adaptations do not change
the audited playerbot command, permission or count logic. Source paths below are
relative to that server tree, under `modules/mod-playerbots/`.

Before a real run, require the source-matched programs and qualified four-schema
installation on its owned MySQL UUID, real auth/world readiness, and a verified
server-data generation containing the matching DBC/maps/vmaps/mmaps/Cameras.
Also require the matching complete imported client/custom-content provider stack,
appearance inputs and the composed client/display/audio/control session. Existing
asset gaps in [ASSET-REQUIREMENTS.md](../../ASSET-REQUIREMENTS.md) remain blockers;
the SQL helper does not supply those assets or qualify world startup.

Use the existing locally owned ordinary player account. Through the real client
character-creation path, create a master and initially one ordinary, same-faction
alt; later extend to at most four controlled alts. Each alt must already exist in
the character database and be offline before it is added. Do not synthesize
character rows, create desktop random-bot accounts, grant GM privileges or invoke
gear/level initialization commands. A basic nonheroic class avoids the separate
Death Knight eligibility gate while establishing this first scenario.

## Selected policy and actual permission boundaries

The sealed policy in [local-server.json](../../config/local-server.json) and
`runtime/server_config.py` sets `AiPlayerbot.Enabled=1`, `AllowAccountBots=1` and
`MaxAddedBots=4`. It disables `BotAutologin`, `RandomBotAutologin`, minimum/maximum
random populations, random account count, AddClass account pools, generated
guild/arena counts and the command-server TCP port. Four is an initial ceiling;
device capacity and sustained performance have not been measured.

`PlayerbotAIConfig.cpp:184–186,243–246,644–646` reads these exact option names.
`PlayerbotMgr.cpp:83–144` permits a same-account alt when `AllowAccountBots` is
enabled and counts both the master's loaded bot map and its pending logins before
rejecting a request at `MaxAddedBots`. This caps that master's add path; the
separate zero-population policy is what excludes automatic random populations.

This is an own-account scenario, not a claim that the configuration globally
permits only own-account control. `AllowGuildBots` and `AllowTrustedAccountBots`
are not overridden by the current sealed profile; both retain source/template
default 1. The module also exposes ordinary-player account key/link/unlink
commands. Do not use those relationships in this minimal gate. Non-random bots
give full command access to their current master; opposing-faction and GM rules
are separate (`src/Mgr/Security/PlayerbotSecurity.cpp:30–49,162–169`). Use an
ordinary player to exercise the actual ownership boundary rather than the GM
bypass.

World configuration initialization still calls `CreateRandomBots` even when
random autologin is disabled (`src/PlayerbotAIConfig.cpp:752`). On a fresh empty
`playerbots_account_type`, zero population/pool/account options calculate zero
requested accounts and run zero account/character creation iterations
(`src/Bot/Factory/RandomPlayerbotFactory.cpp:432–541,709–766`). Existing type 1/2
records are instead unassigned to type 0 when their pools are disabled
(`:438–446`). This source behavior does not authorize adopting arbitrary existing
random-bot state or establish its actual world-start behavior.

## Future command sequence and required observations

The registered management command is `.playerbots bot`, available to `SEC_PLAYER`
from an active player session, with console use disabled
(`src/Script/PlayerbotCommandScript.cpp:28–45` and
`src/Bot/PlayerbotMgr.cpp:861–884`). Some source help strings still say `.bot`;
this audit did not establish a `.bot` alias. Use the registered spelling.

| Step | Command or action | Observation required in the future run |
| --- | --- | --- |
| Roster | `.playerbots bot list` | Existing own-account alts appear with `-`; no automatic random population or unexpected controlled bot is present. |
| Add one | `.playerbots bot add AltName` | Wait for actual bot login, live `+AltName` roster, correct master and party membership. An `add: … - ok` response alone is insufficient. |
| Ownership | `/w AltName who` | A live response identifies it as playing with the intended master; a non-master must not gain full control through ordinary secure commands. |
| Stay | `/p stay`, then move the master on a safe local path | The bot acknowledges the request and actually remains near its recorded stay position. Verify position and time, not just chat text. |
| Follow | `/p follow`, then move the master again | The bot actually resumes following on the expected map/path without a stuck state, unexpected teleport or uncontrolled extra bot. |
| Combat | Select a valid nearby hostile target, then `/p attack` | Observe actual target selection, movement, damage/healing and combat completion. Separately verify loot/quest/inventory behavior; a command response does not establish any of them. |
| Extend | Add each additional existing alt individually, up to four | Confirm each completed login and that the master plus four bots remains a five-member party. Record the combined resource change at each count. |
| Remove | `.playerbots bot remove AltName` | Confirm actual session removal, roster returning to `-`, saved state and no lingering owned process/session. |
| Persistence | Normal master logout, client relog, then clean world/MySQL stop and restart | Verify character state and intended bot ownership/group behavior after each boundary, unchanged account credentials and no partial/uncertain shutdown presented as success. |

The add command resolves existing names through the character cache
(`src/Bot/PlayerbotMgr.cpp:1283–1317`); it does not create an alt. Its implementation
calls a `void AddPlayerBot` and returns `ok` immediately, including after some
rejected requests (`:682–704`). Therefore use the later real login and live roster
as observations: `OnBotLoginInternal` assigns the master and logs the bot login
(`:1621–1631`), while `ListBots` distinguishes loaded `+` and offline own-account
`-` entries (`:1352–1438`). Group creation/invitation is queued to the world thread
(`:544–573`), so it too must be observed rather than inferred from the request.

Party chat reaches each member's AI and whispers reach the selected bot
(`src/Script/Playerbots.cpp:171–211`). Secure commands require full control after
the initial security check (`src/Bot/PlayerbotAI.cpp:951–1018`). The chat strategy
maps `follow`, `stay` and `attack` to their concrete actions
(`src/Ai/Base/Strategy/ChatCommandHandlerStrategy.cpp:49–55`). Follow resets stay
and return positions; stay records the current position and changes its movement
strategies (`src/Ai/Base/Actions/ChatShortcutActions.cpp:46–133`). Their default
acknowledgements may be replaced by localized database text. `who` can include
the current master's name (`src/Ai/Base/Actions/WhoAction.cpp:23–65`). Attack uses
the master's selected target and rejects missing, friendly, dead, out-of-world or
out-of-line-of-sight targets (`src/Ai/Base/Actions/AttackAction.cpp:31–132`).

A future cap rejection test needs a genuine additional existing offline alt. With
four bots already loaded or loading, request that fifth alt and confirm the
explicit count denial and absence of a fifth actual login. Do not mistake the
later generic `ok` acknowledgement for acceptance. This negative test does not
raise the permitted simultaneous count above four.

Use management removal for the first cleanup check. Direct whisper `logout` also
checks the current master and owned bot map
(`src/Bot/PlayerbotAI.cpp:1058–1095`). The source has a whisper-logout hotfix in
`src/Script/Playerbots.cpp:187–191`; this is another reason to verify actual clean
session removal rather than assuming it. Master logout requests all owned bots
to log out (`src/Bot/PlayerbotMgr.cpp:1550–1573`), and its save path iterates owned
bots (`:1604–1618`). These code paths are not persistence evidence until exercised.

## Observations still required

Keep separate results for one bot and each count through four. Record whole
client/Wine/display/audio/world/MySQL steady and peak memory, CPU load, threads,
frame pacing, audio continuity, input response, setup/login latency and storage
growth. On the target device, also record temperature, thermal throttling,
frequency changes and sustained behavior; host helper measurements cannot stand
in for the combined Android workload.

Repeat the actual composed session without external networking, using only owned
loopback service endpoints and fully installed providers. Confirm normal login,
world entry, the chosen bot behavior, save/relog and clean restart still work.
Offline operation, usable controls, graphics/audio, sustained resources, bot AI,
gameplay and device thermals remain unqualified until those observations exist.
No preliminary Thor APK or user test is requested by this plan.
