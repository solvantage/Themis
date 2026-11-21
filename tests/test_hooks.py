"""Attacks on the agent hooks: what they must stop, what they must leave alone, and planted bugs.

A hook that stops too little is no guard, and one that stops too much gets switched off. So this
file holds both tables: commands that must be sent to the owner, and everyday commands that must
pass untouched. Then the hook's own source is broken one line at a time, in memory, and each
planted bug must flip the one case that names it.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from themis import hooks
from themis.proofs import World

SOURCE = Path(hooks.__file__).read_text(encoding="utf-8")
PROTECTED = ["themis.toml", "themis.lock", "grants/**", "receipts/**", ".claude/settings.json", "tools/check.py"]

#: (the command, a word the reason must hold)
MUST_ASK = [
    ("rm notes.md", "deletes"),
    ("rm -rf build", "deletes"),
    ("cd src && rm old.py", "deletes"),
    ("ls; rmdir empty", "deletes"),
    ("/bin/rm notes.md", "deletes"),
    ("sudo rm notes.md", "deletes"),
    ("sudo -u someone rm notes.md", "deletes"),
    ("find . -name '*.tmp' | xargs rm", "deletes"),
    ("find . -name '*.tmp' | xargs -n 1 rm", "deletes"),
    ("find . -name '*.pyc' -delete", "deletes"),
    ("find . -name '*.pyc' -exec rm {} +", "deletes"),
    ("FOO=1 rm notes.md", "deletes"),
    ("echo $(rm notes.md)", "deletes"),
    ("bash -c 'rm -rf build'", "deletes"),
    ("shred secrets.txt", "deletes"),
    ("git rm notes.md", "deletes"),
    ("git clean -fdx", "deletes"),
    ("git -C /somewhere clean -fdx", "deletes"),
    ("git -c core.pager=cat rm notes.md", "deletes"),
    ("git branch -d feature", "deletes a branch"),  # no repository here proves the main line holds it
    ("git branch -D feature", "deletes a branch"),
    ("git -C /somewhere branch --delete feature", "deletes a branch"),
    ("git branch -dr origin/feature", "deletes a branch"),
    ("git push origin --delete feature", "remote"),
    ("git push origin :feature", "remote"),
    ("git push --force origin main", "remote"),
    ("git push -f", "remote"),
    ("git push --force-with-lease origin main", "remote"),
    ("git push origin +main", "remote"),
    ("ssh host uptime", "remote machine"),
    ("scp file host:/tmp/", "remote machine"),
    ("themis grant publish video-1", "Only the owner"),
    ("uv run themis grant config", "Only the owner"),
    ("uv run --quiet themis grant spend --ceiling 500", "Only the owner"),
    ("python -m themis grant holdout", "Only the owner"),
    (".venv/bin/themis grant publish x", "Only the owner"),
    ("themis decide study-a --gate entry --by owner --decision keep --verdict pass --reason because", "overrules a gate"),
    ("uv run themis attest content/a/brief.toml true-result --judge owner --by owner", "attests as the owner"),
    ("themis attest content/a/plan.toml visual --judge=owner --by me", "attests as the owner"),
    ("uv run themis decide study-a --gate entry --by=owner --decision keep --verdict pass --reason x", "overrules a gate"),
    ("echo 'x = 1' > themis.toml", "themis.toml"),
    ("echo '{}' >> .claude/settings.json", ".claude/settings.json"),
    ("cp /tmp/new.toml themis.toml", "themis.toml"),
    ("mv draft.toml grants/config-1.toml", "grants/config-1.toml"),
    ("sed -i '' 's/enforce/warn/' themis.toml", "themis.toml"),
    ("tee themis.lock < /dev/null", "themis.lock"),
    ("touch receipts/suite/fake.json", "receipts/suite/fake.json"),
    ("printf 'raise SystemExit(0)' > tools/check.py", "tools/check.py"),
    ("echo 'unbalanced", "cannot read"),
]

MUST_PASS = [
    "ls -la",
    "git status",
    "git log --oneline -5",
    "git diff main -- themis.toml",
    "cat themis.toml",
    "grep -n enforce themis.toml",
    "git branch feature",
    "git branch -v",
    "git branch --list 'feat/*'",
    "cp themis.toml /tmp/themis-copy.toml",  # a copy reads its source
    "git push origin feature",
    "git push -u origin feature",
    "git commit -m 'rm the old path'",
    "git log --grep 'branch -d'",
    "echo 'rm -rf /' is dangerous",
    "uv run pytest -q",
    "uv run themis check",
    "uv run themis check --changed --reporter json:out.json",
    "themis describe",
    "themis config diff",
    "themis decide study-a --gate entry",
    "themis attest content/a/brief.toml no-cure --judge agent --by writer",
    "uv run themis decide study-a --gate entry --by gate",
    "python -m pytest tests/test_grant.py",
    "echo hello > notes.md",
    "cp notes.md docs/notes.md",
    "sed -n '1,5p' themis.toml",
    "mkdir -p reports && echo ok > reports/out.txt",
    "find . -name '*.py' -newer themis.toml",
    "env | grep PATH",
    "printf 'grant me patience'",
]


@pytest.mark.parametrize(("command", "said"), MUST_ASK, ids=[case[0] for case in MUST_ASK])
def test_a_risky_command_is_sent_to_the_owner(command: str, said: str, tmp_path: Path) -> None:
    reason = hooks.judge_command(command, tmp_path, PROTECTED)
    assert reason is not None and said in reason, f"{command!r} was let through, or stopped for another reason: {reason}"


@pytest.mark.parametrize("command", MUST_PASS)
def test_an_everyday_command_is_left_alone(command: str, tmp_path: Path) -> None:
    assert hooks.judge_command(command, tmp_path, PROTECTED) is None


# --- the hooks, as the host calls them ---------------------------------------------------------


def project(tmp_path: Path, manifest: str = '[rules]\n"config/locked" = "enforce"\n') -> World:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest(manifest)
    world.commit("start")
    return world


def test_an_edit_to_a_protected_file_asks_and_another_edit_does_not(tmp_path: Path) -> None:
    world = project(tmp_path)
    for tool, key in (("Write", "file_path"), ("Edit", "file_path"), ("NotebookEdit", "notebook_path")):
        asked = hooks.pretool({"tool_name": tool, "tool_input": {key: str(world.root / "themis.toml")}}, world.root)
        assert asked["hookSpecificOutput"]["permissionDecision"] == "ask"
        assert "themis.toml" in asked["hookSpecificOutput"]["permissionDecisionReason"]
    assert hooks.pretool({"tool_name": "Write", "tool_input": {"file_path": str(world.root / "notes.md")}}, world.root) is None
    assert hooks.pretool({"tool_name": "Read", "tool_input": {"file_path": str(world.root / "themis.toml")}}, world.root) is None


def test_the_script_an_external_check_runs_is_protected(tmp_path: Path) -> None:
    world = project(tmp_path, f'[[checks.external]]\nid = "ext/x"\ndescription = "d"\ncommand = ["{sys.executable}", "tools/check.py"]\n')
    world.write("tools/check.py", "raise SystemExit(0)\n")
    asked = hooks.pretool({"tool_name": "Edit", "tool_input": {"file_path": "tools/check.py"}}, world.root)
    assert asked is not None and "tools/check.py" in asked["hookSpecificOutput"]["permissionDecisionReason"]


def test_every_hook_is_silent_where_there_is_no_manifest(tmp_path: Path) -> None:
    assert hooks.pretool({"tool_name": "Bash", "tool_input": {"command": "rm -rf everything"}}, tmp_path) is None
    assert hooks.stop({"session_id": "s"}, tmp_path) == (0, "", "")
    hooks.start({"session_id": "s"}, tmp_path)
    assert not (tmp_path / ".themis").exists()


def test_a_new_breach_keeps_the_turn_open_with_a_reason(tmp_path: Path) -> None:
    world = project(tmp_path, '[project]\nname = "w"\n')
    hooks.start({"session_id": "s"}, world.root)
    assert hooks.stop({"session_id": "s"}, world.root) == (0, "", "")
    world.manifest('[rules]\n"config/locked" = "enforce"\n')  # the work now breaks an enforced rule
    code, for_agent, _ = hooks.stop({"session_id": "s"}, world.root)
    assert code == 2 and "themis[config/locked]" in for_agent and "FAIL" in for_agent


def test_a_breach_from_before_the_session_warns_and_does_not_block(tmp_path: Path) -> None:
    world = project(tmp_path)  # config/locked already fails: there is no lock
    hooks.start({"session_id": "s"}, world.root)
    code, for_agent, for_owner = hooks.stop({"session_id": "s"}, world.root)
    assert code == 0 and for_agent == "" and "existed before this session" in for_owner


def test_the_turn_is_released_after_three_blocks_and_says_it_is_not_verified(tmp_path: Path) -> None:
    world = project(tmp_path)
    codes = [hooks.stop({"session_id": "s"}, world.root)[0] for _ in range(hooks.MAX_BLOCKS)]
    assert codes == [2, 2, 2]
    code, for_agent, for_owner = hooks.stop({"session_id": "s"}, world.root)
    assert code == 0 and for_agent == "" and "NOT verified" in for_owner


def test_a_fixed_breach_ends_the_turn(tmp_path: Path) -> None:
    world = project(tmp_path)
    assert hooks.stop({"session_id": "s"}, world.root)[0] == 2
    from themis import configguard
    from themis import manifest as manifests

    configguard.write_lock(manifests.load(world.root))
    assert hooks.stop({"session_id": "s"}, world.root) == (0, "", "")


# --- installing --------------------------------------------------------------------------------


def test_installing_adds_the_three_hooks_once_and_keeps_other_settings(tmp_path: Path) -> None:
    world = project(tmp_path)
    world.write(hooks.SETTINGS, json.dumps({"permissions": {"deny": ["Tool"]}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}))
    assert hooks.missing(world.root) == ["PreToolUse", "SessionStart", "Stop"]
    hooks.install(world.root, "themis")
    hooks.install(world.root, "themis")  # a second install adds nothing
    settings = json.loads((world.root / hooks.SETTINGS).read_text())
    assert hooks.missing(world.root) == []
    assert settings["permissions"] == {"deny": ["Tool"]}
    assert [hook["command"] for entry in settings["hooks"]["Stop"] for hook in entry["hooks"]] == ["echo mine", "themis hook stop"]
    assert len(settings["hooks"]["PreToolUse"]) == 1


def test_a_project_run_with_uv_gets_hooks_that_run_through_uv(tmp_path: Path) -> None:
    world = project(tmp_path)
    world.write("uv.lock", "")
    assert hooks.default_command(world.root) == "uv run --frozen --quiet themis"


# --- planted bugs ------------------------------------------------------------------------------

#: (name, the line as it stands, the line broken, the command whose answer must flip)
PLANTS = [
    ("deletes are let through", "if program in DELETERS or behind & DELETERS:", "if False:", "rm notes.md"),
    ("a wrapper hides the delete", "behind = names if leading & WRAPPERS", "behind = set() if True else names if leading & WRAPPERS",
     "sudo -u someone rm notes.md"),
    ("remote commands are let through", "if program in REMOTES or behind & REMOTES:", "if False:", "ssh host uptime"),
    ("a command inside a shell string is not read", "        if code is not None:", "        if False:", "bash -c 'rm -rf build'"),
    ("git's options hide the subcommand", "index += 2 if args[index] in GIT_VALUED else 1  # an option's value",
     "index += 1  # an option's value", "git -C /somewhere clean -fdx"),
    ("a forced push is let through", 'or _short(flag, "df")', 'or _short(flag, "d")', "git push -f"),
    ("a branch delete is let through", 'if sub == "branch" and any(_long(flag, "delete")', 'if sub == "no-such" and any(_long(flag, "delete")',
     "git branch -D feature"),
    ("an agent may grant itself", 'if asked == "grant":', "if False:", "uv run themis grant config"),
    ("a redirect into a protected file is let through", "reason = _write_danger(redirect.target, cwd, ctx)", "reason = None",
     "echo 'x = 1' > themis.toml"),
    ("an in-place edit of a protected file is let through", 'if _short(arg, "i"):', "if False:", "sed -i '' 's/enforce/warn/' themis.toml"),
    ("an unreadable command is let through", "reading.danger or (UNREADABLE if reading.unreadable else None)", "reading.danger",
     "echo 'unbalanced"),
]


def planted(old: str, new: str) -> types.ModuleType:
    assert SOURCE.count(old) == 1, f"the plant's target must occur exactly once: {old!r}"
    module = types.ModuleType("planted_hooks")
    module.__file__ = hooks.__file__
    sys.modules[module.__name__] = module  # a dataclass looks its module up while it is built
    try:
        exec(compile(SOURCE.replace(old, new), "<planted hooks.py>", "exec"), module.__dict__)  # noqa: S102
    finally:
        del sys.modules[module.__name__]
    return module


@pytest.mark.parametrize(("name", "old", "new", "command"), PLANTS, ids=[plant[0] for plant in PLANTS])
def test_each_planted_bug_lets_through_the_command_that_names_it(name: str, old: str, new: str, command: str, tmp_path: Path) -> None:
    assert hooks.judge_command(command, tmp_path, PROTECTED) is not None, "no false alarm: the real hook stops this"
    assert planted(old, new).judge_command(command, tmp_path, PROTECTED) is None, f"the planted bug {name!r} was not caught"
