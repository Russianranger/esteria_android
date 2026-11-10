"""Owner-chosen worldserver settings, applied as AzerothCore environment overrides.

The rendered configuration generation stays byte-for-byte as verified. The app
writes ``world-overrides.json`` into the session operation; this module accepts
only keys that the active generation's files define, refuses keys the reviewed
policy reserves for Esteria (database, paths, network, logging, module switches
of the stock profile), and maps each accepted key to the name AzerothCore's
ConfigMgr reads from the environment before the file value.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

OVERRIDES_NAME = 'world-overrides.json'
SCOPE = 'esteria-world-config-overrides'
POLICY_SCOPE = 'esteria-world-config-overrides-policy'
MAX_DOCUMENT_BYTES = 256 << 10
MAX_CONFIG_BYTES = 4 << 20
MAX_REPORTED = 32
KEY = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}')
SETTING = re.compile(r'^[ \t]*([A-Za-z0-9_][A-Za-z0-9_.\-]{0,127})[ \t]*=', re.M)


class Rejected(ValueError):
    pass


def env_name(key: str) -> str:
    """Port of IniKeyToEnvVarKey in the pinned server's Config.cpp, with its AC_ prefix."""
    result = ''
    for index, current in enumerate(key):
        if current in ' .-':
            result += '_'
            continue
        if index != len(key) - 1:
            following = key[index + 1]
            if (not current.isupper() and following.isupper()) or \
                    (not current.isdigit() and following.isdigit()) or (current.isdigit() and not following.isdigit()):
                result += current.upper() + '_'
                continue
        result += current.upper()
    return 'AC_' + result


def _bounded_text(path: Path, limit: int) -> str:
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise Rejected('File exceeds its bound')
    return raw.decode('utf-8')


class Policy:
    def __init__(self, document: dict):
        if type(document) is not dict or document.get('formatVersion') != 1 or document.get('scope') != POLICY_SCOPE:
            raise Rejected('Unknown world settings policy')
        self.max_overrides = document['maxOverrides']
        self.max_value = document['maxValueLength']
        if type(self.max_overrides) is not int or not 0 < self.max_overrides <= 1024 or \
                type(self.max_value) is not int or not 0 < self.max_value <= 1024:
            raise Rejected('Invalid world settings policy bounds')
        self.file_pattern = re.compile(document['filePattern'])
        self.protected_keys = frozenset(document['protectedKeys'])
        self.protected_patterns = tuple(re.compile(pattern) for pattern in document['protectedPatterns'])
        self.launch_defaults = dict(document['launchDefaults'])
        if not all(type(key) is str and KEY.fullmatch(key) for key in self.protected_keys | set(self.launch_defaults)):
            raise Rejected('Invalid world settings policy keys')

    @classmethod
    def load(cls, path: Path) -> 'Policy':
        return cls(json.loads(_bounded_text(Path(path), 64 << 10)))

    def protected(self, key: str) -> bool:
        return key in self.protected_keys or any(pattern.search(key) for pattern in self.protected_patterns)

    def value_allowed(self, value) -> bool:
        # An empty text clears a list setting; the app refuses empty numbers before saving.
        return type(value) is str and len(value) <= self.max_value and value == value.strip() and \
            all(character.isprintable() for character in value) and '"' not in value and '\\' not in value


def policy_path(helpers: Path) -> Path:
    """Packaged beside the session helpers; in the repository it lives in config/."""
    packaged = Path(helpers) / 'world-config-policy.json'
    return packaged if packaged.exists() else Path(helpers).parent / 'config/world-config-policy.json'


def defined_keys(configurations: Path, name: str) -> set[str]:
    """Keys a rendered file sets, read only from inside the verified generation directory."""
    root = Path(configurations)
    path = root / name
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise Rejected('Configuration file is not part of the active generation')
    return set(SETTING.findall(_bounded_text(path, MAX_CONFIG_BYTES)))


def environment(document_path: Path, configurations: Path, policy: Policy):
    """Return (environment, applied keys, refused keys). A missing document applies nothing."""
    document_path = Path(document_path)
    if not document_path.exists():
        return {}, [], []
    if document_path.is_symlink() or not document_path.is_file():
        raise Rejected('World settings must be a private regular file')
    document = json.loads(_bounded_text(document_path, MAX_DOCUMENT_BYTES))
    if type(document) is not dict or document.get('formatVersion') != 1 or document.get('scope') != SCOPE or \
            type(document.get('settings')) is not list:
        raise Rejected('Unknown world settings document')
    settings = document['settings']
    env, applied, refused, files = {}, [], [], {}
    for index, entry in enumerate(settings):
        key = entry.get('key') if type(entry) is dict else None
        label = key if type(key) is str and KEY.fullmatch(key) else '#' + str(index)
        try:
            if index >= policy.max_overrides or type(entry) is not dict or set(entry) != {'file', 'key', 'value'}:
                raise Rejected('Malformed entry')
            name = entry['file']
            if type(name) is not str or not policy.file_pattern.fullmatch(name) or label != key:
                raise Rejected('Unknown file or key')
            if policy.protected(key):
                raise Rejected('Managed by Esteria')
            if not policy.value_allowed(entry['value']):
                raise Rejected('Value not allowed')
            if name not in files:
                files[name] = defined_keys(configurations, name)
            if key not in files[name]:
                raise Rejected('Key is not in that file')
            variable = env_name(key)
            if variable in env and env[variable] != entry['value']:
                raise Rejected('Conflicting value for the same setting')
            env[variable] = entry['value']
            applied.append(key)
        except (Rejected, OSError, UnicodeDecodeError):
            refused.append(label)
    return env, applied, refused


def report(applied, refused) -> str:
    """One bounded stdout line for the support bundle: names only, never values."""
    shown = ','.join(applied[:MAX_REPORTED]) + (',...' if len(applied) > MAX_REPORTED else '')
    line = 'WORLD_SETTINGS applied=%d refused=%d keys=%s' % (len(applied), len(refused), shown or '-')
    if refused:
        line += ' refusedKeys=' + ','.join(refused[:MAX_REPORTED])
    return line
