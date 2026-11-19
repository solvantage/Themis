"""Sealed data windows: the one door a study reads unseen data through.

A project declares its data windows in the manifest, and marks the unseen ones as sealed:

    [trading.windows.holdout]
    from = "2022-01-01"
    to = "2024-12-31"
    sealed = true
    looks = 1

A study may also declare windows of its own, in its seal, one key for each window:

    windows: [is-2019, oos-2025]
    window-is-2019: {from = "2019-01-01", to = "2023-12-31"}
    window-oos-2025: {from = "2024-01-01", to = "2025-12-31", sealed = true}

or in a study table of the manifest, `[trading.studies."<study>".windows.<name>]`. A study reads
the project's windows and its own. A window id names one window wherever it is declared: studies
that share an id must give it the same dates, and their looks at it are counted together.

A study asks `window` for a window's dates before it loads any data. A window that is not sealed
is simply handed over. A sealed window opens only with the id of a grant the owner made for it
(`themis grant holdout <study>/<window> --reason ...`, or `holdout <window>` for one of the
project's windows), and each grant opens it once. The look is written down as a look record
before the dates are handed over, so the gate `holdout` can count the looks. A command run by
`themis act holdout <study>/<window> -- ...` gets the same look written before it starts.

There is no value to type that opens a sealed window. It takes a grant file.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from themis import grants as grants_of
from themis import paths, records, schema, work
from themis.gitlog import Git
from themis.packs.trading import units
from themis.schema import Required

if TYPE_CHECKING:
    from themis.manifest import Manifest

ACTION = "holdout"  # the action a grant names when it opens a sealed window
KINDS = ("signal", "pipeline")  # a look measures the idea, or only proves that the code runs
#: What a pipeline look must state: each field of the look record, and what it is in words.
DECLARED = {"scope": "its scope", "purpose": "its purpose", "compared_against": "what it was compared against"}
#: One data window, wherever it is declared: under [trading.windows], in a study table or in a seal.
WINDOW = {"from": Required(str), "to": Required(str), "sealed": bool, "looks": int}
PREFIX = "window-"  # a seal's key that declares one of its study's own windows: window-<id>
MANIFEST = "themis.toml"


class SealedWindow(Exception):
    """A sealed window was asked for and may not be opened. No look was written."""


def windows(manifest: Manifest) -> dict[str, dict[str, Any]]:
    """The data windows the project declared under [trading.windows], by name."""
    return manifest.table("trading").get("windows", {})


def is_sealed(declared: dict[str, Any]) -> bool:
    """True unless the window plainly is not sealed: only a missing `sealed`, or false, leaves it open."""
    return declared.get("sealed", False) is not False


def _said(window: dict[str, Any]) -> str:
    sealed = f", sealed, {window.get('looks', 1)} look(s)" if is_sealed(window) else ""
    return f"{window.get('from')} to {window.get('to')}{sealed}"


def _tables(value: Any) -> dict[str, dict[str, Any]]:
    return {key: item for key, item in value.items() if isinstance(item, dict)} if isinstance(value, dict) else {}


@dataclass
class Windows:
    """Every data window a project declares: its own under [trading.windows], and each study's.

    A window id names one window wherever it is declared, so studies that share an id read the same
    dates and are counted together. A second declaration of an id that differs from the first, or
    one that cannot be read, is a problem: (where, the window id, what is wrong).
    """

    project: dict[str, dict[str, Any]] = field(default_factory=dict)
    studies: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)  # study -> its own windows
    problems: list[tuple[str, str, str]] = field(default_factory=list)
    first: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)  # id -> (where, declaration)

    def add(self, where: str, name: str, window: dict[str, Any], study: str | None = None) -> None:
        if study is not None:
            self.studies.setdefault(study, {})[name] = window
        else:
            self.project[name] = window
        if name not in self.first:
            self.first[name] = (where, window)
            return
        seen, earlier = self.first[name][0], self.first[name][1]
        if _said(earlier) != _said(window):
            self.problems.append((where, name, f"the window {name} is declared here as {_said(window)}, and in {seen} "
                                               f"as {_said(earlier)}: one window id names one window"))

    def of(self, study: str | None) -> dict[str, dict[str, Any]]:
        """The windows a study reads: the project's and its own. With no study, the project's alone."""
        return {**self.project, **self.studies.get((study or "").strip("/"), {})}

    def ids(self) -> dict[str, dict[str, Any]]:
        """Each window id once, as the strictest of its declarations: sealed when any declaration seals
        it or cannot be read, with the fewest looks any of them allows."""
        found: dict[str, dict[str, Any]] = {}
        broken = {name for _, name, _ in self.problems}
        for declared in (self.project, *self.studies.values()):
            for name, window in declared.items():
                held = found.setdefault(name, {**window, "sealed": False})
                if is_sealed(window) or name in broken:
                    looks = [window.get("looks", 1)] + ([held.get("looks", 1)] if held["sealed"] else [])
                    held.update(sealed=True, looks=min(looks))
        return found

    def sealed(self) -> list[str]:
        return sorted(name for name, window in self.ids().items() if is_sealed(window))

    def troubles(self, name: str) -> list[str]:
        """What is wrong with the declarations of this window id, in plain words."""
        return [f"{text} ({where})" for where, found, text in self.problems if found == name]

    def targets(self, study: str | None, name: str) -> tuple[str, ...]:
        """What a grant for one look at this window by this study names: `<study>/<window>`. A window
        of the project's own may also be opened by a grant that names the window alone."""
        study = (study or "").strip("/")
        if not study:
            return (name,)
        return (f"{study}/{name}", name) if name in self.project else (f"{study}/{name}",)


