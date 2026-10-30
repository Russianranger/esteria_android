#!/usr/bin/env python3
"""Native qualification adapter for the shared, no-Git source baseline.

The native caller still verifies its installed binaries, source lock, immutable
content package and compiled selection before invoking this shared algorithm.
"""
from runtime import server_schema_baseline as shared
from tools import qualify_base_sql as base, verify_server_build as files

DATABASES = shared.DATABASES
NEMESIS_MODULE, NEMESIS_BASE = shared.NEMESIS_MODULE, shared.NEMESIS_BASE
NEMESIS_IDENTITY, NEMESIS_TABLES = shared.NEMESIS_IDENTITY, shared.NEMESIS_TABLES
CUSTOM_RACE_DDL = shared.CUSTOM_RACE_DDL
CUSTOM_RACE_IDENTITY, CUSTOM_RACE_TABLES = shared.CUSTOM_RACE_IDENTITY, shared.CUSTOM_RACE_TABLES
require = base.content.require


def contracts():
    return dict(counts=base.BASE_COUNTS, identity=files.identity,
                nemesis_identity=NEMESIS_IDENTITY, custom_race_identity=CUSTOM_RACE_IDENTITY)


def selected_plan(source, manifest):
    return shared.selected_plan(source, manifest, **contracts())


def initialize(connection, source, manifest, apply):
    return shared.initialize(connection, source, manifest, apply, **contracts())
