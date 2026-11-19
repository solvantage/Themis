"""Agent hooks: guardrails that run outside the prompt.

Three hooks, installed into the agent host's settings file:

    before a tool call   stop a delete, work thrown away, a remote command, a forced push,
                         `themis grant`, the owner's own `themis decide` and `themis attest`, and
                         any write to a protected or kept file, and ask the owner
    session start        remember which breaches already exist, so old ones do not block new work
    end of turn          run `themis check` on the changed work; a new breach keeps the turn open

The before-a-tool-call hook has two modes, `pretool` under [agents]. In "ask", the default, it asks
for what is dangerous and says nothing about the rest, so the host's own prompts decide it. In
"allow-unless" it answers allow when nothing needs the owner: no danger, no match among the
project's `ask` and `deny` patterns, and none in the host's own ask and deny lists. A delete whose
every target lies in a temp folder, outside the project, is then no danger. In both modes a `cd`
inside a command moves where its relative paths are read from, and a deny pattern answers deny.

The end-of-turn hook follows six rules. It is silent in a folder with no manifest. It checks only
this project. A blocking exit always carries a reason. Breaches that existed when the session
began are warnings, not blocks. It blocks at most three times in one turn. It never installs
anything and never reports a pass it did not establish.
"""

from __future__ import annotations

import io
import itertools
import json
import os
import re
import shlex
import stat
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from themis import configguard, engine, paths, reporters
from themis import manifest as manifests
from themis.gitlog import Git
from themis.verdict import Verdict

SETTINGS = ".claude/settings.json"
LOCAL_SETTINGS = ".claude/settings.local.json"
MAX_BLOCKS = 3
STATE = ".themis/hook-state.json"
MARK = "themis hook"
OWNER = "owner"  # the judge whose rows only the owner ticks

#: Where scratch work lives. In allow-unless, a delete whose every target is inside one of these,
#: and outside the project, needs no owner.
TEMP = manifests.TEMP_FOLDERS
UNREADABLE = "Themis cannot read this command, so it cannot say it is safe."

DELETERS = {"rm", "rmdir", "unlink", "shred"}
REMOTES = {"ssh", "scp", "sftp"}
WRAPPERS = {"sudo", "command", "time", "nohup", "exec", "env", "xargs", "nice", "builtin"}
SHELLS = {"sh", "bash", "zsh", "dash"}
WRITERS = {"tee", "mv", "cp", "install", "truncate", "touch", "ln", "dd"}
COPIERS = {"cp", "ln", "install"}  # writers that change only where they write to, never what they read
IN_PLACE = {"sed", "perl"}
KEYWORDS = {"if", "then", "else", "elif", "while", "until", "do", "!", "{", "}"}  # stepped over to the program
LOOPS = {"for", "while", "until", "select", "if", "case", "function"}  # their bodies read variables
OPERATORS = {";", "&&", "||", "|", "&", "(", ")", "\n", "|&", ";;"}
SEPARATORS = set(";&|()\n")
GIT_VALUED = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env", "--attr-source"}
EDITORS = ("Write", "Edit", "NotebookEdit", "MultiEdit")
EDIT_RULE = re.compile(r"(?:Edit|Write|MultiEdit|NotebookEdit)(?:\(|\Z)")

