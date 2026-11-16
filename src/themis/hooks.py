"""Agent hooks: guardrails that run outside the prompt.

Three hooks, installed into the agent host's settings file:

    before a tool call   stop a delete, a remote command, a forced push, `themis grant`, and any
                         edit to a protected file, and ask the owner
    session start        remember which breaches already exist, so old ones do not block new work
    end of turn          run `themis check` on the changed work; a new breach keeps the turn open

The end-of-turn hook follows six rules. It is silent in a folder with no manifest. It checks only
this project. A blocking exit always carries a reason. Breaches that existed when the session
began are warnings, not blocks. It blocks at most three times in one turn. It never installs
anything and never reports a pass it did not establish.
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any

from themis import configguard, engine, paths, reporters
from themis import manifest as manifests
from themis.gitlog import Git
from themis.verdict import Verdict

SETTINGS = ".claude/settings.json"
MAX_BLOCKS = 3
STATE = ".themis/hook-state.json"
MARK = "themis hook"

DELETERS = {"rm", "rmdir", "unlink", "shred"}
REMOTES = {"ssh", "scp", "sftp"}
WRAPPERS = {"sudo", "command", "time", "nohup", "exec", "env", "xargs", "nice", "builtin"}
SHELLS = {"sh", "bash", "zsh", "dash"}
WRITERS = {"tee", "mv", "cp", "install", "truncate", "touch", "ln", "dd"}
IN_PLACE = {"sed", "perl"}
OPERATORS = {";", "&&", "||", "|", "&", "(", ")", "\n", "|&", ";;"}
GIT_VALUED = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env", "--attr-source"}


# -- reading a shell command --------------------------------------------------------------------


def _simple_commands(command: str) -> list[list[str]] | None:
    """The command split into simple commands, each a list of words. None when it cannot be read."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    found, current = [], []
    for token in tokens:
        if token in OPERATORS or (token and set(token) <= set(";&|()")):
            if current:
                found.append(current)
            current = []
        else:
            current.append(token)
    if current:
        found.append(current)
    return found


def _program(words: list[str]) -> tuple[str, list[str]]:
    """The program a simple command runs, past any assignments and wrappers, and its arguments."""
    index = 0
    while index < len(words):
        word = words[index].lstrip("`$")
        name = os.path.basename(word)
        if "=" in word and not word.startswith("-") and word.split("=", 1)[0].isidentifier():
            index += 1
        elif name in WRAPPERS:
            index += 1
            while index < len(words) and words[index].startswith("-"):
                index += 1
        else:
            return name, words[index + 1:]
    return "", []


def _git_subcommand(args: list[str]) -> tuple[str, list[str]]:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in GIT_VALUED else 1
    return (args[index], args[index + 1:]) if index < len(args) else ("", [])


def _after_themis(words: list[str]) -> str | None:
    """The first word after `themis`, when this command runs themis however it is launched."""
    for index, word in enumerate(words):
        if os.path.basename(word.lstrip("`$")) == "themis" or (word == "themis" and index and words[index - 1] == "-m"):
            rest = [later for later in words[index + 1:] if not later.startswith("-")]
            return rest[0] if rest else ""
    return None


