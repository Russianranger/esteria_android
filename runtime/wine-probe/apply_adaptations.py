#!/usr/bin/env python3
"""Apply and retain exact, source-owned Wine adaptations for the Android fixture."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def require(value, reason):
    if not value:
        raise ValueError(reason)


def inputs(lock, directory):
    profile = lock['wine']['androidPrivatePeCopy']
    require(profile.get('environment') == {'WINE_ANDROID_PRIVATE_PE_COPY': '1'}, 'adaptation-environment')
    patches = profile.get('patches', [])
    tests = profile.get('testSources', {})
    require(type(patches) is list and 0 < len(patches) <= 4 and type(tests) is dict and
            0 < len(tests) <= 8, 'adaptation-source-count')
    selected = dict(tests)
    for patch in patches:
        require(type(patch) is dict and set(patch) == {'file', 'bytes', 'sha256'}, 'adaptation-patch-fields')
        name = patch['file']
        require(name not in selected and name.endswith('.patch'), 'adaptation-patch-identity')
        selected[name] = {key: patch[key] for key in ('bytes', 'sha256')}
    result = {}
    total = 0
    for name, pin in selected.items():
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', name) and type(pin) is dict and
                set(pin) == {'bytes', 'sha256'} and type(pin.get('bytes')) is int and
                0 < pin['bytes'] <= 262144 and re.fullmatch('[a-f0-9]{64}', pin.get('sha256', '')),
                'adaptation-source-identity')
        path = directory / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == pin['bytes'],
                'adaptation-source-size')
        data = path.read_bytes()
        require(len(data) == pin['bytes'] and hashlib.sha256(data).hexdigest() == pin['sha256'],
                'adaptation-source-hash')
        total += len(data)
        require(total <= 1048576, 'adaptation-source-total')
        result[name] = data
    return profile, result


def apply(lock, directory, source, output):
    profile, selected = inputs(lock, directory)
    require(source.is_dir() and not source.is_symlink() and source.resolve() == source,
            'adaptation-source-root')
    require(not os.path.lexists(output), 'adaptation-output-exists')
    # The caller has verified and freshly unpacked the exact upstream archive.
    # No fuzz, reversed patches or already-applied patches are accepted.
    for patch in profile['patches']:
        subprocess.run(['patch', '--batch', '--forward', '--fuzz=0', '-p1'],
                       input=selected[patch['file']], cwd=source, check=True, timeout=30)
    output.mkdir(mode=0o755)
    for name, data in sorted(selected.items()):
        with (output / name).open('xb') as stream:
            stream.write(data)
    return dict(formatVersion=1, scope='applied-source-owned-wine-adaptations-only',
                environment=profile['environment'],
                files={name: dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                       for name, data in sorted(selected.items())},
                androidRuntimeQualified=False, gameplayQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('lock', 'inputs', 'source', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = apply(json.loads(args.lock.read_bytes()), args.inputs, args.source, args.output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
