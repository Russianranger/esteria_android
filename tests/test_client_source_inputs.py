"""Explicit input selection retains immutable recipes and unchanged old defaults."""
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import package_client_sources as sources, provider_client_runtime as provider
from tools import release_client_inputs as release


class ClientSourceInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source_path = self.root / 'sources.lock.json'
        self.pin_path = self.root / 'runtime/client/android-provider.lock.json'
        self.pin_path.parent.mkdir(parents=True)
        self.source_raw = provider.SOURCE_LOCK.read_bytes();self.pin_raw = provider.PIN.read_bytes()
        self.source = json.loads(self.source_raw);self.pin = json.loads(self.pin_raw)
        self.write()

    def write(self):
        self.source_path.write_bytes(provider.encoded(self.source));self.pin_path.write_bytes(provider.encoded(self.pin))

    def test_default_omission_has_no_selected_input_receipt_extension(self):
        result = sources.input_selection()
        self.assertEqual(result[:4], (self.source_raw, self.source, self.pin_raw, self.pin))
        self.assertIsNone(result[4])
        self.assertIsNone(release.selected_inputs({}))

    def test_runtime_override_retains_exact_raw_lock_at_canonical_recipe_path(self):
        xvid = self.root / 'xvid.tar.gz'; xvid.write_bytes(b'unchanged upstream source fixture')
        recipe = ('URL https://downloads.xvid.com/downloads/xvidcore-1.3.7.tar.gz\nURL_HASH SHA256=' +
                  hashlib.sha256(xvid.read_bytes()).hexdigest() + '\n').encode()
        def archive(*args, **kwargs):
            self.assertEqual(args[0], ['git', 'archive', '--format=tar', self.pin['sourceRevision']])
            kwargs['stdout'].write(b'complete synthetic Git tree fixture')
        runtime = self.root / 'selected-runtime.json'
        profile = json.loads(provider.archives.DEFAULT_LOCK.read_bytes())
        profile['packages']['wine-arm64']['archive']['sha256'] = 'e' * 64
        profile['packages']['wine-arm64']['wineEnvironment'] = {'WINE_ANDROID_PRIVATE_PE_COPY': '1'}
        runtime.write_text('\n' + json.dumps(profile))
        with patch.object(provider.fetch_sources, 'verify_checkout'), patch.object(provider, 'source_blob', return_value=recipe), \
             patch.object(sources.subprocess, 'run', side_effect=archive):
            default = sources.build(self.root, xvid, self.root / 'default-fixture')
            explicit = sources.build(self.root, xvid, self.root / 'selected-fixture', runtime_lock=runtime)
            expected = provider.identity(runtime)
            self.assertNotIn('selectedInputs', default)
            self.assertEqual(explicit['selectedInputs'], {provider.RUNTIME_INPUT: expected})
            canonical = 'integration-recipe/' + provider.RUNTIME_INPUT
            self.assertEqual(explicit['members'][canonical], expected)
            with tarfile.open(self.root / 'selected-fixture/client-corresponding-source.tar.gz', 'r:gz') as retained:
                self.assertEqual(retained.extractfile(canonical).read(), runtime.read_bytes())
            self.assertNotEqual(default['archive'], explicit['archive'])
            # Selecting identical default bytes adds only the external receipt;
            # the corresponding-source archive itself remains byte-identical.
            runtime.write_bytes(provider.archives.DEFAULT_LOCK.read_bytes())
            identical = sources.build(self.root, xvid, self.root / 'identical-fixture', runtime_lock=runtime)
            self.assertEqual(identical['archive'], default['archive'])
            self.assertEqual(identical['members'], default['members'])
            self.source_path.write_bytes(self.source_raw); self.pin_path.write_bytes(self.pin_raw)
            paired = sources.build(self.root, xvid, self.root / 'paired-fixture', self.source_path, self.pin_path, runtime)
            self.assertEqual(set(paired['selectedInputs']), {'sources.lock.json',
                'runtime/client/android-provider.lock.json', provider.RUNTIME_INPUT})
            with self.assertRaisesRegex(ValueError, 'paired-client-source-inputs'):
                sources.build(self.root, xvid, self.root / 'bad-pair', self.source_path, runtime_lock=runtime)

    def test_source_cli_passes_runtime_without_changing_existing_source_input_pair(self):
        args = ['package_client_sources.py', '--client-source', '/source', '--xvid-source', '/xvid.tar.gz', '--output', '/output']
        with patch.object(sys, 'argv', args), patch.object(sources, 'build', return_value={}) as build, redirect_stdout(io.StringIO()):
            sources.main(); self.assertEqual(build.call_args.args[-3:], (None, None, None))
        args += ['--runtime-lock', '/runtime.json', '--source-lock', '/source.json', '--client-input-lock', '/client.json']
        with patch.object(sys, 'argv', args), patch.object(sources, 'build', return_value={}) as build, redirect_stdout(io.StringIO()):
            sources.main()
            self.assertEqual(build.call_args.args[-3:], (Path('/source.json'), Path('/client.json'), Path('/runtime.json')))

    def test_both_overrides_are_required_before_opening_files(self):
        with patch.object(provider, 'small', side_effect=AssertionError('must reject before reading')):
            for arguments in ((self.source_path, None), (None, self.pin_path)):
                with self.subTest(arguments=arguments), self.assertRaisesRegex(ValueError, 'paired-client-source-inputs'):
                    sources.input_selection(*arguments)

    def test_explicit_input_hashes_cover_exact_raw_bytes(self):
        self.source_path.write_bytes(b'\n' + self.source_path.read_bytes())
        raw, lock, pin_raw, pin, selected = sources.input_selection(self.source_path, self.pin_path)
        self.assertEqual(lock, self.source);self.assertEqual(pin, self.pin)
        self.assertEqual(raw, self.source_path.read_bytes());self.assertEqual(pin_raw, self.pin_path.read_bytes())
        self.assertEqual(selected, {name: provider.identity(path) for name, path in (
            ('sources.lock.json', self.source_path), ('runtime/client/android-provider.lock.json', self.pin_path))})

    def test_selected_source_revision_build_identity_and_json_types_are_strict(self):
        mutations = [lambda:self.pin.update(formatVersion=True), lambda:self.pin.update(artifactId=True),
            lambda:self.pin.update(workflowRun=True), lambda:self.pin.update(buildId='1.0'),
            lambda:self.pin.update(androidRuntimeQualified=0), lambda:self.pin.update(sourceRevision='f'*40),
            lambda:self.pin['artifact'].update(bytes=True), lambda:self.pin.update(buildManifestSha256='bad'),
            lambda:self.source['compatibility'].update(extended_limits=1),
            lambda:self.source['compatibility'].update(client_class_capacity=32.0),
            lambda:self.source['compatibility'].update(container_slots=255)]
        for mutation in mutations:
            self.source=json.loads(self.source_raw);self.pin=json.loads(self.pin_raw);mutation();self.write()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                sources.input_selection(self.source_path, self.pin_path)

    def selected(self):
        return dict(selectedInputs={name: provider.identity(path) for name,path in (
            ('sources.lock.json',self.source_path),('runtime/client/android-provider.lock.json',self.pin_path))},
            generationInputs={name:{} for name in release.RECIPE_INPUT_PATHS})

    def test_release_selection_requires_exact_two_inputs_and_complete_recipe_set(self):
        lock=self.selected()
        with patch.object(release,'ROOT',self.root):
            self.assertEqual(release.selected_inputs(lock),lock['selectedInputs'])
            changes=[lambda d:d.update(selectedInputs=None),lambda d:d['selectedInputs'].pop('sources.lock.json'),
                lambda d:d['selectedInputs'].update({'other':{'bytes':1,'sha256':'0'*64}}),
                lambda d:d['generationInputs'].pop('tools/package_client_sources.py'),
                lambda d:d['selectedInputs']['sources.lock.json'].update(bytes=True),
                lambda d:d['selectedInputs']['sources.lock.json'].update(sha256='0'*64)]
            for change in changes:
                altered=copy.deepcopy(lock);change(altered)
                with self.subTest(change=change),self.assertRaises(ValueError):release.selected_inputs(altered)

    @unittest.skipUnless(os.environ.get('ESTERIA_CLIENT_SOURCE') and os.environ.get('ESTERIA_XVID_SOURCE'),
        'requires exact client checkout and upstream Xvid archive')
    def test_explicit_identical_raw_inputs_preserve_default_archive_bytes(self):
        source=Path(os.environ['ESTERIA_CLIENT_SOURCE']);xvid=Path(os.environ['ESTERIA_XVID_SOURCE'])
        # Explicit paths can differ while retaining the exact default raw inputs.
        self.source_path.write_bytes(self.source_raw);self.pin_path.write_bytes(self.pin_raw)
        default=sources.build(source,xvid,self.root/'default')
        explicit=sources.build(source,xvid,self.root/'explicit',self.source_path,self.pin_path)
        self.assertEqual(default['archive'],explicit['archive'])
        self.assertEqual(default['members'],explicit['members'])
        self.assertNotIn('selectedInputs',default)
        selected=explicit.pop('selectedInputs')
        self.assertEqual(default,explicit)
        self.assertEqual(selected['sources.lock.json'],dict(bytes=len(self.source_raw),
            sha256=hashlib.sha256(self.source_raw).hexdigest()))


if __name__=='__main__':unittest.main()
