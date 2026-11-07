"""Independent stock four-schema and auth protocol qualification using shipped APK bytes."""
import argparse
import hmac
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import socket
import tarfile
import time
import zipfile

from runtime import android_database_setup, android_server_installation_setup as installation
from runtime import mysql_bootstrap as db, provision_local_account as account
from tools import auth_protocol, prepare_runtime, qualify_authserver as auth, qualify_server_installation as sql
from tools.verify_server_build import identity

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'runtime/evidence/non-custom-v13-public-apk-readback.json'
ARCHIVES = (
    ('server-runtime', 'server-runtime-arm64', 'android-provider'),
    ('server-programs', 'server-programs', 'programs-playerbots-provider'),
    ('server-content', 'server-content', 'content-provider'),
)
require = prepare_runtime.require


def document(path):
    return json.loads(path.read_bytes())


def stage(output, apk, readback):
    output.mkdir(mode=0o700)
    release = document(readback)
    artifacts = [item for item in release['assets'] if item['name'].endswith('.apk')]
    require(len(artifacts) == 1, 'one measured APK required')
    asset = artifacts[0]
    measured = {key: asset[key] for key in ('bytes', 'sha256')}
    if apk is None:
        url = release['releaseUrl'].replace('/tag/', '/download/') + '/' + asset['name']
        apk = prepare_runtime.fetch(dict(measured, file=asset['name'], url=url), output / 'cache')
    require(identity(apk) == measured, 'published APK changed')
    bindings = dict(apkSha256=asset['sha256'], tag=release['tag'], archives={})
    with zipfile.ZipFile(apk) as signed:
        for prefix, member, lock in ARCHIVES:
            pin = document(ROOT / 'runtime/server' / (lock + '.lock.json'))['archive']
            target = output / (prefix + '.tar.gz')
            with signed.open(f'assets/{prefix}/{member}.archive') as source, target.open('xb') as destination:
                digest = prepare_runtime.hash_stream(source, pin['bytes'], destination)
            require(digest == pin['sha256'], 'APK component differs from selected provider')
            bindings['archives'][prefix] = digest
            (output / (prefix + '.json')).write_bytes(signed.read('assets/' + prefix + '/provider.json'))
            if prefix != 'server-runtime':
                dest = output / prefix
                dest.mkdir()
                with tarfile.open(target, 'r:gz') as tar:
                    tar.extractall(dest, filter='data')
        receipt = output / 'content-receipt.json'
        receipt.write_bytes(signed.read('assets/server-content/package-receipt.json'))
        require(identity(receipt) == document(ROOT / 'runtime/server/content-provider.lock.json')['receipt'],
                'APK content receipt changed')
        profile = output / 'local-server.json'
        profile.write_bytes(signed.read('assets/server-installation/local-server.json'))
        require(identity(profile) == identity(ROOT / 'config/local-server.json'), 'APK SQL profile differs')
        # The ARM worker imports the project's package-qualified entrypoints. Bind every reused module
        # to the APK, including the SQL adaptations and the production service/bootstrap adapters.
        for member in signed.namelist():
            prefix, _, local = member.removeprefix('assets/').partition('/')
            if prefix in ('database-setup', 'database-service', 'server-installation') and (
                    local.endswith(('.py', '.sql')) or local.startswith('server/') and local.endswith('.json')):
                require((ROOT / 'runtime' / local).read_bytes() == signed.read(member), 'APK helper differs: ' + local)
    (output / 'bindings.json').write_text(json.dumps(bindings))
    return apk


