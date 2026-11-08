"""Separately timed SQL SLEEP controls on a fresh signed helper/CLI against an already owned engine."""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import re
import sys
import threading
import time

generation, version, uuid = sys.argv[1:]
if re.fullmatch('[0-9a-f]{64}',generation) is None:
    raise ValueError('Invalid installed helper generation')
helpers=Path('/work/qa-auth-helpers')/generation
pins={'mysql_bootstrap.py':'212bf5bae4c947c57069fe7e816be1c2c1fad6869ef378fc609df359c7f50f2e',
      'mysql_service.py':'55fd55b11c614794929330a92f8b19637c8e02c3471c319f5e9429346fa716d4'}
for name,digest in pins.items():
    member=helpers/name
    if member.resolve()!=member or hashlib.sha256(member.read_bytes()).hexdigest()!=digest:
        raise ValueError('Installed SQL helpers differ from the verified release')
sys.path.insert(0,str(helpers))
import mysql_bootstrap as db
import mysql_service as service

def require(p):
    if not p: raise RuntimeError('Controlled SQL result differs')

state=Path('/work/state')
receipt=db.read_receipt(state/'database-bootstrap.json',version)
require(receipt['uuid']==db.datadir_uuid(state/'database')==uuid)
result=dict(scope='controlled-delay-on-real-first-CLI-result',inducedServerSleepSeconds=4.25,
            normalStartupMeasurement=False,helperSha256=pins)
scratch=Path('/work/qa-cold-sql-control')
def stage(name):
    db.atomic_json(scratch/'phase.json',dict(phase=name))
def elapsed(start): return round(time.monotonic()-start,3)

with db.option_file(state,'esteria',db.read_secret(state/'accounts/database-secret')) as options:
    mysql=Path('/usr/bin/mysql')
    # The CLI and all timeout logic come from the installed app. SQL SLEEP deliberately delays
    # receipt of the real authenticated result. This never alters schemas or application rows.
    stage('first-delayed-query')
    with closing(service.LiveConnection(mysql, options, time.monotonic()+90, lambda:None)) as cli:
        start=time.monotonic()
        require(cli.query('SELECT SLEEP(4.25), @@server_uuid') == ['0\t'+uuid])
        result['firstAuthenticatedDelayedResponseSeconds']=elapsed(start)
        require(result['firstAuthenticatedDelayedResponseSeconds']>=4)
        stage('warm-query')
        start=time.monotonic()
        require(cli.query('SELECT @@server_uuid') == [uuid])
        result['sameCliNormalResponseSeconds']=elapsed(start)
        stage('warm-timeout-query')
        start=time.monotonic()
        try: cli.query('SELECT SLEEP(4.25)')
        except db.BootstrapError as error:
            require(str(error)=='MySQL operation timed out')
        else: raise ValueError('Connected CLI failed to enforce its three-second limit')
        result['sameCliInducedTimeoutSeconds']=elapsed(start)
    require(cli.inner.process.poll() is not None)

    stage('cold-cancellation')
    rd,wr=os.pipe()
    control=service.Control(rd)
    timer=None
    writes=0
    def stop():
        global writes,timer
        writes+=1
        # The second callback comes from the real SQL receiver after it wrote the query.
        if writes==2:
            timer=threading.Timer(.4,lambda:os.write(wr,b'shutdown\n'))
            timer.start()
        reason=control.read(0)
        if reason: raise service.StopRequested(reason)
    try:
        with closing(service.LiveConnection(mysql,options,None,stop)) as cli:
            start=time.monotonic()
            try: cli.query('SELECT SLEEP(4.25)')
            except service.StopRequested as signal:
                require(signal.reason=='command' and timer is not None)
            else: raise ValueError('Outstanding first response ignored shutdown')
            result['cancelReturnSeconds']=elapsed(start)
            require(result['cancelReturnSeconds']<3)
        require(cli.inner.process.poll() is not None)
    finally:
        if timer is not None: timer.cancel(); timer.join()
        control.close(); os.close(rd); os.close(wr)
    stage('post-cancellation-identity')
    with closing(service.LiveConnection(mysql,options,None,lambda:None)) as cli:
        db.check_receipt(receipt,db.identity(cli,version))
result.update(threeSecondWarmCapObserved=True,cancelledOutstandingColdRead=True,
              allControlledClientsReaped=True,sameRealEngineAfterCancellation=True)
db.atomic_json(scratch/'verified.json',result)
