"""Receipts: a tool's proof that something ran, on which exact tree, and what came out.

A receipt is written by a tool, never by hand. It is what turns a sentence such as "the suite
passes" into something a rule can check.

Receipts written on every run, such as the suite's, are local: `.themis/receipts/`, which is not
committed. A receipt that a document cites is copied to `receipts/`, which is.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from themis.gitlog import Git

LOCAL = ".themis/receipts"
COMMITTED = "receipts"


def tree_fingerprint(root: Path) -> str | None:
    """One id for the exact files a tool ran on: the commit's tree, plus any uncommitted change.

    None when the folder is not a git repository with a commit: there is then nothing to pin to.
    """
    git = Git(root)
    tree = git.tree_id() if git.is_repo else None
    if tree is None:
        return None
    dirty = git.dirty()
    if not dirty:
        return tree
    digest = hashlib.sha256(tree.encode())
    for name in sorted(dirty):
        digest.update(name.encode())
        try:
            digest.update((root / name).read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return f"{tree[:12]}+{digest.hexdigest()[:28]}"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def write(root: Path, kind: str, name: str, data: dict[str, Any], *, committed: bool = False) -> Path:
    folder = root / (COMMITTED if committed else LOCAL) / kind
    folder.mkdir(parents=True, exist_ok=True)
    if not committed:
        (root / ".themis" / ".gitignore").write_text("*\n", encoding="utf-8")
    path = folder / f"{name}.json"
    path.write_text(json.dumps({"kind": kind, **data}, indent=2) + "\n", encoding="utf-8")
    return path


def read_all(root: Path, kind: str) -> list[dict[str, Any]]:
    """Every readable receipt of one kind, local and committed."""
    found = []
    for base in (LOCAL, COMMITTED):
        folder = root / base / kind
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                found.append({**data, "_path": path.relative_to(root).as_posix()})
    return found


def suite_for_tree(root: Path, tree: str | None = None) -> dict[str, Any] | None:
    """The newest suite receipt taken on this exact tree, or None."""
    tree = tree or tree_fingerprint(root)
    matching = [receipt for receipt in read_all(root, "suite") if receipt.get("tree") == tree and tree]
    return max(matching, key=lambda receipt: receipt.get("at", ""), default=None)
