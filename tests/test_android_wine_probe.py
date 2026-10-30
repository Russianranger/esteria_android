import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from tools import build_android_wine_probe as build, verify_android_wine_probe as verify, qualify_android_wine as qualify


class WineProbeGuards(unittest.TestCase):
    def test_receipt_requires_every_phase_and_exact_source_identity(self):
        proof=dict(archive=dict(sha256='a'*64),clientInput=dict(sourceRevision='b'*40,artifact=dict(sha256='c'*64)),wineVersion='wine-10.13')
        raw=build.encoded(proof);proot={'source':'fixture-only'}
        checked={phase:dict(clientReceipt={'scope':'synthetic-unexecuted'},clientReceiptSha256='d'*64) for phase in qualify.PHASES}
        good=dict(formatVersion=1,scope=qualify.SCOPE,sourceRevision='e'*40,fingerprint='fixture',api=33,targetSdk=35,abi='x86_64',
                  guestLaunches=4,runtimeProviderSha256=hashlib.sha256(raw).hexdigest(),runtimeArchiveSha256='a'*64,runtimeGeneration='f'*64,
                  clientRevision='b'*40,clientArtifactSha256='c'*64,wineVersion='wine-10.13',prootBuildEvidence=proot,
                  runtimeInstalledByProductionInstaller=True,exactClientPayloadVerified=True,prefixInitialized=True,normalPhaseExits=True,
                  **{flag:False for flag in qualify.FALSE_FLAGS})
        good['clientChecks']={phase:dict(formatVersion=1,scope='owned-reconstructed-client-diagnostic-only',phase=phase,
            **checked[phase],wineserverStoppedNormally=True,commonMainStarted=False,assetsLoaded=False,arm64Qualified=False,gameplayQualified=False)
            for phase in qualify.PHASES}
        qualify.validate_receipt(good,'e'*40,'fixture',raw,proot,checked)
        changes={flag:True for flag in qualify.FALSE_FLAGS}
        changes.update(formatVersion=True,api=32,targetSdk=28,guestLaunches=3,abi='arm64-v8a',clientRevision='1'*40,
                       runtimeProviderSha256='1'*64,clientArtifactSha256='1'*64,wineVersion='wine-8.0',prootBuildEvidence={},
                       normalPhaseExits=False,exactClientPayloadVerified=False,clientChecks={})
        for key,value in changes.items():
            bad=copy.deepcopy(good);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):qualify.validate_receipt(bad,'e'*40,'fixture',raw,proot,checked)
        bad=copy.deepcopy(good);bad['clientChecks']['loopback']['wineserverStoppedNormally']=False
        with self.assertRaises(ValueError):qualify.validate_receipt(bad,'e'*40,'fixture',raw,proot,checked)

    def test_provider_inventory_refuses_links_and_unowned_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'assets/wine-probe').mkdir(parents=True)
            target=root/'assets/wine-probe/NOTICE.txt';target.write_bytes(b'fixture')
            self.assertEqual({'assets/wine-probe/NOTICE.txt'},set(verify.inventory(root)))
            (root/'unexpected').write_bytes(b'unowned')
            with self.assertRaises(ValueError):verify.inventory(root)
            (root/'unexpected').unlink();target.unlink();target.symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):verify.inventory(root)

    def test_pinned_client_is_reconstructed_x64_with_upstream_diagnostics(self):
        pin=json.loads(build.CLIENT_LOCK.read_text())
        self.assertEqual(pin['sourceRevision'],'97b347ee034551ea78dc905c3e209667534e6283')
        self.assertTrue(pin['windowsEntryOfflineLoopbackPassed'])
        self.assertFalse(pin['androidRuntimeQualified']);self.assertFalse(pin['arm64Qualified']);self.assertFalse(pin['gameplayQualified'])


@unittest.skipUnless(os.environ.get('ESTERIA_WINE_PROBE_CLIENT_ARTIFACT') and os.environ.get('ESTERIA_WINE_PROBE_CLIENT_SOURCE'),
                     'requires exact measured reconstructed-client artifact and clean checkout')
class ActualClientInputs(unittest.TestCase):
    def test_exact_artifact_and_source_construct_only_expected_images(self):
        artifact=Path(os.environ['ESTERIA_WINE_PROBE_CLIENT_ARTIFACT']);source=Path(os.environ['ESTERIA_WINE_PROBE_CLIENT_SOURCE'])
        pin=json.loads(build.CLIENT_LOCK.read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);one=root/'one';two=root/'two';one.mkdir();two.mkdir()
            result=build.client_payload(artifact,source,one,pin)
            self.assertEqual(result['architecture'],'x64');self.assertEqual(result['source_revision'],pin['sourceRevision'])
            build.client_payload(artifact,source,two,pin)
            first={path.relative_to(one).as_posix():build.identity(path) for path in one.rglob('*') if path.is_file()}
            second={path.relative_to(two).as_posix():build.identity(path) for path in two.rglob('*') if path.is_file()}
            self.assertEqual(first,second)
            self.assertEqual({name for name in first if name.endswith(('.exe','.dll'))},{'client/WowClient64.exe','client/XvidDecoder.dll'})
            altered=dict(pin,artifact=dict(pin['artifact'],sha256='0'*64))
            with self.assertRaises(ValueError):build.client_payload(artifact,source,root/'bad',altered)


if __name__=='__main__':unittest.main()
