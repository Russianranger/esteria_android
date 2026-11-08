"""Replay the observed v13 translator failure, update in place and repair its unsealed store."""
import json
import os
from pathlib import Path
import re
import subprocess

LEGACY_SHA = '9d9809d5e04b4bac5d1f0826d4fb0255a53318fe3220f5a7d19e8a077b01dbae'
CANDIDATE_SHA = 'c0d251847496c64170bb31d534a925afd1d8e7f92c21687e0e1cbf82c056e6fa'


def exercise(module, container, uid, source, apk, prefix, counters, report):
    shell = module.shell
    require = module.checked
    package = module.PACKAGE
    root = module.ACTOR
    def typed_snapshot():
        names=['game/current','game/generations/'+source+'/complete','game/generations/'+source+'/journal.tsv',
               'runtimes/wine-arm64/current','runtimes/shader-tools-arm64/current']
        facts = shell(container, '''
            root=$1; shift
            for name do
                p="$root/$name"; test -f "$p" && test ! -L "$p"
                stat -c "%d %i %s %Y" "$p"; sha256sum "$p" | cut -d' ' -f1
            done''', root,*names).splitlines()
        require(len(facts)==2*len(names),'unqualified retained provider/input snapshot')
        return facts
    def owner(command, stage):
        before = module.range_counts(counters)
        p = subprocess.run(command, capture_output=True, text=True, timeout=42*60)
        output=p.stdout+'\n'+p.stderr
        rows=[r.removeprefix('ANDROID_HISTORICAL_SHADER_RESULT ') for r in output.splitlines()
              if r.startswith('ANDROID_HISTORICAL_SHADER_RESULT ')]
        if p.returncode or len(rows)!=1:
            report['historicalFailure'] = {'mode':stage,'exit':p.returncode,'classes':re.findall(
                r'(?:Caused by: |ANDROID_SHADER_EXCEPTION )([a-zA-Z0-9_.]+(?:Error|Exception))',output)[-8:],
                'observerLines':[int(n) for n in re.findall(r'ConfirmShader(?:Repair)?\.java:([0-9]+)',output)[-8:]]}
            raise ValueError('historical owner stopped in '+stage)
        body=json.loads(rows[0])
        require(body['mode']==stage and body['closed'] and body['importGeneration']==source,'historical owner identity differs')
        body['authenticatedInput']=module.range_delta(counters,before)
        if stage!='admit':
            require(body['authenticatedInput']['grantedBytes']>0,'historical generation did not read real source')
        return body
    def invocation(prefix,mode):
        return [*prefix,'io.github.russianranger.esteria.runtime.ConfirmShader',mode,source]
    require(shell(container,'sha256sum "$1" | cut -d" " -f1',apk).strip()==LEGACY_SHA,
            'original installed v13 differs from physical support version')
    old=owner(invocation(prefix,'legacy'),'legacy')
    require(old['noCurrentPointer'] and old['workerExit']==2 and old['failedLegacyPermutations']==10,
            'expected failure and unsealed legacy store required')
    report['legacyFailure']=old
    snapshot = typed_snapshot()
    report['phase']='in-place-update'
    updated=shell(container,'''
        candidate=/data/local/tmp/esteria-v19-over-failed-v13.apk
        test ! -e "$candidate"; trap 'rm -f "$candidate"' EXIT
        cp /esteria-qa/input/stock.apk "$candidate"; chmod 0644 "$candidate"
        pm install -r --user 0 "$candidate"
        ''',timeout=420)
    require('Success' in updated.splitlines(),'Android refused v13 to v19 in-place update')
    newbase=shell(container,'pm path "$1"',package).strip().removeprefix('package:')
    require(re.fullmatch(r'/data/app/[A-Za-z0-9_./=+~-]+/base\.apk',newbase) and newbase!=apk and
            shell(container,'sha256sum "$1" | cut -d" " -f1',newbase).strip()==CANDIDATE_SHA,'installed signed candidate differs')
    require(shell(container,'stat -c %u "$1"','/data/data/'+package).strip()==uid and typed_snapshot()==snapshot,
            'old package UID or source/provider identity changed during update')
    require('versionCode=19 ' in shell(container,'dumpsys package "$1"',package),'installed version differs')
    report['phase']='named-repair-after-failed-v13'
    updated_prefix=[v.replace(apk,newbase).replace(os.path.dirname(apk)+'/lib/arm64',os.path.dirname(newbase)+'/lib/arm64') for v in prefix]
    result=owner(invocation(updated_prefix,'recovered'),'recovered')
    require(result['namedRepairPublished'] and result['freshSessionAdmission'] and result['newValidatedModules']==1580 and
            result['verifiedRuntimeHashes']==3162 and result['outputFiles']==4742 and typed_snapshot()==snapshot,
            'selected legacy import or provider state changed during repair')
    report['recovered']=result
    report['phase']='fresh-read-only-session-admission'
    receipt=root+'/state/shader-work/shaders/generations/'+result['generation']+'/receipt.json'
    def shader_selection():
        return shell(container,'for p do stat -c "%d %i %s %Y" "$p"; sha256sum "$p" | cut -d" " -f1; done',
                     root+'/state/shader-work/shaders/current',receipt).splitlines()
    selected=shader_selection()
    normal=owner(invocation(updated_prefix,'admit'),'admit')
    report['freshNormalSession']=normal
    require(normal['fullShaderAdmission'] and not normal['ownedTranslatorLaunched'] and
            normal['generation']==result['generation'] and normal['bytes']==result['outputBytes'] and
            normal['authenticatedInput']['grantedBytes']==0 and typed_snapshot()==snapshot and shader_selection()==selected,
            'ordinary fresh session changed a selected input, read MPQs or repeated preparation')
    report['phase']='separate-fresh-warm-provider-prepare'
    before=module.range_counts(counters)
    completed=subprocess.run(invocation(updated_prefix,'warm'),capture_output=True,text=True,timeout=600)
    rows=[r.removeprefix('ANDROID_SHADER_RESULT ') for r in completed.stdout.splitlines() if r.startswith('ANDROID_SHADER_RESULT ')]
    require(not completed.returncode and len(rows)==1,'fresh warm owner could not reuse repaired selection')
    warm=json.loads(rows[0])
    warm['authenticatedInput']=module.range_delta(counters,before)
    now=typed_snapshot()
    names=['game/current','import/complete','import/journal.tsv','wine/current','shader-tools/current']
    differences={name:{'sameBytes':now[i*2+1]==snapshot[i*2+1],'sameStat':now[i*2]==snapshot[i*2],
                        'beforeStat':snapshot[i*2], 'afterStat':now[i*2]} for i,name in enumerate(names)}
    report['warmProviderPointerObservations']=differences
    report['warmAfterHistoricalRepair']=warm
    require(all(facts['sameBytes'] for facts in differences.values()) and
            all(differences[name]['sameStat'] for name in names[:3]) and shader_selection()==selected,
            'explicit package prepare changed imported bytes, shader selection or provider pointer content')
    require(warm['mode']=='warm' and warm['generation']==result['generation'] and not warm['ownedTranslatorLaunched'] and
            warm['toolsCopiedBytes']==0 and warm['wineCopiedBytes']==0 and warm['sessionReceiptAdmitted'] and
            warm['authenticatedInput']['grantedBytes']==0,
            'fresh post-repair owner repeated work or changed source')
    report.update(phase='complete',warmAfterHistoricalRepair=warm,retainedInputAndProviderFiles=len(snapshot)//2,
                  firstInstalledSha256=LEGACY_SHA,updatedInstalledSha256=CANDIDATE_SHA,uidRetained=True)
