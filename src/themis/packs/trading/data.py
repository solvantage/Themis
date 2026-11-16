"""Sealed data windows: the one door a study reads unseen data through.

A project declares its data windows in the manifest, and marks the unseen ones as sealed:

    [trading.windows.holdout]
    from = "2022-01-01"
    to = "2024-12-31"
    sealed = true
    looks = 1

A study asks `window` for a window's dates before it loads any data. A window that is not sealed
is simply handed over. A sealed window opens only with the id of a grant the owner made for it
(`themis grant holdout <window> --reason ...`), and each grant opens it once. The look is written
down as a look record before the dates are handed over, so the gate `holdout` can count the looks.

There is no value to type that opens a sealed window. It takes a grant file.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from themis import grants as grants_of
from themis import paths, records
from themis.gitlog import Git

if TYPE_CHECKING:
    from themis.manifest import Manifest

ACTION = "holdout"  # the action a grant names when it opens a sealed window
KINDS = ("signal", "pipeline")  # a look measures the idea, or only proves that the code runs
#: What a pipeline look must state: each field of the look record, and what it is in words.
DECLARED = {"scope": "its scope", "purpose": "its purpose", "compared_against": "what it was compared against"}


class SealedWindow(Exception):
    """A sealed window was asked for and may not be opened. No look was written."""


def windows(manifest: Manifest) -> dict[str, dict[str, Any]]:
    """The data windows the project declared under [trading.windows], by name."""
    return manifest.table("trading").get("windows", {})


def is_sealed(declared: dict[str, Any]) -> bool:
    """True unless the window plainly is not sealed: only a missing `sealed`, or false, leaves it open."""
    return declared.get("sealed", False) is not False


def first_uses(looks: Iterable[Any]) -> dict[str, str]:
    """Each grant that a look names, with the path of the first look, in the order given, that named it."""
    found: dict[str, str] = {}
    for look in looks:
        name = look.get("grant")
        if isinstance(name, str) and name.strip():
            found.setdefault(name.strip(), look.path)
    return found


def grant_problem(grants: dict[str, Any], name: str | None, window: str, used_by: str | None = None) -> str | None:
    """Why the grant with this id does not open that sealed window, in plain words. None when it does.

    `grants` holds the project's grant records by id, and `used_by` is the path of an earlier look
    that named the grant, when there is one. The library and the rule `holdout/guarded` both ask
    here, so a look the library allows is one the rule accepts.
    """
    if not name:
        return "no grant is named"
    grant = grants.get(name)
    if grant is None:
        return f"no grant with the id {name} is on file"
    if getattr(grant, "problems", None):
        return f"the grant {name} cannot be read ({'; '.join(grant.problems)})"
    if grant.get("action") != ACTION:
        return f"the grant {name} is for the action {grant.get('action')}, not {ACTION}"
    if grant.get("target") != window:
        return f"the grant {name} is for the target {grant.get('target')}, not {window}"
    if used_by:
        return f"the grant {name} was already used by the look {used_by}"
    return None


def _unused(grant: Any, looks: list[Any]) -> str | None:
    """Why a grant that names this window still cannot open it, when no look is known to have used it."""
    if grant.get("spent_at") or grant.get("spent_by"):
        return f"the grant {grant.id} is marked as spent"
    unread = [look.path for look in looks if look.problems]
    if unread:
        return f"the look record {unread[0]} cannot be read, so the grant cannot be shown to be unused"
    return None


def _folder(manifest: Manifest) -> str:
    """The folder look records live in. A look written anywhere else would never be counted."""
    if "look" not in records.KINDS:
        raise SealedWindow("the look record kind is not registered: the trading pack did not load in full")
    home = records.home_of(manifest, "look")
    folder, _, name = home.rpartition("/")
    if "*" in folder or "?" in folder or not paths.matches("0000-00-00-window-1.toml", name):
        raise SealedWindow(f"look records live in {home}, which names no one folder to write a look in; "
                           "set homes.look to a pattern such as looks/*.toml")
    return folder


def _moment(now: dt.datetime | None) -> dt.datetime:
    """The time to record, in UTC and to the second. A time with no zone is taken to be UTC."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    return now.astimezone(dt.timezone.utc).replace(microsecond=0)


