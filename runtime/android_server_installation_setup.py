#!/usr/bin/env python3
"""Stage real source/updater/configuration/local-login phases on an owned engine.

This never starts/stops MySQL or promotes a fresh slot. The separate Playerbots
finish phase verifies four source schemas without claiming world readiness.
The Android caller retains its typed workspace and live DB handle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
    from . import server_playerbots_setup as playerbots
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
    import server_playerbots_setup as playerbots

SCOPE = 'owned-server-installation-staged-pending-playerbots'
VERIFIED_SCOPE = 'owned-server-installation-four-schemas-verified'
STAGED_REPORT = 'server-installation-staged.json'
VERIFIED_REPORT = 'server-installation-verified.json'
FINISH_JOURNAL = '.server-playerbots-finish.json'
FINISH_SCOPE = 'owned-server-installation-playerbots-finish-intent'
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


def _artifact_pin(value, maximum):
    require(isinstance(value, dict) and set(value) == {'bytes', 'sha256'} and
            type(value.get('bytes')) is int and 0 < value['bytes'] <= maximum and
            isinstance(value.get('sha256'), str) and re.fullmatch('[a-f0-9]{64}', value['sha256']),
            'Invalid installation artifact pin')
    return dict(value)


def _pinned_json(path, identity, maximum, *, progress=None, cancelled=None):
    identity = _artifact_pin(identity, maximum)
    path = Path(path)
    require(path.is_absolute(), 'Absolute pinned installation proof required')
    _, raw = updates._hash(db.private_path(path), identity, progress=progress, cancelled=cancelled, capture=True)
    return packaged._json(raw)


def _helper_inputs(verified, helper, helper_identity, helper_receipt, helper_receipt_identity,
                   native_receipt, native_receipt_identity, *, progress=None, cancelled=None):
    """Check sealed build/native attestations without importing host build tools."""
    helper_identity = _artifact_pin(helper_identity, 64 << 20)
    build = _pinned_json(helper_receipt, helper_receipt_identity, 2 << 20,
                         progress=progress, cancelled=cancelled)
    native = _pinned_json(native_receipt, native_receipt_identity, 2 << 20,
                          progress=progress, cancelled=cancelled)
    require(type(build.get('formatVersion')) is int and build['formatVersion'] == 1 and
            build.get('scope') == 'source-built-playerbots-schema-helper' and
            build.get('phase') == 'built-component' and build.get('buildTarget') == 'esteria_playerbots_database_reference' and
            build.get('actualCompileSucceeded') is True and build.get('actualDatabaseSourcesAndDefinitionVerified') is True and
            build.get('databaseExecuted') is False and build.get('sqlExecuted') is False and
            build.get('originalServerProgramsReplaced') is False and build.get('elf', {}).get('machine') == 'AArch64' and
            type(build.get('preparedStatementCountDeclared')) is int and build['preparedStatementCountDeclared'] == 52 and
            build.get('originalBuild') == verified.compiled['serverBuild'] and
            build.get('originalModules') == verified.receipt['compiledModules'] and
            build.get('serverSource') == verified.manifest['source'] and
            build.get('sourceLock', {}).get('sha256') == verified.receipt['sourceLockSha256'] and
            build.get('executable') == helper_identity,
            'Playerbots helper build/source/module binding differs')
    positive = ('initializedNewInstance', 'productionCoreCompositionCompleted',
        'playerbotsDatabaseAndStatementsQualified', 'exactSourceUpdateLedgerVerified',
        'completedJournalReentryWithoutExecution', 'actualLoaderReentryVerified', 'restartPersistenceVerified',
        'fixtureProbeRemoved', 'finalFourSchemaProductVerification',
        'coreSchemasLedgersCredentialsAccountPreserved', 'cleanShutdownVerified')
    negative = ('playerbotsAiQualified', 'botCharactersCreated', 'authserverExecuted', 'worldserverExecuted',
        'completeSetupQualified', 'slotPromoted', 'existingStateModified', 'schemaUpgradeQualified',
        'androidRuntimeQualified', 'gameplayQualified')
    require(type(native.get('formatVersion')) is int and native['formatVersion'] == 1 and
            native.get('scope') == 'disposable-native-arm64-product-playerbots-schema' and
            native.get('phase') == 'complete' and native.get('qualificationSucceeded') is True and
            all(native.get(name) is True for name in positive) and all(native.get(name) is False for name in negative) and
            not any(name.startswith(('failure', 'cleanupFailure')) for name in native) and
            native.get('originalBuild') == verified.compiled['serverBuild'] and
            native.get('compiledModules') == verified.receipt['compiledModules'] and
            native.get('source') == verified.manifest['source'] and
            native.get('sourceLockSha256') == verified.receipt['sourceLockSha256'] and
            native.get('contentReceipt') == verified.identities['receipt'] and
            native.get('helperBuildReceipt') == helper_receipt_identity and native.get('helperExecutable') == helper_identity and
            type(native.get('preparedStatementCount')) is int and native['preparedStatementCount'] == 52 and
            type(native.get('selectedSourceBaseFiles')) is int and native['selectedSourceBaseFiles'] == 29 and
            type(native.get('selectedSourceUpdates')) is int and native['selectedSourceUpdates'] == 31,
            'Actual native playerbots schema qualification differs')
    db.exact_version(native.get('mysqlVersion', ''))
    native_uuid = native.get('mysqlUuid')
    require(isinstance(native_uuid, str) and re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', native_uuid),
            'Native playerbots qualification instance missing')
    for index, name in enumerate(('playerbotsFirst', 'playerbotsCompletedReentry')):
        row = native.get(name, {})
        require(row.get('scope') == playerbots.SCOPE and row.get('mysqlUuid') == native_uuid and
                row.get('mysqlVersion') == native['mysqlVersion'] and
                row.get('originalBuild') == native['originalBuild'] and row.get('compiledModules') == native['compiledModules'] and
                row.get('contentReceipt') == native['contentReceipt'] and row.get('sourceLockSha256') == native['sourceLockSha256'] and
                row.get('helperBuildReceipt') == helper_receipt_identity and row.get('helperExecutable') == helper_identity and
                type(row.get('preparedStatementCount')) is int and row['preparedStatementCount'] == 52 and
                row.get('compiledPlayerbotsLoaderExecuted') is (index == 0) and
                row.get('playerbotsSchemaInitialized') is True and row.get('exactSourceLedgerVerified') is True and
                row.get('coreSchemasLedgersCredentialsAccountPreserved') is True and
                row.get('databaseSnapshot') == native.get('databaseSnapshot'), 'Native playerbots reentry binding differs')
    helper = Path(helper)
    require(helper.is_absolute(), 'Absolute sealed playerbots helper required')
    updates._hash(db.private_path(helper), helper_identity, progress=progress, cancelled=cancelled)
    return build, native


def _generation(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def _finish_public_receipts(verified, state, staged, final_generation, *, transitioning):
    """Only this known transition may refresh the two public verification receipts."""
    for name, field, scope, operation in (
            ('realm-loopback.json', 'localRealmReceipt', 'owned-verified-content-local-realm-after-compiled-updater', 'verified'),
            ('local-account.json', 'localAccountReceipt',
             'owned-verified-content-local-account-after-compiled-updater-and-realm', 'verified-owned-account')):
        receipt = schema.private_journal(state / name)
        if baseline.file_identity(state / name) == staged[field]: continue
        require(transitioning and type(receipt.get('formatVersion')) is int and receipt['formatVersion'] == 1 and
                receipt.get('scope') == scope and receipt.get('operation') == operation and
                receipt.get('mysqlUuid') == staged['mysqlUuid'] and receipt.get('mysqlVersion') == staged['mysqlVersion'] and
                receipt.get('sourceLockSha256') == verified.receipt['sourceLockSha256'] and
                receipt.get('contentReceipt') == verified.identities['receipt'] and
                receipt.get('compiledModules') == verified.receipt['compiledModules'] and
                receipt.get('configGeneration') == final_generation and receipt.get('completedUpdaterVerified') is True and
                receipt.get('androidRuntimeQualified') is False and receipt.get('gameplayQualified') is False and
                (receipt.get('serverStarted') is False if field == 'localRealmReceipt' else
                 receipt.get('existingCredentialsReset') is False and receipt.get('charactersCreated') is False),
                'Staged local realm/account receipt changed outside the known configuration transition')


def finish_playerbots(verified, connection, state, version, *, helper, helper_identity,
                      helper_receipt, helper_receipt_identity, native_receipt, native_receipt_identity,
                      mysql, data, profile, expected_uuid, verify_service, progress=None, cancelled=None,
                      state_lease=None, staged_data=None):
    """Fixed production ARM64 admission followed by the shared finish kernel.

    Neither this public function nor the CLI accepts a policy, plan, bypass flag
    or result from its caller. A qualification-only source wrapper may use the
    private kernel with a separately measured architecture's real admission.
    """
    def verify_helper():
        return _helper_inputs(verified, helper, helper_identity, helper_receipt, helper_receipt_identity,
            native_receipt, native_receipt_identity, progress=progress, cancelled=cancelled)
    def prepare_helper():
        return playerbots.prepare(verified, Path(helper), Path(helper_receipt), helper_receipt_identity['sha256'],
            mysql, progress=progress, cancelled=cancelled)
    return _finish_playerbots(verified, connection, state, version, helper=helper, helper_identity=helper_identity,
        helper_receipt=helper_receipt, helper_receipt_identity=helper_receipt_identity,
        native_receipt=native_receipt, native_receipt_identity=native_receipt_identity,
        mysql=mysql, data=data, profile=profile, expected_uuid=expected_uuid, verify_service=verify_service,
        progress=progress, cancelled=cancelled, state_lease=state_lease, staged_data=staged_data,
        prepare_helper=prepare_helper, verify_helper=verify_helper)


def _finish_playerbots(verified, connection, state, version, *, helper, helper_identity,
                      helper_receipt, helper_receipt_identity, native_receipt, native_receipt_identity,
                      mysql, data, profile, expected_uuid, verify_service, prepare_helper, verify_helper,
                      progress=None, cancelled=None, state_lease=None, staged_data=None):
    """Finish the fourth source schema on the caller's same retained engine.

    Source-owned admission produces a real Preparation, never a fabricated SQL
    result. This private seam is absent from the public function and CLI.
    The original staged marker is immutable. A private transition intent permits
    cancellation before the PB SQL intent without adopting arbitrary configs.
    Shared PB journals retain their own uncertain-execution refusal semantics.
    No baseline/updater, engine start/stop, promotion or gameplay is performed.
    """
    require(isinstance(verified, packaged.VerifiedContent) and callable(verify_service) and
            callable(prepare_helper) and callable(verify_helper) and
            isinstance(expected_uuid, str) and re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', expected_uuid),
            'Verified content and retained installation service required')
    db.exact_version(version); state, mysql, data = (Path(path) for path in (state, mysql, data))
    staged_data = data if staged_data is None else Path(staged_data)
    require(all(path.is_absolute() for path in (state, mysql, data, staged_data)), 'Absolute installation finish paths required')
    state = db.private_path(state); profile = configurations.sealed_profile(profile)
    checkpoint(cancelled)
    def phase(name):
        checkpoint(cancelled)
        require(verify_service() is not False, 'Owned installation service changed')
        if progress is not None: progress(dict(phase=name))
    with db.state_scope(state, state_lease) as lease:
        phase('installation-playerbots-proofs')
        verify_helper()
        plan = prepare_helper()
        require(isinstance(plan, playerbots.Preparation) and plan.content is verified and
                plan.executable == Path(helper) and plan.mysql == mysql and
                plan.executable_identity == helper_identity and plan.helper_receipt_identity == helper_receipt_identity,
                'Sealed playerbots helper selection differs')
        with realm.config_lock(state), realm.named_locks(connection,
                ('esteria-local-bootstrap', 'esteria-local-realm', 'esteria-local-account')):
            phase('installation-playerbots-staged-verify')
            staged = schema.private_journal(state / STAGED_REPORT)
            staged_identity = baseline.file_identity(state / STAGED_REPORT)
            require(type(staged.get('formatVersion')) is int and staged['formatVersion'] == 1 and staged.get('scope') == SCOPE and
                    staged.get('mysqlUuid') == expected_uuid and staged.get('mysqlVersion') == version and
                    staged.get('sourceLockSha256') == verified.receipt['sourceLockSha256'] and
                    staged.get('contentReceipt') == verified.identities['receipt'] and
                    staged.get('compiledModules') == verified.receipt['compiledModules'] and
                    staged.get('originalBuild') == verified.compiled['serverBuild'] and
                    all(staged.get(name) is True for name in ('baselineComplete', 'compiledUpdaterCompleted',
                        'sourceLedgersVerified', 'sameRevisionReentryVerified', 'localRealmVerified',
                        'localAccountVerified', 'ownedServiceIdentityVerified')) and
                    all(staged.get(name) is False for name in ('playerbotsSchemaVerified', 'completeSetupQualified',
                        'slotPromoted', 'databaseServiceStarted', 'databaseServiceStopped', 'authserverExecuted',
                        'worldserverExecuted', 'serverDataQualified', 'androidRuntimeQualified', 'gameplayQualified')) and
                    staged.get('pendingComponents') == ['playerbots-schema'], 'Authentic private staged installation required')
            completed = updates.verify_completed_update(verified, connection, state, version,
                expected_uuid=expected_uuid, verify_service=verify_service, progress=progress, cancelled=cancelled)
            require(completed.get('compiledUpdaterCompleted') is True and completed.get('compiledUpdaterExecuted') is False and
                    completed.get('sourceLedgersVerified') is True and completed.get('originalBuild') == staged['originalBuild'] and
                    completed.get('selectedProgram') == staged.get('selectedProgram') and
                    completed.get('journalIdentity') == staged.get('compiledUpdaterJournal') and
                    completed.get('baselineJournalIdentity') == staged.get('sourceBaselineJournal'),
                    'Staged baseline, original build or selected updater changed')
            playerbots._owned_account(connection, state, db.read_receipt(state / 'database-bootstrap.json', version))
            password = db.read_secret(state / 'accounts/database-secret')
            old_files = configurations.expected_private_files_verified(verified, state, staged_data, mysql,
                profile=profile, secret=password)
            final_files = configurations.expected_private_files_verified(verified, state, data, mysql,
                profile=profile, secret=password)
            old_generation, final_generation = _generation(old_files), _generation(final_files)
            require(staged.get('configGeneration') == old_generation and
                    realm.generation_files(state / 'config/generations' / old_generation) == old_files,
                    'Original complete staged configuration changed')
            active_generation, active_files = realm._active_generation(state, password)
            require((active_generation == old_generation and active_files == old_files) or
                    (active_generation == final_generation and active_files == final_files),
                    'Active configuration is outside the sealed finish transition')
            binding = dict(stagedInstallationReceipt=staged_identity, mysqlUuid=expected_uuid, mysqlVersion=version,
                bootstrapReceipt=baseline.file_identity(state / 'database-bootstrap.json'),
                source=verified.manifest['source'], sourceLockSha256=verified.receipt['sourceLockSha256'],
                contentReceipt=verified.identities['receipt'], compiledModules=verified.receipt['compiledModules'],
                originalBuild=staged['originalBuild'], selectedProgram=staged['selectedProgram'],
                sourceBaselineJournal=completed['baselineJournalIdentity'], compiledUpdaterJournal=completed['journalIdentity'],
                accountJournal=schema.account_identity(state), credentials=updates._credentials(state),
                helperExecutable=helper_identity, helperBuildReceipt=helper_receipt_identity, helperNativeReceipt=native_receipt_identity,
                stagedConfigGeneration=old_generation, finalConfigGeneration=final_generation)
            require(binding['accountJournal'] is not None, 'Private owned account intent required')
            intent_path = state / FINISH_JOURNAL
            transitioning = os.path.lexists(intent_path)
            if transitioning:
                intent = schema.private_journal(intent_path)
                require(set(intent) == {'formatVersion', 'scope', 'binding'} and type(intent['formatVersion']) is int and
                        intent['formatVersion'] == 1 and intent['scope'] == FINISH_SCOPE and intent['binding'] == binding,
                        'Playerbots finish transition binding changed; adoption refused')
            else:
                require(active_generation == old_generation, 'Unjournaled configuration transition refused')
            _finish_public_receipts(verified, state, staged, final_generation, transitioning=transitioning)
            checkpoint(cancelled)
            if not transitioning:
                db.atomic_json(intent_path, dict(formatVersion=1, scope=FINISH_SCOPE, binding=binding))
            finish_identity = baseline.file_identity(intent_path)
            password = None; old_files = final_files = active_files = None
        phase('installation-playerbots-configurations')
        configured = configurations.render_verified(verified, state, data, mysql, profile=profile)
        require(configured.get('module_configurations_complete') is True and configured.get('lua_scripts_enabled') is False and
                configured.get('generation') == final_generation, 'Final complete configuration differs')
        phase('installation-playerbots-schema')
        applied = playerbots.apply(plan, connection, state, version, profile=profile, data=data,
            expected_uuid=expected_uuid, verify_service=verify_service, progress=progress, cancelled=cancelled, state_lease=lease)
        require(applied.get('playerbotsSchemaInitialized') is True and applied.get('exactSourceLedgerVerified') is True and
                applied.get('preparedStatementCount') == 52 and applied.get('mysqlUuid') == expected_uuid,
                'Playerbots schema did not complete')
        common = dict(profile=profile, data=data, mysql=mysql, expected_uuid=expected_uuid,
                      verify_service=verify_service, state_lease=lease, verify_only=True)
        phase('installation-playerbots-local-verify')
        local_realm = realm.provision_verified(verified, connection, state, version, **common)
        local_account = account.provision_verified(verified, connection, state, version, **common)
        require(local_realm.get('operation') == 'verified' and local_account.get('operation') == 'verified-owned-account' and
                all(row.get('mysqlUuid') == expected_uuid and row.get('completedUpdaterVerified') is True and
                    row.get('configGeneration') == final_generation for row in (local_realm, local_account)),
                'Final owned realm/account verification failed')
        with realm.config_lock(state), realm.named_locks(connection,
                ('esteria-local-bootstrap', 'esteria-local-realm', 'esteria-local-account')):
            phase('installation-four-schemas-verify')
            completed = updates.verify_completed_update(verified, connection, state, version,
                expected_uuid=expected_uuid, verify_service=verify_service, progress=progress, cancelled=cancelled)
            bots = completed.get('playerbots', {})
            require(bots.get('playerbotsSchemaInitialized') is True and bots.get('exactSourceLedgerVerified') is True and
                    bots.get('compiledPlayerbotsLoaderExecuted') is False and bots.get('preparedStatementCount') == 52 and
                    bots.get('helperBuildReceipt') == helper_receipt_identity and bots.get('helperExecutable') == helper_identity and
                    bots.get('mysqlUuid') == expected_uuid, 'Final source-owned four-schema verification failed')
            require(completed.get('journalIdentity') == binding['compiledUpdaterJournal'] and
                    completed.get('baselineJournalIdentity') == binding['sourceBaselineJournal'] and
                    baseline.file_identity(state / STAGED_REPORT) == staged_identity and
                    baseline.file_identity(state / FINISH_JOURNAL) == finish_identity and
                    baseline.file_identity(state / 'database-bootstrap.json') == binding['bootstrapReceipt'] and
                    updates._credentials(state) == binding['credentials'] and
                    schema.account_identity(state) == binding['accountJournal'] and
                    realm.active_config_verified(verified, state, db.read_secret(state / 'accounts/database-secret'),
                        profile=profile, data=data, mysql=mysql) == final_generation,
                    'Installation private source, credentials, account or configuration changed')
            verify_helper()
            _finish_public_receipts(verified, state, staged, final_generation, transitioning=True)
            phase('installation-four-schemas-verified')
            report = dict(formatVersion=1, scope=VERIFIED_SCOPE, mysqlUuid=expected_uuid, mysqlVersion=version,
                source=verified.manifest['source'], sourceLockSha256=verified.receipt['sourceLockSha256'],
                contentReceipt=verified.identities['receipt'], compiledModules=verified.receipt['compiledModules'],
                originalBuild=binding['originalBuild'], selectedProgram=binding['selectedProgram'],
                helperExecutable=helper_identity, helperBuildReceipt=helper_receipt_identity, helperNativeReceipt=native_receipt_identity,
                configGeneration=final_generation, sourceBaselineJournal=binding['sourceBaselineJournal'],
                compiledUpdaterJournal=binding['compiledUpdaterJournal'], playerbotsSchemaJournal=bots['journalIdentity'],
                localAccountJournal=binding['accountJournal'],
                localRealmReceipt=baseline.file_identity(state / 'realm-loopback.json'),
                localAccountReceipt=baseline.file_identity(state / 'local-account.json'),
                stagedInstallationReceipt=staged_identity, playerbotsFinishJournal=finish_identity,
                databaseSnapshots=completed['databaseSnapshots'], playerbotsDatabaseSnapshot=bots['databaseSnapshot'],
                baselineComplete=True, compiledUpdaterCompleted=True, sourceLedgersVerified=True,
                sameRevisionReentryVerified=True, fourSchemasVerified=True, playerbotsSchemaVerified=True,
                localRealmVerified=True, localAccountVerified=True, ownedServiceIdentityVerified=True,
                compiledUpdaterExecuted=False, compiledPlayerbotsLoaderExecuted=applied['compiledPlayerbotsLoaderExecuted'],
                engineStopped=False, completeSetupQualified=False, slotPromoted=False,
                databaseServiceStarted=False, databaseServiceStopped=False, authserverExecuted=False,
                worldserverExecuted=False, serverDataQualified=False, playerbotsAiQualified=False,
                botCharactersCreated=False, androidRuntimeQualified=False, gameplayQualified=False,
                pendingComponents=['owned-clean-engine-stop'])
            db.atomic_json(state / VERIFIED_REPORT, report)
            return report


def selection(path, phase='core'):
    require(phase in ('core', 'playerbots'), 'Invalid installation phase')
    selected, _ = owner.read_json(path, MAX_SELECTION)
    fields = {'formatVersion', 'scope', 'source', 'sourceLockSha256', 'contentReceipt', 'compiledModules',
              'program', 'template', 'originalBuild', 'profile'}
    if phase == 'playerbots': fields.add('playerbotsHelper')
    require(set(selected) == fields and type(selected['formatVersion']) is int and selected['formatVersion'] == 1 and
            selected['scope'] == SELECTION_SCOPE and isinstance(selected['sourceLockSha256'], str) and
            re.fullmatch('[a-f0-9]{64}', selected['sourceLockSha256']), 'Invalid installation selection')
    for name in ('contentReceipt', 'compiledModules', 'program', 'template', 'originalBuild', 'profile'):
        _artifact_pin(selected[name], 64 << 20 if name == 'program' else packaged.MAX_METADATA)
    if phase == 'playerbots':
        helper = selected['playerbotsHelper']
        require(isinstance(helper, dict) and set(helper) == {'executable', 'buildReceipt', 'nativeReceipt'},
                'Invalid playerbots installation selection')
        for name in helper: _artifact_pin(helper[name], 64 << 20 if name == 'executable' else 2 << 20)
    return selected


def run(state, session, content_root, receipt_path, programs_root, service_session, mysql, data, profile_path,
        version, operation, service_operation, uuid, *, interrupted=lambda: False, phase='core'):
    """Fixed production entry point; architecture admission is not caller input."""
    return _run(state, session, content_root, receipt_path, programs_root, service_session, mysql, data, profile_path,
        version, operation, service_operation, uuid, interrupted=interrupted, phase=phase,
        finish_phase=finish_playerbots)


def _run(state, session, content_root, receipt_path, programs_root, service_session, mysql, data, profile_path,
         version, operation, service_operation, uuid, *, finish_phase, interrupted=lambda: False, phase='core'):
    """Shared owned-service/selection kernel for source-owned entry wrappers."""
    require(callable(finish_phase), 'Source-owned installation finish function required')
    db.exact_version(version)
    require(re.fullmatch('[a-f0-9]{32}', operation) and re.fullmatch('[a-f0-9]{32}', service_operation) and
            isinstance(uuid, str) and re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', uuid),
            'Invalid installation operation identity')
    for path in (state, session, service_session): service.plain_directory(Path(path))
    require(session != state and not session.is_relative_to(state) and not state.is_relative_to(session),
            'Installation operation overlaps database storage')
    cancelled = lambda: interrupted() or os.path.lexists(session / 'cancel')
    checkpoint(cancelled)
    selected = selection(session / 'selection.json', phase)
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
            if phase == 'playerbots':
                pins = selected['playerbotsHelper']
                with db.state_scope(state) as lease:
                    staged = schema.private_journal(state / STAGED_REPORT)
                    require(staged.get('selectedProgram') == selected['program'] and
                            schema.private_journal(state / updates.JOURNAL).get('binding', {}).get('template') == selected['template'],
                            'Playerbots selection differs from the staged original programs')
                    report = finish_phase(verified, connection, state, version,
                        helper=programs_root / 'helpers/playerbots-schema', helper_identity=pins['executable'],
                        helper_receipt=programs_root / 'provenance/playerbots-helper-build.json', helper_receipt_identity=pins['buildReceipt'],
                        native_receipt=programs_root / 'provenance/playerbots-native-sql.json', native_receipt_identity=pins['nativeReceipt'],
                        mysql=mysql, data=data / 'data', staged_data=data, profile=profile, verify_service=verify_service,
                        expected_uuid=uuid, progress=progress, cancelled=cancelled, state_lease=lease)
            else:
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
    parser.add_argument('--phase', choices=('core', 'playerbots'), default='core')
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
            interrupted=lambda: stopped[0], phase=args.phase)
        print('Owned server installation four schemas verified; clean engine stop and promotion remain pending'
              if args.phase == 'playerbots' else
              'Owned server installation staged; playerbots schema and complete promotion remain pending')
        return 0
    except Exception as error:
        kind = type(error).__name__
        if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', kind): kind = 'Exception'
        print('Owned installation failed (' + kind + '); private staging and diagnostics retained', file=sys.stderr)
        return 2 if isinstance(error, (schema.SchemaCancelled, packaged.ContentCancelled, updates.UpdateCancelled)) else 1


if __name__ == '__main__': raise SystemExit(main())
