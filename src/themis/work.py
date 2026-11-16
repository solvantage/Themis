"""Units of work: the folders a project keeps its pieces of work in.

A project names them with one pattern, such as `research/experiments/*`. Each folder that matches
is one unit. Inside a unit, patterns are relative to the unit's folder.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from themis import paths


def units(all_files: Iterable[str], pattern: str) -> dict[str, list[str]]:
    """Each unit folder that matches the pattern, with the files under it."""
    pattern = pattern.strip("/")
    if "**" in pattern:
        raise ValueError("a work pattern names folders at one depth; it cannot hold **")
    depth = pattern.count("/") + 1
    found: dict[str, list[str]] = {}
    for name in all_files:
        parts = name.split("/")
        if len(parts) > depth and paths.matches("/".join(parts[:depth]), pattern):
            found.setdefault("/".join(parts[:depth]), []).append(name)
    return found


def inside(unit: str, files: Iterable[str], patterns: Iterable[str]) -> list[str]:
    """The unit's files whose path inside the unit matches one of the patterns."""
    patterns = list(patterns)
    return sorted(name for name in files if paths.matches_any(name[len(unit) + 1:], patterns))


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
