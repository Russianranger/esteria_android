#!/usr/bin/env python3
"""Bounded-read offline data-format preflight for the pinned Esteria server.

This checks headers, declared lengths and known source-derived WDBC field layouts,
not gameplay completeness, combined file/SQL store coverage or client/server row equivalence. No downloads, extraction, repairs or writes to imported content.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import struct
from typing import Callable

SERVER_REVISION = 'f35f04d01689f034778e3474b3c820092f51e461'
BUILD = 12340
SERVER_NAMESPACE = 'EsteriaServerData'
SERVER_MANIFEST = 'manifest.properties'
SERVER_PACKAGE_SCOPE = 'esteria-user-supplied-server-data'
SERVER_DATA_GROUPS = ('dbc', 'dbc-continuations', 'maps', 'vmaps', 'mmaps', 'Cameras')
CONTINUATION = re.compile(r'([A-Za-z][A-Za-z0-9_]*)\.dbc([1-9])-([A-Za-z0-9_-]+)\Z')

# BEGIN GENERATED PINNED SERVER DBC LAYOUTS
# Derived by tools/generate_server_dbc_layouts.py; do not edit this block.
# Values: WDBC field count, on-disk row bytes, SQL overlay table.
# They are not decoded C++ structure sizes or mandatory file lists.
DBC_LAYOUT_SOURCE = {'serverPatches': [{'path': 'patches/server/0001-eluna-declare-area-trigger.patch',
                    'sha256': 'c26b145188c5f97bf30d032e1fe3bd7fe17aa1f8f0daa6793e51f5d830fe7aa6',
                    'submodule': 'src/server/game/LuaEngine'},
                   {'path': 'patches/server/0002-eluna-include-map-manager.patch',
                    'sha256': '4e277dbe56c31ae30640c8e9ad4dee12e944e0f051d9bdc8d62aaa239c50433f',
                    'submodule': 'src/server/game/LuaEngine'},
                   {'path': 'patches/server/0003-eluna-hooks-include-types.patch',
                    'sha256': '5999402d985fcc709abdc90bb4272072d1d5e3e261b2cc7ec19460320c14295f',
                    'submodule': 'src/server/game/LuaEngine'},
                   {'path': 'patches/server/0004-attunement-stat-api.patch',
                    'sha256': 'd9ef6ca8f96ab186c37c072b22143cdded9976aa3a62d083f893c502a5745cb8'},
                   {'path': 'patches/server/0005-script-grid-templates.patch',
                    'sha256': '6b459c90839e7831df8533966442fabd476ae1773f0302c50ccc8a997f157369'},
                   {'path': 'patches/server/0006-empty-script-modules.patch',
                    'sha256': 'ea0beb357c71d8b8c187af9d4afede520e7ac9877e40fbdc5fab99d54fc21f97'},
                   {'path': 'patches/server/0007-runtime-module-config-directory.patch',
                    'sha256': '5e41d474179ef553ec9c2544de947a3724885fd7f3ac233af3d89797acd032ff'}],
 'serverRevision': 'f35f04d01689f034778e3474b3c820092f51e461',
 'sourceFiles': {'modules/mod-wxl-dbc/src/WxlDbcRegistry.cpp': {'bytes': 8923,
                                                                'sha256': 'b36618468e76f57c95d63bd9690ad8a9f6fc251779242894b78de9a92261cef7'},
                 'src/common/DataStores/DBCFileLoader.cpp': {'bytes': 8974,
                                                             'sha256': '8c1996712c5d0e353c2bb7f75e0518c33b3975b0a15cb04da9dba2a581026fc3'},
                 'src/common/DataStores/DBCFileLoader.h': {'bytes': 4110,
                                                           'sha256': 'f6e25acda7a1e82f0911200e523137df04e0fc15f30012542b5fc22d28082aa5'},
                 'src/server/game/DataStores/DBCStores.cpp': {'bytes': 49298,
                                                              'sha256': 'd83093815f834c562fdd10d82bfb2748322415fad4924e21c33842f79c466168'},
                 'src/server/shared/DataStores/DBCStore.cpp': {'bytes': 2378,
                                                               'sha256': '63829b0b7e6b16f99327ab607625019fd891b747475ff97dd9bf91b64fd3cb1f'},
                 'src/server/shared/DataStores/DBCfmt.h': {'bytes': 8273,
                                                           'sha256': '9fbfb1f145d4db03d952311aa2bc05bb1c9496a980d2c42fe111c8b2d0d144a5'}}}
DBC_LAYOUTS = {'achievement.dbc': (62, 248, 'achievement_dbc'),
 'achievement_category.dbc': (20, 80, 'achievement_category_dbc'),
 'achievement_criteria.dbc': (31, 124, 'achievement_criteria_dbc'),
 'areagroup.dbc': (8, 32, 'areagroup_dbc'),
 'areapoi.dbc': (54, 216, 'areapoi_dbc'),
 'areatable.dbc': (36, 144, 'areatable_dbc'),
 'auctionhouse.dbc': (21, 84, 'auctionhouse_dbc'),
 'bankbagslotprices.dbc': (2, 8, 'bankbagslotprices_dbc'),
 'barbershopstyle.dbc': (40, 160, 'barbershopstyle_dbc'),
 'battlemasterlist.dbc': (32, 128, 'battlemasterlist_dbc'),
 'charsections.dbc': (10, 40, 'charsections_dbc'),
 'charstartoutfit.dbc': (77, 296, 'charstartoutfit_dbc'),
 'chartitles.dbc': (37, 148, 'chartitles_dbc'),
 'chatchannels.dbc': (37, 148, 'chatchannels_dbc'),
 'chrclasses.dbc': (60, 240, 'chrclasses_dbc'),
 'chrraces.dbc': (69, 276, 'chrraces_dbc'),
 'cinematiccamera.dbc': (7, 28, 'cinematiccamera_dbc'),
 'cinematicsequences.dbc': (10, 40, 'cinematicsequences_dbc'),
 'creaturedisplayinfo.dbc': (16, 64, 'creaturedisplayinfo_dbc'),
 'creaturedisplayinfoextra.dbc': (21, 84, 'creaturedisplayinfoextra_dbc'),
 'creaturefamily.dbc': (28, 112, 'creaturefamily_dbc'),
 'creaturemodeldata.dbc': (28, 112, 'creaturemodeldata_dbc'),
 'creaturespelldata.dbc': (9, 36, 'creaturespelldata_dbc'),
 'creaturetype.dbc': (19, 76, 'creaturetype_dbc'),
 'currencytypes.dbc': (4, 16, 'currencytypes_dbc'),
 'destructiblemodeldata.dbc': (19, 76, 'destructiblemodeldata_dbc'),
 'dungeonencounter.dbc': (23, 92, 'dungeonencounter_dbc'),
 'durabilitycosts.dbc': (30, 120, 'durabilitycosts_dbc'),
 'durabilityquality.dbc': (2, 8, 'durabilityquality_dbc'),
 'emotes.dbc': (7, 28, 'emotes_dbc'),
 'emotestext.dbc': (19, 76, 'emotestext_dbc'),
 'emotestextsound.dbc': (5, 20, 'emotetextsound_dbc'),
 'faction.dbc': (57, 228, 'faction_dbc'),
 'factiontemplate.dbc': (14, 56, 'factiontemplate_dbc'),
 'gameobjectartkit.dbc': (8, 32, 'gameobjectartkit_dbc'),
 'gameobjectdisplayinfo.dbc': (19, 76, 'gameobjectdisplayinfo_dbc'),
 'gemproperties.dbc': (5, 20, 'gemproperties_dbc'),
 'glyphproperties.dbc': (4, 16, 'glyphproperties_dbc'),
 'glyphslot.dbc': (3, 12, 'glyphslot_dbc'),
 'gtbarbershopcostbase.dbc': (2, 8, 'gtbarbershopcostbase_dbc'),
 'gtchancetomeleecrit.dbc': (2, 8, 'gtchancetomeleecrit_dbc'),
 'gtchancetomeleecritbase.dbc': (2, 8, 'gtchancetomeleecritbase_dbc'),
 'gtchancetospellcrit.dbc': (2, 8, 'gtchancetospellcrit_dbc'),
 'gtchancetospellcritbase.dbc': (2, 8, 'gtchancetospellcritbase_dbc'),
 'gtcombatratings.dbc': (2, 8, 'gtcombatratings_dbc'),
 'gtnpcmanacostscaler.dbc': (2, 8, 'gtnpcmanacostscaler_dbc'),
 'gtoctclasscombatratingscalar.dbc': (2, 8, 'gtoctclasscombatratingscalar_dbc'),
 'gtoctregenhp.dbc': (2, 8, 'gtoctregenhp_dbc'),
 'gtregenhpperspt.dbc': (2, 8, 'gtregenhpperspt_dbc'),
 'gtregenmpperspt.dbc': (2, 8, 'gtregenmpperspt_dbc'),
 'holidays.dbc': (55, 220, 'holidays_dbc'),
 'item.dbc': (8, 32, 'item_dbc'),
 'itembagfamily.dbc': (18, 72, 'itembagfamily_dbc'),
 'itemdisplayinfo.dbc': (25, 100, 'itemdisplayinfo_dbc'),
 'itemextendedcost.dbc': (16, 64, 'itemextendedcost_dbc'),
 'itemlimitcategory.dbc': (20, 80, 'itemlimitcategory_dbc'),
 'itemrandomproperties.dbc': (24, 96, 'itemrandomproperties_dbc'),
 'itemrandomsuffix.dbc': (29, 116, 'itemrandomsuffix_dbc'),
 'itemset.dbc': (53, 212, 'itemset_dbc'),
 'lfgdungeons.dbc': (49, 196, 'lfgdungeons_dbc'),
 'light.dbc': (15, 60, 'light_dbc'),
 'liquidtype.dbc': (45, 180, 'liquidtype_dbc'),
 'lock.dbc': (33, 132, 'lock_dbc'),
 'mailtemplate.dbc': (35, 140, 'mailtemplate_dbc'),
 'map.dbc': (66, 264, 'map_dbc'),
 'mapdifficulty.dbc': (23, 92, 'mapdifficulty_dbc'),
 'movie.dbc': (3, 12, 'movie_dbc'),
 'namesprofanity.dbc': (3, 12, 'namesprofanity_dbc'),
 'namesreserved.dbc': (3, 12, 'namesreserved_dbc'),
 'overridespelldata.dbc': (12, 48, 'overridespelldata_dbc'),
 'powerdisplay.dbc': (6, 24, 'powerdisplay_dbc'),
 'pvpdifficulty.dbc': (6, 24, 'pvpdifficulty_dbc'),
 'questfactionreward.dbc': (11, 44, 'questfactionreward_dbc'),
 'questsort.dbc': (18, 72, 'questsort_dbc'),
 'questxp.dbc': (11, 44, 'questxp_dbc'),
 'randproppoints.dbc': (16, 64, 'randproppoints_dbc'),
 'scalingstatdistribution.dbc': (22, 88, 'scalingstatdistribution_dbc'),
 'scalingstatvalues.dbc': (24, 96, 'scalingstatvalues_dbc'),
 'skillline.dbc': (56, 224, 'skillline_dbc'),
 'skilllineability.dbc': (14, 56, 'skilllineability_dbc'),
 'skillraceclassinfo.dbc': (8, 32, 'skillraceclassinfo_dbc'),
 'skilltiers.dbc': (33, 132, 'skilltiers_dbc'),
 'soundentries.dbc': (30, 120, 'soundentries_dbc'),
 'spell.dbc': (234, 936, 'spell_dbc'),
 'spellcasttimes.dbc': (4, 16, 'spellcasttimes_dbc'),
 'spellcategory.dbc': (2, 8, 'spellcategory_dbc'),
 'spelldifficulty.dbc': (5, 20, 'spelldifficulty_dbc'),
 'spellduration.dbc': (4, 16, 'spellduration_dbc'),
 'spellfocusobject.dbc': (18, 72, 'spellfocusobject_dbc'),
 'spellitemenchantment.dbc': (38, 152, 'spellitemenchantment_dbc'),
 'spellitemenchantmentcondition.dbc': (31, 64, 'spellitemenchantmentcondition_dbc'),
 'spellradius.dbc': (4, 16, 'spellradius_dbc'),
 'spellrange.dbc': (40, 160, 'spellrange_dbc'),
 'spellrunecost.dbc': (5, 20, 'spellrunecost_dbc'),
 'spellshapeshiftform.dbc': (35, 140, 'spellshapeshiftform_dbc'),
 'spellvisual.dbc': (32, 128, 'spellvisual_dbc'),
 'stableslotprices.dbc': (2, 8, 'stableslotprices_dbc'),
 'summonproperties.dbc': (6, 24, 'summonproperties_dbc'),
 'talent.dbc': (23, 92, 'talent_dbc'),
 'talenttab.dbc': (24, 96, 'talenttab_dbc'),
 'taxinodes.dbc': (24, 96, 'taxinodes_dbc'),
 'taxipath.dbc': (4, 16, 'taxipath_dbc'),
 'taxipathnode.dbc': (11, 44, 'taxipathnode_dbc'),
 'teamcontributionpoints.dbc': (2, 8, 'teamcontributionpoints_dbc'),
 'totemcategory.dbc': (20, 80, 'totemcategory_dbc'),
 'transportanimation.dbc': (7, 28, 'transportanimation_dbc'),
 'transportrotation.dbc': (7, 28, 'transportrotation_dbc'),
 'vehicle.dbc': (40, 160, 'vehicle_dbc'),
 'vehicleseat.dbc': (58, 232, 'vehicleseat_dbc'),
 'wmoareatable.dbc': (28, 112, 'wmoareatable_dbc'),
 'worldmaparea.dbc': (11, 44, 'worldmaparea_dbc'),
 'worldmapoverlay.dbc': (17, 68, 'worldmapoverlay_dbc')}
DBC_CONTINUATION_STORES = ('achievement.dbc',
 'achievement_category.dbc',
 'achievement_criteria.dbc',
 'areagroup.dbc',
 'areapoi.dbc',
 'areatable.dbc',
 'auctionhouse.dbc',
 'bankbagslotprices.dbc',
 'barbershopstyle.dbc',
 'battlemasterlist.dbc',
 'charsections.dbc',
 'charstartoutfit.dbc',
 'chartitles.dbc',
 'chatchannels.dbc',
 'chrclasses.dbc',
 'chrraces.dbc',
 'cinematiccamera.dbc',
 'cinematicsequences.dbc',
 'creaturedisplayinfo.dbc',
 'creaturedisplayinfoextra.dbc',
 'creaturefamily.dbc',
 'creaturemodeldata.dbc',
 'creaturespelldata.dbc',
 'creaturetype.dbc',
 'currencytypes.dbc',
 'destructiblemodeldata.dbc',
 'dungeonencounter.dbc',
 'durabilitycosts.dbc',
 'durabilityquality.dbc',
 'emotes.dbc',
 'emotestext.dbc',
 'emotestextsound.dbc',
 'faction.dbc',
 'factiontemplate.dbc',
 'gameobjectartkit.dbc',
 'gameobjectdisplayinfo.dbc',
 'gemproperties.dbc',
 'glyphproperties.dbc',
 'glyphslot.dbc',
 'gtbarbershopcostbase.dbc',
 'gtchancetomeleecrit.dbc',
 'gtchancetomeleecritbase.dbc',
 'gtchancetospellcrit.dbc',
 'gtchancetospellcritbase.dbc',
 'gtcombatratings.dbc',
 'gtnpcmanacostscaler.dbc',
 'gtoctclasscombatratingscalar.dbc',
 'gtoctregenhp.dbc',
 'gtregenhpperspt.dbc',
 'gtregenmpperspt.dbc',
 'holidays.dbc',
 'item.dbc',
 'itembagfamily.dbc',
 'itemdisplayinfo.dbc',
 'itemextendedcost.dbc',
 'itemlimitcategory.dbc',
 'itemrandomproperties.dbc',
 'itemrandomsuffix.dbc',
 'itemset.dbc',
 'lfgdungeons.dbc',
 'light.dbc',
 'liquidtype.dbc',
 'lock.dbc',
 'mailtemplate.dbc',
 'map.dbc',
 'mapdifficulty.dbc',
 'movie.dbc',
 'namesprofanity.dbc',
 'namesreserved.dbc',
 'overridespelldata.dbc',
 'powerdisplay.dbc',
 'pvpdifficulty.dbc',
 'questfactionreward.dbc',
 'questsort.dbc',
 'questxp.dbc',
 'randproppoints.dbc',
 'scalingstatdistribution.dbc',
 'scalingstatvalues.dbc',
 'skillline.dbc',
 'skilllineability.dbc',
 'skillraceclassinfo.dbc',
 'skilltiers.dbc',
 'soundentries.dbc',
 'spell.dbc',
 'spellcasttimes.dbc',
 'spellcategory.dbc',
 'spelldifficulty.dbc',
 'spellduration.dbc',
 'spellfocusobject.dbc',
 'spellitemenchantment.dbc',
 'spellitemenchantmentcondition.dbc',
 'spellradius.dbc',
 'spellrange.dbc',
 'spellrunecost.dbc',
 'spellshapeshiftform.dbc',
 'spellvisual.dbc',
 'stableslotprices.dbc',
 'summonproperties.dbc',
 'talent.dbc',
 'talenttab.dbc',
 'taxinodes.dbc',
 'taxipath.dbc',
 'teamcontributionpoints.dbc',
 'totemcategory.dbc',
 'transportanimation.dbc',
 'transportrotation.dbc',
 'vehicle.dbc',
 'vehicleseat.dbc',
 'wmoareatable.dbc',
 'worldmaparea.dbc',
 'worldmapoverlay.dbc')
# END GENERATED PINNED SERVER DBC LAYOUTS


def parse_server_manifest(raw: bytes) -> dict:
    """A package's declared source is not proof of its producer or coverage."""
    if not 0 < len(raw) <= 2048 or not raw.endswith(b'\n'):
        raise ValueError('bounded newline-terminated matched server manifest required')
    text = raw.decode('ascii')
    if '\r' in text.replace('\r\n', '\n') or any(ord(c) < 32 and c not in '\r\n' for c in text):
        raise ValueError('control character in matched server manifest')
    result = {}
    for line in text.splitlines():
        key, separator, value = line.partition('=')
        if not separator or not key or not value or key in result or any(ord(c) < 32 or ord(c) > 126 or c == '\\' for c in line):
            raise ValueError('invalid or duplicate matched server manifest field')
        result[key] = value
    if set(result) != {'format', 'scope', 'serverRevision', 'clientBuild', 'mode', 'provenance', 'clientProviderOrderSha256'} or \
            result['format'] != '1' or result['scope'] != SERVER_PACKAGE_SCOPE or \
            result['serverRevision'] != SERVER_REVISION or result['clientBuild'] != str(BUILD) or \
            result['mode'] not in ('complete', 'overlay') or result['provenance'] != 'user-supplied-format-checked' or \
            (result['clientProviderOrderSha256'] != 'none' and not re.fullmatch('[0-9a-f]{64}', result['clientProviderOrderSha256'])):
        raise ValueError('matched server manifest source, mode or provenance differs')
    return result


