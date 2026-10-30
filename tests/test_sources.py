import importlib.util
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
