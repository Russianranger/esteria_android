"""Initialize only the source-owned fourth pool on an already owned service.

The compiled helper uses the real database/common loader and prepared statements.
No SQL, ledger row, bot account or character is synthesized here. The caller keeps
its service lease; uncertain execution intent is preserved and never replayed.
"""
from dataclasses import dataclass
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets

try:
    from . import mysql_bootstrap as db, server_content as packaged, server_config as config
    from . import server_schema_setup as schema, server_schema_baseline as baseline
    from . import server_update_setup as core, server_updater as updater
    from . import provision_local_account as account, provision_local_realm as realm
except ImportError:
    import mysql_bootstrap as db
    import server_content as packaged
    import server_config as config
    import server_schema_setup as schema
    import server_schema_baseline as baseline
    import server_update_setup as core
    import server_updater as updater
    import provision_local_account as account
    import provision_local_realm as realm

JOURNAL = '.server-playerbots-schema.json'
SCOPE = 'owned-packaged-content-playerbots-schema-only'
MODULE = 'mod-playerbots'
ROOT = 'modules/mod-playerbots/data/sql/playerbots/'
BASE_COUNT = 29
UPDATE_COUNT = 31
STATEMENTS = 52
MARKER = b'ESTERIA_PLAYERBOTS_DATABASE_REFERENCE_COMPLETE statements='
require = schema.require


@dataclass(frozen=True)
class Preparation:
    content: packaged.VerifiedContent
    executable: Path
    executable_identity: dict
    helper_receipt_identity: dict
    mysql: Path
    expected: dict
    binding: dict


def _selected_content(content, *, progress=None, cancelled=None):
    # Share metadata/original-build and core SQL validation with the core updater.
    _, binding = core._content_inputs(content, progress=progress, cancelled=cancelled)
    require(content.manifest['source']['commit'] == baseline.SUPPORTED_SERVER and
            MODULE in content.compiled['enabledModules'] and 'playerbots.conf' in content.compiled['configFiles'],
            'Pinned compiled playerbots content required')
    plan = content.manifest['databases']['playerbots']
    require(plan.get('executionOrderQualified') is True and isinstance(plan.get('base'), list) and
            len(plan['base']) == BASE_COUNT and plan['base'] == sorted(plan['base']) and
            len(set(plan['base'])) == BASE_COUNT and len(plan.get('updateOrder', [])) == UPDATE_COUNT,
            'Exact source-owned playerbots SQL plan required')
    expected, identities = {}, {}
    for path in plan['base']:
        packaged._path(path)
        require(str(Path(path).parent).replace(os.sep, '/') == ROOT.rstrip('/') + '/base' and path.endswith('.sql'),
                'Playerbots base path differs from its source-owned directory')
    for path, state in [(path, None) for path in plan['base']] + [
            (row['path'], row['state']) for row in plan['updateOrder']]:
        packaged._path(path)
        require(path.startswith(ROOT) and path.endswith('.sql') and path not in identities and
                (state is None or state == 'RELEASED'), 'Playerbots SQL selection requires a new audit')
        pin = {key: content.manifest['files'][path][key] for key in ('bytes', 'sha256')}
        archived = content.receipt['archiveFiles']['source/' + path]
        require(pin == {key: archived[key] for key in pin}, 'Playerbots SQL payload binding differs')
        digest, _ = core._hash(content.source / path, pin, progress=progress, cancelled=cancelled)
        identities[path] = pin
        if state is not None:
            name = Path(path).name
            require(name not in expected, 'Duplicate playerbots update basename')
            expected[name] = (digest, state)
    binding.update(playerbotsPlanSha256=hashlib.sha256(updater.canonical_identity(
        dict(base=plan['base'], updates=expected, files=identities))).hexdigest())
    return expected, binding


