#!/usr/bin/env python3
"""Fixed Android guest entry point for the existing private MySQL bootstrap.

No schemas or game servers are started here. Keep /work/state stable across
application/runtime updates: the bootstrap receipts bind its absolute path.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
if __package__:
    from . import mysql_bootstrap as bootstrap
else:
    import mysql_bootstrap as bootstrap


def failure_diagnostic(error: Exception) -> str:
    """Emit code locations and numeric errno only, never exception text/locals.

    Filesystem and process errors on Android need an actionable failure site.
    SQL failures can embed credentials, so standard tracebacks are unsuitable.
    """
    kind = type(error).__name__
    if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', kind):
        kind = 'Exception'
    fields = [kind]
    if isinstance(error, OSError) and type(error.errno) is int and 0 <= error.errno <= 4095:
        fields.append('errno=' + str(error.errno))
    frames = []; current = error.__traceback__; visited = 0
    while current is not None and visited < 64:
        visited += 1
        code = current.tb_frame.f_code
        module = current.tb_frame.f_globals.get('__name__')
        # Only these two shipped modules; a basename from an arbitrary path is
        # insufficient to authorize logging that frame's function name.
        if module in ('__main__', __name__, bootstrap.__name__) and code.co_filename in (__file__, bootstrap.__file__):
            function = code.co_name
            if re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', function):
                frames.append(function + ':' + str(current.tb_lineno))
        current = current.tb_next
    if frames:
        fields.append('helperFrames=' + ','.join(frames[-8:]))
    return '; '.join(fields)


def setup(state: Path, mysql: Path, mysqld: Path, version: str) -> dict:
    bootstrap.exact_version(version)
    state = bootstrap.private_path(state)
    # The renderer uses this same credential. Generate it once, under the same
    # bootstrap lock, before a fresh initialization; never reset an existing one.
    with bootstrap.state_lock(state):
        existing = any((state / name).exists() for name in (
            'database-bootstrap.json', '.database-initialization.json',
            'database-initializing', '.database-initializing',
            'accounts/database-root-secret'))
        database = bootstrap.private_path(state / 'database')
        existing = existing or (database.exists() and
                                (not database.is_dir() or any(database.iterdir())))
        bootstrap.read_secret(state / 'accounts/database-secret', create=not existing)
        if (state / 'database-bootstrap.json').exists():
            bootstrap.read_secret(state / 'accounts/database-root-secret')
        result = bootstrap.initialize(mysqld, mysql, state, version)
        receipt = bootstrap.read_receipt(state / 'database-bootstrap.json', version)
        if (receipt['uuid'] != result['uuid'] or
                receipt['datadir'] != str(state / 'database') or
                bootstrap.datadir_uuid(state / 'database') != receipt['uuid']):
            raise bootstrap.BootstrapError('Database setup receipt disagrees with persistent storage')
        operation = result['operation']
        if operation not in ('initialized', 'already-initialized', 'recovered-promotion'):
            raise bootstrap.BootstrapError('Unexpected database setup operation')
        # A receipt is deliberately not a claim of live SQL readiness. Even the
        # successful first bootstrap has stopped its private temporary server.
        return {'formatVersion': 1, 'scope': 'database-prepared-no-readiness-claim',
                'operation': operation, 'version': receipt['version'],
                'uuid': receipt['uuid'], 'datadir': receipt['datadir'],
                'databases': receipt['databases'], 'persistentServiceStarted': False, 'liveServiceStateVerified': False,
                'liveSqlAuthenticated': False,
                'bootstrapPopulatedApplicationSchemas': receipt['application_schemas_populated']}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--operation-id', required=True)
    args = parser.parse_args()
    try:
        if not re.fullmatch(r'[0-9a-f]{32}', args.operation_id):
            raise bootstrap.BootstrapError('Invalid setup operation identity')
        output = bootstrap.private_path(Path('/work/setup-results') / (args.operation_id + '.json'))
        if output.exists():
            raise bootstrap.BootstrapError('Setup operation result already exists')
        result = setup(Path('/work/state'), Path('/usr/bin/mysql'),
                       Path('/usr/sbin/mysqld'), args.expected_version)
        bootstrap.atomic_json(output, result)
        print('Esteria database setup completed; live SQL readiness was not checked')
        return 0
    except Exception as error:
        # SQL errors can contain credentials or query fragments. Keep the
        # exception text out of process logs; owned engine logs remain private.
        print('Database setup failed (' + failure_diagnostic(error) +
              '); persistent state was preserved for recovery', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
