#!/usr/bin/env python3
"""Fixed debug guest entry for separately measured original x64 setup tools.

Only a pinned debug helper generation packages this module and its generated
installation-x64-inputs.json. That companion pins the closed programs receipt;
neither the CLI nor the production ARM64 entry accepts a policy or caller path.
The host provider gate verifies full source/debug and independent native SQL
readback before packaging. This guest rechecks the original ELF/library bytes,
their distinct Android invocations and the native receipt before real shared
installation work. It grants no Android, world or gameplay qualification.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import struct
import sys

try:
    from runtime import android_server_installation_setup as installation
except ImportError:
    import android_server_installation_setup as installation

playerbots = installation.playerbots
require = installation.require
GUEST = '/esteria-server-programs'
ROLES = {'dbimport': ('bin/dbimport', 'bin/dbimport.elf'),
    'playerbots-schema': ('helpers/playerbots-schema', 'helpers/playerbots-schema.elf')}
LOADER = 'lib64/ld-linux-x86-64.so.2'
POSITIVE = ('qualificationSucceeded', 'selectedX64ToolsSqlQualified', 'sqlExecuted',
    'initializedNewInstance', 'actualCoreCompositionCompleted', 'completedJournalReentryWithoutExecution',
    'actualLoaderReentryVerified', 'restartPersistenceVerified', 'fixtureProbeRemoved',
    'exactSourceUpdateLedgerVerified', 'finalFourSchemaProductVerification',
    'coreSchemasLedgersCredentialsAccountPreserved', 'cleanShutdownVerified',
    'capturedLoaderAndLibraryCompatibilityQualified')
FALSE_FLAGS = ('androidRuntimeQualified', 'productionArm64ProviderQualified', 'fourSchemaCoordinatorQualified',
    'worldserverQualified', 'playerbotsAiQualified', 'gameplayQualified', 'slotPromoted', 'serverDataQualified')


def _pin(row, maximum=2 << 20):
    require(type(row) is dict and set(row) == {'bytes', 'sha256'} and type(row['bytes']) is int and
        0 < row['bytes'] <= maximum and type(row['sha256']) is str and re.fullmatch('[a-f0-9]{64}', row['sha256']),
        'Installation x64 exact artifact identity required')
    return dict(row)


def _scalar(row, maximum=2 << 20):
    require(type(row) is dict and {'bytes', 'sha256'} <= set(row), 'Installation x64 identity missing')
    return _pin({key: row[key] for key in ('bytes', 'sha256')}, maximum)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Installation x64 duplicate metadata field')
        result[key] = value
    return result


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
        info.st_mtime_ns, info.st_ctime_ns)


def _checked(path, wanted=None, *, maximum=2 << 20, capture=False, executable=False, elf=False):
    """Hash the same bounded plain FD that is parsed, with a fresh path check."""
    path = Path(path)
    if wanted is not None: wanted = _pin(wanted, maximum)
    digest = hashlib.sha256(); chunks = []; count = 0
    with installation.updates.updater.plain_file(path) as stream:
        before = os.fstat(stream.fileno())
        require(0 < before.st_size <= maximum and before.st_nlink == 1 and
            (not executable or before.st_mode & 0o111) and
            (wanted is None or before.st_size == wanted['bytes']), 'Installation x64 file bound or mode differs')
        while block := stream.read(min(128 << 10, before.st_size + 1 - count)):
            count += len(block)
            require(count <= before.st_size, 'Installation x64 file grew')
            digest.update(block)
            if capture: chunks.append(block)
        result = _elf(stream, before.st_size) if elf else None
        after = os.fstat(stream.fileno())
    identity = dict(bytes=count, sha256=digest.hexdigest())
    require(count == before.st_size and (wanted is None or wanted == identity) and
        _stamp(before) == _stamp(after) == _stamp(path.lstat()), 'Installation x64 artifact changed')
    return identity, b''.join(chunks) if capture else result


def _json(path, pin=None, maximum=2 << 20):
    identity, raw = _checked(path, pin, maximum=maximum, capture=True)
    return json.loads(raw, object_pairs_hook=_unique), identity


def _elf(stream, size):
    stream.seek(0); raw = stream.read(64)
    require(len(raw) == 64 and raw[:7] == b'\x7fELF\x02\x01\x01', 'Installation x64 ELF64 required')
    kind, machine, version = struct.unpack_from('<HHI', raw, 16)
    offset = struct.unpack_from('<Q', raw, 32)[0]; header, entry, count = struct.unpack_from('<HHH', raw, 52)
    require(kind in (2, 3) and machine == 62 and version == 1 and header == 64 and entry == 56 and
        0 < count <= 8192 and 64 <= offset <= size and count * entry <= size - offset,
        'Installation x64 original ELF62 program table required')
    stream.seek(offset); table = stream.read(count * entry); loads = 0; interpreter = None
    require(len(table) == count * entry, 'Installation x64 ELF program table truncated')
    for start in range(0, len(table), entry):
        tag, _, position, _, _, length, memory, _ = struct.unpack_from('<IIQQQQQQ', table, start)
        require(position <= size and length <= size - position and (tag != 1 or length <= memory),
            'Installation x64 ELF segment exceeds file')
        if tag == 1: loads += 1
        if tag == 3:
            require(interpreter is None and 2 <= length <= 256, 'Installation x64 ELF interpreter bound')
            stream.seek(position); value = stream.read(length)
            require(value.endswith(b'\0') and b'\0' not in value[:-1], 'Installation x64 ELF interpreter termination')
            interpreter = value[:-1].decode('ascii')
    require(loads > 0 and interpreter in (None, '/lib64/ld-linux-x86-64.so.2'),
        'Installation x64 ELF loader differs')
    return dict(machine=62, elfClass=2, interpreter=interpreter, loadSegments=loads)


LAUNCHER = '''#!/usr/bin/python3
import hashlib,json,os,stat,sys
PLAN=json.loads(@@PLAN@@)
def refuse():
    sys.stderr.write('installation-x64-checked-loader-refused\\n');raise SystemExit(98)
def checked(path,pin):
    if not os.path.isabs(path) or os.path.realpath(path)!=path:refuse()
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=pin['bytes']:refuse()
        digest=hashlib.sha256();count=0
        while True:
            block=os.read(descriptor,131072)
            if not block:break
            count+=len(block)
            if count>before.st_size:refuse()
            digest.update(block)
        after=os.fstat(descriptor);current=os.stat(path,follow_symlinks=False)
        stamp=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns,value.st_nlink)
        if count!=before.st_size or stamp(before)!=stamp(after) or stamp(before)!=stamp(current) or digest.hexdigest()!=pin['sha256']:refuse()
    finally:os.close(descriptor)
if len(sys.argv)!=3 or sys.argv[1]!='--config' or not os.path.isabs(sys.argv[2]) or os.path.realpath(sys.argv[2])!=sys.argv[2]:refuse()
configuration=os.stat(sys.argv[2],follow_symlinks=False)
if not stat.S_ISREG(configuration.st_mode) or configuration.st_nlink!=1 or configuration.st_mode&0o077:refuse()
for path,pin in PLAN['files'].items():checked(path,pin)
if any(name.startswith('LD_') for name in os.environ):refuse()
os.execv(PLAN['loader'],[PLAN['loader'],'--library-path',PLAN['libraryPath'],PLAN['executable'],*sys.argv[1:]])
'''


def invocation_source(build, role):
    """Canonical Android invocation bytes, also used by the host provider builder."""
    require(role in ROLES, 'Installation x64 invocation role differs')
    _, actual = ROLES[role]; libraries = build.get('libraries')
    require(type(libraries) is dict and LOADER in libraries and 1 <= len(libraries) <= 128,
        'Installation x64 captured loader closure required')
    selected = {GUEST + '/' + actual: _scalar(build['executables'][role], 2 << 30),
        GUEST + '/libexec/ld-linux-x86-64.so.2': _scalar(libraries[LOADER], 512 << 20)}
    for name, row in libraries.items():
        require(type(name) is str and re.fullmatch(r'(?:usr/lib/x86_64-linux-gnu|lib64)/[A-Za-z0-9_+.-]{1,128}', name)
            and Path(name).name not in ('.', '..'), 'Installation x64 captured library path differs')
        selected[GUEST + '/libraries/' + name] = _scalar(row, 512 << 20)
    plan = dict(formatVersion=1, scope='android-x64-checked-original-setup-elf-invocation', role=role,
        executable=GUEST + '/' + actual, loader=GUEST + '/libexec/ld-linux-x86-64.so.2',
        libraryPath=GUEST + '/libraries/usr/lib/x86_64-linux-gnu:' + GUEST + '/libraries/lib64', files=selected)
    return LAUNCHER.replace('@@PLAN@@', repr(json.dumps(plan, sort_keys=True, separators=(',', ':')))).encode()


@dataclass(frozen=True)
class _Inputs:
    root: Path
    authority: Path
    authority_identity: dict
    closure: dict
    build: dict
    native: dict

    def verify(self, verified=None, *, version=None):
        fresh = _admit(self.root, self.authority, expected_authority=self.authority_identity)
        if verified is not None:
            require(isinstance(verified, installation.packaged.VerifiedContent) and
                fresh.closure['sourceOrigin'] == dict(originalBuild=verified.compiled['serverBuild'],
                    compiledModules=verified.receipt['compiledModules'],
                    sourceLock=fresh.build['sourceLock'], source=verified.manifest['source']) and
                fresh.build['sourceLock']['sha256'] == verified.receipt['sourceLockSha256'] and
                fresh.native['contentReceipt'] == verified.identities['receipt'],
                'Installation x64 verified content differs')
        if version is not None: require(fresh.native['mysqlVersion'] == version, 'Installation x64 MySQL version differs')
        return fresh

    def finish_playerbots(self, verified, connection, state, version, **arguments):
        def check():
            fresh = self.verify(verified, version=version)
            role = fresh.closure['executables']['playerbots-schema']
            require(Path(arguments['helper']) == self.root / role['invocationPath'] and
                arguments['helper_identity'] == role['invocation'] and
                Path(arguments['helper_receipt']) == self.root / 'provenance/playerbots-helper-build.json' and
                arguments['helper_receipt_identity'] == fresh.closure['buildReceipt'] and
                Path(arguments['native_receipt']) == self.root / 'provenance/playerbots-native-sql.json' and
                arguments['native_receipt_identity'] == fresh.closure['nativeSqlReceipt'],
                'Installation x64 selected helper proof differs')
            return fresh
        def prepare():
            check()
            return self._preparation(verified, arguments['mysql'], version=version,
                progress=arguments.get('progress'), cancelled=arguments.get('cancelled'))
        return installation._finish_playerbots(verified, connection, state, version,
            prepare_helper=prepare, verify_helper=check, **arguments)

    def _preparation(self, verified, mysql, *, version, progress=None, cancelled=None):
        fresh = self.verify(verified, version=version)
        mysql = Path(mysql)
        require(mysql.is_absolute() and installation.db.private_path(mysql).is_file(),
            'Installation x64 actual MySQL client required')
        expected, binding = playerbots._selected_content(verified, progress=progress, cancelled=cancelled)
        helper = self.root / ROLES['playerbots-schema'][0]
        identity = fresh.closure['executables']['playerbots-schema']['invocation']
        binding.update(helperBuildReceipt=fresh.closure['buildReceipt'], helperExecutable=identity,
            helperPath=str(helper), mysqlPath=str(mysql))
        return playerbots.Preparation(verified, helper, identity, fresh.closure['buildReceipt'], mysql, expected, binding)


def _admit(root, authority, *, expected_authority=None):
    """Private fixture reader; the CLI supplies only fixed package-owned paths."""
    root, authority = Path(root), Path(authority)
    require(root.is_absolute() and authority.is_absolute(), 'Installation x64 fixed absolute inputs required')
    selected, selected_identity = _json(authority, expected_authority, 16 << 10)
    require(type(selected) is dict and set(selected) == {'formatVersion', 'scope', 'closure'} and
        type(selected['formatVersion']) is int and selected['formatVersion'] == 1 and
        selected['scope'] == 'android-x64-installation-fixed-inputs', 'Installation x64 fixed input authority required')
    closure, _ = _json(root / 'provenance/x64-closure.json', _pin(selected['closure']))
    require(type(closure) is dict and set(closure) == {'formatVersion', 'scope', 'buildReceipt', 'nativeSqlReceipt',
        'nativeInputSelection', 'nativeBuildSourceReadback', 'buildProducer', 'executables', 'libraries', 'loader',
        'sourceOrigin', 'originalElfBytesChanged', 'nativeInvocationScriptsReused', 'androidRuntimeQualified'} and
        type(closure['formatVersion']) is int and closure['formatVersion'] == 1 and
        closure['scope'] == 'android-x64-original-setup-elf-closure' and
        all(closure[name] is False for name in ('originalElfBytesChanged', 'nativeInvocationScriptsReused', 'androidRuntimeQualified')),
        'Installation x64 original closure required')
    for name in ('buildReceipt', 'nativeSqlReceipt', 'nativeInputSelection', 'nativeBuildSourceReadback'): _pin(closure[name])
    producer = closure['buildProducer']
    require(type(producer) is dict and set(producer) == {'workflowRun', 'job', 'integrationRevision'} and
        all(type(producer[key]) is int and producer[key] > 0 for key in ('workflowRun', 'job')) and
        type(producer['integrationRevision']) is str and re.fullmatch('[a-f0-9]{40}', producer['integrationRevision']),
        'Installation x64 original build producer required')
    build, _ = _json(root / 'provenance/playerbots-helper-build.json', closure['buildReceipt'])
    native, _ = _json(root / 'provenance/playerbots-native-sql.json', closure['nativeSqlReceipt'])
    origin = closure['sourceOrigin']
    require(type(origin) is dict and set(origin) == {'originalBuild', 'compiledModules', 'sourceLock', 'source'},
        'Installation x64 original source origin required')
    for name, path in (('originalBuild', 'server-build.json'), ('compiledModules', 'server-modules.json'), ('sourceLock', 'sources.lock.json')):
        _json(root / 'provenance' / path, _pin(origin[name]))
    require(type(build) is dict and type(build.get('formatVersion')) is int and build['formatVersion'] == 1 and
        build.get('scope') == 'source-built-x86-64-server-setup-tools-only' and build.get('phase') == 'built-unqualified-inputs' and
        build.get('integrationRevision') == producer['integrationRevision'] and
        build.get('targets') == ['dbimport', 'esteria_playerbots_database_reference'] and
        build.get('actualCompileSucceeded') is True and build.get('originalDbimportExecutableBuilt') is True and
        build.get('originalDbimportTargetAndFullStaticModuleScriptLinkGraphBuilt') is True and
        build.get('originalArm64ReceiptReusedForX64Qualification') is False and
        type(build.get('statementsDeclared')) is int and build['statementsDeclared'] == 52 and
        all(build.get(name) is False for name in ('sqlExecuted', 'androidRuntimeQualified', 'productionArm64ProviderQualified',
            'fourSchemaCoordinatorQualified', 'worldserverQualified', 'playerbotsAiQualified', 'gameplayQualified')) and
        build.get('originalArm64Build') == origin['originalBuild'] and build.get('originalArm64Modules') == origin['compiledModules'] and
        build.get('sourceLock') == origin['sourceLock'] and build.get('serverSource') == origin['source'],
        'Installation x64 original compiled source binding differs')
    _validate_native(native, closure)
    libraries = build.get('libraries')
    require(type(libraries) is dict and {LOADER, 'usr/lib/x86_64-linux-gnu/libc.so.6'} <= set(libraries) and
        2 <= len(libraries) <= 128 and closure['libraries'] == {name: _scalar(row, 512 << 20) for name, row in libraries.items()},
        'Installation x64 complete captured libraries differ')
    # Renderer validates all names before any name is joined to the installed root.
    invocation_source(build, 'dbimport')
    for name, row in libraries.items():
        _, elf = _checked(root / 'libraries' / name, _scalar(row, 512 << 20), maximum=512 << 20, elf=True)
        require(elf == row.get('elf'), 'Installation x64 captured library ELF differs')
    loader = closure['loader']
    require(type(loader) is dict and set(loader) == {'path', 'bytes', 'sha256'} and
        loader['path'] == 'libexec/ld-linux-x86-64.so.2' and _scalar(loader, 512 << 20) == _scalar(libraries[LOADER], 512 << 20),
        'Installation x64 captured invocation loader differs')
    _, elf = _checked(root / loader['path'], _scalar(loader, 512 << 20), maximum=512 << 20, executable=True, elf=True)
    require(elf == libraries[LOADER]['elf'], 'Installation x64 executable loader ELF differs')
    require(type(closure['executables']) is dict and set(closure['executables']) == set(ROLES) and
        type(build.get('executables')) is dict and set(build['executables']) == set(ROLES), 'Installation x64 executable roles differ')
    for role, (script, actual) in ROLES.items():
        row = closure['executables'][role]; compiled = build['executables'][role]
        require(type(row) is dict and set(row) == {'actualPath', 'actualExecutable', 'invocationPath', 'invocation'} and
            row['actualPath'] == actual and row['invocationPath'] == script and
            row['actualExecutable'] == _scalar(compiled, 2 << 30) and
            native['checkedInvocations'][role]['actualExecutable'] == row['actualExecutable'] and
            native['checkedInvocations'][role]['loader'] == _scalar(libraries[LOADER], 512 << 20) and
            row['invocation'] != native['checkedInvocations'][role]['invocation'],
            'Installation x64 original executable or separate invocation differs')
        _scalar(compiled.get('original'), 2 << 30); _scalar(compiled.get('pairedDebug'), 2 << 30)
        _, elf = _checked(root / actual, row['actualExecutable'], maximum=2 << 30, executable=True, elf=True)
        require(elf == compiled.get('elf') and elf['interpreter'] == '/lib64/ld-linux-x86-64.so.2',
            'Installation x64 original executable ELF differs')
        _, raw = _checked(root / script, _pin(row['invocation'], 256 << 10), maximum=256 << 10, executable=True, capture=True)
        require(raw == invocation_source(build, role), 'Installation x64 source-owned invocation changed')
    return _Inputs(root, authority, selected_identity, closure, build, native)


def _validate_native(native, closure):
    origin = closure['sourceOrigin']; producer = closure['buildProducer']
    require(type(native) is dict and type(native.get('formatVersion')) is int and native['formatVersion'] == 1 and
        native.get('scope') == 'disposable-native-x64-measured-setup-four-schema-sql' and native.get('phase') == 'complete' and
        all(native.get(name) is True for name in POSITIVE) and all(native.get(name) is False for name in FALSE_FLAGS) and
        not any(name.startswith(('failure', 'cleanupFailure')) for name in native), 'Installation x64 positive native SQL required')
    require(native.get('inputSelection') == closure['nativeInputSelection'] and native.get('buildProducer') == producer and
        native.get('actualX64BuildReceipt') == closure['buildReceipt'] and
        native.get('actualX64LibrarySourceReadback') == closure['nativeBuildSourceReadback'] and
        native.get('contentOriginBuild') == origin['originalBuild'] and native.get('compiledModules') == origin['compiledModules'] and
        native.get('source') == origin['source'] and native.get('sourceLockSha256') == origin['sourceLock']['sha256'] and
        native.get('contentOriginIsOriginalArm64Packaging') is True and native.get('originalArm64ReceiptReusedForX64Qualification') is False,
        'Installation x64 native source or build selection differs')
    for name, expected in (('selectedSourceBaseFiles', 29), ('selectedSourceUpdates', 31), ('preparedStatementCount', 52)):
        require(type(native.get(name)) is int and native[name] == expected, 'Installation x64 native SQL plan differs')
    for name in ('authserverExecuted', 'worldserverExecuted', 'botCharactersCreated', 'characterPersistenceQualified'):
        require(name not in native or native[name] is False, 'Installation x64 native runtime claim differs')
    installation.db.exact_version(native.get('mysqlVersion'))
    uuid = native.get('mysqlUuid')
    require(type(uuid) is str and re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', uuid),
        'Installation x64 native instance identity differs')
    _pin(native.get('contentReceipt')); _pin(native.get('originalMysqlArchive'), 4 << 30)
    invocations = native.get('checkedInvocations')
    require(type(invocations) is dict and set(invocations) == set(ROLES), 'Installation x64 native invocations required')
    for role, row in invocations.items():
        require(type(row) is dict and set(row) == {'path', 'invocation', 'actualExecutable', 'loader',
            'invocationIsOriginalElf', 'originalElfBytesChanged'} and row['invocationIsOriginalElf'] is False and
            row['originalElfBytesChanged'] is False and type(row['path']) is str and len(row['path']) <= 4096 and
            row['path'].startswith('/') and str(Path(row['path'])) == row['path'] and Path(row['path']).name == role and
            all(part not in ('.', '..') for part in Path(row['path']).parts), 'Installation x64 native invocation identity differs')
        for name in ('invocation', 'actualExecutable', 'loader'): _pin(row[name], 2 << 30)
    first = native.get('playerbotsFirst', {})
    require(type(first) is dict and first.get('scope') == playerbots.SCOPE and first.get('mysqlUuid') == uuid and
        first.get('mysqlVersion') == native['mysqlVersion'] and first.get('helperBuildReceipt') == closure['buildReceipt'] and
        first.get('helperExecutable') == invocations['playerbots-schema']['invocation'] and
        first.get('originalBuild') == origin['originalBuild'] and first.get('compiledModules') == origin['compiledModules'] and
        first.get('sourceLockSha256') == origin['sourceLock']['sha256'] and first.get('contentReceipt') == native['contentReceipt'] and
        type(first.get('preparedStatementCount')) is int and first['preparedStatementCount'] == 52 and
        all(first.get(name) is True for name in ('compiledPlayerbotsLoaderExecuted', 'playerbotsSchemaInitialized',
            'exactSourceLedgerVerified', 'coreSchemasLedgersCredentialsAccountPreserved')) and
        type(native.get('databaseSnapshot')) is dict and native['databaseSnapshot'] == first.get('databaseSnapshot'),
        'Installation x64 native fourth-schema result differs')
    reentry = native.get('actualLoaderReentry', {})
    require(type(reentry) is dict and type(reentry.get('exitCode')) is int and reentry['exitCode'] == 0 and
        type(reentry.get('preparedStatementCount')) is int and reentry['preparedStatementCount'] == 52,
        'Installation x64 actual native loader reentry required')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('expected-version', 'operation-id', 'service-operation-id', 'instance-uuid'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--phase', choices=('core', 'playerbots'), default='core')
    args = parser.parse_args(); stopped = [False]
    for signum in (signal.SIGINT, signal.SIGTERM): signal.signal(signum, lambda *_: stopped.__setitem__(0, True))
    try:
        require(re.fullmatch('[a-f0-9]{32}', args.operation_id) and re.fullmatch('[a-f0-9]{32}', args.service_operation_id) and
            re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', args.instance_uuid),
            'Installation x64 operation identity differs')
        admitted = _admit(Path(GUEST), Path(__file__).with_name('installation-x64-inputs.json').absolute())
        admitted.verify(version=args.expected_version)
        session = Path('/work/installation-operations') / args.operation_id
        installation._run(Path('/work/state'), session, Path('/esteria-server-content'), session / 'content-receipt.json',
            Path(GUEST), Path('/work/mysql-sessions') / args.service_operation_id, Path('/usr/bin/mysql'),
            Path('/esteria-data'), Path(__file__).with_name('local-server.json'), args.expected_version,
            args.operation_id, args.service_operation_id, args.instance_uuid, phase=args.phase,
            interrupted=lambda: stopped[0], finish_phase=admitted.finish_playerbots)
        print('Debug x64 installation phase completed; Android qualification requires independent readback')
        return 0
    except Exception as error:
        kind = type(error).__name__
        if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', kind): kind = 'Exception'
        print('Debug x64 installation failed (' + kind + '); private diagnostics retained', file=sys.stderr)
        return 2 if isinstance(error, (installation.schema.SchemaCancelled, installation.packaged.ContentCancelled,
            installation.updates.UpdateCancelled)) else 1


if __name__ == '__main__': raise SystemExit(main())
