"""Receipts, and the pytest plugin that writes one after every test run."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from themis import receipts
from themis.proofs import World

A_TEST = "def test_one():\n    assert True\n\n\ndef test_two():\n    import pytest\n    pytest.skip('not today')\n"


def project(tmp_path: Path, manifest: bool = True) -> World:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    if manifest:
        world.manifest('[project]\nname = "demo"\n')
    world.write("test_demo.py", A_TEST)
    world.commit("start")
    return world


def pytest_in(world: World) -> int:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}  # so the run itself leaves no file behind
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=world.root,
                          env=env, capture_output=True, text=True, check=False).returncode


def test_a_clean_tree_is_named_by_its_commit_and_a_dirty_one_by_its_content(tmp_path: Path) -> None:
    world = project(tmp_path)
    clean = receipts.tree_fingerprint(world.root)
    assert clean == world.git("rev-parse", "HEAD^{tree}").strip()
    world.write("test_demo.py", A_TEST + "\n# changed\n")
    dirty = receipts.tree_fingerprint(world.root)
    assert dirty != clean and "+" in dirty
    world.write("test_demo.py", A_TEST + "\n# changed again\n")
    assert receipts.tree_fingerprint(world.root) != dirty


def test_a_folder_that_is_not_a_repository_has_nothing_to_pin_to(tmp_path: Path) -> None:
    assert receipts.tree_fingerprint(tmp_path) is None


def test_a_test_run_leaves_a_receipt_for_the_tree_it_ran_on(tmp_path: Path) -> None:
    world = project(tmp_path)
    assert pytest_in(world) == 0
    receipt = receipts.suite_for_tree(world.root)
    assert receipt is not None
    assert (receipt["passed"], receipt["failed"], receipt["skipped"]) == (1, 0, 1)
    assert receipt["skipped_tests"] == ["test_demo.py::test_two"]
    assert receipt["tree"] == receipts.tree_fingerprint(world.root)
    assert world.git("status", "--porcelain").strip() == "", "a local receipt must not dirty the tree"


def test_a_receipt_does_not_cover_a_tree_that_changed_afterwards(tmp_path: Path) -> None:
    world = project(tmp_path)
    pytest_in(world)
    world.write("test_demo.py", "def test_one():\n    assert False\n")
    assert receipts.suite_for_tree(world.root) is None


def test_a_folder_themis_does_not_guard_gets_no_receipt(tmp_path: Path) -> None:
    world = project(tmp_path, manifest=False)
    pytest_in(world)
    assert not (world.root / ".themis").exists()
