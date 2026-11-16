"""Views: pages people read, written from what machines read.

A view is a markdown page, or a block inside one, that Themis writes from records and rules. A
generated block sits between two markers:

    <!-- themis:begin NAME -->
    ...
    <!-- themis:end NAME -->

A project lists its views in the manifest: `[views]` maps a file to a view's name. A rule
regenerates each one and fails on a difference, so the page and the records cannot drift.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from themis import records
from themis.gitlog import Git
from themis.manifest import Manifest

#: view name -> a function that writes the view's text from the project.
VIEWS: dict[str, Callable[[Path, Manifest], str]] = {}


def view(name: str) -> Callable[[Callable[[Path, Manifest], str]], Callable[[Path, Manifest], str]]:
    def register(build: Callable[[Path, Manifest], str]) -> Callable[[Path, Manifest], str]:
        VIEWS[name] = build
        return build

    return register


def _markers(name: str) -> tuple[str, str]:
    return f"<!-- themis:begin {name} -->", f"<!-- themis:end {name} -->"


def block(text: str, name: str) -> str | None:
    """The text between a view's markers, or None when the page has no such block."""
    begin, end = _markers(name)
    found = re.search(re.escape(begin) + r"\n(.*?)\n?" + re.escape(end), text, flags=re.DOTALL)
    return found.group(1) if found else None


def with_block(text: str, name: str, body: str) -> str:
    """The page with that block replaced, or with the block added at the end when it had none."""
    begin, end = _markers(name)
    wrapped = f"{begin}\n{body.rstrip()}\n{end}"
    if block(text, name) is None:
        return (text.rstrip() + "\n\n" if text.strip() else "") + wrapped + "\n"
    return re.sub(re.escape(begin) + r".*?" + re.escape(end), lambda _: wrapped, text, count=1, flags=re.DOTALL)


def _cell(value: object) -> str:
    return " ".join(str(value if value is not None else "").split()).replace("|", "\\|")


def _table(header: list[str], rows: list[list[object]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(_cell(item) for item in row) + " |" for row in rows]
    return "\n".join(lines)


@view("rules")
def rules_view(root: Path, manifest: Manifest) -> str:
    """The rules in force in this project, for the agent instructions."""
    lines = ["This project is checked by Themis. These rules are in force. `themis explain RULE` says more.", ""]
    rows = []
    for rule in sorted(manifest.active_rules(), key=lambda rule: rule.id):
        setting = manifest.setting(rule)
        # Only what the project itself switched on: a rule left at its default is not "in force".
        if setting.stated and setting.level != "off":
            rows.append([f"`{rule.id}`", setting.level, rule.promise])
    for table in manifest.external:
        if table.get("level", "enforce") != "off":
            rows.append([f"`{table['id']}`", table.get("level", "enforce"), table["description"]])
    lines.append(_table(["Rule", "Level", "The promise"], rows) if rows else "No rule is in force yet.")
    lines += ["", "Before finishing, run `themis check`. A FAIL or a REFUSE is not done."]
    return "\n".join(lines)


@view("ledger")
def ledger_view(root: Path, manifest: Manifest) -> str:
    found = records.load_kind(root, manifest, "ledger", Git(root).all_files())
    rows = [[record.id, record.get("work"), record.get("state", ""), record.get("logged", ""), record.get("question", "")]
            for record in found if not record.problems]
    return _table(["Record", "Work", "State", "Logged", "Question"], rows) if rows else "No ledger record yet."


@view("decisions")
def decisions_view(root: Path, manifest: Manifest) -> str:
    found = records.load_kind(root, manifest, "decision", Git(root).all_files())
    rows = [[record.get("work"), record.get("decision"), record.get("verdict"), record.get("gate"),
             str(record.get("decided_at", ""))[:10]] for record in found if not record.problems]
    return _table(["Work", "Decision", "Verdict", "Gate", "Decided"], rows) if rows else "No decision yet."


def expected(root: Path, manifest: Manifest, path: str, name: str) -> str | None:
    """What the page should hold: the whole page for a page that is all view, else the page with
    its block rewritten. None when the view's name is unknown."""
    if name not in VIEWS:
        return None
    body = VIEWS[name](root, manifest)
    try:
        current = (root / path).read_text(encoding="utf-8")
    except OSError:
        current = ""
    return with_block(current, name, body)


def write(root: Path, manifest: Manifest, path: str, name: str) -> Path:
    text = expected(root, manifest, path, name)
    if text is None:
        raise ValueError(f"there is no view named {name!r}; choose from {', '.join(sorted(VIEWS))}")
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target
