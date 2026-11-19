"""Gates: trials, prereg and holdout — how a study is counted, planned and shown unseen data.

    trials    each settings version that ran is a logged trial, and a figure adjusted for luck is
              adjusted for every trial in the ledger
    prereg    the plan is complete before the answer is known, and every result says what made it
    holdout   a sealed window is read with a grant, and each look at it is a record

A trial is a core ledger record whose `work` is the study's folder; its `variants` says how many
variants it covers, 1 when it states none. A look is one read of a sealed data window, written by
`themis.packs.trading.data.window`. Each rule's proofs are a table: what the world shows, the
verdict the rule must reach, text the finding must hold, and what the world's builder is given.
"""

from __future__ import annotations

import csv
import io
import json
import string
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from themis import records, work
from themis.packs.trading import data, forward, units
from themis.rule import Context, Param, proof, rule
from themis.schema import Choice, Required

if TYPE_CHECKING:
    from themis.proofs import World

records.register("look", {
    "window": Required(str), "kind": Required(Choice(*data.KINDS)), "at": Required(str), "study": str,
    "grant": str, "scope": str, "purpose": str, "compared_against": str, "forward_returns": bool,
}, "looks/*.toml")

ADJUSTED, COUNTED = "luck_adjusted_sharpe", "trials_counted"
HISTORY = Param("history", str, "results/run-history.csv", None, "the run-history file inside a study, a row a run")
COLUMN = Param("settings_column", str, "settings_id", None, "the run-history column that names each run's settings")
PENALTY = Param("penalty", int, 0, "higher", "extra trials added to the ledger's count, for choices nobody logged")
SETUP = """
    [project]
    packs = ["trading"]
    [trading]
    work = "work/*"
    windows.train = {from = "2015-01-01", to = "2021-12-31"}
    [trading.windows.holdout]
    from = "2022-01-01"
    to = "2024-12-31"
    sealed = true
"""


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _whole(value: Any) -> bool:
    """True for a whole number. True and false are not numbers, and 3.0 is as whole as 3."""
    return not isinstance(value, bool) and (isinstance(value, int) or (isinstance(value, float) and value.is_integer()))


def _hex(value: Any, shortest: int, longest: int) -> bool:
    return isinstance(value, str) and shortest <= len(value) <= longest and set(value) <= set(string.hexdigits)


#: A field a seal or a provenance file states -> (whether a value will do, what it must be, what it is for).
FIELDS = {
    "binding": (_text, "text", "the one clause that decides the study"),
    "gate": (_text, "text", "the gate function that issues the verdict"),
    "nulls": (lambda v: isinstance(v, list) and bool(v), "a list with an entry", "the nulls the idea must beat"),
    "windows": (lambda v: isinstance(v, list) and bool(v), "a list with an entry", "the data windows the study reads"),
    "mde": (lambda v: type(v) in (int, float) and v > 0, "a number above 0", "the smallest effect worth seeing"),
    "iterations": (lambda v: _whole(v) and v > 0, "a whole number above 0", "how many settings may be tried"),
    "risk_rules": (_text, "text", "the risk rules every setting must obey"),
    "settings": (_text, "text", "the fingerprint of the settings the live run and every replay use"),
    "min_trades": (lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0, "a whole number above 0",
                   "how many trades a forward run needs before any pass"),
    "stop_rule": (_text, "text", "who stops trading, and what must happen before a restart"),
    "lines": (lambda v: isinstance(v, list) and bool(v), "a list with an entry",
              "the lines each week is read against, match and unexplained among them"),
    "risk": (lambda v: isinstance(v, list), "a list", "the risk lines that stop the run, whatever else passes"),
    "ranges": (lambda v: isinstance(v, list), "a list", "the days since the start on which the live money is read"),
    "gap_parts": (lambda v: isinstance(v, list), "a list", "the parts the gap between live and replay money is split into"),
    "reasons": (lambda v: isinstance(v, list), "a list", "the known reasons for an entry missed or extra"),
    "commit":(lambda v: _hex(v, 7, 40), "7 to 40 hex characters", "the commit the run was made on"),
    "clean": (lambda v: v is True, "true", "a fingerprint taken on a dirty tree pins nothing"),
    "inputs": (lambda v: isinstance(v, dict) and bool(v) and all(_hex(item, 64, 64) for item in v.values()),
               "a table that gives each input's path a sha256 of 64 hex characters", "what the run read"),
}
TESTED = ("binding", "gate", "nulls", "windows", "mde")  # NEEDS: what the seal of each kind of study must state
NEEDS = {"strategy": TESTED, "signal": TESTED, "data": (), "tune": ("windows", "gate", "iterations", "risk_rules"),
         forward.KIND: ("gate", "settings", "min_trades", "stop_rule", "lines", "risk", "ranges", "gap_parts",
                        "reasons")}
SEAL_FIX = "state it in the seal's frontmatter; a seal already merged changes only through an amendment record"
RERUN = "run the study again on a clean tree; the run writes the commit, clean = true and a sha256 for each input"