def _relative(word: str, root: Path) -> str | None:
    """A word as a repository path, or None when it is not inside the repository."""
    if not word or word.startswith("-"):
        return None
    candidate = Path(word).expanduser()
    absolute = candidate if candidate.is_absolute() else root / candidate
    try:
        return absolute.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def judge_command(command: str, root: Path, protected: list[str]) -> str | None:
    """Why the owner must approve this shell command, or None when Themis has no objection."""
    simple = _simple_commands(command)
    if simple is None:
        return "Themis cannot read this command, so it cannot say it is safe."
    for words in simple:
        program, args = _program(words)
        if program in SHELLS and "-c" in args and args.index("-c") + 1 < len(args):
            inner = judge_command(args[args.index("-c") + 1], root, protected)
            if inner:
                return inner
        # Behind a wrapper such as sudo or xargs, the real program is somewhere among the words.
        names = {os.path.basename(word.lstrip("`$")) for word in words}
        behind = names if names & WRAPPERS else set()
        if program in DELETERS or behind & DELETERS:
            return "This command deletes files."
        if program in REMOTES or behind & REMOTES:
            return "This command reaches a remote machine."
        if program == "find" and ("-delete" in args or any(os.path.basename(a) in DELETERS for a in args)):
            return "This command deletes files."
        if program == "git":
            sub, rest = _git_subcommand(args)
            flags = [word for word in rest if word.startswith("-")]
            if sub in ("rm", "clean"):
                return "This command deletes files."
            if sub == "branch" and any(flag == "--delete" or (not flag.startswith("--") and "d" in flag.lower()) for flag in flags):
                return "This command deletes a branch."
            if sub == "push" and (
                any(flag in ("--delete", "-d", "--force", "-f", "--mirror") or flag.startswith("--force-with-lease") for flag in flags)
                or any(word.startswith((":", "+")) for word in rest if not word.startswith("-"))
            ):
                return "This command deletes or overwrites something on the remote."
        if _after_themis(words) == "grant":
            return "Only the owner gives a grant."
        if _after_themis(words) == "decide" and ("--by=owner" in words or "owner" in words[words.index("--by") + 1:][:1]
                                                 if "--by" in words else "--by=owner" in words):
            return "Only the owner overrules a gate."
        targets = [words[index + 1] for index, word in enumerate(words[:-1]) if word in (">", ">>", ">|")]
        if program in WRITERS or (program in IN_PLACE and any(arg.startswith("-i") for arg in args)):
            targets += args
        for target in targets:
            name = _relative(target, root)
            if name and paths.matches_any(name, protected):
                return f"This command writes to {name}, which only the owner changes."
    return None


# -- the three hooks ----------------------------------------------------------------------------


def _protected(root: Path) -> list[str]:
    manifest = manifests.load(root)
    if manifest.present and not manifest.problems:
        return configguard.protected_paths(manifest)
    return list(configguard.ALWAYS_PROTECTED)


def pretool(payload: dict[str, Any], root: Path) -> dict[str, Any] | None:
    """The answer to a tool call: an "ask" with its reason, or None to leave the call alone."""
    if not (root / manifests.MANIFEST_FILE).is_file():
        return None
    tool, given = payload.get("tool_name", ""), payload.get("tool_input", {}) or {}
    reason = None
    if tool == "Bash":
        reason = judge_command(str(given.get("command", "")), root, _protected(root))
    elif tool in ("Write", "Edit", "NotebookEdit", "MultiEdit"):
        name = _relative(str(given.get("file_path") or given.get("notebook_path") or ""), root)
        if name and paths.matches_any(name, _protected(root)):
            reason = f"{name} is a protected file, which only the owner changes."
    if reason is None:
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "ask",
        "permissionDecisionReason": f"Themis: {reason} The owner's approval is needed.",
    }}


