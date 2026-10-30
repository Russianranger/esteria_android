#!/usr/bin/env python3
"""Fetch exact engine/server revisions without replacing a developer's changes.

Branches in the lock file are documentation only: they never select build inputs.
Patches are SHA-256 checked and applied in order to the pinned source checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}\Z")


def run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.PIPE).strip()


def safe_relative(value: str) -> str:
    p = PurePosixPath(value)
    if not value or p.is_absolute() or ".." in p.parts or "\\" in value or value.startswith("-"):
        raise ValueError(f"unsafe relative path: {value!r}")
    return value


def load_lock(path: Path) -> dict:
    doc = json.loads(path.read_text())
    if doc.get("schema") != 1 or set(doc.get("sources", {})) != {"client", "server"}:
        raise ValueError("unsupported source lock schema or source set")
    for name, source in doc["sources"].items():
        if not SHA.fullmatch(source["commit"]):
            raise ValueError(f"{name}: a full lowercase commit SHA is required")
        if source["url"] != f"https://github.com/Russianranger/{'wowdecomp_esteria' if name == 'client' else 'EsteriaWoW'}.git":
            raise ValueError(f"unexpected {name} source URL")
        for subpath, commit in source["submodules"].items():
            safe_relative(subpath)
            if not SHA.fullmatch(commit):
                raise ValueError("submodules must be pinned to full commit SHAs")
        for patch in source["patches"]:
            safe_relative(patch["path"])
            if not re.fullmatch(r"[0-9a-f]{64}", patch["sha256"]):
                raise ValueError("patch requires SHA-256")
    return doc


def patch_inputs(source: dict, root: Path) -> list[Path]:
    result = []
    for spec in source["patches"]:
        path = (root / spec["path"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("patch escaped project root")
        if hashlib.sha256(path.read_bytes()).hexdigest() != spec["sha256"]:
            raise ValueError(f"patch digest mismatch: {path}")
        result.append(path)
    return result


def verify_checkout(path: Path, source: dict, patches: list[Path]) -> None:
    if run("git", "rev-parse", "HEAD", cwd=path) != source["commit"]:
        raise ValueError(f"{path}: HEAD differs from lock; preserve this checkout and use a new output directory")
    # Expected modifications are exactly the indexed, pinned patches. Never reset.
    if run("git", "diff", "--name-only", cwd=path):
        raise ValueError(f"{path}: uncommitted source changes")
    if run("git", "ls-files", "--others", "--exclude-standard", cwd=path):
        raise ValueError(f"{path}: untracked source files")
    for subpath, commit in source["submodules"].items():
        module = path / subpath
        if run("git", "rev-parse", "HEAD", cwd=module) != commit:
            raise ValueError(f"{subpath}: incorrect pinned submodule")
        if run("git", "status", "--porcelain", cwd=module):
            raise ValueError(f"{subpath}: modified submodule")
    # Compare the index with a temporary index derived from HEAD plus the patches.
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"))
        subprocess.run(["git", "read-tree", "HEAD"], cwd=path, env=env, check=True)
        for patch in patches:
            subprocess.run(["git", "apply", "--cached", str(patch)], cwd=path, env=env, check=True)
        expected = subprocess.check_output(["git", "write-tree"], cwd=path, env=env, text=True).strip()
    actual = run("git", "write-tree", cwd=path)
    if expected != actual:
        raise ValueError(f"{path}: staged content differs from pinned patches")


def fetch(name: str, source: dict, output: Path, root: Path, offline: bool) -> None:
    path = output / name
    patches = patch_inputs(source, root)
    if path.exists():
        verify_checkout(path, source, patches)
        print(f"{name}: verified existing {source['commit']}")
        return
    if offline:
        raise ValueError(f"{name}: pinned source is unavailable offline")
    output.mkdir(parents=True, exist_ok=True)
    # Failed fetches stay visible for diagnosis; do not delete potentially useful work.
    subprocess.run(["git", "init", str(path)], check=True)
    run("git", "remote", "add", "origin", source["url"], cwd=path)
    run("git", "fetch", "--depth", "1", "origin", source["commit"], cwd=path)
    run("git", "checkout", "--detach", source["commit"], cwd=path)
    if source["submodules"]:
        run("git", "submodule", "update", "--init", "--recursive", "--depth", "1", cwd=path)
    for patch in patches:
        run("git", "apply", "--index", str(patch), cwd=path)
    verify_checkout(path, source, patches)
    print(f"{name}: prepared {source['commit']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("components", choices=["client", "server", "all"], nargs="?", default="all")
    parser.add_argument("--lock", type=Path, default=ROOT / "sources.lock.json")
    parser.add_argument("--output", type=Path, default=ROOT / "sources")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    doc = load_lock(args.lock)
    for name in (["client", "server"] if args.components == "all" else [args.components]):
        fetch(name, doc["sources"][name], args.output.resolve(), args.lock.parent, args.offline)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"source preparation failed: {exc}") from exc
