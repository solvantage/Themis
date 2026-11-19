"""Agent hooks: guardrails that run outside the prompt.

Three hooks, installed into the agent host's settings file:

    before a tool call   ask the owner before a delete, work thrown away, a remote command or an
                         upload, `themis grant`, the owner's own `themis decide` and `themis attest`,
                         and any write to a protected or kept file; deny what the project denies
    session start        remember which breaches already exist, so old ones do not block new work
    end of turn          run `themis check` on the changed work; a new breach keeps the turn open

The hook before a tool call has two modes, `pretool` under [agents]. In "ask", the default, it asks
for danger and says nothing about the rest, so the host's own permission mode decides it. In
"allow-safe" it has three answers. Allow, only when it reads every command in the call and each one
is on its safe list: read-only tools, a few git subcommands inside the project, writes and deletes
whose literal targets lie in a temp folder or in the project away from its protected and kept
files, and the project's own `allow` patterns. Ask or deny, for danger, as in "ask". And nothing
for the rest, so the host decides. It never allows what it cannot read.

The end-of-turn hook follows six rules. It is silent in a folder with no manifest. It checks only
this project. A blocking exit always carries a reason. Breaches that existed when the session
began are warnings, not blocks. It blocks at most three times in one turn. It never installs
anything and never reports a pass it did not establish.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import stat
import subprocess
import urllib.parse
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from themis import configguard, engine, paths, reporters, shell
from themis import manifest as manifests
from themis.gitlog import Git
from themis.shell import Simple, Word
from themis.verdict import Verdict

SETTINGS = ".claude/settings.json"
LOCAL_SETTINGS = ".claude/settings.local.json"
MAX_BLOCKS = 3
STATE = ".themis/hook-state.json"
MARK = "themis hook"
OWNER = "owner"  # the judge whose rows only the owner ticks
SAFE_MODE = "allow-safe"

#: Where scratch work lives. In allow-safe, a delete or a write whose every literal target lies in
#: one of these, past every link, and neither inside the project nor above it, is safe.
TEMP = manifests.TEMP_FOLDERS
UNREADABLE = "Themis cannot read this command, so it cannot say it is safe."
#: Guarded in allow-safe as well as the protected paths: the host's settings and the servers it
#: starts, the git hooks and the hook managers' files, the hook's own state, and every `.git`,
#: whose hooks and configuration run programs on the next git command.
GUARDED = (".claude/**", ".mcp.json", ".githooks/**", ".husky/**", ".pre-commit-config.yaml", "lefthook.yml",
           "lefthook.yaml", ".lefthook.yml", ".lefthook.yaml", "lefthook-local.yml", "lefthook-local.yaml",
           ".themis/**", "**/.git", "**/.git/**")
#: The host's settings files outside the project. In allow-safe they are guarded, and their ask
#: and deny lists are read with the project's.
USER_SETTINGS = ("settings.json", "settings.local.json")
MANAGED_SETTINGS = ("/Library/Application Support/ClaudeCode/managed-settings.json",
                    "/etc/claude-code/managed-settings.json")
DEVICES = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}

DELETERS = {"rm", "rmdir", "unlink", "shred"}
REMOTES = {"ssh", "scp", "sftp", "mosh", "sshpass", "autossh", "telnet", "nc", "ncat", "netcat", "socat",
           "ftp", "lftp", "rclone"}
WRAPPERS = {"sudo", "doas", "command", "builtin", "time", "nohup", "exec", "env", "xargs", "parallel", "nice",
            "ionice", "stdbuf", "caffeinate", "setsid", "chrt", "taskset", "flock", "timeout", "unbuffer", "watch",
            "chronic", "npx", "bunx", "pnpx"}
POSITIONAL = {"timeout": 1, "chrt": 1, "taskset": 1, "flock": 1}  # wrappers that take a value before the program
RUNNERS = {("uv", "run"), ("poetry", "run"), ("pipx", "run"), ("npm", "exec"), ("pnpm", "exec"), ("yarn", "exec"),
           ("pdm", "run"), ("hatch", "run"), ("rye", "run")}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "mksh", "csh", "tcsh", "fish", "ash"}
INTERPRETERS = {"python", "python2", "python3", "pypy", "pypy3", "node", "nodejs", "deno", "bun", "perl", "ruby",
                "php", "osascript", "awk", "gawk", "mawk", "nawk", "lua", "tclsh", "Rscript", "julia"}
WRITERS = {"tee", "mv", "cp", "install", "truncate", "touch", "ln", "dd", "rsync"}
COPIERS = {"cp", "ln", "install", "rsync"}  # writers that change only where they write to, never what they read
IN_PLACE = {"sed", "perl", "ruby"}
KEYWORDS = {"if", "then", "else", "elif", "while", "until", "do", "done", "fi", "!", "{", "}"}
CHANGE_FOLDER = {"cd", "pushd", "popd", "source", ".", "eval", "exec", "builtin", "command", "alias", "unalias"}
CLOUD = {"aws", "gcloud", "gsutil", "az", "gh", "glab", "kubectl", "helm", "terraform", "pulumi", "heroku", "fly",
         "flyctl", "vercel", "netlify", "doctl", "firebase", "supabase", "wrangler", "docker", "podman"}
CLOUD_DELETES = {"delete", "rm", "rb", "rmi", "destroy", "remove", "purge", "prune", "del", "uninstall"}
GIT_VALUED = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env", "--attr-source"}
GIT_ENV = {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"}
#: `git -c` keys that make git run a program, or move its hooks.
GIT_RUNS = re.compile(r"(?i)(alias\.|core\.(hookspath|fsmonitor|sshcommand|pager|editor|askpass|gitproxy)"
                      r"|sequence\.editor|diff\.|difftool\.|mergetool\.|filter\.|merge\..*\.driver|credential\."
                      r"|gpg\.|.*\.textconv|.*\.command|protocol\.|uploadpack\.|receivepack\.|include)")
EDITORS = ("Write", "Edit", "NotebookEdit", "MultiEdit")
EDIT_RULE = re.compile(r"\s*(?:Edit|Write|MultiEdit|NotebookEdit)(?:\(|\s*\Z)")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

#: The dangers looked for in the raw text of a command Themis cannot read in full: (pattern, what).
DANGER_TEXT = (
    (re.compile(r"(?<![\w.-])(?:rm|rmdir|unlink|shred)(?![\w.-])"), "a delete"),
    (re.compile(r"\bfind\b[^\n;&|]*?\s-delete\b|\bworktree\s+remove\b|\brsync\b[^\n;&|]*?--(?:delete|remove)"),
     "a delete"),
    (re.compile(r"\bgit\b[^\n;&|]*?\s(?:clean|restore)\b|\breset\s+--ha|\bstash\s+(?:drop|clear)\b"),
     "work thrown away"),
    (re.compile(r"\bcheckout\b[^\n;&|]*?\s--(?=\s)"), "work thrown away"),
    (re.compile(r"\bbranch\s+(?:-[a-zA-Z]*[dD]\b|--d)"), "a branch delete"),
    (re.compile(r"\bpush\b[^\n;&|]*?\s(?:--d|--mi|--fo|--pr|-[a-zA-Z]*[df])(?![\w])|\bpush\b[^\n;&|]*?\s[:+]\w"),
     "a push that deletes or overwrites"),
    (re.compile(r"(?<![\w.-])(?:ssh|scp|sftp|rsync|rclone)(?![\w.-])"), "a remote machine"),
    (re.compile(r"\bthemis\b[^\n;&|]*?\sgrant\b|--by[= ]owner\b|--judge[= ]owner\b"), "a command only the owner runs"),
)
#: In that raw text, what writes, moves or deletes; a protected or kept path beside it asks.
WRITE_TEXT = re.compile(r">|(?<![\w.-])(?:tee|mv|cp|install|truncate|touch|ln|dd|sed|perl|rm|unlink|shred|rsync)"
                        r"(?![\w.-])")
#: In code given to an interpreter on its command line: a call that deletes, or runs another program.
CODE_DANGER = re.compile(r"\b(?:remove|unlink|unlinkSync|rmtree|rmSync|rmdir|rmdirSync|removedirs|system|popen|spawn"
                         r"|spawnSync|execSync|execFileSync|exec[lv]p?e?|truncate)\s*\(|File\.delete|FileUtils\.rm"
                         r"|\bunlink\b|\brm\s+-|`[^`]*\brm\b|\bsubprocess\b|\bchild_process\b|\bPopen\b")


# -- the project's policy -----------------------------------------------------------------------


@dataclass(frozen=True)
class Policy:
    """How the before-a-tool-call hook answers, from [agents]. The defaults are the hook as it was
    before these keys: ask for what is dangerous, and leave the rest to the host."""

    mode: str = "ask"
    protected: tuple[str, ...] = configguard.ALWAYS_PROTECTED
    temp: tuple[str, ...] = TEMP
    keep: tuple[str, ...] = ()
    ask: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()
    allow: tuple[str, ...] = ()
    main: str = ""  # the project's main line, which allow-safe never pushes to
    outside: tuple[str, ...] = ()  # files outside the project guarded in allow-safe: the host's own settings


def policy(root: Path) -> Policy:
    """The project's policy. A manifest that is missing or not valid gives the defaults, so a
    broken manifest never loosens the hook."""
    manifest = manifests.load(root)
    if not manifest.present or manifest.problems:
        return Policy()
    agents = manifest.table("agents")
    mode = agents.get("pretool", "ask")
    safe = mode == SAFE_MODE
    inside, outside = [], _host_config()
    if safe:
        # The folder git runs its hooks from, wherever it is: a hook written there runs on the next
        # commit. A manager's stub folder (husky's `.husky/_`) runs the files beside it, so its
        # parent is guarded too.
        for folder in (agents.get("git_hooks"), _git(root, "config", "--get", "core.hooksPath").stdout.strip()):
            real = _real(folder, root) if folder else None
            if real is not None and os.path.basename(real) == "_":
                real = os.path.dirname(real)
            name = None if real is None else _within(real, os.path.realpath(root))
            if name:
                inside.append(f"{name}/**")
            elif real is not None and name is None:
                outside.append(real)
    return Policy(
        mode=mode,
        protected=(*configguard.protected_paths(manifest), *((LOCAL_SETTINGS, *GUARDED, *inside) if safe else ())),
        temp=tuple(agents.get("temp", TEMP)),
        keep=tuple(agents.get("keep", ())),
        ask=tuple(agents.get("ask", ())),
        deny=tuple(agents.get("deny", ())),
        allow=tuple(agents.get("allow", ())),
        main=str(manifest.project.get("main") or ""),
        outside=tuple(outside) if safe else (),
    )


def _guarded(real: str, outside: Iterable[str]) -> bool:
    """True when a resolved path is one of the guarded places outside the project, lies inside
    one, or is a folder that holds one."""
    return any(_within(real, guarded) is not None or _within(guarded, real) is not None for guarded in outside)


def _host_folder() -> str | None:
    """The host's folder in the user's home ($CLAUDE_CONFIG_DIR, else ~/.claude), or None."""
    folder = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return None if folder.startswith("~") else os.path.realpath(folder)


def _user_settings() -> list[Path]:
    """The host's settings files in the user's own folder."""
    folder = _host_folder()
    return [] if folder is None else [Path(folder, name) for name in USER_SETTINGS]


def _host_config() -> list[str]:
    """What configures the host in the user's home, guarded in allow-safe: its whole folder, and
    `~/.claude.json`, which names the servers it starts."""
    folder, home = _host_folder(), os.path.expanduser("~")
    found = [folder] if folder else []
    if not home.startswith("~"):
        found.append(os.path.realpath(os.path.join(home, ".claude.json")))
    return found


#: What each mode does, as `themis doctor` and `themis hooks install` say it.
MODE_SAYS = {
    "ask": "asks the owner before a delete, work thrown away, a remote command or an upload, an owner-only "
           "command or a write to a protected or kept file, denies what the project denies, and leaves every "
           "other call to the host's own permission mode",
    SAFE_MODE: "allows a call only when it reads every command in it and each is on its safe list (read-only "
               "tools, a few git subcommands, writes and deletes in a temp folder or away from protected files, "
               "the project's allow patterns), asks or denies for danger as in ask mode, and leaves every other "
               "call to the host's own permission mode",
}


def mode_line(root: Path) -> str:
    """The mode, and what it does, in one sentence."""
    chosen = policy(root).mode
    return f'pretool = "{chosen}": before a tool call the hook {MODE_SAYS[chosen]}.'


# -- where a word points ------------------------------------------------------------------------


def _real(text: str, cwd: Path | None) -> str | None:
    """The absolute path a word names, past every link, or None when only the shell could say: a
    `~user` or `~-`, or a relative word in a folder that cannot be known."""
    if not text:
        return None
    if text.startswith("~"):
        text = os.path.expanduser(text)
        if text.startswith("~"):
            return None
    if not os.path.isabs(text):
        if cwd is None:
            return None
        text = os.path.join(str(cwd), text)
    return os.path.realpath(text)


def _within(real: str, home: str) -> str | None:
    """`real` as a path inside the folder `home`, compared without regard to case; "" for the
    folder itself; None outside it."""
    folded, base = real.casefold(), home.casefold().rstrip("/")
    if folded == base:
        return ""
    if folded.startswith(base + "/"):
        return real[len(base) + 1:]
    return None


def _relative(word: str, root: Path, cwd: Path | None = None) -> str | None:
    """A word as a repository path, or None when it is not inside the repository. A relative word
    is read from the folder the command runs in, which is the root unless the host says otherwise."""
    if not word or word.startswith("-"):
        return None
    real = _real(word, cwd or root)
    return None if real is None else _within(real, os.path.realpath(root))


def _holders(pattern: str) -> tuple[list[str], bool]:
    """The folders that hold what a path pattern names, and True when any folder may hold one
    (the pattern starts with a wildcard). A pattern such as `**/.git` names a folder wherever it
    is; only the path itself, or a path inside it, touches it."""
    parts = pattern.casefold().strip("/").split("/")
    if parts[0] == "**" and len(parts) > 1 and not any(char in parts[1] for char in "*?["):
        return [], False
    lead = []
    for part in parts:
        if any(char in part for char in "*?["):
            break
        lead.append(part)
    count = len(lead) - 1 if len(lead) == len(parts) else len(lead)
    return ["/".join(lead[:size]) for size in range(1, count + 1)], not lead


def _touches(name: str, patterns: Iterable[str], root: Path) -> str | None:
    """The pattern a repository path matches, or holds a match of as a folder, compared without
    regard to case. The root holds everything."""
    folded = name.casefold().strip("/")
    for pattern in patterns:
        if not folded or paths.matches(folded, pattern.casefold()):
            return pattern
        folders, anywhere = _holders(pattern)
        if folded in folders or (anywhere and (root / name).is_dir()):
            return pattern
    return None


def _could_touch(name: str, pattern: str) -> bool:
    """True when a path holding a glob could name, or hold, what a path pattern names."""
    globbed, parts = name.casefold().strip("/").split("/"), pattern.casefold().strip("/").split("/")
    for index, part in enumerate(globbed):
        if index >= len(parts):
            return False
        if parts[index] == "**":
            return True
        if not any(char in parts[index] for char in "*?[") and not _fnmatch(parts[index], part):
            return False
    return True


def _fnmatch(text: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(text, pattern)


def _temp_bases(temp: Iterable[str]) -> list[tuple[str, str]]:
    """Each temp pattern as (the folder it starts at, the pattern below it), once as written and
    once with the folder's links followed, since `/tmp` is a link on some systems. A pattern whose
    folder is unset, or is the whole disk, names nothing."""
    found = []
    for pattern in temp:
        text = os.path.expanduser(os.path.expandvars(pattern))
        if "$" in text or not text.startswith("/"):
            continue
        parts = text.split("/")
        cut = next((index for index, part in enumerate(parts) if any(char in part for char in "*?[")), len(parts))
        head, rest = "/".join(parts[:cut]), "/".join(part for part in parts[cut:] if part)
        for base in {os.path.normpath(head or "/"), os.path.realpath(head or "/")}:
            if base.rstrip("/"):
                found.append((base.rstrip("/"), rest or "**"))
    return found


def _scratch(real: str, home: str, temp: Iterable[str]) -> bool:
    """True when a resolved path lies inside a temp folder, and neither inside the project nor
    above it."""
    if _within(real, home) is not None or _within(home, real) is not None:
        return False
    return any(real.startswith(base + "/") and paths.matches(real[len(base) + 1:], rest)
               for base, rest in _temp_bases(temp))


# -- one command line, as it is read ------------------------------------------------------------


@dataclass
class Reading:
    """What the hook made of a command: the first danger it found, whether every command in it is
    understood and safe, whether the 0.2.0 reader could not read it, and each simple command as
    text for the ask, deny and allow patterns."""

    danger: str | None = None
    safe: bool = True
    unreadable: bool = False
    texts: list[str] = field(default_factory=list)

    def ask(self, reason: str | None) -> None:
        if reason and self.danger is None:
            self.danger = reason


@dataclass
class _Line:
    """Where a line's next command runs, and what the commands before it may have done."""

    cwd: Path | None  # None once a `cd` cannot be proven
    mutated: bool = False  # a command that may change the files ran: no later `cd` is followed
    moved: bool = False  # a `cd` was followed in the current `&&` chain
    tree_changed: bool = False  # a command that may make links ran: no later write or delete is safe
    made_folders: bool = False  # a folder was made: no later git is safe, since it may be a repository
    made: list[str] = field(default_factory=list)  # the folders made, past links: nothing written under them is safe

    def child(self) -> _Line:
        return _Line(self.cwd, self.mutated, False, self.tree_changed, self.made_folders, self.made)


