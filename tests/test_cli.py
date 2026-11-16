"""The command line, end to end: a call that checked nothing is never a pass."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest

import publish
import themis
from themis.cli import EXIT_FAIL, EXIT_PASS, EXIT_REFUSE, main
from themis.proofs import World

ROOT = Path(__file__).resolve().parents[1]

WITH_CHECK = """
[project]
name = "demo"

[[checks.external]]
id = "ext/no-todo"
description = "The notes hold no TODO"
command = ["{python}", "tools/no_todo.py"]

[[checks.external.proofs]]
name = "a TODO is caught"
plant = {{ file = "notes.md", append = "TODO: later\\n" }}
expect = "fail"
expect_output = "TODO found"

[[checks.external.proofs]]
name = "clean notes pass"
expect = "pass"
"""
NO_TODO = """
import pathlib, sys
if "TODO" in pathlib.Path("notes.md").read_text():
    print("notes.md:1: TODO found")
    sys.exit(1)
"""


def project(tmp_path: Path) -> World:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.write("notes.md", "all done\n")
    world.write("tools/no_todo.py", NO_TODO)
    world.manifest(WITH_CHECK.format(python=sys.executable))
    world.commit("start")
    return world


def run(world: World, *args: str) -> int:
    return main([args[0], "--root", str(world.root), *args[1:]])


def test_version_flag_prints_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["--version"])
    assert stopped.value.code == 0
    assert capsys.readouterr().out.strip() == f"themis {themis.__version__}"


def test_a_bare_call_refuses(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_REFUSE
    assert "nothing was checked" in capsys.readouterr().err.lower()


def test_a_folder_with_no_manifest_refuses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "--root", str(tmp_path)]) == EXIT_REFUSE
    assert "nothing was checked" in capsys.readouterr().err.lower()


def test_init_writes_a_manifest_that_checks_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["init", "--root", str(tmp_path)]) == EXIT_PASS
    assert (tmp_path / "themis.toml").is_file()
    assert main(["check", "--root", str(tmp_path)]) == EXIT_PASS
    assert main(["init", "--root", str(tmp_path)]) == EXIT_PASS  # a second init changes nothing
    assert "left as it is" in capsys.readouterr().out


def test_check_passes_on_clean_work_and_fails_on_a_breach(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = project(tmp_path)
    assert run(world, "check") == EXIT_PASS
    world.write("notes.md", "TODO: finish\n")
    assert run(world, "check") == EXIT_FAIL
    assert "TODO found" in capsys.readouterr().out


def test_check_writes_the_reports_it_is_asked_for(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = project(tmp_path)
    world.write("notes.md", "TODO: finish\n")
    assert run(world, "check", "--reporter", "compact", "--reporter", "json:out/report.json") == EXIT_FAIL
    assert "error themis[ext/no-todo]" in capsys.readouterr().out
    document = json.loads((world.root / "out/report.json").read_text())
    assert document["verdict"] == "fail"


def test_prove_plants_the_fault_in_a_copy_and_leaves_the_project_alone(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = project(tmp_path)
    assert run(world, "prove", "ext/no-todo") == EXIT_PASS
    out = capsys.readouterr().out
    assert "a TODO is caught" in out and "2 of 2 proofs held" in out
    assert (world.root / "notes.md").read_text() == "all done\n"


def test_prove_fails_when_a_check_has_gone_blind(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = project(tmp_path)
    world.write("tools/no_todo.py", "raise SystemExit(0)\n")  # the check now passes everything
    assert run(world, "prove", "ext/no-todo") == EXIT_FAIL
    assert "expected fail, got pass" in capsys.readouterr().out


def test_prove_requires_the_check_to_fail_for_the_planted_reason(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = project(tmp_path)
    world.write("tools/no_todo.py", "print('something else broke')\nraise SystemExit(1)\n")
    assert run(world, "prove", "ext/no-todo") == EXIT_FAIL
    assert "does not match" in capsys.readouterr().out


def test_describe_lists_rules_and_says_what_is_unproven(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = project(tmp_path)
    assert run(world, "describe") == EXIT_PASS
    out = capsys.readouterr().out
    assert "config/locked" in out and "ext/no-todo" in out and "proven" in out
    assert "their silence is not a pass" in out


def test_explain_gives_the_promise_and_the_reason(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "order/sealed-first", "--root", str(tmp_path)]) == EXIT_PASS
    out = capsys.readouterr().out
    assert "earlier merge" in out and "Why it exists" in out and "work (required)" in out
    assert main(["explain", "no/such-rule", "--root", str(tmp_path)]) == EXIT_REFUSE


def test_config_diff_names_a_weakening_and_lock_then_holds(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = project(tmp_path)
    assert run(world, "config", "diff") == EXIT_PASS
    world.manifest(WITH_CHECK.format(python=sys.executable).replace('description = "The notes hold no TODO"',
                                                                    'description = "The notes hold no TODO"\nlevel = "warn"'))
    assert run(world, "config", "diff") == EXIT_FAIL
    assert "level enforce to warn" in capsys.readouterr().out
    assert run(world, "config", "lock") == EXIT_PASS
    assert run(world, "check", "config/locked") == EXIT_PASS


def test_the_version_has_one_home() -> None:
    """pyproject.toml must not restate the version; the pipeline and the package read one line."""
    project_table = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert "version" not in project_table
    assert "version" in project_table["dynamic"]
    init_text = (ROOT / publish.VERSION_FILE).read_text(encoding="utf-8")
    assert publish.read_version(init_text) == themis.__version__
