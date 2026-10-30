#!/usr/bin/env python3
"""Stage real source/updater/configuration/local-login phases on an owned engine.

This never starts/stops MySQL, promotes a fresh slot or claims playerbots/world
readiness. The Android caller retains its typed workspace and live DB handle.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import signal
import sys

try:
    from . import android_server_schema_setup as owner, mysql_bootstrap as db, mysql_service as service
    from . import server_content as packaged, server_schema_setup as schema, server_schema_baseline as baseline
    from . import server_update_setup as updates, server_config as configurations
    from . import provision_local_realm as realm, provision_local_account as account
except ImportError:
    import android_server_schema_setup as owner
    import mysql_bootstrap as db
    import mysql_service as service
    import server_content as packaged
    import server_schema_setup as schema
    import server_schema_baseline as baseline
    import server_update_setup as updates
    import server_config as configurations
    import provision_local_realm as realm
    import provision_local_account as account

SCOPE = 'owned-server-installation-staged-pending-playerbots'
SELECTION_SCOPE = 'android-owned-server-installation-selection'
MAX_SELECTION = 128 * 1024
require = schema.require


def checkpoint(cancelled):
    if cancelled is not None and cancelled():
        raise schema.SchemaCancelled('Installation cancelled at a completed phase boundary')


def compose(verified, connection, state, version, *, program, program_identity, template, template_identity,
            original_build_identity, mysql, data, profile, apply_sql, verify_service, expected_uuid,
            progress=None, cancelled=None, state_lease=None):
    """Run available real setup phases; a complete promotion proof is impossible.

    One state lease spans all phases. A durable SQL/updater phase finishes its
    own intent before cancellation is observed at the next phase boundary.
    """
    require(isinstance(verified, packaged.VerifiedContent), 'Verified installation content required')
    require(callable(verify_service) and callable(apply_sql) and
            isinstance(expected_uuid, str) and re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', expected_uuid),
            'Owned installation service, SQL adapter and instance UUID required')
    db.exact_version(version); state = Path(state)
    require(state.is_absolute(), 'Absolute owned installation state required')
    profile = configurations.sealed_profile(profile)
    checkpoint(cancelled)
    def phase(name):
        checkpoint(cancelled)
        require(verify_service() is not False, 'Owned installation service changed')
        if progress is not None: progress(dict(phase=name))
    with db.state_scope(state, state_lease) as lease:
        receipt = db.read_receipt(state / 'database-bootstrap.json', version)
        require(receipt['uuid'] == expected_uuid, 'Installation database UUID differs')
        phase('installation-baseline')
        original = schema.initialize(verified, connection, state, version, apply_sql,
            progress=progress, cancelled=cancelled, state_lease=lease)
        require(original.get('baselineImportCompleted') is True, 'Source baseline did not complete')
        phase('installation-updater-verify')
        plan = updates.prepare(verified, Path(program), program_identity, Path(template), template_identity, Path(mysql),
            original_build_identity=original_build_identity, progress=progress, cancelled=cancelled)
        phase('installation-updater')
        first = updates.apply(plan, connection, state, version, progress=progress, cancelled=cancelled,
                              verify_service=verify_service, state_lease=lease)
        require(first.get('compiledUpdaterCompleted') is True and first.get('sourceLedgersVerified') is True,
                'Compiled updater or source ledgers did not complete')
        phase('installation-updater-reentry')
        repeated = updates.apply(plan, connection, state, version, progress=progress, cancelled=cancelled,
                                 verify_service=verify_service, state_lease=lease)
        require(repeated.get('operation') == 'verified-completed-updater' and
                repeated.get('compiledUpdaterExecuted') is False and repeated.get('compiledUpdaterCompleted') is True and
                repeated.get('sourceLedgersVerified') is True and repeated.get('databaseSnapshots') == first.get('databaseSnapshots'),
                'Same-revision updater reentry differs')
        phase('installation-configurations')
        configured = configurations.render_verified(verified, state, Path(data), Path(mysql), profile=profile)
        require(configured.get('module_configurations_complete') is True and configured.get('lua_scripts_enabled') is False,
                'Complete sealed module configuration required')
        common = dict(profile=profile, data=Path(data), mysql=Path(mysql), expected_uuid=expected_uuid,
                      verify_service=verify_service, state_lease=lease)
        phase('installation-local-realm')
        local_realm = realm.provision_verified(verified, connection, state, version, **common)
        phase('installation-local-account')
        local_account = account.provision_verified(verified, connection, state, version, **common)
        phase('installation-verify-owned-login')
        verified_realm = realm.provision_verified(verified, connection, state, version, verify_only=True, **common)
        verified_account = account.provision_verified(verified, connection, state, version, verify_only=True, **common)
        require(verified_realm.get('operation') == 'verified' and verified_account.get('operation') == 'verified-owned-account' and
                all(row.get('mysqlUuid') == expected_uuid and row.get('completedUpdaterVerified') is True
                    for row in (local_realm, local_account, verified_realm, verified_account)),
                'Owned realm/account verification did not complete')
        phase('installation-staged-pending-playerbots')
        report = dict(formatVersion=1, scope=SCOPE, mysqlUuid=expected_uuid, mysqlVersion=version,
            sourceLockSha256=verified.receipt['sourceLockSha256'], contentReceipt=verified.identities['receipt'],
            compiledModules=verified.receipt['compiledModules'], originalBuild=original_build_identity,
            selectedProgram=program_identity, configGeneration=configured['generation'],
            baselineComplete=True, compiledUpdaterCompleted=True, sourceLedgersVerified=True,
            sameRevisionReentryVerified=True, localRealmVerified=True, localAccountVerified=True,
            ownedServiceIdentityVerified=True, contentFilesVerified=len(verified.identities['files']),
            playerbotsSchemaVerified=False, completeSetupQualified=False, slotPromoted=False,
            databaseServiceStarted=False, databaseServiceStopped=False, authserverExecuted=False,
            worldserverExecuted=False, serverDataQualified=False, androidRuntimeQualified=False, gameplayQualified=False,
            pendingComponents=['playerbots-schema'], sourceBaselineJournal=baseline.file_identity(state / schema.JOURNAL),
            compiledUpdaterJournal=baseline.file_identity(state / updates.JOURNAL),
            localRealmReceipt=baseline.file_identity(state / 'realm-loopback.json'),
            localAccountReceipt=baseline.file_identity(state / 'local-account.json'))
        db.atomic_json(state / 'server-installation-staged.json', report)
        return report


def selection(path):
    selected, _ = owner.read_json(path, MAX_SELECTION)
    fields = {'formatVersion', 'scope', 'source', 'sourceLockSha256', 'contentReceipt', 'compiledModules',
              'program', 'template', 'originalBuild', 'profile'}
    require(set(selected) == fields and type(selected['formatVersion']) is int and selected['formatVersion'] == 1 and
            selected['scope'] == SELECTION_SCOPE and isinstance(selected['sourceLockSha256'], str) and
            re.fullmatch('[a-f0-9]{64}', selected['sourceLockSha256']), 'Invalid installation selection')
    for name in ('contentReceipt', 'compiledModules', 'program', 'template', 'originalBuild', 'profile'):
        pin = selected[name]
        require(isinstance(pin, dict) and set(pin) == {'bytes', 'sha256'} and type(pin['bytes']) is int and
                0 < pin['bytes'] <= (64 * 1024**2 if name == 'program' else packaged.MAX_METADATA) and
                isinstance(pin['sha256'], str) and re.fullmatch('[a-f0-9]{64}', pin['sha256']),
                'Invalid installation artifact pin')
    return selected


def run(state, session, content_root, receipt_path, programs_root, service_session, mysql, data, profile_path,
        version, operation, service_operation, uuid, *, interrupted=lambda: False):
    db.exact_version(version)
    require(re.fullmatch('[a-f0-9]{32}', operation) and re.fullmatch('[a-f0-9]{32}', service_operation) and
            isinstance(uuid, str) and re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', uuid),
            'Invalid installation operation identity')
    for path in (state, session, service_session): service.plain_directory(Path(path))
    require(session != state and not session.is_relative_to(state) and not state.is_relative_to(session),
            'Installation operation overlaps database storage')
    cancelled = lambda: interrupted() or os.path.lexists(session / 'cancel')
    checkpoint(cancelled)
    selected = selection(session / 'selection.json')
    compiled, identity = owner.read_json(programs_root / 'provenance/server-modules.json', packaged.MAX_METADATA)
    require(identity == selected['compiledModules'], 'Installation compiled modules differ')
    build, identity = owner.read_json(programs_root / 'provenance/server-build.json', packaged.MAX_METADATA)
    require(identity == selected['originalBuild'] and compiled.get('serverBuild') == identity and
            build.get('serverSource') == selected['source'] and build.get('sourcesLock', {}).get('sha256') == selected['sourceLockSha256'],
            'Installation original build/source binding differs')
    profile, identity = owner.read_json(profile_path, 65536)
    require(identity == selected['profile'], 'Installation sealed profile changed')
    _, identity = owner.read_json(receipt_path, packaged.MAX_METADATA)
    require(identity == selected['contentReceipt'], 'Installation content receipt differs')
    progress = owner.Progress(session)
    verified = packaged.verify(content_root, receipt_path, selected['contentReceipt']['sha256'],
        selected['source'], selected['sourceLockSha256'], compiled, progress=progress, cancelled=cancelled)
    secret = service.read_plain(state / 'accounts/database-secret', 66).strip()
    require(re.fullmatch(b'[a-f0-9]{64}', secret), 'Existing installation credential required')
    password = secret.decode('ascii'); secret = None
    with db.option_file(session, 'esteria', password) as options:
        password = None
        with db.Mysql(mysql, options) as connection:
            def verify_service():
                owner.live_service(connection, state, service_session, version, service_operation, uuid)
                return True
            index = [0]
            def apply(database, path):
                verify_service()
                owner.apply_file(mysql, options, database, path, session, index[0]); index[0] += 1
                verify_service()
            report = compose(verified, connection, state, version, program=programs_root / 'bin/dbimport',
                program_identity=selected['program'], template=programs_root / 'etc/dbimport.conf.dist',
                template_identity=selected['template'], original_build_identity=selected['originalBuild'], mysql=mysql,
                data=data, profile=profile, apply_sql=apply, verify_service=verify_service, expected_uuid=uuid,
                progress=progress, cancelled=cancelled)
    result = dict(report, operationId=operation, serviceOperationId=service_operation)
    db.atomic_json(session / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('expected-version', 'operation-id', 'service-operation-id', 'instance-uuid'):
        parser.add_argument('--' + argument, required=True)
    args = parser.parse_args(); stopped = [False]
    for signum in (signal.SIGINT, signal.SIGTERM): signal.signal(signum, lambda *_: stopped.__setitem__(0, True))
    try:
        require(re.fullmatch('[a-f0-9]{32}', args.operation_id) and re.fullmatch('[a-f0-9]{32}', args.service_operation_id),
                'Invalid installation operation identity')
        session = Path('/work/installation-operations') / args.operation_id
        run(Path('/work/state'), session, Path('/esteria-server-content'), session / 'content-receipt.json',
            Path('/esteria-server-programs'), Path('/work/mysql-sessions') / args.service_operation_id,
            Path('/usr/bin/mysql'), Path('/esteria-data'), Path(__file__).parent / 'local-server.json',
            args.expected_version, args.operation_id, args.service_operation_id, args.instance_uuid,
            interrupted=lambda: stopped[0])
        print('Owned server installation staged; playerbots schema and complete promotion remain pending')
        return 0
    except Exception as error:
        kind = type(error).__name__
        if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', kind): kind = 'Exception'
        print('Owned installation failed (' + kind + '); private staging and diagnostics retained', file=sys.stderr)
        return 2 if isinstance(error, (schema.SchemaCancelled, packaged.ContentCancelled, updates.UpdateCancelled)) else 1


if __name__ == '__main__': raise SystemExit(main())