def unstated(held: dict[str, Any], fields: tuple[str, ...], what: str) -> list[str]:
    """Each needed field that is missing, or is not what it must be, in plain words."""
    found = []
    for field in fields:
        fits, shape, purpose = FIELDS[field]
        if field not in held:
            found.append(f"the {what} does not state {field}: {purpose}")
        elif not fits(held[field]):
            found.append(f"{field} in the {what} must be {shape}: {purpose}")
    return found


def _variants(ctx: Context, rows: list[Any]) -> int | None:
    """How many trials these ledger records count for. None, with a refusal, when one cannot be read."""
    unread = [row for row in rows if not _whole(row.get("variants", 1)) or row.get("variants", 1) < 1]
    for row in unread:
        ctx.refuse("this trial's variants is not a whole number, 1 or more", where=row.path,
                   fix="write variants as a whole number: how many variants the trial covers")
    return None if unread else int(sum(row.get("variants", 1) for row in rows))


def _table(fields: dict[str, Any]) -> str:
    """A flat TOML table for a proof world. A field set to None is left out."""
    return "".join(f"{key} = {json.dumps(value)}\n" for key, value in fields.items() if value is not None)


def _prove(rule_id: str, build: Callable[..., None], cases: list[tuple[str, str, str | None, dict[str, Any]]]) -> None:
    """Register one proof for each case. A case's `files` are written after its world is built."""
    for name, expect, contains, given in cases:
        @proof(rule_id, name, expect=expect, contains=contains)
        def _(world: World, given: dict[str, Any] = given) -> None:
            build(world, **{key: value for key, value in given.items() if key != "files"})
            for path, text in given.get("files", {}).items():
                world.write(path, text)


# -- trials/settings-counted --------------------------------------------------------------------


def _versions(ctx: Context, path: str, column: str) -> dict[str, int] | None:
    """Each settings version in a run history, with the line it first ran on: a run that names none
    is a version of its own. None, with a refusal, when the history cannot be read."""
    text, found, problem = ctx.read(path), {}, None
    try:
        reader = csv.DictReader(io.StringIO(text or ""), strict=True)
        if text is None or column not in (reader.fieldnames or []):
            problem = "is not text" if text is None else f"has no column named {column}"
        for row in reader if problem is None else []:
            found.setdefault((row.get(column) or "").strip(), reader.line_num)
    except csv.Error as error:
        problem = f"cannot be read as CSV ({error})"
    if problem:
        ctx.refuse(f"the run history {problem}", where=path,
                   fix=f"write the run history as CSV, with a header row that holds the column {column}")
    return None if problem else found


@rule("trials/settings-counted", "Each new settings version in the run history is a counted trial.", pack="trading",
      params=(HISTORY, COLUMN),
      learned="A grid of settings ran with nothing logged, so the best run looked like the only one tried.")
def settings_counted(ctx: Context) -> None:
    studies, logged = units.studies(ctx), units.trials(ctx)
    named: dict[str, list[Any]] = {}  # a record may name its study by folder name alone, when no other shares it
    folder_named: dict[str, str] = {}  # a folder name a record used that several studies share
    for name, rows in logged.items():
        if (found := work.named(studies, name)) is not None:
            named.setdefault(found, []).extend(rows)
        elif sum(unit.rsplit("/", 1)[-1] == name.strip("/") for unit in studies) > 1:
            folder_named[name.strip("/")] = name
    for unit, files in sorted(studies.items()):
        path = f"{unit}/{ctx.param('history').strip('/')}"
        if path not in files or ctx.predates(work.inside(unit, files, units.SEAL)):  # sealed before since
            continue
        ctx.inspect()
        versions = _versions(ctx, path, ctx.param("settings_column"))
        rows = named.get(unit, [])
        shared = folder_named.get(unit.rsplit("/", 1)[-1]) if not rows else None
        if shared:
            ctx.breach(f"the ledger record names {shared}, a folder name several studies share, so it counts for "
                       "none of them", where=path, fix=f"name the study by its whole path in the record: work = "
                       f'"{unit}"')
            continue
        if not rows:
            ctx.breach("this study has a run history and no trial in the ledger", where=path,
                       fix="log the study in the ledger, with the variants it covers, and say why the record is late")
            continue
        counted = _variants(ctx, rows)
        if versions is not None and counted is not None and len(versions) > counted:
            ctx.breach(f"the run history holds {len(versions)} settings versions, but the ledger counts {counted} for "
                       "this study", where=path, line=sorted(versions.values())[counted],
                       fix="log each settings version before it runs: raise the trial's variants, or add a trial")


def _history(world: World, runs: str = "s1 s2 s3", trials: tuple[dict[str, Any], ...] = ({"variants": 3},),
             column: str = "settings_id", since: str | None = None, other: str | None = None) -> None:
    """A study whose run history holds one run for each settings version named, and its ledger records.
    With `since`, the study is sealed and merged on the main line first, and the rule binds from that date.
    With `other`, work is a list of two globs, and a second study is other/<other>."""
    rule = f'\n    [rules."trials/settings-counted"]\n    since = "{since}"\n' if since else ""
    setup = SETUP.replace('work = "work/*"', 'work = ["work/*", "other/*"]') if other else SETUP
    world.manifest(setup + rule)
    if other:
        world.write(f"other/{other}/PRE-REG.md", "---\nkind: tune\n---\n")
    if since:
        world.write("work/a/PRE-REG.md", "---\nkind: tune\n---\n")
        world.commit("the seal")
    rows = "".join(f"{number},{version}\n" for number, version in enumerate(runs.split(), start=1))
    world.write("work/a/results/run-history.csv", f"run,{column}\n{rows}")
    for number, fields in enumerate(trials, start=1):
        world.write(f"ledger/t{number}.toml", _table({"work": "work/a", **fields}))


