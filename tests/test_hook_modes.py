"""The before-a-tool-call hook's two modes: "ask" and "allow-unless".

"ask", the default, asks for what is dangerous and says nothing about the rest. "allow-unless"
answers allow when nothing needs the owner, and still asks for every danger, every kept file, the
project's ask patterns and the host's own ask list, and denies what either side denies. Both run
here as the host calls them, in a small notes project with no pack, with a temp folder of its own
named by $TMPDIR. Then the hook's source is broken one line at a time, and each planted bug must
change the answer of the case that names it.
"""

from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from themis import configguard, hooks
from themis import manifest as manifests
from themis.cli import EXIT_PASS, EXIT_REFUSE, main
from themis.proofs import World

SOURCE = Path(hooks.__file__).read_text(encoding="utf-8")
ALLOW = 'pretool = "allow-unless"\n'
MODES = {"ask": "", "allow-unless": ALLOW}


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp folder outside the project, named by $TMPDIR as an agent's shell would see it."""
    folder = tmp_path / "scratch"
    folder.mkdir()
    monkeypatch.setenv("TMPDIR", str(folder))
    monkeypatch.delenv("NO_SUCH_VARIABLE", raising=False)
    return folder


def project(tmp_path: Path, agents: str = "", settings: dict[str, Any] | None = None) -> World:
    world = World(tmp_path / "repo")
    world.root.mkdir(parents=True)
    world.manifest('[project]\nname = "notes"\n\n[agents]\nhost = "claude"\n' + agents)
    world.write("notes.md", "notes\n")
    for name, data in (settings or {}).items():
        world.write(name, data if isinstance(data, str) else json.dumps(data))
    world.commit("start")
    return world


def placed(command: str, world: World, scratch: Path) -> str:
    return (command.replace("<root>", str(world.root)).replace("<scratch>", str(scratch))
            .replace("<above>", str(world.root.parent)))


def answer(world: World, scratch: Path, command: str, cwd: str | None = None, module: Any = hooks) -> tuple[str, str]:
    """(the decision, its reason) for a shell command; ("none", "") when the hook says nothing."""
    payload: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": placed(command, world, scratch)}}
    if cwd:
        payload["cwd"] = placed(cwd, world, scratch)
    said = module.pretool(payload, world.root)
    if not said:
        return "none", ""
    out = said["hookSpecificOutput"]
    return out["permissionDecision"], out["permissionDecisionReason"]


def edit(world: World, path: str, tool: str = "Write", module: Any = hooks) -> str:
    said = module.pretool({"tool_name": tool, "tool_input": {"file_path": str(world.root / path)}}, world.root)
    return said["hookSpecificOutput"]["permissionDecision"] if said else "none"


# --- each kind of danger asks in a repository path, in both modes ------------------------------

#: (the command, a word the reason must hold)
DANGERS = [
    ("rm notes.md", "deletes"),
    ("rm -rf build", "deletes"),
    ("rmdir empty", "deletes"),
    ("unlink notes.md", "deletes"),
    ("shred notes.md", "deletes"),
    ("rm <root>/notes.md", "deletes"),
    ("rm -rf /srv/notes-copy", "deletes"),
    ("rm -rf $NO_SUCH_VARIABLE/x", "deletes"),
    ("find . -name '*.tmp' | xargs rm", "deletes"),
    ("git rm notes.md", "deletes"),
    ("git clean -fdx", "deletes"),
    ("git -C <root> clean -fdx", "deletes"),
    ("find . -name '*.pyc' -delete", "deletes"),
    ("find . -name '*.pyc' -exec rm {} +", "deletes"),
    ("git worktree remove /srv/wt", "deletes"),
    ("git worktree remove --force", "deletes"),
    ("git branch -d feature", "deletes a branch"),
    ("git branch -D feature", "deletes a branch"),
    ("git branch --delete feature", "deletes a branch"),
    ("git push origin --delete feature", "remote"),
    ("git push origin :feature", "remote"),
    ("git push --force origin main", "remote"),
    ("git reset --hard", "throws away work"),
    ("git reset --hard HEAD~1", "throws away work"),
    ("git stash drop", "throws away work"),
    ("git stash clear", "throws away work"),
    ("git checkout -- notes.md", "throws away work"),
    ("git checkout .", "throws away work"),
    ("git checkout -f main", "throws away work"),
    ("git switch --discard-changes main", "throws away work"),
    ("git restore notes.md", "throws away work"),
    ("git restore --staged --worktree notes.md", "throws away work"),
    ("git restore -SW notes.md", "throws away work"),
    ("ssh host uptime", "remote machine"),
    ("scp notes.md host:/srv/", "remote machine"),
    ("sftp host", "remote machine"),
    ("themis grant publish site", "Only the owner"),
    ("themis decide a --gate entry --by owner", "overrules a gate"),
    ("themis attest a.toml row --judge owner", "attests as the owner"),
    ("echo x > themis.toml", "themis.toml"),
    ("cp draft.json .claude/settings.json", ".claude/settings.json"),
    ("ls\nrm notes.md", "deletes"),
    ("ls # a note, isn't it\nrm notes.md", "deletes"),
    ("{ rm notes.md; }", "deletes"),
    ("if true; then rm notes.md; fi", "deletes"),
    ("eval 'rm notes.md'", "deletes"),
    ("rm -rf /tmp", "deletes"),
    ("rm -rf <above>", "deletes"),
    ("rm -rf <scratch>/../repo", "deletes"),
]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(("command", "said"), DANGERS, ids=[case[0] for case in DANGERS])
def test_each_danger_asks_in_both_modes(command: str, said: str, mode: str, tmp_path: Path, scratch: Path) -> None:
    decision, reason = answer(project(tmp_path, MODES[mode]), scratch, command)
    assert decision == "ask" and said in reason, (decision, reason)


