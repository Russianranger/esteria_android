#!/usr/bin/env python3
"""Bind generated AC_MODULES_LIST options to the exact installed server binaries.

Compile commands are parsed as data, never executed. The exact module literal
must occur in both binaries; the config literal is consumed only by worldserver.
This establishes build selection, not module startup or database readiness.
"""
from __future__ import annotations

import argparse
import codecs
import hashlib
import json
from pathlib import Path
import re
import shlex

try:
    from . import manifest_server_content as content
    from . import verify_server_build as binaries
except ImportError:
    import manifest_server_content as content
    import verify_server_build as binaries

TARGETS = {'worldserver': '/src/server/apps/worldserver/Main.cpp',
           'dbimport': '/src/tools/dbimport/Main.cpp'}
MAX_COMMANDS = 256 * 1024 * 1024
MAX_ENTRY = 2 * 1024 * 1024
MAX_ENTRIES = 20000


def read_json(path, limit=16 * 1024 * 1024):
    with binaries.plain_file(path) as stream:
        raw = stream.read(limit + 1)
    content.require(len(raw) <= limit, 'JSON metadata limit')
    return json.loads(raw), {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def json_array(stream, identity):
    """Stream a compile_commands array, bounding one entry and total input."""
    utf8, decoder = codecs.getincrementaldecoder('utf-8')(), json.JSONDecoder()
    buffer, eof, total, count = '', False, 0, 0
    digest = hashlib.sha256()

    def fill():
        nonlocal buffer, eof, total
        data = stream.read(64 * 1024)
        total += len(data)
        content.require(total <= MAX_COMMANDS, 'compile commands total size limit')
        digest.update(data)
        eof = not data
        buffer += utf8.decode(data, final=eof)
        content.require(len(buffer) <= MAX_ENTRY + 65536, 'compile command entry size limit')

    def space():
        nonlocal buffer
        while True:
            buffer = buffer.lstrip()
            if buffer or eof:
                return
            fill()

    space()
    content.require(buffer.startswith('['), 'compile commands must be an array')
    buffer = buffer[1:]
    space()
    first = True
    while not buffer.startswith(']'):
        if not first:
            content.require(buffer.startswith(','), 'missing compile command separator')
            buffer = buffer[1:]
            space()
            content.require(not buffer.startswith(']'), 'trailing compile command separator')
        first = False
        while True:
            try:
                row, end = decoder.raw_decode(buffer)
                break
            except json.JSONDecodeError:
                content.require(not eof and len(buffer) <= MAX_ENTRY, 'malformed or oversized compile command')
                fill()
        content.require(isinstance(row, dict), 'compile command must be an object')
        count += 1
        content.require(count <= MAX_ENTRIES, 'compile command count limit')
        buffer = buffer[end:]
        yield row
        space()
    buffer = buffer[1:]
    space()
    content.require(eof and not buffer, 'trailing compile commands data')
    identity.update(bytes=total, sha256=digest.hexdigest())


def macro_value(row, name):
    args = row.get('arguments')
    if args is None:
        content.require(isinstance(row.get('command'), str), 'compile command lacks arguments/command')
        args = shlex.split(row['command'], posix=True)
    content.require(isinstance(args, list) and all(isinstance(x, str) for x in args), 'invalid compiler arguments')
    values = []
    for i, arg in enumerate(args):
        candidate = args[i + 1] if arg == '-D' and i + 1 < len(args) else arg[2:] if arg.startswith('-D') else ''
        if candidate.startswith(name + '='):
            value = candidate[len(name) + 1:]
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            content.require('"' not in value and '\\' not in value, 'unexpected macro quoting')
            values.append(value)
    content.require(len(values) == 1, f'missing or duplicate {name}')
    return values[0]


def names(value, config=False):
    content.require(value.endswith(',') and len(value) <= 32768, 'expected bounded CMake trailing-comma list')
    result = value[:-1].split(',')
    pattern = r'[A-Za-z0-9_.-]+\.conf' if config else r'[A-Za-z0-9_-]+'
    content.require(result and all(re.fullmatch(pattern, name) for name in result), 'invalid generated names')
    content.require(len(result) == len(set(result)), 'duplicate generated names')
    return result


def extract_commands(path):
    targets, identity = {}, {}
    with binaries.plain_file(path) as stream:
        for row in json_array(stream, identity):
            filename = row.get('file', '').replace('\\', '/')
            for target, suffix in TARGETS.items():
                if filename.endswith(suffix):
                    content.require(target not in targets, 'duplicate target compile command')
                    modules = macro_value(row, 'AC_MODULES_LIST')
                    configs = macro_value(row, 'CONFIG_FILE_LIST')
                    targets[target] = {'modules': names(modules), 'configFiles': names(configs, True),
                                       'moduleLiteral': modules, 'configLiteral': configs}
    content.require(set(targets) == set(TARGETS), 'both worldserver and dbimport compile commands required')
    content.require(targets['worldserver'] == targets['dbimport'], 'worldserver/dbimport module selection differs')
    return targets['worldserver'], identity


def verify_literals(path, expected, literals):
    # C literals require a trailing terminator, not a leading NUL: compilers
    # may pool suffixes or place nonzero rodata immediately before the literal.
    # Selection provenance comes from compile commands + the source-verified,
    # hash-matched build receipt, not standalone inference from binary strings.
    needles = [(value + '\0').encode('ascii') for value in literals]
    maximum = max(map(len, needles))
    found, tail, total, digest = [False] * len(needles), b'', 0, hashlib.sha256()
    with binaries.plain_file(path) as stream:
        while block := stream.read(content.CHUNK):
            total += len(block)
            content.require(total <= expected['bytes'], 'server binary grew beyond receipt')
            digest.update(block)
            window = tail + block
            found = [seen or needle in window for seen, needle in zip(found, needles)]
            tail = window[-maximum + 1:]
    content.require(total == expected['bytes'] and digest.hexdigest() == expected['sha256'], 'server binary receipt mismatch')
    content.require(all(found), 'generated module/config literal absent from installed binary')
    return dict(expected, generatedLiteralsPresent=True)


def verify(compile_commands, install, build_path):
    build, build_identity = read_json(build_path)
    content.require(build.get('schemaVersion') == 1 and build.get('architecture') == 'Linux-ARM64' and
                    build.get('sourceCheckoutAndPatchesVerified') is True, 'unverified server build receipt')
    selection, commands_identity = extract_commands(compile_commands)
    files = {row['path']: row for row in build['files']}
    evidence = {}
    for target in TARGETS:
        name = 'bin/' + target
        content.require(name in files, 'required executable missing from build receipt')
        row = files[name]
        content.require(row.get('elf', {}).get('machine') == 'AArch64', 'server target is not verified ARM64')
        expected = {key: row[key] for key in ('bytes', 'sha256')}
        literals = (selection['moduleLiteral'],)
        if target == 'worldserver':
            literals += (selection['configLiteral'],)
        evidence[target] = verify_literals(install / name, expected, literals)
    return dict(formatVersion=1, scope='compiled-server-module-selection',
                source=build['serverSource'], sourceLockSha256=build['sourcesLock']['sha256'],
                serverBuild=build_identity, compileCommands=commands_identity,
                enabledModules=selection['modules'], configFiles=selection['configFiles'],
                generatedListsMatchInstalledBinaries=True, binaries=evidence,
                sqlExecuted=False, moduleStartupQualified=False, androidRuntimeQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-commands', type=Path, required=True)
    parser.add_argument('--install', type=Path, required=True)
    parser.add_argument('--server-build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    document = verify(args.compile_commands, args.install, args.server_build)
    content.atomic_output(args.output, document)
    print(json.dumps(dict(modules=len(document['enabledModules']), configs=len(document['configFiles']),
                          generatedListsMatchInstalledBinaries=True, sqlExecuted=False)))


if __name__ == '__main__':
    main()
