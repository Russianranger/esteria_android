#!/usr/bin/env python3
"""Compare generated client descriptors to the pinned Esteria server source.

This establishes update-field layout only, not packet/runtime compatibility.
The server header's field sizes are checked against the next concrete offset;
this prevents relying on stale Size comments alone. No C++ expression is eval'd.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

FIELD_HEADER = Path('src/server/game/Entities/Object/Updates/UpdateFields.h')
ALIASES = {'PLAYER_FIELD_LIFETIME_HONORBALE_KILLS': 'PLAYER_FIELD_LIFETIME_HONORABLE_KILLS'}
APPROVED = {'build': 12340, 'quest_slots': 25, 'container_slots': 254,
            'max_class_id': 32, 'class_mask_words': 1, 'class_mask_bytes': 4,
            'quest_remove_slot_bytes': 1, 'item_cache_version': 5,
            'petition_cache_version': 1, 'character_restriction_trailer_bytes': 40}


def parse_fields(source: str) -> dict[str, dict]:
    values: dict[str, dict] = {}
    pattern = re.compile(r'^\s*([A-Z][A-Z0-9_]*)\s*=\s*([^,]+),\s*(?://(.*))?$')
    for line in source.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        name, expression, comment = match.groups()
        total = 0
        for part in expression.strip().split('+'):
            part = part.strip()
            if re.fullmatch(r'0x[0-9a-fA-F]+|[0-9]+', part):
                total += int(part, 0)
            elif part in values:
                total += values[part]['offset']
            else:
                raise ValueError(f'Unsupported server expression for {name}: {expression}')
        if name in values:
            raise ValueError(f'Duplicate server field: {name}')
        size = re.search(r'\bSize:\s*(\d+)', comment or '')
        values[name] = {'offset': total, 'count': int(size.group(1)) if size else None}
    if not values:
        raise ValueError('No server update fields found')
    return values


def verify(manifest: dict, source: str) -> dict:
    fields = parse_fields(source)
    problems = []
    for key, expected in APPROVED.items():
        if manifest.get(key) != expected:
            problems.append(f'{key}: expected {expected}, got {manifest.get(key)!r}')
    for key, field in [('active_player_dwords', 'PLAYER_END'),
                       ('container_dwords', 'CONTAINER_END'),
                       ('player_field_base_dword', 'UNIT_END')]:
        if manifest.get(key) != fields[field]['offset']:
            problems.append(f'{key}: client {manifest.get(key)}, server {fields[field]["offset"]}')
    slots = (fields['CONTAINER_END']['offset'] - fields['CONTAINER_FIELD_SLOT_1']['offset']) // 2
    if slots != manifest.get('container_slots'):
        problems.append(f'container slots: client {manifest.get("container_slots")}, server {slots}')
    if fields['CONTAINER_FIELD_SLOT_1']['count'] != slots * 2:
        problems.append('server container Size comment disagrees with numeric layout')
    server_players = {name: field for name, field in fields.items()
                      if name.startswith('PLAYER_') and name != 'PLAYER_END'}
    mapped = {}
    for client in manifest.get('player_fields', []):
        name = ALIASES.get(client['name'], client['name'])
        if name in mapped:
            problems.append(f'duplicate client descriptor: {name}')
        mapped[name] = client
        server = server_players.get(name)
        if server is None:
            problems.append(f'client-only field: {name}')
        elif (client.get('offset'), client.get('count')) != (server['offset'], server['count']):
            problems.append(f'{name}: client offset/size {client.get("offset")}/{client.get("count")}, '
                            f'server {server["offset"]}/{server["count"]}')
    for name in sorted(server_players.keys() - mapped.keys()):
        problems.append(f'missing client descriptor: {name}')
    ordered = sorted(server_players.items(), key=lambda pair: pair[1]['offset'])
    for index, (name, field) in enumerate(ordered):
        end = ordered[index + 1][1]['offset'] if index + 1 < len(ordered) else fields['PLAYER_END']['offset']
        if field['count'] != end - field['offset']:
            problems.append(f'{name}: server Size comment does not cover interval to next field')
    quest_names = [name for name in server_players if re.fullmatch(r'PLAYER_QUEST_LOG_\d+_1', name)]
    if len(quest_names) != manifest.get('quest_slots'):
        problems.append(f'quest slots: client {manifest.get("quest_slots")}, server {len(quest_names)}')
    needed_masks = (fields['PLAYER_END']['offset'] + 31) // 32
    if manifest.get('required_mask_dwords') != needed_masks:
        problems.append(f'update mask count: expected {needed_masks}')
    if problems:
        raise ValueError('\n'.join(problems))
    return {'status': 'passed', 'scope': 'update-field layout, not runtime protocol qualification',
            'build': manifest['build'], 'player_fields_checked': len(mapped),
            'active_player_dwords': fields['PLAYER_END']['offset'], 'required_mask_dwords': needed_masks,
            'container_dwords': fields['CONTAINER_END']['offset'], 'container_slots': slots,
            'quest_slots': len(quest_names), 'class_mask_words': manifest['class_mask_words']}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True, type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--client', type=Path, help='Generate approved 25/254/32 descriptors from this checkout')
    group.add_argument('--manifest', type=Path, help='Validate an actual build generated/limits/limits.json')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = args.manifest
            if args.client:
                subprocess.run([sys.executable, str(args.client.resolve() / 'Tools/gen_descriptors.py'),
                                '--quest-slots', '25', '--container-slots', '254', '--max-classes', '32',
                                '--output', temporary], check=True)
                manifest_path = Path(temporary) / 'limits.json'
            report = verify(json.loads(manifest_path.read_text()), (args.server / FIELD_HEADER).read_text())
        payload = json.dumps(report, indent=2) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload)
        print(payload, end='')
        return 0
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(f'Protocol validation failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
