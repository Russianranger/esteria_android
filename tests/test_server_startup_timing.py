"""Host clocks/production Python statuses; never Android or native-server evidence."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from runtime import server_session as session

ROOT = Path(__file__).resolve().parents[1]


class StartupTimingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK17 required')
    def test_production_java_deadline_policy(self):
        with tempfile.TemporaryDirectory() as output:
            package = 'io/github/russianranger/esteria/core/runtime/'
            sources = [ROOT / 'core/src/main/java' / package / 'ServerStartupTiming.java',
                       ROOT / 'core/src/test/java' / package / 'ServerStartupTimingTests.java']
            subprocess.run(['javac', '-d', output, *map(str, sources)], check=True, capture_output=True, timeout=30)
            result = subprocess.run(['java', '-cp', output,
                'io.github.russianranger.esteria.core.runtime.ServerStartupTimingTests'], check=True,
                capture_output=True, text=True, timeout=30)
            self.assertIn('PASS:', result.stdout)

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK17 required')
    def test_python_status_through_actual_android_json_production_consumer(self):
        import hashlib
        fixture = ROOT / 'tests/fixtures/android13-json'
        manifest = json.loads((fixture / 'source-manifest.json').read_bytes())
        for name, selected in manifest['files'].items():
            raw = (fixture / name).read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (selected['bytes'], selected['sha256']))
        with tempfile.TemporaryDirectory() as output, redirect_stdout(StringIO()):
            output = Path(output)
            session.StartupStatus(output, 'a'*32,
                dict(sourceLockSha256='b'*64, activeProofSha256='c'*64)).update('source-selection')
            sources = list((fixture / 'aosp').glob('*.java')) + list((fixture / 'support').glob('*.java'))
            sources += [ROOT / 'core/src/main/java/io/github/russianranger/esteria/core/runtime/ServerStartupTiming.java',
                ROOT / 'app/src/main/java/io/github/russianranger/esteria/runtime/ServerStartupStatus.java',
                ROOT / 'app/src/test/java/io/github/russianranger/esteria/runtime/ServerStartupStatusTests.java']
            subprocess.run(['javac', '-d', str(output), *map(str, sources)], check=True, capture_output=True, timeout=30)
            result = subprocess.run(['java', '-cp', str(output),
                'io.github.russianranger.esteria.runtime.ServerStartupStatusTests', str(output / 'startup-status.json')],
                check=True, capture_output=True, text=True, timeout=30)
            self.assertIn('PASS:', result.stdout)

    def test_atomic_python_status_separates_admission_from_native_and_redacts_failure(self):
        with tempfile.TemporaryDirectory() as output, redirect_stdout(StringIO()) as logs:
            root = Path(output); clock = [10.0]
            status = session.StartupStatus(root, 'a'*32,
                dict(sourceLockSha256='b'*64, activeProofSha256='c'*64), clock=lambda: clock[0])
            status.update('provider-verification')
            clock[0] += 600
            status.update('native-launch', 'authserver', native=True)
            first = json.loads((root / 'startup-status.json').read_bytes())
            self.assertEqual((first['elapsedMs'], first['nativeElapsedMs']), (600000, 0))
            self.assertEqual(first['operationId'], 'a'*32)
            self.assertEqual(first['sourceLockSha256'], 'b'*64)
            clock[0] += 50
            status.update('owned-world-listener', 'worldserver', native=True)
            status.failed(ValueError('DO_NOT_EXPORT_PRIVATE_ERROR_TEXT'))
            last = json.loads((root / 'startup-status.json').read_bytes())
            self.assertEqual((last['elapsedMs'], last['nativeElapsedMs']), (650000, 50000))
            self.assertEqual(last['failureType'], 'ValueError')
            self.assertEqual(last['readiness'], 'owned-world-listener')
            self.assertNotIn('DO_NOT_EXPORT', logs.getvalue())
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['startup-status.json'])
            with self.assertRaisesRegex(ValueError, 'Fixed server startup'):
                status.update('private path', 'unbound program')

    def test_native_wait_refuses_timeout_cancel_and_condition_finishing_late(self):
        active = object.__new__(session.Session)
        active._check = lambda: None
        with patch.object(session.time, 'monotonic', return_value=5):
            with self.assertRaisesRegex(ValueError, 'deadline'):
                active._await(lambda: True, 5, lambda: False)
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                active._await(lambda: True, 10, lambda: True)
        with patch.object(session.time, 'monotonic', side_effect=[4, 6]):
            with self.assertRaisesRegex(ValueError, 'deadline'):
                active._await(lambda: True, 5, lambda: False)

    def test_actual_completed_verifier_cancels_during_payload_and_keeps_generation(self):
        from tests.test_server_data_generation import ServerDataGenerationTests
        fixture = ServerDataGenerationTests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        data, io = session.data, session.data.world_io
        with patch.object(data, 'execute', side_effect=fixture.fake_execute):
            receipt = fixture.generate()
        generation = fixture.store / 'generations' / receipt['generation']
        # Synthetic payload only: cancellation must occur within this file read,
        # before header checks. This is no game-data compatibility claim.
        payload = generation / 'data/dbc/Cancel.dbc'
        payload.write_bytes(b'x' * (1 << 20))
        receipt['files'] = data.inventory(generation / 'data')
        (generation / 'receipt.json').write_bytes(data.storage.encoded(receipt))
        original = data.storage.identity
        cancelled = [False]
        consume = io.Policy.consumed
        def consumed(policy, count):
            consume(policy, count)
            if policy.read_bytes >= 256 << 10:
                cancelled[0] = True
        with patch.object(io.Policy, 'consumed', consumed), patch.dict('os.environ', {io.SPEED_ENVIRONMENT: 'fast'}):
            with self.assertRaises(io.PreparationPaused):
                with io.android_policy(cancelled=lambda: cancelled[0]) as policy:
                    data.verify_completed(generation, receipt['inputs'])
            self.assertGreaterEqual(policy.read_bytes, 256 << 10)
            self.assertLess(policy.read_bytes, 1 << 20)
        self.assertIs(data.storage.identity, original)
        self.assertFalse(io.enabled())
        self.assertEqual(payload.stat().st_size, 1 << 20)
        self.assertEqual((fixture.store / 'current').read_text(), receipt['generation'] + '\n')

    def test_session_admission_context_restores_helpers_on_cancel_and_retains_speed(self):
        io = session.data.world_io
        original = session.data.storage.identity
        reports = []
        with tempfile.TemporaryDirectory() as output, patch.dict('os.environ', {io.SPEED_ENVIRONMENT: 'fast'}):
            path = Path(output) / 'retained-data'; path.write_bytes(b'unchanged')
            with self.assertRaises(io.PreparationPaused):
                with io.android_policy(cancelled=lambda: True, progress=reports.append) as policy:
                    self.assertEqual(policy.speed, 'fast')
                    session.data.storage.identity(path, 1024)
            self.assertIs(session.data.storage.identity, original)
            self.assertFalse(io.enabled())
            self.assertEqual(path.read_bytes(), b'unchanged')
            self.assertTrue(any('"readBytes":0' in report for report in reports))


if __name__ == '__main__':
    unittest.main()
