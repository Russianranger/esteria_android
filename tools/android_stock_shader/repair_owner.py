"""Run the installed foreground-independent repair owner against the same cold/warm private Android fixture."""
import json
from pathlib import Path
import re
import subprocess


def run_repair(container, command_prefix, source, generation, report_path):
    if container != 'esteria-android-qa':
        raise ValueError('qualified isolated Android container required')
    result = subprocess.run([*command_prefix, 'io.github.russianranger.esteria.runtime.ConfirmShader', 'repair', source],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=145*60)
    # Android exception messages and compiler logs can contain real names. Keep them on the disposable runner.
    rows = [row.removeprefix('ANDROID_SHADER_REPAIR_RESULT ') for row in result.stdout.splitlines()
            if row.startswith('ANDROID_SHADER_REPAIR_RESULT ')]
    if result.returncode or len(rows) != 1:
        classes = re.findall(r'(?:Caused by: |^)([a-zA-Z_][a-zA-Z0-9_.]+(?:Exception|Error))\b', result.stdout, re.MULTILINE)
        lines = re.findall(r'ConfirmShaderRepair\.java:(\d+)\)', result.stdout)
        failure = dict(phase='installed-named-repair', returncode=result.returncode, exceptionClasses=classes[-6:],
                       observerLines=[int(line) for line in lines[-4:]])
        Path(report_path).write_text(json.dumps(failure)+'\n')
        raise RuntimeError('installed named shader repair failed')
    proof = json.loads(rows[0])
    flags = ('pointerRestored','damagedRejectedByFullAdmission','sameSizeAndInodeAtInjection','javaMillisecondMtimePreserved',
             'fullSessionReceiptAdmitted','previousRejectedGenerationRetained','sourceAndProviderPointersUnchanged','ownersClosed')
    observed = ('generation','importGeneration','initialReceipt','repairedReceipt','pointerRecompiled','warmRecompiled',
                'javaExactMtimePreserved','nativeRebuiltModulesValidated','runtimeFileDigestsPreserved','files',
                'pointerMs','rebuildAndAdmissionMs','warmMs')
    if set(proof) != set(flags + observed) or not all(proof.get(key) is True for key in flags):
        raise ValueError('installed repair result fields differ')
    if (proof['generation'] != generation or proof['importGeneration'] != source or
            proof['pointerRecompiled'] is not False or proof['warmRecompiled'] is not False or
            type(proof['javaExactMtimePreserved']) is not bool or proof['nativeRebuiltModulesValidated'] != 1580 or
            proof['runtimeFileDigestsPreserved'] != 3162 or proof['files'] != 4742 or
            any(not re.fullmatch(r'[0-9a-f]{64}',proof[k]) for k in ('initialReceipt','repairedReceipt')) or
            any(type(proof[k]) is not int or proof[k] < 0 for k in ('pointerMs','rebuildAndAdmissionMs','warmMs'))):
        raise ValueError('native repair selection or verified inventory differs')
    Path(report_path).write_text(json.dumps(proof,indent=2)+'\n')
    return proof
