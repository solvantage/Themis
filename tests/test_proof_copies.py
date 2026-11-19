"""A proof's copy of a repository holds what git would carry, and has a git folder of its own.

Ignored data (a results cache, a second environment) never goes into a copy, however large. A plant
can stage the file it changes, so a check that reads only what is staged can be proven too; the
staging reaches the copy, never the original.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from themis import manifest as manifests
from themis import proofs
from themis.proofs import World
from themis.verdict import Verdict

CHECK = """
import subprocess, sys
staged = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True).stdout.split()
bad = [name for name in staged if name.endswith(".secret")]
for name in bad:
    print(f"{name}: a secrets file is staged")
sys.exit(1 if bad else 0)
"""


def a_project(tmp_path: Path) -> World:
    """A plain docs-and-scripts project: tracked pages, an untracked draft, ignored data."""
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.write(".gitignore", "data/\n*.log\n")
    world.write("README.md", "# Notes\n")
    world.write("scripts/staged_guard.py", CHECK)
    world.commit("start")
    world.write("docs/draft.md", "not committed yet\n")
    world.write("data/big.bin", "x" * 10000)
    world.write("run.log", "noise\n")
    return world


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def test_a_copy_holds_the_tracked_and_the_untracked_files_and_leaves_ignored_ones_behind(tmp_path: Path) -> None:
    world = a_project(tmp_path)
    copy = proofs.copy_repository(world.root, tmp_path / "copies")
    held = sorted(path.relative_to(copy).as_posix() for path in copy.rglob("*")
                  if path.is_file() and ".git" not in path.relative_to(copy).parts)
    assert held == [".gitignore", "README.md", "docs/draft.md", "scripts/staged_guard.py"]
    assert git(copy, "log", "--format=%s").split("\n")[0] == "start"
    assert (world.root / "data/big.bin").is_file()  # the original is untouched


def test_staging_in_a_copy_never_reaches_the_original(tmp_path: Path) -> None:
    world = a_project(tmp_path)
    copy = proofs.copy_repository(world.root, tmp_path / "copies")
    proofs.stage_plant(copy, {"file": "docs/draft.md"})
    assert "docs/draft.md" in git(copy, "diff", "--cached", "--name-only")
    assert git(world.root, "diff", "--cached", "--name-only") == ""


def test_a_copy_of_a_linked_worktree_is_a_repository_of_its_own(tmp_path: Path) -> None:
    world = a_project(tmp_path)
    world.commit("the draft")
    linked = tmp_path / "linked"
    git(world.root, "worktree", "add", "-q", "-b", "side", str(linked))
    (linked / "side.md").write_text("on the side branch\n", encoding="utf-8")
    copy = proofs.copy_repository(linked, tmp_path / "copies")
    assert (copy / ".git").is_dir()
    assert git(copy, "rev-parse", "--abbrev-ref", "HEAD").strip() == "side"
    assert git(copy, "status", "--porcelain").strip() == "?? side.md"
    proofs.stage_plant(copy, {"file": "side.md"})
    assert git(linked, "diff", "--cached", "--name-only") == ""
    assert "worktrees" not in {path.name for path in (copy / ".git").iterdir()}


def test_a_folder_that_is_not_a_repository_is_copied_whole(tmp_path: Path) -> None:
    folder = tmp_path / "plain"
    (folder / "docs").mkdir(parents=True)
    (folder / "docs/page.md").write_text("a page\n", encoding="utf-8")
    (folder / "__pycache__").mkdir()
    (folder / "__pycache__/x.pyc").write_text("", encoding="utf-8")
    copy = proofs.copy_repository(folder, tmp_path / "copies")
    assert (copy / "docs/page.md").is_file() and not (copy / "__pycache__").exists()


MANIFEST = """
[project]
name = "notes"

[[checks.external]]
id = "ext/staged-guard"
description = "No secrets file is staged."
command = ["{python}", "-I", "scripts/staged_guard.py"]

[[checks.external.proofs]]
name = "a staged secrets file is caught"
plant = {{ file = "keys.secret", content = "planted\\n", stage = true }}
expect = "fail"
expect_output = "keys\\\\.secret: a secrets file is staged"

[[checks.external.proofs]]
name = "the same file left unstaged is not this check's business"
plant = {{ file = "keys.secret", content = "planted\\n" }}
expect = "pass"
"""


def test_a_plant_that_stages_proves_a_check_that_reads_only_what_is_staged(tmp_path: Path) -> None:
    world = a_project(tmp_path)
    world.manifest(MANIFEST.format(python=sys.executable))
    world.commit("the check")
    manifest = manifests.load(world.root)
    assert manifest.problems == []
    outcomes = proofs.run_external(manifest)
    assert [(outcome.held, outcome.actual) for outcome in outcomes] == [(True, Verdict.FAIL), (True, Verdict.PASS)]
    assert git(world.root, "diff", "--cached", "--name-only") == ""


def test_stage_is_true_or_false(tmp_path: Path) -> None:
    world = a_project(tmp_path)
    world.manifest(MANIFEST.format(python=sys.executable).replace("stage = true", 'stage = "yes"'))
    assert any("stage must be true or false" in problem for problem in manifests.load(world.root).problems)