@dataclass(frozen=True)
class _Context:
    root: Path
    home: str  # the project's folder, past every link
    policy: Policy
    temp: tuple[str, ...]  # the temp folders, in allow-safe; none in ask mode
    text: str  # the whole command, for the raw search
    cdpath: bool  # CDPATH is set, or named in the command: a bare `cd NAME` may go elsewhere


def read_command(command: str, root: Path, cwd: Path | None, chosen: Policy) -> Reading:
    """Read a shell command for its dangers, whether it is safe, and its simple commands."""
    context = _Context(root=root, home=os.path.realpath(root), policy=chosen,
                       temp=chosen.temp if chosen.mode == SAFE_MODE else (), text=command,
                       cdpath=bool(os.environ.get("CDPATH")) or "CDPATH" in command)
    reading = Reading()
    _read(command, _Line(cwd), context, reading, 0)
    return reading


def _shlex_reads(text: str) -> bool:
    """True when the 0.2.0 reader could read the text. In ask mode, what it could not read still
    asks, exactly as it did."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        list(lexer)
    except ValueError:
        return False
    return True


def _read(text: str, line: _Line, ctx: _Context, reading: Reading, depth: int, *, legacy: bool = False) -> None:
    """Read one command text. `legacy` marks the texts the 0.2.0 reader read too: the whole command
    and a shell's `-c` string; what it could not read there, ask mode still asks about."""
    if (legacy or depth == 0) and not _shlex_reads(text):
        reading.unreadable = True
    try:
        if depth > 6:
            raise shell.Unreadable("commands nested too deep")
        pieces = shell.parse(text)
    except shell.Unreadable:
        reading.safe = False
        reading.ask(_scan(text, ctx))
        reading.texts += [part.strip() for part in re.split(r"[;&|\n()]+", text) if part.strip()]
        return
    saved: list[tuple[Path | None, bool]] = []
    for index, piece in enumerate(pieces):
        if isinstance(piece, str):
            if piece == "(":
                saved.append((line.cwd, line.moved))
            elif piece == ")":
                if saved:
                    line.cwd, line.moved = saved.pop()
            elif piece != "&&" and line.moved:
                line.cwd, line.moved = None, False  # the `cd` before it may not have run
            continue
        before = pieces[index - 1] if index and isinstance(pieces[index - 1], str) else ""
        after = pieces[index + 1] if index + 1 < len(pieces) and isinstance(pieces[index + 1], str) else ""
        _simple(piece, str(before), str(after), line, ctx, reading, depth)


