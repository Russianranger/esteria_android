#!/usr/bin/env python3
"""Repair one source-selected stock shader generation under the normal store's writer lock."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

if __package__:
    from . import stock_shader_generation as stock
else:
    # Fixed independent APK mount. The repair driver is outside the generation's recipe.
    sys.path.insert(0, '/esteria-stock-client')
    import stock_shader_generation as stock


def requested_inputs(game, generation, tools, revision, locale):
    helpers = stock.helper_files()
    return dict(formatVersion=1, contentProfile=stock.DEFAULT_CONTENT_PROFILE, importGeneration=generation,
                clientRevision=revision, locale=locale, importMetadata=stock.imported(game, generation),
                toolManifestSha256=stock.tool_identity(tools, revision),
                preparationHelperSha256=helpers['stock_shader_generation.py']['sha256'], preparationHelperFiles=helpers)


def sealed(path, key, inputs):
    """A false result concerns this directory only. Propagate storage/permission/cancellation errors."""
    stock.canonical(path)
    try:
        receipt = json.loads(stock.read(path / 'receipt.json', stock.MAX_TEXT))
        if not isinstance(receipt, dict) or set(receipt) != {
                'formatVersion','scope','generation','inputs','outputs','graphicsQualified','androidQualified','gameplayQualified'}:
            return False
        return (type(receipt['formatVersion']) is int and receipt['formatVersion'] == 1 and
                receipt['scope'] == 'local-generated-shaders-not-render-qualified' and receipt['generation'] == key and
                all(receipt[k] is False for k in ('graphicsQualified','androidQualified','gameplayQualified')) and
                stock.encoded(receipt['inputs']) == stock.encoded(inputs) and
                receipt['outputs'] == stock.validate_output(path / 'shaders'))
    except (FileNotFoundError, UnicodeError, json.JSONDecodeError, stock.ShaderError):
        return False


def repair(store, game, generation, tools, revision, locale):
    stock.require(locale in stock.LOCALES, 'explicit supported locale required')
    store, game, tools = stock.canonical(store, create=True), stock.canonical(game), stock.canonical(tools)
    stock.require(not any(a == b or a in b.parents or b in a.parents for a, b in
                          ((store, game), (store, tools), (game, tools))), 'shader repair roots must be separate')
    lock = os.open(store / '.setup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        inputs = requested_inputs(game, generation, tools, revision, locale)
        key = hashlib.sha256(stock.encoded(inputs)).hexdigest()
        generations = stock.canonical(store / 'generations', create=True)
        destination = generations / key
        pointer = store / 'current'
        if os.path.lexists(pointer):
            stock.canonical(pointer, False)
        if os.path.lexists(destination) and sealed(destination, key, inputs):
            if not pointer.exists() or pointer.stat().st_size != 65 or stock.read(pointer,65) != (key+'\n').encode():
                stock.atomic(pointer, (key+'\n').encode())
            return key, 'verified-existing'
        work = stock.canonical(store / 'repair', create=True)
        staged = work / 'generations' / key
        if os.path.lexists(staged) and not sealed(staged, key, inputs):
            # An interrupted worker never publishes partial output. Preserve externally
            # damaged scratch without changing the primary selection.
            staged.rename(work / ('invalid-staged-' + key + '-' + uuid.uuid4().hex))
            stock.sync(staged.parent)
            stock.sync(work)
        candidate = stock.generate(work, game, generation, tools, revision, locale)
        stock.require(candidate['generation'] == key and stock.encoded(candidate['inputs']) == stock.encoded(inputs),
                      'stock coordinator selected different shader inputs; preserve existing generation')
        # generate() validated and synced the candidate and its receipt while our outer owner
        # also held the primary store and the Android caller held the import. It has
        # its own independent scratch lock, so reacquire it and verify the selected tree.
        staged_lock = os.open(work / '.setup.lock', os.O_RDWR | os.O_NOFOLLOW)
        try:
            fcntl.flock(staged_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            stock.require(stock.read(work / 'current',65) == (key+'\n').encode() and sealed(staged,key,inputs) and
                          requested_inputs(game,generation,tools,revision,locale) == inputs,
                          'completed shader replacement or selected input changed')
            backup = None
            if os.path.lexists(destination):
                stock.canonical(destination)
                backup = work / ('replaced-' + key + '-' + uuid.uuid4().hex)
                destination.rename(backup)
                stock.sync(generations)
                stock.sync(work)
            try:
                staged.rename(destination)
            except OSError:
                if backup is not None and not os.path.lexists(destination):
                    backup.rename(destination)
                    stock.sync(generations)
                    stock.sync(work)
                raise
            stock.sync(generations)
            stock.sync(staged.parent)
            stock.atomic(pointer,(key+'\n').encode())
        finally:
            os.close(staged_lock)
        return key, 'published-replacement'
    finally:
        os.close(lock)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('store','game','tools'):
        parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--generation',required=True)
    parser.add_argument('--client-revision',required=True)
    parser.add_argument('--locale',required=True)
    parser.add_argument('--content-profile',choices=[stock.DEFAULT_CONTENT_PROFILE],required=True)
    parser.add_argument('--android-low-memory',action='store_true',required=True)
    args=parser.parse_args()
    try:
        with stock.world_io.android_policy():
            key, action=repair(args.store,args.game,args.generation,args.tools,args.client_revision,args.locale)
        print('Shader repair ' + action + ' generation=' + key,flush=True)
        return 0
    except stock.world_io.PreparationPaused:
        stock.world_io.print_pause()
        return stock.world_io.PAUSED_EXIT_CODE
    except (OSError,ValueError) as error:
        print('shader repair failed: ' + type(error).__name__ + ': ' + str(error),file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