def _read_state(root: Path) -> dict[str, Any]:
    try:
        data = json.loads((root / STATE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(root: Path, state: dict[str, Any]) -> None:
    path = root / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / ".gitignore").write_text("*\n", encoding="utf-8")
    path.write_text(json.dumps(state), encoding="utf-8")


def _marks(report: engine.Report) -> list[str]:
    """One mark for each finding of an enforced rule, to tell an old breach from a new one."""
    return sorted(
        f"{result.id}|{finding.where}|{finding.message}"
        for result in report.results if result.counts and result.verdict is not Verdict.PASS
        for finding in result.findings
    )


def _run(root: Path) -> engine.Report | None:
    manifest = manifests.load(root)
    if not manifest.present:
        return None
    git = Git(root)
    main = git.main_ref(manifest.project.get("main"))
    return engine.run(manifest, changed=git.changed_against(main) if main else None)


def start(payload: dict[str, Any], root: Path) -> None:
    """Remember what is already broken when the session begins. Never prints, never fails."""
    try:
        report = _run(root)
        if report is None:
            return
        state = _read_state(root)
        state[str(payload.get("session_id", "session"))] = {"known": _marks(report), "blocks": 0, "tree": None}
        _write_state(root, state)
    except Exception:  # noqa: BLE001 - a baseline that cannot be taken must not stop a session
        return


def stop(payload: dict[str, Any], root: Path) -> tuple[int, str, str]:
    """(exit code, text for the agent, text for the owner). Exit 2 keeps the turn open."""
    report = _run(root)
    if report is None:
        return 0, "", ""
    session = str(payload.get("session_id", "session"))
    state = _read_state(root)
    mine = state.setdefault(session, {"known": [], "blocks": 0, "tree": None})
    known = set(mine.get("known", []))
    fresh = [mark for mark in _marks(report) if mark not in known]
    old = [mark for mark in _marks(report) if mark in known]
    warning = ""
    if old:
        warning = f"Themis: {len(old)} breach(es) that existed before this session still stand."
    if not fresh:
        mine["blocks"] = 0
        _write_state(root, state)
        return 0, "", warning
    if mine.get("blocks", 0) >= MAX_BLOCKS:
        mine["blocks"] = 0
        _write_state(root, state)
        return 0, "", f"Themis: the check still fails after {MAX_BLOCKS} attempts. The work is NOT verified."
    mine["blocks"] = mine.get("blocks", 0) + 1
    _write_state(root, state)
    text = reporters.compact(report).strip() or "the check did not pass, and reported no finding"
    lead = f"Themis check: {report.verdict.value.upper()}. Fix what is listed, then finish again."
    return 2, f"{lead}\n{text}", warning


# -- installing ---------------------------------------------------------------------------------


def wanted(command: str) -> dict[str, list[dict[str, Any]]]:
    def entry(action: str, timeout: int, matcher: str | None = None) -> dict[str, Any]:
        hook = {"hooks": [{"type": "command", "command": f"{command} hook {action}", "timeout": timeout}]}
        return {"matcher": matcher, **hook} if matcher else hook

    return {
        "PreToolUse": [entry("pretool", 15, "Bash|Write|Edit|MultiEdit|NotebookEdit")],
        "SessionStart": [entry("start", 60)],
        "Stop": [entry("stop", 300)],
    }


def default_command(root: Path) -> str:
    return "uv run --quiet themis" if (root / "uv.lock").is_file() else "themis"


def _has(entries: Any, action: str) -> bool:
    return any(
        isinstance(hook, dict) and f"{MARK} {action}" in str(hook.get("command", ""))
        for entry in (entries if isinstance(entries, list) else [])
        for hook in (entry.get("hooks", []) if isinstance(entry, dict) else [])
    )


def missing(root: Path) -> list[str] | None:
    """The hooks that are not installed. None when the settings file cannot be read."""
    path = root / SETTINGS
    if not path.is_file():
        return ["PreToolUse", "SessionStart", "Stop"]
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    hooks = settings.get("hooks", {}) if isinstance(settings, dict) else {}
    events = {"PreToolUse": "pretool", "SessionStart": "start", "Stop": "stop"}
    return [event for event, action in events.items() if not _has(hooks.get(event), action)]


def install(root: Path, command: str | None = None) -> Path:
    """Add the three hooks to the host's settings, leaving every other setting as it is."""
    path = root / SETTINGS
    settings: dict[str, Any] = {}
    if path.is_file():
        settings = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise ValueError(f"{SETTINGS} is not a JSON object")
    hooks = settings.setdefault("hooks", {})
    events = {"PreToolUse": "pretool", "SessionStart": "start", "Stop": "stop"}
    for event, entries in wanted(command or default_command(root)).items():
        if not _has(hooks.get(event), events[event]):
            hooks.setdefault(event, []).extend(entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return path
