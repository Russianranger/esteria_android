#!/usr/bin/env python3
"""Prepare reviewable runtime and rebuild inputs without changing production pins.

The output is deliberately incomplete for app adoption: publication, independently
measured providers and X11/client gates are required before selecting any files.
Historical provider descriptors are never copied into the proposal as new ones.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

try:
    from . import wine_arm64_requalification as retained
    from . import prepare_runtime as archives
    from .package_server_content import publish_directory
except ImportError:
    import wine_arm64_requalification as retained
    import prepare_runtime as archives
    from package_server_content import publish_directory

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LOCK = ROOT / 'runtime/runtime-sources.lock.json'
BOUND_INPUTS = ('runtime/runtime-sources.lock.json', 'runtime/bridges/sources.lock.json',
                'runtime/bridges/x11-runtime.lock.json', 'runtime/bridges/android-provider.lock.json',
                'runtime/client/android-provider.lock.json', 'runtime/client/dependency-release.lock.json',
                'runtime/shaders/android-provider.lock.json', 'runtime/shaders/dependency-release.lock.json',
                'runtime/turnip/sources.lock.json', 'runtime/turnip/android-provider.lock.json')
require = archives.require


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def release_tag(pin):
    return 'deps-wine-arm64-' + pin['sourceRevision'][:7] + '-' + pin['files']['wine-arm64.tar.gz']['sha256'][:12]


def proposal(candidate, receipt, pin, previous, tag):
    """Translate measured metadata to the existing Android installation contract."""
    require(re.fullmatch(r'deps-wine-arm64-[a-z0-9-]+', tag), 'adoption-release-tag')
    old = json.loads(retained.runtime.LOCK.read_bytes())['oldProviderArchiveSha256']
    require(previous['formatVersion'] == 1 and previous['packages']['wine-arm64']['archive']['sha256'] == old,
            'adoption-production-base-changed')
    selected = copy.deepcopy(candidate['packages']['wine-arm64'])
    require(selected['archive'] == receipt['archive'] and selected['archive']['sha256'] != old and
            selected['wineEnvironment'] == {'WINE_ANDROID_PRIVATE_PE_COPY': '1'}, 'adoption-measured-runtime-binding')
    base = 'https://github.com/Russianranger/esteria_android/releases/'
    selected['release'] = base + 'tag/' + tag
    for key in ('archive', 'manifest'):
        selected[key]['url'] = base + 'download/' + tag + '/' + selected[key]['file']
    selected['status'] = 'source-owned-native-arm64-host-measured-android-unqualified'
    bounds = receipt['installLimits']
    require(bounds['entries'] == selected['archiveEntries'] and
            bounds['fileBytes'] == receipt['maximumPhysicalFileBytes'] and
            selected['archiveFileBytes'] <= bounds['fileBytes'] <= selected['limits']['fileBytes'] and
            0 < bounds['memberBytes'] <= selected['limits']['memberBytes'], 'adoption-measured-install-bounds')
    selected['limits'] = {name: bounds[name] for name in ('entries', 'memberBytes', 'fileBytes', 'pathBytes')}
    marker = selected['markerPath']
    metadata = {name: selected['components'].pop(name) for name in (marker, 'usr/lib/os-release')}
    selected['metadataFiles'] = ['usr/lib/os-release']
    selected['sourceCompanion'] = dict(file='wine-arm64-corresponding-sources.zip', **pin['sourcesArtifact'],
        originalArtifactId=pin['sourcesArtifactId'], originalWorkflowRun=pin['workflowRun'],
        originalProducerRevision=pin['sourceRevision'],
        url=base + 'download/' + tag + '/wine-arm64-corresponding-sources.zip')
    profile = dict(formatVersion=1, packageKey='wine-arm64', metadataBytes=32*1024**2, requiredMetadata=metadata)
    result = copy.deepcopy(previous)
    result['purpose'] = 'review-only source-owned ARM64 Wine proposal; publication and coherent providers required'
    result['packages']['wine-arm64'] = selected
    result['androidInstallation'] = profile
    for key in ('softwareGraphics', 'softwareAudio'):
        require(candidate[key]['runtimeArchiveSha256'] == selected['archive']['sha256'], 'adoption-component-profile-binding')
        result[key] = copy.deepcopy(candidate[key])
    require(not selected['components'].keys() & metadata.keys(), 'adoption-duplicate-install-file')
    require(len(encoded(result)) <= 128*1024, 'adoption-runtime-lock-exceeds-application-bound')
    return result


def rebound_context(source, output, archive, old):
    """Make new build inputs, never a relabelled binary/provider receipt."""
    require(not os.path.lexists(output), 'adoption-build-context-exists')
    shutil.copytree(source, output, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    path = output / 'sources.lock.json'; before = retained.client.identity(path)
    value = json.loads(retained.client.small(path))
    require(value['runtimeArchiveSha256'] == old, 'adoption-old-build-input-binding-changed')
    value['runtimeArchiveSha256'] = archive
    path.write_bytes(encoded(value))
    return dict(originalSourceLock=before, proposedSourceLock=retained.client.identity(path),
                originalRuntimeArchiveSha256=old, proposedRuntimeArchiveSha256=archive,
                rebuildRequired=True, actualBinaryOrProviderQualified=False)


def selected_host_evidence(path, pin, client):
    value = json.loads(retained.client.small(path))
    require(value.get('scope') == 'actual-native-linux-arm64-selected471-on-retained-source-owned-wine-component-evidence' and
            value.get('conclusion') == 'success' and value.get('selectedRuntimeInput') == pin and
            value.get('selectedClientInput') == client and value.get('runtimeRecompiled') is False and
            value.get('selected471ActualComponentGatesPassed') is True and value.get('gameplayQualified') is False and
            value.get('androidArm64Qualified') is False, 'adoption-selected-host-evidence')
    result = value['qualification']
    flags = retained.qualification.qualification_flags(result['worker'], ['presentation', 'texture'],
                                                      result['namespaceExit'], True, True, True, True, True)
    require(len(flags) == 9 and all(flags.values()) and all(result.get(key) is True for key in flags) and
            result.get('runtimeArchiveSha256') == pin['files']['wine-arm64.tar.gz']['sha256'] and
            result.get('client', {}).get('sourceRevision') == client['sourceRevision'] and
            result.get('wineEnvironment') == {'WINE_ANDROID_PRIVATE_PE_COPY': '1'}, 'adoption-selected-host-gates')
    return dict(receipt=retained.client.identity(path), workflowRun=value['workflowRun'],
                integrationRevision=value['integrationRevision'], clientRevision=client['sourceRevision'],
                runtimeArchiveSha256=result['runtimeArchiveSha256'], allNineNativeComponentGatesPassed=True,
                androidQualified=False, gameplayQualified=False)


def prepare(package, output, host_evidence=None):
    output = Path(os.path.abspath(output))
    require(not os.path.lexists(output), 'adoption-output-exists')
    archives.directory(output.parent)
    pin, selected_client = retained.pins()
    receipt, candidate = retained.runtime_package(archives.directory(package), pin)
    before = {name: retained.client.identity(ROOT / name) for name in BOUND_INPUTS}
    previous = json.loads(retained.client.small(RUNTIME_LOCK))
    tag = release_tag(pin)
    proposed = proposal(candidate, receipt, pin, previous, tag)
    host = selected_host_evidence(host_evidence, pin, selected_client) if host_evidence is not None else None
    old = previous['packages']['wine-arm64']['archive']['sha256']
    archive = proposed['packages']['wine-arm64']['archive']['sha256']
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.', dir=output.parent))
    try:
        (stage / 'runtime-sources.proposed.lock.json').write_bytes(encoded(proposed))
        contexts = {}
        for key, source in (('bridge', 'runtime/bridges'), ('turnip', 'runtime/turnip')):
            contexts[key] = rebound_context(ROOT / source, stage / (key + '-build-context'), archive, old)
        # These are originals to preserve when publishing, not regenerated source
        # or execution receipts. Large companion bytes stay on the CI/release path.
        files = {name: pin['files'][name] for name in sorted(retained.RUNTIME_FILES)}
        report = dict(formatVersion=1, scope='review-only-source-owned-arm64-wine-adoption-inputs',
            previousRuntimeArchiveSha256=old, proposedRuntimeArchiveSha256=archive,
            producerRevision=pin['sourceRevision'], producerWorkflowRun=pin['workflowRun'],
            originalNativeClientRevision=pin['originalNativeClientRevision'],
            selectedClientRevision=selected_client['sourceRevision'],
            productionInputs=before, proposedRuntimeLock=retained.client.identity(stage / 'runtime-sources.proposed.lock.json'),
            originalRuntimePackageFiles=files, originalRuntimeArtifact=dict(id=pin['artifactId'], **pin['artifact']),
            originalSourceArtifact=dict(id=pin['sourcesArtifactId'], **pin['sourcesArtifact']),
            sourceCompanionFilename='wine-arm64-corresponding-sources.zip', proposedReleaseTag=tag,
            proposedReleasePublished=False, buildContexts=contexts,
            requiredWineEnvironment={'WINE_ANDROID_PRIVATE_PE_COPY': '1'},
            maximumPhysicalFileBytes=receipt['maximumPhysicalFileBytes'],
            maximumHardLinkCopies=receipt['maximumHardLinkCopies'],
            selectedHostEvidence=host,
            requiredRemainingChecks=([] if host else ['selected471ActualNativeClientComponentGates']) + [
                'publishExactRuntimeAndCompleteOriginalSourceCompanion',
                'rebuildGuestBridgeAndMeasureNewProviderAndSourceClosure',
                'rebuildTurnipAndRunActualIcdAndShaderCompilerComponentGates',
                'repackSelectedClientAndShaderProvidersAndMatchingSources',
                'reauditX11ElfLoaderConfigurationAndAliases',
                'actualAuthenticatedX11WrongMissingAndCorrectCookieChecks',
                'validatedApplicationWineEnvironmentSelection',
                'verifyCoherentAllProviderApk'],
            sourceArchiveRepacked=False, runtimeRecompiled=False, runtimeExpandedLocally=False,
            providersRelabelled=False, productionPinsChanged=False,
            readyForProductionSelection=False, androidQualified=False, gameplayQualified=False)
        require(before == {name: retained.client.identity(ROOT / name) for name in BOUND_INPUTS},
                'adoption-production-inputs-changed-during-preparation')
        (stage / 'adoption-preparation.json').write_bytes(encoded(report))
        publish_directory(stage, output)
        archives.sync_directory(output.parent)
        return report
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--host-evidence', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.runtime_package, args.output, args.host_evidence), indent=2))


if __name__ == '__main__': main()
