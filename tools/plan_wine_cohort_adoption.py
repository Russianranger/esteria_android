#!/usr/bin/env python3
"""Describe the exact atomic seven-file adoption; never mutate production locks."""
import argparse
import json
from pathlib import Path

try:
    from . import release_wine_cohort as release
except ImportError:
    import release_wine_cohort as release

ROOT=release.ROOT
ROSTER={
 'runtime/runtime-sources.lock.json':'runtime/wine-arm64-adoption/measured/runtime-sources.proposed.lock.json',
 'runtime/bridges/android-provider.lock.json':'runtime/wine-arm64-adoption/measured/guest-bridges-input.lock.json',
 'runtime/bridges/sources.lock.json':'runtime/wine-arm64-adoption/measured/bridge-sources.lock.json',
 'runtime/turnip/android-provider.lock.json':'runtime/wine-arm64-adoption/measured/turnip-input.lock.json',
 'runtime/turnip/sources.lock.json':'runtime/wine-arm64-adoption/measured/turnip-sources.lock.json',
 'runtime/shaders/android-provider.lock.json':'runtime/wine-arm64-adoption/measured/shader-tools-input.lock.json',
 'runtime/bridges/x11-runtime.lock.json':'runtime/wine-arm64-adoption/x11-runtime.lock.json'}
require=release.require


def plan():
    values={name:json.loads(release.client.small(ROOT/path)) for name,path in ROSTER.items()}
    runtime=values['runtime/runtime-sources.lock.json']['packages']['wine-arm64']
    require(runtime['archive']['sha256']==release.measured.RUNTIME and runtime['wineEnvironment']=={'WINE_ANDROID_PRIVATE_PE_COPY':'1'},
        'adoption-selected-runtime-profile')
    guest=values['runtime/bridges/android-provider.lock.json'];turnip=values['runtime/turnip/android-provider.lock.json']
    shader=values['runtime/shaders/android-provider.lock.json'];client=json.loads(release.client.small(release.client.PIN))
    require(guest['integrationRevision']==turnip['integrationRevision']==release.measured.PRODUCER and
        guest['workflowRun']==release.measured.RUN and
        guest['artifact']['runId']==release.measured.RUN and
        turnip['artifact']['originalNativeBuildArtifact']['runId']==release.measured.RUN and
        turnip['artifact']['runId']==41079114080 and turnip['artifact']['id']==12989171109 and
        shader['artifact']['originalBuildRunId']==release.measured.RUN and
        shader['artifact']['runId']==turnip['artifact']['runId'],'adoption-original-binary-and-source-recovery-remain-distinct')
    for path in ('runtime/bridges/sources.lock.json','runtime/turnip/sources.lock.json'):
        require(values[path]['runtimeArchiveSha256']==release.measured.RUNTIME,'adoption-build-source-runtime-binding')
    for pin in (turnip,shader):require(pin['requiredWineArchiveSha256']==release.measured.RUNTIME,'adoption-provider-runtime-binding')
    require(guest.get('androidRuntimeQualified') is False and
        all(turnip.get(k) is False for k in ('androidQualified','hardwareQualified','gameplayQualified')) and
        all(shader.get(k) is False for k in ('androidQualified','gameAssetShadersQualified','gameplayQualified')),
        'adoption-provider-qualification-scope')
    require(client['sourceRevision']==shader['clientRevision']=='471ee42faadf4a97a1d0a86989cf1452621f2dc5',
        'adoption-client-shader-pair')
    bridge_source=release.identity(ROOT/ROSTER['runtime/bridges/sources.lock.json'])
    require({k:guest['repositoryInputs']['runtime/bridges/sources.lock.json'][k] for k in ('bytes','sha256')}==bridge_source,
        'adoption-guest-source-retention')
    x11=values['runtime/bridges/x11-runtime.lock.json']
    require(x11['runtimeArchiveSha256']==release.measured.RUNTIME,'adoption-x11-runtime-binding')
    files={name:dict(source=path,identity=release.identity(ROOT/path),current=release.identity(ROOT/name))
        for name,path in ROSTER.items()}
    return dict(formatVersion=1,scope='proposed-atomic-seven-file-source-owned-wine-cohort-adoption',files=files,
        unchangedClientInput=release.identity(release.client.PIN),sourceSelection=release.selected_inputs(),
        sourceOnlyRecoveryNotANewBinaryBuild=True,historicalF036ReleasesUnchanged=True,
        requiredBeforeActivation=['actual-public-cohort-publication','actual-public-cohort-and-full-wine-source-readback'],
        requiredAfterAtomicActivation=['coherent-current-apk-byte-and-source-verification'],
        productionLocksMutated=False,androidQualified=False,hardwareQualified=False,gameplayQualified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args()
    value=plan()
    if args.output:release.wine.write_new(args.output,release.encoded(value))
    else:print(json.dumps(value,indent=2))


if __name__=='__main__':main()
