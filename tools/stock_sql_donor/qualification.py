"""Disposable stock SQL provenance and same-instance verification in an offline ARM64 rootfs."""
import json
from pathlib import Path
import re
import socket
import time

from runtime import android_database_setup, mysql_bootstrap as db, provision_local_realm as realm
from runtime import server_content, server_playerbots_setup as bots
from tools import qualify_packaged_server_auth as auth

SOURCE = '075ed711bd8be7aaeac8bdfca2be8c607afb8f4b'
APK = '60a90c58dfc211c53928853dbbebd04929668da69d46d4c0a027c143f6857eb6'
TAG = 'non-custom-v0.1.0-non-custom.18'
PINS = {'server-runtime':'21a9e8020aac3c780114e2b3e368a643a6e830d35b6406ed99135dec9ba03ce5',
        'server-programs':'963a23c1390440260b85ffe164b2d7508c56b005b315dce8a919ae443a46d1bf',
        'server-content':'0f41b2deea5344fcea4cbc70bbddf0bab1dfda1cd0346e23e92592aac63056e6'}
PACKAGE = {'tag':TAG,'apkSha256':APK,'archives':PINS}
NAMESPACE = {'work':'/work','package':'/package','source':'/package/server-content/source','data':'/esteria-data/data'}


def require(valid):
    if not valid:
        raise ValueError('Disposable donor qualification failed')


def verify():
    state=Path('/work/state')
    sessions=Path('/work/mysql-sessions')
    package=Path('/package')
    evidence=Path('/evidence')
    require([n for _,n in socket.if_nameindex()]==['lo'])
    require(auth.document(package/'bindings.json')==PACKAGE)
    previous=auth.document(evidence/'stock-auth.json')
    require(all(previous[k]==v for k,v in PACKAGE.items()))
    labels=[r['stage'] for r in previous['stages']]
    ordered=['bootstrap','authenticated-database','enter-core','enter-playerbots','four-schemas-verified',
             'auth-srp-12340-loopback-session-key-verified','sql-completion-bound-to-clean-stop',
             'separate-incomplete-world-startup-observation','same-uuid-reopened-and-cleanly-stopped']
    require(all(labels.count(k)==1 for k in ordered) and sorted(labels.index(k) for k in ordered)==[labels.index(k) for k in ordered])
    require(auth.document(evidence/'world-startup.json')['phase']=='stock-starting-area-map-gate')
    uuid=previous['stages'][-1]['uuid']
    version=auth.document(Path('/etc/esteria-server-runtime.json'))['expectedMysqlSqlVersion']
    require(re.fullmatch('[0-9a-f-]{36}',uuid) and previous['stages'][labels.index('authenticated-database')]['uuid']==uuid)
    mysql,mysqld=Path('/usr/bin/mysql'),Path('/usr/sbin/mysqld')
    require(android_database_setup.setup(state,mysql,mysqld,version)['operation']=='already-initialized')
    receipt=db.read_receipt(state/'database-bootstrap.json',version)
    require(receipt['uuid']==uuid==db.datadir_uuid(state/'database') and receipt['datadir']==str(state/'database'))
    phases,_=auth.selections(package)
    core=phases[0][1]
    helper=phases[-1][1]['playerbotsHelper']
    pins=dict(helperExecutable=helper['executable'],helperBuildReceipt=helper['buildReceipt'],helperNativeReceipt=helper['nativeReceipt'])
    completion=auth.document(state/'server-setup-complete.json')
    first=completion['serviceOperationId']
    require(re.fullmatch('[0-9a-f]{32}',first))
    auth.sql.validate_complete(state,sessions/first,completion,pins,version,uuid,first)
    identities=auth.sql.private_identities(state)
    content=server_content.verify(package/'server-content',package/'content-receipt.json',core['contentReceipt']['sha256'],
                                  core['source'],core['sourceLockSha256'],auth.document(package/'server-programs/provenance/server-modules.json'))
    started=time.monotonic()
    owner=auth.sql.ServiceProcess(state,sessions,mysql,mysqld,version)
    try:
        owner.wait_ready(uuid)
        secret=db.read_secret(state/'accounts/database-secret')
        with db.option_file(state,'esteria',secret) as options,db.Mysql(mysql,options) as connection,db.state_lock(state):
            check=lambda:owner.verify(connection,uuid)
            require(check())
            with realm.named_locks(connection,('esteria-local-bootstrap','esteria-local-realm','esteria-local-account')):
                completed=bots.verify_completed(content,connection,state,version,expected_uuid=uuid,verify_service=check)
            require(completed['playerbotsSchemaInitialized'] is True and completed['exactSourceLedgerVerified'] is True and
                    completed['preparedStatementCount']==bots.STATEMENTS and completed['mysqlUuid']==uuid)
            names=connection.query('SHOW DATABASES')
            require(set(db.DATABASES).issubset(names))
            require(realm.active_config_verified(content,state,secret,profile=auth.document(package/'local-server.json'),
                    data=Path(NAMESPACE['data']),mysql=mysql)==completion['configGeneration'] and check())
        owner.stop(uuid)
    finally:
        owner.close()
    require(auth.sql.private_identities(state)==identities)
    auth.sql.validate_complete(state,sessions/first,completion,pins,version,uuid,first)
    stopped=[]
    for row in sorted(sessions.iterdir()):
        require(row.is_dir() and not row.is_symlink() and re.fullmatch('[0-9a-f]{32}',row.name))
        auth.sql.stopped_document(auth.document(row/'stopped.json'),row.name,version,uuid)
        stopped.append(row.name)
    require(len(stopped)==3 and owner.operation in stopped and first in stopped)
    db.atomic_json(evidence/'package.json',PACKAGE)
    db.atomic_json(evidence/'cold-reopen.json',dict(formatVersion=1,scope='fresh-native-packaged-stock-sql-cold-reopen',
                   sourceCommit=SOURCE,package=PACKAGE,namespace=NAMESPACE,uuid=uuid,version=version,initialSetupOperation=first,
                   coldOperation=owner.operation,cleanlyStoppedOperations=stopped,fourSchemas=list(db.DATABASES),
                   originalAuthChallengeVerified=True,originalAccountAndConfigRetained=True,completedLedgerVerified=True,
                   noMigrationOrSeederOnReopen=True,sourceBoundIdentities=identities,seconds=round(time.monotonic()-started,3)))


if __name__=='__main__':
    verify()
