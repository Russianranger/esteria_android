#!/usr/bin/env python3
"""Measure a source-bound Android x64 installation fixture, without executing it.

The native SQL gate must already be independently qualified.  This builder does
not enable the Android gate: its descriptor is measured first, then a separate
readback and exact descriptor pin must be committed before APK packaging.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import importlib.util
import re
import subprocess
import sys
import tarfile
import tempfile

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import android_installation_x64_inputs as gate
from tools import qualify_server_setup_x64_sql as sql
from tools import fetch_android_mysql_fixture as mysql
from tools import package_server_engine as engine
from tools import package_server_engine_notices as notices

ROOT = Path(__file__).resolve().parents[1]
SCOPE = 'android-x86-64-server-installation-probe-only'
PREFIX = 'assets/installation-probe'
GUEST = '/esteria-server-programs'
HELPERS = ('android_server_installation_setup.py', 'android_server_schema_setup.py',
    'mysql_bootstrap.py', 'mysql_service.py', 'server_content.py', 'server_schema_setup.py',
    'server_schema_baseline.py', 'server_schema_adaptations.py', 'server_update_setup.py',
    'server_updater.py', 'server_playerbots_setup.py', 'owned_process_group.py', 'server_config.py',
    'provision_local_realm.py', 'provision_local_account.py', 'server/appearance-schema-v1.sql',
    'server/appearance-schema.lock.json', 'local-server.json', 'installation_x64_entry.py')
GENERATED_HELPER = 'installation-x64-inputs.json'
ROLES = {'dbimport': ('bin/dbimport', 'bin/dbimport.elf'),
    'playerbots-schema': ('helpers/playerbots-schema', 'helpers/playerbots-schema.elf')}
ORIGINALS = {'metadata/server-build.json': 'provenance/server-build.json',
    'metadata/server-modules.json': 'provenance/server-modules.json',
    'integration/sources.lock.json': 'provenance/sources.lock.json',
    sql.TEMPLATE: 'etc/dbimport.conf.dist'}
require = gate.require
native = gate.native
files = native.files
encode = sql.encode


def identity_bytes(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def copy(source, target, pin, mode=0o444):
    engine.copy_verified(source, target, native.identity(pin), mode)


def write_archive(root, output):
    """Stream deterministic regular files; preserve explicit executable roles."""
    inventory = {}; total = 0
    with output.open('xb') as raw:
        with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as archive:
                for source in files.installed_files(root):
                    name = source.relative_to(root).as_posix(); engine.content.safe_path(name)
                    row = files.identity(source); row['mode'] = 0o555 if source.stat().st_mode & 0o111 else 0o444
                    total += row['bytes']; require(total <= 2 << 30, 'installation-x64-programs-payload-bound')
                    member = tarfile.TarInfo(name); member.size = row['bytes']; member.mode = row['mode']
                    member.uid = member.gid = member.mtime = 0; member.uname = member.gname = ''
                    with files.plain_file(source) as stream:
                        checked = engine.package.HashReader(stream, row); archive.addfile(member, checked); checked.finish()
                    inventory[name] = row
        raw.flush(); os.fsync(raw.fileno())
    require(1 <= len(inventory) <= 512, 'installation-x64-programs-inventory-bound')
    engine.verify_archive(output, inventory)
    return inventory


def original_metadata(payload, build, output, *, source_notices=False):
    """Read the original archived recipe, including its metadata, without Git."""
    source = payload / 'corresponding-source/source-inputs'
    receipt = native.small(source / 'source-inputs-receipt.json', 8 << 20)
    archive = source / 'server-engine-source-inputs.tar.gz'; native.pinned(archive, receipt['archive'])
    selected = receipt['archiveFiles']; seen = set(); wanted = dict(ORIGINALS)
    if source_notices:
        audit, _ = notices.load_audit()
        for row in audit['noticeCandidates']:
            name = 'source/' + row['path']; pin = native.identity(selected.get(name), 16 << 20)
            require(pin['bytes'] == row['bytes'] and selected[name].get('gitBlob') == row['gitBlobSha1'],
                'installation-x64-original-license-source-binding')
            wanted[name] = 'notices/source/' + row['path']
        wanted[notices.LUA_PATH] = 'notices/lua-source-archive.tar.gz'
    for name in wanted: native.identity(selected.get(name), 16 << 20)
    with files.plain_file(archive) as raw, native.archives.bounded_tar(raw,
            dict(entries=10000, pathBytes=4096, fileBytes=256 << 20)) as bundle:
        for member in bundle:
            if member.name in wanted:
                expected = native.identity(selected[member.name], 16 << 20)
                require(member.name not in seen and member.isfile() and member.size == expected['bytes'],
                    'installation-x64-original-metadata-member')
                target = output / wanted[member.name]; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with bundle.extractfile(member) as incoming, target.open('xb') as outgoing:
                    require(native.archives.hash_stream(incoming, member.size, outgoing) == expected['sha256'],
                        'installation-x64-original-metadata-changed')
                    outgoing.flush(); os.fsync(outgoing.fileno())
                target.chmod(0o444); seen.add(member.name)
            bundle.members.clear()
    require(seen == set(wanted), 'installation-x64-original-metadata-missing')
    if source_notices:
        lua = output / 'notices/lua-source-archive.tar.gz'
        raw = notices.lua_notice(gate._raw(lua, 16 << 20))
        target = output / 'notices/LUA-README.html'; target.write_bytes(raw); target.chmod(0o444)
        lua.unlink()  # Full original archive remains in the complete source companion.
    for name, expected in (('server-build.json', build['originalArm64Build']),
            ('server-modules.json', build['originalArm64Modules']), ('sources.lock.json', build['sourceLock'])):
        native.pinned(output / 'provenance' / name, expected)


def guest_entry():
    path = ROOT / 'tests/android-installation-x64/installation_x64_entry.py'
    spec = importlib.util.spec_from_file_location('installation_x64_source_entry', path)
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
    return module


def invocations(payload, build, output, native_sql):
    libraries = build['libraries']; loader_name = 'lib64/ld-linux-x86-64.so.2'
    require(loader_name in libraries and all(row['elf']['machine'] == 62 for row in libraries.values()),
        'installation-x64-captured-elf62-closure-required')
    loader = 'libexec/ld-linux-x86-64.so.2'
    for name, row in libraries.items():
        engine.content.safe_path(name); copy(payload / 'libraries' / name, output / 'libraries' / name, row)
    copy(payload / 'libraries' / loader_name, output / loader, libraries[loader_name], 0o555)
    result = {}
    for role, (script, actual) in ROLES.items():
        original = build['executables'][role]
        require(original['elf']['machine'] == 62, 'installation-x64-original-elf62-required')
        copy(payload / 'bin' / role, output / actual, original, 0o555)
        raw = guest_entry().invocation_source(build, role)
        require(identity_bytes(raw) != native_sql['checkedInvocations'][role]['invocation'],
            'installation-x64-native-invocation-must-have-separate-identity')
        target = output / script; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(raw); target.chmod(0o555)
        result[role] = dict(actualPath=actual, actualExecutable=native.identity(original),
            invocationPath=script, invocation=identity_bytes(raw))
    return result


def source_snapshot():
    """Bind the new recipe separately from old runtime and native producers."""
    def git(*arguments):
        return subprocess.check_output(['git', '-C', str(ROOT), *arguments], stderr=subprocess.DEVNULL)
    require(not git('status', '--porcelain', '--untracked-files=normal').strip(),
        'installation-x64-clean-packaging-recipe-required')
    commit = git('rev-parse', 'HEAD').decode().strip()
    names = recipe_names()
    for name in names:
        require(git('show', commit + ':' + name) == gate._raw(ROOT / name, 2 << 20),
            'installation-x64-packaging-source-differs-from-git')
    return dict(repository='Russianranger/esteria_android', commit=commit,
        files={name: files.identity(ROOT / name) for name in sorted(names)})


def recipe_names():
    names = ['tools/provider_android_installation_x64.py', 'tools/android_installation_x64_inputs.py',
        'tests/android-installation-x64/installation_x64_entry.py', 'tests/native-java-installation/restart_probe.py',
        'config/local-server.json']
    names += ['runtime/' + name for name in HELPERS if name not in ('local-server.json', 'installation_x64_entry.py')]
    names += [path.relative_to(ROOT).as_posix() for path in (ROOT/'core/src/main/java').rglob('*.java')]
    names += ['app/src/main/java/io/github/russianranger/esteria/runtime/'+name+'.java' for name in
        ('ServerRuntimeSetup','ServerProgramsSetup','ServerContentSetup','ServerSourceSelection','GuestHelperAssets',
        'ServerDatabaseSetup','ServerDatabaseService','ServerInstallationSetup','ProotProcess','NativeProcessBridge')]
    names += ['app/src/androidTest/java/io/github/russianranger/esteria/runtime/'+name+'.java' for name in
        ('InstallationX64Inputs','InstallationX64Lifetime','ServerInstallationX64Test')]
    names += ['native/process-owner/'+name for name in
        ('process_owner.cpp','process_usage.cpp','jni_bridge.cpp','process_owner.h','process_usage.h')]
    names += ['app/server-installation-probe.gradle']
    return sorted(names)


def verify_recipe(recipe, companion):
    require(type(recipe) is dict and set(recipe) == {'repository','commit','files'} and
        recipe['repository']=='Russianranger/esteria_android' and type(recipe['commit']) is str and
        re.fullmatch('[a-f0-9]{40}',recipe['commit']) and type(recipe['files']) is dict and
        set(recipe['files'])==set(recipe_names()),'installation-x64-source-recipe-schema')
    for name,row in recipe['files'].items():
        engine.content.safe_path(name);native.pinned(companion/name,row,2<<20)
        original=subprocess.check_output(['git','-C',str(ROOT),'show',recipe['commit']+':'+name],stderr=subprocess.DEVNULL)
        require(identity_bytes(original)==native.identity(row,2<<20),
            'installation-x64-source-recipe-differs-from-git')


def require_current_code(recipe):
    """Activation Q may change pins, while executable source remains exact P.

    Compare source bytes, not whole commits or the changing selection lock. The
    eventual Android receipt independently records its actual current revision.
    """
    require(type(recipe) is dict and type(recipe.get('files')) is dict and
        set(recipe['files'])==set(recipe_names()),'installation-x64-current-consumer-source-set-differs')
    for name,row in recipe['files'].items():
        native.pinned(ROOT/name,row,2<<20)


def verify_helpers(provider, descriptor):
    recipe=descriptor['currentPackagingRecipe']['files']; rows=descriptor['helpers']
    require(type(rows) is dict and set(rows)==set(HELPERS)|{GENERATED_HELPER},
        'installation-x64-source-helper-set-differs')
    root=provider/'assets/installation-probe-helpers'
    for name in HELPERS:
        source=('config/local-server.json' if name=='local-server.json' else
            'tests/android-installation-x64/'+name if name=='installation_x64_entry.py' else 'runtime/'+name)
        require(rows[name]==recipe[source], 'installation-x64-packaged-helper-differs-from-original-source')
        native.pinned(root/name,rows[name])
    generated=gate.small(root/GENERATED_HELPER,16384)
    require(type(generated) is dict and set(generated)=={'formatVersion','scope','closure'} and
        type(generated['formatVersion']) is int and generated['formatVersion']==1 and
        generated['scope']=='android-x64-installation-fixed-inputs',
        'installation-x64-generated-helper-inputs-differ')
    programs=gate.small(provider/PREFIX/'programs.json',2<<20)
    require(generated['closure']==programs['closure'] and generated['closure']==
        native.identity(programs['requiredFiles']['provenance/x64-closure.json']),
        'installation-x64-generated-helper-closure-differs')
    native.pinned(root/GENERATED_HELPER,rows[GENERATED_HELPER])
    require(gate.small(root/'manifest.json',16384)==dict(formatVersion=1,files=rows),
        'installation-x64-source-helper-manifest-differs')
    native.pinned(provider/PREFIX/'restart_probe.py',recipe['tests/native-java-installation/restart_probe.py'])


def helpers(output, closure):
    root = output / 'assets/installation-probe-helpers'; rows = {}
    for name in HELPERS:
        source = ROOT / ('config/local-server.json' if name == 'local-server.json' else
            'tests/android-installation-x64/' + name if name == 'installation_x64_entry.py' else 'runtime/' + name)
        row = files.identity(source); copy(source, root / name, row); rows[name] = row
    engine.put_metadata(root / GENERATED_HELPER, dict(formatVersion=1,
        scope='android-x64-installation-fixed-inputs', closure=closure))
    rows[GENERATED_HELPER] = files.identity(root / GENERATED_HELPER)
    engine.put_metadata(root / 'manifest.json', dict(formatVersion=1, files=rows))
    return rows


def programs_tree(payload, build_receipt, native_pin, selected, qualification, programs):
    """Derive the closed runtime from actual admitted sources, never its claims."""
    programs.mkdir(mode=0o700)
    original_metadata(payload, build_receipt, programs, source_notices=True)
    invoked = invocations(payload, build_receipt, programs, qualification)
    copy(payload / 'build-receipt.json', programs / 'provenance/playerbots-helper-build.json', native_pin['build']['buildReceipt'])
    copy(ROOT / selected['nativeSql']['qualification']['path'], programs / 'provenance/playerbots-native-sql.json', selected['nativeSql']['qualification'])
    for name, row in build_receipt['libraryNotices'].items():
        copy(payload / 'notices' / name / 'copyright', programs / 'notices' / name / 'copyright', row)
    closure = dict(formatVersion=1, scope='android-x64-original-setup-elf-closure',
        buildReceipt=native_pin['build']['buildReceipt'], nativeBuildSourceReadback=native_pin['build']['librarySourceReadback'],
        buildProducer=native_pin['build']['producer'], nativeSqlReceipt=native.identity(selected['nativeSql']['qualification']),
        nativeInputSelection=native.identity(selected['nativeSql']['inputSelection']), executables=invoked,
        libraries={name: native.identity(row) for name,row in build_receipt['libraries'].items()},
        loader=dict(path='libexec/ld-linux-x86-64.so.2', **native.identity(build_receipt['libraries']['lib64/ld-linux-x86-64.so.2'])),
        sourceOrigin=dict(originalBuild=build_receipt['originalArm64Build'],compiledModules=build_receipt['originalArm64Modules'],
            sourceLock=build_receipt['sourceLock'],source=qualification['source']),
        originalElfBytesChanged=False,nativeInvocationScriptsReused=False,androidRuntimeQualified=False)
    engine.put_metadata(programs/'provenance/x64-closure.json',closure)
    return closure


def programs_descriptor(programs, archive):
    inventory=write_archive(programs,archive)
    for name,row in inventory.items():
        if name.startswith(('libraries/','libexec/')) or name.endswith('.elf'): row['elfMachine']=62
    return dict(formatVersion=1,scope='android-x64-installation-programs-only',packageKey='installation-tools-x86-64',
        archive=files.identity(archive),archiveFile='programs.archive',archiveEntries=len(inventory),
        archiveFileBytes=sum(row['bytes'] for row in inventory.values()),
        limits=dict(entries=4096,memberBytes=1<<30,fileBytes=2<<30,pathBytes=4096,metadataBytes=32<<20),
        requiredFiles=inventory,closure=files.identity(programs/'provenance/x64-closure.json'))


def full_source_companion(inputs, component, output, recipe):
    """Retain original ELF/debug/source bytes outside the APK, then read them all."""
    output.mkdir(mode=0o700); rows = {}
    for source in files.installed_files(component):
        name = 'x64-component/' + source.relative_to(component).as_posix()
        row = files.identity(source); copy(source, output / name, row); rows[name] = row
    # Restore/recheck every original MySQL/proot source ZIP member using the
    # original explicit pin, never the current-source consumer's strict guard.
    frozen = gate.frozen_mysql.input_selection()
    # Retain the exact original ZIP rather than an unbound second copy of its
    # recipe members. Independent readback can repeat every ZIP CRC/hash and
    # package-source check against its original external measured identity.
    with tempfile.TemporaryDirectory(prefix='esteria-installation-original-sources-',dir=output.parent) as temporary:
        source_readback = mysql.restore_sources(inputs / 'mysql/completeSources.zip',Path(temporary)/'source',
            frozen,inputs/'mysql')
    copy(inputs/'mysql/completeSources.zip',output/'original-mysql-proot-completeSources.zip',frozen['artifacts']['completeSources'])
    for name in ('provider.json', 'runtime.json', 'sources.lock.json'):
        source = inputs / 'mysql/provider/assets/mysql-probe' / name
        copy(source, output / 'original-mysql-metadata' / name, files.identity(source))
    copy(inputs/'mysql/SOURCE-MANIFEST.json',output/'original-mysql-metadata/SOURCE-MANIFEST.json',frozen['files']['SOURCE-MANIFEST.json'])
    for source in files.installed_files(inputs/'mysql/proot-provider'):
        copy(source,output/'original-proot-provider'/source.relative_to(inputs/'mysql/proot-provider'),files.identity(source),
            0o555 if 'jniLibs' in source.parts else 0o444)
    for name in recipe['files']:
        copy(ROOT / name, output / 'packaging-recipe' / name, recipe['files'][name])
    for source in files.installed_files(output): rows[source.relative_to(output).as_posix()] = files.identity(source)
    engine.put_metadata(output / 'SOURCE-MANIFEST.json', dict(formatVersion=1,
        scope='android-x64-installation-complete-original-source-debug-and-new-recipe',
        files=rows, fileBytes=sum(row['bytes'] for row in rows.values()),
        originalMysqlProotSourceReadback=source_readback, currentPackagingRecipe=recipe,
        **{name: False for name in gate.FALSE_FLAGS}))
    return files.identity(output / 'SOURCE-MANIFEST.json')


def original_mysql_source_readback(companion,frozen,recorded):
    archive=companion/'original-mysql-proot-completeSources.zip'
    native.pinned(archive,frozen['artifacts']['completeSources'])
    metadata=companion/'original-mysql-metadata'
    with tempfile.TemporaryDirectory(prefix='esteria-installation-source-reread-') as temporary:
        temporary=Path(temporary);inputs=temporary/'inputs'
        for name in ('provider.json','runtime.json','sources.lock.json'):
            row=frozen['files']['provider/assets/mysql-probe/'+name]
            copy(metadata/name,inputs/'provider/assets/mysql-probe'/name,row)
        copy(metadata/'SOURCE-MANIFEST.json',inputs/'SOURCE-MANIFEST.json',frozen['files']['SOURCE-MANIFEST.json'])
        actual=mysql.restore_sources(archive,temporary/'source',frozen,inputs)
        require(actual==recorded,'installation-x64-original-source-zip-members-differ')
    return actual


def verify(output, expected=None):
    output = native.archives.directory(output)
    path = output / PREFIX / 'provider.json'; raw = gate._raw(path, 128 << 10)
    if expected is not None: require(identity_bytes(raw) == gate.identity(expected, 128 << 10),
        'installation-x64-independent-provider-pin-differs')
    descriptor = json.loads(raw, object_pairs_hook=gate._unique)
    require(descriptor.get('formatVersion') == 1 and descriptor.get('scope') == SCOPE and
        type(descriptor.get('packagedFiles')) is dict and 1 <= len(descriptor['packagedFiles']) <= 64 and
        all(descriptor.get(name) is False for name in gate.FALSE_FLAGS), 'installation-x64-provider-schema')
    selected = descriptor['packagedFiles']; actual = {p.relative_to(output).as_posix() for p in files.installed_files(output)}
    require(actual == set(selected) | {PREFIX + '/provider.json'}, 'installation-x64-provider-file-closure')
    for name, row in selected.items():
        engine.content.safe_path(name)
        require(name.startswith((PREFIX + '/', 'assets/installation-probe-helpers/')) and name != PREFIX + '/provider.json',
            'installation-x64-provider-file-path')
        native.pinned(output / name, row)
    programs = gate.small(output / PREFIX / 'programs.json', 2 << 20)
    engine.verify_archive(output / PREFIX / 'programs.archive', programs['requiredFiles'])
    require(programs['archive'] == files.identity(output / PREFIX / 'programs.archive'),
        'installation-x64-programs-archive-binding')
    require(descriptor['nativeSqlReceipt'] == selected[PREFIX + '/native-sql-qualification.json'] and
        descriptor['programsDescriptor'] == selected[PREFIX + '/programs.json'] and
        descriptor['contentDescriptor'] == selected[PREFIX + '/content-provider.json'],
        'installation-x64-provider-descriptor-bindings')
    verify_helpers(output,descriptor)
    return descriptor


def verify_external(provider, frozen_source, mysql_provider, proot_provider):
    """Profile-only old runtime verification, with new caller proof kept apart.

    The unchanged standalone MySQL verifier still checks current sources. This
    explicit profile executes only the already supported exact whole-checkout
    frozen recipe; no caller command or ROOT override is accepted.
    """
    selected=gate.load_pin(require_enabled=True)
    frozen=gate.frozen_mysql.inspect(frozen_source)
    frozen_source=native.archives.directory(Path(os.path.abspath(frozen_source)))
    provider=native.archives.directory(provider);mysql_provider=native.archives.directory(mysql_provider)
    proot_provider=native.archives.directory(proot_provider)
    descriptor=verify(provider,selected['provider'])
    require_current_code(descriptor['currentPackagingRecipe'])
    native_sql=gate.record(selected['nativeSql']['qualification'])
    require(descriptor['nativeSqlReceipt']==native.identity(selected['nativeSql']['qualification']) and
        descriptor['mysqlProvider']==frozen['originalPin']['files']['provider/assets/mysql-probe/provider.json'],
        'installation-x64-external-runtime-selection-differs')
    original=frozen['originalPin']
    assets=mysql_provider/'assets/mysql-probe'
    require({path.name for path in assets.iterdir()}==mysql.retained.builder.NAMES,
        'installation-x64-external-mysql-file-closure')
    for name in mysql.retained.builder.NAMES:
        native.pinned(assets/name,original['files']['provider/assets/mysql-probe/'+name])
    require(gate.small(assets/'provider.json',128<<10)['expectedMysqlSqlVersion']==native_sql['mysqlVersion'],
        'installation-x64-external-mysql-version-differs')
    command=[sys.executable,'-B','-s','-E',str(frozen_source/'tools/verify_android_mysql_probe.py'),
        '--provider',str(mysql_provider),'--proot-provider',str(proot_provider)]
    with tempfile.TemporaryFile() as stdout,tempfile.TemporaryFile() as stderr:
        result=subprocess.run(command,cwd=frozen_source,env=gate.frozen_mysql._environment(),stdin=subprocess.DEVNULL,
            stdout=stdout,stderr=stderr,timeout=1800)
        require(result.returncode==0 and 0<stdout.tell()<=2<<20 and stderr.tell()<=2<<20,
            'installation-x64-frozen-original-runtime-verification-failed')
        stdout.seek(0);proof=json.load(stdout)
    require(proof.get('providerVerified') is True and proof.get('apkVerified') is False and
        all(proof.get(name) is False for name in ('androidMysqlQualified','productionAdapterQualified','arm64Qualified')),
        'installation-x64-frozen-runtime-must-not-inherit-current-app-qualification')
    require(gate.frozen_mysql.inspect(frozen_source)==frozen,'installation-x64-frozen-source-changed-during-verification')
    return dict(formatVersion=1,scope='new-android-installation-profile-original-runtime-verification-only',
        providerDescriptor=files.identity(provider/PREFIX/'provider.json'),
        nativeSqlReceipt=descriptor['nativeSqlReceipt'],historicalRuntimeProducer=original['producer'],
        historicalConsumerRecipeRevision=gate.frozen_mysql.RECIPE,
        entireFrozenRecipe=frozen['frozenRecipe'],historicalJavaServiceEvidenceAppliesToCurrentCaller=False,
        **{name:False for name in gate.FALSE_FLAGS})


def readback(product):
    """Independently re-read a measured product, never execute its programs.

    This receipt is an input for review/commit, not an automatic permission to
    build an APK.  The descriptor hash stays outside its own bytes.
    """
    selected = gate.load_pin(require_native=True); pin = native.load_pin(require_enabled=True)
    product = native.archives.directory(product); provider = product / 'provider'
    descriptor = verify(provider)
    qualification = gate.record(selected['nativeSql']['qualification'])
    require(descriptor['nativeSqlReceipt'] == native.identity(selected['nativeSql']['qualification']) and
        descriptor['nativeInputSelection'] == native.identity(selected['nativeSql']['inputSelection']),
        'installation-x64-readback-native-selection-differs')
    companion = product / 'corresponding-source'
    native.pinned(companion / 'SOURCE-MANIFEST.json', descriptor['sourceCompanionManifest'])
    manifest = gate.small(companion / 'SOURCE-MANIFEST.json', 8 << 20)
    require(manifest.get('scope') == 'android-x64-installation-complete-original-source-debug-and-new-recipe' and
        manifest.get('currentPackagingRecipe') == descriptor['currentPackagingRecipe'] and
        type(manifest.get('files')) is dict and 1 <= len(manifest['files']) <= 20000,
        'installation-x64-readback-source-manifest-required')
    verify_recipe(descriptor['currentPackagingRecipe'],companion/'packaging-recipe')
    actual = {path.relative_to(companion).as_posix() for path in files.installed_files(companion)}
    require(actual == set(manifest['files']) | {'SOURCE-MANIFEST.json'}, 'installation-x64-readback-source-file-closure')
    for name, row in manifest['files'].items():
        engine.content.safe_path(name); native.pinned(companion / name, row)
    require(sum(row['bytes'] for row in manifest['files'].values()) == manifest['fileBytes'],
        'installation-x64-readback-source-byte-count')
    admitted = native.admit_component(companion / 'x64-component', pin)
    frozen = gate.frozen_mysql.input_selection()
    metadata = companion / 'original-mysql-metadata'
    for name in ('provider.json', 'runtime.json', 'sources.lock.json'):
        native.pinned(metadata / name, frozen['files']['provider/assets/mysql-probe/' + name])
    require(descriptor['mysqlProvider']==frozen['files']['provider/assets/mysql-probe/provider.json'] and
        descriptor['mysqlVersion']==qualification['mysqlVersion'] and
        qualification['originalMysqlArchive']==frozen['files']['provider/assets/mysql-probe/mysql-x86-64.archive'],
        'installation-x64-readback-original-mysql-provider-differs')
    proot_root=companion/'original-proot-provider'
    mysql.retained.verify.proot.verify(proot_root)
    proot_path=proot_root/'assets/proot-probe/build-evidence.json';proot=gate.small(proot_path,128<<10)
    original= native.record(frozen['actualAndroidEvidence'])['actualQualification']['appEvidence']['prootBuildEvidence']
    require(proot==original and descriptor['proot']==dict(buildEvidence=files.identity(proot_path),
        nativeFiles=proot['nativeFiles'],sourceLockSha256=proot['prootSourceLockSha256']),
        'installation-x64-readback-original-proot-provider-differs')
    original_mysql_source_readback(companion,frozen,manifest['originalMysqlProotSourceReadback'])
    programs = gate.small(provider / PREFIX / 'programs.json', 2 << 20)
    # Extract only the already verified closed normalized archive into an owned
    # fresh temporary directory. No executable or SQL is invoked.
    with tempfile.TemporaryDirectory(prefix='esteria-installation-x64-readback-') as temporary:
        temporary=Path(temporary);root=temporary/'actual';root.mkdir(mode=0o700); inventory = programs['requiredFiles']
        programs_tree(companion/'x64-component/payload',admitted['build'],pin,selected,qualification,temporary/'expected')
        expected=programs_descriptor(temporary/'expected',temporary/'expected.archive')
        require(programs==expected,'installation-x64-programs-differ-from-original-source-and-notices')
        content_root=temporary/'content/assets/server-content';content_root.mkdir(parents=True,mode=0o700)
        for source,target in (('content.archive','server-content.archive'),('content-provider.json','provider.json'),
                ('content-receipt.json','package-receipt.json')):
            copy(provider/PREFIX/source,content_root/target,files.identity(provider/PREFIX/source))
        sql.provider.verify(temporary/'content')
        require(files.identity(content_root/'package-receipt.json')==qualification['contentReceipt'],
            'installation-x64-readback-original-content-receipt-differs')
        with files.plain_file(provider / PREFIX / 'programs.archive') as stream, native.archives.bounded_tar(stream,
                dict(entries=4096, pathBytes=4096, fileBytes=2 << 30)) as bundle:
            seen = set()
            for member in bundle:
                engine.content.safe_path(member.name)
                require(member.isfile() and member.name in inventory and member.name not in seen and
                    member.size == inventory[member.name]['bytes'] and member.mode == inventory[member.name]['mode'],
                    'installation-x64-readback-program-member')
                target = root / member.name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with bundle.extractfile(member) as incoming, target.open('xb') as outgoing:
                    require(native.archives.hash_stream(incoming, member.size, outgoing) == inventory[member.name]['sha256'],
                        'installation-x64-readback-program-bytes')
                target.chmod(member.mode); seen.add(member.name); bundle.members.clear()
            require(seen == set(inventory), 'installation-x64-readback-program-closure')
        checked = guest_entry()._admit(root, provider / 'assets/installation-probe-helpers' / GENERATED_HELPER)
        require(checked.build == admitted['build'] and checked.native == qualification,
            'installation-x64-readback-original-build-or-sql-differs')
        for name, row in descriptor['currentPackagingRecipe']['files'].items():
            native.pinned(companion / 'packaging-recipe' / name, row)
    # A readback is bound to exact independently selected native inputs and all
    # bytes. The caller must commit this small receipt plus descriptor pin.
    return dict(formatVersion=1, scope='independent-android-x64-installation-provider-readback',
        providerDescriptor=files.identity(provider / PREFIX / 'provider.json'),
        nativeSqlReceipt=descriptor['nativeSqlReceipt'], nativeInputSelection=descriptor['nativeInputSelection'],
        allPackagedProviderFilesReadBack=True, allProgramElfAndCapturedLibraryBytesReadBack=True,
        fullOriginalSourcesAndPairedDebugReadBack=True, originalElfBytesUnchanged=True,
        invocationScriptsHaveSeparateIdentities=True, sourceCompanionManifest=descriptor['sourceCompanionManifest'],
        **{name: False for name in gate.FALSE_FLAGS})


def build(inputs, output):
    selected = gate.load_pin(require_native=True)  # Refuse pending before any output.
    native_pin = native.load_pin(require_enabled=True)
    qualification = gate.record(selected['nativeSql']['qualification']); gate.validate_native_sql(qualification, native_pin)
    inputs = native.archives.directory(inputs); output = Path(os.path.abspath(output))
    native.archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'installation-x64-existing-output-preserved')
    require(inputs != output and inputs not in output.parents and output not in inputs.parents,
        'installation-x64-input-output-overlap')
    recipe = source_snapshot()
    component = inputs / 'component' / native.COMPONENT
    admitted = native.admit_component(component, native_pin)
    payload = component / 'payload'; build_receipt = admitted['build']
    mysql_descriptor = sql.mysql_descriptor(inputs)
    content = sql.provider.verify(inputs / 'content-provider')
    require(content['providerVerified'] is True, 'installation-x64-content-provider-required')
    with tempfile.TemporaryDirectory(prefix='.' + output.name + '.stage-', dir=output.parent) as temporary:
        stage = Path(temporary); provider = stage / 'provider'; programs = stage / 'programs'
        assets = provider / PREFIX; assets.mkdir(mode=0o700, parents=True)
        programs_tree(payload,build_receipt,native_pin,selected,qualification,programs)
        plan=programs_descriptor(programs,assets/'programs.archive')
        engine.put_metadata(assets / 'programs.json', plan)
        copy(ROOT / selected['nativeSql']['qualification']['path'], assets / 'native-sql-qualification.json', selected['nativeSql']['qualification'])
        observer=ROOT / 'tests/native-java-installation/restart_probe.py'
        copy(observer,assets / 'restart_probe.py',files.identity(observer))
        for source, target in (('provider.json', 'content-provider.json'), ('server-content.archive', 'content.archive'),
                ('package-receipt.json', 'content-receipt.json')):
            path = inputs / 'content-provider/assets/server-content' / source; copy(path, assets / target, files.identity(path))
        helper_rows = helpers(provider, files.identity(programs / 'provenance/x64-closure.json'))
        companion = full_source_companion(inputs, component, stage / 'corresponding-source', recipe)
        proot_path = inputs / 'mysql/proot-provider/assets/proot-probe/build-evidence.json'
        proot = gate.small(proot_path, 128 << 10)
        require(proot.get('scope') == 'android-13-x86_64-proot-glibc-probe-build-only', 'installation-x64-original-proot-proof-required')
        for name, row in proot['nativeFiles'].items(): native.pinned(inputs / 'mysql/proot-provider/jniLibs/x86_64' / name, row)
        descriptor = dict(formatVersion=1, scope=SCOPE, nativeSqlReceipt=files.identity(assets / 'native-sql-qualification.json'),
            nativeInputSelection=native.identity(selected['nativeSql']['inputSelection']),
            programsDescriptor=files.identity(assets / 'programs.json'), contentDescriptor=files.identity(assets / 'content-provider.json'),
            mysqlProvider=files.identity(inputs / 'mysql/provider/assets/mysql-probe/provider.json'),
            mysqlVersion=mysql_descriptor['expectedMysqlSqlVersion'],
            proot=dict(buildEvidence=files.identity(proot_path), nativeFiles=proot['nativeFiles'], sourceLockSha256=proot['prootSourceLockSha256']),
            sourceCompanionManifest=companion, currentPackagingRecipe=recipe, helpers=helper_rows,
            packagedFiles={p.relative_to(provider).as_posix(): files.identity(p) for p in files.installed_files(provider)},
            **{name: False for name in gate.FALSE_FLAGS})
        engine.put_metadata(assets / 'provider.json', descriptor)
        require(files.identity(assets / 'provider.json')['bytes'] <= 128 << 10, 'installation-x64-provider-metadata-bound')
        verify(provider)
        require(source_snapshot() == recipe and gate.load_pin(require_native=True) == selected,
            'installation-x64-selected-inputs-changed-during-measurement')
        # Prepare the entire product before a single no-clobber directory publish.
        product = stage / 'product'; product.mkdir(mode=0o700)
        os.rename(provider, product / 'provider'); os.rename(stage / 'corresponding-source', product / 'corresponding-source')
        engine.put_metadata(product / 'measurement.json', dict(formatVersion=1,
            scope='android-x64-installation-provider-measurement-no-execution', providerDescriptor=files.identity(product / 'provider' / PREFIX / 'provider.json'),
            nativeSqlReceipt=descriptor['nativeSqlReceipt'], nativeInputSelection=descriptor['nativeInputSelection'],
            sourceCompanionManifest=companion, independentReadbackRequired=True,
            **{name: False for name in gate.FALSE_FLAGS}))
        sql.provider.transaction.publish_directory(product, output)
        native.archives.sync_directory(output.parent)
        return descriptor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    builder=subparsers.add_parser('build');builder.add_argument('--inputs',type=Path,required=True);builder.add_argument('--output',type=Path,required=True)
    reader=subparsers.add_parser('readback');reader.add_argument('--product',type=Path,required=True)
    external=subparsers.add_parser('verify-external')
    for name in ('provider','frozen-source','mysql-provider','proot-provider'):external.add_argument('--'+name,type=Path,required=True)
    arguments = parser.parse_args()
    if arguments.command == 'readback':
        print(encode(readback(arguments.product)).decode(),end='');return
    if arguments.command=='verify-external':
        print(encode(verify_external(arguments.provider,arguments.frozen_source,arguments.mysql_provider,arguments.proot_provider)).decode(),end='');return
    result = build(arguments.inputs, arguments.output)
    print(json.dumps(dict(scope='android-x64-installation-provider-measured-not-enabled',
        providerDescriptor=identity_bytes(encode(result)), sqlExecuted=False, androidRuntimeQualified=False), sort_keys=True))


if __name__ == '__main__': main()
