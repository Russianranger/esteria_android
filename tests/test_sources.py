import importlib.util
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fetch_sources", ROOT / "tools/fetch_sources.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SourceLockTests(unittest.TestCase):
    def test_lock_is_pinned_and_matches_format(self):
        lock = module.load_lock(ROOT / "sources.lock.json")
        self.assertEqual(lock["compatibility"]["base_client_build"], 12340)
        self.assertEqual(lock["compatibility"]["container_slots"], 254)

    def test_reject_branch_instead_of_commit(self):
        doc = json.loads((ROOT / "sources.lock.json").read_text())
        doc["sources"]["client"]["commit"] = "Esteria"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock.json"
            path.write_text(json.dumps(doc))
            with self.assertRaises(ValueError):
                module.load_lock(path)

    def test_reject_traversal(self):
        for path in ["../x", "/tmp/x", "x/../../x", "x\\..\\x", "--flag"]:
            with self.assertRaises(ValueError):
                module.safe_relative(path)

    def test_patch_scope_must_be_an_exact_pinned_submodule(self):
        doc = json.loads((ROOT / 'sources.lock.json').read_text())
        doc['sources']['server']['patches'] = [
            {'path': 'patches/server/example.patch', 'sha256': '0' * 64, 'submodule': 'untracked/module'}]
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'lock.json'
            path.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError, 'exactly pinned'):
                module.load_lock(path)

    def test_indexed_submodule_patch_is_reproducible_and_user_edits_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            origin, parent = root / 'origin', root / 'parent'
            def git(repo, *args):
                return subprocess.check_output(['git', *args], cwd=repo, text=True,
                                               stderr=subprocess.PIPE).strip()
            for repo in (origin, parent):
                repo.mkdir()
                git(repo, 'init', '-q')
                git(repo, 'config', 'user.name', 'Fixture')
                git(repo, 'config', 'user.email', 'fixture@example.invalid')
                (repo / 'source.txt').write_text('original\n')
                git(repo, 'add', '.')
                git(repo, 'commit', '-qm', 'fixture')
            git(parent, '-c', 'protocol.file.allow=always', 'submodule', 'add', str(origin), 'deps/engine')
            git(parent, 'commit', '-qm', 'pinned dependency')
            dependency = parent / 'deps/engine'
            patch = root / 'fix.patch'
            patch.write_text('diff --git a/source.txt b/source.txt\n'
                             '--- a/source.txt\n+++ b/source.txt\n@@ -1 +1 @@\n-original\n+patched\n')
            source = {'commit': git(parent, 'rev-parse', 'HEAD'),
                      'submodules': {'deps/engine': git(origin, 'rev-parse', 'HEAD')},
                      'patches': [{'path': 'fix.patch', 'sha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
                                   'submodule': 'deps/engine'}]}
            patches = module.patch_inputs(source, root)
            git(dependency, 'apply', '--index', str(patch))
            module.verify_checkout(parent, source, patches)
            module.verify_checkout(parent, source, patches)  # Deterministic repeated/offline validation.
            path = dependency / 'source.txt'
            path.write_text('uncommitted user work\n')
            with self.assertRaisesRegex(ValueError, 'uncommitted'):
                module.verify_checkout(parent, source, patches)
            git(dependency, 'add', 'source.txt')
            with self.assertRaisesRegex(ValueError, 'staged content differs'):
                module.verify_checkout(parent, source, patches)
            self.assertEqual(path.read_text(), 'uncommitted user work\n')
            patch.write_text(patch.read_text() + '\n')
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                module.patch_inputs(source, root)

    def test_preserves_dirty_and_wrong_head_checkouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()
            git("init", "-q")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            path = repo / "source.txt"
            path.write_text("original")
            git("add", ".")
            git("commit", "-qm", "fixture")
            source = {"commit": git("rev-parse", "HEAD"), "submodules": {}}
            module.verify_checkout(repo, source, [])
            path.write_text("user work")
            for flag, inverse in [("--assume-unchanged", "--no-assume-unchanged"),
                                  ("--skip-worktree", "--no-skip-worktree")]:
                git("update-index", flag, "source.txt")
                with self.assertRaises(ValueError):
                    module.verify_checkout(repo, source, [])
                self.assertEqual(path.read_text(), "user work")
                git("update-index", inverse, "source.txt")
            with self.assertRaises(ValueError):
                module.verify_checkout(repo, source, [])
            self.assertEqual(path.read_text(), "user work")
            git("add", ".")
            with self.assertRaises(ValueError):
                module.verify_checkout(repo, source, [])
            git("commit", "-qm", "user work")
            with self.assertRaises(ValueError):
                module.verify_checkout(repo, source, [])
            self.assertEqual(path.read_text(), "user work")


if __name__ == "__main__":
    unittest.main()
