"""Separate the current APK source binding from an unchanged archived server build.

Client identity may advance after its own protocol/runtime gates. The server
source selection and declared compatibility profile must remain exactly equal.
Original build/content/source/debug receipts keep their original full-lock hash.
"""
import hashlib
import json
from pathlib import Path
import re

from tools import fetch_sources, verify_server_build as files

require = files.require


def same(left, right):
    # Python equality treats True == 1 and 12340 == 12340.0. Source/profile
    # contracts retain JSON types, like the Android JSONObject comparison.
    options = dict(sort_keys=True, separators=(',', ':'), allow_nan=False)
    return json.dumps(left, **options) == json.dumps(right, **options)


def identity(row):
    require(isinstance(row, dict) and type(row.get('bytes')) is int and 0 < row['bytes'] <= 65536 and
            re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')), 'server-source-lock-identity-required')
    return {key: row[key] for key in ('bytes', 'sha256')}


def validate_current(pin, current_path):
    with files.plain_file(current_path) as stream:
        require(len(stream.read(65537)) <= 65536, 'server-current-app-source-lock-size-bound')
    current = fetch_sources.load_lock(current_path)
    require(type(current.get('schema')) is int and current['schema'] == 1, 'server-current-source-lock-schema-differs')
    require(identity(pin.get('appSourceLock')) == files.identity(current_path), 'server-current-app-source-lock-differs')
    identity(pin.get('serverBuildSourceLock'))
    require(isinstance(pin.get('serverBuildSourceLockText'), str), 'server-archived-build-source-text-required')
    validate_archived(pin['serverBuildSourceLockText'].encode('utf-8'), pin)
    require(isinstance(pin.get('serverSource'), dict) and same(current['sources']['server'], pin['serverSource']),
            'server-current-source-selection-differs')
    require(isinstance(pin.get('serverBuildCompatibility'), dict) and
            same(current.get('compatibility'), pin['serverBuildCompatibility']), 'server-current-compatibility-profile-differs')
    return current


def validate_archived(raw, pin):
    require(dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) == identity(pin['serverBuildSourceLock']),
            'server-archived-build-source-lock-differs')
    archived = json.loads(raw)
    require(archived.get('schema') == 1 and same(archived.get('sources', {}).get('server'), pin['serverSource']) and
            same(archived.get('compatibility'), pin['serverBuildCompatibility']), 'server-archived-build-profile-differs')
    return archived


def descriptor_fields(pin):
    return dict(appSourceLockSha256=pin['appSourceLock']['sha256'],
        serverBuildSourceLock=identity(pin['serverBuildSourceLock']),
        serverBuildSourceLockSha256=pin['serverBuildSourceLock']['sha256'],
        serverBuildSourceLockText=pin['serverBuildSourceLockText'],
        serverSource=pin['serverSource'], serverBuildCompatibility=pin['serverBuildCompatibility'])