#: What hides part of a command from the word-by-word reading: a substitution, a here-document.
OPAQUE = re.compile(r"\$\(|`|<\(|>\(|<<")
#: The dangers looked for in the raw text of a command Themis cannot read in full: (pattern, what).
DANGER_TEXT = (
    (re.compile(r"(?<![\w.-])(?:rm|rmdir|unlink|shred)(?![\w.-])"), "a delete"),
    (re.compile(r"\bfind\b[^\n;&|]*?\s-delete\b|\bworktree\s+remove\b"), "a delete"),
    (re.compile(r"\bgit\b[^\n;&|]*?\s(?:clean|restore)\b|\breset\s+--hard\b|\bstash\s+(?:drop|clear)\b"),
     "work thrown away"),
    (re.compile(r"\bcheckout\b[^\n;&|]*?\s--(?=\s)"), "work thrown away"),
    (re.compile(r"\bbranch\s+(?:-[a-zA-Z]*[dD]\b|--delete\b)"), "a branch delete"),
    (re.compile(r"\bpush\b[^\n;&|]*?\s(?:--delete|--mirror|--force\S*|-[df])(?![\w-])|\bpush\b[^\n;&|]*?\s[:+]\w"),
     "a push that deletes or overwrites"),
    (re.compile(r"(?<![\w.-])(?:ssh|scp|sftp)(?![\w.-])"), "a remote machine"),
    (re.compile(r"\bthemis\b[^\n;&|]*?\sgrant\b|--by[= ]owner\b|--judge[= ]owner\b"), "a command only the owner runs"),
)
#: In that raw text, what writes, moves or deletes; a protected or kept path beside it asks.
WRITE_TEXT = re.compile(r">|(?<![\w.-])(?:tee|mv|cp|install|truncate|touch|ln|dd|sed|perl|rm|unlink|shred)(?![\w.-])")


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


def policy(root: Path) -> Policy:
    """The project's policy. A manifest that is missing or not valid gives the defaults, so a
    broken manifest never loosens the hook."""
    manifest = manifests.load(root)
    if not manifest.present or manifest.problems:
        return Policy()
    agents = manifest.table("agents")
    mode = agents.get("pretool", "ask")
    # In allow-unless the host's local settings hold ask and deny lists the hook obeys: guard them too.
    local = (LOCAL_SETTINGS,) if mode == "allow-unless" else ()
    return Policy(
        mode=mode,
        protected=(*configguard.protected_paths(manifest), *local),
        temp=tuple(agents.get("temp", TEMP)),
        keep=tuple(agents.get("keep", ())),
        ask=tuple(agents.get("ask", ())),
        deny=tuple(agents.get("deny", ())),
    )


#: What each mode does, as `themis doctor` and `themis hooks install` say it.
MODE_SAYS = {
    "ask": "asks the owner before a delete, work thrown away, a remote command, an owner-only command or a "
           "write to a protected or kept file, and leaves every other call to the host's own prompts",
    "allow-unless": "answers allow unless a call deletes outside a temp folder, throws work away, reaches a "
                    "remote machine, runs an owner-only command, writes to a protected or kept file, or "
                    "matches an ask or deny pattern of the project or of the host",
}


def mode_line(root: Path) -> str:
    """The mode, and what it does, in one sentence."""
    chosen = policy(root).mode
    return f'pretool = "{chosen}": before a tool call the hook {MODE_SAYS[chosen]}.'


# -- reading a shell command --------------------------------------------------------------------


class _Lines(io.StringIO):
    """A command's text for the lexer. A comment ends at its newline, and that newline still parts
    the commands on either side of it, as it does in the shell."""

    def readline(self, size: int | None = -1, /) -> str:
        line = super().readline(size)
        if not line.endswith("\n"):
            return line
        self.seek(self.tell() - 1)
        return line[:-1]


