"""Grants and attestations, written by a command and never by hand.

A grant is the owner's yes to one action on one target, used once. An attestation says who judged
a file, and holds the hash of what they judged. An action receipt is what guarded code leaves
behind, naming the grant it used. The gates `grant` and `attest` compare these files.

The standard library reads TOML and does not write it, so the small writer these records need
lives here too.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from themis import receipts

GRANTS = "grants"
ATTESTATIONS = "attestations"
_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+\Z")


# -- writing TOML -------------------------------------------------------------------------------


def _text(value: str) -> str:
    """A TOML basic string. JSON escapes text almost as TOML does. Two cases differ, and both are
    handled here: JSON would write some characters, such as an emoji, as two escaped halves, which
    TOML refuses, so every character is written as it is; and JSON leaves the delete character
    bare, which TOML refuses too, so that one is escaped."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("text that is not valid Unicode cannot be written") from None
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _value(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return "[" + ", ".join(_text(item) for item in value) + "]"
    raise TypeError(f"{key}: only text, a number, true or false, or a list of text can be written")


def to_toml(table: dict[str, Any]) -> str:
    """A flat table as TOML: one `key = value` line for each entry, in the order given.

    A value is text, a number, true or false, or a list of text. Anything else raises TypeError:
    a record that needs more than this is not one this module writes.
    """
    lines = []
    for key, value in table.items():
        if not isinstance(key, str) or not key:
            raise TypeError("a key is text, and is not empty")
        lines.append(f"{key if _BARE_KEY.match(key) else _text(key)} = {_value(key, value)}")
    return "".join(f"{line}\n" for line in lines)


# -- names, times and hashes --------------------------------------------------------------------


def slug(text: str, limit: int = 40) -> str:
    """Text made safe for a file name: lower case, with one hyphen for each run of other characters."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:limit].strip("-") or "item"


def file_hash(path: Path) -> str:
    """The SHA-256 of a file's bytes: what an attestation is bound to."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def grant_id(grant: Any) -> str | None:
    """A grant's id: its record's file name without `.toml`. Takes a record, a path or the id itself."""
    if grant is None:
        return None
    found = getattr(grant, "id", None)
    return found if isinstance(found, str) else Path(str(grant)).name.removesuffix(".toml")


def _moment(now: dt.datetime | None) -> dt.datetime:
    """The time to record, in UTC and to the second. A time with no zone is taken to be UTC."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    return now.astimezone(dt.timezone.utc).replace(microsecond=0)


def _named(**fields: Any) -> None:
    for name, value in fields.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be given, and must not be empty")


def _free(folder: Path, stem: str, suffix: str) -> str:
    """The stem itself when no file has it, else the stem with the first free number after it."""
    number, name = 1, stem
    while os.path.lexists(folder / f"{name}{suffix}"):  # a link that leads nowhere still holds the name
        number += 1
        name = f"{stem}-{number}"
    return name


def _write_new(folder: Path, stem: str, text: str) -> Path:
    """Write a new record and never an existing one: a name that is taken gets a numbered suffix."""
    folder.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        path = folder / (f"{stem}.toml" if number == 1 else f"{stem}-{number}.toml")
        try:
            with path.open("x", encoding="utf-8") as handle:  # "x" refuses a name that is already there
                handle.write(text)
            return path
        except FileExistsError:
            number += 1


# -- grants -------------------------------------------------------------------------------------


def new_grant(
    root: Path, action: str, target: str, *, granted_by: str, reason: str,
    ceiling: float | None = None, unit: str | None = None, now: dt.datetime | None = None,
) -> Path:
    """Write the owner's yes to one action on one target, and return the new record's path.

    The record is `grants/<UTC date>-<action>-<target>.toml`. A grant always says why: an empty
    reason raises ValueError. An action that spends is given a ceiling, and the unit it is in.
    """
    _named(action=action, target=target, granted_by=granted_by)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("a grant needs a reason: say why the owner allows this")
    if ceiling is not None and (isinstance(ceiling, bool) or not isinstance(ceiling, (int, float))
                                or not math.isfinite(ceiling) or ceiling < 0):
        raise ValueError("a ceiling is a number, zero or more")
    moment = _moment(now)
    data: dict[str, Any] = {"action": action, "target": target, "granted_by": granted_by,
                            "granted_at": moment.isoformat(), "reason": reason}
    data.update({key: value for key, value in (("ceiling", ceiling), ("unit", unit)) if value is not None})
    stem = f"{moment.date().isoformat()}-{slug(action)}-{slug(target)}"
    return _write_new(Path(root) / GRANTS, stem, to_toml(data))


def find_grant(grants: Iterable[Any], action: str, target: str) -> Any | None:
    """The grant for that action on that target, or None. With several, the newest one.

    `grants` are grant records, or plain tables. A grant already marked spent (`spent_at` or
    `spent_by`) is not returned: it cannot open another action.
    """
    usable = [
        grant for grant in grants
        if grant.get("action") == action and grant.get("target") == target
        and not grant.get("spent_at") and not grant.get("spent_by")
    ]
    return max(usable, key=lambda grant: str(grant.get("granted_at", "")), default=None)


def record_action(
    root: Path, action: str, target: str, *, grant: Any = None, amount: float | None = None,
    unit: str | None = None, by: str | None = None, now: dt.datetime | None = None,
) -> Path:
    """Write the receipt of a guarded action that ran, and return its path.

    `grant` is the grant the action used: its record, its path or its id. The receipt is committed,
    under `receipts/action/`, so `grant/required` can compare it with the grants.
    """
    _named(action=action, target=target)
    if amount is not None and (isinstance(amount, bool) or not isinstance(amount, (int, float))
                               or not math.isfinite(amount)):
        raise ValueError("an amount is a number")
    moment = _moment(now)
    data: dict[str, Any] = {"action": action, "target": target, "at": moment.isoformat()}
    optional = (("grant", grant_id(grant)), ("amount", amount), ("unit", unit), ("by", by))
    data.update({key: value for key, value in optional if value is not None})
    folder = Path(root) / receipts.COMMITTED / "action"
    name = _free(folder, f"{moment.strftime('%Y-%m-%d-%H%M%S')}-{slug(action)}-{slug(target)}", ".json")
    return receipts.write(Path(root), "action", name, data, committed=True)


# -- attestations -------------------------------------------------------------------------------


def new_attestation(
    root: Path, subject: str, row: str, judge: str, by: str, *, note: str | None = None,
    author: str | None = None, shown: Iterable[str] | None = None, now: dt.datetime | None = None,
) -> Path:
    """Record who judged a file, and the hash of the file as it is now. Return the record's path.

    `subject` is the file's path in the repository, `row` the checklist row it answers, `judge`
    the kind of judge the row names and `by` who judged. `author` is who made the file and `shown`
    lists what the judge was given: a second reader needs both. A subject that is not a file in
    the repository raises ValueError, because nothing can be judged that is not there.
    """
    base = Path(root).resolve()
    target = (base / subject).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise ValueError(f"{subject} is not a file in this repository, so it cannot be judged")
    _named(row=row, judge=judge, by=by)
    written = Path(os.path.normpath(base / subject))  # the path as it was named: a link keeps its own name
    name = (written if written.is_relative_to(base) else target).relative_to(base).as_posix()
    moment = _moment(now)
    data: dict[str, Any] = {"subject": name, "row": row, "judge": judge, "by": by,
                            "at": moment.isoformat(), "sha256": file_hash(target)}
    optional = (("note", note), ("author", author), ("shown", None if shown is None else list(shown)))
    data.update({key: value for key, value in optional if value is not None})
    stem = f"{moment.date().isoformat()}-{slug(name)}-{slug(row)}"
    return _write_new(Path(root) / ATTESTATIONS, stem, to_toml(data))