_prove("trials/settings-counted", _history, [
    ("three settings versions, and a trial that covers three variants", "pass", None, {}),
    ("the same settings run again is not a new version", "pass", None, {"runs": "s1 s1 s2 s3 s1"}),
    ("two trials add up, and one states no variants", "pass", None, {"trials": ({"variants": 2}, {"work": "a"})}),
    ("a run with new settings and no trial for it", "fail", "but the ledger counts 2", {"trials": ({"variants": 2},)}),
    ("a trial for another study does not count here", "fail", "no trial in the", {"trials": ({"work": "work/b"},)}),
    ("work is a list, and a trial names a folder name only this study has", "pass", None,
     {"trials": ({"work": "a", "variants": 3},), "other": "b"}),
    ("a trial that names a folder name two studies share counts for neither", "fail",
     "the ledger record names a, a folder name several studies share", {"trials": ({"work": "a", "variants": 3},),
                                                                         "other": "a"}),
    ("a run history with no settings column", "refuse", "has no column named settings_id", {"column": "preset"}),
    ("a run history that is not CSV", "refuse", "cannot be read as CSV", {"runs": '"s1'}),
    ("a trial whose variants is not a number", "refuse", "not a whole number", {"trials": ({"variants": "a few"},)}),
    ("a study sealed before the rule's start date is exempt", "refuse", "nothing was inspected",
     {"trials": ({"variants": 2},), "since": "2027-01-01"}),
    ("a study sealed after the rule's start date is counted", "fail", "but the ledger counts 2",
     {"trials": ({"variants": 2},), "since": "2025-01-01"}),
])


# -- trials/count-feeds-adjustment --------------------------------------------------------------


@rule("trials/count-feeds-adjustment", "The luck-adjusted figure uses the ledger's own count of trials.",
      pack="trading", params=(PENALTY,),
      learned="A figure was adjusted for the few trials of its own study, while the ledger held many more.")
def count_feeds_adjustment(ctx: Context) -> None:
    paths = [f"{unit}/{units.METRICS}" for unit, files in sorted(units.studies(ctx).items())
             if not ctx.predates(work.inside(unit, files, units.SEAL))]  # sealed before since
    held = {path: metrics.get(COUNTED) for path in paths if ADJUSTED in (metrics := units.read_json(ctx, path) or {})}
    if not held:
        return
    ctx.inspect(len(held))
    rows = [row for found in units.trials(ctx).values() for row in found]
    if not rows:
        ctx.refuse("the ledger holds no trial that can be read, so the trials cannot be counted",
                   fix="log every trial in the ledger before a figure is adjusted for their number")
        return
    if _variants(ctx, rows) is None:
        return
    penalty = max(ctx.param("penalty") or 0, 0)
    extra = f", plus a penalty of {penalty}" if penalty else ""
    for path, stated in held.items():
        counted = int(sum(row.get("variants", 1) for row in _ledger_at(ctx, path, rows)))
        if not _whole(stated):
            ctx.breach(f"the metrics hold {ADJUSTED} and no whole number under {COUNTED}", where=path,
                       fix=f"compute the figure with the ledger's count, {counted}{extra}, and record it as {COUNTED}")
        elif stated < counted + penalty:
            ctx.breach(f"the luck-adjusted figure used a trial count of {int(stated)}, but the ledger counts "
                       f"{counted}{extra}", where=path,
                       fix="compute the figure again with the ledger's own count; every logged trial counts")


def _ledger_at(ctx: Context, path: str, rows: list[Any]) -> list[Any]:
    """The trials the ledger held when this metrics file was last committed.

    A figure is adjusted for the trials that were logged when it was computed, and a trial logged
    later does not make it wrong. A metrics file that is new, or that changed since its last commit,
    is being written now, so it answers to the whole ledger. A trial counts for the variants its
    record states today.
    """
    commit = (ctx.git.run("log", "-1", "--format=%H", "--", path) or "").strip()
    if not commit or path in ctx.git.dirty():
        return rows
    held = set((ctx.git.run("ls-tree", "-r", "-z", "--name-only", commit) or "").split("\0"))
    return [row for row in rows if row.path in held]