#: Everyday commands: allowed in allow-unless, left to the host in ask.
EVERYDAY = [
    "ls -la",
    "git status",
    "uv run pytest -q",
    "echo hello > notes.md",
    "git commit -m 'rm the old path'",
    "echo 'rm -rf /' is dangerous",
    "git restore --staged notes.md",
    "git checkout main",
    "git checkout -b topic",
    "git stash",
    "git stash pop",
    "git reset --soft HEAD~1",
    "git reset notes.md",
    "git push origin feature",
    "git branch -v",
    "cat themis.toml",
    "python -c 'print(1)'",
    "for f in a b; do echo $f; done",
    'echo "$(date)"',
    "cat <<'EOF'\nhello\nEOF",
    "cat > <scratch>/note.txt <<'EOF'\nhello\nEOF",
]


@pytest.mark.parametrize("command", EVERYDAY)
def test_an_everyday_command_is_allowed_or_left_to_the_host(command: str, tmp_path: Path, scratch: Path) -> None:
    assert answer(project(tmp_path, ALLOW), scratch, command)[0] == "allow"
    assert answer(project(tmp_path / "plain"), scratch, command)[0] == "none"


# --- temp folders ------------------------------------------------------------------------------

SCRATCH_WORK = [
    "rm -rf <scratch>/clone",
    "rm -rf $TMPDIR/clone",
    'rm -rf "${TMPDIR}/clone" <scratch>/other',
    "rm -rf /tmp/themis-hook-test-clone",
    "cd <scratch> && rm -rf clone",
    "cd <scratch>/clone && git clean -fdx && git reset --hard",
    "git -C <scratch>/clone branch -D topic",
    "git worktree remove --force <scratch>/wt",
    "find <scratch>/clone -name '*.pyc' -delete",
    "bash -c 'cd <scratch> && rm -rf clone'",
]


@pytest.mark.parametrize("command", SCRATCH_WORK)
def test_a_delete_inside_a_temp_folder_is_allowed_and_still_asks_in_ask_mode(command: str, tmp_path: Path,
                                                                             scratch: Path) -> None:
    assert answer(project(tmp_path, ALLOW), scratch, command) == (
        "allow", 'Themis: Nothing in this command needs the owner (pretool = "allow-unless").')
    assert answer(project(tmp_path / "plain"), scratch, command)[0] == "ask"


def test_a_delete_with_one_target_outside_the_temp_folders_asks(tmp_path: Path, scratch: Path) -> None:
    world = project(tmp_path, ALLOW)
    assert answer(world, scratch, "rm -rf <scratch>/clone notes.md")[0] == "ask"
    assert answer(world, scratch, "rm -rf <scratch>/clone /srv/x")[0] == "ask"


def test_a_project_inside_a_temp_folder_is_not_scratch(tmp_path: Path, scratch: Path) -> None:
    world = project(tmp_path, ALLOW + f'temp = ["{tmp_path}/**"]\n')
    assert answer(world, scratch, "rm notes.md")[0] == "ask"
    assert answer(world, scratch, f"rm -rf {tmp_path}/elsewhere")[0] == "allow"