def _pieces(command: str) -> list[str | list[str]] | None:
    """The command as its simple commands, each a list of words, with the operators between them
    as text. A newline parts commands as `;` does. None when the command cannot be read."""
    lexer = shlex.shlex(_Lines(command), posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    found: list[str | list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in OPERATORS or (token and set(token) <= SEPARATORS):
            if current:
                found.append(current)
            current = []
            found.append(token)
        else:
            current.append(token)
    if current:
        found.append(current)
    return found


def _simple_commands(command: str) -> list[list[str]] | None:
    """The command split into simple commands, each a list of words. None when it cannot be read."""
    pieces = _pieces(command)
    return None if pieces is None else [piece for piece in pieces if isinstance(piece, list)]


def _start(words: list[str]) -> int:
    """Where the program of a simple command stands, past assignments, wrappers and keywords."""
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
        elif word in KEYWORDS:
            index += 1
        else:
            return index
    return index


def _program(words: list[str]) -> tuple[str, list[str]]:
    """The program a simple command runs, past any assignments and wrappers, and its arguments."""
    index = _start(words)
    if index >= len(words):
        return "", []
    return os.path.basename(words[index].lstrip("`$")), words[index + 1:]


def _git_subcommand(args: list[str]) -> tuple[str, list[str]]:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in GIT_VALUED else 1
    return (args[index], args[index + 1:]) if index < len(args) else ("", [])


def _git_folder(args: list[str], cwd: Path | None) -> Path | None:
    """The folder a git command works in: where it runs, moved by each `-C`."""
    folder, index = cwd, 0
    while index < len(args) and args[index].startswith("-"):
        if args[index] == "-C" and index + 1 < len(args):
            folder = _place(args[index + 1], folder)
        step = 2 if args[index] in GIT_VALUED else 1
        index += step
    return folder


def _operands(args: list[str]) -> list[str]:
    """The arguments that are not options; after `--`, all of them."""
    found, ended = [], False
    for arg in args:
        if arg == "--" and not ended:
            ended = True
        elif ended or not arg.startswith("-"):
            found.append(arg)
    return found


def _after_themis(words: list[str]) -> str | None:
    """The first word after `themis`, when this command runs themis however it is launched."""
    for index, word in enumerate(words):
        if os.path.basename(word.lstrip("`$")) == "themis" or (word == "themis" and index and words[index - 1] == "-m"):
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


# -- where a word points ------------------------------------------------------------------------


def _relative(word: str, root: Path, cwd: Path | None = None) -> str | None:
    """A word as a repository path, or None when it is not inside the repository. A relative word
    is read from the folder the command runs in, which is the root unless the host says otherwise."""
    if not word or word.startswith("-"):
        return None
    candidate = Path(word).expanduser()
    absolute = candidate if candidate.is_absolute() else (cwd or root) / candidate
    try:
        return absolute.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _named(word: str, root: Path, cwd: Path | None) -> str | None:
    """A command's word as a repository path. Where the folder cannot be known, a relative word is
    read from the root: the stricter reading for a protected or kept path."""
    return _relative(word, root, cwd if cwd is not None else root)


def _place(word: str, cwd: Path | None) -> Path | None:
    """The absolute path a word names, or None when only the shell could say: a variable that is
    not set here, a substitution, or a relative word in a folder that cannot be known."""
    if not word or word.startswith("-"):
        return None
    text = os.path.expanduser(os.path.expandvars(word))
    if "$" in text or "`" in text:
        return None
    path = Path(text)
    if not path.is_absolute():
        if cwd is None:
            return None
        path = cwd / path
    return Path(os.path.normpath(path))


def _temp_bases(temp: Iterable[str]) -> list[tuple[str, str]]:
    """Each temp pattern as (the folder it starts at, the pattern below it), once as written and
    once with the folder's links followed, since `/tmp` is a link on some systems."""
    found = []
    for pattern in temp:
        text = os.path.expanduser(os.path.expandvars(pattern))
        if "$" in text or not text.startswith("/"):
            continue  # a variable that is not set names no folder
        parts = text.split("/")
        cut = next((index for index, part in enumerate(parts) if any(char in part for char in "*?[")), len(parts))
        head, rest = "/".join(parts[:cut]) or "/", "/".join(part for part in parts[cut:] if part)
        for base in {os.path.normpath(head), str(Path(head).resolve())}:
            found.append((base.rstrip("/"), rest or "**"))
    return found


def _scratch(place: Path | None, root: Path, temp: Iterable[str]) -> bool:
    """True when a path lies inside a temp folder, past every link, and neither inside the project
    nor above it."""
    if place is None:
        return False
    try:
        real, home = place.resolve(), root.resolve()
    except OSError:
        return False
    if real == home or home in real.parents or real in home.parents:
        return False
    text = real.as_posix()
    return any(text.startswith(base + "/") and paths.matches(text[len(base) + 1:], rest)
               for base, rest in _temp_bases(temp))


def _moved(program: str, args: list[str], cwd: Path | None, pushed: list[Path | None], *, sure: bool) -> Path | None:
    """The folder after a `cd`, `pushd` or `popd`; None when it cannot be known. `sure` is False
    when what follows runs whether or not the move worked; then a folder not there now is unknown."""
    if program == "popd":
        return pushed.pop() if pushed else None
    if program == "pushd":
        pushed.append(cwd)
    operands = [arg for arg in args if arg == "-" or not arg.startswith("-")]
    if not operands:
        target = _place("~", cwd) if program == "cd" else None
    else:
        target = None if operands[0] == "-" else _place(operands[0], cwd)
    if target is not None and not sure and not target.is_dir():
        return None
    return target


def _piped(operator: str) -> bool:
    """True when the command beside this operator runs in a shell of its own: a pipe, or `&`."""
    return operator.strip("()\n") in ("|", "|&", "&")


# -- judging a shell command --------------------------------------------------------------------


def judge_command(command: str, root: Path, protected: Iterable[str], cwd: Path | None = None, *,
                  keep: Iterable[str] = (), temp: Iterable[str] = ()) -> str | None:
    """Why the owner must approve this shell command, or None when Themis has no objection. `cwd`
    is the folder the command runs in, for its relative paths; the root, when not given. A `cd`
    inside the command moves it. Files under `keep` may not be deleted, moved or overwritten. A
    delete whose every target lies inside a `temp` folder, outside the project, is no objection.
    A command that cannot be read is answered UNREADABLE, unless its raw text names a danger."""
    return _judge_text(command, root, list(protected), list(keep), list(temp), cwd if cwd is not None else root)


def _judge_text(command: str, root: Path, protected: list[str], keep: list[str], temp: list[str],
                cwd: Path | None) -> str | None:
    text = command.replace("\\\n", " ")
    pieces = _pieces(text)
    if pieces is None:
        return _scan(text, protected, keep) or UNREADABLE
    reason = _judge_pieces(pieces, root, protected, keep, temp, cwd)
    if reason is None and (OPAQUE.search(text) or any(isinstance(piece, list) and piece[0] in LOOPS for piece in pieces)):
        reason = _scan(text, protected, keep)
    return reason


def _judge_pieces(pieces: list[str | list[str]], root: Path, protected: list[str], keep: list[str],
                  temp: list[str], cwd: Path | None) -> str | None:
    """Each simple command in turn, from the folder the commands before it moved to."""
    saved: list[Path | None] = []  # the folder at each open parenthesis: a subshell's `cd` ends with it
    pushed: list[Path | None] = []  # what pushd remembers
    for index, piece in enumerate(pieces):
        if isinstance(piece, str):
            for char in piece:
                if char == "(":
                    saved.append(cwd)
                elif char == ")" and saved:
                    cwd = saved.pop()
            continue
        before = pieces[index - 1] if index and isinstance(pieces[index - 1], str) else ""
        after = pieces[index + 1] if index + 1 < len(pieces) and isinstance(pieces[index + 1], str) else ""
        program, args = _program(piece)
        if program in ("cd", "pushd", "popd"):
            if not (_piped(str(before)) or _piped(str(after))):
                cwd = _moved(program, args, cwd, pushed, sure=str(after).strip("()\n") == "&&")
            continue
        reason = _judge_simple(piece, program, args, root, protected, keep, temp, cwd)
        if reason:
            return reason
    return None


def _deleting(targets: list[str], root: Path, keep: list[str], temp: list[str], cwd: Path | None,
              what: str = "This command deletes files.") -> str | None:
    """Why a delete of these targets needs the owner, or None when every one is scratch."""
    for target in targets:
        name = _named(target, root, cwd)
        if name and paths.matches_any(name, keep):
            return f"This command deletes {name}, which the project keeps."
    return _gone([_place(target, cwd) for target in targets], root, temp, what)


def _gone(places: list[Path | None], root: Path, temp: list[str], what: str) -> str | None:
    """`what`, unless there are places and every one of them is scratch. No place known asks."""
    return None if places and all(_scratch(place, root, temp) for place in places) else what


def _git_local(sub: str, rest: list[str], flags: list[str]) -> str | None:
    """What a git command deletes or throws away in its own repository, or None."""
    if sub in ("rm", "clean"):
        return "This command deletes files."
    if sub == "branch" and any(flag == "--delete" or (not flag.startswith("--") and "d" in flag.lower()) for flag in flags):
        return "This command deletes a branch."
    if (sub == "reset" and "--hard" in flags) or (sub == "stash" and rest[:1] in (["drop"], ["clear"])):
        return "This command throws away work."
    if sub in ("checkout", "switch") and any(flag in ("-f", "--force", "--discard-changes") for flag in flags):
        return "This command throws away work."
    if sub == "checkout" and ("." in rest or ("--" in rest and rest.index("--") + 1 < len(rest))):
        return "This command throws away work."
    if sub == "restore":
        short = [flag for flag in flags if not flag.startswith("--")]
        staged = "--staged" in flags or any("S" in flag for flag in short)
        worktree = "--worktree" in flags or any("W" in flag for flag in short)
        if worktree or not staged:
            return "This command throws away work."
    return None


def _written(program: str, args: list[str], cwd: Path | None) -> list[str]:
    """What a writer changes: a copier only what it writes to, into a folder under each source's
    name; any other writer every argument."""
    if program not in COPIERS:
        return list(args)
    operands = _operands(args)
    folder = _flag(args, "-t") or _flag(args, "--target-directory")
    if folder is None and operands:
        place = _place(operands[-1], cwd)
        if len(operands) == 1 or not (operands[-1].endswith("/") or (place is not None and place.is_dir())):
            return operands[-1:]
        folder = operands[-1]
    sources = [operand for operand in operands if operand != folder]
    return [os.path.join(folder, os.path.basename(source.rstrip("/"))) for source in sources] or ([folder] if folder else [])


def _judge_simple(words: list[str], program: str, args: list[str], root: Path, protected: list[str],
                  keep: list[str], temp: list[str], cwd: Path | None) -> str | None:
    if program in SHELLS and "-c" in args and args.index("-c") + 1 < len(args):
        inner = _judge_text(args[args.index("-c") + 1], root, protected, keep, temp, cwd)
        if inner:
            return inner
    if program == "eval":
        inner = _judge_text(" ".join(args), root, protected, keep, temp, cwd)
        if inner:
            return inner
    # Behind a wrapper such as sudo or xargs, the real program is somewhere among the words.
    names = {os.path.basename(word.lstrip("`$")) for word in words}
    behind = names if names & WRAPPERS else set()
    if program in DELETERS or behind & DELETERS:
        # What a wrapper such as xargs deletes is not on the line, so it always asks.
        reason = _deleting(_operands(args) if program in DELETERS else [], root, keep, temp, cwd)
        if reason:
            return reason
    if program in REMOTES or behind & REMOTES:
        return "This command reaches a remote machine."
    if program == "find" and ("-delete" in args or any(os.path.basename(a) in DELETERS for a in args)):
        starts = list(itertools.takewhile(lambda arg: not arg.startswith(("-", "(", "!")), args)) or ["."]
        reason = _deleting(starts, root, keep, temp, cwd)
        if reason:
            return reason
    moved: list[str] = []
    if program == "git":
        sub, rest = _git_subcommand(args)
        flags = [word for word in rest if word.startswith("-")]
        if sub == "worktree" and rest[:1] == ["remove"]:
            reason = _gone([_place(target, _git_folder(args, cwd)) for target in _operands(rest[1:])], root, temp,
                           "This command deletes files.")
            if reason:
                return reason
        local = _git_local(sub, rest, flags)
        if local:
            reason = _gone([_git_folder(args, cwd)], root, temp, local)
            if reason:
                return reason
        if sub == "push" and (
            any(flag in ("--delete", "-d", "--force", "-f", "--mirror") or flag.startswith("--force-with-lease") for flag in flags)
            or any(word.startswith((":", "+")) for word in rest if not word.startswith("-"))
        ):
            return "This command deletes or overwrites something on the remote."
        if sub == "mv":
            moved = _operands(rest)
    if _after_themis(words) == "grant":
        return "Only the owner gives a grant."
    if _after_themis(words) == "decide" and ("--by=owner" in words or "owner" in words[words.index("--by") + 1:][:1]
                                             if "--by" in words else "--by=owner" in words):
        return "Only the owner overrules a gate."
    if _after_themis(words) == "attest" and _flag(words, "--judge") == OWNER:
        return "Only the owner attests as the owner."
    redirected = [words[index + 1] for index, word in enumerate(words[:-1]) if word in (">", ">>", ">|")]
    targets, kept = redirected + moved, redirected + moved
    if program in WRITERS or (program in IN_PLACE and any(arg.startswith("-i") for arg in args)):
        targets += args
        kept += _written(program, args, cwd)
    for target in targets:
        name = _named(target, root, cwd)
        if name and paths.matches_any(name, protected):
            return f"This command writes to {name}, which only the owner changes."
    for target in kept:
        name = _named(target, root, cwd)
        if name and paths.matches_any(name, keep):
            return f"This command writes to or moves {name}, which the project keeps."
    return None


def _literal(pattern: str) -> str:
    """The longest stretch of a path pattern without a wildcard, to look for in raw text."""
    longest = max(re.split(r"[*?\[\]]", pattern), key=len).lstrip("/")
    return longest if len(longest.strip("/")) >= 3 else ""


def _scan(text: str, protected: list[str], keep: list[str]) -> str | None:
    """Why the raw text of a command Themis cannot read in full needs the owner: it names a danger,
    or it writes and names a protected or kept path. None when it names neither."""
    for pattern, what in DANGER_TEXT:
        found = pattern.search(text)
        if found:
            return f"Themis cannot read all of this command, and its text names {what}: `{found.group(0).strip()}`."
    if WRITE_TEXT.search(text):
        for patterns, whose in ((protected, "which only the owner changes"), (keep, "which the project keeps")):
            for pattern in patterns:
                literal = _literal(pattern)
                if literal and literal in text:
                    return f"Themis cannot read all of this command, and it writes beside {pattern}, {whose}."
    return None


# -- the answer to a tool call ------------------------------------------------------------------


def _texts(command: str) -> list[str]:
    """What a command pattern is matched against: the whole command and each of its lines, and
    each simple command, as written and from its program on."""
    found = [command.strip(), *(line.strip() for line in command.splitlines())]
    for words in _simple_commands(command.replace("\\\n", " ")) or []:
        start = _start(words)
        found += [" ".join(words), " ".join(words[start:])]
        if start < len(words) and words[start].startswith("./"):
            found.append(" ".join([words[start][2:], *words[start + 1:]]))
    return [text for text in found if text]


def _glob(pattern: str) -> re.Pattern[str]:
    """A command pattern: `*` stands for any text. One that ends in `:*`, as the host writes them,
    matches its words alone or followed by anything."""
    prefix = pattern.endswith(":*")
    body = pattern[:-2] if prefix else pattern
    return re.compile(".*".join(re.escape(part) for part in body.split("*")) + (r"(?:\s.*)?" if prefix else ""), re.DOTALL)


def _matching(patterns: Iterable[str], texts: list[str]) -> str | None:
    """The first pattern that matches one of the texts in full."""
    return next((pattern for pattern in patterns if any(_glob(pattern).fullmatch(text) for text in texts)), None)


def host_lists(root: Path) -> dict[str, list[tuple[str, str]]] | None:
    """The host's own ask and deny entries from the project's two settings files, each with the
    file it came from. None when a settings file is there and cannot be read."""
    found: dict[str, list[tuple[str, str]]] = {"ask": [], "deny": []}
    for name in (SETTINGS, LOCAL_SETTINGS):
        path = root / name
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
            entries += [(entry, name) for entry in (listed if isinstance(listed, list) else []) if isinstance(entry, str)]
    return found


def _host_match(lists: dict[str, list[tuple[str, str]]], kind: str, texts: list[str]) -> tuple[str, str] | None:
    """The host's `Bash(...)` entry of this kind that matches the command, and its file."""
    for entry, name in lists[kind]:
        written = re.fullmatch(r"Bash(?:\((.*)\))?", entry.strip(), re.DOTALL)
        if written and _matching([written.group(1) or "*"], texts):
            return entry, name
    return None


def _answer(decision: str, reason: str) -> dict[str, Any]:
    said = f"Themis: {reason}" + (" The owner's approval is needed." if decision == "ask" else "")
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": decision, "permissionDecisionReason": said,
    }}