def _declared(key: str, value: Any) -> tuple[dict[str, Any] | None, str | None]:
    """A window a seal declares under `key`, read from its inline table; or what is wrong with it."""
    text = value.strip() if isinstance(value, str) else ""
    if not (text.startswith("{") and text.endswith("}")):
        return None, (f"the seal's {key} must be an inline table, such as "
                      '{from = "2022-01-01", to = "2024-12-31", sealed = true}')
    try:
        window = tomllib.loads(f"window = {text}")["window"]
    except tomllib.TOMLDecodeError as error:
        return None, f"the seal's {key} cannot be read as an inline table ({error})"
    window = {name: item.isoformat() if isinstance(item, (dt.date, dt.time)) else item for name, item in window.items()}
    wrong = schema.problems(window, WINDOW, f"the seal's {key}")
    return (None, "; ".join(wrong)) if wrong else (window, None)


def studies_patterns(value: Any) -> list[str]:
    """The study patterns under [trading] work: one glob, or a list of them."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [item for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def studies(manifest: Manifest, files: Iterable[str]) -> dict[str, list[str]]:
    """Each study folder with its files, or nothing when the project has not said where studies live."""
    found: dict[str, list[str]] = {}
    files = list(files)
    for pattern in studies_patterns(manifest.table("trading").get("work")):
        try:
            found.update(work.units(files, pattern))
        except ValueError:
            continue  # a pattern that cannot name studies is refused by the rules that read studies
    return found


def collect(manifest: Manifest, files: Iterable[str], read: Callable[[str], str | None]) -> Windows:
    """Every data window the project declares: under [trading.windows], in each study table, and in
    each study's seal. `files` are the repository's files and `read` gives one file's text."""
    table, found = manifest.table("trading"), Windows()
    for name, window in _tables(table.get("windows")).items():
        found.add(MANIFEST, name, window)
    for study, entry in _tables(table.get("studies")).items():
        for name, window in _tables(entry.get("windows")).items():
            found.add(MANIFEST, name, window, study.strip("/"))
    for unit, inside in sorted(studies(manifest, files).items()):
        seals = work.inside(unit, inside, units.SEAL)
        try:
            plan = records.frontmatter(read(seals[0]) or "") if seals else None
        except ValueError:
            continue  # a seal that cannot be read is refused by prereg/declared
        for key, value in sorted((plan or {}).items()):
            if key.startswith(PREFIX) and len(key) > len(PREFIX):
                window, problem = _declared(key, value)
                if problem:
                    found.problems.append((seals[0], key[len(PREFIX):], problem))
                else:
                    found.add(seals[0], key[len(PREFIX):], window, unit)
    return found