def _piped(operator: str) -> bool:
    return operator in ("|", "|&", "&")


def _simple(simple: Simple, before: str, after: str, line: _Line, ctx: _Context, reading: Reading,
            depth: int) -> None:
    reading.texts += _command_texts(simple, line, ctx)
    for word in simple.all_words():
        for inner in word.subs:  # a substitution runs first, from the same folder
            _read(inner, line.child(), ctx, reading, depth + 1)
    _inner(simple, before, line, ctx, reading, depth)
    reading.ask(_danger(simple, line, ctx))
    safe = _safe(simple, line, ctx)
    reading.safe = reading.safe and safe
    head = simple.words[0] if simple.words else None
    program = head.text if head is not None and head.literal else ""
    if program == "cd" and not simple.assigns:
        line.cwd = _cd(simple, before, after, line, ctx)
        line.moved = line.cwd is not None
    elif head is not None and (program in CHANGE_FOLDER or not head.literal or _start([w.text for w in simple.words])):
        line.cwd = None  # it may move the shell, or run something that does
    if not (safe and _read_only(simple)):
        line.mutated = True
    if not safe or _rewrites_tree(simple):
        line.tree_changed = True
    if not safe or program == "mkdir" or _rewrites_tree(simple):
        line.made_folders = True
    if program == "mkdir":
        line.made += [real for word in simple.words[1:] if not word.text.startswith("-")
                      for real in [_real(word.text, line.cwd)] if real is not None]


def _cd(simple: Simple, before: str, after: str, line: _Line, ctx: _Context) -> Path | None:
    """The folder a `cd` moves to, when it can be proven: a bare `cd DIR` with at most -L or -P, a
    literal folder that exists and can be entered, not in a pipe or after `||`, with nothing before
    it in the line that could have changed the files. Without -P the shell reads `..` against the
    path as written, not past its links, so a `..` then is not followed."""
    if (line.cwd is None or line.mutated or _piped(before) or _piped(after) or before == "||"
            or simple.words[0].raw != "cd"):
        return None
    rest = simple.words[1:]
    if any(not word.literal for word in rest):
        return None
    operands = [word.text for word in rest if word.text not in ("-L", "-P", "--")]
    if len(operands) != 1 or operands[0].startswith("-"):
        return None
    target = operands[0]
    physical = [word.text for word in rest if word.text in ("-L", "-P")][-1:] == ["-P"]
    if ".." in target.split("/") and not physical:
        return None
    if ctx.cdpath and not os.path.isabs(target) and not target.startswith(("./", "../")) and target not in (".", ".."):
        return None
    real = _real(target, line.cwd)
    if real is None or not os.path.isdir(real) or not os.access(real, os.X_OK):
        return None
    return Path(real)


def _command_texts(simple: Simple, line: _Line, ctx: _Context) -> list[str]:
    """A simple command as the patterns see it: as written, from its program on, with its
    program's path read from the project's root, and for git with its global options taken out,
    so `git -C . push` is still `git push`."""
    words = [word.text for word in simple.words]
    found = [" ".join(word.text for word in (*simple.assigns, *simple.words))]
    start = _start(words)
    if start < len(words):
        found.append(" ".join(words[start:]))
        found += _program_texts(words[start:], line, ctx)
        if os.path.basename(words[start]) == "git":
            sub, rest = _git_subcommand(words[start + 1:])
            if sub:
                found.append(" ".join(["git", sub, *rest]))
    return [text for text in found if text]


def _program_texts(words: list[str], line: _Line, ctx: _Context) -> list[str]:
    found = []
    program = words[0]
    if program.startswith("./"):
        found.append(" ".join([program[2:], *words[1:]]))
    if "/" in program:
        real = _real(program, line.cwd)
        name = None if real is None else _within(real, ctx.home)
        if name:
            found.append(" ".join([name, *words[1:]]))
    return found


# -- danger -------------------------------------------------------------------------------------


def _start(words: list[str]) -> int:
    """Where the program of a simple command stands, past assignments, wrappers, runners such as
    `uv run`, and keywords."""
    index = 0
    while index < len(words):
        word = words[index].lstrip("`$")
        name = os.path.basename(word)
        if "=" in word and not word.startswith("-") and word.split("=", 1)[0].isidentifier():
            index += 1
        elif index + 1 < len(words) and (name, words[index + 1]) in RUNNERS:
            index += 2
            while index < len(words) and words[index].startswith("-"):
                index += 1
        elif name in WRAPPERS:
            index += 1
            while index < len(words) and words[index].startswith("-"):
                index += 1
            index += POSITIONAL.get(name, 0)
        elif word in KEYWORDS:
            index += 1
        else:
            return index
    return index


def _program(words: list[str]) -> tuple[str, list[str], int]:
    """The program a simple command runs, past any assignments and wrappers, its arguments, and
    where it stands."""
    index = _start(words)
    if index >= len(words):
        return "", [], index
    return os.path.basename(words[index].lstrip("`$")), words[index + 1:], index


def _operands(args: list[str]) -> list[str]:
    """The arguments that are not options; after `--`, all of them."""
    found, ended = [], False
    for arg in args:
        if arg == "--" and not ended:
            ended = True
        elif ended or not arg.startswith("-") or arg == "-":
            found.append(arg)
    return found


def _after_themis(words: list[str]) -> str | None:
    """The first word after `themis`, when this command runs themis however it is launched:
    `themis`, a path to it, or `python -m themis` and `-m themis.cli`."""
    for index, word in enumerate(words):
        base = os.path.basename(word.lstrip("`$"))
        module = word[2:] if word.startswith("-m") and len(word) > 2 else (word if index and words[index - 1] == "-m" else "")
        if base == "themis" or module == "themis" or module.startswith("themis."):
            rest = [later for later in words[index + 1:] if not later.startswith("-")]
            return rest[0] if rest else ""
    return None


def _flag(words: list[str], name: str) -> str | None:
    """The value given to a flag, written as `--name value` or `--name=value`."""
    for index, word in enumerate(words):
        if word == name and index + 1 < len(words):
            return words[index + 1]
        if word.startswith(f"{name}="):
            return word.split("=", 1)[1]
    return None


def _long(flag: str, *names: str) -> bool:
    """True when `flag` is one of these long options, or an abbreviation git and GNU tools accept."""
    name = flag[2:].split("=", 1)[0] if flag.startswith("--") else ""
    return bool(name) and any(full.startswith(name) for full in names)


def _short(flag: str, chars: str) -> bool:
    """True when a cluster of short options such as `-fu` holds one of these letters."""
    return flag.startswith("-") and not flag.startswith("--") and any(char in flag[1:] for char in chars)


def _hits(word: Word, cwd: Path | None, ctx: _Context) -> tuple[str, str] | None:
    """(what is touched, "protected" or "kept") when a written, moved or deleted word names a
    protected or kept path, or a folder that holds one, compared without regard to case."""
    text = word.text
    if not text or word.expands or (text.startswith("-") and text != "-"):
        return None
    protected, keep = ctx.policy.protected, ctx.policy.keep
    names: list[str] = []
    real = _real(text, cwd)
    if real is not None:
        name = _within(real, ctx.home)
        if name is not None:
            names.append(name)
        elif _guarded(real, ctx.policy.outside):
            return real, "protected"
    if cwd is None and not os.path.isabs(text) and not text.startswith("~"):
        names.append(os.path.normpath(text))  # the stricter reading: from the root
        base = os.path.basename(text.rstrip("/")).casefold()
        for kind, patterns in (("protected", protected), ("kept", keep)):
            lasts = [pattern.casefold().rstrip("/").rsplit("/", 1)[-1] for pattern in patterns]
            if any(last.strip("*?") and _fnmatch(base, last) for last in lasts):
                return text, kind
    for name in names:
        if word.glob:
            for kind, patterns in (("protected", protected), ("kept", keep)):
                if any(_could_touch(name, pattern) for pattern in patterns):
                    return name, kind
        if _touches(name, protected, ctx.root):
            return name or "the project", "protected"
        if _touches(name, keep, ctx.root):
            return name or "the project", "kept"
    return None


def _write_danger(word: Word, cwd: Path | None, ctx: _Context) -> str | None:
    hit = _hits(word, cwd, ctx)
    if hit is None:
        return None
    name, kind = hit
    if kind == "protected":
        return f"This command writes to {name}, which only the owner changes."
    return f"This command writes to or moves {name}, which the project keeps."