def _adjusted(world: World, counted: Any = 4, ledger: tuple[Any, ...] = (3, None), extra: str = "",
              later: int = 0, edited: bool = False, since: str | None = None) -> None:
    """A study whose metrics hold a luck-adjusted figure and its count, and a ledger of three variants and one.

    `later` commits the study, then logs that many more trials. `edited` then changes the metrics file.
    With `since`, the study is sealed and merged on the main line first, the rule binds from that date,
    and a second study, sealed later, holds a figure that used the ledger's count.
    """
    if since:
        extra += f'\n    [rules."trials/count-feeds-adjustment"]\n    since = "{since}"\n'
        world.manifest(SETUP + extra)
        world.write("work/a/PRE-REG.md", "---\nkind: strategy\n---\n")
        world.commit("the seal")
        world.write("work/b/results/metrics.json", json.dumps({ADJUSTED: 0.7, COUNTED: 4}))
    world.manifest(SETUP + extra)
    for name, variants in zip("ab", ledger):
        world.write(f"ledger/{name}.toml", _table({"work": f"work/{name}", "variants": variants}))
    world.write("work/a/results/metrics.json", json.dumps({ADJUSTED: 0.8} | ({COUNTED: counted} if counted else {})))
    if later:
        world.commit("the study, and the ledger as it stood")
        for number in range(later):
            world.write(f"ledger/later-{number}.toml", _table({"work": "work/c"}))
        world.commit("trials logged after the figure")
    if edited:
        world.write("work/a/results/metrics.json", json.dumps({ADJUSTED: 0.9, COUNTED: counted}))


_prove("trials/count-feeds-adjustment", _adjusted, [
    ("the figure used the ledger's count", "pass", None, {}),
    ("a count above the ledger's is not a breach", "pass", None, {"counted": 9}),
    ("metrics with no luck-adjusted figure need no count", "pass", None,
     {"files": {"work/b/results/metrics.json": '{"net_return": 0.12}\n'}}),
    ("a figure that counted only its own study", "fail", "a trial count of 3, but the ledger counts 4", {"counted": 3}),
    ("a figure with no count beside it", "fail", "no whole number under trials_counted", {"counted": None}),
    ("the ledger's count, short of the project's penalty", "fail", "the ledger counts 4, plus a penalty of 2",
     {"extra": '\n    [rules."trials/count-feeds-adjustment"]\n    penalty = 2\n'}),
    ("an empty ledger cannot be counted", "refuse", "the ledger holds no trial", {"ledger": ()}),
    ("a trial logged after the figure was committed does not make it wrong", "pass", None, {"later": 3}),
    ("a committed figure still answers to the ledger of its day", "fail", "a trial count of 3, but the ledger counts 4",
     {"counted": 3, "later": 3}),
    ("a figure computed again answers to the whole ledger", "fail", "a trial count of 4, but the ledger counts 7",
     {"later": 3, "edited": True}),
    ("a study sealed before the rule's start date is left alone", "pass", None, {"counted": 3, "since": "2027-01-01"}),
    ("a study sealed on the rule's start date is held to it", "fail", "a trial count of 3, but the ledger counts 4",
     {"counted": 3, "since": "2026-01-01"}),
])


# -- prereg/declared ----------------------------------------------------------------------------


@rule("prereg/declared", "The seal names its kind, its binding clause, its gate, its nulls, its windows and the "
      "smallest effect worth seeing.", pack="trading",
      learned="A plan was sealed with no bar in it, and the bar was chosen after the results were in.")
def declared(ctx: Context) -> None:
    windows = _all_windows(ctx)
    for unit, files in sorted(units.studies(ctx).items()):
        found = units.seal(ctx, unit, files)
        if found is None:
            continue  # not sealed yet, or a seal that cannot be read, which is refused
        ctx.inspect()
        path, plan = found
        kind = plan.get("kind")
        if not isinstance(kind, str) or kind not in NEEDS:
            said = "names no kind" if kind is None else f"names the kind {kind!r}"
            ctx.breach(f"the seal {said}; a kind is strategy, signal, data, tune or forward", where=path, fix=SEAL_FIX)
            continue
        for fault in unstated(plan, NEEDS[kind], f"seal of this {kind} study"):
            ctx.breach(fault, where=path, fix=SEAL_FIX)
        for fault in forward.seal_problems(plan) if kind == forward.KIND else ():
            ctx.breach(fault, where=path, fix=SEAL_FIX)  # its lines, risk lines and ranges, each an inline table
        named = plan.get("windows") if "windows" in NEEDS[kind] else None
        for name in named if isinstance(named, list) else []:
            if str(name) not in windows.of(unit):
                ctx.breach(f"the seal names the window {name}, which the manifest does not declare and this "
                           "study does not either", where=path,
                           fix=f"declare it under [trading.windows], or give the study its own: "
                               f"{data.PREFIX}{name}: {{from = \"...\", to = \"...\"}} in the seal")
    for where, _, problem in windows.problems:  # a window declared two ways, or one that cannot be read
        ctx.inspect()
        ctx.breach(problem, where=where, fix="declare each window id once, the same way wherever it is declared; "
                                             "a window with other dates takes an id of its own")


def _sealed(world: World, file: str = "PRE-REG.md", fence: str = "---", extra: str = "", **changes: Any) -> None:
    """A study whose seal states all a strategy needs, apart from the changes. None leaves a field out."""
    fields = {"kind": "strategy", "binding": "the net figure beats the shuffled null in the test window",
              "gate": "direction", "nulls": "[shuffled, always-long, always-short]", "windows": "[train, holdout]",
              "mde": 0.2, **changes}
    lines = [f"{key}: {value}" for key, value in fields.items() if value is not None]
    world.manifest(SETUP + extra)
    world.write(f"work/a/{file}", "\n".join([fence, *lines, fence, "", "The plan, in words.", ""]))