def _answer_command(command: str, root: Path, cwd: Path, chosen: Policy) -> dict[str, Any] | None:
    allowing = chosen.mode == "allow-unless"
    reason = judge_command(command, root, chosen.protected, cwd, keep=chosen.keep, temp=chosen.temp if allowing else ())
    if allowing and reason == UNREADABLE:
        reason = None  # its raw text named no danger
    texts = _texts(command)
    denied = _matching(chosen.deny, texts)
    if denied:
        return _answer("deny", f'This command matches "{denied}" under [agents] deny.')
    lists = host_lists(root) if allowing else {"ask": [], "deny": []}
    hosted = _host_match(lists, "deny", texts) if lists else None
    if hosted:
        return _answer("deny", f"This command matches {hosted[0]} in the deny list of {hosted[1]}.")
    if reason:
        return _answer("ask", reason)
    asked = _matching(chosen.ask, texts)
    if asked:
        return _answer("ask", f'This command matches "{asked}" under [agents] ask.')
    if not allowing or lists is None:
        return None  # the host decides; Themis never allows past lists it cannot read
    hosted = _host_match(lists, "ask", texts)
    if hosted:
        return _answer("ask", f"This command matches {hosted[0]} in the ask list of {hosted[1]}.")
    return _answer("allow", 'Nothing in this command needs the owner (pretool = "allow-unless").')