def test_the_project_names_its_own_temp_folders(tmp_path: Path, scratch: Path) -> None:
    world = project(tmp_path, ALLOW + f'temp = ["{tmp_path}/builds/*/out/**"]\n')
    assert answer(world, scratch, f"rm -rf {tmp_path}/builds/a/out/x")[0] == "allow"
    assert answer(world, scratch, f"rm -rf {tmp_path}/builds/a/src")[0] == "ask"
    assert answer(world, scratch, "rm -rf <scratch>/clone")[0] == "ask"  # the system folders are no longer listed


def test_a_link_out_of_a_temp_folder_is_followed(tmp_path: Path, scratch: Path) -> None:
    world = project(tmp_path, ALLOW)
    (scratch / "link").symlink_to(world.root, target_is_directory=True)
    assert answer(world, scratch, "rm -rf <scratch>/link/")[0] == "ask"


# --- cd inside a command -----------------------------------------------------------------------

#: (the command, True when it writes to the project's protected manifest)
MOVES = [
    ("cd <scratch> && cat > themis.toml", False),
    ("cd <scratch>; echo x > themis.toml", False),
    ("cd <scratch> && echo x > themis.toml && cd <root> && echo y > themis.toml", True),
    ("cat > <root>/themis.toml", True),
    ("cd <scratch> && cat > <root>/themis.toml", True),
    ("cd <scratch> | true; echo x > themis.toml", True),
    ("(cd <scratch> && true); echo x > themis.toml", True),
    ("cd $NO_SUCH_VARIABLE && echo x > themis.toml", True),
    ("cd docs && echo x > ../themis.toml", True),
    ("cd <scratch>/not-there; echo x > themis.toml", True),
    ("pushd <scratch> && echo x > themis.toml && popd && echo y > themis.toml", True),
    ("pushd <scratch> && echo x > themis.toml && popd", False),
]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(("command", "protected"), MOVES, ids=[case[0] for case in MOVES])
def test_cd_moves_where_relative_paths_are_read(command: str, protected: bool, mode: str, tmp_path: Path,
                                                scratch: Path) -> None:
    decision, reason = answer(project(tmp_path, MODES[mode]), scratch, command)
    if protected:
        assert decision == "ask" and "themis.toml" in reason
    else:
        assert decision == ("allow" if mode == "allow-unless" else "none")


def test_relative_paths_start_from_the_folder_the_host_names(tmp_path: Path, scratch: Path) -> None:
    world = project(tmp_path, ALLOW)
    assert answer(world, scratch, "cat > themis.toml", cwd="<scratch>")[0] == "allow"
    assert answer(world, scratch, "echo x > ../themis.toml", cwd="<root>/docs")[0] == "ask"


# --- what the word-by-word reading cannot see --------------------------------------------------

HIDDEN = [
    ("cat > <scratch>/a.sh <<'EOF'\nrm -rf x\nEOF", "delete"),
    ("cat > <scratch>/a.sh <<'EOF'\necho \"rm -rf x\"\nEOF", "delete"),
    ("cat > <scratch>/a.txt <<'EOF'\nit's time to rm -rf x\nEOF", "delete"),
    ("cat > <scratch>/a.sh <<'EOF'\nssh host uptime\nEOF", "remote"),
    ('echo "$(rm notes.md)"', "delete"),
    ('echo "$(git worktree remove ../wt)"', "delete"),
    ("echo `rm notes.md`", "delete"),
    ("diff <(git reset --hard) notes.md", "throw"),
    ("for f in *.tmp; do rm $f; done", "delete"),
    ('while read f; do shred "$f"; done < list.txt', "delete"),
    ("cat > themis.toml <<'EOF'\nit's mine\nEOF", "themis.toml"),
]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(("command", "said"), HIDDEN, ids=[case[0] for case in HIDDEN])
def test_a_danger_hidden_from_the_reading_still_asks(command: str, said: str, mode: str, tmp_path: Path,
                                                     scratch: Path) -> None:
    decision, reason = answer(project(tmp_path, MODES[mode]), scratch, command)
    assert decision == "ask" and said in reason, (decision, reason)


