"""The checkpoint: the file a working session leaves for the next one.

A checkpoint opens with a headline of four lines. The first two are facts, and a tool writes them:
when the file was written, which commit the main line was at, and what the suite's receipt says.
The last two are judgment, and the agent writes them: what changed, and what comes next. Below the
headline sit dated entries of a few bullets each, then the standing traps and the closed decisions,
each pointing at its home record.

This module reads that shape for the handoff gate, and writes the facts for `themis checkpoint`.
"""

from __future__ import annotations

import datetime as dt
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from themis import receipts
from themis.gitlog import Git

if TYPE_CHECKING:
    from themis.manifest import Manifest

DEFAULT_HOME = "CHECKPOINT.md"
TITLE = "# Checkpoint — where we left off"
SECTIONS = ("Recently shipped", "Standing traps", "Do not re-propose")
UPDATED, SUITE, CHANGED, NEXT = "**Last updated:**", "**Suite:**", "**Changed:**", "**Next:**"
PLACEHOLDER = "(write one line)"
NO_RECEIPT = f"{SUITE} unverified — no receipt for this tree."
COUNTS = ("passed", "skipped", "failed", "errors")

_NAMED = re.compile(r"`(?P<main>[^`\s]+)` at `(?P<commit>[0-9a-fA-F]{7,40})`")
_TAG = re.compile(r"<!--\s*r:suite/(?P<name>[A-Za-z0-9._+-]+)\s*-->")
_COMMENT = re.compile(r"<!--.*?-->")
_NUMBER = r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)"  # 1204 or 1,204, never the tail of another number
_PASSED = re.compile(_NUMBER + r"\s*pass", re.IGNORECASE)
_SKIPPED = re.compile(_NUMBER + r"\s*skip", re.IGNORECASE)
_UNVERIFIED = re.compile(r"\bunverified\b", re.IGNORECASE)
_DATED = re.compile(r"\s*\*\*(\d{4}-\d{2}-\d{2})")
_HEADING = re.compile(r"(#{1,6})\s+(.*?)[\s#]*$")
_BULLET = re.compile(r"[-*+]\s+(?![-*_\s]*$)")  # a list item, not a rule drawn as `- - -`
_FENCE = ("```", "~~~")
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(\s*(?:<([^>]*)>|([^)\s]+))")  # [text](target) or [text](<a target>)
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_PULL_REQUEST = re.compile(r"\(#(\d+)\)\s*$|^Merge pull request #(\d+)")


@dataclass(frozen=True)
class Entry:
    """A dated entry: the line that begins `**YYYY-MM-DD`, and how many bullets follow it."""

    date: str
    line: int
    bullets: int


@dataclass(frozen=True)
class Bullet:
    """One list item under a heading, with the lines that continue it joined on."""

    text: str
    line: int


@dataclass(frozen=True)
class Checkpoint:
    """What a checkpoint holds. Line numbers count from 1."""

    lines: int = 0  # how long the file is
    headline: tuple[str, ...] = ()  # the run of non-blank lines that starts at **Last updated:**
    headline_line: int | None = None
    main: str | None = None  # the main line's name, as the headline writes it
    commit: str | None = None  # the commit the headline names
    suite: str | None = None  # the **Suite:** line of the headline
    suite_line: int | None = None
    receipt: str | None = None  # NAME, when the suite line carries <!--r:suite/NAME-->
    passed: int | None = None
    skipped: int | None = None
    unverified: bool = False  # True when the suite line says so itself
    entries: tuple[Entry, ...] = ()
    #: heading text -> the bullets under it, those under its deeper headings included
    sections: dict[str, tuple[Bullet, ...]] = field(default_factory=dict)

    def section(self, name: str) -> tuple[Bullet, ...]:
        """The bullets under every heading with this text, whatever its case. Empty when there is none."""
        wanted = name.strip().casefold()
        return tuple(bullet for heading, found in self.sections.items() if heading.casefold() == wanted
                     for bullet in found)


def _number(pattern: re.Pattern[str], text: str) -> int | None:
    found = pattern.search(text)
    return int(found[1].replace(",", "")) if found else None


def _plain(lines: list[str]) -> list[str]:
    """The lines, with every fenced code block blanked: an example is not part of the shape."""
    out, fenced = [], False
    for line in lines:
        fence = line.lstrip().startswith(_FENCE)
        out.append("" if fenced or fence else line)
        fenced = fenced != fence
    return out


