#!/usr/bin/env python3
"""Inspect a completed stock import using the verified reconstructed-client reader.

This is bounded preparation-time data validation. It neither authenticates Blizzard
signatures nor claims graphical/world execution; the unchanged client does those
checks at normal startup. No original data is edited and no archive is downloaded.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import posixpath
import re
import stat
import struct
import sys

try:
    from . import shader_generation as storage, extractor_order as order, world_io
except ImportError:
    import shader_generation as storage
    import extractor_order as order
    import world_io

CLIENT_REVISION = '471ee42faadf4a97a1d0a86989cf1452621f2dc5'
PROFILE = 'stock-3.3.5a'
MAX_METADATA = 64 << 20
MAX_MEMBERS = 150000
MAX_TABLE_ENTRIES = 2 << 20
MAX_UI_FILES = 8192
MAX_UI_BYTES = 64 << 20
CATALOG_MARKER = re.compile(r'^esteria/esteria[^/]*\.bin$', re.I)
SENTINELS = {'AreaTable.dbc': 4987, 'CharTitles.dbc': 177, 'GemProperties.dbc': 1629,
             'Item.dbc': 56806, 'ItemExtendedCost.dbc': 2997, 'Map.dbc': 724, 'Spell.dbc': 80864,
             'ChrRaces.dbc': 1, 'ChrClasses.dbc': 1}

# BEGIN GENERATED PINNED CLIENT DBC LAYOUTS
CLIENT_DBC_LAYOUT_SOURCE = {'clientRevision': '471ee42faadf4a97a1d0a86989cf1452621f2dc5', 'fileCount': 479, 'storeCount': 238}
CLIENT_DBC_LAYOUT_SOURCE_SHA256 = '46e7144f28daf3eccbf9254d92d23a93af8dae001723f314c254ec615be0ee92'
CLIENT_DBC_LAYOUTS = {'DBFilesClient\\Achievement.dbc': (62, 248), 'DBFilesClient\\Achievement_Category.dbc': (20, 80), 'DBFilesClient\\Achievement_Criteria.dbc': (31, 124), 'DBFilesClient\\AnimationData.dbc': (8, 32), 'DBFilesClient\\AreaGroup.dbc': (8, 32), 'DBFilesClient\\AreaPOI.dbc': (54, 216), 'DBFilesClient\\AreaTable.dbc': (36, 144), 'DBFilesClient\\AreaTrigger.dbc': (10, 40), 'DBFilesClient\\AttackAnimKits.dbc': (5, 20), 'DBFilesClient\\AttackAnimTypes.dbc': (2, 8), 'DBFilesClient\\AuctionHouse.dbc': (21, 84), 'DBFilesClient\\BankBagSlotPrices.dbc': (2, 8), 'DBFilesClient\\BannedAddOns.dbc': (11, 44), 'DBFilesClient\\BarberShopStyle.dbc': (40, 160), 'DBFilesClient\\BattlemasterList.dbc': (32, 128), 'DBFilesClient\\CameraShakes.dbc': (8, 32), 'DBFilesClient\\Cfg_Categories.dbc': (21, 84), 'DBFilesClient\\Cfg_Configs.dbc': (4, 16), 'DBFilesClient\\CharBaseInfo.dbc': (2, 2), 'DBFilesClient\\CharHairGeosets.dbc': (6, 24), 'DBFilesClient\\CharSections.dbc': (10, 40), 'DBFilesClient\\CharStartOutfit.dbc': (77, 296), 'DBFilesClient\\CharTitles.dbc': (37, 148), 'DBFilesClient\\CharacterFacialHairStyles.dbc': (8, 32), 'DBFilesClient\\ChatChannels.dbc': (37, 148), 'DBFilesClient\\ChatProfanity.dbc': (3, 12), 'DBFilesClient\\ChrClasses.dbc': (60, 240), 'DBFilesClient\\ChrRaces.dbc': (69, 276), 'DBFilesClient\\CinematicCamera.dbc': (7, 28), 'DBFilesClient\\CinematicSequences.dbc': (10, 40), 'DBFilesClient\\CreatureDisplayInfo.dbc': (16, 64), 'DBFilesClient\\CreatureDisplayInfoExtra.dbc': (21, 84), 'DBFilesClient\\CreatureFamily.dbc': (28, 112), 'DBFilesClient\\CreatureModelData.dbc': (28, 112), 'DBFilesClient\\CreatureMovementInfo.dbc': (2, 8), 'DBFilesClient\\CreatureSoundData.dbc': (38, 152), 'DBFilesClient\\CreatureSpellData.dbc': (9, 36), 'DBFilesClient\\CreatureType.dbc': (19, 76), 'DBFilesClient\\CurrencyCategory.dbc': (19, 76), 'DBFilesClient\\CurrencyTypes.dbc': (4, 16), 'DBFilesClient\\DanceMoves.dbc': (24, 96), 'DBFilesClient\\DeathThudLookups.dbc': (5, 20), 'DBFilesClient\\DestructibleModelData.dbc': (19, 76), 'DBFilesClient\\DungeonEncounter.dbc': (23, 92), 'DBFilesClient\\DungeonMap.dbc': (8, 32), 'DBFilesClient\\DungeonMapChunk.dbc': (5, 20), 'DBFilesClient\\DurabilityCosts.dbc': (30, 120), 'DBFilesClient\\DurabilityQuality.dbc': (2, 8), 'DBFilesClient\\Emotes.dbc': (7, 28), 'DBFilesClient\\EmotesText.dbc': (19, 76), 'DBFilesClient\\EmotesTextData.dbc': (18, 72), 'DBFilesClient\\EmotesTextSound.dbc': (5, 20), 'DBFilesClient\\EnvironmentalDamage.dbc': (3, 12), 'DBFilesClient\\Exhaustion.dbc': (23, 92), 'DBFilesClient\\Faction.dbc': (57, 228), 'DBFilesClient\\FactionGroup.dbc': (20, 80), 'DBFilesClient\\FactionTemplate.dbc': (14, 56), 'DBFilesClient\\FileData.dbc': (3, 12), 'DBFilesClient\\FootprintTextures.dbc': (2, 8), 'DBFilesClient\\FootstepTerrainLookup.dbc': (5, 20), 'DBFilesClient\\GMSurveyAnswers.dbc': (20, 80), 'DBFilesClient\\GMSurveyCurrentSurvey.dbc': (2, 8), 'DBFilesClient\\GMSurveyQuestions.dbc': (18, 72), 'DBFilesClient\\GMSurveySurveys.dbc': (11, 44), 'DBFilesClient\\GMTicketCategory.dbc': (18, 72), 'DBFilesClient\\GameObjectArtKit.dbc': (8, 32), 'DBFilesClient\\GameObjectDisplayInfo.dbc': (19, 76), 'DBFilesClient\\GameTables.dbc': (3, 12), 'DBFilesClient\\GameTips.dbc': (18, 72), 'DBFilesClient\\GemProperties.dbc': (5, 20), 'DBFilesClient\\GlyphProperties.dbc': (4, 16), 'DBFilesClient\\GlyphSlot.dbc': (3, 12), 'DBFilesClient\\GroundEffectDoodad.dbc': (3, 12), 'DBFilesClient\\GroundEffectTexture.dbc': (11, 44), 'DBFilesClient\\HelmetGeosetVisData.dbc': (8, 32), 'DBFilesClient\\HolidayDescriptions.dbc': (18, 72), 'DBFilesClient\\HolidayNames.dbc': (18, 72), 'DBFilesClient\\Holidays.dbc': (55, 220), 'DBFilesClient\\Item.dbc': (8, 32), 'DBFilesClient\\ItemBagFamily.dbc': (18, 72), 'DBFilesClient\\ItemClass.dbc': (20, 80), 'DBFilesClient\\ItemCondExtCosts.dbc': (4, 16), 'DBFilesClient\\ItemDisplayInfo.dbc': (25, 100), 'DBFilesClient\\ItemExtendedCost.dbc': (16, 64), 'DBFilesClient\\ItemGroupSounds.dbc': (5, 20), 'DBFilesClient\\ItemLimitCategory.dbc': (20, 80), 'DBFilesClient\\ItemPetFood.dbc': (18, 72), 'DBFilesClient\\ItemPurchaseGroup.dbc': (26, 104), 'DBFilesClient\\ItemRandomProperties.dbc': (24, 96), 'DBFilesClient\\ItemRandomSuffix.dbc': (29, 116), 'DBFilesClient\\ItemSet.dbc': (53, 212), 'DBFilesClient\\ItemSubClass.dbc': (44, 176), 'DBFilesClient\\ItemSubClassMask.dbc': (19, 76), 'DBFilesClient\\ItemVisualEffects.dbc': (2, 8), 'DBFilesClient\\ItemVisuals.dbc': (6, 24), 'DBFilesClient\\LanguageWords.dbc': (3, 12), 'DBFilesClient\\Languages.dbc': (18, 72), 'DBFilesClient\\LfgDungeonExpansion.dbc': (8, 32), 'DBFilesClient\\LfgDungeonGroup.dbc': (21, 84), 'DBFilesClient\\LfgDungeons.dbc': (49, 196), 'DBFilesClient\\Light.dbc': (15, 60), 'DBFilesClient\\LightFloatBand.dbc': (34, 136), 'DBFilesClient\\LightIntBand.dbc': (34, 136), 'DBFilesClient\\LightParams.dbc': (9, 36), 'DBFilesClient\\LightSkybox.dbc': (3, 12), 'DBFilesClient\\LiquidMaterial.dbc': (3, 12), 'DBFilesClient\\LiquidType.dbc': (45, 180), 'DBFilesClient\\LoadingScreenTaxiSplines.dbc': (19, 76), 'DBFilesClient\\LoadingScreens.dbc': (4, 16), 'DBFilesClient\\Lock.dbc': (33, 132), 'DBFilesClient\\LockType.dbc': (53, 212), 'DBFilesClient\\MailTemplate.dbc': (35, 140), 'DBFilesClient\\Map.dbc': (66, 264), 'DBFilesClient\\MapDifficulty.dbc': (23, 92), 'DBFilesClient\\Material.dbc': (5, 20), 'DBFilesClient\\Movie.dbc': (3, 12), 'DBFilesClient\\MovieFileData.dbc': (2, 8), 'DBFilesClient\\MovieVariation.dbc': (3, 12), 'DBFilesClient\\NPCSounds.dbc': (5, 20), 'DBFilesClient\\NameGen.dbc': (4, 16), 'DBFilesClient\\NamesProfanity.dbc': (3, 12), 'DBFilesClient\\NamesReserved.dbc': (3, 12), 'DBFilesClient\\ObjectEffect.dbc': (12, 48), 'DBFilesClient\\ObjectEffectGroup.dbc': (2, 8), 'DBFilesClient\\ObjectEffectModifier.dbc': (8, 32), 'DBFilesClient\\ObjectEffectPackage.dbc': (2, 8), 'DBFilesClient\\ObjectEffectPackageElem.dbc': (4, 16), 'DBFilesClient\\OverrideSpellData.dbc': (12, 48), 'DBFilesClient\\Package.dbc': (20, 80), 'DBFilesClient\\PageTextMaterial.dbc': (2, 8), 'DBFilesClient\\PaperDollItemFrame.dbc': (3, 12), 'DBFilesClient\\ParticleColor.dbc': (10, 40), 'DBFilesClient\\PetPersonality.dbc': (24, 96), 'DBFilesClient\\PowerDisplay.dbc': (6, 15), 'DBFilesClient\\PvpDifficulty.dbc': (6, 24), 'DBFilesClient\\QuestFactionReward.dbc': (11, 44), 'DBFilesClient\\QuestInfo.dbc': (18, 72), 'DBFilesClient\\QuestSort.dbc': (18, 72), 'DBFilesClient\\QuestXP.dbc': (11, 44), 'DBFilesClient\\RandPropPoints.dbc': (16, 64), 'DBFilesClient\\Resistances.dbc': (20, 80), 'DBFilesClient\\ScalingStatDistribution.dbc': (22, 88), 'DBFilesClient\\ScalingStatValues.dbc': (24, 96), 'DBFilesClient\\ScreenEffect.dbc': (10, 40), 'DBFilesClient\\ServerMessages.dbc': (18, 72), 'DBFilesClient\\SheatheSoundLookups.dbc': (7, 28), 'DBFilesClient\\SkillCostsData.dbc': (5, 20), 'DBFilesClient\\SkillLine.dbc': (56, 224), 'DBFilesClient\\SkillLineAbility.dbc': (14, 56), 'DBFilesClient\\SkillLineCategory.dbc': (19, 76), 'DBFilesClient\\SkillRaceClassInfo.dbc': (8, 32), 'DBFilesClient\\SkillTiers.dbc': (33, 132), 'DBFilesClient\\SoundAmbience.dbc': (3, 12), 'DBFilesClient\\SoundEmitters.dbc': (10, 40), 'DBFilesClient\\SoundEntries.dbc': (30, 120), 'DBFilesClient\\SoundEntriesAdvanced.dbc': (24, 96), 'DBFilesClient\\SoundFilter.dbc': (2, 8), 'DBFilesClient\\SoundFilterElem.dbc': (13, 52), 'DBFilesClient\\SoundProviderPreferences.dbc': (24, 96), 'DBFilesClient\\SoundSamplePreferences.dbc': (17, 68), 'DBFilesClient\\SoundWaterType.dbc': (4, 16), 'DBFilesClient\\SpamMessages.dbc': (2, 8), 'DBFilesClient\\Spell.dbc': (234, 936), 'DBFilesClient\\SpellCastTimes.dbc': (4, 16), 'DBFilesClient\\SpellCategory.dbc': (2, 8), 'DBFilesClient\\SpellChainEffects.dbc': (48, 177), 'DBFilesClient\\SpellDescriptionVariables.dbc': (2, 8), 'DBFilesClient\\SpellDifficulty.dbc': (5, 20), 'DBFilesClient\\SpellDispelType.dbc': (21, 84), 'DBFilesClient\\SpellDuration.dbc': (4, 16), 'DBFilesClient\\SpellEffectCameraShakes.dbc': (4, 16), 'DBFilesClient\\SpellFocusObject.dbc': (18, 72), 'DBFilesClient\\SpellIcon.dbc': (2, 8), 'DBFilesClient\\SpellItemEnchantment.dbc': (38, 152), 'DBFilesClient\\SpellItemEnchantmentCondition.dbc': (31, 64), 'DBFilesClient\\SpellMechanic.dbc': (18, 72), 'DBFilesClient\\SpellMissile.dbc': (15, 60), 'DBFilesClient\\SpellMissileMotion.dbc': (5, 20), 'DBFilesClient\\SpellRadius.dbc': (4, 16), 'DBFilesClient\\SpellRange.dbc': (40, 160), 'DBFilesClient\\SpellRuneCost.dbc': (5, 20), 'DBFilesClient\\SpellShapeshiftForm.dbc': (35, 140), 'DBFilesClient\\SpellVisual.dbc': (32, 128), 'DBFilesClient\\SpellVisualEffectName.dbc': (7, 28), 'DBFilesClient\\SpellVisualKit.dbc': (38, 152), 'DBFilesClient\\SpellVisualKitAreaModel.dbc': (3, 12), 'DBFilesClient\\SpellVisualKitModelAttach.dbc': (10, 40), 'DBFilesClient\\StableSlotPrices.dbc': (2, 8), 'DBFilesClient\\Startup_Strings.dbc': (19, 76), 'DBFilesClient\\Stationery.dbc': (4, 16), 'DBFilesClient\\StringLookups.dbc': (2, 8), 'DBFilesClient\\SummonProperties.dbc': (6, 24), 'DBFilesClient\\Talent.dbc': (23, 92), 'DBFilesClient\\TalentTab.dbc': (24, 96), 'DBFilesClient\\TaxiNodes.dbc': (24, 96), 'DBFilesClient\\TaxiPath.dbc': (4, 16), 'DBFilesClient\\TaxiPathNode.dbc': (11, 44), 'DBFilesClient\\TeamContributionPoints.dbc': (2, 8), 'DBFilesClient\\TerrainType.dbc': (6, 24), 'DBFilesClient\\TerrainTypeSounds.dbc': (1, 4), 'DBFilesClient\\TotemCategory.dbc': (20, 80), 'DBFilesClient\\TransportAnimation.dbc': (7, 28), 'DBFilesClient\\TransportPhysics.dbc': (11, 44), 'DBFilesClient\\TransportRotation.dbc': (7, 28), 'DBFilesClient\\UISoundLookups.dbc': (3, 12), 'DBFilesClient\\UnitBlood.dbc': (10, 40), 'DBFilesClient\\UnitBloodLevels.dbc': (4, 16), 'DBFilesClient\\Vehicle.dbc': (40, 160), 'DBFilesClient\\VehicleSeat.dbc': (58, 232), 'DBFilesClient\\VehicleUIIndSeat.dbc': (5, 20), 'DBFilesClient\\VehicleUIIndicator.dbc': (2, 8), 'DBFilesClient\\VocalUISounds.dbc': (7, 28), 'DBFilesClient\\WMOAreaTable.dbc': (28, 112), 'DBFilesClient\\WeaponImpactSounds.dbc': (23, 92), 'DBFilesClient\\WeaponSwingSounds2.dbc': (4, 16), 'DBFilesClient\\Weather.dbc': (8, 32), 'DBFilesClient\\WorldChunkSounds.dbc': (9, 36), 'DBFilesClient\\WorldMapArea.dbc': (11, 44), 'DBFilesClient\\WorldMapContinent.dbc': (14, 56), 'DBFilesClient\\WorldMapOverlay.dbc': (17, 68), 'DBFilesClient\\WorldMapTransforms.dbc': (10, 40), 'DBFilesClient\\WorldSafeLocs.dbc': (22, 88), 'DBFilesClient\\WorldStateUI.dbc': (63, 252), 'DBFilesClient\\WorldStateZoneSounds.dbc': (8, 32), 'DBFilesClient\\ZoneIntroMusicTable.dbc': (5, 20), 'DBFilesClient\\ZoneMusic.dbc': (8, 32), 'DBFilesClient\\gtBarberShopCostBase.dbc': (1, 4), 'DBFilesClient\\gtChanceToMeleeCrit.dbc': (1, 4), 'DBFilesClient\\gtChanceToMeleeCritBase.dbc': (1, 4), 'DBFilesClient\\gtChanceToSpellCrit.dbc': (1, 4), 'DBFilesClient\\gtChanceToSpellCritBase.dbc': (1, 4), 'DBFilesClient\\gtCombatRatings.dbc': (1, 4), 'DBFilesClient\\gtNPCManaCostScaler.dbc': (1, 4), 'DBFilesClient\\gtOCTClassCombatRatingScalar.dbc': (2, 8), 'DBFilesClient\\gtOCTRegenHP.dbc': (1, 4), 'DBFilesClient\\gtOCTRegenMP.dbc': (1, 4), 'DBFilesClient\\gtRegenHPPerSpt.dbc': (1, 4), 'DBFilesClient\\gtRegenMPPerSpt.dbc': (1, 4)}
# END GENERATED PINNED CLIENT DBC LAYOUTS


def require(condition, message):
    if not condition:
        raise ValueError(message)


def virtual_name(value):
    value = value.replace('\\', '/')
    require(value.isascii() and len(value) <= 259 and not value.startswith('/') and
            ':' not in value and '\0' not in value, 'unsafe virtual client member')
    value = posixpath.normpath(value)
    require(value not in ('', '.', '..') and not value.startswith('../'), 'virtual client path escapes its root')
    return value


def imported_name(value):
    """A journal path is an imported filename, not an MPQ virtual member.

    Non-provider installer/readme names can be Unicode and longer than the
    engine's virtual path bound. Keep the importer's containment rules here.
    """
    require(isinstance(value, str) and 0 < len(value.encode('utf-8')) <= 1024 and
            not value.startswith('/') and not any(c in value for c in ('\\', ':')) and
            all(ord(c) >= 32 and ord(c) != 127 for c in value), 'unsafe imported journal path')
    parts = value.split('/')
    require(len(parts) <= 32 and all(part not in ('', '.', '..') and
            not part.endswith(('.', ' ')) for part in parts), 'unsafe imported journal path')
    return value


def effective_provider_path(relative):
    """Any supported classical locale, including an effective folder boundary.

    This is the mask-2/mask-3 OpenArchives table plus PatchFiles enumeration,
    matching ContentPackageLayout. In particular, an inactive installed locale
    or unsupported alternate view must never be discarded as ancillary.
    """
    parts = relative.lower().split('/')
    if len(parts) < 2 or parts[0] != 'data':
        return False
    name = parts[1]
    if name.endswith('.mpq') and (name in {'alternate.mpq', 'expansion.mpq', 'lichking.mpq',
            'common.mpq', 'common-2.mpq', 'common-3.mpq', 'patch.mpq'} or name.startswith('patch-')):
        return True
    if len(parts) < 3 or parts[1] not in {name.lower() for name in order.LOCALES}:
        return False
    locale, name = parts[1:3]
    return name.endswith('.mpq') and (name == 'patch-' + locale + '.mpq' or
            name.startswith('patch-' + locale + '-') or name in {prefix + locale + '.mpq'
            for prefix in ('locale-', 'speech-', 'expansion-locale-', 'lichking-locale-',
                           'expansion-speech-', 'lichking-speech-')})


def ancillary_archives(source, pins):
    """Record ignored physical archives without opening or rehashing them.

    Only files or folder-MPQ members outside every effective provider boundary
    qualify. The original
    completed import remains intact; the Java stock projection independently
    checks these paths and import hashes before omitting them from its own view.
    """
    exclusions, seen, count = [], set(), 0
    for parent, directories, files in os.walk(source, followlinks=False):
        for name in sorted(directories + files):
            path = Path(parent) / name
            relative = imported_name(path.relative_to(source).as_posix())
            count += 1
            require(count <= MAX_MEMBERS, 'stock physical inventory member bound')
            folded = relative.casefold()
            require(folded not in seen, 'case-colliding stock imported path: ' + relative)
            seen.add(folded)
            info = path.lstat()
            require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode),
                    'linked or special stock imported path: ' + relative)
            if not stat.S_ISREG(info.st_mode) or not any(part.endswith('.mpq') for part in folded.split('/')) or effective_provider_path(relative):
                continue
            pin = pins.get(folded)
            require(pin is not None and info.st_size == pin['bytes'],
                    'ancillary archive differs from its completed streaming import: ' + relative)
            exclusions.append({'path': relative, **pin,
                'reason': 'Ancillary archive or folder member: no effective provider location in the selected classical client profile; excluded from the app-owned stock view, original import preserved'})
            require(len(exclusions) <= 4096, 'stock ancillary archive exclusion bound')
    return exclusions


def importer_pins(source, generation):
    """Trust the owned streaming import journals; do not hash 16+ GiB again."""
    require(storage.HASH.fullmatch(generation) is not None and source.name == 'data', 'full import generation required')
    at = storage.canonical(source.parent)
    require(at.name == generation, 'stock source path differs from import generation')
    rows, seen, total = {}, set(), 0
    while True:
        require(at.name not in seen and len(seen) < 32, 'import journal ancestry cycle/depth')
        seen.add(at.name)
        journal = storage.canonical(at / 'journal.tsv', False)
        total += journal.stat().st_size
        require(total <= MAX_METADATA, 'stock import journal exceeds64MiB')
        local = {}
        with journal.open('rb') as incoming:
            while line := incoming.readline(2049):
                require(len(line) <= 2048, 'stock import journal record bound')
                if not line.endswith(b'\n'):
                    continue
                parts = line.rstrip(b'\n').split(b'\t')
                if len(parts) != 4:
                    continue
                try:
                    name = base64.b64decode(parts[0], validate=True).decode('utf-8')
                    size = int(parts[1]); digest = parts[3].decode('ascii')
                    require(size >= 0 and storage.HASH.fullmatch(digest) is not None, 'invalid imported file pin')
                    name = imported_name(name)
                    local[name.casefold()] = {'bytes': size, 'sha256': digest}
                    require(len(local) <= MAX_MEMBERS, 'stock import journal member bound')
                except (UnicodeError, ValueError):
                    continue  # The importer itself can retain an interrupted record.
        for name, pin in local.items():
            rows.setdefault(name, pin)
        parent = at / 'base-ready'
        if not parent.exists():
            break
        raw = storage.read(parent, 66)
        ancestor = raw.decode('ascii').removesuffix('\n')
        require(raw == (ancestor + '\n').encode() and storage.HASH.fullmatch(ancestor) is not None,
                'invalid stock import ancestry')
        at = storage.canonical(at.parent / ancestor)
    return rows


def load_reader(tools, revision):
    manifest = storage.tool_identity(tools, revision)
    name = '_esteria_verified_stock_bls'
    for loaded in list(sys.modules):
        if loaded == name or loaded.startswith(name + '.'):
            del sys.modules[loaded]
    specification = importlib.util.spec_from_file_location(name, tools / 'bls/__init__.py',
            submodule_search_locations=[str(tools / 'bls')])
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        specification.loader.exec_module(module)
        reader = importlib.import_module(name + '.archive')
        return reader, manifest
    finally:
        sys.dont_write_bytecode = previous


def standard_provider(relative, locale):
    parts = relative.lower().split('/')
    if len(parts) == 2 and parts[0] == 'data':
        return parts[1] in {'common.mpq', 'common-2.mpq', 'common-3.mpq', 'expansion.mpq',
                            'lichking.mpq', 'patch.mpq', 'patch-2.mpq', 'patch-3.mpq'}
    if len(parts) == 3 and parts[:2] == ['data', locale.lower()]:
        suffix = locale.lower() + '.mpq'
        return parts[2] in {prefix + suffix for prefix in ('locale-', 'speech-', 'expansion-locale-',
                'lichking-locale-', 'expansion-speech-', 'lichking-speech-', 'patch-')} | {
                'patch-' + locale.lower() + '-2.mpq', 'patch-' + locale.lower() + '-3.mpq'}
    return False


class PackedTable:
    """The pinned reader's indexed rows backed by compact decoded bytes.

    Lookup and member decoding still execute the verified provider reader. Only
    table representation changes: a row is unpacked when queried instead of
    retaining millions of Python tuples and integer objects across the stack.
    """
    def __init__(self, raw, format_, count, high=None):
        require(len(raw) == count * 16, 'decoded MPQ table length differs')
        self.raw, self.row, self.count, self.high = raw, struct.Struct(format_), count, high

    def __len__(self):
        return self.count

    def __getitem__(self, index):
        if index < 0:
            index += self.count
        if index < 0 or index >= self.count:
            raise IndexError(index)
        row = self.row.unpack_from(self.raw, index * 16)
        if self.high is not None:
            row = (row[0] | struct.unpack_from('<H', self.high, index * 2)[0] << 32,) + row[1:]
        return row


def table_spans(archive, maximum):
    """Same v0/v1 extent guards as the pinned reader, before allocation."""
    for position, count in ((archive.hash_table_pos, archive.hash_table_size),
                            (archive.block_table_pos, archive.block_table_size)):
        require(count <= maximum and archive.header_size <= position <= archive.archive_size,
                'invalid or oversized MPQ table: ' + str(archive.path))
    require(archive.hash_table_size and not archive.hash_table_size & (archive.hash_table_size - 1),
            'MPQ hash table count must be a power of two: ' + str(archive.path))
    hash_expected, block_expected = archive.hash_table_size * 16, archive.block_table_size * 16
    if archive.format_version == 0:
        hash_stored, block_stored = hash_expected, block_expected
        require(not (archive.hash_table_pos < archive.block_table_pos + block_stored and
                archive.block_table_pos < archive.hash_table_pos + hash_stored),
                'overlapping MPQ tables: ' + str(archive.path))
    else:
        hash_stored = archive.block_table_pos - archive.hash_table_pos
        block_end = archive.high_block_pos or min(archive.archive_size, archive.block_table_pos + block_expected)
        block_stored = block_end - archive.block_table_pos
        require(2 <= hash_stored <= hash_expected and 0 <= block_stored <= block_expected,
                'unsupported MPQ table ordering/extent: ' + str(archive.path))
        require(not archive.block_table_size or block_stored >= 2,
                'truncated MPQ block table: ' + str(archive.path))
        require(not archive.high_block_pos or archive.high_block_pos + archive.block_table_size * 2 <= archive.archive_size,
                'truncated MPQ high-block table: ' + str(archive.path))
    require(archive.hash_table_pos + hash_stored <= archive.archive_size and
            archive.block_table_pos + block_stored <= archive.archive_size,
            'truncated MPQ tables: ' + str(archive.path))
    return hash_stored, block_stored


def read_decrypted_table(archive, size, key, crypt):
    """Pinned MPQ word cipher, in-place; preserve a final partial word."""
    raw = bytearray(size)
    with memoryview(raw) as view:
        at = 0
        while at < size:
            got = archive.f.readinto(view[at:])
            require(got, 'truncated MPQ data: ' + str(archive.path))
            at += got
        seed, key = 0xEEEEEEEE, key & 0xFFFFFFFF
        # Android ARM64 and the host runners are little endian. Keep an exact
        # portable path for other hosts rather than changing the archive format.
        if sys.byteorder == 'little':
            with view[:size // 4 * 4].cast('I') as words:
                for index in range(len(words)):
                    seed = (seed + crypt[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
                    plain = (words[index] ^ ((key + seed) & 0xFFFFFFFF)) & 0xFFFFFFFF
                    words[index] = plain
                    key = ((((~key) << 0x15) + 0x11111111) | (key >> 0x0B)) & 0xFFFFFFFF
                    seed = (plain + seed + (seed << 5) + 3) & 0xFFFFFFFF
        else:
            for at in range(0, size // 4 * 4, 4):
                seed = (seed + crypt[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
                plain = (struct.unpack_from('<I', raw, at)[0] ^ ((key + seed) & 0xFFFFFFFF)) & 0xFFFFFFFF
                struct.pack_into('<I', raw, at, plain)
                key = ((((~key) << 0x15) + 0x11111111) | (key >> 0x0B)) & 0xFFFFFFFF
                seed = (plain + seed + (seed << 5) + 3) & 0xFFFFFFFF
    return raw


def compact_mpq_class(reader):
    """App-owned storage adapter; the immutable provider bytes stay unchanged."""
    mq = reader.mq
    class CompactMPQ(mq.MPQ):
        def _read_exact(self, size):
            # The provider limits decoded members to64MiB, but its single-unit
            # path otherwise reads the declared stored length first. Bound
            # that allocation too, including the largest legitimate sector
            # offset/CRC table (512-byte sectors plus two offsets).
            maximum = mq.MAX_FILE_SIZE + ((mq.MAX_FILE_SIZE + 511) // 512 + 2) * 4
            require(0 <= size <= maximum,
                    'MPQ read exceeds bounded member and sector-table limit: ' + str(self.path))
            return super()._read_exact(size)

        def _read_tables(self):
            hash_stored, block_stored = table_spans(self, mq.MAX_TABLE_ENTRIES)
            for name, position, stored, count, format_ in (
                    ('hash_table', self.hash_table_pos, hash_stored, self.hash_table_size, '<IIHHI'),
                    ('block_table', self.block_table_pos, block_stored, self.block_table_size, '<IIII')):
                self.f.seek(self.archive_offset + position)
                raw = read_decrypted_table(self, stored, mq.hash_string('(' + name.replace('_', ' ') + ')', 3), mq.CT)
                if stored != count * 16:
                    raw = mq.decompress_sector(raw, count * 16)
                high = None
                if name == 'block_table' and self.high_block_pos:
                    self.f.seek(self.archive_offset + self.high_block_pos)
                    high = self._read_exact(count * 2)
                setattr(self, name, PackedTable(raw, format_, count, high))
    return CompactMPQ


def preflight_tables(paths, reader, locale):
    """Bound each prospective provider before decrypting its packed tables.

    Optional classification needs the archive's real catalogue members. Keep
    one bounded packed candidate as headroom, then enforce the historical
    combined limit only when retaining an effective provider. Content-confirmed
    optional archives never consume that retained-provider budget.
    """
    class HeaderProbe(reader.mq.MPQ):
        def _read_tables(self):
            pass  # Reuse only the pinned header discovery; no table allocation.
    counts = {}
    for path in paths:
        probe = HeaderProbe(path, reader.LOCALES[locale])
        try:
            table_spans(probe, reader.mq.MAX_TABLE_ENTRIES)
            counts[path] = probe.hash_table_size + probe.block_table_size
        finally:
            probe.close()
    return counts


class Stack:
    def __init__(self, source, locale, reader, pins):
        self.archives = []
        self.providers, self.exclusions, self.unknown = [], [], []
        data_dirs = [path for path in source.iterdir() if path.name.casefold() == 'data']
        require(len(data_dirs) == 1, 'one stock Data directory required')
        paths = reader.provider_paths(data_dirs[0], locale)
        require(len(paths) <= order.MAX_PROVIDERS, 'stock provider inventory bound')
        for path in paths:
            relative = path.relative_to(source).as_posix()
            require(path.is_file() and not path.is_symlink(),
                    'Stock 3.3.5a requires regular archive providers; inspect folder overlay: ' + relative)
            pin = pins.get(relative.casefold())
            require(pin is not None and path.stat().st_size == pin['bytes'],
                    'archive differs from its completed streaming import: ' + relative)
        table_counts = preflight_tables(paths, reader, locale)
        retained_count = 0
        archive_type = compact_mpq_class(reader)
        try:
            for path in paths:
                relative = path.relative_to(source).as_posix()
                require(path.is_file() and not path.is_symlink(),
                        'Stock 3.3.5a requires regular archive providers; inspect folder overlay: ' + relative)
                pin = pins.get(relative.casefold())
                require(pin is not None and path.stat().st_size == pin['bytes'],
                        'archive differs from its completed streaming import: ' + relative)
                archive = archive_type(path, reader.LOCALES[locale])
                retained = False
                try:
                    require(archive.find('(listfile)') is not None, 'missing shader/listfile inventory: ' + relative)
                    require(archive.block_table[archive.find('(listfile)')][2] <= 16 << 20,
                            'archive listfile exceeds16MiB before allocation: ' + relative)
                    names, _ = archive.read_file('(listfile)')
                    require(len(names) <= 16 << 20, 'archive listfile exceeds16MiB: ' + relative)
                    members = names.decode('utf-8', errors='replace').replace('\\', '/').splitlines()
                    require(len(members) <= MAX_MEMBERS, 'archive listfile member bound: ' + relative)
                    candidates = [name for name in members if CATALOG_MARKER.search(name)]
                    markers = []
                    for name in candidates:
                        found = archive.find(name.replace('/', '\\'))
                        if found is None or archive.block_table[found][2] > 12 + 16384 * 156:
                            continue
                        raw, _ = archive.read_file(name.replace('/', '\\'))
                        if len(raw) >= 12:
                            magic, version, count = struct.unpack_from('<3I', raw)
                            if magic == 0x314D4845 and version == 1 and count <= 16384 and len(raw) == 12 + count * 156:
                                markers.append(name + ' [EHM1/v1, ' + str(count) + ' selection records]')
                    row = {'path': relative, **pin}
                    if markers:
                        require(not standard_provider(relative, locale),
                                'essential stock archive contains Esteria catalogues: ' + relative)
                        row.update(classification='confirmed-optional', reason='Esteria catalogue members: ' + ', '.join(markers[:4]))
                        self.exclusions.append({key: row[key] for key in ('path', 'bytes', 'sha256', 'reason')})
                    elif candidates or not standard_provider(relative, locale):
                        row.update(classification='unknown-overlay', reason='No reviewed stock or optional content identity; archive name alone is insufficient')
                        self.unknown.append({key: row[key] for key in ('path', 'bytes', 'sha256', 'reason')})
                    else:
                        row.update(classification='stock-candidate', reason='Conventional archive; effective members validated below, cryptographic authenticity remains a client startup check')
                    self.providers.append(row)
                    if not markers:
                        retained_count += table_counts[path]
                        require(retained_count <= MAX_TABLE_ENTRIES,
                                'combined retained stock MPQ table memory bound before retaining: ' + relative)
                        self.archives.append((relative, archive)); retained = True
                finally:
                    if not retained:
                        archive.close()
                        # Release this candidate before the next constructor
                        # so optional archives use one packed-table headroom.
                        archive = None
        except Exception:
            self.close()
            raise

    def close(self):
        for _, archive in self.archives:
            archive.close()
        self.archives.clear()

    def read(self, name, maximum=64 << 20):
        query = virtual_name(name).replace('/', '\\')
        for provider, archive in reversed(self.archives):
            found = archive.find(query)
            if found is not None:
                require(archive.block_table[found][2] <= maximum, 'virtual member size bound: ' + name)
                raw, _ = archive.read_file(query)
                return provider, raw
        raise ValueError('missing essential stock member: ' + name)


def inspect_dbc(raw, name, layout):
    require(len(raw) >= 20, 'truncated stock DBC: ' + name)
    magic, count, fields, stride, strings = struct.unpack_from('<4s4I', raw)
    require(magic == b'WDBC' and (fields, stride) == tuple(layout) and
            20 + count * stride + strings == len(raw),
            'stock DBC layout/length differs: ' + name + '; expected ' + str(layout[0]) +
            ' fields/' + str(layout[1]) + ' row bytes')
    required = SENTINELS.get(name.rsplit('\\', 1)[-1])
    if required is not None:
        require(any(struct.unpack_from('<I', raw, 20 + row * stride)[0] == required for row in range(count)),
                'stock DBC is missing build12340/Human Warrior sentinel ' + str(required) + ': ' + name)
    return {'records': count, 'fields': fields, 'recordBytes': stride, 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


def inspect_ui(stack, toc):
    """Check the real TOC/XML/Lua closure without substituting a signature check."""
    seen, active, total = {}, set(), 0
    def visit(name):
        nonlocal total
        name = virtual_name(name)
        folded = name.casefold()
        require(folded not in active, 'recursive stock UI include: ' + name)
        if folded in seen:
            return
        require(len(seen) < MAX_UI_FILES, 'stock UI closure file bound')
        provider, raw = stack.read(name, 4 << 20)
        total += len(raw)
        require(total <= MAX_UI_BYTES, 'stock UI closure exceeds64MiB')
        seen[folded] = {'path': name, 'provider': provider, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        active.add(folded)
        text = raw.decode('utf-8-sig', errors='replace')
        if folded.endswith('.toc'):
            for line in re.split(r'[\r\n]+', text):
                if line and not line.startswith('#'):
                    visit(posixpath.join(posixpath.dirname(name), line.rstrip(' ')))
        elif folded.endswith('.xml'):
            # Engine ProcessXMLForMakeSign consumes Script/Include file tags in
            # document order. This parser checks closure only, not its MD5/RSA.
            text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
            for tag in re.finditer(r'<\s*(?:Script|Include)\s+[^>]*>', text, re.I):
                value = re.search(r'\bfile\s*=\s*["\']([^"\']+)["\']', tag[0], re.I)
                if value:
                    visit(posixpath.join(posixpath.dirname(name), value[1].replace('\\', '/')))
        active.remove(folded)
    visit(toc)
    provider, signature = stack.read(toc + '.sig', 276)
    require(len(signature) == 276, 'stock UI signature must contain276 bytes: ' + toc + '.sig')
    return {'files': len(seen), 'bytes': total, 'closureSha256': hashlib.sha256(storage.encoded(seen)).hexdigest(),
            'signatureProvider': provider, 'signatureSha256': hashlib.sha256(signature).hexdigest(),
            'rsaAuthenticated': False, 'runtimeDigestValidated': False}


def inspect(source, tools, revision, locale, generation, *, reader_loader=load_reader):
    source, tools = storage.canonical(source), storage.canonical(tools)
    require(revision == CLIENT_REVISION, 'stock inspection requires exact selected client revision')
    pins = importer_pins(source, generation)
    tree = order.Inventory(source)
    require(tree.find('Data/common.MPQ') is not None, 'missing essential Data/common.MPQ')
    require(locale in order.LOCALES, 'unsupported stock requested locale')
    start = order.LOCALES.index(locale)
    effective = next((candidate for index in range(len(order.LOCALES))
        if (candidate := order.LOCALES[(start + index) % len(order.LOCALES)]) and
        tree.find('Data/' + candidate + '/locale-' + candidate + '.MPQ')), None)
    require(effective is not None, 'missing complete installed stock locale')
    require(tree.find('Data/' + effective + '/speech-' + effective + '.MPQ') is not None,
            'missing essential Data/' + effective + '/speech-' + effective + '.MPQ')
    reader, tool_hash = reader_loader(tools, revision)
    require(effective in reader.LOCALES, 'stock shader reader does not support winning locale: ' + effective)
    report = {'formatVersion': 1, 'contentProfile': PROFILE, 'importGeneration': generation,
            'clientRevision': revision, 'requestedLocale': locale, 'effectiveLocale': effective,
            'toolManifestSha256': tool_hash, 'providers': [], 'exclusions': [], 'unknownOverlays': [],
            'checks': {}, 'errors': [], 'passed': False, 'runtimeSignatureValidation': False,
            'runtimeExecution': False, 'worldEntry': False}
    ancillary = ancillary_archives(source, pins)
    stack = Stack(source, effective, reader, pins)
    try:
        report.update(providers=list(reversed(stack.providers)), exclusions=stack.exclusions + ancillary, unknownOverlays=stack.unknown)
        require(len(report['exclusions']) <= 4096, 'combined stock archive exclusion bound')
        if stack.unknown:
            report['errors'].extend('unclassified optional overlay: ' + row['path'] for row in stack.unknown)
        checks = report['checks']
        def run(name, action):
            try:
                checks[name] = action()
            except world_io.PreparationPaused:
                raise
            except (OSError, ValueError, RuntimeError, struct.error) as error:
                report['errors'].append(name + ': ' + str(error))
        def signaturefile():
            provider, raw = stack.read('signaturefile', 16 << 20)
            require(raw.startswith(b'2\r\n2\r\nRELEASE\r\n'), 'stock signaturefile has unsupported version/scope header')
            return {'provider': provider, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'rsaAuthenticated': False}
        run('signaturefile', signaturefile)
        for toc in ('Interface/GlueXML/GlueXML.toc', 'Interface/FrameXML/FrameXML.toc'):
            run(toc, lambda toc=toc: inspect_ui(stack, toc))
        run('Interface/FrameXML/Bindings.xml', lambda: {'provider': stack.read('Interface/FrameXML/Bindings.xml', 4 << 20)[0]})
        dbcs = {}; checks['clientDbcs'] = dbcs
        for name, layout in CLIENT_DBC_LAYOUTS.items():
            def dbc(name=name, layout=layout):
                provider, raw = stack.read(name)
                result = inspect_dbc(raw, name, layout)
                result['provider'] = provider; dbcs[name] = result
                return result
            try:
                dbc()
            except world_io.PreparationPaused:
                raise
            except (OSError, ValueError, RuntimeError, struct.error) as error:
                report['errors'].append(str(error))
        def shaders():
            inv = reader.inventory(stack.archives)
            stages = {kind: sum(len(names) for (stage, _), names in inv.items() if stage == kind) for kind in ('vertex', 'pixel')}
            require(all(stages.values()), 'stock shader listfile inventory lacks vertex or pixel containers')
            return {'listedVertexContainers': stages['vertex'], 'listedPixelContainers': stages['pixel'], 'actualTranslation': False}
        run('shaderInputs', shaders)
        report['passed'] = not report['errors']
        return report
    finally:
        stack.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'tools', 'report'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('client-revision', 'locale', 'generation'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--android-low-memory', action='store_true', help='Use the fixed Android preparation I/O policy')
    args = parser.parse_args()
    report = None
    try:
        if args.android_low_memory:
            with world_io.android_policy(progress=lambda value: print(value, flush=True)):
                report = inspect(args.source, args.tools, args.client_revision, args.locale, args.generation)
        else:
            report = inspect(args.source, args.tools, args.client_revision, args.locale, args.generation)
        storage.atomic(args.report, storage.encoded(report))
        print('Stock profile: ' + report['contentProfile'] + '; import: ' + report['importGeneration'] +
              '; requested locale: ' + report['requestedLocale'] + '; effective locale: ' + report['effectiveLocale'])
        print('Inspected providers: ' + str(len(report['providers'])) + '; DBC layouts: ' +
              str(len(report['checks'].get('clientDbcs', {}))) + '; excluded optional/ancillary files: ' +
              str(len(report['exclusions'])) + '; unknown overlays: ' + str(len(report['unknownOverlays'])))
        for row in report['exclusions'][:32]:
            print('Excluded file: ' + row['path'] + '; ' + row['reason'])
        if len(report['exclusions']) > 32:
            print('Additional exclusions retained in compatibility report: ' + str(len(report['exclusions']) - 32))
        if not report['passed']:
            print('Stock client validation failed: ' + '; '.join(report['errors'][:8]), file=sys.stderr)
            return 0  # A complete diagnostic report is the result consumed by the Android owner.
        print('Stock client data inspected; client signatures and world entry still require runtime execution')
        return 0
    except world_io.PreparationPaused:
        world_io.print_pause()
        return world_io.PAUSED_EXIT_CODE
    except (OSError, ValueError, RuntimeError, struct.error) as error:
        report = report or {'formatVersion': 1, 'contentProfile': PROFILE, 'importGeneration': args.generation,
            'clientRevision': args.client_revision, 'requestedLocale': args.locale, 'effectiveLocale': '',
            'toolManifestSha256': storage.tool_identity(args.tools, args.client_revision), 'providers': [], 'exclusions': [], 'unknownOverlays': [], 'checks': {},
            'errors': [str(error)], 'passed': False, 'runtimeSignatureValidation': False, 'runtimeExecution': False, 'worldEntry': False}
        storage.atomic(args.report, storage.encoded(report))
        print('Stock client validation failed: ' + str(error), file=sys.stderr)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