def data_file_checker(group: str, path: Path):
    suffix, name = path.suffix.lower(), path.name.lower()
    if group == 'dbc':
        if name.endswith('.dbc'): return check_dbc
        if re.fullmatch(r'component\.wow-[A-Za-z]{4}\.txt', path.name): return None
    elif group == 'dbc-continuations':
        if CONTINUATION.fullmatch(path.name): return check_dbc
        if path.name == 'wxl-dbc.manifest': return None
    elif group == 'maps' and suffix == '.map': return check_map
    elif group == 'vmaps' and (suffix in ('.vmtree', '.vmtile', '.vmo') or name == 'gameobjectmodels.dtree'): return check_vmap
    elif group == 'mmaps':
        if suffix == '.mmtile': return check_mmtile
        if suffix == '.mmap': return check_mmap
    elif group == 'Cameras' and suffix == '.m2': return check_camera
    raise ValueError('unrecognized matched server data file: ' + str(path))


def continuation_order(root: Path, base: Path) -> dict:
    """Mirror pinned WxlDbcScan ordering; refuse ambiguous or escaping input.

    Source sorts tier, explicit manifest position, project and base-table name.
    Unordered-map ties have no stable source order and need explicit manifest
    positions. No rows are merged or fabricated by this preflight.
    """
    entries = {}; manifest_positions = {}; base_headers = {}
    if base.is_dir():
        for path in files_bounded(base):
            if path.name.lower().endswith('.dbc'):
                check_dbc(path); header, _ = read_header(path, 20)
                signature = struct.unpack('<4s4I', header)[2:4]
                key = path.name.lower()
                if key in base_headers and base_headers[key] != signature:
                    raise ValueError('locale/base DBC field layout disagrees: ' + path.name)
                base_headers[key] = signature
    for path in files_bounded(root):
        relative = path.relative_to(root).as_posix()
        if path.name == 'wxl-dbc.manifest':
            if relative != 'wxl-dbc.manifest': raise ValueError('continuation manifest must be at the continuation root')
            continue
        matched = CONTINUATION.fullmatch(path.name)
        if not matched: raise ValueError('unrecognized continuation filename: ' + relative)
        check_dbc(path); header, _ = read_header(path, 20)
        signature = struct.unpack('<4s4I', header)[2:4]
        table, tier, project = matched.groups(); base_name = table + '.dbc'
        if base_name.lower() in base_headers and base_headers[base_name.lower()] != signature:
            raise ValueError('continuation field count or record size differs from base: ' + relative)
        entries[relative] = (int(tier), project.lower(), base_name.lower())
    manifest = root / 'wxl-dbc.manifest'
    if manifest.exists() or manifest.is_symlink():
        if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 1024*1024:
            raise ValueError('bounded regular continuation manifest required')
        with manifest.open('r', encoding='ascii', newline='') as stream:
            manifest_text = stream.read(1024*1024+1)
        if len(manifest_text) > 1024*1024: raise ValueError('continuation manifest grew beyond bound')
        if any(ord(c) > 126 or ord(c) < 32 and c not in '\n\r\t' for c in manifest_text):
            raise ValueError('continuation manifest requires ASCII without other control characters')
        position = 0
        for line in manifest_text.split('\n'):
            line = line.rstrip(' \t\r').lstrip(' \t')
            if not line or line.startswith('#'): continue
            if line.startswith('/') or '\\' in line or ':' in line or any(p in ('', '.', '..') for p in line.split('/')) or \
                    any(ord(c) < 32 or ord(c) > 126 for c in line) or line not in entries:
                raise ValueError('continuation manifest references an unsafe or absent file')
            if line not in manifest_positions: manifest_positions[line] = position
            position += 1
    keys = {}
    for name, (tier, project, table) in entries.items():
        key = (tier, manifest_positions.get(name, 0x7fffffff), project, table)
        if key in keys: raise ValueError('ambiguous continuation order; list both files in wxl-dbc.manifest')
        keys[key] = name
    return {'files_checked': len(entries), 'order': [keys[key] for key in sorted(keys)],
            'ordering': 'tier-then-manifest-position-then-project-then-base-table',
            'base_field_layouts_checked': len(base_headers), 'rows_merged': False}


