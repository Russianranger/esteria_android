#!/usr/bin/env python3
"""Admit a measured data-tool update beside an unchanged frozen server release.

The old public recipe still verifies its original complete provider. This small
selection binds the two changed current data-tool inputs explicitly; it never
relabels historical source/debug bytes as the newly compiled programs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import package_server_engine as engine, verify_server_build as files

ROOT = Path(__file__).resolve().parents[1]
LOCK = 'runtime/server/data-tools-update.lock.json'
INPUTS = ('runtime/server/data-tools-provider.lock.json',
          'runtime/server/data-tools-qualified-artifacts.lock.json')
NATIVE = 'runtime/server/ordered-tools-inputs.lock.json'
SCOPE = 'measured-data-tools-update-over-frozen-local-server-profile'
require = files.require


def document(raw):
    def unique(rows):
        result = {}
        for key, value in rows:
            require(key not in result, 'data-tools-update-duplicate-json-key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
        parse_constant=lambda _: require(False, 'data-tools-update-nonfinite-json'))


def current_qualification():
    from tools import provider_server_data_tools as provider, prepare_data_tools_provider as acquisition
    selected = provider.load_pin(sealed=True)
    acquisition.load_pin()
    return selected['actualOrderedSourceQualification']


def changed_inputs(baseline, current):
    require(type(baseline) is dict and type(current) is dict and set(baseline) == set(current),
            'data-tools-update-server-selection-roster')
    changed = {name for name in current if current[name] != baseline[name]}
    require(changed == set(INPUTS), 'data-tools-update-only-two-measured-inputs-may-change')
    return changed


def validate(value, baseline_path, baseline, current, root=ROOT):
    changed_inputs(baseline, current)
    require(type(value) is dict and type(value.get('formatVersion')) is int and
        all(value.get(name) is False for name in ('oldPublicProviderReinterpreted',
            'serverProgramsChanged', 'androidRuntimeQualified', 'gameplayQualified')),
        'data-tools-update-explicit-qualification-boundary')
    expected = dict(formatVersion=1, scope=SCOPE, state='source-and-native-qualified',
        baselineReleaseLock=files.identity(baseline_path),
        baselineInputs={name: baseline[name] for name in INPUTS},
        updatedInputs={name: current[name] for name in INPUTS},
        nativeInputLock=files.identity(Path(root) / NATIVE),
        orderedSourceQualification=current_qualification(),
        oldPublicProviderReinterpreted=False, serverProgramsChanged=False,
        androidRuntimeQualified=False, gameplayQualified=False)
    require(value == expected, 'data-tools-update-exact-baseline-and-measured-selection-required')
    return value


def selection(baseline_path, baseline, current, root=ROOT):
    if baseline == current: return None
    changed_inputs(baseline, current)
    path = Path(root) / LOCK
    require(path.is_file(), 'data-tools-update-explicit-lock-required')
    with files.plain_file(path) as incoming:
        raw = incoming.read((64 << 10) + 1)
    require(len(raw) <= 64 << 10, 'data-tools-update-lock-byte-bound')
    value = document(raw)
    validate(value, baseline_path, baseline, current, root)
    return dict(selection=files.identity(path), baselineInputs=value['baselineInputs'],
        updatedInputs=value['updatedInputs'], nativeInputLock=value['nativeInputLock'],
        orderedSourceQualification=value['orderedSourceQualification'])


def measure(baseline_path, current, root=ROOT):
    with files.plain_file(baseline_path) as incoming:
        raw = incoming.read((4 << 20) + 1)
    require(len(raw) <= 4 << 20, 'data-tools-update-baseline-lock-byte-bound')
    baseline = document(raw)['selectedInputs']
    changed_inputs(baseline, current)
    value = dict(formatVersion=1, scope=SCOPE, state='source-and-native-qualified',
        baselineReleaseLock=files.identity(baseline_path),
        baselineInputs={name: baseline[name] for name in INPUTS},
        updatedInputs={name: current[name] for name in INPUTS},
        nativeInputLock=files.identity(Path(root) / NATIVE),
        orderedSourceQualification=current_qualification(),
        oldPublicProviderReinterpreted=False, serverProgramsChanged=False,
        androidRuntimeQualified=False, gameplayQualified=False)
    return validate(value, baseline_path, baseline, current, root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), 'data-tools-update-existing-output-preserved')
    from tools import release_local_server_components as release
    value = measure(ROOT / 'runtime/server-components-publication/dependency-release.lock.json',
                    release.selected_inputs())
    with args.output.open('xb') as outgoing: outgoing.write(engine.canonical(value))
    print(json.dumps(dict(output=str(args.output), identity=files.identity(args.output)), indent=2))


if __name__ == '__main__': main()
