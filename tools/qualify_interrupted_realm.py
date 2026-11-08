"""Native ARM64 regression for starting auth after the genuine world loader exits early."""
import os
import time
from pathlib import Path

from runtime import mysql_bootstrap as db, provision_local_realm as realm, server_session as session
from runtime import server_session_process as processes
from tools import observe_stock_world_startup as world, qualify_packaged_grunt as grunt
from tools import qualify_packaged_server_auth as stock

OUT = Path('/evidence/realm-recovery.json')
FLAG = 'SELECT flag FROM acore_auth.realmlist WHERE id=1'
require = stock.require


def preserved(sql, state):
    """Keep exact protected rows and private receipt identities inside this disposable process."""
    realm_rows = sql.query('SELECT id,HEX(name),address,localAddress,localSubnetMask,port,icon,timezone,'
                           'allowedSecurityLevel,population,gamebuild FROM acore_auth.realmlist ORDER BY id')
    account_columns = ','.join('HEX(`' + c[0] + '`)' for c in stock.account.COLUMNS['account'])
    private_accounts = sql.query('SELECT ' + account_columns + ' FROM acore_auth.account ORDER BY id')
    tables = ('acore_auth.account_access', 'acore_auth.rbac_account_permissions',
              'acore_auth.realmcharacters', 'acore_characters.characters')
    return dict(private=stock.sql.private_identities(state), realm=realm_rows, accounts=private_accounts,
                tables=[sql.query('SELECT * FROM ' + t) for t in tables],
                ledgers=[sql.query('SELECT name,hash,state FROM acore_' + name + '.updates ORDER BY name')
                         for name in ('auth', 'characters', 'world', 'playerbots')])


def expect_rejected_auth(state, program, configuration):
    path = state / 'logs' / 'realm-restart-negative.log'
    auth = processes.ServerChild('authserver', program, configuration / 'authserver.conf',
                                 state / 'run/authserver', path)
    exit_code = None
    try:
        auth.start()
        exit_code = auth.group.wait(90)
    finally:
        try:
            auth.stop(auth_timeout=30)
        except ValueError:
            if not (exit_code == 1 and auth.closed and auth.group.closed and not auth.group.forced):
                raise
    require(auth.process.returncode == 1 and auth.error is None and auth.observed == auth.stored,
            'original auth exit or diagnostic log differed')
    require(path.stat().st_size <= processes.LOG_LIMIT and b'No valid realms specified' in path.read_bytes(),
            'original no-eligible-realm diagnosis was not observed')


