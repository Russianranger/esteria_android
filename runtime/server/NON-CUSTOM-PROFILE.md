# Stock 3.3.5a server profile

The `non-custom` branch seals `content_profile=stock-3.3.5a` in the bundled
local-server policy. The separate Android package owns its own databases,
configuration generations and saves. Complete pinned server sources and the
seven integration adaptations remain unchanged and recoverable.

## SQL selection

The original core baseline is imported unchanged, including its genuine DBC SQL
corrections. The compiled updater then reads an app-owned, streamed copy of only
selected authentic source update files. `SourceDirectory` is a supported input to
the pinned updater. Source metadata and every original SQL input are verified;
selected file hashes and the stock policy are bound into the private updater
journal. The projected file set and bytes are checked again before execution.
No SQL rows, update ledger entries or empty substitute files are fabricated.

The stock projection excludes:

- Core `pending_db_world` custom content, retaining the original pure
  `rev_20260929001000000.sql` DDL required by the compiled race loader.
- World SQL from `mod-custom-server`, `mod-classless-wildcard` and
  `mod-worgoblin-high-elf`.
- Individual Progression world SQL, which replaces stock outfits and restores
  Vanilla-era quests/NPC stats even when its runtime configuration is disabled.
  Its character schema remains available to the compiled module.
- Battlemon's separate `data/sql/world` custom actor/model scripts. Its
  `data/sql/db-world` catalog schemas remain for the unconditional catalog loader.
- The transmog NPC/summoner script that includes custom client spell 200100.

Auth and character schema updates, ordinary released/archived updates and
asset-independent module data remain. In particular, the canonical stock Human
Warrior start is retained. Every SQL file still comes from the pinned server.
The source audit, paths and exact hashes are in
`runtime/evidence/stock-sql-source-f35f-audit.json`.

Both normal auth/world startup configurations disable automatic core SQL updates;
the normal bot configuration also disables automatic fourth-schema updates.
The fourth-schema playerbots setup also disables core updates and enables only
its own schema loader. This prevents the preserved full source tree from
reapplying excluded world SQL after setup. Setup continues to refuse adopted,
partial or existing saves; repeats verify completed journals without SQL replay.

## Runtime content policy

All compiled configuration files remain present and hash checked. Source-supported
options disable WXL DBC continuations, classless gameplay, Individual Progression, challenge modes,
Battlemon/battles/overworld, transmog UI, external bridges and unqualified Lua.
Other asset-independent modules remain configured. Bot population/autologin are
off; bot AI qualification is deferred.

Individual Progression's unconditional `OnAfterConfigLoad` overrides are also
disabled separately: SimpleConfigOverride, MaxMonsterSight, DisableQuestMarkers
and DisableRDF. This retains the main source configuration's Wrath regeneration,
breathing timer, item-attribute validation and quest markers.

After actual updater execution and on completed setup verification, live SQL
queries require empty ChrRaces, ChrClasses, Map and CharStartOutfit overlay tables,
and the canonical Human Warrior start at map 0 / zone 12 / Northshire. Other
baseline DBC correction tables remain intact. A failed query preserves the
installation and reports the exact stock closure that failed.

Those SQL predicates are not a world-entry result. The real worldserver must
load the generated stock DBCs, maps and vectors, satisfy its build-era and
cross-table checks, then complete the existing owned protocol/console readiness
checks. Normal graphical client initialization, login, character creation and
world entry still require authentic client data. No such data-backed execution
was available during this source/profile change.