BARE = {"binding": None, "gate": None, "nulls": None, "windows": None, "mde": None}
TUNE = {"kind": "tune", "binding": None, "nulls": None, "mde": None, "iterations": 50, "risk_rules": "rules/risk.json"}
OOS = '{from = "2025-01-01", to = "2025-12-31", sealed = true}'  # a study's own sealed window, shared by its siblings
OWN = {**TUNE, "windows": "[train, oos]", "window-oos": OOS}


def _sibling(window: str = OOS, study: str = "work/b", name: str = "oos") -> dict[str, str]:
    """The seal of a sibling study that declares its own window, oos unless named, as given."""
    return {f"{study}/PRE-REG.md": f"---\nkind: tune\nwindows: [train, {name}]\nwindow-{name}: {window}\n"
                                    "gate: tune\niterations: 9\nrisk_rules: r.json\n---\n"}


STUDY_TABLE = """
    [trading.studies."work/a".windows.oos]
    from = "2025-01-01"
    to = "2025-12-31"
    sealed = true
"""
_prove("prereg/declared", _sealed, [
    ("a strategy seal that states its whole plan", "pass", None, {}),
    ("a data study states its kind and nothing more", "pass", None, {"kind": "data", **BARE}),
    ("a tune seal with its windows, gate, budget and risk rules", "pass", None, TUNE),
    ("a seal that names no kind", "fail", "names no kind", {"kind": None}),
    ("a kind that is not one of the five", "fail", "names the kind 'backtest'", {"kind": "backtest"}),
    ("a strategy seal with no binding clause", "fail", "does not state binding", {"binding": None}),
    ("a signal seal with no gate", "fail", "this signal study does not state gate", {"kind": "signal", "gate": None}),
    ("a list of nulls that is empty", "fail", "nulls in the seal of this strategy study must be", {"nulls": "[]"}),
    ("a window the manifest does not declare", "fail", "names the window live, which", {"windows": "[train, live]"}),
    ("a smallest effect of zero", "fail", "mde in the seal of this strategy study must be", {"mde": 0}),
    ("a tune seal with no iteration budget", "fail", "does not state iterations", {**TUNE, "iterations": None}),
    ("a tune budget of two and a half", "fail", "study must be a whole number above 0", {**TUNE, "iterations": 2.5}),
    ("a tune seal that declares its own windows", "pass", None,
     {**OWN, "windows": "[is-2019, oos]", "window-is-2019": "{from = 2019-01-01, to = 2023-12-31}"}),
    ("a study table in the manifest gives the study its own window", "pass", None,
     {**TUNE, "windows": "[train, oos]", "extra": STUDY_TABLE}),
    ("sibling studies declare one window the same way", "pass", None, {**OWN, "files": _sibling()}),
    ("a study gives a window of the project's other dates", "fail", "one window id names one window",
     {**OWN, "window-holdout": '{from = "2023-01-01", to = "2024-12-31", sealed = true}'}),
    ("a sibling declares a shared window with other dates", "fail", "as 2025-01-01 to 2025-12-31, sealed",
     {**OWN, "files": _sibling('{from = "2025-02-01", to = "2025-12-31", sealed = true}')}),
    ("a study table and the seal declare one window two ways", "fail", "one window id names one window",
     {**OWN, "window-oos": '{from = "2025-01-01", to = "2025-12-31"}', "extra": STUDY_TABLE}),
    ("a window in the seal that is not an inline table", "fail", "window-oos must be an inline table",
     {**OWN, "window-oos": "2025-01-01 to 2025-12-31"}),
    ("a window in the seal with no end date", "fail", "window-oos.to is required",
     {**OWN, "window-oos": '{from = "2025-01-01", sealed = true}'}),
    ("a window only a sibling study declares", "fail", "this study does not either",
     {**TUNE, "windows": "[train, oos]", "files": _sibling()}),
    ("a seal with no frontmatter block", "refuse", "no frontmatter block", {"fence": ""}),
    ("no study is sealed yet", "refuse", "nothing was inspected", {"file": "notes.md"}),
])