def test_a_command_that_cannot_be_read_is_allowed_only_when_its_text_names_no_danger(tmp_path: Path,
                                                                                     scratch: Path) -> None:
    unreadable = "cat > <scratch>/a.txt <<'EOF'\nit's fine\nEOF"
    assert answer(project(tmp_path, ALLOW), scratch, unreadable)[0] == "allow"
    assert answer(project(tmp_path / "plain"), scratch, unreadable) == (
        "ask", f"Themis: {hooks.UNREADABLE} The owner's approval is needed.")


# --- the project's patterns, and the host's own lists ------------------------------------------

PATTERNS = 'ask = ["scripts/deploy.sh prod*"]\ndeny = ["scripts/wipe.sh*"]\n'


@pytest.mark.parametrize("mode", MODES)
def test_the_projects_ask_and_deny_patterns_hold_in_both_modes(mode: str, tmp_path: Path, scratch: Path) -> None:
    world = project(tmp_path, MODES[mode] + PATTERNS)
    assert answer(world, scratch, "./scripts/deploy.sh prod --now") == (
        "ask", 'Themis: This command matches "scripts/deploy.sh prod*" under [agents] ask. '
               "The owner's approval is needed.")
    assert answer(world, scratch, "FOO=1 scripts/wipe.sh all") == (
        "deny", 'Themis: This command matches "scripts/wipe.sh*" under [agents] deny.')
    assert answer(world, scratch, "ls && scripts/wipe.sh all")[0] == "deny"
    assert answer(world, scratch, "rm notes.md; scripts/wipe.sh")[0] == "deny"  # deny wins over ask
    assert answer(world, scratch, "scripts/deploy.sh staging")[0] == ("allow" if mode == "allow-unless" else "none")


HOST = {"permissions": {"allow": ["Bash(make *)"], "ask": ["Bash(make deploy:*)"], "deny": ["Bash(make wipe *)"]}}


@pytest.mark.parametrize("name", [hooks.SETTINGS, hooks.LOCAL_SETTINGS])
def test_an_allow_never_skips_the_hosts_own_ask_or_deny(name: str, tmp_path: Path, scratch: Path) -> None:
    world = project(tmp_path, ALLOW, {name: HOST})
    decision, reason = answer(world, scratch, "make deploy prod")
    assert decision == "ask" and f"Bash(make deploy:*) in the ask list of {name}" in reason
    assert answer(world, scratch, "make deploy")[0] == "ask"
    decision, reason = answer(world, scratch, "cd <scratch> && make wipe all")
    assert decision == "deny" and f"Bash(make wipe *) in the deny list of {name}" in reason
    assert answer(world, scratch, "make deployment")[0] == "allow"
    assert answer(world, scratch, "make test")[0] == "allow"


def test_the_ask_mode_leaves_the_hosts_lists_to_the_host(tmp_path: Path, scratch: Path) -> None:
    world = project(tmp_path, "", {hooks.SETTINGS: HOST})
    assert answer(world, scratch, "make deploy prod")[0] == "none"
    assert answer(world, scratch, "make wipe all")[0] == "none"


def test_host_lists_that_cannot_be_read_are_never_allowed_past(tmp_path: Path, scratch: Path) -> None:
    world = project(tmp_path, ALLOW, {hooks.LOCAL_SETTINGS: "{not json"})
    assert answer(world, scratch, "ls")[0] == "none"
    assert answer(world, scratch, "rm notes.md")[0] == "ask"
    assert edit(world, "notes.md") == "none"


def test_an_edit_is_allowed_unless_the_host_has_edit_rules_of_its_own(tmp_path: Path, scratch: Path) -> None:
    assert edit(project(tmp_path, ALLOW), "notes.md") == "allow"
    assert edit(project(tmp_path / "plain"), "notes.md") == "none"
    ruled = project(tmp_path / "ruled", ALLOW, {hooks.LOCAL_SETTINGS: {"permissions": {"ask": ["Edit(docs/**)"]}}})
    assert edit(ruled, "notes.md") == "none"
    assert edit(ruled, "themis.toml") == "ask"


def test_in_allow_unless_the_hosts_local_settings_are_protected(tmp_path: Path, scratch: Path) -> None:
    world = project(tmp_path, ALLOW)
    assert edit(world, hooks.LOCAL_SETTINGS) == "ask"
    assert answer(world, scratch, "echo '{}' > .claude/settings.local.json")[0] == "ask"
    assert edit(project(tmp_path / "plain"), hooks.LOCAL_SETTINGS) == "none"


# --- kept files --------------------------------------------------------------------------------