def _temp_word(word: Word, line: _Line, ctx: _Context) -> bool:
    """True when a word names a path inside a temp folder: literal, placed, past every link, with
    no command before it in the line that could have made a link."""
    if not word.literal or line.tree_changed or not ctx.temp:
        return False
    real = _real(word.text, line.cwd)
    return real is not None and not _guarded(real, ctx.policy.outside) and _scratch(real, ctx.home, ctx.temp)


def _deleting(targets: list[Word], line: _Line, ctx: _Context, what: str = "This command deletes files.") -> str | None:
    """Why a delete of these targets needs the owner, or None when every one is scratch."""
    for target in targets:
        hit = _hits(target, line.cwd, ctx)
        if hit and hit[1] == "kept":
            return f"This command deletes {hit[0]}, which the project keeps."
    if targets and all(_temp_word(target, line, ctx) for target in targets):
        return None
    return what


def _written(program: str, args: list[Word], cwd: Path | None) -> tuple[list[Word], Word | None]:
    """What a writer changes, and the folder it writes into, if any. A copier or `mv` changes only
    what it writes to: into a folder, each source's name there (the folder itself for a source
    ending in `/` or `.`). Any other writer changes every argument."""
    if program not in COPIERS and program != "mv":
        return list(args), None
    operands = [word for word in args if not word.text.startswith("-") or word.text == "-"]
    texts = [word.text for word in args]
    named = _flag(texts, "-t") or _flag(texts, "--target-directory")
    if named is not None:
        folder = next((word for word in operands if word.text == named), Word(text=named, raw=named))
        sources = [word for word in operands if word is not folder]
    elif operands:
        folder, sources = operands[-1], operands[:-1]
        real = _real(folder.text, cwd)
        into = folder.text.endswith("/") or (real is not None and os.path.isdir(real)) or program == "rsync"
        if not sources or not into:
            return [folder], folder
    else:
        return [], None
    found = []
    for source in sources:
        base = os.path.basename(source.text.rstrip("/"))
        inside = source.text.endswith("/") or base in (".", "")
        text = folder.text if inside else os.path.join(folder.text, base)
        found.append(Word(text=text, raw=text, glob=folder.glob or source.glob, quoted=folder.quoted or source.quoted,
                          bare=folder.bare or source.bare))
    return found or [folder], folder


def _in_place(program: str, args: list[str]) -> bool:
    """True when sed, perl or ruby edits its files in place: `-i` alone or in a cluster such as
    `-Ei` or `-pi`, or sed's `--in-place` however shortened."""
    for arg in args:
        if arg == "--":
            return False
        if program == "sed" and arg.startswith("--") and _long(arg, "in-place"):
            return True
        if _short(arg, "i"):
            return True
    return False


def _remote(text: str) -> bool:
    """True for an rsync or scp operand on another machine: `host:path` or `rsync://`."""
    return "://" in text or bool(re.match(r"[^/.][^/]*?:", text))


def _sends(program: str, args: list[str]) -> bool:
    """True when curl or wget sends data or asks a remote host to change something."""
    urls = [arg for arg in args if "://" in arg]
    if urls and all((urllib.parse.urlsplit(url).hostname or "") in LOCAL_HOSTS for url in urls):
        return False
    if program == "wget":
        return any(arg.startswith(("--post-data", "--post-file", "--method", "--body-data", "--body-file")) for arg in args)
    for index, arg in enumerate(args):
        method = (args[index + 1] if index + 1 < len(args) else "") if arg in ("-X", "--request") else (
            arg[2:] if arg.startswith("-X") else arg.split("=", 1)[1] if arg.startswith("--request=") else None)
        if method is not None and method.upper() not in ("GET", "HEAD", "OPTIONS"):
            return True
        if arg.startswith(("-d", "--data", "--json", "-F", "--form", "-T", "--upload")):
            return True
    return False


def _danger(simple: Simple, line: _Line, ctx: _Context) -> str | None:
    """Why the owner must approve this simple command, or None."""
    cwd = line.cwd
    for redirect in simple.redirects:
        if not (redirect.reads or redirect.duplicates):
            reason = _write_danger(redirect.target, cwd, ctx)
            if reason:
                return reason
    if not simple.words:
        return None
    words = [word.text for word in simple.words]
    program, args, start = _program(words)
    argw = simple.words[start + 1:]
    # Behind a wrapper such as sudo or xargs, the real program is somewhere among the words.
    names = {os.path.basename(word.lstrip("`$")) for word in words}
    leading = {os.path.basename(word) for word in words[:start]}
    behind = names if leading & WRAPPERS or any((a, b) in RUNNERS for a, b in zip(words[:start], words[1:start + 1])) else set()
    if program in DELETERS or behind & DELETERS:
        # What a wrapper such as xargs deletes is not on the line, so it always asks.
        targets = [word for word in argw if not word.text.startswith("-") or word.text == "-"] if program in DELETERS else []
        reason = _deleting(targets, line, ctx)
        if reason:
            return reason
    if program in REMOTES or behind & REMOTES:
        return "This command reaches a remote machine."
    if program == "rsync" or "rsync" in behind:
        operands = [word for word in argw if not word.text.startswith("-")]
        if any(_remote(word.text) for word in operands) or any(_short(arg, "e") or _long(arg, "rsh") for arg in args):
            return "This command reaches a remote machine."
        if operands and any(_long(arg, "delete", "remove-source-files") or arg.startswith("--del") for arg in args):
            reason = _deleting(operands[-1:], line, ctx)
            if reason:
                return reason
    if program in ("curl", "wget") and _sends(program, args):
        return "This command sends data to, or changes something on, another machine."
    if program in CLOUD and set(args) & CLOUD_DELETES:
        return "This command deletes or changes something on a remote service."
    if program == "find":
        if "-delete" in args or any(os.path.basename(arg) in DELETERS for arg in args):
            starts = []
            for word in argw:
                if word.text.startswith(("-", "(", "!")):
                    break
                starts.append(word)
            follows = any(arg in ("-L", "-follow", "-H") for arg in args)
            # Following links, find may delete anywhere they lead, so no folder counts as scratch.
            reason = _deleting(starts or [Word(text=".", raw=".")], _Line(None, tree_changed=True) if follows else line, ctx)
            if reason:
                return reason
        for index, arg in enumerate(args):
            if arg in ("-fprint", "-fprint0", "-fprintf", "-fls") and index + 1 < len(argw):
                reason = _write_danger(argw[index + 1], cwd, ctx)
                if reason:
                    return reason
    if program in ("tar", "bsdtar", "gtar", "unzip"):
        reason = _unpacks(program, args, cwd, ctx)
        if reason:
            return reason
    moved: list[Word] = []
    if program == "git":
        reason, moved = _git_danger(simple, args, argw, line, ctx)
        if reason:
            return reason
    asked = _after_themis(words)
    if asked == "grant":
        return "Only the owner gives a grant."
    if asked == "decide" and ("--by=owner" in words or "owner" in words[words.index("--by") + 1:][:1]
                              if "--by" in words else "--by=owner" in words):
        return "Only the owner overrules a gate."
    if asked == "attest" and _flag(words, "--judge") == OWNER:
        return "Only the owner attests as the owner."
    targets, kept = list(moved), list(moved)
    if program in WRITERS or (program in IN_PLACE and _in_place(program, args)):
        written, folder = _written(program, argw, cwd)
        sources = [word for word in argw if word is not folder and (not word.text.startswith("-") or word.text == "-")]
        if program not in COPIERS and program != "mv":
            sources = list(argw)
        targets += sources + written
        kept += written + (sources if program == "mv" else [])
    if program == "dd":
        targets += [Word(text=arg[3:], raw=arg[3:]) for arg in args if arg.startswith("of=")]
        kept += [Word(text=arg[3:], raw=arg[3:]) for arg in args if arg.startswith("of=")]
    for word in targets:
        hit = _hits(word, cwd, ctx)
        if hit and hit[1] == "protected":
            return f"This command writes to {hit[0]}, which only the owner changes."
    for word in kept:
        hit = _hits(word, cwd, ctx)
        if hit and hit[1] == "kept":
            return f"This command writes to or moves {hit[0]}, which the project keeps."
    return None


def _unpacks(program: str, args: list[str], cwd: Path | None, ctx: _Context) -> str | None:
    """Why an archive unpacked into a folder holding protected or kept files needs the owner."""
    if program == "unzip":
        folder = _flag(args, "-d") or "."
    else:
        first = args[0] if args else ""
        extracting = any(_long(arg, "extract", "get") or _short(arg, "x") for arg in args) or (
            first and not first.startswith("-") and "x" in first)
        if not extracting:
            return None
        folder = _flag(args, "-C") or _flag(args, "--directory") or "."
    hit = _hits(Word(text=folder, raw=folder), cwd, ctx)
    if hit is None:
        return None
    return f"This command unpacks files into {hit[0]}, which holds files only the owner changes."


def _git_folder_known(simple: Simple, args: list[str], cwd: Path | None) -> Path | None:
    """The folder a git command works in, past `-C`; None when `--git-dir`, `--work-tree` or a
    GIT_* variable points it elsewhere, or when the folder is a linked worktree whose branches and
    stashes are shared with another checkout."""
    if any(word.text.split("=", 1)[0] in GIT_ENV for word in simple.assigns):
        return None
    folder: Path | None = cwd
    index = 0
    while index < len(args) and args[index].startswith("-"):
        arg = args[index]
        if arg in ("--git-dir", "--work-tree") or arg.startswith(("--git-dir=", "--work-tree=")):
            return None
        if arg == "-C" and index + 1 < len(args):
            real = _real(args[index + 1], folder)
            folder = None if real is None else Path(real)
        index += 2 if arg in GIT_VALUED else 1
    return folder


