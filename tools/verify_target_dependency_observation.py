#!/usr/bin/env python3
"""Read back a retained Ninja target observation without running a compiler.

This checks the published source/object/command graph, rather than claiming to
independently possess the original native object bytes or system-header sources.
The caller authenticates the native producer receipt and prepared source tree.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from tools import capture_ordered_extractor_dependencies as dependencies
from tools import manifest_server_content as content, manifest_server_modules as modules
from tools import verify_server_build as files

require = files.require
TRUE_FLAGS = ('actualTargetSourceDependencyObservation', 'dependencyIdentitiesObservedAfterBuild',
              'dependenciesNotNewerThanObject')
FALSE_FLAGS = ('sourceCompanionComplete', 'systemHeaderSourcesCopied', 'unknownOriginalSystemHashesCompared',
               'androidRuntimeQualified', 'customEsteriaDataLoadOrderQualified', 'worldQualified', 'gameplayQualified')
LINK_TRUE_FLAGS = ('linkDependenciesNotNewerThanOutput',)
LINK_FALSE_FLAGS = ('linkInputsCopied', 'systemLinkSourcesCopied')


def identity(row):
    require(type(row) is dict and type(row.get('bytes')) is int and 0 <= row['bytes'] <= dependencies.MAX_TEXT and
            isinstance(row.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', row['sha256']),
            'target-observation-invalid-identity')
    return {key: row[key] for key in ('bytes', 'sha256')}


def verify(payload, receipt, prepared_inventory, compile_commands, *, targets, machines,
           observation_identity=None, required_sources=(), expected_objects=None, expected_links=None,
           required_link_programs=None):
    """Return source coverage after exact retained graph and byte verification.

    ``prepared_inventory`` uses the observed ``source/``, ``integration/`` and
    ``external/`` prefixes. ``required_sources`` uses those same relative paths.
    ``machines`` and ``targets`` are an explicit caller policy, not inferred from
    mutable artifact contents. No native object or absolute system file is read.
    """
    require(type(targets) is tuple and targets and len(set(targets)) == len(targets) and
            all(type(x) is str and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_+.-]{0,127}', x) for x in targets) and
            type(machines) is tuple and machines and all(type(x) is int for x in machines),
            'target-observation-explicit-target-and-machine-policy-required')
    scope = ('actual-ordered-target-source-and-dependency-observation' if targets == dependencies.TARGETS else
             'actual-target-source-and-dependency-observation')
    require(receipt.get('formatVersion') == 1 and receipt.get('scope') == scope and
            receipt.get('targets') == list(targets) and receipt.get('objectElfMachines') == sorted(set(machines)) and
            all(receipt.get(k) is True for k in TRUE_FLAGS) and
            all(receipt.get(k) is False for k in FALSE_FLAGS) and
            all(receipt.get(k) is True for k in LINK_TRUE_FLAGS) and
            all(receipt.get(k) is False for k in LINK_FALSE_FLAGS), 'target-observation-native-scope-or-gates')
    for name in ('observedObjects', 'observedProjectFiles', 'observedGeneratedFiles', 'observedSystemHeaders'):
        limit = dependencies.MAX_OBJECTS if name == 'observedObjects' else dependencies.MAX_FILES
        minimum = 1 if name in ('observedObjects', 'observedProjectFiles') else 0
        require(type(receipt.get(name)) is int and minimum <= receipt[name] <= limit,
                'target-observation-count-bound')
    require(expected_objects is None or receipt['observedObjects'] == expected_objects,
            'target-observation-object-count-differs')
    for name, limit in (('observedLinks', len(targets)), ('observedLinkInputs', dependencies.MAX_FILES),
                        ('observedSystemLinkInputs', dependencies.MAX_FILES)):
        require(type(receipt.get(name)) is int and 0 <= receipt[name] <= limit, 'target-observation-link-count-bound')
    require(expected_links is None or receipt['observedLinks'] == expected_links, 'target-observation-link-count-differs')
    require(receipt.get('linkElfMachines') == (sorted(set(machines)) if receipt['observedLinks'] else []),
            'target-observation-link-machine-policy-differs')
    root = Path(payload) / 'build/dependency-observation'
    rows = receipt.get('outputFiles')
    require(type(rows) is dict and 0 < len(rows) <= dependencies.MAX_FILES, 'target-observation-file-count-bound')
    for name, row in rows.items():
        content.safe_path(name); identity(row)
    actual = {p.relative_to(root).as_posix(): files.identity(p) for p in files.installed_files(root)}
    require(actual == {name: identity(row) for name, row in rows.items()}, 'target-observation-output-files-changed')
    observed, oid = modules.read_json(root / 'observation.json', limit=dependencies.MAX_TEXT)
    require(oid == identity(rows['observation.json']) and
            (observation_identity is None or oid == observation_identity), 'target-observation-exact-identity-required')
    require(observed.get('formatVersion') == 1 and observed.get('scope') == scope and
            observed.get('targets') == list(targets) and
            all(observed.get(k) is receipt.get(k) for k in TRUE_FLAGS + FALSE_FLAGS + LINK_TRUE_FLAGS + LINK_FALSE_FLAGS),
            'target-observation-document-scope-differs')
    objects, project, generated, system = [observed.get(k) for k in
                                         ('objects', 'projectFiles', 'generatedFiles', 'systemHeaders')]
    require(all(type(x) is dict for x in (objects, project, generated, system)) and
            len(objects) == receipt['observedObjects'] and len(project) == receipt['observedProjectFiles'] and
            len(generated) == receipt['observedGeneratedFiles'] and len(system) == receipt['observedSystemHeaders'] and
            hashlib.sha256(dependencies.encoded(objects)).hexdigest() == receipt.get('objectMetadataSha256'),
            'target-observation-count-or-object-metadata-differs')
    links, link_inputs, system_links = [observed.get(k) for k in ('links', 'linkInputs', 'systemLinkInputs')]
    require(all(type(x) is dict for x in (links, link_inputs, system_links)) and
            len(links) == receipt['observedLinks'] and len(link_inputs) == receipt['observedLinkInputs'] and
            len(system_links) == receipt['observedSystemLinkInputs'] and
            hashlib.sha256(dependencies.encoded(links)).hexdigest() == receipt.get('linkMetadataSha256'),
            'target-observation-link-count-or-metadata-differs')
    for name, row in project.items():
        content.safe_path(name)
        require(prepared_inventory.get(name) == identity(row), 'target-observation-project-source-changed')
    for name, row in generated.items():
        content.safe_path(name)
        require(Path(name).suffix in dependencies.HEADER_SUFFIXES | dependencies.SOURCE_SUFFIXES and
                files.identity(root / 'generated' / name) == identity(row), 'target-observation-generated-header-changed')
    require(set(rows) == {'observation.json', 'ninja-deps.txt', 'ninja-target-commands.txt'} |
            {'generated/' + name for name in generated}, 'target-observation-output-set-differs')
    for name, row in system.items():
        identity(row); path = Path(name)
        require(path.is_absolute() and '..' not in path.parts and
                any(dependencies.inside(path, p) for p in dependencies.SYSTEM_ROOTS),
                'target-observation-system-header-root-differs')
    commands, _ = modules.read_json(Path(payload) / 'build/commands.json', limit=dependencies.MAX_TEXT)
    require(type(commands) is list, 'target-observation-command-list-required')
    configure = [row.get('argv') for row in commands if type(row) is dict and row.get('phase') == 'configure']
    require(len(configure) == 1 and type(configure[0]) is list and
            all(type(x) is str for x in configure[0]) and configure[0].count('-B') == configure[0].count('-S') == 1,
            'target-observation-native-configure-paths')
    build = Path(configure[0][configure[0].index('-B') + 1])
    source = Path(configure[0][configure[0].index('-S') + 1])
    require(build.is_absolute() and source.is_absolute() and source.name == 'source' and
            '..' not in build.parts and '..' not in source.parts, 'target-observation-native-absolute-paths')
    prepared = source.parent
    raw, command_id = dependencies.text_file(Path(payload) / 'build/compile_commands.json')
    require(command_id == compile_commands == receipt.get('compileCommands'), 'target-observation-compile-commands-changed')
    database = dependencies.compile_database(raw, build)
    deps_raw, _ = dependencies.text_file(root / 'ninja-deps.txt')
    targets_raw, _ = dependencies.text_file(root / 'ninja-target-commands.txt')
    deps = dependencies.parse_dependencies(deps_raw.decode('utf-8'))
    target_commands = dependencies.target_commands(targets_raw.decode('utf-8'), build)
    link_commands = dependencies.link_commands(targets_raw.decode('utf-8'), build, targets=targets)
    require(not (set(objects) & set(links)) and set(objects) | set(links) == set(deps) and
            {str(build / n) for n in objects} == {str(p) for p in target_commands} and
            {str(build / n) for n in links} == {str(p) for p in link_commands},
            'target-observation-native-object-graph-differs')
    compiled = set(); used = {'project': set(), 'generated': set(), 'system': set()}
    for name, row in objects.items():
        content.safe_path(name); path = build / name
        require(type(row) is dict and path in database and database[path] == target_commands[path] and
                type(row.get('elfMachine')) is int and row['elfMachine'] in machines and
                row.get('source') == str(database[path]['source']) and
                row.get('compileCommandSha256') == hashlib.sha256(dependencies.encoded(database[path]['argv'])).hexdigest() and
                type(row.get('dependencyCount')) is int and row['dependencyCount'] == deps[name]['count'] and
                type(row.get('dependencies')) is list and row['dependencyCount'] == len(row['dependencies']) and
                row.get('ninjaDependenciesMtime') == deps[name]['mtime'] and
                type(row.get('objectMtimeNs')) is int and row['objectMtimeNs'] > 0,
                'target-observation-native-object-command-binding')
        identity(row['identity']); compiled.add(row['source'])
        for reference, raw_dependency in zip(row['dependencies'], deps[name]['dependencies']):
            require(type(reference) is str and ':' in reference, 'target-observation-malformed-reference')
            kind, key = reference.split(':', 1)
            require(kind in used and key in {'project': project, 'generated': generated, 'system': system}[kind],
                    'target-observation-object-dependency-outside-observation')
            lexical = dependencies.absolute(raw_dependency, build)
            if kind == 'project':
                require(lexical == prepared / key, 'target-observation-project-dependency-log-binding')
            elif kind == 'generated':
                require(lexical == build / key, 'target-observation-generated-dependency-log-binding')
            else:
                require(any(dependencies.inside(lexical, p) for p in dependencies.SYSTEM_ROOTS),
                        'target-observation-system-dependency-log-root')
            used[kind].add(key)
        source_path = Path(row['source'])
        if dependencies.inside(source_path, prepared):
            source_ref = 'project:' + source_path.relative_to(prepared).as_posix()
        else:
            require(dependencies.inside(source_path, build), 'target-observation-source-outside-owned-roots')
            source_ref = 'generated:' + source_path.relative_to(build).as_posix()
        require(source_ref in row['dependencies'], 'target-observation-compiled-unit-not-in-dependencies')
    require(all(used[k] == set(v) for k, v in (('project', project), ('generated', generated), ('system', system))),
            'target-observation-unused-entries')
    require({row['elfMachine'] for row in objects.values()} == set(machines),
            'target-observation-observed-machine-set-differs')
    for name, row in link_inputs.items():
        content.safe_path(name)
        require(type(row) is dict and row.get('kind') in ('object', 'archive'), 'target-observation-link-input-kind')
        value = identity(row['identity'])
        if row['kind'] == 'object':
            require(Path(name).suffix == '.o' and name in objects and value == identity(objects[name]['identity']),
                    'target-observation-local-link-object-differs')
        else:
            require(Path(name).suffix == '.a', 'target-observation-local-link-archive-differs')
    for name, row in system_links.items():
        identity(row); path = Path(name)
        require(path.is_absolute() and '..' not in path.parts and
                any(dependencies.inside(path, p) for p in dependencies.SYSTEM_LINK_ROOTS),
                'target-observation-system-link-input-root-differs')
    used_links = set(); used_system_links = set(); linked_programs = {}
    for name, row in links.items():
        content.safe_path(name); path = build / name
        require(type(row) is dict and path in link_commands and type(row.get('elfMachine')) is int and
                row['elfMachine'] in machines and row.get('elfType') in ('EXEC', 'DYN') and
                row.get('linkCommandSha256') == hashlib.sha256(dependencies.encoded(link_commands[path]['argv'])).hexdigest() and
                type(row.get('dependencyCount')) is int and row['dependencyCount'] == deps[name]['count'] and
                type(row.get('dependencies')) is list and row['dependencyCount'] == len(row['dependencies']) and
                row.get('ninjaDependenciesMtime') == deps[name]['mtime'] and
                type(row.get('outputMtimeNs')) is int and row['outputMtimeNs'] > 0,
                'target-observation-native-link-command-binding')
        linked_programs[Path(name).name] = identity(row['identity'])
        explicit_local = set(); skip = False
        for token in link_commands[path]['argv'][1:]:
            if skip: skip = False; continue
            if token == '-o': skip = True; continue
            if not token.startswith('-') and Path(token).suffix in ('.o', '.a'):
                value = dependencies.absolute(token, link_commands[path]['directory'])
                if dependencies.inside(value, build): explicit_local.add('build:' + value.relative_to(build).as_posix())
        require(explicit_local <= set(row['dependencies']), 'target-observation-explicit-local-link-input-missing')
        for ref, raw_dependency in zip(row['dependencies'], deps[name]['dependencies']):
            require(type(ref) is str and ':' in ref, 'target-observation-malformed-link-reference')
            kind, key = ref.split(':', 1); lexical = dependencies.absolute(raw_dependency, build)
            if kind == 'build':
                require(key in link_inputs and lexical == build / key, 'target-observation-build-link-dependency-binding')
                if link_inputs[key]['kind'] == 'object':
                    require(objects[key]['objectMtimeNs'] <= row['outputMtimeNs'],
                            'target-observation-link-object-newer-than-output')
                used_links.add(key)
            else:
                require(kind == 'system' and key in system_links and
                        any(dependencies.inside(lexical, p) for p in dependencies.SYSTEM_LINK_ROOTS),
                        'target-observation-system-link-dependency-binding')
                used_system_links.add(key)
    require(used_links == set(link_inputs) and used_system_links == set(system_links),
            'target-observation-unused-link-inputs')
    require(len(linked_programs) == len(links) and {r['elfMachine'] for r in links.values()} ==
            (set(machines) if links else set()), 'target-observation-observed-link-machine-or-name-set-differs')
    if required_link_programs is not None:
        require(type(required_link_programs) is dict and set(required_link_programs) == set(targets) and
                linked_programs == {n: identity(row) for n, row in required_link_programs.items()},
                'target-observation-selected-link-programs-differ')
    for name in required_sources:
        content.safe_path(name)
        require(str(prepared / name) in compiled, 'target-observation-required-unit-not-compiled')
    return dict(receipt=receipt, observation=oid, nativeBuildRoot=str(build), nativePreparedRoot=str(prepared),
        projectFiles=project, generatedFiles=generated, systemHeaderIdentities=system,
        links=links, linkInputIdentities=link_inputs, systemLinkInputIdentities=system_links,
        observedObjectMetadataReadback=True, originalObjectBytesIndependentlyReadback=False,
        observedLinkMetadataReadback=True, originalLinkInputBytesIndependentlyReadback=False,
        linkInputsCopied=False, systemLinkSourcesCopied=False,
        systemHeaderSourcesCopied=False, unknownOriginalSystemHashesCompared=False)