KEPT = [
    "echo x > data/prices.csv",
    "echo x >> data/prices.csv",
    "mv data/prices.csv old.csv",
    "mv new.csv data/prices.csv",
    "cp new.csv data/prices.csv",
    "cp -t data new.csv",
    "sed -i '' s/a/b/ data/prices.csv",
    "tee data/prices.csv",
    "git mv data/prices.csv old.csv",
    "cd data && echo x > prices.csv",
    "rm data/prices.csv",
]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("command", KEPT)
def test_a_kept_file_is_never_deleted_moved_or_overwritten_without_the_owner(command: str, mode: str,
                                                                             tmp_path: Path, scratch: Path) -> None:
    world = project(tmp_path, MODES[mode] + 'keep = ["data/**"]\n')
    decision, reason = answer(world, scratch, command)
    assert decision == "ask" and "which the project keeps" in reason, (decision, reason)


def test_a_kept_file_may_be_read_and_copied_out(tmp_path: Path, scratch: Path) -> None:
    world = project(tmp_path, ALLOW + 'keep = ["data/**"]\n')
    for command in ("cat data/prices.csv", "cp data/prices.csv <scratch>/", "wc -l data/*.csv"):
        assert answer(world, scratch, command)[0] == "allow", command
    for tool in ("Write", "Edit", "MultiEdit"):
        assert edit(world, "data/prices.csv", tool) == "ask"


# --- the default stays as it was ---------------------------------------------------------------


def test_with_no_new_keys_the_hook_answers_as_before(tmp_path: Path, scratch: Path) -> None:
    world = project(tmp_path)
    assert answer(world, scratch, "ls") == ("none", "")
    assert answer(world, scratch, "rm -rf <scratch>/clone")[0] == "ask"
    assert answer(world, scratch, "echo x > themis.toml") == (
        "ask", "Themis: This command writes to themis.toml, which only the owner changes. The owner's approval is needed.")
    assert edit(world, "notes.md") == "none"


def test_a_manifest_that_is_not_valid_never_loosens_the_hook(tmp_path: Path, scratch: Path) -> None:
    world = project(tmp_path, 'pretool = "allow"\n')
    assert any("agents.pretool must be one of ask, allow-unless" in problem
               for problem in manifests.load(world.root).problems)
    assert hooks.policy(world.root) == hooks.Policy()
    assert answer(world, scratch, "ls")[0] == "none"
    world.manifest('[agents]\npretool = "allow-unless"\ntemp = "/tmp/**"\n')
    assert any("agents.temp must be a list of text" in problem for problem in manifests.load(world.root).problems)
    assert answer(world, scratch, "ls")[0] == "none"


# --- the mode, as the commands report it -------------------------------------------------------


def test_a_project_with_no_pack_runs_the_hook_from_the_command_line(tmp_path: Path, scratch: Path,
                                                                    monkeypatch: pytest.MonkeyPatch,
                                                                    capsys: pytest.CaptureFixture[str]) -> None:
    world = project(tmp_path, ALLOW + PATTERNS + 'keep = ["data/**"]\n')

    def hook(command: str) -> str:
        payload = {"tool_name": "Bash", "tool_input": {"command": placed(command, world, scratch)}, "cwd": str(world.root)}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        assert main(["hook", "pretool", "--root", str(world.root)]) == EXIT_PASS
        return json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"]

    assert [hook(command) for command in (
        "git status", "rm -rf <scratch>/clone", "rm notes.md", "mv data/a.csv b.csv", "scripts/deploy.sh prod",
        "scripts/wipe.sh", "cd <scratch> && cat > themis.toml",
    )] == ["allow", "allow", "ask", "ask", "ask", "deny", "allow"]

    assert main(["hooks", "install", "--root", str(world.root)]) == EXIT_PASS
    assert 'Mode: pretool = "allow-unless": before a tool call the hook answers allow unless' in capsys.readouterr().out
    assert main(["doctor", "--root", str(world.root)]) in (EXIT_PASS, EXIT_REFUSE)
    assert 'The agent hook: pretool = "allow-unless"' in capsys.readouterr().out


def test_the_rule_names_the_mode_when_the_hook_before_a_tool_call_is_missing(tmp_path: Path) -> None:
    from themis import engine

    world = project(tmp_path, ALLOW)
    result = engine.run(manifests.load(world.root), only={"agents/hooks-installed"}).results[0]
    assert any('nothing answers before a tool call (pretool = "allow-unless")' in finding.message
               for finding in result.findings)