def reader(root: Path) -> Callable[[str], str | None]:
    def read(name: str) -> str | None:
        try:
            return (root / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
    return read


def first_uses(looks: Iterable[Any]) -> dict[str, str]:
    """Each grant that a look names, with the path of the first look, in the order given, that named it."""
    found: dict[str, str] = {}
    for look in looks:
        name = look.get("grant")
        if isinstance(name, str) and name.strip():
            found.setdefault(name.strip(), look.path)
    return found


def grant_problem(grants: dict[str, Any], name: str | None, window: str | tuple[str, ...],
                  used_by: str | None = None) -> str | None:
    """Why the grant with this id does not open that sealed window, in plain words. None when it does.

    `grants` holds the project's grant records by id, and `window` is the target a grant for this
    look names, or the targets that will each do (`Windows.targets`). `used_by` is the path of an
    earlier look that named the grant, when there is one. The library, `themis act` and the rule
    `holdout/guarded` all ask here, so a look the library allows is one the rule accepts.
    """
    targets = (window,) if isinstance(window, str) else tuple(window)
    if not name:
        return "no grant is named"
    grant = grants.get(name)
    if grant is None:
        return f"no grant with the id {name} is on file"
    if getattr(grant, "problems", None):
        return f"the grant {name} cannot be read ({'; '.join(grant.problems)})"
    if grant.get("action") != ACTION:
        return f"the grant {name} is for the action {grant.get('action')}, not {ACTION}"
    if grant.get("target") not in targets:
        return f"the grant {name} is for the target {grant.get('target')}, not {' or '.join(targets)}"
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
    record whose action is "holdout" and whose target is `<study>/<window>` (or the window alone,
    for one of the project's windows), and which no look has used yet. The look is written to
    `looks/<UTC date>-<window>-<n>.toml` before the dates are returned, and so is an action receipt
    under `receipts/action/` that names the grant.

    `kind` is "signal" for a look that measures the idea, or "pipeline" for one that only proves the
    code runs. A pipeline look needs a grant too, and states its `scope`, its `purpose` and what it
    was `compared_against`. `study` is the folder of the study that looks: it reads the project's
    windows and those its own seal or study table declares. `now` sets the clock.

    Raises KeyError for a window that neither the manifest nor the study declares, ValueError for a
    look that is badly described, and SealedWindow when a sealed window may not be opened. Nothing
    is written then.
    """
    moment = _moment(now)
    span, target, _ = _open(Path(root), manifest, name, grant=grant, kind=kind, study=study, now=moment,
                            stated={"scope": scope, "purpose": purpose, "compared_against": compared_against})
    if target is not None:
        # The core's own receipt of a guarded action, so the core grant rules see the look as well.
        grants_of.record_action(root, ACTION, target, grant=grant.strip() if isinstance(grant, str) else None,
                                now=moment)
    return span


def act(root: Path, manifest: Manifest, target: str, *, grant: str, now: dt.datetime | None = None) -> list[Path]:
    """What `themis act holdout <study>/<window> -- COMMAND` writes before the command starts: the
    signal look the holdout rules count, keyed by the study and the window. A target with no study
    names one of the project's windows. Raises ValueError, with nothing written, when the look may
    not be taken; the core writes the action receipt itself."""
    study, _, name = target.rpartition("/")
    try:
        _, opened, path = _open(Path(root), manifest, name, grant=grant, kind="signal", study=study or None,
                                now=_moment(now), stated={})
    except (KeyError, SealedWindow) as error:
        raise ValueError(str(error.args[0] if error.args else error)) from None
    if opened is None or path is None:
        raise ValueError(f"the window {name} is not sealed: a study reads it with no grant, so there is no "
                         "look to record")
    return [path]


def _open(root: Path, manifest: Manifest, name: str, *, grant: str | None, kind: str, study: str | None,
          now: dt.datetime, stated: dict[str, str | None]) -> tuple[tuple[str, str], str | None, Path | None]:
    """The window's dates, the target of the grant that opened it and the look written; the last two
    are None for a window that is not sealed. Raises as `window` does, with nothing written."""
    if kind not in KINDS:
        raise ValueError(f"a look's kind is {' or '.join(KINDS)}, not {kind!r}")
    if manifest.problems:
        raise SealedWindow("the manifest has problems, so it cannot say which windows are sealed: "
                           + "; ".join(manifest.problems))
    if study is not None and not isinstance(study, str):
        raise ValueError("study must be text")
    files = Git(root).all_files()
    found = collect(manifest, files, reader(root))
    declared = found.of(study)
    if name not in declared:
        raise KeyError(f"the manifest declares no data window named {name!r} under [trading.windows]"
                       + (f", and the study {study} declares none of its own" if study else ""))
    troubles = found.troubles(name)
    if troubles:
        raise SealedWindow(f"the window {name} was not opened: {'; '.join(troubles)}. Give each window one "
                           "declaration, or an id of its own")
    span = (declared[name]["from"], declared[name]["to"])
    if not is_sealed(found.ids()[name]):
        return span, None, None

    stated = {"study": study, **stated}
    wrong = [field for field, value in stated.items() if value is not None and not isinstance(value, str)]
    if wrong:
        raise ValueError(f"{', '.join(wrong)} must be text")
    missing = [field for field in DECLARED if kind == "pipeline" and not (stated.get(field) or "").strip()]
    if missing:
        raise ValueError("a pipeline look states its scope, its purpose and what it was compared against; "
                         f"give {', '.join(missing)}")

    folder = _folder(manifest)
    grants = {record.id: record for record in records.load_kind(root, manifest, "grant", files)}
    looks = records.load_kind(root, manifest, "look", files)
    wanted = grant.strip() if isinstance(grant, str) else None
    targets = found.targets(study, name)
    problem = grant_problem(grants, wanted, targets, first_uses(looks).get(wanted)) or _unused(grants[wanted], looks)
    if problem:
        raise SealedWindow(f"the window {name} is sealed and was not opened: {problem}. The owner opens it "
                           f"for one look with `themis grant {ACTION} {targets[0]} --reason ...`.")
    text = _toml({"window": name, "kind": kind, "at": now.isoformat(), "grant": wanted, **stated})
    stem = f"{now.date().isoformat()}-{re.sub(r'[^A-Za-z0-9_.-]+', '-', name).strip('-.') or 'window'}"
    return span, grants[wanted].get("target"), _write(root / folder, stem, text)
