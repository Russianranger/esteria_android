#!/usr/bin/env python3
"""Read-only real SQL persistence comparison for the Java coordinator gate.

Run only inside the production PRoot namespace. Raw account/credential/SQL rows
never enter stdout or a public artifact. This executes no updater or bot AI.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def run(args):
    if not re.fullmatch('[a-f0-9]{64}', args.helper_generation) or not re.fullmatch('[a-f0-9]{32}', args.operation):
        raise ValueError('Invalid qualification helper or operation identity')
    helper = Path('/work/installation-helpers') / args.helper_generation
    if helper.is_symlink() or helper.resolve() != helper:
        raise ValueError('Plain production helper generation required')
    sys.path.insert(0, str(helper))
    import mysql_bootstrap as db
    import server_playerbots_setup as bots
    state = Path('/work/state')
    bootstrap = db.read_receipt(state / 'database-bootstrap.json', args.version)
    if bootstrap['uuid'] != args.uuid:
        raise ValueError('Persistent bootstrap UUID changed')
    password = db.read_secret(state / 'accounts/database-secret')
    with db.state_lock(state), db.option_file(state, 'esteria', password) as options, db.Mysql(Path('/usr/bin/mysql'), options) as connection:
        if connection.query('SELECT @@server_uuid') != [args.uuid]:
            raise ValueError('Live SQL UUID changed')
        bots._owned_account(connection, state, bootstrap, fresh=True)
        private = bots.preserved_core(connection)
        rows = connection.query('SELECT name,hash,state FROM `acore_playerbots`.`updates` ORDER BY name')
        expected = {}
        for row in rows:
            fields = row.split('\t')
            if len(fields) != 3 or fields[0] in expected:
                raise ValueError('Invalid playerbots ledger')
            expected[fields[0]] = (fields[1].lower(), fields[2])
        snapshot = bots.snapshot(connection, expected)
        journal = json.loads((state / bots.JOURNAL).read_bytes())
        if journal.get('phase') != 'complete' or journal.get('snapshot') != snapshot:
            raise ValueError('Persistent playerbots tables or ledger changed')
        private['playerbots'] = snapshot
        # Comparison stays private. The public Java receipt only states whether
        # the two independently observed actual SQL snapshots were identical.
        result = dict(formatVersion=1, scope='private-native-java-installation-sql-comparison',
            mysqlUuid=args.uuid, coreAndAccountRowsSha256=hashlib.sha256(json.dumps(private,
                sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            playerbotsTableCount=snapshot['tableCount'], playerbotsUpdateCount=snapshot['updateCount'],
            ownedAccountAndRealmVerified=True, playerbotsJournalMatchesLiveSql=True)
        target = Path('/work/qualification-results') / (args.operation + '.json')
        if target.exists() or target.is_symlink():
            raise ValueError('Existing SQL comparison preserved')
        db.atomic_json(target, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('helper-generation', 'operation', 'version', 'uuid'):
        parser.add_argument('--' + name, required=True)
    try:
        run(parser.parse_args())
        print('Actual read-only SQL account, realm and four-schema persistence observation complete')
        return 0
    except Exception as error:
        print('Java installation SQL comparison failed (' + type(error).__name__ + '); private diagnostics retained', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
