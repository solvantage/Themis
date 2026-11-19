"""Units of work: the folders a project keeps its pieces of work in.

A project names them with one pattern, such as `research/experiments/*`, or with a list of
patterns, such as `["research/*", "products/*/setups/*/tune"]`. Each folder that matches one of
them is one unit. Inside a unit, patterns are relative to the unit's folder.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from themis import paths


def patterns(value: str | Iterable[str] | None) -> list[str]:
    """The work patterns a project gave, as a list: one pattern, a list of them, or none."""
    if value is None:
        return []
    found = [value] if isinstance(value, str) else list(value)
    return [str(pattern).strip("/") for pattern in found if str(pattern).strip("/")]


def units(all_files: Iterable[str], pattern: str | Iterable[str]) -> dict[str, list[str]]:
    """Each unit folder that matches the pattern, or one of the patterns, with the files under it."""
    wanted = patterns(pattern)
    for each in wanted:
        if "**" in each:
            raise ValueError("a work pattern names folders at one depth; it cannot hold **")
    all_files = list(all_files)
    found: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()  # two patterns may match the same folder: its files count once
    for each in wanted:
        depth = each.count("/") + 1
        for name in all_files:
            parts = name.split("/")
            folder = "/".join(parts[:depth])
            if len(parts) > depth and (folder, name) not in seen and paths.matches(folder, each):
                seen.add((folder, name))
                found.setdefault(folder, []).append(name)
    return found


def inside(unit: str, files: Iterable[str], patterns: Iterable[str]) -> list[str]:
    """The unit's files whose path inside the unit matches one of the patterns."""
    patterns = list(patterns)
    return sorted(name for name in files if paths.matches_any(name[len(unit) + 1:], patterns))


def file_name(unit: str) -> str:
    """A unit's whole path as one file name, so two units that share a folder name never share a
    record: `setups/a/tune` and `setups/b/tune` are `setups-a-tune` and `setups-b-tune`."""
    return unit.strip("/").replace("/", "-")


def named(units: Iterable[str], name: str) -> str | None:
    """The unit a record names: by its path, or by its folder name when no other unit has that
    folder name. None when it names no unit, or a folder name several units share."""
    name = name.strip("/")
    units = list(units)
    if name in units:
        return name
    found = [unit for unit in units if unit.rsplit("/", 1)[-1] == name]
    return found[0] if len(found) == 1 else None


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