def prepare(content, executable, helper_receipt, helper_receipt_sha256, mysql, *, progress=None, cancelled=None):
    """Bind an externally pinned, separately source-built helper to real content."""
    expected, binding = _selected_content(content, progress=progress, cancelled=cancelled)
    executable, helper_receipt, mysql = (Path(path) for path in (executable, helper_receipt, mysql))
    require(all(path.is_absolute() for path in (executable, helper_receipt, mysql)) and
            isinstance(helper_receipt_sha256, str) and re.fullmatch('[a-f0-9]{64}', helper_receipt_sha256),
            'Explicit absolute playerbots helper inputs and receipt digest required')
    executable, helper_receipt, mysql = (db.private_path(path) for path in (executable, helper_receipt, mysql))
    raw = config.bounded_plain(helper_receipt, 2 * 1024**2)
    receipt_identity = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    require(receipt_identity['sha256'] == helper_receipt_sha256, 'Playerbots helper receipt digest differs')
    receipt = packaged._json(raw)
    require(type(receipt.get('formatVersion')) is int and receipt['formatVersion'] == 1 and
            receipt.get('scope') == 'source-built-playerbots-schema-helper' and
            receipt.get('actualCompileSucceeded') is True and
            receipt.get('actualDatabaseSourcesAndDefinitionVerified') is True and
            receipt.get('databaseExecuted') is False and receipt.get('elf', {}).get('machine') == 'AArch64' and
            type(receipt.get('preparedStatementCountDeclared')) is int and receipt['preparedStatementCountDeclared'] == STATEMENTS and
            receipt.get('originalBuild') == content.compiled['serverBuild'] and
            receipt.get('originalModules') == content.receipt['compiledModules'] and
            receipt.get('serverSource') == content.manifest['source'] and
            receipt.get('sourceLock', {}).get('sha256') == content.receipt['sourceLockSha256'],
            'Playerbots helper source/build/module binding differs')
    identity = core._pin(receipt.get('executable'))
    require(identity['bytes'] > 0 and os.access(executable, os.X_OK) and mysql.is_file(),
            'Selected playerbots helper or MySQL client unavailable')
    core._hash(executable, identity, progress=progress, cancelled=cancelled)
    binding.update(helperBuildReceipt=receipt_identity, helperExecutable=identity,
                   helperPath=str(executable), mysqlPath=str(mysql))
    return Preparation(content, executable, identity, receipt_identity, mysql, expected, binding)


def snapshot(connection, expected):
    tables = connection.query('SHOW TABLES FROM `acore_playerbots`')
    require('updates' in tables and 'updates_include' in tables, 'Playerbots source ledger is absent')
    rows = connection.query('SELECT name,hash,state FROM `acore_playerbots`.`updates` ORDER BY name')
    ledger = {}
    for row in rows:
        parts = row.split('\t')
        require(len(parts) == 3 and parts[0] not in ledger, 'Invalid or duplicate playerbots update ledger')
        ledger[parts[0]] = (parts[1].lower(), parts[2])
    require(ledger == expected, 'Playerbots ledger differs from exact selected source SQL')
    columns = connection.query("SELECT HEX(TABLE_NAME),ORDINAL_POSITION,HEX(COLUMN_NAME),HEX(COLUMN_TYPE),"
        "IS_NULLABLE,(COLUMN_DEFAULT IS NULL),HEX(COALESCE(COLUMN_DEFAULT,'')),"
        "HEX(COALESCE(COLLATION_NAME,'')),HEX(EXTRA) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA='acore_playerbots' ORDER BY TABLE_NAME,ORDINAL_POSITION")
    indexes = connection.query("SELECT HEX(TABLE_NAME),HEX(INDEX_NAME),NON_UNIQUE,SEQ_IN_INDEX,"
        "HEX(COALESCE(COLUMN_NAME,'')),COALESCE(SUB_PART,0),HEX(INDEX_TYPE) "
        "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='acore_playerbots' "
        "ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX")
    require(columns and indexes, 'Playerbots source schema metadata is absent')
    return dict(tableCount=len(tables), tablesSha256=hashlib.sha256(updater.canonical_identity(tables)).hexdigest(),
        updateCount=len(rows), ledgerSha256=hashlib.sha256(updater.canonical_identity(rows)).hexdigest(),
        columnsSha256=hashlib.sha256(updater.canonical_identity(columns)).hexdigest(),
        indexesSha256=hashlib.sha256(updater.canonical_identity(indexes)).hexdigest())


def preserved_core(connection):
    """Private binary-safe comparison; never put these row values in a receipt."""
    value = {}
    for name in updater.DATABASES:
        value[name] = dict(tables=connection.query('SHOW TABLES FROM `acore_' + name + '`'),
            ledger=connection.query('SELECT * FROM `acore_' + name + '`.`updates` ORDER BY name'))
    columns = ','.join('HEX(`' + row[0] + '`)' for row in account.COLUMNS['account'])
    value['accounts'] = connection.query('SELECT ' + columns + ' FROM acore_auth.account ORDER BY id')
    value['trackers'] = connection.query('SELECT * FROM acore_auth.realmcharacters ORDER BY realmid,acctid')
    value['realm'] = connection.query(realm.ROW_SQL)
    return value


