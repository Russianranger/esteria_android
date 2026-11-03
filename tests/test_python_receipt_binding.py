"""Production Python -> production Java consumer with unchanged Android13 JSON.

Only synthetic native/compiler output is used; no owner assets, actual Android
execution, Thor world readiness or gameplay is claimed by these host tests.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from runtime import server_data_generation as data
from tools import prepare_android_receipt_fixtures as fixtures

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / 'tests/fixtures/android13-json'


class PythonReceiptFixtureProducer(unittest.TestCase):
    def test_exact_android13_json_and_streaming_reader_sources(self):
        manifest = json.loads((SOURCES / 'source-manifest.json').read_bytes())
        self.assertEqual(manifest['tag'], 'android-13.0.0_r1')
        self.assertEqual(len(manifest['files']), 11)
        for name, pin in manifest['files'].items():
            raw = (SOURCES / name).read_bytes()
            self.assertEqual(len(raw), pin['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), pin['sha256'])
            self.assertIn('/+/refs/tags/android-13.0.0_r1/', pin['url'])
        self.assertEqual(manifest['files']['aosp/JSONStringer.java']['sha256'],
                         '8772ac80610cd62e906330152b09864c471a0921f199f4b9d670d98050e3d86c')

    def test_real_python_producers_keep_v10_generation_helper_and_bounded_test_only_files(self):
        baseline = json.loads((ROOT / 'runtime/evidence/non-custom-v10-release-gates.json').read_bytes())
        self.assertEqual(data.preparation_helper_generation(),
                         baseline['runtimeHelperClosures']['server-data']['manifest']['sha256'])
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'assets'
            value = fixtures.prepare(output)
            self.assertTrue(value['productionPythonGenerationExecuted'])
            self.assertTrue(value['nativeToolExecutionReplaced'])
            self.assertTrue(value['shaderCompilerExecutionReplaced'])
            self.assertFalse(value['gameplayQualified'])
            self.assertLess(sum(row['bytes'] for row in value['files'].values()), 1 << 20)
            self.assertFalse(any('/.' in name for name in value['files']))
            for kind, family in (('data', 'server-data'), ('shader', 'shaders')):
                selected = output / kind / 'work' / family / 'generations' / value[kind]['generation']
                receipt = json.loads((selected / 'receipt.json').read_bytes())
                expected = hashlib.sha256(data.storage.encoded(receipt['inputs'])).hexdigest()
                self.assertEqual(receipt['generation'], expected)
                self.assertEqual(receipt['inputs']['contentProfile'], 'stock-3.3.5a')
                self.assertEqual((output / kind / 'work' / family / 'current').read_text(), expected + '\n')
                variants = json.loads((output / (kind + '-mutants.json')).read_bytes())
                for row in variants:
                    self.assertEqual(row['generation'], hashlib.sha256(data.storage.encoded(row['inputs'])).hexdigest())


class PythonToAndroidJavaReceipt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('javac')
        if not compiler and os.environ.get('JAVA_HOME'):
            candidate = Path(os.environ['JAVA_HOME']) / 'bin/javac'
            if candidate.is_file(): compiler = str(candidate)
        if not compiler:
            raise unittest.SkipTest('JDK17 javac required for actual Android13 source/production consumer execution')
        cls.compiler = compiler
        cls.java = str(Path(compiler).resolve().with_name('java'))
        cls.temporary = tempfile.TemporaryDirectory(prefix='esteria-receipt-consumer-')
        cls.root = Path(cls.temporary.name)
        cls.assets = cls.root / 'assets'
        cls.fixture = fixtures.prepare(cls.assets)
        helper = cls.assets / 'data/work/data-helpers' / cls.fixture['data']['helperGeneration']
        helper.mkdir(parents=True)
        for name in data.PREPARATION_HELPERS:
            shutil.copyfile(ROOT / 'runtime' / name, helper / name)
        cls.classes = cls.root / 'classes'
        cls.compile(cls.classes)
        cls.legacy = cls.root / 'legacy-classes'
        cls.compile(cls.legacy, legacy=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @classmethod
    def compile(cls, destination, legacy=False):
        destination.mkdir()
        generated = cls.root / ('legacy-source' if legacy else 'source')
        generated.mkdir()
        lock = json.loads((ROOT / 'sources.lock.json').read_bytes())
        build = generated / 'BuildConfig.java'
        build.write_text('package io.github.russianranger.esteria; public final class BuildConfig {'
            'public static final String CLIENT_REVISION="' + lock['sources']['client']['commit'] + '";}')
        binding = ROOT / 'app/src/main/java/io/github/russianranger/esteria/runtime/ServerDataBinding.java'
        if legacy:
            source = binding.read_text()
            old = '''java.util.TreeSet<String> names=new java.util.TreeSet<>();value.keys().forEachRemaining(names::add);StringBuilder out=new StringBuilder("{");
                for(String name:names){if(out.length()>1)out.append(',');out.append(JSONObject.quote(name)).append(':');Object item=value.get(name);
                    if(item instanceof JSONObject)out.append(canonical((JSONObject)item));
                    else if(item instanceof String)out.append(JSONObject.quote((String)item));
                    else if(item instanceof Boolean||item instanceof Integer||item instanceof Long)out.append(item);
                    else throw new IOException("Unsupported canonical data input value");}
                return out.append('}').toString();'''
            assert source.count('return PythonReceiptJson.canonical(value);') == 1
            source = source.replace('return PythonReceiptJson.canonical(value);', old)
            binding = generated / 'ServerDataBinding.java'
            binding.write_text(source)
        files = [*sorted((SOURCES / 'aosp').glob('*.java')),
                 *sorted((SOURCES / 'support').glob('*.java')),
                 *sorted((ROOT / 'core/src/main/java').rglob('*.java')),
                 build, binding, ROOT / 'app/src/main/java/io/github/russianranger/esteria/runtime/PythonReceiptJson.java',
                 SOURCES / 'ReceiptBindingHarness.java']
        result = subprocess.run([cls.compiler, '--release', '17', '-d', str(destination), *map(str, files)],
                                capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise AssertionError('Actual source/consumer fixture did not compile: ' + result.stderr[-8000:])

    def execute(self, mode, *, legacy=False):
        return subprocess.run([self.java, '-Xmx32m', '-cp', str(self.legacy if legacy else self.classes),
                               'io.github.russianranger.esteria.runtime.ReceiptBindingHarness', mode, str(self.assets)],
                              capture_output=True, text=True, timeout=30)

    def test_python_generated_unicode_control_slash_integer_and_boolean_bytes(self):
        result = self.execute('codec')
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['vectorsPassed'], 6)
        self.assertTrue(value['android13QuoteExecuted'])
        self.assertTrue(value['strictValueTypes'])

    def test_actual_python_generation_is_accepted_and_matching_hash_mutants_remain_rejected(self):
        result = self.execute('inspect')
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertTrue(value['pythonGenerationAccepted'])
        self.assertEqual(value['matchingHashMutantsRejected'], 11)
        self.assertTrue(value['completedDataUnchanged'])
        self.assertEqual(value['generation'], self.fixture['data']['generation'])

    def test_restoring_android_quote_hash_policy_reproduces_the_owner_failure(self):
        result = self.execute('inspect', legacy=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Prepared data source/import selection differs', result.stderr)


if __name__ == '__main__':
    unittest.main()