def probe(package, state, service, version, uuid, _record):
    selected, auth_pin = stock.selections(package)
    program = package / 'server-programs/bin/authserver'
    require(stock.identity(program) == auth_pin, 'different authserver program')
    config = state / 'config/generations' / stock.document(state / 'server-setup-complete.json')['configGeneration']
    require(config.resolve(strict=True) == config, 'canonical source configuration required')
    result = dict(scope='original incomplete-world restart and owned one-realm recovery on disposable stock SQL',
                  environment='native Linux ARM64 without a network interface beyond loopback',
                  authserverSha256=auth_pin['sha256'], serverSessionHelper=stock.identity(Path(session.__file__)),
                  gameAssetsUsed=False, graphicalLogin=False, gameplayQualified=False,
                  sourceBoundStockPackage=stock.document(package / 'bindings.json'), stages=[])
    started = time.monotonic()

    def record(phase, **details):
        result['stages'].append(dict(phase=phase, elapsedSeconds=round(time.monotonic()-started, 3), **details))
        db.atomic_json(OUT, result)

    require(result['serverSessionHelper'] == dict(bytes=33388, sha256='5ac999c21443a483fc4070011aad4ea53cd0f37603a3a52e6e51a977223385cc'),
            'native observer must call the exact reviewed production helper')
    record('verified-compiled-authserver-and-original-four-schema-reopen')
    mysql = Path('/usr/bin/mysql')
    secret = db.read_secret(state / 'accounts/database-secret')
    with db.option_file(state, 'esteria', secret) as opts, db.Mysql(mysql, opts) as sql:
        verify = lambda: service.verify(sql, uuid)
        require(verify() and sql.query(realm.ROW_SQL) == [realm.EXPECTED_ROW], 'different owned source instance')
        result['protectedJournalCount'] = len(stock.sql.private_identities(state))
        for attempt in (1, 2):
            # Run the real unmodified selected worldserver twice. It stops because there are no game maps.
            if attempt == 2:
                # Preserve this disposable operation's previously observed diagnostics under new names.
                for name in ('world-bootstrap-stdout.log', 'Server-before-world-observation.log'):
                    previous = state / 'logs' / name
                    target = previous.with_name('first-' + name)
                    require(previous.is_file() and not previous.is_symlink() and not os.path.lexists(target),
                            'previous world observation changed')
                    previous.rename(target)
            output = Path('/evidence') / f'world-restart-{attempt}.json'
            require(world.observe(package, selected[0][1], state, service, uuid, config, output),
                    'selected real worldserver did not reach the expected empty-map boundary')
            observed = stock.document(output)
            require(verify() and sql.query(FLAG) == ['1'] and observed['nativeExit'] == 1
                    and observed['nativeProcessReaped'] and observed['startingAreaDataRequired'],
                    'original world did not leave selected realm in startup state')
            record('original-world-exited-at-missing-map', attempt=attempt, flag=1,
                   nativeSeconds=observed['nativeElapsedSeconds'], originalWorldReaped=True)
            if attempt == 1:
                expect_rejected_auth(state, program, config)
                require(verify() and sql.query(FLAG) == ['3'], 'original auth did not leave the excluded flag')
                record('original-auth-exited-no-eligible-realms', flag=3, originalExit=1, originalAuthReaped=True)

            before = preserved(sql, state)
            before_flag = sql.query(FLAG)
            with db.state_lock(state) as lease, realm.config_lock(state):
                saw_uncommitted_fix = []
                def cancel_after_update():
                    if sql.query(FLAG) == ['2']:
                        saw_uncommitted_fix.append(True)
                        return True
                    return False
                for cancelled in (lambda: True, cancel_after_update):
                    try:
                        session.recover_interrupted_realm(sql, state, uuid, verify, state_lease=lease, cancelled=cancelled)
                    except ValueError as error:
                        require(str(error) == 'Owned server startup cancelled', 'unexpected cancellation boundary')
                    else:
                        raise ValueError('production cancellation did not stop recovery')
                require(saw_uncommitted_fix == [True] and sql.query(FLAG) == before_flag and preserved(sql, state) == before,
                        'cancelled operation mutated the realm, private state, account or ledgers')
            with db.state_lock(state) as lease, realm.config_lock(state):
                require(session.recover_interrupted_realm(sql, state, uuid, verify, state_lease=lease) is True
                        and verify() and sql.query(FLAG) == ['2'] and preserved(sql, state) == before,
                        'recovery failed or mutated unrelated rows, source or credentials')
            with db.state_lock(state) as lease, realm.config_lock(state):
                require(session.recover_interrupted_realm(sql, state, uuid, verify, state_lease=lease) is False
                        and verify() and sql.query(FLAG) == ['2'] and preserved(sql, state) == before,
                        'later clean reentry repeated recovery or changed protected rows')
                record('cancel-and-reenter-original-owned-database', attempt=attempt, beforeFlag=int(before_flag[0]),
                       preMutationCancelObserved=True, rolledBackAfterObservedUncommittedWrite=True,
                       recoveredFlag=2, unchangedReentryWrote=False, preservedCredsAccountsRealmFieldsAndFourLedgers=True)

                # Try an unrelated flag and a combined unknown transition on the disposable row inside an
                # explicit rollback. Neither branch may normalize or discard independently configured flags.
                for foreign in (4, 5):
                    sql.query('START TRANSACTION')
                    try:
                        sql.query('UPDATE acore_auth.realmlist SET flag=' + str(foreign) + ' WHERE id=1')
                        try:
                            changed = session.recover_interrupted_realm(sql, state, uuid, verify, state_lease=lease)
                        except ValueError:
                            require(foreign == 5, 'unexpected rejection for an unrelated offline bit')
                        else:
                            require(changed is False and foreign == 4, 'foreign realm flags were accepted or overwritten')
                        require(sql.query(FLAG) == [str(foreign)], 'foreign mask was discarded')
                    finally:
                        sql.query('ROLLBACK')
                    require(sql.query(FLAG) == ['2'] and preserved(sql, state) == before,
                            'private negative case escaped its transaction')
                record('unrelated-flag-masks-preserved', attempt=attempt, masks=[4, 5])

                # The fixture already issued a standalone source auth probe on attempt 1.
                # Keep original logs and forward the contract's exact two sequential PE signals.
                def client_probe(state, connection, intent, child, _number):
                    return grunt.server_probe(state, connection, intent, child, attempt)
                confirmed = stock.protocol_probe(state, mysql, version, program, auth_pin, config,
                                                  client_probe=client_probe, attempt=10+attempt)
                require(verify() and confirmed['clientServerSessionKeyMatched'] and confirmed['nonceMatched']
                        and confirmed['productionOwnedAuthListenerVerified'] and confirmed['fourLedgersPreserved'],
                        'actual reconstructed Grunt authentication was not established')
                record('genuine-reconstructed-grunt-logged-in', attempt=attempt, exitAndServerStopClean=True,
                       executableSha256=confirmed['executableSha256'], wineArchiveSha256=confirmed['wineArchiveSha256'],
                       keyAndNonceMatch=True, returnedRealmCount=confirmed['realmCount'])


def main():
    os.umask(0o077)
    # The standard fixture requires an entirely empty private /work and installs its own stock SQL.
    # Its detailed fixture reports include a UUID and remain private.
    work = Path('/work')
    upstream = Path('/private-evidence/stock-auth.json')
    try:
        stock.run(Path('/package'), work, upstream, world_probe=probe)
    except Exception as error:
        result = stock.document(OUT) if OUT.is_file() else {}
        result.update(failureClass=type(error).__name__, **stock.sql.safe_failure_context(error, work / 'state'))
        db.atomic_json(OUT, result)
        raise
    final = stock.document(upstream)['stages'][-1]
    require(final['stage'] == 'same-uuid-reopened-and-cleanly-stopped', 'source-owned SQL closure was not confirmed')
    result = stock.document(OUT)
    result['finalDatabaseCommandStopVerified'] = True
    db.atomic_json(OUT, result)


if __name__ == '__main__':
    main()
