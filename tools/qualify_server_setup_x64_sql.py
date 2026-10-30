#!/usr/bin/env python3
"""Qualify separately measured x64 setup ELFs on a fresh native MySQL instance.

The production ARM64 admission functions remain unchanged. This fixture admits
its own measured x64 build/source/library closure, invokes the unchanged setup
ELFs through their captured loader, and uses the real product SQL operations.
It never adopts saved state, promotes a slot, starts a world, or runs on Android.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import server_setup_x64_sql_inputs as selection
from tools import fetch_android_mysql_fixture as mysql_inputs
from tools import prepare_server_requalification as remote
from tools import qualify_server_providers as transfer
from tools import release_local_server_components as release
from tools import provider_server_content as provider
from tools import qualify_dbimport as importer, qualify_base_sql as base
from tools import qualify_playerbots_component as checks
from runtime import mysql_bootstrap as db, server_playerbots_setup as playerbots
from runtime import server_update_setup as updater, server_schema_baseline as baseline
from runtime import android_server_installation_setup as installation

ROOT = Path(__file__).resolve().parents[1]
SCOPE = 'disposable-native-x64-measured-setup-four-schema-sql'
TEMPLATE = 'source/src/tools/dbimport/dbimport.conf.dist'
require = selection.require
FALSE_FLAGS = ('androidRuntimeQualified', 'productionArm64ProviderQualified', 'fourSchemaCoordinatorQualified',
    'worldserverQualified', 'playerbotsAiQualified', 'gameplayQualified', 'slotPromoted', 'serverDataQualified')


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def fresh(path):
    path = Path(os.path.abspath(path)); selection.archives.directory(path.parent, create=True)
    require(not os.path.lexists(path), 'x64-sql-existing-output-preserved')
    path.mkdir(mode=0o700); return path


def load_selection():
    return selection.load_pin(require_enabled=True)


def acquire(output, api=None):
    pin = load_selection()
    output = Path(os.path.abspath(output)); selection.archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'x64-sql-existing-inputs-preserved')
    require(shutil.disk_usage(output.parent).free >= pin['minimumFreeBytes'], 'x64-sql-inputs-require-sixteen-GiB-free')
    api = api or remote.Github(os.environ.get('GITHUB_TOKEN'))
    output = fresh(output)
    producer = pin['build']['producer']
    run = api.json('/actions/runs/' + str(producer['workflowRun']))
    require(run.get('id') == producer['workflowRun'] and run.get('head_sha') == producer['integrationRevision'] and
        run.get('status') == 'completed' and run.get('conclusion') == 'success', 'x64-sql-original-build-success-required')
    for name, row in pin['build']['artifacts'].items():
        transfer.verify_remote(api, dict(row, workflowRun=producer['workflowRun'], integrationRevision=producer['integrationRevision']))
        api.download(remote.API + '/actions/artifacts/' + str(row['id']) + '/zip', output / (name + '.zip'), row)
        selection.pinned(output / (name + '.zip'), row)
    component = selection.restore_component_zip(output / 'complete.zip', output / 'component', pin)
    mysql = mysql_inputs.acquire(output / 'mysql', api)
    # Download only the already publicly verified content bundle and its bounded
    # original member inventory. The large ARM64 programs bundle is unnecessary.
    content = pin['serverContent']; public_lock = selection.small(ROOT / content['releaseSelection']['path'])
    publication = selection.small(ROOT / content['publicationReceipt']['path'])
    cache = output / 'public-content'; cache.mkdir(mode=0o700)
    for name in ('providers-receipt.json', 'server-content-provider.tar.gz'):
        expected = public_lock['files'][name]
        published = publication['assets'][name]
        require({key: published[key] for key in ('bytes', 'sha256')} == expected, 'x64-sql-public-content-pin-differs')
        selected = selection.archives.fetch(dict(expected, file=name, url=published['url']), cache)
        selection.pinned(selected, expected)
    rows = selection.small(cache / 'providers-receipt.json')['providers']['server-content-provider.tar.gz']
    require(rows['archive'] == public_lock['files']['server-content-provider.tar.gz'], 'x64-sql-public-content-inventory-binding')
    release.read_bundle(cache / 'server-content-provider.tar.gz', rows['members'], output / 'content-provider')
    content_proof = provider.verify(output / 'content-provider')
    proof = dict(formatVersion=1, scope='measured-x64-setup-sql-inputs-ready-no-execution',
        selectionIdentity=selection.files.identity(selection.LOCK), component=component, mysql=mysql,
        originalPublicContent=content_proof, contentOriginIsOriginalArm64Packaging=True,
        selectedX64ToolsSqlQualified=False, sqlExecuted=False, **{name: False for name in FALSE_FLAGS})
    release.engine.put_metadata(output / 'preparation.json', proof)
    return proof


def mysql_descriptor(inputs):
    """Rebind restored metadata to the exact measured MySQL byte selection."""
    locked = mysql_inputs.load_pin()
    path = inputs / 'mysql/provider/assets/mysql-probe/provider.json'
    selection.pinned(path, locked['files']['provider/assets/mysql-probe/provider.json'])
    value = selection.small(path)
    require(selection.identity(value.get('archive')) ==
        locked['files']['provider/assets/mysql-probe/' + mysql_inputs.retained.builder.ARCHIVE],
        'x64-sql-original-mysql-archive-selection-required')
    return value


def prepare_image(inputs, output):
    pin = load_selection(); inputs = selection.archives.directory(inputs)
    proof = selection.small(inputs / 'preparation.json')
    require(proof.get('scope') == 'measured-x64-setup-sql-inputs-ready-no-execution' and
        proof.get('selectionIdentity') == selection.files.identity(selection.LOCK) and proof.get('sqlExecuted') is False,
        'x64-sql-preparation-required')
    provider_root = inputs / 'mysql/provider/assets/mysql-probe'
    descriptor = mysql_descriptor(inputs)
    archive = provider_root / mysql_inputs.retained.builder.ARCHIVE
    selection.pinned(archive, descriptor['archive'])
    output = fresh(output)
    release.engine.copy_verified(archive, output / 'mysql-x86-64.tar.gz', selection.identity(descriptor['archive']), 0o444)
    (output / 'Dockerfile').write_text('FROM scratch\nADD mysql-x86-64.tar.gz /\n'
        'ENV LANG=C.UTF-8\nCMD ["/usr/bin/python3", "--version"]\n')
    proof = dict(formatVersion=1, scope='exact-original-x64-mysql-rootfs-for-native-setup-sql',
        inputSelection=selection.files.identity(selection.LOCK), runtimeArchive=selection.identity(descriptor['archive']),
        runtimeChanged=False, packagedDatabaseState=False, sqlExecuted=False, **{name: False for name in FALSE_FLAGS})
    release.engine.put_metadata(output / 'image-context.json', proof); return proof


LAUNCHER = '''#!/usr/bin/python3
import hashlib,json,os,stat,sys
PLAN=json.loads(@@PLAN@@)
def refuse():
    sys.stderr.write('x64-sql-checked-loader-refused\\n');raise SystemExit(98)
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


def launchers(payload, admitted, output):
    """Preserve actual ELF identities separately from source-owned invocations."""
    require(admitted.get('allRuntimeOriginalDebugLibraryNoticeAndSourceFilesVerified') is True,
        'x64-sql-complete-component-admission-required')
    payload = selection.archives.directory(payload); output = fresh(output)
    build = admitted['build']; libs = build['libraries']
    loader_name = 'lib64/ld-linux-x86-64.so.2'
    require(loader_name in libs and all(row.get('elf', {}).get('machine') == 62 for row in libs.values()),
        'x64-sql-captured-x64-loader-required')
    original_loader = payload / 'libraries' / loader_name
    # Original provider/source files remain read-only. Make an executable copy
    # of only the pinned interpreter in this private invocation directory.
    loader = output / 'captured-ld-linux-x86-64.so.2'
    release.engine.copy_verified(original_loader, loader, selection.identity(libs[loader_name]), 0o500)
    result = {}
    for role in ('dbimport', 'playerbots-schema'):
        actual = payload / 'bin' / role; executable = build['executables'][role]
        require(executable.get('elf', {}).get('machine') == 62, 'x64-sql-actual-x64-executable-required')
        selections = {str(actual): selection.identity(executable)}
        selections.update({str(payload / 'libraries' / name): selection.identity(row) for name, row in libs.items()})
        selections[str(loader)] = selection.identity(libs[loader_name])
        for path, expected in selections.items(): selection.pinned(Path(path), expected)
        plan = dict(formatVersion=1, scope='checked-original-x64-setup-elf-loader-invocation', role=role,
            executable=str(actual), loader=str(loader),
            libraryPath=':'.join(str(payload / 'libraries' / name) for name in ('usr/lib/x86_64-linux-gnu', 'lib64')),
            files=selections)
        source = LAUNCHER.replace('@@PLAN@@', repr(json.dumps(plan, sort_keys=True, separators=(',', ':')))).encode()
        path = output / role
        with path.open('xb') as stream: stream.write(source)
        path.chmod(0o700)
        result[role] = dict(path=str(path), invocation=selection.files.identity(path),
            actualExecutable=selection.identity(executable), loader=selection.identity(libs[loader_name]),
            invocationIsOriginalElf=False, originalElfBytesChanged=False)
    return result


def template(payload, output):
    source = payload / 'corresponding-source/source-inputs'
    receipt = selection.small(source / 'source-inputs-receipt.json', 16 << 20)
    archive = source / 'server-engine-source-inputs.tar.gz'
    selection.pinned(archive, receipt['archive'])
    row = receipt.get('archiveFiles', {}).get(TEMPLATE)
    require(type(row) is dict, 'x64-sql-original-dbimport-template-required')
    expected = selection.identity(row, 2 << 20); found = False
    require(not os.path.lexists(output), 'x64-sql-existing-template-preserved')
    with selection.files.plain_file(archive) as raw, selection.archives.bounded_tar(raw,
            dict(entries=40000, pathBytes=4096, fileBytes=2 << 30)) as bundle:
        for member in bundle:
            if member.name == TEMPLATE:
                require(not found and member.isfile() and member.size == expected['bytes'], 'x64-sql-original-template-member')
                with bundle.extractfile(member) as incoming, output.open('xb') as outgoing:
                    require(selection.archives.hash_stream(incoming, member.size, outgoing) == expected['sha256'],
                        'x64-sql-original-template-bytes')
                output.chmod(0o400); found = True
            bundle.members.clear()
    require(found, 'x64-sql-original-template-absent'); return expected


def x64_playerbots_plan(verified, admitted, invocation, mysql):
    """Fixture-only x64 adapter, never an ARM64 receipt or production admission.

    The closed measured component has already passed actual ELF/source/debug/DSO
    admission. Share the product's complete source-SQL selection and apply logic;
    do not call or alter its deliberately ARM64-only helper-receipt admission.
    """
    require(admitted.get('allRuntimeOriginalDebugLibraryNoticeAndSourceFilesVerified') is True and
        admitted['build'].get('statementsDeclared') == 52 and
        admitted['build']['executables']['playerbots-schema'].get('elf', {}).get('machine') == 62 and
        invocation.get('actualExecutable') == selection.identity(admitted['build']['executables']['playerbots-schema']) and
        invocation.get('invocationIsOriginalElf') is False and invocation.get('originalElfBytesChanged') is False,
        'x64-sql-source-built-52-statement-helper-required')
    expected, binding = playerbots._selected_content(verified)
    executable = Path(invocation['path']); selection.pinned(executable, invocation['invocation'])
    binding.update(helperBuildReceipt=selection.identity(admitted['sourceReadback']['buildReceipt']),
        helperExecutable=invocation['invocation'], helperPath=str(executable), mysqlPath=str(mysql))
    return playerbots.Preparation(verified, executable, invocation['invocation'],
        selection.identity(admitted['sourceReadback']['buildReceipt']), mysql, expected, binding)


def run(inputs, output, mysql, mysqld, version):
    require(platform.system() == 'Linux' and platform.machine() == 'x86_64', 'x64-sql-native-linux-x86-64-required')
    pin = load_selection()  # Pending selection refuses before output or SQL.
    inputs = selection.archives.directory(inputs)
    prepared = selection.small(inputs / 'preparation.json')
    require(prepared.get('scope') == 'measured-x64-setup-sql-inputs-ready-no-execution' and
        prepared.get('selectionIdentity') == selection.files.identity(selection.LOCK) and prepared.get('sqlExecuted') is False,
        'x64-sql-exact-preparation-required')
    component = inputs / 'component' / pin['build']['componentPrefix']
    admitted = selection.admit_component(component, pin)
    mysql_provider = mysql_descriptor(inputs)
    require(version == mysql_provider.get('expectedMysqlSqlVersion'), 'x64-sql-original-mysql-version-required')
    db.exact_version(version)
    for path, name in ((mysql, 'usr/bin/mysql'), (mysqld, 'usr/sbin/mysqld')):
        require(path.is_absolute() and path == path.resolve(strict=True), 'x64-sql-canonical-mysql-executable-required')
        selection.pinned(path, mysql_provider['requiredFiles'][name])
    provider.verify(inputs / 'content-provider')
    output = fresh(output); state = output / 'private-state'; state.mkdir(mode=0o700)
    evidence = dict(formatVersion=1, scope=SCOPE, phase='verify-inputs', qualificationSucceeded=False,
        inputSelection=selection.files.identity(selection.LOCK), buildProducer=pin['build']['producer'],
        actualX64BuildReceipt=pin['build']['buildReceipt'], actualX64LibrarySourceReadback=pin['build']['librarySourceReadback'],
        originalMysqlArchive=selection.identity(mysql_provider['archive']), mysqlVersion=version,
        contentOriginIsOriginalArm64Packaging=True, originalArm64ReceiptReusedForX64Qualification=False,
        selectedX64ToolsSqlQualified=False, sqlExecuted=False, **{name: False for name in FALSE_FLAGS})
    capture = None
    try:
        payload = Path(admitted['payloadPath']); invocations = launchers(payload, admitted, output / 'invocations')
        evidence['checkedInvocations'] = invocations
        original_template = output / 'dbimport.conf.dist'; template_id = template(payload, original_template)
        assets = inputs / 'content-provider/assets/server-content'
        source = output / 'source-content-input'; source.mkdir(mode=0o700)
        for name, original in (('package-receipt.json', assets / 'package-receipt.json'),
                ('server-content.tar.gz', assets / provider.ARCHIVE)):
            release.engine.copy_verified(original, source / name, selection.files.identity(original), 0o400)
        receipt_sha = selection.files.identity(source / 'package-receipt.json')['sha256']
        lock = ROOT / 'runtime/server/server-build-sources.lock.json'
        receipt, manifest, compiled = importer.unpack_content(source, receipt_sha, lock, output / 'content')
        verified = importer.verify_runtime_content(output / 'content', source, receipt_sha, lock, manifest, compiled)
        require(admitted['build']['originalArm64Build'] == verified.compiled['serverBuild'] and
            admitted['build']['originalArm64Modules'] == verified.receipt['compiledModules'] and
            admitted['build']['serverSource'] == verified.manifest['source'], 'x64-sql-content-origin-source-binding')
        plan = x64_playerbots_plan(verified, admitted, invocations['playerbots-schema'], mysql)
        evidence.update(contentReceipt=verified.identities['receipt'], contentOriginBuild=verified.compiled['serverBuild'],
            compiledModules=receipt['compiledModules'], source=receipt['source'], sourceLockSha256=receipt['sourceLockSha256'],
            selectedSourceBaseFiles=playerbots.BASE_COUNT, selectedSourceUpdates=playerbots.UPDATE_COUNT,
            preparedStatementCount=playerbots.STATEMENTS, sourceSelectedContentFiles=len(verified.identities['files']))
        profile = json.loads((ROOT / 'config/local-server.json').read_bytes()); data = output / 'unavailable-game-data'
        password = db.read_secret(state / 'accounts/database-secret', create=True)
        with db.state_lock(state) as lease:
            evidence['phase'] = 'initialize-owned-mysql'; db.initialize(mysqld, mysql, state, version)
            evidence['initializedNewInstance'] = True; evidence['sqlExecuted'] = True
            capture = db.EngineCapture(base.engine_command(mysqld, state), state / 'logs/x64-mysql-private.log')
            base.wait_owned(mysql, state, version, capture)
            with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
                require(connection.query("SELECT GET_LOCK('esteria-local-bootstrap',0)") == ['1'], 'x64-sql-fresh-instance-lock')
                base.empty_databases(connection); bootstrap = db.read_receipt(state / 'database-bootstrap.json', version)
                uuid = bootstrap['uuid']; evidence['mysqlUuid'] = uuid
                def service():
                    require(capture is not None and capture.process.poll() is None, 'x64-sql-owned-service-exited')
                    db.check_receipt(bootstrap, db.identity(connection, version))
                evidence['phase'] = 'actual-core-updater-composition'
                staged = installation.compose(verified, connection, state, version,
                    program=Path(invocations['dbimport']['path']), program_identity=invocations['dbimport']['invocation'],
                    template=original_template, template_identity=template_id, original_build_identity=verified.compiled['serverBuild'],
                    mysql=mysql, data=data, profile=profile,
                    apply_sql=lambda name, sql: base.apply_base(mysql, options, 'acore_' + name, sql, state / 'logs/sql-private.log'),
                    verify_service=service, expected_uuid=uuid, state_lease=lease)
                require(staged.get('scope') == installation.SCOPE and staged.get('playerbotsSchemaVerified') is False and
                    staged.get('completeSetupQualified') is False, 'x64-sql-core-must-remain-pending-playerbots')
                evidence['actualCoreCompositionCompleted'] = True
                evidence['phase'] = 'actual-playerbots-source-loader'
                common = dict(profile=profile, data=data, expected_uuid=uuid, verify_service=service, state_lease=lease)
                first = playerbots.apply(plan, connection, state, version, **common)
                require(first.get('compiledPlayerbotsLoaderExecuted') is True, 'x64-sql-real-helper-execution-required')
                evidence['playerbotsFirst'] = first
                retained = checks.identities(state); core_before = playerbots.preserved_core(connection)
                pb_before = playerbots.snapshot(connection, plan.expected)
                repeated = playerbots.apply(plan, connection, state, version, **common)
                require(repeated.get('compiledPlayerbotsLoaderExecuted') is False and checks.identities(state) == retained,
                    'x64-sql-completed-helper-must-not-replay')
                evidence['completedJournalReentryWithoutExecution'] = True
                checks.verify_product(verified, connection, state, version, mysql, data, profile, uuid, service, lease)
                private_before = checks.identities(state)
                require(playerbots.preserved_core(connection) == core_before, 'x64-sql-core-preservation-before-probe')
                token = hashlib.sha256((pin['build']['buildReceipt']['sha256'] + uuid).encode()).hexdigest()
                checks.probe(connection, token, create=True)
                operation = state / 'run/x64-loader-reentry'; operation.mkdir(mode=0o700)
                configuration, _ = playerbots.render_configuration(verified, state, mysql, data, profile, operation)
                updater._hash(plan.executable, plan.executable_identity)
                evidence['actualLoaderReentry'] = playerbots.run_loader(plan.executable, configuration, operation / 'helper-private.log')
                checks.probe(connection, token)
                require(playerbots.preserved_core(connection) == core_before and checks.identities(state) == private_before,
                    'x64-sql-real-loader-reentry-preserved-core')
                evidence['actualLoaderReentryVerified'] = True
            base.stop_owned(capture); capture = None
            evidence['phase'] = 'clean-persistent-restart'
            capture = db.EngineCapture(base.engine_command(mysqld, state), state / 'logs/x64-mysql-restart-private.log')
            base.wait_owned(mysql, state, version, capture)
            with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
                require(connection.query("SELECT GET_LOCK('esteria-local-bootstrap',0)") == ['1'], 'x64-sql-restart-instance-lock')
                checks.probe(connection, token)
                require(playerbots.preserved_core(connection) == core_before and checks.identities(state) == private_before,
                    'x64-sql-restart-core-credentials-and-journals-preserved')
                evidence['restartPersistenceVerified'] = True
                connection.query('DROP TABLE `acore_playerbots`.`esteria_playerbots_probe`')
                require(playerbots.snapshot(connection, plan.expected) == pb_before, 'x64-sql-source-schema-restored-after-probe')
                checks.verify_product(verified, connection, state, version, mysql, data, profile, uuid, service, lease)
                require(checks.identities(state) == private_before and playerbots.preserved_core(connection) == core_before,
                    'x64-sql-final-four-schema-product-preserved')
                evidence.update(fixtureProbeRemoved=True, exactSourceUpdateLedgerVerified=True,
                    finalFourSchemaProductVerification=True, coreSchemasLedgersCredentialsAccountPreserved=True,
                    databaseSnapshot=pb_before)
            base.stop_owned(capture); capture = None
            evidence.update(cleanShutdownVerified=True, selectedX64ToolsSqlQualified=True,
                capturedLoaderAndLibraryCompatibilityQualified=True, qualificationSucceeded=True, phase='complete')
        return checks.public_record(evidence)
    except BaseException as error:
        evidence.update(qualificationSucceeded=False, failurePhase=evidence['phase'], failureClass=type(error).__name__, phase='failed')
        raise
    finally:
        try:
            if capture is not None:
                try: base.stop_owned(capture)
                except BaseException as error:
                    evidence.update(qualificationSucceeded=False, cleanupFailureClass=type(error).__name__); raise
        finally:
            db.atomic_json(output / 'qualification.json', checks.public_record(evidence))


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='operation', required=True)
    acquire_parser = sub.add_parser('acquire'); acquire_parser.add_argument('--output', type=Path, required=True)
    image = sub.add_parser('image-context')
    for name in ('inputs', 'output'): image.add_argument('--' + name, type=Path, required=True)
    execute = sub.add_parser('run')
    for name in ('inputs', 'output', 'mysql', 'mysqld'): execute.add_argument('--' + name, type=Path, required=True)
    execute.add_argument('--expected-version', required=True)
    args = parser.parse_args()
    if args.operation == 'acquire': value = acquire(args.output)
    elif args.operation == 'image-context': value = prepare_image(args.inputs, args.output)
    else: value = run(args.inputs, args.output, args.mysql, args.mysqld, args.expected_version)
    print(json.dumps(value, sort_keys=True, indent=2))


if __name__ == '__main__': main()