def selections(package):
    programs = document(package / 'server-programs.json')
    content = document(package / 'server-content.json')
    selected = document(package / 'bindings.json')
    for provider in (programs, content):
        require(provider['requiredServerRuntimeArchiveSha256'] == selected['archives']['server-runtime'],
                'mismatched server runtime requirement')
    def pin(name):
        expected = {key: programs['requiredFiles'][name][key] for key in ('bytes', 'sha256')}
        require(identity(package / 'server-programs' / name) == expected, 'server program or evidence changed')
        return expected
    require(content['compiledModules'] == pin('provenance/server-modules.json'), 'compiled modules selection differs')
    core = dict(formatVersion=1, scope=installation.SELECTION_SCOPE, source=content['serverSource'],
                sourceLockSha256=content['serverBuildSourceLockSha256'], contentReceipt=content['receipt'],
                compiledModules=content['compiledModules'], program=pin('bin/dbimport'),
                template=pin('etc/dbimport.conf.dist'), originalBuild=pin('provenance/server-build.json'),
                profile=identity(package / 'local-server.json'))
    pb = dict(executable=pin('helpers/playerbots-schema'), buildReceipt=pin('provenance/playerbots-helper-build.json'),
              nativeReceipt=pin('provenance/playerbots-native-sql.json'))
    return [('core', core), ('playerbots', dict(core, playerbotsHelper=pb))], pin('bin/authserver')


def protocol_probe(state, mysql, version, program, expected, configuration, *, client_probe=None, attempt=1):
    require(identity(program) == expected, 'selected authserver changed before execution')
    intent = account.read_intent(state / account.JOURNAL, db.read_receipt(state / 'database-bootstrap.json', version))
    child = auth.OwnedAuthserver(program, configuration / 'authserver.conf', state / 'logs' / f'auth-probe-{attempt}-private.log')
    try:
        auth.wait_authserver(child)
        with socket.create_connection(('127.0.0.1', 3724), timeout=5) as transport:
            realms, key = auth_protocol.login(transport, intent)
        require(auth.owns_listener(child.process.pid), 'auth listener ownership changed')
        require(len(realms) == 1 and realms[0]['id'] == 1 and realms[0]['address'] == '127.0.0.1:8085'
                and realms[0]['locked'] == 0 and realms[0]['build'] in (None, (3, 3, 5, 12340)),
                'authserver realm does not match local build 12340')
        with db.option_file(state, 'esteria', db.read_secret(state / 'accounts/database-secret')) as options:
            with db.Mysql(mysql, options) as connection:
                rows = connection.query('SELECT LOWER(HEX(session_key)),os,locale FROM acore_auth.account WHERE id='
                                        + str(intent['accountId']))
                require(len(rows) == 1 and hmac.compare_digest(rows[0], key.hex() + '\tWin\t0'),
                        'negotiated auth key differs from persistent session')
                if client_probe is not None:
                    return client_probe(state, connection, intent, child, attempt)
    finally:
        child.stop()