def _owned_account(connection, state, bootstrap, *, fresh=False):
    """Verify the already completed owner without recovery, DML or journal writes."""
    intent = account.read_intent(state / account.JOURNAL, bootstrap)
    require(intent['phase'] == 'ready', 'Owned account must complete recovery before playerbots setup')
    account_id = account.match_account(account.selected_account(connection, intent['username']), intent)
    counts = connection.query('SELECT numchars FROM acore_auth.realmcharacters WHERE realmid=1 AND acctid=' + str(account_id))
    require(connection.query(realm.ROW_SQL) == [realm.EXPECTED_ROW] and len(counts) == 1 and
            re.fullmatch('[0-9]{1,3}', counts[0]) and int(counts[0]) <= 255 and (not fresh or counts == ['0']),
            'Valid owned realm/account tracker required before playerbots setup')


def render_configuration(content, state, mysql, data, profile, operation):
    password = db.read_secret(state / 'accounts/database-secret')
    generation = realm.active_config_verified(content, state, password, profile=profile, data=data, mysql=mysql)
    source = state / 'config/generations' / generation
    (operation / 'modules').mkdir(mode=0o700)
    world = config.overlay(config.bounded_plain(source / 'worldserver.conf', 4 << 20).decode(), {
        # Core pools already completed the separately journalled stock SQL
        # projection. Only the fourth playerbots loader may update here.
        'Updates.AutoSetup': 0, 'Updates.EnableDatabases': 0, 'Updates.Redundancy': 1,
        'Updates.AllowRehash': 1, 'Updates.ArchivedRedundancy': 0, 'Updates.CleanDeadRefMaxCount': 0,
        'Database.Reconnect.Attempts': 1, 'Database.Reconnect.Seconds': 1, 'Logger.root': '4,Console',
        'TempDir': config.quoted(operation)})
    bots = config.overlay(config.bounded_plain(source / 'modules/playerbots.conf', 4 << 20).decode(), {
        'Playerbots.Updates.EnableDatabases': 1, 'PlayerbotsDatabase.WorkerThreads': 1,
        'PlayerbotsDatabase.SynchThreads': 1})
    path = operation / 'worldserver.conf'
    config.write_private(path, world); config.write_private(operation / 'modules/playerbots.conf', bots)
    return path, generation


def run_loader(executable, configuration, log, *, on_started=None):
    result = updater.run_importer(executable, configuration, log, on_started=on_started)
    raw = config.bounded_plain(log, updater.LOG_LIMIT)
    matches = re.findall(re.escape(MARKER) + rb'([1-9][0-9]{0,3}) mysqlClientLibrary=([A-Za-z0-9.+_~-]{1,96})\r?\n', raw)
    require(len(matches) == 1 and int(matches[0][0]) == STATEMENTS,
            'Actual source playerbots loader/prepared-statements completion missing')
    return dict(result, preparedStatementCount=STATEMENTS, mysqlClientLibrary=matches[0][1].decode('ascii'))


def _receipt(binding, bootstrap, operation, executed, database_snapshot):
    return dict(formatVersion=1, scope=SCOPE, operation=operation, mysqlUuid=bootstrap['uuid'],
        mysqlVersion=bootstrap['version'], sourceLockSha256=binding['sourceLockSha256'],
        contentReceipt=binding['contentReceipt'], compiledModules=binding['compiledModules'],
        originalBuild=binding['originalBuild'], helperBuildReceipt=binding['helperBuildReceipt'],
        helperExecutable=binding['helperExecutable'], playerbotsPlanSha256=binding['playerbotsPlanSha256'],
        playerbotsSchemaInitialized=True, exactSourceLedgerVerified=True, preparedStatementCount=STATEMENTS,
        compiledPlayerbotsLoaderExecuted=executed, preparedStatementsPreviouslyVerified=True,
        coreSchemasLedgersCredentialsAccountPreserved=True, databaseSnapshot=database_snapshot,
        playerbotsAiQualified=False, botCharactersCreated=False, worldserverExecuted=False,
        schemaUpgradeQualified=False, androidRuntimeQualified=False, gameplayQualified=False)