#: A forward seal that states its whole plan: its settings, its count, its lines, its risk lines and its ranges.
FORWARD = {
    **BARE, "kind": "forward", "gate": "forward", "settings": "3f9a0c1d", "min_trades": 220,
    "stop_rule": "the owner stops it; a restart is a new run, sealed anew", "lines": "[match, unexplained, entry-cost]",
    "line-match": '{worse = "lower", pass = 0.9, stop = 0.8, running = 2}',
    "line-unexplained": '{worse = "higher", pass = 50, stop = 200}',
    "line-entry-cost": '{worse = "higher", pass = 0.43, stop = 0.86, min = 30}',
    "risk": "[day-loss]", "line-day-loss": '{worse = "higher", stop = 0.52}',
    "ranges": "[30, 61]", "range-30": "{low = 9500, high = 12500}", "range-61": "{low = 9000, high = 15000}",
    "gap_parts": "[spread, commission, swap]", "reasons": "[news pause, server restart]",
    "changes_allowed": "[spread]", "changes_stop": "[leverage]",
}
_prove("prereg/declared", _sealed, [
    ("a forward seal with its settings, its count, its lines, its risk lines and its ranges", "pass", None, FORWARD),
    ("a forward seal with no lists of changes, and no risk line or range", "pass", None,
     {**FORWARD, "changes_allowed": None, "changes_stop": None, "risk": "[]", "line-day-loss": None, "ranges": "[]",
      "range-30": None, "range-61": None}),
    ("a forward seal with no settings", "fail", "does not state settings", {**FORWARD, "settings": None}),
    ("a count of trades written as a word", "fail", "min_trades in the seal of this forward study must be a whole",
     {**FORWARD, "min_trades": "many"}),
    ("a forward seal that names another gate", "fail", "a forward seal names the gate forward, not entry",
     {**FORWARD, "gate": "entry"}),
    ("a forward seal that draws no match line", "fail", "lines in the seal must hold match",
     {**FORWARD, "lines": "[unexplained, entry-cost]", "line-match": None}),
    ("a line with no table", "fail", "names the line entry-cost and has no line-entry-cost",
     {**FORWARD, "line-entry-cost": None}),
    ("a line whose stop is on the better side of its pass", "fail", "on the better side of its pass",
     {**FORWARD, "line-match": '{worse = "lower", pass = 0.8, stop = 0.9}'}),
    ("a match line read the wrong way round", "fail", "line-match.worse must be lower",
     {**FORWARD, "line-match": '{worse = "higher", pass = 0.9}'}),
    ("a line run over no weeks", "fail", "line-match.running must be a whole number, 1 or more",
     {**FORWARD, "line-match": '{worse = "lower", pass = 0.9, stop = 0.8, running = 0}'}),
    ("a risk line with a pass as well", "fail", "line-day-loss.pass is not a known key",
     {**FORWARD, "line-day-loss": '{worse = "higher", pass = 0.3, stop = 0.52}'}),
    ("a range with its low above its high", "fail", "has its low, 12500, above its high, 9500",
     {**FORWARD, "range-30": "{low = 12500, high = 9500}"}),
    ("a range day with no table", "fail", "names the day 61 in ranges and has no range-61",
     {**FORWARD, "range-61": None}),
    ("a line table for a line the seal does not name", "fail", "draws a line that neither lines nor risk names",
     {**FORWARD, "line-slippage": '{worse = "higher", pass = 1}'}),
    ("a change both allowed and a stop", "fail", "the change spread is both allowed and a stop",
     {**FORWARD, "changes_stop": "[spread, leverage]"}),
])


# -- prereg/provenance --------------------------------------------------------------------------


@rule("prereg/provenance", "Every result carries a fingerprint taken on a clean tree.", pack="trading",
      learned="A study stopped reproducing itself, and nothing said which code and data had made its numbers.")
def provenance(ctx: Context) -> None:
    for unit, files in sorted(units.studies(ctx).items()):
        if not units.has_results(unit, files):
            continue
        ctx.inspect()
        path = f"{unit}/{units.PROVENANCE}"
        if not ctx.exists(path):
            ctx.breach("this study holds results and no provenance file", where=unit, fix=RERUN)
            continue
        held = units.read_json(ctx, path)  # None is a file that cannot be read, which is refused
        for fault in unstated(held, ("commit", "clean", "inputs"), "provenance") if held is not None else []:
            ctx.breach(fault, where=path, fix=RERUN)


def _ran(world: World, file: str = "provenance.json", **changes: Any) -> None:
    """A study with a result and its provenance, apart from the changes. None leaves a field out."""
    held = {"commit": "0a1b2c3d4e5f", "clean": True, "inputs": {"data/bars.csv": "ab" * 32}, **changes}
    world.manifest(SETUP)
    world.write("work/a/results/metrics.json", '{"net_return": 0.12}\n')
    world.write(f"work/a/results/{file}", json.dumps({key: value for key, value in held.items() if value is not None}))


_prove("prereg/provenance", _ran, [
    ("a result with its commit, a clean tree and its inputs' hashes", "pass", None, {}),
    ("a sealed study with no result yet needs no fingerprint", "pass", None,
     {"files": {"work/b/PRE-REG.md": "---\nkind: data\n---\n"}}),
    ("results with no provenance file", "fail", "no provenance file", {"file": "notes.json"}),
    ("results made on a dirty tree", "fail", "a fingerprint taken on a dirty tree pins nothing", {"clean": False}),
    ("no clean-tree flag at all", "fail", "does not state clean", {"clean": None}),
    ("a commit that is a word, not a hash", "fail", "commit in the provenance must be", {"commit": "latest"}),
    ("an empty table of inputs", "fail", "inputs in the provenance must be a table", {"inputs": {}}),
    ("an input with no hash", "fail", "a sha256 of 64 hex characters", {"inputs": {"data/bars.csv": "to do"}}),
    ("a provenance file that cannot be read", "refuse", "not valid JSON",
     {"files": {"work/a/results/provenance.json": '{"commit": \n'}}),
])


# -- holdout/guarded ----------------------------------------------------------------------------


def _all_windows(ctx: Context) -> data.Windows:
    """Every data window: the project's, and those each study declares in its seal or study table."""
    return data.collect(ctx.manifest, ctx.all_files, ctx.read)