def check_server_package(root: Path, selected: dict) -> dict:
    """Validate all supplied files, including the server's separate DBC folder."""
    if root.is_symlink() or not root.is_dir(): raise ValueError('matched server data root required')
    allowed = SERVER_DATA_GROUPS if selected['mode'] == 'complete' else ('dbc', 'dbc-continuations')
    groups = {}; recognized = 0
    for child in root.iterdir():
        if child.name not in allowed or child.is_symlink() or not child.is_dir():
            raise ValueError('unsupported matched server data group: ' + child.name)
        checked = 0
        for path in files_bounded(child):
            if not path.is_file(): raise ValueError('regular matched server file required')
            checker = data_file_checker(child.name, path)
            if checker: checker(path); checked += 1
            elif path.stat().st_size > (1024*1024 if path.name == 'wxl-dbc.manifest' else 65536):
                raise ValueError('matched server ancillary file exceeds bound')
        groups[child.name] = checked; recognized += checked
    if not recognized: raise ValueError('matched server package contains no recognized data')
    if selected['mode'] == 'complete' and not all(groups.get(name, 0) > 0 for name in ('dbc', 'maps', 'vmaps', 'mmaps', 'Cameras')):
        raise ValueError('complete matched server package requires all five data groups')
    if 'dbc-continuations' in groups: continuation_order(root / 'dbc-continuations', root / 'dbc')
    return {'groups': groups, 'provenance': 'user-supplied-format-checked', 'worldQualified': False}


