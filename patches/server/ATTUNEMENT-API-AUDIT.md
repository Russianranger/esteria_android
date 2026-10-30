# Attunement stat API compatibility audit

Server source: `f35f04d01689f034778e3474b3c820092f51e461`.
Module: `modules/mod-attunement-plus/src/mod_attunement_plus.cpp`.
Adaptation: `0004-attunement-stat-api.patch`, SHA-256
`d9ef6ca8f96ab186c37c072b22143cdded9976aa3a62d083f893c502a5745cb8`.

Native ARM64 build [40987376145](https://github.com/Russianranger/esteria_android/actions/runs/40987376145)
at integration `286608f62c9c1861771851f7bdd45ba79da73f6f` reached object 1214/2258
and failed because the module calls removed `Player::ApplyStatBuffMod` and
`Player::HandleStatModifier` methods. This is source API drift, not an ARM
instruction-set or ABI failure. The partial compiler cache was retained.

## Exact source comparison

The historical implementation was checked in the authoritative AzerothCore tree:

- [Unit.h before removal](https://github.com/azerothcore/azerothcore-wotlk/blob/50b36e842a1357611402d3eece3692861cb0dc03/src/server/game/Entities/Unit/Unit.h).
- [Unit.cpp before removal](https://github.com/azerothcore/azerothcore-wotlk/blob/50b36e842a1357611402d3eece3692861cb0dc03/src/server/game/Entities/Unit/Unit.cpp).
- [The spell-group/stat-system migration](https://github.com/azerothcore/azerothcore-wotlk/commit/2f7f9bd72f188298d8805e1faaa4019c1e03016c).

`50b36e8` is the preceding Unit.h-touching revision in that path's history.
The actual target implementation was independently read from the pinned Esteria
Git objects, particularly `Entities/Unit/Unit.h`, `Unit.cpp`, `StatSystem.cpp` and
`Entities/Object/Object.h` / `Object.cpp`.

| Old call | Actual historical effect | Selected-core adaptation |
| --- | --- | --- |
| `ApplyStatBuffMod(stat, amount, apply)` | Adds/removes `amount` from the positive or negative **display field** via `ApplyModSignedFloatValue`; never changes the underlying primary-stat modifier groups. | Module-local `ApplyAttunementStatDisplay` retains that exact field selection and amount/apply operation through the still-present `ApplyModSignedFloatValue`. |
| `HandleStatModifier(UNIT_MOD_ARMOR, TOTAL_VALUE, amount, apply)` | Adds/removes a flat armor modifier, then recalculates when stat modification is enabled. | `HandleStatFlatModifier` with the same `UNIT_MOD_ARMOR`, `TOTAL_VALUE`, amount and apply flag. |
| `HandleStatModifier(UNIT_MOD_ATTACK_POWER, TOTAL_VALUE, amount, apply)` | Adds/removes flat attack power, then recalculates when enabled. | `HandleStatFlatModifier` with the same attack-power group and arguments. |

All four armor/AP calls are guarded by positive applied/cached values. The modern
API's early return for zero amounts therefore does not change these paths. Both
old and new APIs store the flat delta when `CanModifyStats()` is false and defer
recalculation; the module ignores their boolean return value. Existing explicit
armor/attack-power refreshes, cached removal order, rounding, weapon-DPS conversion,
other sink calculations, persistent SQL queries and 10-second refresh cadence are
unchanged.

The compiler's `UpdateStatBuffMod` suggestion is **not** a compatible substitution.
That modern one-argument method recomputes display values from equipment and aura
state; it has no amount/apply delta. Nor is adding a primary `BASE_VALUE` modifier
an equivalent port: that would introduce real primary and secondary combat bonuses
which the historical display-only method did not provide.

## Preserved behavior and unresolved gameplay defect

The module's original header incorrectly claimed that its primary-stat call drove
secondary stats such as health from stamina. The historical implementation disproves
that claim. This patch corrects the comments and preserves the actual old display
operation, while retaining real armor/AP modifiers. It does not silently introduce
a new permanent-stat source or change balance during an API compatibility fix.

Primary-stat **gameplay bonuses remain unqualified**. The modern aura/equipment
recalculation path may recompute those display fields; the compatibility helper
does not claim to solve that separate interaction. A deliberate future gameplay
fix must choose and test a persistent stat source, apply/remove/refresh symmetry,
gear and aura recalculation, secondary-stat effects and relog behavior against the
matching character/content state. Do not mark the full attunement feature complete
because this module compiles.

## Validation and content scope

The patch was applied with `git apply --check` and `git apply --index` to a temporary
fixture containing the exact pinned original module bytes. The resulting file
matched the reviewed adaptation. The source repository's working tree was not
modified. The server workflow now compiles the actual attunement translation unit
first, using the configured ARM64 headers/options, before continuing the full build.
Its success is pending the next real CI run; no local full module compilation or
runtime bonus test is claimed.

Only one C++ module source and its comments are changed. SQL, Lua, configuration,
module discovery, updater ordering and network fields are unchanged. The centralized
content policy verifies this exact patch digest at **server-root scope**, distinct
from the three Eluna-scoped C++ patches. A matching name with altered bytes, a moved
scope or any unreviewed SQL patch remains rejected. Source inventories now include
an explicit `sourceAdaptations` record instead of mislabeling this as an Eluna-only
or content-changing patch.
