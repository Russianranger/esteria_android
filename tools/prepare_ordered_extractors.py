#!/usr/bin/env python3
"""Apply a separately pinned extractor-only adaptation to a fresh source export.

Neither the global seven-patch selection nor original preparation receipts change.
The output is unsealed until its actual target-only native build/lookup gates pass.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

if not __package__:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import package_server_engine as engine, prepare_runtime as archives
from tools import package_server_content as transaction, verify_server_build as files

ROOT=Path(__file__).resolve().parents[1]
LOCK=ROOT/'runtime/server/extractor-order.lock.json'
require=files.require


def load_pin():
    pin,_=engine.modules.read_json(LOCK)
    require(pin.get('formatVersion')==1 and pin.get('scope')=='separate-extractor-only-order-adaptation-inputs' and
            pin.get('contract')=='esteria-classical-ordered-providers-v1' and
            pin.get('globalServerPatchListChanged') is False and len(pin.get('baseFiles',{}))==4 and
            set(pin['baseFiles'])==set(pin['adaptedFiles']),'extractor-adaptation-input-pin')
    for kind in ('patch','header'):
        row=pin[kind];engine.content.safe_path(row['file'])
        require(files.identity(ROOT/row['file'])==engine.identity(row),'extractor-adaptation-recipe-changed:'+kind)
    require(set(pin.get('recipes',{}))=={'runtime/extractor_order.py','tools/prepare_ordered_extractors.py'},
            'extractor-adaptation-recipe-set')
    for name,row in pin['recipes'].items():
        engine.content.safe_path(name)
        require(files.identity(ROOT/name)==row,'extractor-adaptation-recipe-changed:'+name)
    return pin


def apply(source,pin=None):
    """Mutate only a caller-owned fresh copy, with exact before/after readback."""
    pin=pin or load_pin();source=archives.directory(Path(os.path.abspath(source)))
    for name,row in pin['baseFiles'].items():
        engine.content.safe_path(name);require(files.identity(source/name)==row,'extractor-adaptation-base-file-changed:'+name)
        (source/name).chmod(0o600)
    header=source/pin['header']['installedPath'];require(not os.path.lexists(header),'extractor-adaptation-header-already-exists')
    patch=ROOT/pin['patch']['file']
    for operation in (['--check'],[]):
        result=subprocess.run(['git','apply','--no-index',*operation,str(patch)],cwd=source,
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30,
            env={'PATH':'/usr/bin:/bin','LC_ALL':'C','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null',
                 'GIT_CEILING_DIRECTORIES':str(source.parent),'GIT_OPTIONAL_LOCKS':'0'})
        require(result.returncode==0,'extractor-adaptation-patch-did-not-apply-exactly')
    engine.copy_verified(ROOT/pin['header']['file'],header,engine.identity(pin['header']))
    for name,row in pin['adaptedFiles'].items():
        require(files.identity(source/name)==row,'extractor-adaptation-after-file-changed:'+name);(source/name).chmod(0o444)
    require(files.identity(header)==engine.identity(pin['header']),'extractor-adaptation-header-readback')
    return dict(formatVersion=1,scope='separate-extractor-only-source-adaptation',inputLock=files.identity(LOCK),
        baseServerSource=pin['baseServerSource'],serverBuildSourceLock=pin['serverBuildSourceLock'],
        patch=pin['patch'],header=pin['header'],beforeFiles=pin['baseFiles'],afterFiles=pin['adaptedFiles'],
        globalServerPatchListChanged=False,sourceCompanionComplete=False,nativeAdaptedToolsQualified=False,
        clientMpqConversionQualified=False,customEsteriaDataLoadOrderQualified=False,
        androidRuntimeQualified=False,gameplayQualified=False)


def prepare(prepared,output):
    pin=load_pin();prepared=archives.directory(Path(os.path.abspath(prepared)))
    original,original_identity=engine.modules.read_json(prepared/'preparation-receipt.json')
    require(original.get('sourceLock')==pin['serverBuildSourceLock'] and original.get('gitMetadataPresent') is False and
            original.get('assetTreesIncluded') is False and original.get('sourceCompanionComplete') is False,
            'exact-unsealed-seven-patch-source-preparation-required')
    output=Path(os.path.abspath(output));archives.directory(output.parent,create=True)
    require(not os.path.lexists(output) and prepared!=output and prepared not in output.parents and output not in prepared.parents,
            'extractor-adaptation-output-exists-or-overlaps')
    stage=Path(tempfile.mkdtemp(prefix='.'+output.name+'.stage-',dir=output.parent))
    try:
        # Source preparation outputs only regular files/directories. Never follow
        # links into a repository, assets or an unrelated working tree.
        for parent,dirs,names in os.walk(prepared,followlinks=False):
            for name in dirs+names:require(not (Path(parent)/name).is_symlink(),'linked extractor preparation refused')
        shutil.copytree(prepared,stage,dirs_exist_ok=True)
        proof=apply(stage/'source',pin);proof['originalPreparationReceipt']=original_identity
        require(files.identity(stage/'preparation-receipt.json')==original_identity,'original-extractor-preparation-receipt-rewritten')
        engine.put_metadata(stage/'extractor-adaptation.json',proof)
        archives.sync_directory(stage);transaction.publish_directory(stage,output);archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists():shutil.rmtree(stage)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('prepared','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(json.dumps(prepare(args.prepared,args.output),indent=2))


if __name__=='__main__':main()
