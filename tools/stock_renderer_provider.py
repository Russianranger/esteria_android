"""Build a source-reviewed renderer-only replacement for the stock client provider."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from tools import provider_client_runtime as client

ROOT = client.ROOT
STOCK = '471ee42faadf4a97a1d0a86989cf1452621f2dc5'
PREVIOUS_RENDERER = '807c4384ef28f4da51d3c50eec5082627cad36ea'
EXECUTABLE = 'fa3e74b7f332fef0f212e954a0de18f685ead8bd'
SOURCE_DIFF = '182c4df27c204cb3e3a10333cabff2a8c8f70ef7ca0bcf4f174ce676ad850547'
LOADER_DIFF = '6eba8647520043e4c322170fd889b4b6154d78e6e9c77397e906967cedc3fd26'
DESCRIPTOR = 'renderer-compatibility.json'
BASE = 'client-runtime/'
LOADER_FILES = {
    'Engine/Source/Gx/CGxDeviceVulkan/Vulkan/Loader.cpp',
    'Engine/Source/Gx/CGxDeviceVulkan/Vulkan/Loader.hpp',
    'Tools/VulkanTests/texture_device.cpp',
}
REVIEWED_FILES = LOADER_FILES | {
    'Engine/Source/Gx/CGxDeviceVulkan/Vulkan/Texture.cpp',
    'Engine/Source/Gx/CGxDeviceVulkan/CGxDeviceVulkanTexture.cpp',
    '.github/workflows/arm64-client.yml', 'Tools/RuntimeManifest/reuse_stock_xvid.py',
    'Tools/VulkanTests/CMakeLists.txt', 'Tools/VulkanTests/compressed_clear.cpp',
}
HELPERS = ('fetch_sources', 'prepare_runtime', 'provider_client_runtime', 'package_client_sources',
           'package_server_content', 'manifest_server_content', 'manifest_server_modules', 'verify_server_build')
REVISIONS = {'preparedClientRevision', 'executableRevision'}
HASHES = {'preparedSourceLockSha256', 'previousClientArchiveSha256', 'previousExecutableSha256',
          'executableSourceLockSha256', 'sourceDiffSha256', 'clientArchiveSha256', 'executableSha256',
          'requiredWineArchiveSha256', 'shaderToolsArchiveSha256', 'shaderToolManifestSha256'}
require = client.require


def record(path):
    return json.loads(client.small(path))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def descriptor(path):
    raw = client.small(path)
    item = json.loads(raw)
    require(raw == client.encoded(item) and set(item) == HASHES | REVISIONS | {'formatVersion', 'scope'} and
            type(item['formatVersion']) is int and item['formatVersion'] == 1 and
            item['scope'] == 'stock-renderer-only', 'renderer-descriptor-schema')
    require(all(isinstance(item[k], str) and re.fullmatch('[0-9a-f]{64}', item[k]) for k in HASHES) and
            all(isinstance(item[k], str) and re.fullmatch('[0-9a-f]{40}', item[k]) for k in REVISIONS) and
            item['preparedClientRevision'] == STOCK and item['executableRevision'] == EXECUTABLE and item['sourceDiffSha256'] == SOURCE_DIFF and
            item['previousExecutableSha256'] != item['executableSha256'] and
            item['previousClientArchiveSha256'] != item['clientArchiveSha256'], 'renderer-descriptor-identities')
    return item


def changed_files(source, old, new, reviewed_files):
    git = ['git', '-C', str(source)]
    subprocess.run([*git, 'merge-base', '--is-ancestor', old, new], check=True)
    diff = [*git, '-c', 'diff.noprefix=false', '-c', 'diff.mnemonicPrefix=false', 'diff',
            '--no-color', '--no-ext-diff', '--no-textconv', '--no-renames', '--src-prefix=a/', '--dst-prefix=b/']
    paths = set(subprocess.check_output([*diff, '--name-only', '-z', old, new, '--']).decode().rstrip('\0').split('\0'))
    require(paths == reviewed_files, 'renderer-diff-paths')
    delta = subprocess.check_output([*diff, '--binary', '--full-index', old, new, '--'])
    require(0 < len(delta) <= 2 << 20, 'renderer-diff-size')
    return digest(delta)


def selected(source, source_lock, input_lock):
    prepared = record(client.SOURCE_LOCK)
    lock = client.fetch_sources.load_lock(source_lock)
    measured = record(input_lock)
    revision = measured['sourceRevision']
    require(prepared['sources']['client']['commit'] == STOCK and isinstance(revision, str) and
            revision == EXECUTABLE, 'renderer-source-revisions')
    expected = json.loads(json.dumps(prepared))
    expected['sources']['client'].update(commit=revision, branch='non-custom')
    require(client.encoded(lock) == client.encoded(expected), 'renderer-must-preserve-server-layout-and-client-origin')
    require(set(measured) == set(record(client.PIN)) and type(measured['formatVersion']) is int and
            measured['formatVersion'] == 1 and measured['scope'] == 'measured-reconstructed-client-provider-inputs'
            and measured['androidRuntimeQualified'] is False and
            all(type(measured[k]) is int and measured[k] > 0 for k in ('workflowRun', 'artifactId')) and
            re.fullmatch(str(measured['workflowRun']) + r'\.[1-9][0-9]*', measured['buildId']) and
            re.fullmatch('[a-f0-9]{64}', measured['buildManifestSha256']) and
            set(measured['artifact']) == {'sha256', 'bytes'}, 'renderer-measured-pin')
    client.archives.pin_identity(dict(measured['artifact'], file='client.zip'))
    require(22 <= measured['artifact']['bytes'] <= 512 << 20, 'renderer-artifact-size-limit')
    client.fetch_sources.verify_checkout(source, lock['sources']['client'], [])
    require(changed_files(source, PREVIOUS_RENDERER, revision, LOADER_FILES) == LOADER_DIFF,
            'renderer-reviewed-loader-diff')
    source_diff = changed_files(source, STOCK, revision, REVIEWED_FILES)
    require(source_diff == SOURCE_DIFF, 'renderer-reviewed-source-diff')
    return measured, source_diff


def stage_recipe(root, source_lock, input_lock):
    # The frozen tools use canonical input paths. Supply exactly those paths in a
    # disposable recipe tree so historic direct invocations remain reproducible.
    selections = {client.SOURCE_LOCK: source_lock, client.PIN: input_lock,
                  client.archives.DEFAULT_LOCK: client.archives.DEFAULT_LOCK, ROOT / 'LICENSE': ROOT / 'LICENSE'}
    selections.update({ROOT/'tools'/(name+'.py'): ROOT/'tools'/(name+'.py') for name in HELPERS})
    for original, chosen in selections.items():
        path = root / original.relative_to(ROOT)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(client.small(chosen))


def source_package(source, source_lock, input_lock, xvid, output):
    selected(source, source_lock, input_lock)
    with tempfile.TemporaryDirectory(prefix='renderer-source-') as temporary:
        root = Path(temporary)
        stage_recipe(root, source_lock, input_lock)
        subprocess.run([sys.executable, '-B', root/'tools/package_client_sources.py', '--client-source', source,
                        '--xvid-source', xvid, '--runtime-lock', root/'runtime/runtime-sources.lock.json',
                        '--output', output], check=True, stdout=subprocess.DEVNULL)


def donor(inputs):
    pins = record(ROOT/'runtime/wine-cohort-publication/dependency-release.lock.json')['files']
    receipt = inputs/'provider-assets-receipt.json'
    client.verify_identity(receipt, pins[receipt.name])
    members = record(receipt)['members']
    keys = {BASE + 'provider.json', 'shader-tools/provider.json'}
    values = {}
    # Only two authenticated metadata members are needed. The complete historical
    # release has an independent verifier before its providers reach this stage.
    limits = dict(entries=len(members), fileBytes=sum(p['bytes'] for p in members.values()), pathBytes=4096)
    with client.archives.plain_file(inputs/'provider-assets.tar.gz') as raw, client.archives.bounded_tar(raw, limits) as tar:
        for item in tar:
            if item.name in keys:
                pin = members[item.name]
                require(item.isfile() and item.size == pin['bytes'] <= client.META_LIMIT and
                        item.name not in values, 'renderer-donor-metadata-member')
                with tar.extractfile(item) as stream:
                    data = stream.read(item.size)
                require(digest(data) == pin['sha256'], 'renderer-donor-metadata-hash')
                values[item.name] = json.loads(data)
            tar.members.clear()
    require(set(values) == keys, 'renderer-donor-metadata-missing')
    source_receipt = inputs/'client-source-receipt.json'
    client.verify_identity(source_receipt, pins[source_receipt.name])
    return members, values[BASE+'provider.json'], values['shader-tools/provider.json'], record(source_receipt)


def verify_sources(package, source, source_lock, input_lock, pin, original):
    receipt = record(package/'source-receipt.json')
    archive = package/'client-corresponding-source.tar.gz'
    require(receipt['source'] == record(source_lock)['sources']['client'] and
            receipt['sourceLockSha256'] == client.identity(source_lock)['sha256'] and
            receipt['inputLockSha256'] == client.identity(input_lock)['sha256'] and
            receipt['clientArtifact'] == pin['artifact'] and receipt['clientBuildId'] == pin['buildId'] and
            receipt['archiveReadBack'] is True and receipt['scope'] == 'retained-reconstructed-client-source-inputs' and
            receipt['androidRuntimeQualified'] is False and receipt['gameplayQualified'] is False and
            receipt['xvid'] == original['xvid'], 'renderer-source-companion-selection')
    members = receipt['members']
    require(set(members) == set(original['members']) and members['README.txt'] == original['members']['README.txt'] and
            members['xvidcore-1.3.7.tar.gz'] ==
            original['members']['xvidcore-1.3.7.tar.gz'], 'renderer-source-companion-roster')
    for filename, where in [('sources.lock.json', source_lock), ('runtime/client/android-provider.lock.json', input_lock),
                            (client.RUNTIME_INPUT, client.archives.DEFAULT_LOCK)]:
        require(members['integration-recipe/'+filename] == client.identity(where), 'renderer-source-companion-lock')
    for name, expected in members.items():
        if name.startswith('integration-recipe/tools/') or name == 'integration-recipe/LICENSE':
            require(expected == client.identity(ROOT/name.removeprefix('integration-recipe/')),
                    'renderer-source-companion-recipe')
    with subprocess.Popen(['git', '-C', str(source), 'archive', '--format=tar', pin['sourceRevision']],
                          stdout=subprocess.PIPE) as proc:
        tree = members['client-source.tar']
        require(0 < tree['bytes'] <= 256 << 20 and
                client.archives.hash_stream(proc.stdout, tree['bytes']) == tree['sha256'] and
                not proc.stdout.read(1) and proc.wait() == 0, 'renderer-source-tree-mismatch')
    client.verify_identity(archive, receipt['archive'])
    client.audit(archive, members)


def build_provider(source, artifact, source_lock, input_lock, work):
    recipe = work/'recipe'
    stage_recipe(recipe, source_lock, input_lock)
    output = work/'provider'
    subprocess.run([sys.executable, '-B', recipe/'tools/provider_client_runtime.py', 'build',
                    '--client-source', source, '--artifact', artifact, '--provider', output,
                    '--runtime-lock', recipe/'runtime/runtime-sources.lock.json'],
                   stdout=subprocess.DEVNULL, check=True)
    return output


def issue(members, old, shader, new, source_diff):
    require(old['sourceRevision'] == STOCK == shader['clientRevision'] and
            old['sourceLockSha256'] == client.identity(client.SOURCE_LOCK)['sha256'] and
            old['archive']['sha256'] == members[BASE+client.ARCHIVE]['sha256'] and
            shader['archive']['sha256'] == members['shader-tools/shader-tools-arm64.archive']['sha256'],
            'renderer-donor-provider-selection')
    for key in ('protocol', 'capabilities', 'requiredWineRuntime', 'requiredWineArchiveSha256', 'selectedInputs'):
        require(client.encoded(new[key]) == client.encoded(old[key]), 'renderer-provider-contract-mismatch:'+key)
    before, after = old['requiredFiles'], new['requiredFiles']
    changing = {'bin/WowClient64.exe', 'metadata/client-build.json', 'metadata/sources.lock.json', client.MARKER}
    require(set(before) == set(after), 'renderer-provider-members-changed')
    for name in before.keys() - changing:
        require(before[name] == after[name], 'renderer-provider-bytes-changed:'+name)
    return dict(formatVersion=1, scope='stock-renderer-only', preparedClientRevision=old['sourceRevision'],
                preparedSourceLockSha256=old['sourceLockSha256'], previousClientArchiveSha256=old['archive']['sha256'],
                previousExecutableSha256=before['bin/WowClient64.exe']['sha256'], executableRevision=new['sourceRevision'],
                executableSourceLockSha256=new['sourceLockSha256'], sourceDiffSha256=source_diff,
                clientArchiveSha256=new['archive']['sha256'], executableSha256=after['bin/WowClient64.exe']['sha256'],
                requiredWineArchiveSha256=old['requiredWineArchiveSha256'], shaderToolsArchiveSha256=shader['archive']['sha256'],
                shaderToolManifestSha256=shader['toolManifestSha256'])


def apk_members(cohort_members, compatibility_path, provider_dir):
    """Compose the checked client subtree with already authenticated cohort members."""
    expected = descriptor(compatibility_path)
    assets = client.archives.directory(provider_dir/client.ASSETS)
    names = {client.ARCHIVE, 'provider.json', 'NOTICE.txt', DESCRIPTOR}
    require({v.name for v in assets.iterdir()} == names, 'renderer-provider-file-set')
    require(client.small(assets/DESCRIPTOR) == client.small(compatibility_path), 'renderer-provider-descriptor-mismatch')
    source = record(assets/'provider.json')
    previous = {k for k in cohort_members if k.startswith(BASE)}
    require(previous == {BASE+n for n in names - {DESCRIPTOR}} and
            cohort_members[BASE+client.ARCHIVE]['sha256'] == expected['previousClientArchiveSha256'] and
            cohort_members['shader-tools/shader-tools-arm64.archive']['sha256'] == expected['shaderToolsArchiveSha256'],
            'renderer-apk-donor-mismatch')
    require(source['sourceRevision'] == expected['executableRevision'] and
            source['sourceLockSha256'] == expected['executableSourceLockSha256'] and
            source['archive']['sha256'] == expected['clientArchiveSha256'] and
            source['requiredFiles']['bin/WowClient64.exe']['sha256'] == expected['executableSha256'] and
            source['requiredWineArchiveSha256'] == expected['requiredWineArchiveSha256'],
            'renderer-apk-provider-identity')
    replacements = {BASE+n: client.identity(assets/n) for n in names}
    require(replacements[BASE+'NOTICE.txt'] == cohort_members[BASE+'NOTICE.txt'] and
            replacements[BASE+client.ARCHIVE] == {k:source['archive'][k] for k in ('bytes','sha256')},
            'renderer-apk-archive-or-notice')
    return {**cohort_members, **replacements}


def run(args):
    if args.command == 'source':
        source_package(args.client_source, args.source_lock, args.client_input_lock, args.xvid_source, args.source_package)
        return
    measured, source_diff = selected(args.client_source, args.source_lock, args.client_input_lock)
    members, old, shader, original = donor(args.cohort_inputs)
    verify_sources(args.source_package, args.client_source, args.source_lock, args.client_input_lock, measured, original)
    out = args.provider.absolute()
    client.archives.directory(out.parent, create=True)
    require(args.command == 'verify' or not os.path.lexists(out), 'renderer-provider-output-exists')
    with tempfile.TemporaryDirectory(prefix='.renderer-', dir=out.parent) as stage:
        provider = build_provider(args.client_source, args.artifact, args.source_lock, args.client_input_lock, Path(stage))
        assets = provider/client.ASSETS
        issued = issue(members, old, shader, record(assets/'provider.json'), source_diff)
        compatibility = assets/DESCRIPTOR
        compatibility.write_bytes(client.encoded(issued))
        descriptor(compatibility)
        if args.command != 'measure':
            require(client.small(args.compatibility) == client.small(compatibility), 'renderer-reviewed-descriptor-mismatch')
        produced = apk_members(members, compatibility, provider)
        if args.command == 'verify':
            require(produced == apk_members(members, compatibility, out), 'renderer-provider-rebuild-mismatch')
        else:
            client.publish_directory(provider, out)
            client.archives.sync_directory(out.parent)
        print(client.encoded(issued).decode(), end='')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('source', 'measure', 'build', 'verify'):
        cmd = commands.add_parser(name)
        for option in ('client-source', 'source-lock', 'client-input-lock', 'source-package'):
            cmd.add_argument('--'+option, type=Path, required=True)
        if name == 'source':
            cmd.add_argument('--xvid-source', type=Path, required=True)
        else:
            for option in ('artifact', 'cohort-inputs', 'provider'):
                cmd.add_argument('--'+option, type=Path, required=True)
            if name != 'measure':
                cmd.add_argument('--compatibility', type=Path, required=True)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