def parse(text: str) -> Checkpoint:
    """Read a checkpoint's shape. Nothing here judges it: a missing part is simply None or empty."""
    lines = _plain(text.splitlines())
    found: dict[str, Any] = {"lines": len(lines)}
    start = next((index for index, line in enumerate(lines) if line.lstrip().startswith(UPDATED)), None)
    if start is not None:
        run = lines[start:]
        run = run[:next((index for index, line in enumerate(run) if not line.strip()), len(run))]
        found.update(headline=tuple(run), headline_line=start + 1)
        named = _NAMED.search(" ".join(run))
        if named:
            found.update(main=named["main"], commit=named["commit"])
        at = next((index for index, line in enumerate(run) if line.lstrip().startswith(SUITE)), None)
        if at is not None:
            tag, shown = _TAG.search(run[at]), _COMMENT.sub("", run[at])
            found.update(suite=run[at], suite_line=start + at + 1, receipt=tag["name"] if tag else None,
                         passed=_number(_PASSED, shown), skipped=_number(_SKIPPED, shown),
                         unverified=bool(_UNVERIFIED.search(shown)))

    entries: list[list[Any]] = []
    sections: dict[str, list[list[Any]]] = {}
    under: list[tuple[int, list[list[Any]]]] = []  # the headings a line sits under, the outermost first
    entry = bullet = None
    for number, line in enumerate(lines, start=1):
        heading, dated = _HEADING.match(line), _DATED.match(line)
        if heading:  # it closes every heading of its own depth or deeper, and opens its own
            entry = bullet = None
            under = [(depth, held) for depth, held in under if depth < len(heading[1])]
            under.append((len(heading[1]), sections.setdefault(heading[2], [])))
        elif dated:
            bullet, entry = None, [dated[1], number, 0]
            entries.append(entry)
        elif _BULLET.match(line):
            bullet = [line[1:].strip(), number]
            if entry is not None:
                entry[2] += 1
            for _, held in under:
                if bullet not in held[-1:]:  # two open headings may share one name, and so one list
                    held.append(bullet)
        elif not line.strip():
            bullet = None
        elif bullet is not None:
            bullet[0] += " " + line.strip()  # a bullet that runs on to the next line
    return Checkpoint(
        entries=tuple(Entry(*entry) for entry in entries),
        sections={name: tuple(Bullet(*bullet) for bullet in bullets) for name, bullets in sections.items()},
        **found,
    )


def links(text: str) -> list[str]:
    """The targets of the markdown links in a piece of text. A picture is not a link."""
    return [bracketed or plain for bracketed, plain in _LINK.findall(text)]


def target_path(link: str, folder: str = "") -> str | None:
    """The repository path a relative link points at, read from the folder of the page that holds it.

    None for a web address, a link inside the same page, an absolute path, or a path that leaves
    the repository: none of those is a file a rule can look for.
    """
    target = unquote(link.split("#", 1)[0])
    if not target or target.startswith("/") or _SCHEME.match(target):
        return None
    path = posixpath.normpath(posixpath.join(folder, target))
    return None if path in (".", "..") or path.startswith("../") else path


def home(manifest: Manifest) -> str:
    """Where this project keeps its checkpoint: `[homes] checkpoint`, else CHECKPOINT.md."""
    return manifest.homes.get("checkpoint") or DEFAULT_HOME


def receipt_name(receipt: dict[str, Any]) -> str:
    """The name a tag cites a receipt by: its file's name, without the `.json`."""
    return str(receipt.get("_path", "")).rsplit("/", 1)[-1].removesuffix(".json")


def receipt_named(root: Path, name: str) -> dict[str, Any] | None:
    """The suite receipt a tag cites, or None. The committed copy comes first: the next reader has that one."""
    found = [receipt for receipt in receipts.read_all(Path(root), "suite") if receipt_name(receipt) == name]
    return max(found, key=lambda receipt: receipt["_path"].startswith(receipts.COMMITTED + "/"), default=None)


def counts(receipt: dict[str, Any]) -> dict[str, int] | None:
    """A suite receipt's four counts, or None when one is missing or is not a whole number."""
    found = {key: receipt.get(key) for key in COUNTS}
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in found.values()):
        return None
    return found