def _verify_completed(content, connection, state, version, *, expected_uuid, verify_service,
                      core_journal_identity, core_snapshot, progress=None, cancelled=None):
    """Called only by the core verifier, inside its retained locks; no recursion."""
    expected, content_binding = _selected_content(content, progress=progress, cancelled=cancelled)
    core.checkpoint(cancelled); core._service(verify_service)
    require(connection.query("SELECT IS_USED_LOCK('esteria-local-bootstrap') = CONNECTION_ID()") == ['1'],
            'Caller must own the bootstrap SQL lock during playerbots verification')
    bootstrap = core._instance(connection, state, version)
    require(bootstrap['uuid'] == expected_uuid, 'Playerbots verification UUID differs')
    path = state / JOURNAL
    journal = schema.private_journal(path); journal_identity = baseline.file_identity(path)
    binding = journal.get('binding', {})
    credentials, account_identity = core._credentials(state), schema.account_identity(state)
    require(type(journal.get('formatVersion')) is int and journal['formatVersion'] == 1 and
            journal.get('scope') == SCOPE and journal.get('phase') == 'complete' and
            journal.get('compiledPlayerbotsLoaderExecuted') is True and
            type(journal.get('run', {}).get('exitCode')) is int and journal['run']['exitCode'] == 0 and
            type(journal.get('run', {}).get('preparedStatementCount')) is int and
            journal['run']['preparedStatementCount'] == STATEMENTS,
            'Completed source-bound playerbots journal required')
    require(all(binding.get(key) == value for key, value in content_binding.items()) and
            binding.get('credentials') == credentials and binding.get('coreUpdaterJournal') == core_journal_identity and
            binding.get('mysqlUuid') == expected_uuid and binding.get('mysqlVersion') == version and
            binding.get('datadir') == bootstrap['datadir'] and journal.get('coreSnapshot') == core_snapshot,
            'Completed playerbots source, core, credentials or instance changed')
    core._pin(binding.get('helperBuildReceipt')); core._pin(binding.get('helperExecutable'))
    require(binding.get('accountJournal') == account_identity, 'Playerbots owned account journal changed')
    _owned_account(connection, state, bootstrap)
    observed = snapshot(connection, expected)
    require(observed == journal.get('snapshot'), 'Completed playerbots tables or source ledgers changed')
    core.checkpoint(cancelled); core._service(verify_service)
    require(core._instance(connection, state, version)['uuid'] == expected_uuid and
            core._credentials(state) == credentials and schema.account_identity(state) == account_identity and
            baseline.file_identity(path) == journal_identity, 'Playerbots private context changed during verification')
    return dict(_receipt(binding, bootstrap, 'verified-completed-playerbots-schema', False, observed),
                journalIdentity=journal_identity)


def verify_completed(content, connection, state, version, *, expected_uuid, verify_service,
                     progress=None, cancelled=None):
    """Read only under the caller's state/service/bootstrap locks; execute nothing."""
    verified = core.verify_completed_update(content, connection, state, version, expected_uuid=expected_uuid,
        verify_service=verify_service, progress=progress, cancelled=cancelled)
    require('playerbots' in verified, 'Completed playerbots schema proof is absent')
    return verified['playerbots']


