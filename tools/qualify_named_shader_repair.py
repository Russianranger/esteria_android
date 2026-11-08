"""Use the production shader coordinator and repair driver on one authenticated ARM64 corpus."""
import hashlib
import json
import os
import re
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def guarded_translator():
    # This runs in the production coordinator's bounded translator subprocess. Only
    # MPQ reads and launches of the exact unmodified compiler are observed.
    sys.path.insert(0, str(ROOT))
    from tools.qualify_stock_shader_corpus import verified_reads
    ranges, calls, compiler, script, *arguments = sys.argv[1:]
    extents = {Path(p): spans for p, spans in json.loads(Path(ranges).read_bytes()).items()}
    def audit(event, args):
        if event == 'subprocess.Popen' and os.fsdecode(args[0]) == compiler:
            with open(calls, 'ab') as log:
                log.write(b'compile\n')
    sys.addaudithook(audit)
    sys.path.insert(0, str(Path(script).parent))
    sys.argv = [script, *arguments]
    with verified_reads(extents, dict(mpqReadCalls=0, mpqReadBytes=0)):
        runpy.run_path(script, run_name='__main__')


def qualify(work, client, tools, revision, extents, proof):
    from runtime import stock_shader_generation as stock, stock_shader_repair
    from tools.qualify_stock_shader_corpus import require
    require(extents is not None, 'repair qualification requires the authenticated extent fixture')
    game = work / 'fixture-import'
    store = work / 'repair-shaders'
    source = hashlib.sha256(b'private authenticated stock shader projection fixture, v1').hexdigest()
    generation = game / 'generations' / source
    data = generation / 'data'
    paths = {}
    for path, spans in extents.items():
        selected = data / path.relative_to(client)
        selected.parent.mkdir(parents=True, exist_ok=True)
        os.link(path, selected)
        paths[str(selected)] = spans
    ranges = work / 'private-repair-extents.json'
    ranges.write_text(json.dumps(paths))
    (generation / 'complete').write_text(f'format=1\nclientBuild=12340\nrequest={source}\nsource={source}\n')
    (generation / 'journal.tsv').write_text('private fixture import metadata for authenticated shader extents\n')
    (game / 'current').write_text(source + '\n')
    calls = work / 'compiler-calls'
    calls.touch()
    compiler = (tools / 'bin/glslangValidator').resolve()
    execute = stock.execute
    def guarded(command, log, timeout, **kwargs):
        require(Path(command[4]) == stock.TRANSLATION_ADAPTER, 'unexpected production shader invocation')
        observed = [*command[:4], str(Path(__file__).resolve()), str(ranges), str(calls), str(compiler), *command[4:]]
        return execute(observed, log, timeout, **kwargs)
    def count():
        return len(calls.read_bytes().splitlines())
    def disassembly_contents(directory, pins, staging, key):
        result = {}
        for name in pins:
            if not name.endswith('.spvasm'):
                continue
            raw = (directory / 'shaders' / name).read_bytes()
            require(hashlib.sha256(raw).hexdigest() == pins[name]['sha256'], 'compiled disassembly differs from its receipt')
            first, separator, body = raw.partition(b'\n')
            expected = os.fsencode(staging / (key+'-'))
            suffix = os.fsencode('/shaders/' + name.removesuffix('.spvasm') + '.glsl')
            require(separator and first.startswith(expected) and first.endswith(suffix) and
                    re.fullmatch(rb'[0-9a-f]{32}', first[len(expected):-len(suffix)]) and body.startswith(b'; SPIR-V\n'),
                    'unexpected compiler diagnostic filename or disassembly header')
            result[name] = hashlib.sha256(body).hexdigest()
        return result
    args = store, game, source, tools, revision, 'enUS'
    with patch.object(stock, 'execute', side_effect=guarded):
        proof['stage'] = 'initial-production-shader-generation'
        receipt = stock.generate(*args)
        key = receipt['generation']
        modules = sorted(name for name in receipt['outputs'] if name.endswith('.spv'))
        initial = count()
        proof.update(stage='corrupt-private-copy',initialCompilerInvocations=initial)
        require(initial == len(modules) == 1580, 'initial selected compiler count differs')
        dest = store / 'generations' / key
        old_disassembly = disassembly_contents(dest,receipt['outputs'],store / 'staging',key)
        private_file = dest / 'shaders' / modules[0]
        original = private_file.read_bytes()
        private_file.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        try:
            stock.generate(*args)
        except stock.ShaderError:
            pass
        else:
            raise ValueError('normal preparation accepted damaged stock SPIR-V')
        require(count() == initial, 'unexpected compile during old-generation rejection')
        proof['stage'] = 'explicit-same-size-repair'
        repaired, action = stock_shader_repair.repair(*args)
        rebuilt = count() - initial
        proof.update(stage='verify-repaired-outputs',repairCompilerInvocations=rebuilt)
        after = json.loads((dest / 'receipt.json').read_bytes())
        same_runtime = (after['outputs'].keys() == receipt['outputs'].keys() and
                        all(after['outputs'][name] == pin for name,pin in receipt['outputs'].items() if not name.endswith('.spvasm')))
        same_disassembly = disassembly_contents(dest,after['outputs'],store / 'repair/staging',key) == old_disassembly
        proof.update(runtimeOutputsMatch=same_runtime, normalizedDisassembliesMatch=same_disassembly,
                     outputGenerationMatch=repaired == key, repairedSpirvBytesMatch=private_file.read_bytes() == original)
        require(repaired == key and action == 'published-replacement' and rebuilt == initial and
                private_file.read_bytes() == original and same_runtime and same_disassembly and
                {k:v for k,v in after.items() if k!='outputs'} == {k:v for k,v in receipt.items() if k!='outputs'},
                'named repair did not restore selected runtime shaders and disassembly contents')
        (store / 'current').write_text('damaged fixture pointer\n')
        reused, action = stock_shader_repair.repair(*args)
        warm = count()-initial-rebuilt
        require(reused == key and action == 'verified-existing' and warm == 0 and
                (store / 'current').read_text() == key+'\n', 'warm stock repair did not restore selection without recompiling')
    return dict(environment='native Linux ARM64, authenticated stock shader reads and fixture import metadata',
                generation=key, outputFiles=len(receipt['outputs']), modules=len(modules), sameGenerationInputs=True, runtimeOutputsMatch=True, normalizedDisassembliesMatch=True,
                initialCompilerInvocations=initial, repairCompilerInvocations=rebuilt, warmCompilerInvocations=warm,
                compilerSha256=stock.identity(compiler,64<<20)['sha256'], fixedSameSizeSpirv=True,
                fixedInvalidPointer=True, androidRuntimeQualified=False, gameplayQualified=False)


if __name__ == '__main__':
    guarded_translator()