def _git_subcommand(args: list[str]) -> tuple[str, list[str]]:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in GIT_VALUED else 1  # an option's value is not the subcommand
    return (args[index], args[index + 1:]) if index < len(args) else ("", [])


def _git_local(sub: str, rest: list[str], flags: list[str], cwd: Path | None) -> str | None:
    """What a git command deletes or throws away in its own repository, or None."""
    if sub in ("rm", "clean"):
        return "This command deletes files."
    if sub == "branch" and any(_long(flag, "delete") or _short(flag, "dD") for flag in flags):
        return "This command deletes a branch."
    if sub == "branch" and any(_long(flag, "force") or _short(flag, "MCf") for flag in flags):
        return "This command overwrites a branch."
    if (sub == "reset" and any(_long(flag, "hard") for flag in flags)) or (sub == "stash" and rest[:1] in (["drop"], ["clear"])):
        return "This command throws away work."
    if sub in ("checkout", "switch") and any(_long(flag, "force", "discard-changes") or _short(flag, "fBC") for flag in flags):
        return "This command throws away work."
    if sub == "checkout":
        named = {rest[index + 1] for index, word in enumerate(rest[:-1]) if word in ("-b", "-B", "--orphan")}
        operands = [operand for operand in _operands(rest) if operand not in named]
        if "." in rest or ("--" in rest and rest.index("--") + 1 < len(rest)) or len(operands) >= 2 or any(
                operand.startswith(":") or any(char in operand for char in "*?[") for operand in operands) or (
                cwd is not None and any(os.path.lexists(os.path.join(cwd, operand)) for operand in operands)):
            return "This command throws away work."
    if sub == "restore":
        staged = any(_long(flag, "staged") or _short(flag, "S") for flag in flags)
        worktree = any(_long(flag, "worktree") or _short(flag, "W") for flag in flags)
        if worktree or not staged:
            return "This command throws away work."
    return None


def _git_danger(simple: Simple, args: list[str], argw: list[Word], line: _Line,
                ctx: _Context) -> tuple[str | None, list[Word]]:
    """Why a git command needs the owner, and the paths `git mv` moves."""
    reason, moved = _git_own_danger(simple, args, argw, line, ctx)
    if reason:
        return reason, moved
    index = 0
    while index < len(args) and args[index].startswith("-"):
        if (args[index] == "-c" and index + 1 < len(args) and GIT_RUNS.match(args[index + 1])) or (
                args[index].startswith("--config-env")):
            return "This command makes git run a program, or move its hooks, for this one command.", []
        index += 2 if args[index] in GIT_VALUED else 1
    return None, moved


def _git_own_danger(simple: Simple, args: list[str], argw: list[Word], line: _Line,
                    ctx: _Context) -> tuple[str | None, list[Word]]:
    sub, rest = _git_subcommand(args)
    flags = [word for word in rest if word.startswith("-")]
    folder = _git_folder_known(simple, args, line.cwd)
    shared = folder is not None and (folder / ".git").is_file()  # a linked worktree shares branches and stashes
    hooked = ("commit", "push", "merge", "rebase", "am", "cherry-pick", "revert", "pull")
    if (sub in hooked and any(_long(flag, "no-verify") for flag in flags)) or (
            sub == "commit" and any(_short(flag, "n") for flag in flags)):
        return "This command skips the git hooks.", []
    if sub == "worktree" and rest[:1] == ["remove"]:
        targets = [Word(text=text, raw=text) for text in _operands(rest[1:])]
        if not targets or not all(_temp_word(target, _Line(folder, tree_changed=line.tree_changed), ctx) for target in targets):
            return "This command deletes files.", []
    local = _git_local(sub, rest, flags, folder)
    if local:
        here = folder is not None and not shared and _temp_word(Word(text=str(folder), raw=str(folder)), line, ctx)
        if not here:
            return local, []
    if sub == "push" and (
        any(_long(flag, "delete", "force", "force-with-lease", "force-if-includes", "mirror", "prune")
            or _short(flag, "df") for flag in flags)
        or any(word.startswith((":", "+")) for word in rest if not word.startswith("-"))
    ):
        return "This command deletes or overwrites something on the remote.", []
    if sub == "mv":
        start = len(argw) - len(rest)
        return None, [word for word in argw[start:] if not word.text.startswith("-")]
    return None, []


def _inner(simple: Simple, before: str, line: _Line, ctx: _Context, reading: Reading, depth: int) -> None:
    """Read the commands a simple command runs in turn: a shell's `-c` string, its script or what
    it reads, `eval`, `env -S`, an alias, `find -exec`, and the code given to an interpreter."""
    words = [word.text for word in simple.words]
    program, args, start = _program(words)
    if not program:
        return
    bodies = [redirect.body if redirect.body is not None else redirect.target.text
              for redirect in simple.redirects if redirect.op in ("<<", "<<-", "<<<")]
    if program in SHELLS:
        code = next((args[index + 1] for index, arg in enumerate(args)
                     if arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:] and index + 1 < len(args)), None)
        script = next((arg for arg in args if not arg.startswith(("-", "+"))), None)
        if code is not None:
            _read(code, line.child(), ctx, reading, depth + 1, legacy=True)
        elif script is not None and code is None:
            rest = args[args.index(script):]
            reading.texts += [" ".join(rest), *_program_texts(rest, line, ctx)]
        for body in bodies:
            _read(body, line.child(), ctx, reading, depth + 1)
        if code is None and script is None and _piped(before):
            reading.ask(_scan(ctx.text, ctx))  # the shell runs what the pipe gives it
    elif program == "eval":
        _read(" ".join(args), line.child(), ctx, reading, depth + 1)
    elif program == "alias":
        for arg in args:
            if "=" in arg:
                _read(arg.split("=", 1)[1], line.child(), ctx, reading, depth + 1)
    elif program in ("source", "."):
        reading.texts += [" ".join(args)]
    elif program == "find":
        for index, arg in enumerate(args):
            if arg in ("-exec", "-execdir", "-ok", "-okdir"):
                end = next((later for later in range(index + 1, len(args)) if args[later] in (";", "+")), len(args))
                _read(shlex.join(args[index + 1:end]), line.child(), ctx, reading, depth + 1)
    if "env" in {os.path.basename(word) for word in words[:start]}:
        split = _flag(words, "-S") or _flag(words, "--split-string")
        if split:
            _read(split, line.child(), ctx, reading, depth + 1)
    base = re.sub(r"[\d.]+$", "", program)
    if base in INTERPRETERS or program in INTERPRETERS:
        codes = list(bodies)
        if base in ("awk", "gawk", "mawk", "nawk"):
            codes += [arg for arg in args if not arg.startswith("-")]
        for index, arg in enumerate(args[:-1]):
            if arg in ("-c", "-e", "-E", "-r", "--eval", "-p", "--print") or (
                    arg.startswith("-") and not arg.startswith("--") and arg[-1:] in "ceE"):
                codes.append(args[index + 1])
        for code in codes:
            reading.ask(_code_danger(code, ctx))


def _code_danger(code: str, ctx: _Context) -> str | None:
    if CODE_DANGER.search(code):
        return "This command runs code that deletes files or runs other programs."
    for pattern in (*ctx.policy.protected, *ctx.policy.keep):
        literal = _literal(pattern)
        if literal and literal.casefold() in code.casefold():
            return f"This command runs code that names {pattern}, which only the owner changes."
    return None


def _literal(pattern: str) -> str:
    """The longest stretch of a path pattern without a wildcard, to look for in raw text."""
    longest = max(re.split(r"[*?\[\]]", pattern), key=len).lstrip("/")
    return longest if len(longest.strip("/")) >= 3 else ""


def _scan(text: str, ctx: _Context) -> str | None:
    """Why the raw text of a command Themis cannot read in full needs the owner: it names a danger,
    or it writes and names a protected or kept path. None when it names neither."""
    for pattern, what in DANGER_TEXT:
        found = pattern.search(text)
        if found:
            return f"Themis cannot read all of this command, and its text names {what}: `{found.group(0).strip()}`."
    if WRITE_TEXT.search(text):
        for patterns, whose in ((ctx.policy.protected, "which only the owner changes"),
                                (ctx.policy.keep, "which the project keeps")):
            for pattern in patterns:
                literal = _literal(pattern)
                if literal and literal.casefold() in text.casefold():
                    return f"Themis cannot read all of this command, and it writes beside {pattern}, {whose}."
    return None


# -- what allow-safe allows ---------------------------------------------------------------------


def _plain(args: list[Word], *, short: str = "", long: tuple[str, ...] = (), glob: bool = True,
           dynamic: bool = False, operands: int | None = None) -> list[Word] | None:
    """The operands, when no option is forbidden and every word is plain enough; else None. A
    forbidden long option matches however it is shortened, as GNU tools accept."""
    found, ended = [], False
    for word in args:
        if word.expands and not dynamic:
            return None
        if (word.glob or word.brace or word.tilde) and not glob:
            return None
        text = word.text
        if ended or word.expands or text == "-" or not text.startswith("-"):
            found.append(word)
        elif text == "--":
            ended = True
        elif text.startswith("--"):
            name = text[2:].split("=", 1)[0].casefold()
            if any(full.startswith(name) or name.startswith(full) for full in long):
                return None
        elif any(char in short for char in text[1:]):
            return None
    if operands is not None and len(found) > operands:
        return None
    return found


