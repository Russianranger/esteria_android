"""Exact immutable reference inputs for legacy-generation unit fixtures only.

These raw Git blobs are retained in-tree so shallow CI requires no fetch and no
network. Production defaults, release locks and validators are never rewritten.
"""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent/'fixtures/wine-pre-adoption-4d27'
REVISION='4d27ba80aed0669bdbe15871ad5ddb59c14b3a39'
MANIFEST_SHA256='5c81ae895f55cfef6519e626216e8d832de3665392c63774326da552a0338ed7'


def raw(name):
    manifest_raw=(ROOT/'manifest.json').read_bytes()
    assert hashlib.sha256(manifest_raw).hexdigest()==MANIFEST_SHA256
    manifest=json.loads(manifest_raw)
    assert manifest['formatVersion']==1 and manifest['sourceRevision']==REVISION
    pin=manifest['files'][name];data=(ROOT/name).read_bytes()
    assert len(data)==pin['bytes'] and hashlib.sha256(data).hexdigest()==pin['sha256'],name
    assert hashlib.sha1(('blob '+str(len(data))+'\0').encode()+data).hexdigest()==pin['gitBlob'],name
    return data


def value(name):return json.loads(raw(name))


def materialize(output,names=None):
    names=names if names is not None else json.loads((ROOT/'manifest.json').read_bytes())['files']
    for name in names:
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw(name))
    return output