def facts(root: Path, manifest: Manifest, *, now: dt.datetime | None = None) -> dict[str, Any]:
    """What a tool can state without judgment.

    `utc` and `local` are the time, as `YYYY-MM-DD HH:MM`. `main` is the main line's name, `commit`
    its short commit, `tree` that commit's tree, and `pull_request` the number its message names.
    `suite` is the newest suite receipt taken on that tree, as it was read, or None. On a clean
    checkout of the main line that tree is the current tree. Anywhere else a receipt for the
    current tree would not be a receipt for the commit the headline names, so it is not offered.
    """
    root, git = Path(root), Git(Path(root))
    moment = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    main = git.main_ref(manifest.project.get("main"))
    commit = tree = number = None
    if main:
        commit = (git.run("rev-parse", "--short=8", f"{main}^{{commit}}") or "").strip() or None
        tree = (git.run("rev-parse", "--verify", "--quiet", f"{main}^{{tree}}") or "").strip() or None
        named = _PULL_REQUEST.search((git.run("show", "-s", "--format=%s", main) or "").strip())
        number = int(named[1] or named[2]) if named else None
    receipt = receipts.suite_for_tree(root, tree) if tree else None
    return {
        "utc": moment.strftime("%Y-%m-%d %H:%M"),
        "local": moment.astimezone().strftime("%Y-%m-%d %H:%M"),
        "main": main,
        "commit": commit,
        "tree": tree,
        "pull_request": number,
        "suite": receipt if receipt and counts(receipt) else None,
    }


def _one_line(text: str | None) -> str:
    return " ".join((text or "").split()) or PLACEHOLDER


def _suite_line(receipt: dict[str, Any] | None) -> str:
    found = counts(receipt) if receipt else None
    if found is None:
        return NO_RECEIPT
    said = f"{found['passed']:,} pass / {found['skipped']:,} skip"
    said += f" / {found['failed']:,} fail" if found["failed"] else ""
    said += f" / {found['errors']:,} error" if found["errors"] else ""
    return f"{SUITE} {said}<!--r:suite/{receipt_name(receipt)}-->."


def headline(facts: dict[str, Any], changed: str | None = None, next_step: str | None = None) -> list[str]:
    """The four headline lines. The first two come from the facts; the last two are the agent's."""
    utc, local = facts["utc"], facts["local"]
    stamp = f"{UPDATED} {local} local ({utc if utc[:10] != local[:10] else utc[11:]} UTC)."
    if facts.get("main") and facts.get("commit"):
        number = f" (#{facts['pull_request']})" if facts.get("pull_request") else ""
        stamp += f" `{facts['main']}` at `{facts['commit']}`{number}."
    return [stamp, _suite_line(facts.get("suite")), f"{CHANGED} {_one_line(changed)}",
            f"{NEXT} {_one_line(next_step)}"]


def _rewritten(lines: list[str], fresh: list[str]) -> list[str]:
    """The file's lines with the two generated headline lines replaced, and the rest as it was."""
    page = parse("\n".join(lines))
    if page.headline_line is None:  # no headline yet: a whole one goes under the title
        first = next((index for index, line in enumerate(lines) if line.strip()), None)
        at = first + 1 if first is not None and lines[first].startswith("# ") else 0
        head, tail = lines[:at], lines[at:]
        return head + ([""] if head else []) + fresh + ([""] if tail and tail[0].strip() else []) + tail
    start, end = page.headline_line - 1, page.headline_line - 1 + len(page.headline)
    kept = [line for line in lines[start + 1:end] if not line.lstrip().startswith(SUITE)]
    for label, line in ((CHANGED, fresh[2]), (NEXT, fresh[3])):
        if not any(old.lstrip().startswith(label) for old in kept):
            kept.append(line)
    return lines[:start] + fresh[:2] + kept + lines[end:]


def refresh(root: Path, manifest: Manifest) -> Path:
    """Write the facts into the checkpoint, and return its path.

    The `**Last updated:**` and `**Suite:**` lines are rewritten. The `**Changed:**` and `**Next:**`
    lines, and everything below the headline, stay as the file has them. A project with no
    checkpoint gets a new one: the title, the headline and the three section headings.

    A receipt the headline cites must be there for the next reader. So when the newest receipt is
    a local one, it is copied to the committed folder under the same name.
    """
    root = Path(root)
    path = root / home(manifest)
    known = facts(root, manifest)
    suite = known["suite"]
    if suite and suite["_path"].startswith(receipts.LOCAL + "/"):
        copied = {key: value for key, value in suite.items() if key != "_path"}
        receipts.write(root, "suite", receipt_name(suite), copied, committed=True)
    fresh, newline = headline(known), "\n"
    if path.is_file():
        text = path.read_bytes().decode("utf-8")
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = _rewritten(text.splitlines(), fresh)
    else:
        lines = [TITLE, "", *fresh]
        for name in SECTIONS:
            lines += ["", f"## {name}"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(newline.join(lines) + newline, encoding="utf-8", newline="")
    return path