# --- the configuration: the mode and the temp folders are read their own way -------------------


@pytest.mark.parametrize(
    ("old", "new", "kind"),
    [
        ({}, {"agents": {"pretool": "allow-unless"}}, "weakening"),
        ({"agents": {"host": "claude"}}, {"agents": {"host": "claude", "pretool": "allow-unless"}}, "weakening"),
        ({"agents": {"pretool": "ask"}}, {"agents": {"pretool": "allow-unless"}}, "weakening"),
        ({"agents": {"pretool": "allow-unless"}}, {"agents": {"pretool": "ask"}}, "tightening"),
        ({"agents": {"pretool": "allow-unless"}}, {"agents": {}}, "tightening"),
        ({"agents": {"host": "claude"}}, {"agents": {"host": "claude", "temp": ["/scratch/**"]}}, "weakening"),
        ({"agents": {"temp": ["/a/**"]}}, {"agents": {"temp": ["/a/**", "/b/**"]}}, "weakening"),
        ({"agents": {"temp": ["/a/**", "/b/**"]}}, {"agents": {"temp": ["/a/**"]}}, "tightening"),
        ({"agents": {"host": "claude"}}, {"agents": {"host": "claude", "temp": ["/tmp/**"]}}, "tightening"),
        ({"agents": {"host": "claude"}}, {"agents": {"host": "claude", "keep": ["data/**"]}}, "tightening"),
        ({"agents": {"keep": ["data/**"]}}, {"agents": {}}, "weakening"),
        ({"agents": {"ask": ["a*"]}}, {"agents": {"ask": ["a*", "b*"], "deny": ["c*"]}}, "tightening"),
        ({"agents": {"deny": ["c*"]}}, {"agents": {"deny": []}}, "weakening"),
    ],
)
def test_each_change_to_the_hook_keys_is_classified(old: dict, new: dict, kind: str) -> None:
    assert {change.kind for change in configguard.classify(old, new)} == {kind}, configguard.classify(old, new)


# --- planted bugs ------------------------------------------------------------------------------

