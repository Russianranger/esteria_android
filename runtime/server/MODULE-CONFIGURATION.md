# Complete local module configuration

The server compiles a `CONFIG_FILE_LIST` and `AC_MODULES_LIST` from selected
modules. `manifest_server_modules.py` extracts those actual compile definitions
and verifies their literals in the hash-matched installed binaries. The content
packager checks that exact selection against its source inventory and includes
every selected `.conf.dist`, plus the original auth/world main templates.

`render_server_config.py` accepts `--module-inventory` and `--compiled-modules`
together. It requires matching source-lock/module/config identities, rejects
missing or case-colliding destinations, and verifies all template sizes/SHA-256
before atomically activating a generation. Templates are bounded to 4 MiB each and
16 MiB for module content. Non-overridden settings retain their source values.
Existing credentials remain unchanged. Reuse rejects altered files, extra files,
symbolic links, FIFOs and oversized content instead of accepting partial output.

The caller must first verify the installed content package and server binaries;
metadata supplied to this renderer is not an independent signature. Main template
hashes bind the exact bytes rendered, avoiding a second-read mismatch. The private
`module-configuration.json` records source/template identities and the selected
config filenames, with startup/gameplay qualification false. The ordinary
bootstrap/account-fixture call without both manifests still prepares playerbots
only and explicitly reports `module_configurations_complete=false`.

## Local profile

- Playerbots command-server port is 0 (source-supported disabled value). The
  original default 8888 is an extra TCP service and is unnecessary for controlled
  in-game bots. Random populations remain zero and the controlled ceiling is 4,
  pending measured resource qualification.
- AzerothPlex media broadcasting is disabled and its bind is 127.0.0.1. This optional
  media service is outside the local-gameplay candidate; appearance/game transport
  is unchanged.
- Battlemon's separate LAN sidecar remains disabled and is pinned to loopback;
  Battlemon gameplay settings are preserved.
- Discord chat transmission, the separate Esteria chat bridge and launcher HTTP
  account API remain disabled. Their external dependencies are not packaged. The
  local application's owned account provisioning is separate.
- Lua remains explicitly disabled until a qualified local script map is installed.
  The pinned ElunaConfig.cpp defaults `Eluna.Enabled` to true while the main
  template omits the key; the renderer adds the source-supported false setting.
  This renderer currently does not enable mapped Lua packages. Required custom
  Lua remains a documented runtime/content qualification task.

These are explicit supported options, not no-op module implementations. C++ appearance, inventory and protocol implementations remain unchanged.
Lua-dependent custom extensions, including affected custom races, remain unavailable
until their script/content maps are installed and qualified. Extra content-dependent
modules still require matching data and actual runtime validation.

## Loading and evidence boundary

Patch7 makes the server resolve module configs next to its selected main config,
preserving the existing default path. It is now selected by `sources.lock.json`
with client `0f931bbade36a4b197725d691b8eff7caea7b3be`. Its actual source-linked
x86 host reference verifies absolute, relative and bare configuration paths,
reload, default-path preservation and missing-sibling refusal.
Do not launch a complete world configuration through a binary that still bakes a
CI runner config path. ConfigMgr can return success when module files are absent;
readiness must check the actual loaded selection/values as well as file presence.

Twenty-six related host groups pass (renderer, content inventory and deterministic
package). A source-only exercise rendered all 50 committed module templates from
server f35f04d after comparing their exact bytes with Git. Its selection record was
synthetic; it does not qualify binary selection or module startup. A further actual ConfigMgr x86 host fixture now parses all 50 real source templates,
then changes fixture-only sentinels and verifies every value through actual reload.
It checks the rendered Lua, bot command port, random population and controlled
bot ceiling values and verifies that source configurations remain byte-identical.
Template bytes were compared with the archived content receipt; installed binary
selection was not independently reverified by that host exercise.

`qualify_module_configurations.py` adds the native ARM64 gate: source/patch and
installed receipts, real ConfigMgr/reference compile commands and integration
source bytes must match before rendering the exact compiled world's selection.
The reference links real `common`, copies configurations into a fresh private
fixture, and never runs worldserver or SQL. Its public receipt binds source and
executable hashes, exact selected filenames, parsed policies and reload evidence.
The workflow retains no private configurations or logs in public artifacts.

The auth and reconstructed-client qualification compositions now use the same
complete metadata renderer, after requiring both main source templates to match
the installed build. This prepares world module configurations; authserver itself
does not load the world's CONFIG_FILE_LIST.

Native ARM64 run [41041859706](https://github.com/Russianranger/esteria_android/actions/runs/41041859706)
at integration `e1341cf658d972d66bd05c90150eb7bf3c3db0df` now passes the actual
source/build-bound ConfigMgr gate for all 50 compiled world module configurations:
every selected file parses, fixture reload values and rendered policies verify,
and original configuration bytes remain unchanged. Its public receipt identifies
a 9,187,984-byte reference, SHA-256
`bb553f0a0b8dc7ee1d1d1019922dedec97e34e31f1a3c56faaa1593dda26bced`.
The matching source lock is the current seven-patch
`5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1`.
Exact receipt/artifact bindings are in
`runtime/evidence/server-module-configurations-41041859706.json`.

The later compiled SQL/auth/playerbots composition still fails in that earlier
snapshot. ConfigMgr starts neither worldserver nor SQL; module gameplay hooks,
playerbots execution, world entry and Android remain separate gates.