def _toml(fields: dict[str, str | None]) -> str:
    """A flat table of text as TOML, one `key = "value"` line for each field that was stated.

    The standard library reads TOML and does not write it. JSON escapes text the way a TOML basic
    string does, but for two cases: it would write a character outside the basic plane as two
    halves, which TOML refuses, so such characters are written as they are; and it leaves the
    delete character bare. Text that is not valid Unicode raises ValueError before anything is written.
    """
    lines = [f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in fields.items()
             if value is not None and value.strip()]
    text = "".join(lines).replace("\x7f", "\\u007f")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("a look's text is not valid Unicode, so it cannot be written") from None
    return text


def _write(folder: Path, stem: str, text: str) -> Path:
    """Write a new look record under the first free number, and never over an existing one."""
    folder.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        path = folder / f"{stem}-{number}.toml"
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(text)
        except FileExistsError:
            number += 1  # the name is taken, perhaps by a look written a moment ago: take the next
            continue
        return path


def window(
    root: Path, manifest: Manifest, name: str, *, grant: str | None = None, kind: str = "signal",
    study: str | None = None, scope: str | None = None, purpose: str | None = None,
    compared_against: str | None = None, now: dt.datetime | None = None,
) -> tuple[str, str]:
    """The window's `(from, to)` dates, handed over only when the window may be read.

    A window that is not sealed is simply returned. A sealed window needs `grant`: the id of a grant
    record whose action is "holdout" and whose target is this window, and which no look has used
    yet. The look is written to `looks/<UTC date>-<window>-<n>.toml` before the dates are returned,
    and so is an action receipt under `receipts/action/` that names the grant.

    `kind` is "signal" for a look that measures the idea, or "pipeline" for one that only proves the
    code runs. A pipeline look needs a grant too, and states its `scope`, its `purpose` and what it
    was `compared_against`. `study` is the folder of the study that looks. `now` sets the clock.

    Raises KeyError for a window the manifest does not declare, ValueError for a look that is badly
    described, and SealedWindow when a sealed window may not be opened. Nothing is written then.
    """
    if kind not in KINDS:
        raise ValueError(f"a look's kind is {' or '.join(KINDS)}, not {kind!r}")
    if manifest.problems:
        raise SealedWindow("the manifest has problems, so it cannot say which windows are sealed: "
                           + "; ".join(manifest.problems))
    declared = windows(manifest)
    if name not in declared:
        raise KeyError(f"the manifest declares no data window named {name!r} under [trading.windows]")
    span = (declared[name]["from"], declared[name]["to"])
    if not is_sealed(declared[name]):
        return span

    stated = {"study": study, "scope": scope, "purpose": purpose, "compared_against": compared_against}
    wrong = [field for field, value in stated.items() if value is not None and not isinstance(value, str)]
    if wrong:
        raise ValueError(f"{', '.join(wrong)} must be text")
    missing = [field for field in DECLARED if kind == "pipeline" and not (stated[field] or "").strip()]
    if missing:
        raise ValueError("a pipeline look states its scope, its purpose and what it was compared against; "
                         f"give {', '.join(missing)}")

    root, folder = Path(root), _folder(manifest)
    files = Git(root).all_files()
    grants = {record.id: record for record in records.load_kind(root, manifest, "grant", files)}
    looks = records.load_kind(root, manifest, "look", files)
    wanted = grant.strip() if isinstance(grant, str) else None
    problem = grant_problem(grants, wanted, name, first_uses(looks).get(wanted)) or _unused(grants[wanted], looks)
    if problem:
        raise SealedWindow(f"the window {name} is sealed and was not opened: {problem}. The owner opens it "
                           f"for one look with `themis grant {ACTION} {name} --reason ...`.")
    moment = _moment(now)
    text = _toml({"window": name, "kind": kind, "at": moment.isoformat(), "grant": wanted, **stated})
    stem = f"{moment.date().isoformat()}-{re.sub(r'[^A-Za-z0-9_.-]+', '-', name).strip('-.') or 'window'}"
    _write(root / folder, stem, text)
    # The core's own receipt of a guarded action, so the core grant rules see the look as well.
    grants_of.record_action(root, ACTION, name, grant=wanted, now=moment)
    return span
