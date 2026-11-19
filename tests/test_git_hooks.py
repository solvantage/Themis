"""The hooks find the project, and the git hooks run Themis on every commit and push.

All in a plain docs-and-scripts project: nothing here is a field's work.
"""

from __future__ import annotations

import io
import json
import shlex
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from themis import hooks
from themis.cli import EXIT_PASS, EXIT_REFUSE, main
from themis.proofs import World

MANIFEST = '[project]\nname = "notes"\n\n[agents]\ngit_hooks = ".githooks"\n'
RUN_WITH = f"{shlex.quote(sys.executable)} -m themis.cli"


def a_project(tmp_path: Path, manifest: str = MANIFEST) -> World:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest(manifest)
    world.write("docs/README.md", "# Notes\n")
    world.write("scripts/build.sh", "echo built\n")
    world.write(".gitignore", ".themis/\n")
    world.commit("start")
    return world


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


# --- which project a hook judges ---------------------------------------------------------------


def test_the_project_is_the_root_given_then_the_hosts_folder_then_the_nearest_manifest(tmp_path: Path) -> None:
    world = a_project(tmp_path)
    (world.root / "docs/deep").mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert hooks.project_root("/given", "/host", str(elsewhere)) == Path("/given").resolve()
    assert hooks.project_root(None, str(world.root), str(elsewhere)) == world.root.resolve()
    assert hooks.project_root(None, None, str(world.root / "docs/deep")) == world.root.resolve()
    assert hooks.project_root(None, None, str(elsewhere)) == elsewhere.resolve()


def ask(world: World, payload: dict, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        *flags: str) -> str:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert main(["hook", "pretool", *flags]) == EXIT_PASS
    return capsys.readouterr().out


def test_from_a_shell_outside_the_project_a_protected_edit_still_asks(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    world = a_project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    edit = {"cwd": str(outside), "tool_name": "Edit", "tool_input": {"file_path": str(world.root / "themis.toml")}}
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    assert ask(world, edit, monkeypatch, capsys) == ""  # 0.1.0's answer: no manifest where the shell is
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(world.root))
    assert "protected file" in ask(world, edit, monkeypatch, capsys)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR")
    assert "protected file" in ask(world, edit, monkeypatch, capsys, "--root", str(world.root))


def test_a_commands_relative_paths_are_read_from_the_shells_folder(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    world = a_project(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(world.root))
    inside = {"cwd": str(world.root / "docs"), "tool_name": "Bash"}
    up = ask(world, {**inside, "tool_input": {"command": "echo x > ../themis.toml"}}, monkeypatch, capsys)
    assert "writes to themis.toml" in up
    here = ask(world, {**inside, "tool_input": {"command": "echo x > themis.toml"}}, monkeypatch, capsys)
    assert here == ""  # docs/themis.toml is not the manifest


# --- the git hooks -----------------------------------------------------------------------------


def install(world: World, *flags: str) -> int:
    return main(["hooks", "install", "--git", "--root", str(world.root), "--run-with", RUN_WITH, *flags])


def test_installing_the_git_hooks_writes_both_and_points_git_at_them(tmp_path: Path) -> None:
    world = a_project(tmp_path)
    assert install(world) == EXIT_PASS
    for event, check in (("pre-commit", "check --changed"), ("pre-push", "check")):
        path = world.root / ".githooks" / event
        assert path.read_text().rstrip().endswith(f"{RUN_WITH} {check}")
        assert path.stat().st_mode & stat.S_IXUSR
    assert git(world.root, "config", "core.hooksPath").stdout.strip() == ".githooks"
    assert hooks.git_missing(world.root, ".githooks") == []
    assert install(world) == EXIT_PASS  # the same hooks again: nothing to refuse


def test_another_folder_can_hold_them(tmp_path: Path) -> None:
    world = a_project(tmp_path)
    assert install(world, "--path", "tools/hooks") == EXIT_PASS
    assert git(world.root, "config", "core.hooksPath").stdout.strip() == "tools/hooks"
    assert (world.root / "tools/hooks/pre-push").is_file()


def test_a_different_hook_is_kept_unless_forced(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = a_project(tmp_path)
    world.write(".githooks/pre-commit", "#!/bin/sh\necho mine\n")
    assert install(world) == EXIT_REFUSE
    assert "already holds a different hook" in capsys.readouterr().err
    assert (world.root / ".githooks/pre-commit").read_text() == "#!/bin/sh\necho mine\n"
    assert not (world.root / ".githooks/pre-push").exists()
    assert install(world, "--force") == EXIT_PASS
    assert "themis.cli check --changed" in (world.root / ".githooks/pre-commit").read_text()


def test_a_folder_that_is_not_a_repository_gets_no_git_hooks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = tmp_path / "plain"
    folder.mkdir()
    (folder / "themis.toml").write_text('[project]\nname = "plain"\n', encoding="utf-8")
    assert main(["hooks", "install", "--git", "--root", str(folder)]) == EXIT_REFUSE
    assert "not a git repository" in capsys.readouterr().err


def test_the_pre_commit_hook_stops_a_commit_that_breaks_an_enforced_rule(tmp_path: Path) -> None:
    world = a_project(tmp_path)
    assert install(world) == EXIT_PASS
    world.commit("the hooks")  # a clean check: the commit goes in
    world.manifest(MANIFEST + "\n[unknown]\nkey = 1\n")  # config/valid is enforced and refuses
    with pytest.raises(RuntimeError, match="failed"):
        world.commit("a manifest that is not valid")
    assert git(world.root, "log", "--format=%s", "-1").stdout.strip() == "the hooks"


def test_the_rule_checks_the_declared_git_hooks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = a_project(tmp_path)
    report = ["check", "--root", str(world.root), "agents/hooks-installed", "--reporter", "json"]
    main(report)
    first = json.loads(capsys.readouterr().out)["results"][0]
    assert first["verdict"] == "fail" and "pre-commit git hook is not installed" in json.dumps(first["findings"])
    assert install(world) == EXIT_PASS
    capsys.readouterr()
    main(report)
    assert json.loads(capsys.readouterr().out)["results"][0]["verdict"] == "pass"


def test_doctor_names_git_hooks_that_are_declared_and_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = a_project(tmp_path)
    assert main(["doctor", "--root", str(world.root)]) == EXIT_REFUSE
    assert "run `themis hooks install --git`" in capsys.readouterr().out