def read_header(path: Path, size: int) -> tuple[bytes, int]:
    if path.is_symlink() or not path.is_file():
        raise ValueError('regular file required; symbolic links are unsupported')
    with path.open('rb') as stream:
        total = os.fstat(stream.fileno()).st_size
        header = stream.read(size)
    if len(header) != size:
        raise ValueError(f'truncated header: need {size} bytes, got {len(header)}')
    return header, total


def check_dbc(path: Path) -> None:
    header, size = read_header(path, 20)
    magic, rows, fields, stride, strings = struct.unpack('<4s4I', header)
    if magic != b'WDBC' or not fields or not stride:
        raise ValueError('expected WDBC header with nonzero field count and row stride')
    expected = 20 + rows * stride + strings
    if size != expected:
        raise ValueError(f'DBC declared length {expected} differs from file length {size}')
    # The native loader uses its format to compute offsets, including packed
    # byte columns. A self-consistent WDBC length alone can still describe an
    # incompatible or unsafe row layout. Locales/continuations use the same
    # base store format. Unknown tables remain structural-only; no unknown
    # custom schema or SQL-backed missing-file requirement is invented.
    base_name = re.sub(r'\.dbc[1-9]-[A-Za-z0-9_-]+$', '.dbc', path.name, flags=re.I)
    layout = DBC_LAYOUTS.get(base_name.casefold())
    if layout is not None and (fields, stride) != layout[:2]:
        raise ValueError(f'pinned server DBC layout expects {layout[0]} fields and {layout[1]} record bytes, '
                         f'got {fields}/{stride}')


