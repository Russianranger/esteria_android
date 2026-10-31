"""Journal one exact compiled-updater operation on an already owned SQL service.

This module neither initializes a database nor starts a MySQL/auth/world service.
The caller retains its exclusive service lease. Interrupted or failed updater
intent is preserved and refused; completed repeats verify ledgers without replay.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

try:
    from . import mysql_bootstrap as db, server_content as packaged, server_updater as updater
    from . import server_schema_setup as schema, server_schema_baseline as baseline
except ImportError:
    import mysql_bootstrap as db
    import server_content as packaged
    import server_updater as updater
    import server_schema_setup as schema
    import server_schema_baseline as baseline

JOURNAL = '.server-compiled-updater.json'
SCOPE = 'owned-packaged-content-compiled-updater-only'
BLOCK = 128 * 1024
require = schema.require
CONTENT_PROFILE = updater.config.CONTENT_PROFILE
STOCK_SQL_POLICY = 'stock-world-source-selection-v2'
_CUSTOM_WORLD_MODULES = frozenset(('mod-custom-server', 'mod-classless-wildcard', 'mod-worgoblin-high-elf',
                                  'mod-individual-progression'))
STOCK_OVERLAYS_SQL = ('SELECT (SELECT COUNT(*) FROM acore_world.chrraces_dbc),'
    '(SELECT COUNT(*) FROM acore_world.chrclasses_dbc),'
    '(SELECT COUNT(*) FROM acore_world.map_dbc),'
    '(SELECT COUNT(*) FROM acore_world.charstartoutfit_dbc)')
STOCK_START_SQL = ('SELECT COUNT(*) FROM acore_world.playercreateinfo WHERE race=1 AND class=1 '
    'AND map=0 AND zone=12 AND ABS(position_x + 8949.95)<0.005 '
    'AND ABS(position_y + 132.493)<0.0005 AND ABS(position_z - 83.5312)<0.0005 '
    'AND ABS(orientation)<0.0001')


def stock_world_sql_snapshot(connection):
    """Query the actual combined-content SQL input, without claiming DBC loads.

    Four source-baseline empty overlays must leave races/classes/maps/outfits to
    the supplied stock DBCs. Other source corrections (including Spell.dbc SQL)
    remain unchanged. The world loader still validates actual DBC rows and
    geographical data before the owned readiness protocol can complete.
    """
    require(connection.query(STOCK_OVERLAYS_SQL) == ['0\t0\t0\t0'],
            'Stock SQL closure changed: ChrRaces/ChrClasses/Map/CharStartOutfit overlays must be empty; '
            'preserving this installation for diagnosis')
    require(connection.query(STOCK_START_SQL) == ['1'],
            'Stock Human Warrior start missing or changed: expected map 0, zone 12, Northshire; '
            'preserving this installation for diagnosis')
    return dict(contentProfile=CONTENT_PROFILE, stockRaceClassMapOutfitSqlOverlaysEmpty=True,
                humanWarriorNorthshireStartVerified=True, actualFileDbcRowsLoaded=False,
                worldStartupExecuted=False, gameplayQualified=False)


def stock_update_selected(database, row):
    """Select authentic source files, keeping compiled schema requirements.

    The pinned core pending-world directory contains custom race/model/map
    content. Its pure four-table DDL prerequisite is retained; ordinary released
    and archived core updates, and character/auth schema updates, are unchanged.
    Battlemon's catalog schemas remain available to its unconditional loader,
    while its separate custom world actors are not installed.
    """
    path = row['path']
    if database != 'world':
        return True
    if path.startswith('data/sql/updates/pending_db_world/'):
        return path == baseline.CUSTOM_RACE_DDL
    parts = Path(path).parts
    if len(parts) >= 2 and parts[0] == 'modules' and parts[1] in _CUSTOM_WORLD_MODULES:
        return False
    if path.startswith('modules/mod-battlemon/data/sql/world/'):
        return False
    if path == 'modules/mod-transmog/data/sql/db-world/2016_11_17_transmog_npc.sql':
        return False
    return True


def _stock_selection(content):
    require(content.manifest.get('source', {}).get('commit') == baseline.SUPPORTED_SERVER,
            'Stock SQL selection requires the audited server revision')
    return {database: [row for row in content.manifest['databases'][database]['updateOrder']
                       if stock_update_selected(database, row)] for database in updater.DATABASES}


def _project_stock_sql(plan, operation, *, cancelled=None):
    """Stream a private, source-verified SQL view; never modify packaged source.

    The source-supported dbimport discovery sees only selected paths. Copying
    prevents a shared hard link from weakening immutable-source validation. All
    SQL bytes remain exact source bytes, with no generated rows or ledger edits.
    """
    destination = operation / 'stock-sql-source'
    destination.mkdir(mode=0o700)
    selected = _stock_selection(plan.content)
    require(hashlib.sha256(updater.canonical_identity(selected)).hexdigest() ==
            plan.binding['selectedSourcePathsSha256'], 'Prepared stock SQL path selection changed')
    inventory = {}
    for database in updater.DATABASES:
        for row in selected[database]:
            checkpoint(cancelled)
            relative = row['path']; packaged._path(relative)
            pin = _pin({key: plan.content.manifest['files'][relative][key] for key in ('bytes', 'sha256')})
            archived = plan.content.receipt['archiveFiles']['source/' + relative]
            require(pin == {key: archived[key] for key in ('bytes', 'sha256')}, 'Stock SQL archived pin changed')
            target = destination / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            count, digest = 0, hashlib.sha256()
            with updater.plain_file(plan.content.source / relative) as source, target.open('xb') as output:
                os.chmod(target, 0o600)
                before = os.fstat(source.fileno())
                require(before.st_size == pin['bytes'] and before.st_nlink == 1, 'Stock SQL source size or sharing changed')
                while block := source.read(BLOCK):
                    checkpoint(cancelled)
                    count += len(block)
                    require(count <= pin['bytes'], 'Stock SQL source grew while projecting')
                    digest.update(block); output.write(block)
                output.flush(); os.fsync(output.fileno())
                after = os.fstat(source.fileno())
            require(dict(bytes=count, sha256=digest.hexdigest()) == pin and
                    (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'Stock SQL source identity changed')
            inventory[relative] = pin
    receipt = dict(formatVersion=1, contentProfile=CONTENT_PROFILE, sqlSelectionPolicy=STOCK_SQL_POLICY,
                   selectedUpdatesSha256=plan.binding['selectedUpdatesSha256'], files=inventory,
                   sourceFilesModified=False, sqlExecuted=False, worldStartupExecuted=False)
    db.atomic_json(destination / 'stock-sql-selection.json', receipt)
    return destination, inventory


def _verify_stock_sql(destination, inventory):
    expected = set(inventory) | {'stock-sql-selection.json'}
    actual = set()
    for folder, dirs, names in os.walk(destination, followlinks=False):
        for name in dirs + names:
            require(not (Path(folder) / name).is_symlink(), 'Stock SQL projection contains a link')
        actual.update((Path(folder) / name).relative_to(destination).as_posix() for name in names)
        require(len(actual) <= len(expected), 'Stock SQL projection file set changed')
    require(actual == expected, 'Stock SQL projection file set changed')
    for relative, pin in inventory.items():
        _hash(destination / relative, pin)


class UpdateCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class Preparation:
    content: packaged.VerifiedContent
    executable: Path
    selected_program_identity: dict
    template: Path
    template_identity: dict
    mysql: Path
    original_build_identity: dict
    expected: dict
    binding: dict


def checkpoint(cancelled):
    if cancelled is not None and cancelled():
        raise UpdateCancelled('Compiled updater cancelled before durable execution intent')


def _pin(value):
    require(isinstance(value, dict) and set(value) == {'bytes', 'sha256'} and
            type(value.get('bytes')) is int and 0 <= value['bytes'] <= 4 * 1024**3 and
            isinstance(value.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', value['sha256']),
            'Explicit compiled updater artifact identity required')
    return dict(value)


def _hash(path, pin, *, progress=None, cancelled=None, capture=False):
    checkpoint(cancelled)
    pin = _pin(pin)
    sha256, sha1, count, chunks = hashlib.sha256(), hashlib.sha1(), 0, []
    with updater.plain_file(path) as stream:
        before = os.fstat(stream.fileno())
        require(before.st_size == pin['bytes'] and before.st_nlink == 1, 'Updater artifact size or sharing changed')
        while block := stream.read(BLOCK):
            checkpoint(cancelled)
            count += len(block)
            require(count <= pin['bytes'], 'Updater artifact grew during verification')
            sha256.update(block); sha1.update(block)
            if capture: chunks.append(block)
            if progress is not None:
                progress(dict(phase='verify-updater-input', bytes=count, totalBytes=pin['bytes']))
            checkpoint(cancelled)
        after = os.fstat(stream.fileno())
    require(count == pin['bytes'] and sha256.hexdigest() == pin['sha256'] and
            (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'Updater artifact identity changed')
    return sha1.hexdigest(), b''.join(chunks) if capture else None


def _content_inputs(content, *, progress=None, cancelled=None):
    checkpoint(cancelled)
    require(isinstance(content, packaged.VerifiedContent) and content.source == content.root / 'source',
            'Verified extracted updater content required')
    metadata = {}
    for name, expected, maximum in (('content-manifest', content.manifest, 16 * 1024**2),
                                     ('compiled-modules', content.compiled, 1024**2)):
        relative = 'metadata/' + name + '.json'
        pin = _pin(content.identities['files'][relative])
        require(pin == content.receipt['archiveFiles'][relative] and pin['bytes'] <= maximum,
                'Archived updater metadata binding differs')
        _, raw = _hash(content.root / relative, pin, progress=progress, cancelled=cancelled, capture=True)
        require(json.loads(raw) == expected, 'Archived updater metadata object changed')
        metadata[name] = pin
    require(content.manifest.get('source') == content.compiled.get('source') == content.receipt.get('source') and
            content.manifest.get('sourceLockSha256') == content.compiled.get('sourceLockSha256') ==
            content.receipt.get('sourceLockSha256'), 'Updater source selection differs')
    expected = {}
    selected = _stock_selection(content)
    for database in updater.DATABASES:
        expected[database] = {}
        for row in content.manifest['databases'][database]['updateOrder']:
            path = row['path']; packaged._path(path)
            pin = _pin({key: content.manifest['files'][path][key] for key in ('bytes', 'sha256')})
            archive_pin = content.receipt['archiveFiles']['source/' + path]
            require(pin == {key: archive_pin[key] for key in ('bytes', 'sha256')}, 'Updater SQL payload binding differs')
            digest, _ = _hash(content.source / path, pin, progress=progress, cancelled=cancelled)
            name = Path(path).name
            require(name not in expected[database] and row['state'] in ('RELEASED', 'ARCHIVED', 'PENDING', 'CUSTOM', 'MODULE'),
                    'Duplicate or invalid selected updater SQL')
            if stock_update_selected(database, row):
                expected[database][name] = (digest, row['state'])
    binding = dict(contentReceipt=copy.deepcopy(content.identities['receipt']),
        source=copy.deepcopy(content.manifest['source']), sourceLockSha256=content.receipt['sourceLockSha256'],
        compiledModules=metadata['compiled-modules'], contentManifest=metadata['content-manifest'],
        originalBuild=_pin(content.compiled.get('serverBuild')),
        contentProfile=CONTENT_PROFILE, sqlSelectionPolicy=STOCK_SQL_POLICY,
        selectedSourcePathsSha256=hashlib.sha256(updater.canonical_identity(selected)).hexdigest(),
        selectedUpdatesSha256=hashlib.sha256(updater.canonical_identity(expected)).hexdigest())
    return expected, binding


def prepare(content, executable, selected_program_identity, template, template_identity, mysql,
            *, original_build_identity, progress=None, cancelled=None):
    """Bind caller-verified engine pins to real verified content, without SQL."""
    expected, binding = _content_inputs(content, progress=progress, cancelled=cancelled)
    selected_program_identity, template_identity = _pin(selected_program_identity), _pin(template_identity)
    original_build_identity = _pin(original_build_identity)
    require(original_build_identity == binding['originalBuild'],
            'Updater original build differs from the original compiled selection')
    executable, template, mysql = (Path(path) for path in (executable, template, mysql))
    require(all(path.is_absolute() for path in (executable, template, mysql)) and
            selected_program_identity['bytes'] > 0 and template_identity['bytes'] <= 2 * 1024**2,
            'Absolute bounded updater/template/client paths required')
    executable, template, mysql = (db.private_path(path) for path in (executable, template, mysql))
    require(mysql.is_file() and os.access(executable, os.X_OK), 'Selected updater or MySQL client unavailable')
    _hash(executable, selected_program_identity, progress=progress, cancelled=cancelled)
    _hash(template, template_identity, progress=progress, cancelled=cancelled)
    binding.update(selectedProgram=selected_program_identity, template=template_identity,
                   executablePath=str(executable), templatePath=str(template), mysqlPath=str(mysql))
    return Preparation(content, executable, selected_program_identity, template, template_identity,
                       mysql, original_build_identity, expected, binding)


def _service(verify_service):
    if verify_service is not None:
        require(verify_service() is not False, 'Owned database service identity changed')


def _instance(connection, state, version):
    bootstrap = db.read_receipt(state / 'database-bootstrap.json', version)
    require(bootstrap['datadir'] == str(state / 'database') and db.datadir_uuid(state / 'database') == bootstrap['uuid'],
            'Updater persistent database identity changed')
    db.check_receipt(bootstrap, db.identity(connection, version)); db.check_listener(connection, None)
    require(connection.query('SELECT CURRENT_USER()') in (['esteria@127.0.0.1'], ['esteria@localhost']),
            'Unexpected updater database account')
    return bootstrap


def _credentials(state):
    """Validate/hash existing secrets without chmod, creation or replacement."""
    result = {}
    for name in ('database-secret', 'database-root-secret'):
        path = state / 'accounts' / name
        with updater.plain_file(path) as stream:
            info = os.fstat(stream.fileno())
            require(info.st_uid == os.geteuid() and info.st_nlink == 1 and not info.st_mode & 0o077 and
                    info.st_size <= 66, 'Updater credential must be an owned unshared private file')
            raw = stream.read(67)
        require(len(raw) == info.st_size and re.fullmatch(b'[a-f0-9]{64}', raw.strip()),
                'Existing updater database credential is invalid')
        result[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return result


def _untouched(connection):
    require(connection.query('SELECT COUNT(*) FROM `acore_auth`.`account`') == ['0'] and
            connection.query('SELECT COUNT(*) FROM `acore_characters`.`characters`') == ['0'],
            'Existing accounts or characters preserved; updater adoption refused')
    snapshot = {}
    for name in baseline.DB_ORDER:
        tables = connection.query('SHOW TABLES FROM `acore_' + name + '`')
        if name == 'playerbots':
            require(not tables, 'Unregistered playerbots database must remain empty')
        else:
            require('updates' in tables and 'updates_include' in tables, 'Completed source baseline ledgers required')
        rows = [] if name == 'playerbots' else connection.query(
            'SELECT name,hash,state FROM `acore_' + name + '`.`updates` ORDER BY name')
        snapshot[name] = dict(tablesSha256=hashlib.sha256(updater.canonical_identity(tables)).hexdigest(),
                              ledgerSha256=hashlib.sha256(updater.canonical_identity(rows)).hexdigest())
    return snapshot


def _receipt(binding, bootstrap, operation, executed, snapshot, stock_sql):
    return dict(formatVersion=1, scope=SCOPE, operation=operation, qualificationSucceeded=True,
        mysqlUuid=bootstrap['uuid'], mysqlVersion=bootstrap['version'],
        contentReceipt=binding['contentReceipt'], sourceLockSha256=binding['sourceLockSha256'],
        source=copy.deepcopy(binding['source']), compiledModules=binding['compiledModules'],
        contentManifest=binding['contentManifest'], selectedUpdatesSha256=binding['selectedUpdatesSha256'],
        contentProfile=binding['contentProfile'], sqlSelectionPolicy=binding['sqlSelectionPolicy'],
        selectedSourcePathsSha256=binding['selectedSourcePathsSha256'],
        stockWorldSql=stock_sql,
        originalBuild=binding['originalBuild'], selectedProgram=binding['selectedProgram'],
        template=binding['template'], compiledUpdaterExecuted=executed, compiledUpdaterCompleted=True,
        sourceLedgersVerified=True, credentialsAndAccountJournalPreserved=True, baselineJournalUnchanged=True,
        databaseSnapshots=snapshot, gameSchemasQualified=False, existingSaveUpgradesQualified=False,
        playerbotsRuntimeQualified=False, authserverExecuted=False, worldserverExecuted=False,
        androidRuntimeQualified=False, gameplayQualified=False)


def _verify_completed(content, connection, state, version, expected_uuid, verify_service,
                      content_binding, expected, *, cancelled=None):
    checkpoint(cancelled); _service(verify_service)
    require(connection.query("SELECT IS_USED_LOCK('esteria-local-bootstrap') = CONNECTION_ID()") == ['1'],
            'Caller must own the bootstrap SQL lock during completed updater verification')
    bootstrap = _instance(connection, state, version)
    require(bootstrap['uuid'] == expected_uuid, 'Completed updater service UUID differs from caller ownership')
    path, baseline_path = state / JOURNAL, state / schema.JOURNAL
    journal, baseline_journal = schema.private_journal(path), schema.private_journal(baseline_path)
    journal_identity, baseline_identity = baseline.file_identity(path), baseline.file_identity(baseline_path)
    credentials, account = _credentials(state), schema.account_identity(state)
    binding = journal.get('binding')
    require(type(journal.get('formatVersion')) is int and journal['formatVersion'] == 1 and journal.get('scope') == SCOPE and
            journal.get('phase') == 'complete' and journal.get('compiledUpdaterExecuted') is True and
            type(journal.get('run', {}).get('exitCode')) is int and journal['run']['exitCode'] == 0 and isinstance(binding, dict),
            'Private completed compiled updater journal required')
    require(all(binding.get(key) == value for key, value in content_binding.items() if key not in
                ('selectedProgram', 'template', 'executablePath', 'templatePath', 'mysqlPath')) and
            binding.get('credentials') == credentials and binding.get('baselineJournal') == baseline_identity and
            binding.get('mysqlUuid') == expected_uuid and binding.get('mysqlVersion') == version and
            binding.get('datadir') == bootstrap['datadir'], 'Completed updater source or private binding changed')
    require(_pin(binding.get('selectedProgram'))['bytes'] > 0 and
            0 < _pin(binding.get('template'))['bytes'] <= 2 * 1024**2, 'Invalid historical updater artifact sizes')
    require(all(isinstance(binding.get(key), str) and Path(binding[key]).is_absolute()
                for key in ('executablePath', 'templatePath', 'mysqlPath')), 'Invalid historical updater artifact paths')
    baseline_binding = baseline_journal.get('binding', {})
    require(type(baseline_journal.get('formatVersion')) is int and baseline_journal['formatVersion'] == 1 and
            baseline_journal.get('phase') == 'baseline-complete' and baseline_journal.get('pending') is None and
            baseline_journal.get('completed') == baseline_binding.get('paths') and
            all(baseline_binding.get(key) == value for key, value in dict(mysqlUuid=expected_uuid,
                mysqlVersion=version, datadir=bootstrap['datadir'], credentials=credentials,
                contentReceipt=content_binding['contentReceipt'], sourceLockSha256=content_binding['sourceLockSha256'],
                compiledModules=content.receipt['compiledModules']).items()), 'Completed source baseline binding changed')
    checkpoint(cancelled)
    snapshot = updater.core_schema_snapshot(connection, expected)
    require(snapshot == journal.get('snapshot'), 'Completed updater live ledger or table set changed')
    stock_sql = stock_world_sql_snapshot(connection)
    require(stock_sql == journal.get('stockWorldSql'), 'Completed stock SQL closure changed')
    playerbots = None
    if connection.query('SHOW TABLES FROM `acore_playerbots`') or os.path.lexists(state / '.server-playerbots-schema.json'):
        # A source-owned fourth pool has its own durable execution journal. The
        # default dbimport primitive still requires it empty; only a completed
        # private playerbots journal can authorize later core read-only checks.
        try:
            from . import server_playerbots_setup
        except ImportError:
            import server_playerbots_setup
        playerbots = server_playerbots_setup._verify_completed(content, connection, state, version,
            expected_uuid=expected_uuid, verify_service=verify_service,
            core_journal_identity=journal_identity, core_snapshot=snapshot, cancelled=cancelled)
    checkpoint(cancelled); _service(verify_service)
    require(_instance(connection, state, version)['uuid'] == expected_uuid and
            _credentials(state) == credentials and schema.account_identity(state) == account and
            baseline.file_identity(path) == journal_identity and baseline.file_identity(baseline_path) == baseline_identity,
            'Completed updater private context changed during verification')
    result = dict(_receipt(binding, bootstrap, 'verified-completed-updater', False, snapshot, stock_sql),
                  journalIdentity=journal_identity, baselineJournalIdentity=baseline_identity)
    if playerbots is not None:
        result['playerbots'] = playerbots
    return result


def verify_completed_update(content, connection, state, version, *, expected_uuid, verify_service,
                            progress=None, cancelled=None):
    """Read-only readiness check inside the caller's retained locks and lease.

    The caller holds its state/config/service lease and bootstrap SQL named lock.
    This function takes/releases no locks, rewrites no journal, and hashes no
    historical executable/template. It verifies current content and source SQL,
    private completed bindings and live source ledgers before caller mutations.
    """
    require(callable(verify_service), 'Explicit retained service verifier required')
    state = Path(state)
    require(state.is_absolute(), 'Absolute owned updater state required')
    state = db.private_path(state)
    expected, binding = _content_inputs(content, progress=progress, cancelled=cancelled)
    return _verify_completed(content, connection, state, version, expected_uuid,
                             verify_service, binding, expected, cancelled=cancelled)


def apply(plan, connection, state, version, *, progress=None, cancelled=None, verify_service=None, state_lease=None):
    """Execute once after a real completed baseline; repeats validate without replay.

    Cancellation is honored before durable intent. After intent, the selected
    updater must finish within its shared timeout; cancellation never implies a
    mid-SQL rollback. Callers check cancellation again before any later stage.
    ``verify_service`` may raise or return False if its retained owner changed.
    An optional real ``state_lease`` is forwarded through completed-baseline
    validation and reused for this updater's state scope without relocking.
    """
    require(isinstance(plan, Preparation), 'Prepared exact updater selection required')
    checkpoint(cancelled); state = Path(state)
    require(state.is_absolute(), 'Absolute owned updater state required')
    state = db.private_path(state)
    # A missing/partial baseline is never converted into a fresh initialization.
    baseline_path = state / schema.JOURNAL
    previous = schema.private_journal(baseline_path)
    require(previous.get('phase') == 'baseline-complete', 'Completed source baseline journal required before updater')
    baseline_identity = baseline.file_identity(baseline_path)
    def no_baseline_sql(*_args):
        raise db.BootstrapError('Updater must never initialize or replay a source baseline')
    _service(verify_service)
    baseline_result = schema.initialize(plan.content, connection, state, version, no_baseline_sql,
                                        cancelled=cancelled, state_lease=state_lease)
    require(baseline_result.get('operation') == 'already-prepared' and
            baseline.file_identity(baseline_path) == baseline_identity, 'Completed source baseline changed')
    _service(verify_service)
    refreshed = prepare(plan.content, plan.executable, plan.selected_program_identity, plan.template,
        plan.template_identity, plan.mysql, original_build_identity=plan.original_build_identity,
        progress=progress, cancelled=cancelled)
    require(refreshed.binding == plan.binding and refreshed.expected == plan.expected, 'Prepared updater selection changed')
    with db.state_scope(state, state_lease):
        checkpoint(cancelled)
        require(baseline.file_identity(baseline_path) == baseline_identity, 'Completed baseline journal changed before updater lock')
        bootstrap = _instance(connection, state, version)
        require(connection.query("SELECT GET_LOCK('esteria-local-bootstrap',0)") == ['1'], 'Another operation owns updater instance')
        try:
            credentials, account = _credentials(state), schema.account_identity(state)
            binding = dict(plan.binding, baselineJournal=baseline_identity, credentials=credentials,
                mysqlUuid=bootstrap['uuid'], mysqlVersion=version, datadir=bootstrap['datadir'])
            path = state / JOURNAL
            if os.path.lexists(path):
                journal = schema.private_journal(path)
                require(type(journal.get('formatVersion')) is int and journal['formatVersion'] == 1 and
                        journal.get('scope') == SCOPE and journal.get('binding') == binding,
                        'Updater source, engine, credentials or instance changed; upgrade/adoption refused')
                if journal.get('phase') == 'complete':
                    return _verify_completed(plan.content, connection, state, version, bootstrap['uuid'],
                        verify_service, plan.binding, plan.expected, cancelled=cancelled)
                require(journal.get('phase') == 'prepared' and journal.get('compiledUpdaterExecuted') is False,
                        'Interrupted or failed updater preserved; replay refused')
                require(account is None and _untouched(connection) == journal.get('before'),
                        'Prepared updater state changed; adoption refused')
            else:
                require(account is None, 'Existing account journal preserved; fresh updater adoption refused')
                before = _untouched(connection)
                checkpoint(cancelled)
                journal = dict(formatVersion=1, scope=SCOPE, binding=binding, phase='prepared',
                               compiledUpdaterExecuted=False, before=before)
                db.atomic_json(path, journal)
            checkpoint(cancelled)
            run = db.private_path(state / 'run'); updater.config.plain_directory(run)
            operation = run / ('updater-' + secrets.token_hex(16)); operation.mkdir(mode=0o700)
            (operation / 'run').mkdir(mode=0o700); (operation / 'logs').mkdir(mode=0o700)
            _hash(plan.template, plan.template_identity, cancelled=cancelled)
            password = db.read_secret(state / 'accounts/database-secret')
            sql_source, sql_inventory = _project_stock_sql(plan, operation, cancelled=cancelled)
            configuration = updater.render_importer(plan.template, sql_source, operation, plan.mysql, password)
            configuration_pin = baseline.file_identity(configuration)
            _hash(plan.template, plan.template_identity, cancelled=cancelled)
            _hash(plan.executable, plan.selected_program_identity, cancelled=cancelled)
            _service(verify_service); _instance(connection, state, version)
            require(_credentials(state) == credentials and schema.account_identity(state) == account and
                    baseline.file_identity(baseline_path) == baseline_identity, 'Private updater binding changed before execution')
            checkpoint(cancelled)
            journal.update(phase='in-flight', invocation=str(operation))
            db.atomic_json(path, journal)  # Must be durable BEFORE Popen, never in on_started.
            started = False
            def on_started():
                nonlocal started
                started = True
            # Observers may request cancellation here; this committed unit still
            # executes. Observer exceptions cannot strand an unlaunched intent.
            if progress is not None:
                try: progress(dict(phase='compiled-updater-intent-committed'))
                except Exception: pass
            try:
                # Recheck after observers and durable intent, directly before
                # process creation. This committed unit no longer polls cancel.
                _service(verify_service); _instance(connection, state, version)
                require(_credentials(state) == credentials and schema.account_identity(state) == account and
                        baseline.file_identity(baseline_path) == baseline_identity,
                        'Private updater binding changed immediately before execution')
                _hash(plan.template, plan.template_identity)
                _hash(configuration, configuration_pin)
                _hash(plan.executable, plan.selected_program_identity)
                _verify_stock_sql(sql_source, sql_inventory)
                execution = updater.run_importer(plan.executable, configuration,
                    operation / 'logs/updater-private.log', on_started=on_started)
                require(started, 'Updater did not establish actual process creation')
                _instance(connection, state, version); _service(verify_service)
                snapshot = updater.schema_snapshot(connection, plan.expected)
                stock_sql = stock_world_sql_snapshot(connection)
                require(_credentials(state) == credentials and schema.account_identity(state) == account and
                        baseline.file_identity(baseline_path) == baseline_identity, 'Private identities changed during updater')
                journal.update(phase='complete', compiledUpdaterExecuted=True, run=execution, snapshot=snapshot,
                               stockWorldSql=stock_sql)
                db.atomic_json(path, journal)
                return _receipt(plan.binding, bootstrap, 'executed-compiled-updater', True, snapshot, stock_sql)
            except BaseException:
                journal.update(phase='failed', compiledUpdaterExecuted=started)
                db.atomic_json(path, journal)
                raise
        finally:
            require(connection.query("SELECT RELEASE_LOCK('esteria-local-bootstrap')") == ['1'],
                    'Updater operation lock release failed; state preserved')