Rule = Callable[[list[Word], _Line, _Context], bool]


def _tool(**rules: Any) -> Rule:
    return lambda args, line, ctx: _plain(args, **rules) is not None


def _writable(word: Word, line: _Line, ctx: _Context) -> bool:
    """True when a literal path may be written: inside a temp folder, or inside the project away
    from every protected and kept path and the folders that hold them."""
    if not word.literal or line.tree_changed:
        return False
    real = _real(word.text, line.cwd)
    if real is None or _guarded(real, ctx.policy.outside):
        return False
    if any(_within(real, made) for made in line.made):
        return False  # under a folder this line made: what it holds is not known when the hook reads
    if ctx.temp and _scratch(real, ctx.home, ctx.temp):
        return True
    name = _within(real, ctx.home)
    return bool(name) and not _touches(name, (*ctx.policy.protected, *ctx.policy.keep), ctx.root)


def _maker(args: list[Word], line: _Line, ctx: _Context) -> bool:
    found = _plain(args, glob=False)
    return bool(found) and all(_writable(word, line, ctx) for word in found or [])


def _remover(chars: str, longs: tuple[str, ...]) -> Rule:
    def check(args: list[Word], line: _Line, ctx: _Context) -> bool:
        found, ended = [], False
        for word in args:
            text = word.text
            if not word.literal:
                return False
            if not ended and text == "--":
                ended = True
            elif not ended and text.startswith("--"):
                if text[2:] not in longs:
                    return False
            elif not ended and text.startswith("-") and text != "-":
                if set(text[1:]) - set(chars):
                    return False
            else:
                found.append(word)
        return bool(found) and all(_temp_word(word, line, ctx) for word in found)

    return check


SED_SCRIPT = re.compile(
    r"(?:(?:\d+|\$)(?:,(?:\d+|\$))?)?"
    r"(?:[pd=]|s(?P<d>[/|#:,@])(?:(?!(?P=d))[^\\\n]|\\.)*(?P=d)(?:(?!(?P=d))[^\\\n]|\\.)*(?P=d)[gIipmM0-9]*)"
)
SED_LONG = {"quiet", "silent", "regexp-extended", "null-data", "zero-terminated", "separate", "unbuffered", "posix",
            "sandbox", "debug"}


def _sed(args: list[Word], line: _Line, ctx: _Context) -> bool:
    """sed that only prints: no in-place edit, no script file, and each script a print, a delete
    from the output, or a substitution without the `w` or `e` flags."""
    scripts, operands, index, ended = [], [], 0, False
    while index < len(args):
        word, text = args[index], args[index].text
        if not word.literal:
            return False
        if not ended and text == "--":
            ended = True
        elif not ended and text in ("-e", "--expression"):
            if index + 1 >= len(args) or not args[index + 1].literal:
                return False
            scripts.append(args[index + 1].text)
            index += 1
        elif not ended and text.startswith("--expression="):
            scripts.append(text.split("=", 1)[1])
        elif not ended and text.startswith("--"):
            if text[2:] not in SED_LONG:
                return False
        elif not ended and text.startswith("-") and text != "-":
            if set(text[1:]) - set("nEsurz"):
                return False
        else:
            operands.append(text)
        index += 1
    if not scripts:
        if not operands:
            return False
        scripts = [operands.pop(0)]
    return all(SED_SCRIPT.fullmatch(script.strip()) for script in scripts)


def _printf(args: list[Word], line: _Line, ctx: _Context) -> bool:
    """printf with a plain format first: no option, so never `-v`, which sets a shell variable. The
    values after the format may come from substitutions, which are read in turn."""
    return bool(args) and args[0].literal and not args[0].text.startswith("-")


FIND_ACTS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}


def _find(args: list[Word], line: _Line, ctx: _Context) -> bool:
    return all(word.literal and word.text not in FIND_ACTS for word in args)


GIT_READ = {"status", "log", "show", "diff", "rev-parse", "rev-list", "ls-files", "ls-tree", "blame", "describe",
            "shortlog", "merge-base", "cat-file", "show-ref", "grep"}
GIT_READ_LONG = ("output", "ext-diff", "open-files-in-pager", "exec")
GIT_GLOBAL = {"--no-pager", "-P", "--no-optional-locks", "--literal-pathspecs"}
MERGE_OK = {"--ff-only", "-q", "--quiet", "-v", "--verbose", "--stat", "-n", "--no-stat", "--progress", "--no-progress"}
WORKTREE_OK = {"--detach", "-d", "--lock", "--track", "--no-track", "--checkout", "--no-checkout", "-q", "--quiet",
               "--guess-remote", "--no-guess-remote", "--orphan"}


def _git_safe(args: list[Word], line: _Line, ctx: _Context) -> bool:
    """git, inside the project only: read-only subcommands, and a short list that changes the
    repository without throwing anything away. Options are matched exactly, never by prefix."""
    folder, index = line.cwd, 0
    while index < len(args) and args[index].text.startswith("-"):
        word = args[index]
        if not word.literal:
            return False
        if word.text in GIT_GLOBAL:
            index += 1
            continue
        if word.text == "-C" and index + 1 < len(args) and args[index + 1].literal:
            real = _real(args[index + 1].text, folder)
            if real is None or _within(real, ctx.home) is None:
                return False
            folder, index = Path(real), index + 2
            continue
        return False
    if folder is None or index >= len(args) or not args[index].literal:
        return False
    real = os.path.realpath(folder)
    if _within(real, ctx.home) is None:
        return False  # a repository elsewhere may carry hooks or a configuration that runs programs
    parts = Path(_within(real, ctx.home) or ".").parts
    if any((Path(ctx.home, *parts[:size]) / ".git").exists() for size in range(1, len(parts) + 1) if parts != (".",)):
        return False  # a repository nested in the project
    if line.made_folders:
        return False  # a folder made earlier in the line may be a repository git would run in
    sub, rest = args[index].text, args[index + 1:]
    if sub in GIT_READ:
        return _plain(rest, short="O" if sub == "grep" else "", long=GIT_READ_LONG, glob=False) is not None
    if sub == "stash":
        return bool(rest) and rest[0].text in ("list", "show") and _plain(rest[1:], long=GIT_READ_LONG, glob=False) is not None
    if sub == "remote":
        return all(word.literal and word.text in ("-v", "--verbose") for word in rest)
    rule = GIT_CHANGES.get(sub)
    return rule is not None and rule(rest, Path(real), line, ctx)


def _git_branch(rest: list[Word], folder: Path, line: _Line, ctx: _Context) -> bool:
    return _plain(rest, short="dDmMcCfe", long=("delete", "move", "copy", "force", "edit-description"), glob=False) is not None


def _git_add(rest: list[Word], folder: Path, line: _Line, ctx: _Context) -> bool:
    cut = next((index for index, word in enumerate(rest) if word.literal and word.text == "--"), len(rest))
    return (_plain(rest[:cut], short="ipe", long=("interactive", "patch", "edit"), glob=False) is not None
            and all(not word.expands for word in rest[cut + 1:]))


def _git_commit(rest: list[Word], folder: Path, line: _Line, ctx: _Context) -> bool:
    """A commit with its message given (no editor), that does not amend or skip the hooks. The
    message may come from a quoted substitution, which is read in turn."""
    message, index = False, 0
    while index < len(rest):
        word, text = rest[index], rest[index].text
        if text in ("-m", "--message", "-F", "--file", "-C", "--reuse-message") and word.literal:
            if index + 1 >= len(rest) or rest[index + 1].bare or rest[index + 1].glob:
                return False
            message, index = True, index + 2
            continue
        if text.startswith(("--message=", "--file=", "--reuse-message=")) and not word.bare:
            message, index = True, index + 1
            continue
        if not word.literal:
            return False
        if text.startswith("--"):
            if text != "--" and _long(text, "amend", "edit", "reedit-message", "no-verify", "interactive", "patch",
                                      "template", "fixup", "squash"):
                return False
        elif text.startswith("-") and text != "-":
            for position, char in enumerate(text[1:]):
                if char in "ecnpt":
                    return False
                if char in "mFC":
                    message = True
                    if position == len(text) - 2:
                        if index + 1 >= len(rest) or rest[index + 1].bare or rest[index + 1].glob:
                            return False
                        index += 1
                    break
                if char in "Su":
                    break
        index += 1
    return message


#: A branch or remote named plainly: no `:`, `+`, `@`, `~`, `^`, glob, or `..`.
PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")