def _answer_edit(path: str, root: Path, cwd: Path, chosen: Policy) -> dict[str, Any] | None:
    name = _relative(path, root, cwd)
    if name and paths.matches_any(name, chosen.protected):
        return _answer("ask", f"{name} is a protected file, which only the owner changes.")
    if name and paths.matches_any(name, chosen.keep):
        return _answer("ask", f"{name} is kept by the project, so only the owner changes it.")
    if chosen.mode != "allow-unless":
        return None
    lists = host_lists(root)
    if lists is None or any(EDIT_RULE.match(entry.strip()) for entries in lists.values() for entry, _ in entries):
        return None  # the host has rules of its own for edits, and applies them itself
    return _answer("allow", 'Nothing in this edit needs the owner (pretool = "allow-unless").')


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
    """The answer to a tool call: "deny" or "ask" with its reason; in allow-unless, "allow" when
    nothing needs the owner; else None, to leave the call to the host. The payload's cwd is used
    only to read the call's relative paths."""
    if not (root / manifests.MANIFEST_FILE).is_file():
        return None
    tool, given = payload.get("tool_name", ""), payload.get("tool_input", {}) or {}
    cwd = (root / str(payload["cwd"])).resolve() if payload.get("cwd") else root
    chosen = policy(root)
    if tool == "Bash":
        return _answer_command(str(given.get("command", "")), root, cwd, chosen)
    if tool in EDITORS:
        return _answer_edit(str(given.get("file_path") or given.get("notebook_path") or ""), root, cwd, chosen)
    return None


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
