#!/usr/bin/env python3
"""Host source/metadata adapter for the shared runtime configuration renderer.

The source-backed package/module validator remains a host gate. Runtime callers
use render_verified with real VerifiedContent, never a fabricated source receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime import server_config as shared

PROFILE = Path(__file__).resolve().parents[1] / 'config/local-server.json'
MODULE_OVERRIDES = shared.MODULE_OVERRIDES
quoted, overlay = shared.quoted, shared.overlay
disable_unqualified_lua = shared.disable_unqualified_lua
write_private, bounded_plain, plain_directory = shared.write_private, shared.bounded_plain, shared.plain_directory


def module_configurations(server: Path, inventory_path: Path, compiled_path: Path, bots: dict,
                          main_templates: dict) -> tuple[dict, dict]:
    """Keep the original host source/binary selection validator before rendering."""
    try:
        from .package_server_content import validate_modules
    except ImportError:
        from package_server_content import validate_modules
    inventory_raw = bounded_plain(inventory_path.absolute(), 16 << 20)
    compiled_raw = bounded_plain(compiled_path.absolute(), 1 << 20)
    inventory, compiled = json.loads(inventory_raw), json.loads(compiled_raw)
    if inventory.get('formatVersion') != 1 or inventory.get('scope') != 'source-content-inventory' or \
            inventory.get('contentSha256Complete') is not True or \
            not re.fullmatch('[0-9a-f]{64}', inventory.get('sourceLockSha256', '')):
        raise ValueError('Source-verified content inventory required for module configuration')
    validate_modules(compiled, inventory)
    return shared._module_configurations(server, inventory, compiled,
        {'bytes': len(inventory_raw), 'sha256': hashlib.sha256(inventory_raw).hexdigest()},
        {'bytes': len(compiled_raw), 'sha256': hashlib.sha256(compiled_raw).hexdigest()}, bots, main_templates)


def render(server: Path, state: Path, data: Path, sql_source: Path, mysql_client: Path,
           *, module_inventory: Path | None = None, compiled_modules: Path | None = None) -> dict:
    if (module_inventory is None) != (compiled_modules is None):
        raise ValueError('Both source and compiled module selections are required')
    prepare = None
    if module_inventory is not None:
        prepare = lambda bots, main: module_configurations(server, module_inventory, compiled_modules, bots, main)
    return shared._render(server, state, data, sql_source, mysql_client,
                          profile=json.loads(PROFILE.read_text()), module_preparer=prepare)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True, type=Path)
    parser.add_argument('--state-root', required=True, type=Path)
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--sql-source', required=True, type=Path)
    parser.add_argument('--mysql-client', required=True, type=Path)
    parser.add_argument('--module-inventory', type=Path)
    parser.add_argument('--compiled-modules', type=Path)
    args = parser.parse_args()
    print(json.dumps(render(args.server, args.state_root, args.data_root, args.sql_source, args.mysql_client,
                           module_inventory=args.module_inventory, compiled_modules=args.compiled_modules), indent=2))


if __name__ == '__main__':
    main()