def check_map(path: Path) -> None:
    header, size = read_header(path, 44)
    magic, version, build, *chunks = struct.unpack('<4s10I', header)
    if magic != b'MAPS' or version != 9 or build != BUILD:
        raise ValueError(f'expected MAPS version 9 build {BUILD}, got {magic!r}/{version}/{build}')
    ranges = []
    for offset, length in zip(chunks[::2], chunks[1::2]):
        if length:
            if offset < 44 or offset + length > size:
                raise ValueError('map chunk lies outside the file')
            ranges.append((offset, offset + length))
    ranges.sort()
    if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
        raise ValueError('map chunks overlap')


def check_vmap(path: Path) -> None:
    header, _ = read_header(path, 8)
    if header != b'VMAP_4.8':
        raise ValueError(f'expected assembled VMAP_4.8, got {header!r}')


def check_mmtile(path: Path) -> None:
    header, size = read_header(path, 56)
    magic, detour, version, payload = struct.unpack_from('<4I', header)
    if (magic, detour, version) != (0x4D4D4150, 7, 20):
        raise ValueError('expected MMAP magic, Detour version 7, mmap version 20')
    if not payload or payload != size - 56:
        raise ValueError('mmap tile payload length does not match its 56-byte header')


def check_mmap(path: Path) -> None:
    _, size = read_header(path, 28)
    if size != 28:
        raise ValueError('expected 28-byte dtNavMeshParams for a map index')