def _git_run(folder: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, check=False, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None


def _plain_name(text: str) -> bool:
    return bool(PLAIN_NAME.fullmatch(text)) and ".." not in text and not text.endswith(("/", ".lock")) and text != "HEAD"


def _local_branch(folder: Path, name: str) -> bool:
    """True when `name` is plainly an existing local branch, and no file of that name exists."""
    done = _git_run(folder, "show-ref", "--verify", "--quiet", f"refs/heads/{name}")
    return (_plain_name(name) and not os.path.lexists(os.path.join(folder, name))
            and done is not None and done.returncode == 0)


def _remotes(folder: Path) -> set[str]:
    done = _git_run(folder, "remote")
    return set(done.stdout.split()) if done is not None and done.returncode == 0 else set()


def _git_fetch(rest: list[Word], folder: Path, line: _Line, ctx: _Context) -> bool:
    """A fetch from a remote the repository names, with plain branch names: never a URL or a
    `host:path`, which reach any machine, and no prune or force."""
    flags = {"-q", "--quiet", "-v", "--verbose", "--tags", "--no-tags", "--progress", "--no-progress"}
    if not all(word.literal for word in rest) or any(word.text.startswith("-") and word.text not in flags for word in rest):
        return False
    operands = [word.text for word in rest if not word.text.startswith("-")]
    if not operands:
        return True
    if operands[0] not in _remotes(folder):
        return False
    return all(all(_plain_name(part) for part in spec.split(":", 1)) for spec in operands[1:])


def _branch_move(rest: list[Word], folder: Path, create: tuple[str, ...]) -> bool:
    """`git switch NAME` or `git checkout NAME` for an existing local branch, or a new branch made
    with -c or -b, from a start point named plainly that is not a file. Nothing else: no path, no
    pathspec, no glob, no force."""
    if not all(word.literal for word in rest):
        return False
    texts = [word.text for word in rest if word.text not in ("-q", "--quiet")]
    if texts and texts[0] in create:
        if len(texts) not in (2, 3) or not _plain_name(texts[1]):
            return False
        start = texts[2:]
        return all(_plain_name(name) and not os.path.lexists(os.path.join(folder, name)) for name in start)
    return len(texts) == 1 and _local_branch(folder, texts[0])


def _git_switch(rest: list[Word], folder: Path, line: _Line, ctx: _Context) -> bool:
    return _branch_move(rest, folder, ("-c", "--create"))


def _git_checkout(rest: list[Word], folder: Path, line: _Line, ctx: _Context) -> bool:
    return _branch_move(rest, folder, ("-b",))


def _git_merge(rest: list[Word], folder: Path, line: _Line, ctx: _Context) -> bool:
    texts = [word.text for word in rest]
    return all(word.literal for word in rest) and "--ff-only" in texts and all(
        text in MERGE_OK or not text.startswith("-") for text in texts)


def _git_worktree(rest: list[Word], folder: Path, line: _Line, ctx: _Context) -> bool:
    if not rest or not all(word.literal for word in rest):
        return False
    if rest[0].text == "list":
        return all(word.text in ("--porcelain", "-v", "--verbose", "-z") for word in rest[1:])
    if rest[0].text != "add":
        return False
    operands, index = [], 1
    while index < len(rest):
        text = rest[index].text
        if text in ("-b", "--reason"):
            index += 2
            continue
        if text.startswith("-") and text not in WORKTREE_OK and not text.startswith("--reason="):
            return False
        if not text.startswith("-"):
            operands.append(rest[index])
        index += 1
    return bool(operands) and _writable(operands[0], _Line(folder), ctx)


def _git_push(rest: list[Word], folder: Path, line: _Line, ctx: _Context) -> bool:
    """Only `git push [-u] REMOTE BRANCH`: a remote the repository names, with no push mapping or
    mirror in its configuration, and an existing local branch named plainly that is not the main
    line under any of its names. Anything else gets no answer."""
    if not all(word.literal for word in rest):
        return False
    texts = [word.text for word in rest if word.text not in ("-u", "--set-upstream")]
    if len(texts) != 2 or any(text.startswith("-") for text in texts):
        return False
    remote, branch = texts
    main = ctx.policy.main.removeprefix("refs/").removeprefix("heads/").removeprefix("remotes/").split("/")[-1]
    default = _git_run(folder, "symbolic-ref", "-q", "--short", f"refs/remotes/{remote}/HEAD")
    named = default.stdout.strip().removeprefix(f"{remote}/") if default is not None else ""
    mains = {"main", "master", main.casefold(), named.casefold()} - {""}  # also the remote's own default branch
    if remote not in _remotes(folder) or branch.casefold() in mains or branch.startswith(("refs/", "heads/", "remotes/", "tags/")):
        return False
    mapped = _git_run(folder, "config", "--get-regexp", rf"^remote\.{re.escape(remote)}\.(push|mirror)$")
    if mapped is None or mapped.stdout.strip():
        return False
    return _local_branch(folder, branch)


GIT_CHANGES: dict[str, Callable[[list[Word], Path, _Line, _Context], bool]] = {
    "branch": _git_branch, "add": _git_add, "commit": _git_commit, "fetch": _git_fetch, "switch": _git_switch,
    "checkout": _git_checkout, "merge": _git_merge, "worktree": _git_worktree, "push": _git_push,
}

#: The built-in safe list. Interpreters, shells, runners and anything else that runs other
#: commands are never on it; only the project's own `allow` patterns can let one through.
SAFE: dict[str, Rule] = {
    **{name: _tool() for name in ("ls", "cat", "head", "tail", "wc", "cut", "diff", "cmp", "grep", "egrep", "fgrep",
                                  "tr", "nl", "comm", "basename", "dirname", "realpath", "readlink", "stat", "du",
                                  "which", "shasum", "sha1sum", "sha256sum", "md5sum", "md5", "pwd")},
    "sort": _tool(short="o", long=("output", "compress-program"), glob=False),
    "uniq": _tool(glob=False, operands=1),
    "rg": _tool(short="z", long=("pre", "pre-glob", "hostname-bin", "search-zip"), glob=False),
    "file": _tool(short="C", long=("compile",), glob=False),
    "date": _tool(short="sf", long=("set", "file"), glob=False),
    **{name: _tool(dynamic=True) for name in ("echo", "true", "false", "test", "[", "cd")},
    "printf": _printf, "sed": _sed, "find": _find, "mkdir": _maker, "touch": _maker, "git": _git_safe,
    "rm": _remover("rRfvdI", ("recursive", "force", "verbose", "dir")), "rmdir": _remover("v", ()),
}
#: Safe commands that change nothing, so a `cd` after them can still be followed.
READ_ONLY = set(SAFE) - {"mkdir", "touch", "rm", "rmdir", "git"}


def _redirect_safe(redirect: shell.Redirect, line: _Line, ctx: _Context) -> bool:
    if redirect.reads or redirect.duplicates:
        return True
    target = redirect.target
    if target.literal and target.text in DEVICES:
        return True
    return _writable(target, line, ctx)


def _safe(simple: Simple, line: _Line, ctx: _Context) -> bool:
    """True when allow-safe may allow this simple command: no assignment, a program named plainly,
    every redirection to a writable place, and either the project's `allow` pattern or the safe list."""
    if simple.assigns or not simple.words:
        return False
    head = simple.words[0]
    if not head.literal or head.raw != head.text or "/" in head.text:
        return False
    if not all(_redirect_safe(redirect, line, ctx) for redirect in simple.redirects):
        return False
    if ctx.policy.allow and not any(word.expands for word in simple.words):
        if _matching(ctx.policy.allow, [" ".join(word.text for word in simple.words)]):
            return True
    rule = SAFE.get(head.text)
    return rule is not None and rule(simple.words[1:], line, ctx)


def _read_only(simple: Simple) -> bool:
    if not simple.words or any(not (r.reads or r.duplicates or r.target.text in DEVICES) for r in simple.redirects):
        return False
    program = simple.words[0].text
    if program == "git":
        sub = next((word.text for word in simple.words[1:] if not word.text.startswith("-")), "")
        return sub in GIT_READ
    return program in READ_ONLY


def _rewrites_tree(simple: Simple) -> bool:
    """True for a git command that writes files a branch holds, which may include links."""
    words = [word.text for word in simple.words]
    return bool(words) and words[0] == "git" and _git_subcommand(words[1:])[0] in (
        "checkout", "switch", "merge", "worktree", "restore", "reset", "stash", "pull", "rebase", "cherry-pick",
        "revert", "am", "apply", "clone", "read-tree", "checkout-index")


# -- the answer to a tool call ------------------------------------------------------------------


def judge_command(command: str, root: Path, protected: Iterable[str], cwd: Path | None = None, *,
                  keep: Iterable[str] = (), temp: Iterable[str] = ()) -> str | None:
    """Why the owner must approve this shell command, or None when Themis has no objection. `cwd`
    is the folder the command runs in; the root, when not given. Files under `keep` may not be
    deleted, moved or overwritten. With `temp`, a delete whose every literal target lies in one of
    those folders is no objection. A command the 0.2.0 reader cannot read is answered UNREADABLE,
    unless its raw text names a danger."""
    temp = tuple(temp)
    chosen = Policy(mode=SAFE_MODE if temp else "ask", protected=tuple(protected), keep=tuple(keep), temp=temp)
    reading = read_command(command, root, cwd if cwd is not None else root, chosen)
    return reading.danger or (UNREADABLE if reading.unreadable else None)


def _glob(pattern: str) -> re.Pattern[str]:
    """A command pattern, as the host reads `Bash(...)`: `*` stands for any text, and a trailing
    ` *` or `:*` for the words before it alone or followed by anything."""
    tail = pattern.endswith((" *", ":*"))
    body = pattern[:-2] if tail else pattern
    return re.compile(".*".join(re.escape(part) for part in body.split("*")) + (r"(?:\s.*)?" if tail else ""), re.DOTALL)


def _matching(patterns: Iterable[str], texts: list[str]) -> str | None:
    """The first pattern that matches one of the texts in full."""
    return next((pattern for pattern in patterns if any(_glob(pattern).fullmatch(text) for text in texts)), None)


def _settings_files(root: Path) -> list[tuple[Path, str]]:
    found = [(root / SETTINGS, SETTINGS), (root / LOCAL_SETTINGS, LOCAL_SETTINGS)]
    found += [(path, str(path)) for path in _user_settings()]
    found += [(Path(path), path) for path in MANAGED_SETTINGS]
    return found


def host_lists(root: Path) -> dict[str, list[tuple[str, str]]] | None:
    """The host's own ask and deny entries, from the project's settings, the user's and the
    managed ones, each with the file it came from. None when any of them is there and cannot be
    read, holds a list that is not a list of text, or a `Bash(` entry that does not close."""
    found: dict[str, list[tuple[str, str]]] = {"ask": [], "deny": []}
    for path, shown in _settings_files(root):
        if not path.is_file():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        permissions = settings.get("permissions", {}) if isinstance(settings, dict) else None
        if not isinstance(permissions, dict):
            return None
        for kind, entries in found.items():
            listed = permissions.get(kind, [])
            if not isinstance(listed, list) or not all(isinstance(entry, str) for entry in listed):
                return None
            for entry in listed:
                if entry.strip().startswith("Bash") and _bash_pattern(entry) is None:
                    return None
                entries.append((entry, shown))
    return found


def _bash_pattern(entry: str) -> str | None:
    written = re.fullmatch(r"\s*Bash(?:\((.*)\))?\s*", entry, re.DOTALL)
    return None if written is None else (written.group(1) or "*")


def _host_match(lists: dict[str, list[tuple[str, str]]], kind: str, texts: list[str]) -> tuple[str, str] | None:
    """The host's `Bash(...)` entry of this kind that matches the command, and its file."""
    for entry, name in lists[kind]:
        pattern = _bash_pattern(entry) if entry.strip().startswith("Bash") else None
        if pattern is not None and _matching([pattern], texts):
            return entry, name
    return None


def _answer(decision: str, reason: str) -> dict[str, Any]:
    said = f"Themis: {reason}" + (" The owner's approval is needed." if decision == "ask" else "")
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": decision, "permissionDecisionReason": said,
    }}