def _windows(ctx: Context) -> tuple[data.Windows, list[str]]:
    """The declared data windows, and the ids of the sealed ones. Stops the rule when none is sealed."""
    found = _all_windows(ctx)
    sealed = found.sealed()
    if not sealed:
        ctx.not_configured("mark a data window as sealed: sealed = true under [trading.windows.<name>], "
                           "or in a study's own window")
    return found, sealed


def _looks(ctx: Context) -> list[Any]:
    """The look records, oldest first."""
    return sorted(ctx.records("look"), key=lambda look: (look.get("at"), look.path))


@rule("holdout/guarded", "A window marked sealed is read only with a grant.", pack="trading",
      learned="Sealed data was read by agents whose instructions never mentioned the seal.")
def guarded(ctx: Context) -> None:
    windows, sealed = _windows(ctx)
    grants, looks = {record.id: record for record in ctx.records("grant")}, _looks(ctx)
    spent = data.first_uses(looks)  # a grant is spent by the first look that names it
    for look in looks:
        name, grant = look.get("window"), (look.get("grant") or "").strip() or None
        study = look.get("study") if isinstance(look.get("study"), str) else None
        if name in windows.of(study) and name not in sealed:
            continue  # a window that is not sealed needs no grant
        ctx.inspect()
        if name not in windows.of(study):
            whose = f" and its study {study} does not either" if study else ""
            ctx.breach(f"this look names the window {name}, which the manifest does not declare{whose}",
                       where=look.path, fix="name a window the manifest or the study declares, or declare this one")
            continue
        earlier = spent.get(grant) if spent.get(grant) != look.path else None
        targets = windows.targets(study, name)
        problem = data.grant_problem(grants, grant, targets, earlier)
        if problem:
            ctx.breach(f"this look read the sealed window {name} with no grant that opens it: {problem}",
                       where=look.path, fix=f"tell the owner the window was read; before each look the owner runs "
                                            f"`themis grant {data.ACTION} {targets[0]} --reason ...`, and the look "
                                            f"goes through `themis act {data.ACTION} {targets[0]} -- ...` or "
                                            "data.window")


GRANT = {"action": "holdout", "target": "holdout", "granted_by": "owner", "granted_at": "2026-01-01T09:00:00+00:00",
         "reason": "the plan is sealed and both test windows are done"}
TWO = {"looks": ({}, {}), "grants": ({}, {})}  # a second look, with a grant of its own
PIPELINE = {"kind": "pipeline", "scope": "the first 50 rows", "purpose": "show the loader reads the sealed files",
            "compared_against": "the row counts in the data inventory", "forward_returns": False}


SEALS = {**_sibling(study="work/a"), **_sibling()}  # two sibling studies that share the sealed window oos
AT_OOS = {"window": "oos", "study": "work/a"}


def _holdout(world: World, looks: tuple[dict[str, Any], ...] = ({},), grants: tuple[dict[str, Any], ...] = ({},),
             extra: str = "") -> None:
    """A sealed window, grants g1, g2, ... for it, and looks l1, l2, ..., a day apart. Look n is a signal
    look that names grant n. Each record is that honest one, apart from the changes given."""
    world.manifest(SETUP + extra)
    for number, changes in enumerate(grants, start=1):
        world.write(f"grants/g{number}.toml", _table({**GRANT, **changes}))
    for number, changes in enumerate(looks, start=1):
        look = {"window": "holdout", "kind": "signal", "at": f"2026-01-0{number + 1}T10:00:00+00:00",
                "grant": f"g{number}", **changes}
        world.write(f"looks/l{number}.toml", _table(look))


_prove("holdout/guarded", _holdout, [
    ("a look at a sealed window with the owner's grant for it", "pass", None, {}),
    ("a look at an open window needs no grant", "pass", None, {"looks": ({}, {"window": "train", "grant": None})}),
    ("a second look with a grant of its own", "pass", None, {**TWO, "looks": ({}, {"kind": "pipeline"})}),
    ("a sealed window read with no grant", "fail", "no grant is named", {"looks": ({"grant": None},)}),
    ("a look that names a grant nobody wrote", "fail", "no grant with the id g9", {"looks": ({"grant": "g9"},)}),
    ("a grant for another action", "fail", "for the action publish, not holdout", {"grants": ({"action": "publish"},)}),
    ("a grant for another window", "fail", "is for the target train, not holdout", {"grants": ({"target": "train"},)}),
    ("one grant used for two looks", "fail", "g1 was already used by the look", {"looks": ({}, {"grant": "g1"})}),
    ("a look at a window nobody declared", "fail", "the manifest does not declare", {"looks": ({"window": "live"},)}),
    ("a study's look at its own sealed window, with a grant for the study and the window", "pass", None,
     {"looks": (AT_OOS,), "grants": ({"target": "work/a/oos"},), "files": SEALS}),
    ("a study's look at a window of the project's, with a grant for the study and the window", "pass", None,
     {"looks": ({"study": "work/a"},), "grants": ({"target": "work/a/holdout"},)}),
    ("a grant for a sibling's look does not open this study's", "fail", "for the target work/b/oos, not work/a/oos",
     {"looks": (AT_OOS,), "grants": ({"target": "work/b/oos"},), "files": SEALS}),
    ("a grant for the window alone does not open a study's own window", "fail", "for the target oos, not work/a/oos",
     {"looks": (AT_OOS,), "grants": ({"target": "oos"},), "files": SEALS}),
    ("a look at a study's own window that names no study", "fail", "which the manifest does not declare",
     {"looks": ({"window": "oos"},), "grants": ({"target": "oos"},), "files": SEALS}),
    ("a look record that cannot be read", "refuse", "is not valid TOML", {"files": {"looks/l2.toml": 'window = "x\n'}}),
    ("nobody has looked at a sealed window yet", "refuse", "nothing was inspected", {"looks": ()}),
])


