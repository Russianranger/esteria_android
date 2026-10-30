#!/usr/bin/env python3
"""Run actual source-built compiler, validator and disassembler on bounded fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess


def require(ok, reason):
    if not ok: raise ValueError(reason)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();require(platform.machine() in ('aarch64','arm64'),'native-arm64-shader-test-required')
    args.output.mkdir();directory=args.directory.resolve();output=args.output.resolve()
    report=dict(formatVersion=1,scope='native-linux-arm64-shader-tools-only',qualified=False,
                androidQualified=False,gameAssetShadersQualified=False,gameplayQualified=False)
    def run(label, argv, expected):
        result=subprocess.run([str(x) for x in argv],cwd=output,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
        require(len(result.stdout)<=1024**2,'fixture-log-size-limit')
        (output/(label+'.log')).write_bytes(result.stdout)
        require((result.returncode==0) if expected else (0<result.returncode<128),label+'-unexpected-exit')
        return result.stdout
    try:
        source=output/'fixture.vert';source.write_text('#version 450\nvoid main(){gl_Position=vec4(0,0,0,1);}\n')
        compiler=directory/'glslangValidator';validator=directory/'spirv-val'
        spv=output/'valid.spv'
        log=run('compile-validate-disassemble',[compiler,'-V','--target-env','vulkan1.0','--spirv-val','--spirv-dis',
            '-S','vert','-o',spv,source],True)
        require(b'OpMemoryModel' in log and b'OpEntryPoint Vertex' in log,'actual-disassembly-required')
        raw=spv.read_bytes();require(20<=len(raw)<=65536 and raw[:4]==b'\x03\x02\x23\x07','real-spirv-output-required')
        run('independent-valid-spirv',[validator,'--target-env','vulkan1.0',spv],True)
        invalid=output/'invalid.vert';invalid.write_text('#version 450\nvoid main(){gl_Position=missing_symbol;}\n')
        bad_output=output/'invalid.spv'
        run('invalid-glsl',[compiler,'-V','--target-env','vulkan1.0','--spirv-val','--spirv-dis','-S','vert','-o',bad_output,invalid],False)
        require(not bad_output.exists(),'invalid-glsl-produced-output')
        malformed=output/'malformed.spv';malformed.write_bytes(b'BAD!'+raw[4:])
        run('invalid-spirv',[validator,'--target-env','vulkan1.0',malformed],False)
        report.update(qualified=True,validGlslCompiled=True,spirvValidated=True,spirvDisassembled=True,
            invalidGlslRejected=True,invalidSpirvRejected=True,validSpirvSha256=hashlib.sha256(raw).hexdigest())
    finally:
        (output/'qualification.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
