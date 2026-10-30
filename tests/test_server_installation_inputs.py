"""Small host artifact fixtures only; no network/native binaries/SQL are run."""
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from tools import prepare_server_installation_inputs as setup


def identity(raw): return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class InstallationInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_real_measured_pin_crossbinds_the_existing_helper_selection(self):
        pin, lock, original = setup.load_pin()
        self.assertEqual(pin['producer']['workflowRun'],41081216973)
        self.assertEqual(pin['artifact']['id'],12990195617)
        self.assertEqual(pin['artifact']['bytes'],40130109)
        self.assertEqual(set(pin['members']),setup.MEMBERS)
        self.assertEqual(original['executable']['sha256'],'b7d9b72c17f32294915f0a474283c543057ffb7de7b3f93015c2e7e179bfcf25')
        self.assertEqual(lock,setup.files.identity(setup.LOCK))

    def test_exact_remote_success_head_artifact_expiry_and_digest_are_required(self):
        pin,_,_=setup.load_pin(); producer=pin['producer']; expected=pin['artifact']
        run=dict(id=producer['workflowRun'],head_sha=producer['integrationRevision'],status='completed',conclusion='success')
        artifact=dict(id=expected['id'],expired=False,size_in_bytes=expected['bytes'],digest='sha256:'+expected['sha256'],
            workflow_run=dict(id=run['id'],head_sha=run['head_sha']))
        api=Mock();api.json.side_effect=[run,artifact];setup.verify_remote(api,pin)
        for changed in (dict(run,head_sha='0'*40),dict(run,conclusion='failure'),dict(run,status='in_progress')):
            api.json.side_effect=[changed]
            with self.assertRaisesRegex(ValueError,'producer'):setup.verify_remote(api,pin)
        for changed in (dict(artifact,expired=True),dict(artifact,digest='sha256:'+'0'*64),
                        dict(artifact,workflow_run=dict(id=run['id']+1,head_sha=run['head_sha']))):
            api.json.side_effect=[run,changed]
            with self.assertRaisesRegex(ValueError,'artifact'):setup.verify_remote(api,pin)
        api.download.assert_not_called()

    def registration(self, *, extra=None, changed=None):
        rows={name:json.dumps({'fixture':name}).encode() for name in setup.MEMBERS}
        path=self.root/('registration-'+str(len(list(self.root.iterdir())))+'.zip')
        with zipfile.ZipFile(path,'w') as archive:
            for name,raw in rows.items():archive.writestr(name,raw if name!=changed else raw+b'changed')
            if extra:archive.writestr(extra,b'unsafe extra')
        pin=dict(artifact=identity(path.read_bytes()),members={name:identity(raw) for name,raw in rows.items()})
        return path,pin

    def test_outer_exact_members_and_streamed_hashes_precede_candidate_use(self):
        archive,pin=self.registration();output=self.root/'outer';setup.extract_registration(archive,output,pin)
        for name,row in pin['members'].items():
            self.assertEqual(setup.files.identity(output/name),row)
            self.assertEqual((output/name).stat().st_mode&0o777,0o444)
        with patch.object(setup.transfer,'bounded_zip') as opened:
            with self.assertRaisesRegex(ValueError,'outer-pin'):setup.extract_registration(archive,self.root/'bad',dict(pin,artifact=identity(b'wrong')))
            opened.assert_not_called()
        for extra in ('unexpected.txt','../outside'):
            path,bad=self.registration(extra=extra)
            with self.assertRaises(ValueError):setup.extract_registration(path,self.root/('extra-'+str(len(extra))),bad)
        path,bad=self.registration(changed='acquisition.json')
        with self.assertRaisesRegex(ValueError,'size|hash'):setup.extract_registration(path,self.root/'changed',bad)
        self.assertFalse((self.root/'outside').exists())

    def small_tar(self, *, mode_change=False, extra=False):
        payload={'runtime/helpers/playerbots-schema':(b'HOST_FIXTURE_NOT_ELF',0o555),
            'runtime/provenance/playerbots-helper-build.json':(b'{"fixture":"build"}',0o444),
            'runtime/provenance/playerbots-native-sql.json':(b'{"fixture":"native"}',0o444),
            'companion/build-payload/recipes/.github/workflows/fixture.yml':(b'fixture source recipe\n',0o444)}
        proof=dict(runtimeFiles={name.removeprefix('runtime/'):dict(identity(raw),mode=mode) for name,(raw,mode) in payload.items() if name.startswith('runtime/')},
            companionFiles={name.removeprefix('companion/'):dict(identity(raw),mode=mode) for name,(raw,mode) in payload.items() if name.startswith('companion/')})
        raw=json.dumps(proof,sort_keys=True).encode();payload['candidate-pin.json']=(raw,0o444)
        registration=self.root/('registered-'+str(len(list(self.root.iterdir()))));(registration/'candidate').mkdir(parents=True)
        (registration/'candidate/candidate-pin.json').write_bytes(raw)
        archive=registration/'candidate.tar.gz'
        with archive.open('wb') as stream,gzip.GzipFile(fileobj=stream,mode='wb',mtime=0,filename='') as compressed:
            with tarfile.open(fileobj=compressed,mode='w|',format=tarfile.GNU_FORMAT) as tar:
                for name,(data,mode) in sorted(payload.items()):
                    item=tarfile.TarInfo(name);item.size=len(data);item.mode=0o600 if mode_change and name.endswith('playerbots-schema') else mode
                    tar.addfile(item,io.BytesIO(data))
                if extra:
                    item=tarfile.TarInfo('../outside');item.size=1;tar.addfile(item,io.BytesIO(b'x'))
        pin=dict(members={'candidate/candidate-pin.json':identity(raw),'candidate.tar.gz':setup.files.identity(archive)},
            candidateFiles=len(payload),candidateExpandedBytes=sum(len(row[0]) for row in payload.values()))
        return registration,pin,proof,payload

    def test_authenticated_tar_modes_hidden_recipe_and_all_bytes_read_back(self):
        registration,pin,proof,payload=self.small_tar();output=self.root/'candidate'
        with patch.object(setup.candidate,'verify',return_value=proof) as verify:
            self.assertEqual(setup.extract_candidate(registration,output,pin),proof)
            verify.assert_called_once_with(output,pin['members']['candidate/candidate-pin.json']['sha256'])
        for name,(raw,mode) in payload.items():
            self.assertEqual((output/name).read_bytes(),raw);self.assertEqual((output/name).stat().st_mode&0o777,mode)
        with self.assertRaisesRegex(ValueError,'existing'):setup.extract_candidate(registration,output,pin)

    def test_wrong_tar_mode_extra_path_and_bad_crc_refuse_before_extraction(self):
        for mode_change,extra in ((True,False),(False,True)):
            registration,pin,proof,_=self.small_tar(mode_change=mode_change,extra=extra);output=self.root/('bad-'+str(mode_change))
            with patch.object(setup.candidate,'verify') as verify,self.assertRaises(ValueError):setup.extract_candidate(registration,output,pin)
            self.assertFalse(output.exists());verify.assert_not_called()
        registration,pin,proof,_=self.small_tar();path=registration/'candidate.tar.gz'
        raw=bytearray(path.read_bytes());raw[-8]^=1;path.write_bytes(raw);pin['members']['candidate.tar.gz']=identity(raw)
        with self.assertRaises((OSError,ValueError)):setup.extract_candidate(registration,self.root/'crc',pin)
        self.assertFalse((self.root/'crc').exists())

    def test_case_collision_or_expanded_bound_and_current_helper_lock_tamper_refuse(self):
        _,pin,proof,_=self.small_tar();bad=copy.deepcopy(proof)
        row=bad['runtimeFiles']['helpers/playerbots-schema'];bad['runtimeFiles']['HELPERS/PLAYERBOTS-SCHEMA']=dict(row,mode=0o444)
        with self.assertRaises(ValueError):setup.candidate_inventory(bad,pin)
        with self.assertRaises(ValueError):setup.candidate_inventory(proof,dict(pin,candidateExpandedBytes=pin['candidateExpandedBytes']+1))
        actual,_,_=setup.load_pin();actual['helperInputLock']['sha256']='0'*64
        with patch.object(setup.candidate.modules,'read_json',return_value=(actual,identity(b'fixture'))), \
                self.assertRaises(ValueError):setup.load_pin()

    def test_existing_output_refuses_before_network_and_no_compiler_or_sql_path(self):
        output=self.root/'existing';output.mkdir();(output/'sentinel').write_bytes(b'preserve')
        api=Mock()
        with self.assertRaisesRegex(ValueError,'existing'):setup.prepare(output,api)
        api.json.assert_not_called();api.download.assert_not_called()
        self.assertEqual((output/'sentinel').read_bytes(),b'preserve')


if __name__=='__main__':unittest.main()