def check_camera(path: Path) -> None:
    header, _ = read_header(path, 8)
    if header[:4] != b'MD20':
        raise ValueError('expected legacy MD20 camera model')


def files_bounded(root: Path):
    """Walk names only. No content hashing and no symlink traversal."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError('required directory missing or is a symbolic link')
    def failed(error):
        raise error
    count = 0
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed):
        if len(Path(directory).relative_to(root).parts) > 16:
            raise ValueError('server data directory depth exceeds bound')
        seen = set()
        for name in dirs + files:
            count += 1
            if count > 300000:
                raise ValueError('server data entry count exceeds bound')
            folded = name.casefold()
            if folded in seen:
                raise ValueError(f'case-colliding names under {Path(directory).relative_to(root)}')
            seen.add(folded)
            if (Path(directory) / name).is_symlink():
                raise ValueError(f'symbolic link found: {(Path(directory) / name).relative_to(root)}')
        for name in files:
            yield Path(directory) / name


def check_server_data(root: Path) -> dict:
    # dbcN-project continuation files use the same WDBC format, not just *.dbc.
    groups: dict[str, Callable[[Path], Callable | None]] = {
        'dbc': lambda p: check_dbc if re.search(r'\.dbc(?:[1-9]-[^/]+)?$', p.name, re.I) else None,
        'maps': lambda p: check_map if p.suffix.lower() == '.map' else None,
        'vmaps': lambda p: check_vmap if p.suffix.lower() in ('.vmtree', '.vmtile', '.vmo')
        or p.name.lower() == 'gameobjectmodels.dtree' else None,
        'mmaps': lambda p: check_mmtile if p.suffix.lower() == '.mmtile'
        else check_mmap if p.suffix.lower() == '.mmap' else None,
        'Cameras': lambda p: check_camera if p.suffix.lower() == '.m2' else None,
    }
    report = {'server_revision': SERVER_REVISION, 'expected_client_build': BUILD,
              'validation': 'file headers and declared lengths only', 'groups': {},
              'error_count': 0, 'errors': []}

    def error(path, message):
        report['error_count'] += 1
        # A damaged archive can produce many thousands of files; keep reports bounded.
        if len(report['errors']) < 100:
            report['errors'].append({'path': str(path), 'error': str(message)})
    for name, classifier in groups.items():
        checked = 0
        try:
            for path in files_bounded(root / name):
                checker = classifier(path)
                if checker:
                    checked += 1
                    try:
                        checker(path)
                    except (ValueError, OSError) as failure:
                        error(path.relative_to(root), failure)
            if not checked:
                error(name, 'no recognized data files')
        except (ValueError, OSError) as failure:
            error(name, failure)
        report['groups'][name] = {'files_checked': checked}
    if (root / 'dbc-continuations').exists() or (root / 'dbc-continuations').is_symlink():
        try:
            report['continuations'] = continuation_order(root / 'dbc-continuations', root / 'dbc')
        except (ValueError, OSError) as failure:
            error('dbc-continuations', failure)
    report['checks_passed'] = report['error_count'] == 0
    report['gameplay_qualified'] = False
    report['limitations'] = ['Does not establish map coverage, DBC schema/row compatibility or custom asset closure.',
                             'Cameras and VMAP checks verify magic only; payload parsing remains the server loader gate.',
                             'Use extractors from the pinned server against the same effective client MPQ stack.',
                             'Run again after content changes; the importer owns the resumable copy/hash journal.']
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-data', type=Path, required=True)
    args = parser.parse_args(argv)
    report = check_server_data(args.server_data)
    print(json.dumps(report, indent=2))
    return 0 if report['checks_passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