def apply(plan, connection, state, version, *, profile, data, expected_uuid, verify_service,
          progress=None, cancelled=None, state_lease=None):
    """Initialize the empty fourth schema once; finish a committed unit on cancel."""
    require(isinstance(plan, Preparation) and callable(verify_service), 'Prepared playerbots selection and owned service required')
    state = Path(state); require(state.is_absolute(), 'Absolute owned playerbots state required')
    state = db.private_path(state); data = Path(data); profile = config.sealed_profile(profile)
    core.checkpoint(cancelled)
    refreshed, content_binding = _selected_content(plan.content, progress=progress, cancelled=cancelled)
    require(refreshed == plan.expected and all(plan.binding.get(k) == value for k, value in content_binding.items()),
            'Prepared playerbots source changed')
    with db.state_scope(state, state_lease), realm.config_lock(state):
        bootstrap = core._instance(connection, state, version)
        require(bootstrap['uuid'] == expected_uuid, 'Playerbots instance differs from owned service')
        with realm.named_locks(connection, ('esteria-local-bootstrap', 'esteria-local-realm', 'esteria-local-account')):
            completed = core.verify_completed_update(plan.content, connection, state, version,
                expected_uuid=expected_uuid, verify_service=verify_service, cancelled=cancelled)
            if os.path.lexists(state / JOURNAL):
                journal = schema.private_journal(state / JOURNAL)
                require(journal.get('binding', {}).get('helperBuildReceipt') == plan.helper_receipt_identity and
                        journal.get('binding', {}).get('helperExecutable') == plan.executable_identity,
                        'Playerbots helper changed; upgrades/adoption refused')
                require(journal.get('phase') == 'complete', 'Partial playerbots setup preserved; replay refused')
                require('playerbots' in completed, 'Completed playerbots journal failed live verification')
                return completed['playerbots']
            require(not connection.query('SHOW TABLES FROM `acore_playerbots`') and
                    connection.query('SELECT COUNT(*) FROM `acore_characters`.`characters`') == ['0'],
                    'Existing playerbots schema or characters preserved; fresh setup adoption refused')
            credentials, account_identity = core._credentials(state), schema.account_identity(state)
            require(account_identity is not None, 'Owned account must precede playerbots schema setup')
            _owned_account(connection, state, bootstrap, fresh=True)
            before = preserved_core(connection)
            binding = dict(copy.deepcopy(plan.binding), coreUpdaterJournal=completed['journalIdentity'],
                credentials=credentials, accountJournal=account_identity, mysqlUuid=expected_uuid,
                mysqlVersion=version, datadir=bootstrap['datadir'])
            run = db.private_path(state / 'run'); config.plain_directory(run)
            operation = run / ('playerbots-' + secrets.token_hex(16)); operation.mkdir(mode=0o700)
            configuration, generation = render_configuration(plan.content, state, plan.mysql, data, profile, operation)
            configuration_pin = baseline.file_identity(configuration)
            module_pin = baseline.file_identity(operation / 'modules/playerbots.conf')
            core._service(verify_service); core.checkpoint(cancelled)
            journal = dict(formatVersion=1, scope=SCOPE, phase='in-flight', binding=binding,
                compiledPlayerbotsLoaderExecuted=False, coreSnapshot=completed['databaseSnapshots'])
            db.atomic_json(state / JOURNAL, journal)  # Durable BEFORE the first possible DDL.
            started = False
            def on_started():
                nonlocal started
                started = True
            if progress is not None:
                try: progress(dict(phase='playerbots-schema-intent-committed'))
                except Exception: pass
            try:
                core._service(verify_service); core._instance(connection, state, version)
                core._hash(configuration, configuration_pin)
                core._hash(operation / 'modules/playerbots.conf', module_pin)
                core._hash(plan.executable, plan.executable_identity)
                require(core._credentials(state) == credentials and schema.account_identity(state) == account_identity and
                        baseline.file_identity(state / core.JOURNAL) == completed['journalIdentity'],
                        'Playerbots private context changed before execution')
                result = run_loader(plan.executable, configuration, operation / 'helper-private.log', on_started=on_started)
                require(started, 'Playerbots helper process creation not established')
                observed = snapshot(connection, plan.expected)
                require(preserved_core(connection) == before and core._credentials(state) == credentials and
                        schema.account_identity(state) == account_identity and
                        baseline.file_identity(state / core.JOURNAL) == completed['journalIdentity'] and
                        realm.active_config_verified(plan.content, state, db.read_secret(state / 'accounts/database-secret'),
                            profile=profile, data=data, mysql=plan.mysql) == generation,
                        'Playerbots loader changed core, account, credentials or configuration')
                core._service(verify_service); core._instance(connection, state, version)
                journal.update(phase='complete', compiledPlayerbotsLoaderExecuted=True, run=result, snapshot=observed)
                db.atomic_json(state / JOURNAL, journal)
                checked = verify_completed(plan.content, connection, state, version,
                    expected_uuid=expected_uuid, verify_service=verify_service)
                return dict(checked, operation='initialized-playerbots-schema', compiledPlayerbotsLoaderExecuted=True)
            except BaseException:
                journal.update(phase='failed', compiledPlayerbotsLoaderExecuted=started)
                db.atomic_json(state / JOURNAL, journal)
                raise
