"""Context transaction tests use synthetic bytes, never a qualified guest image."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare_server_dependency_image as image


class ServerDependencyImage(unittest.TestCase):
    def fixture(self, root):
        inputs = root / 'inputs'; inputs.mkdir()
        data = b'synthetic archive bytes; no ELF or execution claim\n' * 200
        (inputs / image.ARCHIVE).write_bytes(data)
        (inputs / 'source-companion.zip').write_bytes(b'synthetic source companion outside context')
        pin = {'archive': {'file': image.ARCHIVE, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}
        proof = {'scope': 'synthetic-unit-fixture-only', 'dockerImageBuilt': False,
                 'guestExecuted': False, 'androidRuntimeQualified': False, 'gameplayQualified': False}
        return inputs, pin, proof

    def test_context_has_only_exact_archive_and_offline_recipe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); inputs, pin, proof = self.fixture(root); output = root / 'image'
            with patch.object(image, 'validate_inputs', return_value=(pin, proof)) as checked:
                receipt = image.prepare(inputs, output)
            checked.assert_called_once_with(inputs)
            self.assertEqual({p.name for p in (output / 'context').iterdir()}, image.CONTEXT_FILES)
            self.assertEqual((output / 'context' / image.ARCHIVE).read_bytes(), (inputs / image.ARCHIVE).read_bytes())
            recipe = (output / 'context/Dockerfile').read_bytes()
            self.assertEqual(recipe, image.dockerfile(pin['archive']['sha256']))
            self.assertTrue(recipe.startswith(b'FROM scratch\n'))
            self.assertNotIn(b'RUN ', recipe); self.assertNotIn(b'apt-get', recipe)
            self.assertIn(b'LANG=C.UTF-8', recipe); self.assertIn(b'PATH=/usr/local/sbin:', recipe)
            self.assertFalse(receipt['sourceCompanionCopiedIntoContext'])
            self.assertFalse(receipt['dockerImageBuilt']); self.assertFalse(receipt['guestExecuted'])
            self.assertEqual(json.loads((output / 'context-receipt.json').read_bytes()), receipt)

    def test_rejection_preserves_inputs_and_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); inputs,pin,proof=self.fixture(root); output=root/'existing';output.mkdir()
            (output/'marker').write_bytes(b'preserved')
            with patch.object(image,'validate_inputs') as checked, self.assertRaisesRegex(ValueError,'output-exists'):
                image.prepare(inputs,output)
            checked.assert_not_called();self.assertEqual((output/'marker').read_bytes(),b'preserved')
            with patch.object(image,'validate_inputs',side_effect=ValueError('source-companion-not-verified')):
                with self.assertRaisesRegex(ValueError,'source-companion-not-verified'):
                    image.prepare(inputs,root/'rejected')
            self.assertFalse((root/'rejected').exists());self.assertTrue((inputs/image.ARCHIVE).is_file())

    def test_copy_rehash_rejects_post_validation_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);inputs,pin,proof=self.fixture(root);output=root/'image'
            (inputs/image.ARCHIVE).write_bytes(b'changed after validation')
            with self.assertRaisesRegex(ValueError,'identity-mismatch'):
                image.write_context(inputs,output,pin,proof)
            self.assertFalse(output.exists());self.assertEqual({p.name for p in root.iterdir()},{'inputs'})

    def test_context_and_inputs_are_disjoint_and_aliases_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);inputs,pin,proof=self.fixture(root)
            for output in (inputs,inputs/'context',root):
                with self.subTest(output=output),self.assertRaises(ValueError):image.prepare(inputs,output)
            (root/'alias').symlink_to(inputs,target_is_directory=True)
            with self.assertRaises(ValueError):image.prepare(root/'alias',root/'output')

    def test_dockerfile_label_cannot_inject_an_instruction(self):
        for value in ('a'*63,'a'*64+'\nRUN false',None,'g'*64):
            with self.subTest(value=value),self.assertRaises(ValueError):image.dockerfile(value)

    def test_inner_source_validation_is_mandatory_despite_candidate_success(self):
        # A successful ZIP/publication hash check is not the fresh inner-source
        # validation promised by this helper. These are synthetic metadata mocks.
        identity={'bytes':1,'sha256':'a'*64}
        lock={'published':{'assets':{'release-manifest.json':identity}}}
        with tempfile.TemporaryDirectory() as directory:
            inputs=Path(directory)
            with patch.object(image.release,'load_lock',return_value=(lock,{})), \
                 patch.object(image.release,'verify_candidate',return_value={'release-manifest.json':identity}), \
                 patch.object(image.provider,'descriptor',return_value={}), \
                 patch.object(image.release,'small_json',return_value={}), \
                 patch.object(image.release,'validate_sources',side_effect=ValueError('inner-source-mismatch')) as sources:
                with self.assertRaisesRegex(ValueError,'inner-source-mismatch'):image.validate_inputs(inputs)
                sources.assert_called_once_with(inputs/image.release.SOURCE_ZIP,lock,{}, {})


if __name__=='__main__':unittest.main()
