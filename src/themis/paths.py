"""Path patterns, matched the same way everywhere.

`*` matches inside one folder, `**` matches across folders, `?` matches one character. Paths are
relative to the repository root and use forward slashes.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Iterable


@functools.lru_cache(maxsize=None)
def _compiled(pattern: str) -> re.Pattern[str]:
    out, index = [], 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(out) + r"\Z")


def matches(path: str, pattern: str) -> bool:
    return _compiled(pattern.strip("/")).match(path.strip("/")) is not None


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(matches(path, pattern) for pattern in patterns)


def select(paths: Iterable[str], pattern: str) -> list[str]:
    return sorted(path for path in paths if matches(path, pattern))