KEEP = 'keep = ["data/**"]\n'
#: (name, the line as it stands, the line broken, the [agents] keys, settings files, the call)
PLANTS = [
    ("cd is not followed", "cwd = _moved(program, args, cwd, pushed,", "cwd = cwd or _moved(program, args, cwd, pushed,",
     ALLOW, {}, "cd <scratch> && cat > themis.toml"),
    ("a subshell's cd outlives it", "cwd = saved.pop()", "saved.pop()", ALLOW, {},
     "(cd <scratch> && true); echo x > themis.toml"),
    ("a cd in a pipe is followed", "if not (_piped(str(before)) or _piped(str(after))):", "if True:", ALLOW, {},
     "cd <scratch> | true; echo x > themis.toml"),
    ("a folder that may not be there is trusted", "if target is not None and not sure and not target.is_dir():",
     "if False:", ALLOW, {}, "cd <scratch>/not-there; echo x > themis.toml"),
    ("a delete in a temp folder still asks",
     "return None if places and all(_scratch(place, root, temp) for place in places) else what", "return what",
     ALLOW, {}, "rm -rf <scratch>/clone"),
    ("the project counts as scratch", "if real == home or home in real.parents or real in home.parents:",
     "if real in home.parents:", ALLOW + 'temp = ["<above>/**"]\n', {}, "rm notes.md"),
    ("a folder above the project counts as scratch", "if real == home or home in real.parents or real in home.parents:",
     "if real == home or home in real.parents:", ALLOW + 'temp = ["<above>/../**"]\n', {}, "rm -rf <above>"),
    ("links out of a temp folder are not followed", "real, home = place.resolve(), root.resolve()",
     "real, home = place, root.resolve()", ALLOW, {}, "rm -rf <scratch>/link/"),
    ("a newline does not part commands", 'lexer.whitespace = " \\t\\r"', 'lexer.whitespace = " \\t\\r\\n"', ALLOW, {},
     "ls\nrm notes.md"),
    ("a comment swallows the next line", "shlex.shlex(_Lines(command),", "shlex.shlex(io.StringIO(command),",
     ALLOW, {}, "ls # a note\nrm notes.md"),
    ("a keyword hides the program", "elif word in KEYWORDS:", "elif False:", ALLOW, {}, "{ rm notes.md; }"),
    ("hidden text is not read", "if reason is None and (OPAQUE.search(text)", "if False and (OPAQUE.search(text)",
     ALLOW, {}, "cat <<'EOF'\necho \"rm -rf x\"\nEOF"),
    ("work thrown away is let through", 'if (sub == "reset" and "--hard" in flags)', 'if (sub == "no-such" and "--hard" in flags)',
     ALLOW, {}, "git reset --hard"),
    ("a restore of the working tree is let through", "if worktree or not staged:", "if False:", ALLOW, {},
     "git restore notes.md"),
    ("a kept file may be overwritten", 'return f"This command writes to or moves {name}, which the project keeps."',
     "pass", ALLOW + KEEP, {}, "echo x > data/prices.csv"),
    ("a copy out of a kept folder asks", "kept += _written(program, args, cwd)", "kept += args", ALLOW + KEEP, {},
     "cp data/prices.csv <scratch>/"),
    ("an unreadable command is allowed in ask mode", "if allowing and reason == UNREADABLE:", "if reason == UNREADABLE:",
     "", {}, "cat > <scratch>/a.txt <<'EOF'\nit's fine\nEOF"),
    ("the project's deny is not read", "denied = _matching(chosen.deny, texts)", "denied = None", ALLOW + PATTERNS, {},
     "scripts/wipe.sh all"),
    ("the project's ask is not read", "asked = _matching(chosen.ask, texts)", "asked = None", ALLOW + PATTERNS, {},
     "scripts/deploy.sh prod"),
    ("the host's deny list is not read", 'hosted = _host_match(lists, "deny", texts) if lists else None', "hosted = None",
     ALLOW, {hooks.SETTINGS: HOST}, "make wipe all"),
    ("the host's ask list is not read", 'hosted = _host_match(lists, "ask", texts)', "hosted = None",
     ALLOW, {hooks.SETTINGS: HOST}, "make deploy prod"),
    ("the host's local settings are not read", "for name in (SETTINGS, LOCAL_SETTINGS):", "for name in (SETTINGS,):",
     ALLOW, {hooks.LOCAL_SETTINGS: HOST}, "make deploy prod"),
    ("host lists that cannot be read are skipped",
     "except (OSError, UnicodeDecodeError, json.JSONDecodeError):\n            return None",
     "except (OSError, UnicodeDecodeError, json.JSONDecodeError):\n            continue",
     ALLOW, {hooks.LOCAL_SETTINGS: "{not json"}, "ls"),
    ("an edit is allowed past the host's own edit rules", "if lists is None or any(EDIT_RULE.match(entry.strip())",
     "if lists is None or any(False and EDIT_RULE.match(entry.strip())",
     ALLOW, {hooks.LOCAL_SETTINGS: {"permissions": {"ask": ["Edit(docs/**)"]}}}, "Write notes.md"),
    ("a broken manifest loosens the hook", "if not manifest.present or manifest.problems:", "if not manifest.present:",
     'pretool = "allow-unless"\nno_such_key = 1\n', {}, "ls"),
]


def planted(old: str, new: str) -> types.ModuleType:
    assert SOURCE.count(old) == 1, f"the plant's target must occur exactly once: {old!r}"
    module = types.ModuleType("planted_hook_modes")
    module.__file__ = hooks.__file__
    sys.modules[module.__name__] = module  # a dataclass looks its module up while it is built
    try:
        exec(compile(SOURCE.replace(old, new), "<planted hooks.py>", "exec"), module.__dict__)  # noqa: S102
    finally:
        del sys.modules[module.__name__]
    return module


@pytest.mark.parametrize(("name", "old", "new", "agents", "settings", "call"), PLANTS, ids=[plant[0] for plant in PLANTS])
def test_each_planted_bug_changes_the_answer_that_names_it(name: str, old: str, new: str, agents: str,
                                                           settings: dict[str, Any], call: str, tmp_path: Path,
                                                           scratch: Path) -> None:
    world = project(tmp_path, agents.replace("<above>", str(tmp_path)), settings)
    (scratch / "link").symlink_to(world.root, target_is_directory=True)
    broken = planted(old, new)

    def said(module: Any) -> str:
        if call.startswith("Write "):
            return edit(world, call.removeprefix("Write "), module=module)
        return answer(world, scratch, call, module=module)[0]

    assert said(hooks) != said(broken), f"the planted bug {name!r} was not caught: both answer {said(hooks)}"