def run(package, work, evidence, world_probe=None, client_probe=None):
    require(platform.machine().lower() in ('aarch64', 'arm64'), 'native Linux ARM64 required')
    require(not any(work.iterdir()), 'an empty disposable state directory is required')
    os.umask(0o077)
    started = time.monotonic()
    proof = dict(scope='packaged-stock-server-database-and-standalone-auth', environment='Linux ARM64',
                 worldserverExecuted=False, reconstructedClientExecuted=False, gameplayQualified=False,
                 stages=[], **document(package / 'bindings.json'))
    if world_probe is not None:
        proof['scope'] = 'packaged-stock-native-world-session'
        del proof['worldserverExecuted']
    if client_probe is not None:
        proof['scope'] = 'packaged-stock-four-schema-reconstructed-grunt-authentication'
    def record(stage, **details):
        if stage == 'real-worldserver-ready-and-cleanly-stopped':
            proof['worldserverExecuted'] = True
        proof['stages'].append(dict(stage=stage, elapsedSeconds=round(time.monotonic()-started, 3), **details))
        db.atomic_json(evidence, proof)
    state = work / 'state'
    sessions = work / 'mysql-sessions'
    state.mkdir(mode=0o700)
    sessions.mkdir(mode=0o700)
    mysql, mysqld = Path('/usr/bin/mysql'), Path('/usr/sbin/mysqld')
    version = document(Path('/etc/esteria-server-runtime.json'))['expectedMysqlSqlVersion']
    phases, expected_auth = selections(package)
    record('bootstrap')
    result = android_database_setup.setup(state, mysql, mysqld, version)
    uuid = result['uuid']
    owned = sql.ServiceProcess(state, sessions, mysql, mysqld, version)
    try:
        owned.wait_ready(uuid)
        record('authenticated-database', version=version, uuid=uuid)
        def install_phase(phase, selection):
            operation = secrets.token_hex(16)
            directory = work / operation
            directory.mkdir(mode=0o700)
            db.atomic_json(directory / 'selection.json', selection)
            receipt = directory / 'content-receipt.json'
            shutil.copyfile(package / 'content-receipt.json', receipt)
            record('enter-' + phase)
            return installation.run(state, directory, package / 'server-content', receipt, package / 'server-programs',
                                      owned.session, mysql, Path('/esteria-data'), package / 'local-server.json',
                                      version, operation, owned.operation, uuid, phase=phase)
        for phase, selection in phases:
            result = install_phase(phase, selection)
        require(result['fourSchemasVerified'] and result['playerbotsSchemaVerified'] and result['mysqlUuid'] == uuid,
                'four source-bound schemas required before auth probe')
        record('four-schemas-verified')
        with db.state_lock(state):
            configuration = state / 'config/generations' / result['configGeneration']
            program = package / 'server-programs/bin/authserver'
            first_client = protocol_probe(state, mysql, version, program, expected_auth, configuration, client_probe=client_probe)
            if client_probe is not None:
                proof['reconstructedClientExecuted'] = True
                record('reconstructed-grunt-login', **first_client)
        record('auth-srp-12340-loopback-session-key-verified', authserverSha256=expected_auth['sha256'])
        repeated = install_phase(*phases[-1])
        require(repeated['fourSchemasVerified'] and not repeated['compiledPlayerbotsLoaderExecuted']
                and not repeated['compiledUpdaterExecuted'], 'completed stock schemas must be verified without replay')
        owned.stop(uuid)
        helper = phases[-1][1]['playerbotsHelper']
        pins = dict(helperExecutable=helper['executable'], helperBuildReceipt=helper['buildReceipt'],
                    helperNativeReceipt=helper['nativeReceipt'])
        sql.complete_sql_receipt(state, owned.session, document(state / installation.VERIFIED_REPORT),
                                 pins, version, uuid, owned.operation)
        record('sql-completion-bound-to-clean-stop')
    finally:
        owned.close()
    require(android_database_setup.setup(state, mysql, mysqld, version)['operation'] == 'already-initialized',
            'database was not reused')
    reopened = sql.ServiceProcess(state, sessions, mysql, mysqld, version)
    try:
        reopened.wait_ready(uuid)
        if client_probe is not None:
            with db.state_lock(state):
                again = protocol_probe(state, mysql, version, program, expected_auth, configuration,
                                       client_probe=client_probe, attempt=2)
            record('same-database-reconstructed-grunt-login', **again)
        if world_probe is not None:
            record('enter-world-admission')
            world_probe(package, state, reopened, version, uuid, record)
        reopened.stop(uuid)
    finally:
        reopened.close()
    record('same-uuid-reopened-and-cleanly-stopped', uuid=uuid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    prep = actions.add_parser('stage')
    prep.add_argument('--apk', type=Path)
    prep.add_argument('--readback', type=Path, default=BASELINE)
    prep.add_argument('--output', type=Path, required=True)
    running = actions.add_parser('run')
    running.add_argument('--grunt', action='store_true')
    args = parser.parse_args()
    if args.action == 'stage':
        stage(args.output, args.apk, args.readback)
    else:
        evidence = Path('/evidence/stock-auth.json')
        work = Path('/work')
        try:
            client_probe = None
            if args.grunt:
                from tools.qualify_packaged_grunt import server_probe as client_probe
            run(Path('/package'), work, evidence, client_probe=client_probe)
        except Exception as error:
            proof = document(evidence) if evidence.is_file() else {}
            proof.update(failureClass=type(error).__name__, **sql.safe_failure_context(error, work / 'state'))
            db.atomic_json(evidence, proof)
            raise


if __name__ == '__main__':
    main()