@proof("grant/required", "a project's own guarded list that keeps holdout still fails a look with no grant",
       expect="fail", contains="the guarded action holdout ran on holdout with no grant")
def _(world: World) -> None:
    """A stated list replaces the pack's default one, so a project that lists its own keeps holdout in it."""
    world.manifest(SETUP + '\n    [rules."grant/required"]\n    guarded = ["publish", "holdout"]\n')
    world.write("receipts/action/a1.json", json.dumps(
        {"kind": "action", "action": "holdout", "target": "holdout", "at": "2026-01-02T10:00:00+00:00"}))


# -- holdout/one-signal-look --------------------------------------------------------------------


@rule("holdout/one-signal-look", "Each sealed window has at most its allowed number of signal looks.", pack="trading",
      learned="Settings were tried on the unseen years again and again until they passed, and then lost.")
def one_signal_look(ctx: Context) -> None:
    windows, sealed = _windows(ctx)
    ids = windows.ids()  # a window id shared by sibling studies is one window: their looks count together
    looks = [look for look in _looks(ctx) if look.get("kind") == "signal"]
    for name in sealed:
        ctx.inspect()
        allowed = max(ids[name].get("looks", 1), 0)
        taken = [look for look in looks if look.get("window") == name]
        for number, look in enumerate(taken[allowed:], start=allowed + 1):
            ctx.breach(f"this is signal look number {number} at the sealed window {name}, which allows {allowed}",
                       where=look.path, fix="the window is no longer unseen: say so in every result that used this "
                                            "look, and seal a fresh window for the next test")


_prove("holdout/one-signal-look", _holdout, [
    ("one signal look, and a pipeline look beside it", "pass", None, {**TWO, "looks": ({}, {"kind": "pipeline"})}),
    ("a sealed window nobody has looked at", "pass", None, {"looks": ()}),
    ("two looks at a window that allows two", "pass", None, {**TWO, "extra": "    looks = 2\n"}),
    ("a signal look at a window that is not sealed is not counted", "pass", None, {"looks": ({}, {"window": "train"})}),
    ("a second signal look at a window that allows one", "fail", "signal look number 2 at the sealed window", TWO),
    ("windows of their own, one look at each", "pass", None,
     {**TWO, "looks": (AT_OOS, {"window": "oos-b", "study": "work/b"}),
      "files": {**_sibling(study="work/a"), **_sibling(name="oos-b")}}),
    ("sibling studies share a window, and their looks count together", "fail",
     "signal look number 2 at the sealed window oos",
     {"looks": (AT_OOS, {"window": "oos", "study": "work/b"}),
      "grants": ({"target": "work/a/oos"}, {"target": "work/b/oos"}), "files": SEALS}),
    ("a look whose kind is neither", "refuse", "must be one of signal, pipeline", {"looks": ({"kind": "peek"},)}),
])


# -- holdout/pipeline-look-declared -------------------------------------------------------------


@rule("holdout/pipeline-look-declared", "A look that only proves the code works states its scope, its purpose and "
      "what it was compared against, and computes no forward return.", pack="trading",
      learned="A check that the code ran on unseen data also showed how the idea would have done there.")
def pipeline_look_declared(ctx: Context) -> None:
    _windows(ctx)
    for look in _looks(ctx):
        if look.get("kind") != "pipeline":
            continue
        ctx.inspect()
        for field, what in data.DECLARED.items():
            if not _text(look.get(field)):
                ctx.breach(f"this pipeline look does not state {what}", where=look.path,
                           fix=f"add {field} to the look record, in words a reader can check")
        if look.get("forward_returns") is True:
            ctx.breach("this pipeline look computed a forward return, so it saw how the idea did on sealed data",
                       where=look.path, fix="count it as a signal look: set kind to signal, and tell the owner")


_prove("holdout/pipeline-look-declared", _holdout, [
    ("a pipeline look that states all three", "pass", None, {"looks": (PIPELINE,)}),
    ("a signal look beside it states none of them", "pass", None, {"looks": (PIPELINE, {})}),
    ("a pipeline look with no purpose", "fail", "not state its purpose", {"looks": (PIPELINE | {"purpose": None},)}),
    ("a pipeline look compared against nothing", "fail", "does not state what it was compared against",
     {"looks": (PIPELINE | {"compared_against": "  "},)}),
    ("a pipeline look that computed a forward return", "fail", "computed a forward return",
     {"looks": (PIPELINE | {"forward_returns": True},)}),
    ("no pipeline look has been taken", "refuse", "nothing was inspected", {}),
])
