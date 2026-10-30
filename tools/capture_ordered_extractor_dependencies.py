#!/usr/bin/env python3
"""Observe actual ordered-target objects and their Ninja source dependencies.

``run(argv, label, timeout)`` must run the command through the caller's bounded
process owner, raise on nonzero exit, and return the Path of its complete stdout
log. This module reads and copies those logs into a fresh output directory. It
does not run a compiler, copy objects/ELFs, or supply a source-completeness claim.
The caller establishes the fresh native build, exact recipes and ABI environment.
An explicit safe ``targets`` tuple may select another closed native component;
the default remains the two ordered extractors with identical checks.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat

MAX_TEXT = 64 << 20
MAX_FILE = 64 << 20
MAX_OBJECTS = 5000
MAX_FILES = 30000
MAX_EDGES = 1000000
MAX_GENERATED = 128 << 20
TARGETS = ('map_extractor', 'vmap4_extractor')
SYSTEM_ROOTS = (Path('/usr/include'), Path('/usr/lib/gcc'))
SYSTEM_LINK_ROOTS = (Path('/usr/lib'), Path('/lib'), Path('/usr/lib64'), Path('/lib64'))
HEADER_SUFFIXES = {'.h', '.hh', '.hpp', '.hxx', '.inc', '.inl', '.tcc'}
SOURCE_SUFFIXES = {'.c', '.cc', '.cpp', '.cxx', '.C'}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def absolute(value, base=None):
    value = Path(value)
    require(not any(c in str(value) for c in '\x00\r\n\t'), 'invalid observed dependency path')
    return Path(os.path.abspath((base / value) if base is not None and not value.is_absolute() else value))


def canonical_directory(value):
    value = absolute(value)
    require(value == value.resolve(strict=True) and value.is_dir(), 'canonical observation directory required')
    return value


def inside(path, root):
    return path == root or root in path.parents


def unlinked(path):
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor /= part
        require(not stat.S_ISLNK(cursor.lstat().st_mode), 'linked project or object input refused')


def identity(path):
    require(stat.S_ISREG(path.lstat().st_mode), 'regular observed input required')
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        require(0 <= before.st_size <= MAX_FILE, 'observed input byte bound')
        digest = hashlib.sha256(); count = 0
        while block := stream.read(128 << 10):
            count += len(block); require(count <= MAX_FILE, 'observed input grew beyond bound')
            digest.update(block)
        after = os.fstat(stream.fileno())
    keys = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    require(count == before.st_size and all(getattr(before, k) == getattr(after, k) for k in keys),
            'observed input changed during hashing')
    return dict(bytes=count, sha256=digest.hexdigest())


def text_file(path):
    path = absolute(path); unlinked(path)
    row = identity(path)
    require(row['bytes'] <= MAX_TEXT, 'observation text byte bound')
    raw = path.read_bytes()
    require(dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) == row, 'observation log changed')
    return raw, row


def parse_dependencies(text):
    records = {}; current = None; edges = 0
    header = re.compile(r'^(.*): #deps ([0-9]+), deps mtime ([0-9]+) \(([^)]+)\)$')
    def finish():
        if current is not None:
            # Ninja/GCC can report a repeated include spelling. Preserve its raw
            # count; identities are closed separately by canonical dependency path.
            require(len(current['dependencies']) == current['count'],
                    'Ninja dependency count differs: declared='+str(current['count'])+
                    ' observed='+str(len(current['dependencies'])))
    for line in text.splitlines():
        if not line:
            continue
        match = header.fullmatch(line)
        if match:
            finish(); name, count, mtime, state = match.groups()
            require(state == 'VALID', 'stale Ninja dependency record refused')
            require(name and name not in records and 0 < int(count) <= MAX_FILES, 'duplicate or invalid Ninja object')
            current = dict(count=int(count), mtime=int(mtime), dependencies=[])
            records[name] = current
            require(len(records) <= MAX_OBJECTS, 'Ninja object count bound')
        else:
            require(current is not None and line.startswith('    ') and line[4:], 'malformed Ninja dependency output')
            current['dependencies'].append(line[4:]); edges += 1
            require(edges <= MAX_EDGES, 'Ninja dependency edge bound')
    finish(); require(records, 'Ninja reported no built objects')
    return records


def arguments(value):
    require(type(value) is list and value and all(type(v) is str and v for v in value), 'compiler argument list required')
    require(not any(v in ('&&', '||', ';', '|', '>', '<') for v in value), 'unsupported shell compiler command')
    return value


def compiler_io(argv, directory):
    require(argv.count('-c') == 1 and argv.count('-o') == 1, 'unambiguous compiler -c and -o required')
    c, o = argv.index('-c'), argv.index('-o')
    require(c + 1 < len(argv) and o + 1 < len(argv), 'incomplete compiler source or object')
    return absolute(argv[c + 1], directory), absolute(argv[o + 1], directory)


def normalized_command(argv):
    """CMake omits GCC dependency-file bookkeeping from its compile database."""
    result = []; position = 0
    while position < len(argv):
        token = argv[position]
        if token in ('-MD', '-MMD', '-MP'):
            position += 1; continue
        if token in ('-MF', '-MT', '-MQ'):
            require(position + 1 < len(argv), 'incomplete compiler dependency option')
            position += 2; continue
        result.append(token); position += 1
    return result


def compile_database(raw, build):
    def unique(rows):
        result = {}
        for key, value in rows:
            require(key not in result, 'duplicate compile database JSON field')
            result[key] = value
        return result
    values = json.loads(raw, object_pairs_hook=unique)
    require(type(values) is list and 0 < len(values) <= 10000, 'compile database row bound')
    result = {}
    for row in values:
        require(type(row) is dict and type(row.get('directory')) is str and type(row.get('file')) is str,
                'compile database row required')
        directory = absolute(row['directory'])
        require(inside(directory, build), 'compiler directory is outside owned build')
        if 'arguments' in row:
            argv = arguments(row['arguments'])
        else:
            require(type(row.get('command')) is str, 'compile database command required')
            argv = arguments(shlex.split(row['command']))
        source, output = compiler_io(argv, directory)
        require(source == absolute(row['file'], directory) and inside(output, build), 'compile database source/object differs')
        if 'output' in row:
            require(type(row['output']) is str and absolute(row['output'], directory) == output,
                    'compile database declared object differs')
        require(output not in result, 'duplicate compile database object')
        result[output] = dict(source=source, directory=directory, argv=normalized_command(argv))
    return result


def target_commands(text, build):
    result = {}
    for line in text.splitlines():
        if not line:
            continue
        require(len(line.encode()) <= 1 << 20, 'Ninja command line bound')
        argv = shlex.split(line); directory = build
        if len(argv) >= 3 and argv[0] == 'cd' and argv[2] == '&&':
            directory = absolute(argv[1], build); argv = argv[3:]
        if '-c' not in argv or '-o' not in argv:
            continue
        argv = arguments(argv)
        source, output = compiler_io(argv, directory)
        require(inside(directory, build) and inside(output, build) and output not in result,
                'Ninja compiler object is duplicate or outside owned build')
        result[output] = dict(source=source, directory=directory, argv=normalized_command(argv))
        require(len(result) <= MAX_OBJECTS, 'Ninja target command count bound')
    require(result, 'Ninja target graph has no compiler commands')
    return result


def link_commands(text, build, targets=TARGETS):
    """Parse explicit GCC/Clang LD-depfile commands without executing a shell.

    CMake wraps a link in ``: && driver ... && :``. Only that exact wrapper
    and an optional leading ``cd directory &&`` are accepted. Link commands
    without an LD depfile remain outside this observation (legacy fixtures).
    A raw linker dependency record without its explicit command is refused.
    """
    result = {}
    driver = re.compile(r'(?:(?:[A-Za-z0-9_+.]+)-)*(?:gcc|g\+\+|cc|c\+\+|clang|clang\+\+)(?:-[0-9]+(?:\.[0-9]+)*)?')
    for line in text.splitlines():
        if not line: continue
        require(len(line.encode()) <= 1 << 20, 'Ninja link command line bound')
        argv = shlex.split(line); directory = build
        if len(argv) >= 3 and argv[0] == 'cd' and argv[2] == '&&':
            directory = absolute(argv[1], build); argv = argv[3:]
        flags = [token for token in argv if token.startswith('-Wl,--dependency-file')]
        if not flags: continue
        if argv[:2] == [':', '&&']:
            require(argv[-2:] == ['&&', ':'], 'unsupported Ninja link shell wrapper')
            argv = argv[2:-2]
        arguments(argv)
        require(len(flags) == 1 and flags[0].startswith('-Wl,--dependency-file=') and
                flags[0] != '-Wl,--dependency-file=' and '-c' not in argv and argv.count('-o') == 1 and
                Path(argv[0]).is_absolute() and driver.fullmatch(Path(argv[0]).name),
                'explicit compiler driver link command required')
        position = argv.index('-o'); require(position+1 < len(argv), 'link output argument missing')
        output = absolute(argv[position+1], directory)
        depfile = absolute(flags[0].split('=', 1)[1], directory)
        require(inside(directory, build) and inside(output, build) and output.name in targets and
                inside(depfile, build) and output != depfile and output not in result,
                'owned unique selected linked target and depfile required')
        result[output] = dict(directory=directory, argv=argv, dependencyFile=depfile)
        require(len(result) <= len(targets), 'Ninja selected link command count bound')
    return result


def write_new(path, raw):
    require(len(raw) <= MAX_TEXT, 'dependency observation metadata byte bound')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    path.chmod(0o444)


def capture(build: Path, prepared: Path, commands: Path, ninja: Path, run, output: Path, *, targets=TARGETS):
    """Return a typed observation receipt; ``output`` contains source-only evidence.

    The returned receipt inventories every output file. It is returned to the
    caller for inclusion in its build receipt, avoiding a self-referential file
    inventory. Project inputs and system headers are hashed separately; system
    sources are not copied and unknown original system hashes are not compared.
    """
    require(type(targets) is tuple and 0 < len(targets) <= 8 and
            all(type(name) is str and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_+.-]{0,127}',name) for name in targets) and
            len(set(targets)) == len(targets),
            'explicit safe target tuple required')
    scope='actual-ordered-target-source-and-dependency-observation' if targets==TARGETS else 'actual-target-source-and-dependency-observation'
    build, prepared = canonical_directory(build), canonical_directory(prepared)
    commands, ninja, output = absolute(commands), absolute(ninja), absolute(output)
    require(callable(run) and not os.path.lexists(output), 'fresh dependency observation output required')
    require(all(not inside(output, root) and not inside(root, output) for root in (build, prepared)) and
            not inside(commands, output), 'dependency observation output overlaps inputs')
    canonical_directory(output.parent); unlinked(ninja)
    require(os.access(ninja, os.X_OK), 'executable Ninja required')
    ninja_identity = identity(ninja)
    database_raw, database_identity = text_file(commands)
    database = compile_database(database_raw, build)
    output.mkdir(mode=0o700)
    deps_path = Path(run([str(ninja), '-C', str(build), '-t', 'deps'], 'ordered-ninja-deps', 120))
    command_path = Path(run([str(ninja), '-C', str(build), '-t', 'commands', *targets], 'ordered-ninja-commands', 120))
    deps_raw, deps_identity = text_file(deps_path); command_raw, command_identity = text_file(command_path)
    write_new(output / 'ninja-deps.txt', deps_raw); write_new(output / 'ninja-target-commands.txt', command_raw)
    records = parse_dependencies(deps_raw.decode('utf-8'))
    target = target_commands(command_raw.decode('utf-8'), build)
    linked_targets = link_commands(command_raw.decode('utf-8'), build, targets)
    observed = {}; objects = {}; project = {}; generated = {}; system = {}; machines = set()
    links = {}; link_inputs = {}; system_links = {}; link_machines = set(); observed_links = {}; link_mtime_bounds = {}
    dependency_mtime_bounds = {}
    roots = {name: canonical_directory(prepared / name) for name in ('source', 'external', 'integration')}

    def dependency(value):
        lexical = absolute(value, build); resolved = lexical.resolve(strict=True)
        for name, root in roots.items():
            if inside(lexical, root):
                unlinked(lexical); require(resolved == lexical, 'linked project dependency refused')
                key = name + '/' + lexical.relative_to(root).as_posix(); group = project; kind = 'project'
                break
        else:
            if inside(lexical, build):
                unlinked(lexical); require(resolved == lexical and
                    (lexical.suffix in HEADER_SUFFIXES or lexical.suffix in SOURCE_SUFFIXES),
                    'unsupported generated build dependency')
                key = lexical.relative_to(build).as_posix(); group = generated; kind = 'generated'
            else:
                require(any(inside(resolved, root) for root in SYSTEM_ROOTS), 'unknown non-system dependency root')
                key = str(resolved); group = system; kind = 'system'
        # Rehash each unique input at completion; repeated include edges need
        # not read the same large system header for every translation unit.
        row = observed.get(resolved)
        if row is None:
            row = identity(resolved)
            observed[resolved] = row
        require(len(observed) <= MAX_FILES, 'observed dependency file count bound')
        group[key] = row
        return kind + ':' + key, resolved

    for name, record in records.items():
        path = absolute(name, build); unlinked(path)
        if path in linked_targets:
            continue
        require(inside(path, build) and path not in objects and path in database and path in target,
                'Ninja built object has no unique owned compile command')
        declared, actual = database[path], target[path]
        require(declared == actual, 'Ninja target command differs from compile database')
        object_mtime = path.stat().st_mtime_ns
        source = declared['source'].resolve(strict=True)
        references = []; paths = set()
        for value in record['dependencies']:
            reference, resolved = dependency(value)
            require(resolved.stat().st_mtime_ns <= object_mtime,
                    'dependency newer than compiled object; replay target build')
            dependency_mtime_bounds[resolved] = min(dependency_mtime_bounds.get(resolved, object_mtime), object_mtime)
            references.append(reference); paths.add(resolved)
        require(source in paths and any(inside(source, root) for root in (*roots.values(), build)),
                'compiled source is absent from owned observed dependencies')
        row = identity(path)
        with path.open('rb') as stream:
            header = stream.read(20)
        require(len(header) == 20 and header[:6] == b'\x7fELF\x02\x01' and header[16:18] == b'\x01\x00',
                'observed compiler output is not an ELF64 relocatable object')
        machine = int.from_bytes(header[18:20], 'little'); machines.add(machine)
        objects[path] = dict(identity=row, source=str(source), elfMachine=machine,
            compileCommandSha256=hashlib.sha256(encoded(declared['argv'])).hexdigest(),
            dependencyCount=record['count'], ninjaDependenciesMtime=record['mtime'], objectMtimeNs=object_mtime,
            dependencies=references)
    require(set(objects) == set(target), 'Ninja target graph and built dependency objects differ')

    def link_dependency(value):
        lexical = absolute(value, build); resolved = lexical.resolve(strict=True)
        if inside(lexical, build):
            unlinked(lexical)
            require(resolved == lexical and lexical.suffix in ('.o', '.a'), 'unsupported owned linker input')
            kind = 'object' if lexical.suffix == '.o' else 'archive'
            row = observed_links.get(resolved)
            if row is None: row = identity(resolved); observed_links[resolved] = row
            if kind == 'object':
                require(resolved in objects and objects[resolved]['identity'] == row,
                        'linked object was not observed in actual compiler graph')
            else:
                with resolved.open('rb') as stream:
                    require(stream.read(8) == b'!<arch>\n', 'linked local archive is not a regular ar archive')
            key = lexical.relative_to(build).as_posix(); link_inputs[key] = dict(identity=row, kind=kind)
            reference = 'build:'+key
        else:
            require(any(inside(lexical, root) for root in SYSTEM_LINK_ROOTS) and
                    any(inside(resolved, root) for root in SYSTEM_LINK_ROOTS), 'unknown system linker input root')
            unlinked(resolved)
            row = observed_links.get(resolved)
            if row is None: row = identity(resolved); observed_links[resolved] = row
            key = str(resolved); system_links[key] = row; reference = 'system:'+key
        require(len(observed_links) <= MAX_FILES, 'observed linker input count bound')
        return reference, resolved

    for name, record in records.items():
        path = absolute(name, build)
        if path not in linked_targets: continue
        require(path not in links, 'duplicate normalized linked output')
        declared = linked_targets[path]; output_mtime = path.stat().st_mtime_ns
        references = []; paths = set()
        for value in record['dependencies']:
            reference, resolved = link_dependency(value)
            require(resolved.stat().st_mtime_ns <= output_mtime,
                    'link dependency newer than linked output; replay target build')
            link_mtime_bounds[resolved] = min(link_mtime_bounds.get(resolved, output_mtime), output_mtime)
            references.append(reference); paths.add(resolved)
        # Inputs spelled explicitly in the command must also occur in the LD
        # record; driver-selected runtime libraries remain additional evidence.
        skip = False
        for token in declared['argv'][1:]:
            if skip: skip = False; continue
            if token == '-o': skip = True; continue
            if not token.startswith('-') and (Path(token).suffix in ('.o', '.a') or '.so' in Path(token).name):
                require(absolute(token, declared['directory']).resolve(strict=True) in paths,
                        'explicit linker command input absent from dependency record')
        row = identity(path)
        with path.open('rb') as stream: header = stream.read(20)
        require(len(header) == 20 and header[:6] == b'\x7fELF\x02\x01' and header[16:18] in (b'\x02\x00', b'\x03\x00'),
                'observed linked output is not an ELF64 executable or dynamic executable')
        machine = int.from_bytes(header[18:20], 'little'); link_machines.add(machine)
        require(machine in machines, 'linked output machine differs from compiled objects')
        links[path] = dict(identity=row, elfMachine=machine, elfType='EXEC' if header[16:18] == b'\x02\x00' else 'DYN',
            linkCommandSha256=hashlib.sha256(encoded(declared['argv'])).hexdigest(),
            dependencyCount=record['count'], ninjaDependenciesMtime=record['mtime'], outputMtimeNs=output_mtime,
            dependencies=references)
    require(set(links) == set(linked_targets) and len(records) == len(objects)+len(links),
            'Ninja link target graph and dependency records differ')
    generated_bytes = 0
    for name, row in generated.items():
        path = build / name; generated_bytes += row['bytes']
        require(generated_bytes <= MAX_GENERATED, 'generated observation copy byte bound')
        with path.open('rb') as stream:
            require(stream.read(4) != b'\x7fELF', 'ELF in generated source observation')
        raw, copied = text_file(path); require(copied == row, 'generated dependency changed before copy')
        write_new(output / 'generated' / name, raw)
    for path, row in observed.items():
        require(identity(path) == row, 'observed dependency changed before completion')
        require(path.stat().st_mtime_ns <= dependency_mtime_bounds[path],
                'dependency newer than compiled object; replay target build')
    for path, row in objects.items():
        require(identity(path) == row['identity'] and path.stat().st_mtime_ns == row['objectMtimeNs'],
                'observed object changed before completion')
    for path, row in observed_links.items():
        require(identity(path) == row, 'observed linker input changed before completion')
        require(path.stat().st_mtime_ns <= link_mtime_bounds[path],
                'link dependency newer than linked output; replay target build')
    for path, row in links.items():
        require(identity(path) == row['identity'] and path.stat().st_mtime_ns == row['outputMtimeNs'],
                'observed linked output changed before completion')
    require(text_file(commands)[1] == database_identity and text_file(deps_path)[1] == deps_identity and
            text_file(command_path)[1] == command_identity and identity(ninja) == ninja_identity,
            'observation command inputs changed before completion')
    object_rows = {path.relative_to(build).as_posix(): value for path, value in objects.items()}
    link_rows = {path.relative_to(build).as_posix(): value for path, value in links.items()}
    observation = dict(formatVersion=1, scope=scope,
        targets=list(targets), objects=object_rows, projectFiles=project, generatedFiles=generated, systemHeaders=system,
        links=link_rows, linkInputs=link_inputs, systemLinkInputs=system_links,
        linkDependenciesNotNewerThanOutput=True, linkInputsCopied=False, systemLinkSourcesCopied=False,
        actualTargetSourceDependencyObservation=True, dependencyIdentitiesObservedAfterBuild=True,
        dependenciesNotNewerThanObject=True, systemHeaderSourcesCopied=False,
        unknownOriginalSystemHashesCompared=False, sourceCompanionComplete=False,
        androidRuntimeQualified=False, customEsteriaDataLoadOrderQualified=False, worldQualified=False, gameplayQualified=False)
    write_new(output / 'observation.json', encoded(observation))
    inventory = {path.relative_to(output).as_posix(): identity(path) for path in sorted(output.rglob('*')) if path.is_file()}
    return dict(formatVersion=1, scope=observation['scope'], targets=list(targets), compileCommands=database_identity,
        ninja=dict(path=str(ninja), **ninja_identity), observedObjects=len(objects), observedProjectFiles=len(project),
        observedGeneratedFiles=len(generated), observedSystemHeaders=len(system), objectElfMachines=sorted(machines),
        observedLinks=len(links), observedLinkInputs=len(link_inputs), observedSystemLinkInputs=len(system_links),
        linkElfMachines=sorted(link_machines), linkMetadataSha256=hashlib.sha256(encoded(link_rows)).hexdigest(),
        linkDependenciesNotNewerThanOutput=True, linkInputsCopied=False, systemLinkSourcesCopied=False,
        objectMetadataSha256=hashlib.sha256(encoded(object_rows)).hexdigest(), outputFiles=inventory,
        actualTargetSourceDependencyObservation=True, dependencyIdentitiesObservedAfterBuild=True,
        dependenciesNotNewerThanObject=True, systemHeaderSourcesCopied=False,
        unknownOriginalSystemHashesCompared=False, sourceCompanionComplete=False,
        androidRuntimeQualified=False, customEsteriaDataLoadOrderQualified=False, worldQualified=False, gameplayQualified=False)