def _answer_command(command: str, root: Path, cwd: Path, chosen: Policy) -> dict[str, Any] | None:
    allowing = chosen.mode == SAFE_MODE
    reading = read_command(command, root, cwd, chosen)
    denied = _matching(chosen.deny, reading.texts)
    if denied:
        return _answer("deny", f'This command matches "{denied}" under [agents] deny.')
    lists = host_lists(root) if allowing else {"ask": [], "deny": []}
    hosted = _host_match(lists, "deny", reading.texts) if lists else None
    if hosted:
        return _answer("deny", f"This command matches {hosted[0]} in the deny list of {hosted[1]}.")
    if reading.danger:
        return _answer("ask", reading.danger)
    asked = _matching(chosen.ask, reading.texts)
    if asked:
        return _answer("ask", f'This command matches "{asked}" under [agents] ask.')
    if not allowing:
        return _answer("ask", UNREADABLE) if reading.unreadable else None
    if not reading.safe or lists is None:
        return None  # not known to be safe: the host decides
    hosted = _host_match(lists, "ask", reading.texts)
    if hosted:
        return _answer("ask", f"This command matches {hosted[0]} in the ask list of {hosted[1]}.")
    return _answer("allow", 'Every command in this call is on the safe list (pretool = "allow-safe").')


def _answer_edit(path: str, root: Path, cwd: Path, chosen: Policy) -> dict[str, Any] | None:
    home = os.path.realpath(root)
    real = _real(path, cwd)
    name = None if real is None else _within(real, home)
    if name and _touches(name, chosen.protected, root):
        return _answer("ask", f"{name} is a protected file, which only the owner changes.")
    if name and _touches(name, chosen.keep, root):
        return _answer("ask", f"{name} is kept by the project, so only the owner changes it.")
    if real is not None and _guarded(real, chosen.outside):
        return _answer("ask", f"{real} holds the host's own settings or the git hooks, which only the owner changes.")
    if chosen.mode != SAFE_MODE or real is None or not (name or _scratch(real, home, chosen.temp)) or _guarded(real, chosen.outside):
        return None
    lists = host_lists(root)
    if lists is None or any(EDIT_RULE.match(entry) for entries in lists.values() for entry, _ in entries):
        return None  # the host has rules of its own for edits, or settings it cannot read
    return _answer("allow", 'This edit is inside the project, away from protected files (pretool = "allow-safe").')


# -- the three hooks ----------------------------------------------------------------------------


def project_root(given: str | None, project_dir: str | None, cwd: str | None) -> Path:
    """The project a hook judges. The root named with --root, else the host's project folder
    (`$CLAUDE_PROJECT_DIR`), else the nearest folder at or above the shell's folder that holds a
    manifest, else the shell's folder. The shell's folder alone is never trusted: from outside the
    project it would find no manifest, and let a protected edit through."""
    for named in (given, project_dir):
        if named:
            return Path(named).expanduser().resolve()
    start = Path(cwd or ".").expanduser().resolve()
    return next((folder for folder in (start, *start.parents) if (folder / manifests.MANIFEST_FILE).is_file()), start)


def pretool(payload: dict[str, Any], root: Path) -> dict[str, Any] | None:
    """The answer to a tool call: "deny" or "ask" with its reason; in allow-safe, "allow" when every
    command is known safe; else None, to leave the call to the host. The payload's cwd is used only
    to read the call's relative paths. A call the hook fails to judge asks."""
    if not (root / manifests.MANIFEST_FILE).is_file():
        return None
    try:
        tool, given = payload.get("tool_name", ""), payload.get("tool_input", {}) or {}
        cwd = (root / str(payload["cwd"])).resolve() if payload.get("cwd") else root
        chosen = policy(root)
        if tool == "Bash":
            return _answer_command(str(given.get("command", "")), root, cwd, chosen)
        if tool in EDITORS:
            return _answer_edit(str(given.get("file_path") or given.get("notebook_path") or ""), root, cwd, chosen)
        return None
    except Exception as error:  # noqa: BLE001 - a call the hook cannot judge goes to the owner
        return _answer("ask", f"Themis could not judge this call ({error.__class__.__name__}).")


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
    """How a hook starts themis: through uv, held to its lock file, in a uv project."""
    return "uv run --frozen --quiet themis" if (root / "uv.lock").is_file() else "themis"


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


# -- git hooks ----------------------------------------------------------------------------------

GIT_HOOKS = ".githooks"
#: Each git hook, the check it runs, and why.
GIT_EVENTS = {
    "pre-commit": ("check --changed", "the rules, and the external checks whose paths changed, before each commit"),
    "pre-push": ("check", "every rule and every external check, before each push"),
}
#: A line that runs Themis: any command that ends in a word holding `themis` (`themis`, `uv run themis`,
#: `python -m themis.cli`), not a line that only prints the words. What follows it is matched exactly.
_RUNS_THEMIS = r"^\s*(?!(?:exec\s+)?(?:echo|printf|:|true)\b)(?:exec\s+)?(?:\S+\s+)*?\S*\bthemis\b\S*\s+"


def runs_check(text: str, check: str) -> bool:
    """True when a line of the hook, not a comment, runs exactly `<command> <check>`: `check` for
    pre-push, `check --changed` for pre-commit. `check --changed` is not the full check."""
    wanted = re.compile(_RUNS_THEMIS + r"\s+".join(map(re.escape, check.split())) + r"\s*$")
    return any(wanted.match(line) for line in text.splitlines() if not line.lstrip().startswith("#"))


def git_hook(command: str, event: str) -> str:
    check, why = GIT_EVENTS[event]
    return (f"#!/bin/sh\n# Written by `themis hooks install --git`: {why}. Never bypass it with --no-verify.\n"
            f'cd "$(git rev-parse --show-toplevel)" || exit 1\nexec {command} {check}\n')


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def install_git(root: Path, folder: str = GIT_HOOKS, command: str | None = None, *, force: bool = False) -> list[Path]:
    """Write the git hooks into a folder of the repository and point git at it (core.hooksPath).
    A different hook already there is kept, unless `force`: raises ValueError naming it."""
    if _git(root, "rev-parse", "--git-dir").returncode != 0:
        raise ValueError("this folder is not a git repository")
    target = (root / folder).resolve()
    if root.resolve() != target and root.resolve() not in target.parents:
        raise ValueError(f"{folder} is outside the repository")
    wanted = {event: git_hook(command or default_command(root), event) for event in GIT_EVENTS}
    differs = [event for event in GIT_EVENTS
               if (target / event).is_file() and (target / event).read_text(encoding="utf-8") != wanted[event]]
    if differs and not force:
        raise ValueError(f"{folder}/{differs[0]} already holds a different hook; keep it, or run again with --force")
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for event, text in wanted.items():
        path = target / event
        path.write_text(text, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written.append(path)
    done = _git(root, "config", "core.hooksPath", target.relative_to(root.resolve()).as_posix() or ".")
    if done.returncode != 0:
        raise ValueError(f"git did not take core.hooksPath: {done.stderr.strip()}")
    return written


def git_missing(root: Path, folder: str) -> list[tuple[str, str]]:
    """What keeps the declared git hooks from running Themis, as (what, where) pairs."""
    found = []
    target = (root / folder).resolve()
    said = _git(root, "config", "--get", "core.hooksPath").stdout.strip()
    if not said or (root / said).resolve() != target:
        found.append((f"git does not run the hooks in {folder}: core.hooksPath is {said or 'not set'}", folder))
    for event, (check, _) in GIT_EVENTS.items():
        path, where = target / event, f"{folder.strip('/')}/{event}"
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            found.append((f"the {event} git hook is not installed", where))
            continue
        if not os.access(path, os.X_OK):
            found.append((f"the {event} git hook is not executable, so git skips it", where))
        if not runs_check(text, check):
            found.append((f"the {event} git hook does not run `themis {check}`", where))
    return found
