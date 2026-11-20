"""Gate: forward — a live run, held week by week against a replay of the same dates.

A forward run trades live under sealed settings, and each week the same settings are replayed over
the same dates, from the same start. It is one study whose seal is of kind `forward`, and it holds
one record a week, written by the project's own script through `themis run`:

    <study>/PRE-REG.md                         the seal, merged on its own before the first live trade
    <study>/results/week-YYYY-WW.json          one record an ISO week (`WEEK` below)
    decisions/<study>-week-YYYY-WW.json        that week's decision: `themis decide <study>/week-YYYY-WW
                                               --gate forward`
    decision-inputs/<study>-week-YYYY-WW.json  what the gate read, built by `build` from the seal and the
                                               records, never typed

A bad week is a verdict from the gate: stop, look-closer, defer or pass. A rule here fails only when
the seal, a record or a stored verdict is missing or dishonest. With no study sealed as `forward`,
each rule says "not configured". The seal:

    ---
    kind: forward
    gate: forward
    settings: 3f9a0c1d                  the fingerprint the live run and every replay use
    min_trades: 220                     trades before any pass
    stop_rule: the owner stops it; a restart is a new run, sealed anew
    lines: [match, unexplained, entry-cost]
    line-match: {worse = "lower", pass = 0.90, stop = 0.80, running = 2}
    line-unexplained: {worse = "higher", pass = 50, stop = 200}
    line-entry-cost: {worse = "higher", pass = 0.43, stop = 0.86, min = 30}
    risk: [day-loss]
    line-day-loss: {worse = "higher", stop = 0.52}
    ranges: [30, 61]
    range-30: {low = 9500, high = 12500}
    range-61: {low = 9000, high = 15000}
    gap_parts: [spread, commission, swap]
    reasons: [news pause, server restart]
    changes_allowed: [spread]
    changes_stop: [leverage]
    ---

`match` and `unexplained` are lines every forward seal draws, and Themis computes them from the
records; the other lines are the project's own. A line has a `pass` and, optionally, a `stop`, on
the side its `worse` names; between the two is "look closer". `running` is how many weeks in a row
a line must be past its stop before it stops that week (1 when unset), and `min` the least sample
it is read on (0 when unset); a line on no sample is never judged. A risk line has only a `stop`,
and once passed it stops every week after. A range is the live money on a day since
the start, `{low, high}`.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from themis import records, schema, work
from themis.gitlog import Git
from themis.grants import find_grant, to_toml
from themis.packs.trading import data, units
from themis.packs.trading.pack import pack
from themis.packs.trading.validity import _basis
from themis.rule import Context, Param, proof, rule
from themis.schema import ANY, Choice, Required

if TYPE_CHECKING:
    from themis.proofs import World

KIND = GATE = ACTION = "forward"  # the kind of study, the gate that decides its weeks, the grant's action
OWN = ("match", "unexplained")  # the lines Themis computes from the records
LINE, RANGE = "line-", "range-"  # a seal's keys that hold one line, or one range
ID = re.compile(r"^[A-Za-z0-9_-]+$")
#: One line of the seal, one risk line, and one range, each written as an inline table.
LINE_TABLE = {"worse": Required(Choice("higher", "lower")), "pass": Required(float), "stop": float, "running": int,
              "min": int}
RISK_TABLE = {"worse": Required(Choice("higher", "lower")), "stop": Required(float)}
RANGE_TABLE = {"low": Required(float), "high": Required(float)}
EXAMPLES = {"line": '{worse = "lower", pass = 0.9, stop = 0.8}', "risk line": '{worse = "higher", stop = 0.5}',
            "range": "{low = 9000, high = 12000}"}
WORSE = {"match": "lower", "unexplained": "higher"}  # a share falls, a remainder grows


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _whole(value: Any, least: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= least


def _inline(key: str, value: Any, spec: dict[str, Any], what: str) -> tuple[dict[str, Any] | None, list[str]]:
    """One of the seal's inline tables, read and checked against its spec; or what is wrong with it."""
    text = value.strip() if isinstance(value, str) else ""
    if not (text.startswith("{") and text.endswith("}")):
        return None, [f"the seal's {key} must be an inline table, such as {EXAMPLES[what]}"]
    try:
        table = tomllib.loads(f"table = {text}")["table"]
    except tomllib.TOMLDecodeError as error:
        return None, [f"the seal's {key} cannot be read as an inline table ({error})"]
    wrong = schema.problems(table, spec, f"the seal's {key}")
    wrong += [f"the seal's {key}.{name} must be a finite number" for name, item in table.items()
              if isinstance(item, float) and not math.isfinite(item)]
    return (None, wrong) if wrong else (table, [])


def _ids(plan: dict[str, Any], field: str, problems: list[str]) -> list[str]:
    """The ids a list field of the seal names, in order. A field that is missing or is not a list is
    left to the check of the seal's fields."""
    value, found = plan.get(field), []
    for index, item in enumerate(value if isinstance(value, list) else []):
        if not isinstance(item, str) or not ID.match(item):
            problems.append(f"{field}[{index}] in the seal must be an id of letters, digits, - and _")
        elif item in found:
            problems.append(f"{field} in the seal names {item} twice")
        else:
            found.append(item)
    return found


def _texts(plan: dict[str, Any], field: str, problems: list[str], optional: bool = False) -> list[str]:
    """The words a list field of the seal holds: each one text, none twice."""
    value, found = plan.get(field), []
    if optional and field in plan and not isinstance(value, list):
        problems.append(f"{field} in the seal must be a list, such as [spread]")
    for index, item in enumerate(value if isinstance(value, list) else []):
        if not isinstance(item, str) or not item.strip():
            problems.append(f"{field}[{index}] in the seal must be text")
        elif item in found:
            problems.append(f"{field} in the seal names {item} twice")
        else:
            found.append(item)
    return found


def _past(value: float, bound: float, worse: str) -> bool:
    """True when the value lies beyond the bound, on the side its `worse` names."""
    return value > bound if worse == "higher" else value < bound


def _line(name: str, key: str, table: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """A line as the gate reads it, with its defaults; and what is wrong with it."""
    worse, passed, stop = table["worse"], float(table["pass"]), table.get("stop")
    line = {"worse": worse, "pass": passed, "running": table.get("running", 1), "min": table.get("min", 0)}
    if stop is not None:
        line["stop"] = float(stop)
    problems = []
    if stop is not None and _past(passed, float(stop), worse):
        problems.append(f"the seal's {key} puts its stop, {stop:g}, on the better side of its pass, {passed:g}: "
                        f"a stop lies past the pass, on the {worse} side")
    if not _whole(line["running"], 1):
        problems.append(f"the seal's {key}.running must be a whole number, 1 or more: the weeks in a row")
    if not _whole(line["min"], 0):
        problems.append(f"the seal's {key}.min must be a whole number, 0 or more: the least sample")
    if name in WORSE and worse != WORSE[name]:
        problems.append(f"the seal's {key}.worse must be {WORSE[name]}: Themis computes {name}, and a "
                        f"{'share' if name == 'match' else 'remainder'} is worse when it is {WORSE[name]}")
    if name == "match" and not all(0 <= value <= 1 for value in (passed, *([float(stop)] if stop is not None else []))):
        problems.append(f"the seal's {key} reads a share, so its pass and its stop lie between 0 and 1")
    if name == "unexplained" and passed < 0:
        problems.append(f"the seal's {key} reads the size of a remainder, so its pass is 0 or more")
    return line, problems


@dataclass(frozen=True)
class Seal:
    """A forward run's seal, read in full."""

    path: str
    settings: str
    min_trades: int
    stop_rule: str
    lines: dict[str, dict[str, Any]]  # id -> {worse, pass, running, min, and stop when it has one}
    risk: dict[str, dict[str, Any]]  # id -> {worse, stop}
    ranges: dict[str, dict[str, float]]  # the day, as text -> {low, high}
    gap_parts: tuple[str, ...]
    reasons: tuple[str, ...]
    changes_allowed: tuple[str, ...]
    changes_stop: tuple[str, ...]

    def table(self) -> dict[str, Any]:
        """What the gate reads of the seal."""
        return {"settings": self.settings, "min_trades": self.min_trades, "lines": self.lines, "risk": self.risk,
                "ranges": self.ranges, "reasons": list(self.reasons), "changes_allowed": list(self.changes_allowed),
                "changes_stop": list(self.changes_stop)}


def parse(plan: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The tables of a forward seal, and what is wrong with them: its lines, its risk lines, its
    ranges and its lists. A field that is missing, or of the wrong shape, is left to the check of the
    seal's fields (`process.NEEDS`), so it is said once."""
    problems: list[str] = []
    gate = plan.get("gate")
    if isinstance(gate, str) and gate.strip() and gate != GATE:
        problems.append(f"a forward seal names the gate {GATE}, not {gate}")
    names, risky = _ids(plan, "lines", problems), _ids(plan, "risk", problems)
    if isinstance(plan.get("lines"), list):
        problems += [f"lines in the seal must hold {name}: Themis computes it from the records" for name in OWN
                     if name not in names]
    problems += [f"the seal names {name} both as a line and as a risk line; give each its own id"
                 for name in names if name in risky]
    lines, risk, ranges = {}, {}, {}
    for name in names:
        key = LINE + name
        if key not in plan:
            problems.append(f"the seal names the line {name} and has no {key}, such as {EXAMPLES['line']}")
            continue
        table, wrong = _inline(key, plan[key], LINE_TABLE, "line")
        problems += wrong
        if table is not None:
            lines[name], wrong = _line(name, key, table)
            problems += wrong
    for name in (name for name in risky if name not in names):
        key = LINE + name
        if key not in plan:
            problems.append(f"the seal names the risk line {name} and has no {key}, such as {EXAMPLES['risk line']}")
            continue
        table, wrong = _inline(key, plan[key], RISK_TABLE, "risk line")
        problems += wrong
        if table is not None:
            risk[name] = {"worse": table["worse"], "stop": float(table["stop"])}
    days = plan.get("ranges")
    for index, day in enumerate(days if isinstance(days, list) else []):
        key = f"{RANGE}{day}"
        if not _whole(day, 1):
            problems.append(f"ranges[{index}] in the seal must be a whole number of days since the start, 1 or more")
        elif str(day) in ranges:
            problems.append(f"ranges in the seal names the day {day} twice")
        elif key not in plan:
            problems.append(f"the seal names the day {day} in ranges and has no {key}, such as {EXAMPLES['range']}")
        else:
            table, wrong = _inline(key, plan[key], RANGE_TABLE, "range")
            problems += wrong
            if table is not None and table["low"] > table["high"]:
                problems.append(f"the seal's {key} has its low, {table['low']:g}, above its high, {table['high']:g}")
            elif table is not None:
                ranges[str(day)] = {"low": float(table["low"]), "high": float(table["high"])}
    named_days = [str(day) for day in (days if isinstance(days, list) else []) if _whole(day, 1)]
    for key in sorted(plan):
        if key.startswith(LINE) and key[len(LINE):] not in (*names, *risky):
            problems.append(f"the seal's {key} draws a line that neither lines nor risk names")
        if key.startswith(RANGE) and key[len(RANGE):] not in named_days:
            problems.append(f"the seal's {key} draws a range for a day that ranges does not name")
    parts, reasons = _texts(plan, "gap_parts", problems), _texts(plan, "reasons", problems)
    allowed = _texts(plan, "changes_allowed", problems, optional=True)
    stopping = _texts(plan, "changes_stop", problems, optional=True)
    problems += [f"the change {what} is both allowed and a stop in the seal" for what in allowed if what in stopping]
    held = {"lines": lines, "risk": risk, "ranges": ranges, "gap_parts": tuple(parts), "reasons": tuple(reasons),
            "changes_allowed": tuple(allowed), "changes_stop": tuple(stopping)}
    return held, problems


def seal_problems(plan: dict[str, Any]) -> list[str]:
    """What is wrong with a forward seal's tables, for `prereg/declared`."""
    return parse(plan)[1]


def read_seal(path: str, plan: dict[str, Any]) -> tuple[Seal | None, list[str]]:
    """A forward seal, read in full; or every way it falls short, its fields included."""
    from themis.packs.trading import process  # it reads this module's tables for prereg/declared

    problems = process.unstated(plan, process.NEEDS[KIND], f"seal of this {KIND} study")
    held, wrong = parse(plan)
    problems += wrong
    if plan.get("kind") != KIND:
        problems.append(f"the seal's kind is {plan.get('kind')!r}, not {KIND}")
    if problems:
        return None, problems
    return Seal(path=path, settings=plan["settings"], min_trades=plan["min_trades"], stop_rule=plan["stop_rule"],
                **held), []


# -- the weekly record --------------------------------------------------------------------------

WEEK_FILE = re.compile(r"^week-([0-9]{4})-([0-9]{2})\.json$")  # ASCII digits only: one name for one week
LONGEST = dt.timedelta(days=8)  # a week's period, at most: a broker's clock and a change of clocks fit in it
RECORDS = "results/week-*.json"  # inside the study
TIME = "2026-11-23T00:00:00+00:00"  # every time in a record is written so: with its UTC offset
PERIOD = {"from": Required(str), "to": Required(str)}
START = {"at": Required(str), "balance": Required(float), "open_positions": Required(int), "peak": Required(float)}
LIVE = {"run": Required(str), "settings": Required(str), "start": Required(START), "trades": Required(int),
        "net": Required(float), "first_trade_at": Required(str), "*": ANY}
REPLAY = {"run": Required(str), "settings": Required(str), "period": Required(PERIOD), "start": Required(START),
          "trades": Required(int), "net": Required(float), "*": ANY}
MATCHED = {"id": Required(str), "live_at": Required(str), "replay_at": Required(str)}
UNPAIRED = {"id": Required(str), "at": Required(str), "reason": Required(str)}
CHANGE = {"at": Required(str), "what": Required(str), "from": Required(ANY), "to": Required(ANY)}
LINE_VALUE = {"value": Required(ANY), "n": Required(int)}  # value: a number, or null with n 0 (`_line_values`)
#: The weekly record, `<study>/results/week-YYYY-WW.json`. Every key is required, and a list or a table
#: may be empty. `live` and `replay` may hold further fingerprint fields, for forward/same-dates-control.
WEEK = {
    "week": Required(str),  # its ISO week, YYYY-WW, as its file is named
    "period": Required(PERIOD),  # from the moment the week starts to the moment the next one does
    "live": Required(LIVE),
    "replay": Required(ANY),  # REPLAY; or null for a week with no replay, which forward/same-dates-control fails
    "entries": Required({"matched": Required([MATCHED]), "missed": Required([UNPAIRED]),
                         "extra": Required([UNPAIRED])}),
    "fill_costs": Required({"*": {"n": Required(int), "live": Required(float), "replay": Required(float)}}),
    "gap": Required({"parts": Required({"*": float}), "unexplained": Required(float)}),
    "lines": Required({"*": LINE_VALUE}),  # a value, or null when n is 0: a line read on no sample
    "conditions": Required({"changes": Required([CHANGE])}),
    "risk": Required({"*": float}),
    "range": Required({"*": float}),
}
COUNTS = ("live.trades", "live.start.open_positions", "replay.trades", "replay.start.open_positions")
READ_FIX = ("write the record as the trading pack's page says (section 3), every time with its UTC offset; a seal "
            "already merged changes only through an amendment record")


def moment(value: Any) -> dt.datetime | None:
    """A time with its UTC offset, read; None for anything else, a time with no offset among them."""
    if not isinstance(value, str):
        return None
    try:
        found = dt.datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return found if found.utcoffset() is not None else None


def _shown(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat()


def _unfinite(value: Any, where: str) -> list[str]:
    """Each number that is not finite, by where it is: JSON can carry NaN, and a whole number too large
    for a float, and no line reads either."""
    if isinstance(value, float) and not math.isfinite(value):
        return [f"{where} must be a finite number"]
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > sys.float_info.max:
        return [f"{where} must be a finite number"]
    if isinstance(value, dict):
        return [problem for key, item in value.items() for problem in _unfinite(item, f"{where}.{key}")]
    if isinstance(value, list):
        return [problem for index, item in enumerate(value) for problem in _unfinite(item, f"{where}[{index}]")]
    return []


def _line_values(lines: dict[str, Any], where: str) -> list[str]:
    """What is wrong with the values of a week's own lines: each a number, or null when its n is 0. A
    line read on no sample has no value to judge."""
    found = []
    for name, held in lines.items():
        value = held["value"]
        if value is None and held["n"] != 0:
            found.append(f"{where}.{name}.value is null, and its n is {held['n']}: only a line read on no sample "
                         "has no value")
        elif value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            found.append(f"{where}.{name}.value must be a number, or null when its n is 0")
    return found


def _get(record: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        record = record.get(part) if isinstance(record, dict) else None
    return record


def _key(name: str) -> tuple[int, int]:
    year, number = name.split("-")
    return int(year), int(number)


def _name(key: tuple[int, int]) -> str:
    return f"{key[0]}-{key[1]:02d}"


def _next(key: tuple[int, int]) -> tuple[int, int]:
    """The ISO week after this one."""
    year, number, _ = (dt.date.fromisocalendar(*key, 1) + dt.timedelta(days=7)).isocalendar()
    return year, number


@dataclass
class Week:
    """One weekly record, read and checked against `WEEK`."""

    name: str  # its ISO week, such as 2026-48
    path: str
    record: dict[str, Any]

    @property
    def key(self) -> tuple[int, int]:
        return _key(self.name)

    def subject(self, study: str) -> str:
        """What its decision names: `<study>/week-YYYY-WW`."""
        return f"{study}/week-{self.name}"

    @property
    def period(self) -> tuple[dt.datetime, dt.datetime]:
        held = self.record["period"]
        return moment(held["from"]), moment(held["to"])  # type: ignore[return-value]

    @property
    def replay(self) -> dict[str, Any] | None:
        return self.record["replay"] or None


def _times(record: dict[str, Any]) -> list[tuple[str, Any]]:
    """Every time the record holds, each with where it is."""
    live, replay, entries = record["live"], record["replay"] or {}, record["entries"]
    found = [("period.from", record["period"]["from"]), ("period.to", record["period"]["to"]),
             ("live.start.at", live["start"]["at"])]
    if live["first_trade_at"].strip():
        found.append(("live.first_trade_at", live["first_trade_at"]))
    if replay:
        found += [("replay.period.from", replay["period"]["from"]), ("replay.period.to", replay["period"]["to"]),
                  ("replay.start.at", replay["start"]["at"])]
    for index, entry in enumerate(entries["matched"]):
        found += [(f"entries.matched[{index}].live_at", entry["live_at"]),
                  (f"entries.matched[{index}].replay_at", entry["replay_at"])]
    for kind in ("missed", "extra"):
        found += [(f"entries.{kind}[{index}].at", entry["at"]) for index, entry in enumerate(entries[kind])]
    found += [(f"conditions.changes[{index}].at", change["at"])
              for index, change in enumerate(record["conditions"]["changes"])]
    return found


def read_week(path: str, text: str | None) -> tuple[Week | None, list[str]]:
    """A weekly record, read and checked; or every way it cannot be read. A record that cannot be
    read decides nothing, so every forward rule refuses it."""
    named = WEEK_FILE.match(path.rsplit("/", 1)[-1])
    if not named:
        return None, ["a weekly record is named by its ISO week, week-YYYY-WW.json, such as week-2026-48.json"]
    year, number = int(named[1]), int(named[2])
    try:
        dt.date.fromisocalendar(year, number, 1)
    except ValueError:
        return None, [f"{year} has no ISO week {number}"]
    if text is None:
        return None, ["the record cannot be read as text"]
    try:
        record = json.loads(text)
    except json.JSONDecodeError as error:
        return None, [f"the record is not valid JSON ({error})"]
    if not isinstance(record, dict):
        return None, ["the record is not a JSON object"]
    problems = schema.problems(record, WEEK, "the record")
    if not problems and record["replay"] not in (None, {}):
        problems += schema.problems(record["replay"], REPLAY, "the record's replay")
    problems += _unfinite(record, "the record") + ([] if problems else _line_values(record["lines"], "the record.lines"))
    if problems:
        return None, problems
    name, live = _name((year, number)), record["live"]
    if record["week"] != name:
        problems.append(f"the record's week is {record['week']}, and its file is named for week {name}")
    problems += [f"the record's {where}, {value!r}, is not a time with its UTC offset, such as {TIME}"
                 for where, value in _times(record) if moment(value) is None]
    problems += [f"the record's {where} is {_get(record, where)}: a count is 0 or more" for where in COUNTS
                 if (_get(record, where) or 0) < 0]
    problems += [f"the record's {where}.{key}.n is {item['n']}: a count is 0 or more"
                 for where in ("fill_costs", "lines") for key, item in record[where].items() if item["n"] < 0]
    if live["trades"] and not live["first_trade_at"].strip():
        problems.append("the record's live.first_trade_at is empty, and the live week holds trades")
    entries = record["entries"]
    taken = len(entries["matched"]) + len(entries["extra"])
    if live["trades"] != taken:
        problems.append(f"the record's live.trades is {live['trades']}, and its entries hold {taken} live entries: "
                        "each live trade is a matched entry or an extra one")
    problems += [f"the record's lines holds {own}, which Themis computes from the record itself; leave it out"
                 for own in OWN if own in record["lines"]]
    if problems:
        return None, problems
    week = Week(name, path, record)
    for where, held in (("period", record["period"]), ("replay.period", (week.replay or {}).get("period"))):
        if held is not None and not moment(held["from"]) < moment(held["to"]):
            problems.append(f"the record's {where} does not end after it starts")
    problems = problems or _placed(week, (year, number))
    return (None, problems) if problems else (week, [])


def _placed(week: Week, key: tuple[int, int]) -> list[str]:
    """What is wrong with where the record sits in time. Its period lies in the ISO week its file names,
    read by its middle in UTC, so a short first week, a broker's clock hours off UTC and a change of
    clocks all fit, and it runs for 8 days at most. Each live entry, missed entry and change lies in
    the period; a matched entry's replay time may fall just over its edge."""
    begun, ended = week.period
    shown = f"{_shown(begun)} to {_shown(ended)}"
    if ended - begun > LONGEST:
        return [f"the record's period, {shown}, runs for {(ended - begun) / dt.timedelta(days=1):g} days, and a "
                f"week's runs for {LONGEST.days} at most"]
    middle = (begun + (ended - begun) / 2).astimezone(dt.timezone.utc)
    held = middle.isocalendar()[:2]
    if held != key:
        return [f"the record's period, {shown}, does not lie in ISO week {_name(key)}: its middle falls in week "
                f"{_name(held)}"]
    entries, inside = week.record["entries"], []
    inside += [(f"entries.matched[{index}].live_at", entry["live_at"]) for index, entry in enumerate(entries["matched"])]
    for kind in ("missed", "extra"):
        inside += [(f"entries.{kind}[{index}].at", entry["at"]) for index, entry in enumerate(entries[kind])]
    inside += [(f"conditions.changes[{index}].at", change["at"])
               for index, change in enumerate(week.record["conditions"]["changes"])]
    return [f"the record's {where}, {value}, lies outside its period, {shown}" for where, value in inside
            if not begun <= moment(value) < ended]


@dataclass
class Run:
    """A forward run: its seal, its weekly records oldest first, and what could not be read."""

    study: str
    seal: Seal | None = None
    weeks: list[Week] = field(default_factory=list)
    problems: list[tuple[str, str]] = field(default_factory=list)  # (where, what is wrong)

    def upto(self, name: str) -> list[Week]:
        """The weeks of the run up to this one, this one included."""
        return [week for week in self.weeks if week.key <= _key(name)]


def _seal_of(read: Callable[[str], str | None], unit: str,
             files: list[str]) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """A study's seal, its frontmatter, and why the frontmatter cannot be read when it cannot."""
    seals = work.inside(unit, files, units.SEAL)
    if not seals:
        return None, None, None
    try:
        plan = records.frontmatter(read(seals[0]) or "")
    except ValueError as error:
        return seals[0], None, str(error)
    return seals[0], plan, None if plan is not None else "it has no block between two --- lines"


def is_forward(read: Callable[[str], str | None], unit: str, files: list[str]) -> bool:
    """True for a study sealed as kind forward; and for one whose seal cannot be read while it holds
    weekly records, so a seal that breaks after a week was recorded is refused, not passed over."""
    path, plan, _ = _seal_of(read, unit, files)
    if plan is not None:
        return plan.get("kind") == KIND
    return path is not None and bool(work.inside(unit, files, [RECORDS]))


def sealed(manifest: Any, files: list[str], read: Callable[[str], str | None]) -> dict[str, list[str]]:
    """Each forward run (`is_forward`), with its files."""
    return {unit: inside for unit, inside in sorted(data.studies(manifest, files).items())
            if is_forward(read, unit, inside)}


def read_run(study: str, files: list[str], read: Callable[[str], str | None]) -> Run:
    """A forward run, read from its seal and its weekly records."""
    run = Run(study)
    path, plan, error = _seal_of(read, study, files)
    if path is None or plan is None:
        run.problems.append((path or study, f"the forward run's seal cannot be read: {error or 'there is none'}"))
    else:
        run.seal, wrong = read_seal(path, plan)
        run.problems += [(path, f"the seal cannot be read as a forward seal: {problem}") for problem in wrong]
    for name in work.inside(study, files, [RECORDS]):
        week, wrong = read_week(name, read(name))
        run.problems += [(name, problem) for problem in wrong]
        if week is not None:
            run.weeks.append(week)
    run.weeks.sort(key=lambda week: week.key)
    return run


# -- what the gate reads, built from the seal and the records -----------------------------------


def _subject(subject: str) -> tuple[str, str]:
    """The study and the week a decision names: `<study>/week-YYYY-WW`."""
    study, _, last = str(subject).strip("/").rpartition("/")
    named = re.fullmatch(r"week-([0-9]{4})-([0-9]{2})", last)
    if not study or not named:
        raise ValueError(f"the gate {GATE} decides one week of a forward run, named <study>/week-YYYY-WW, not {subject}")
    return study, f"{named[1]}-{named[2]}"


def _due(seal: Seal, start: dt.datetime, week: Week) -> list[str]:
    """The sealed range days that fall in this week: day N is N days after the run's first week began."""
    begun, ended = week.period
    return [day for day in seal.ranges if begun <= start + dt.timedelta(days=int(day)) < ended]


def _inputs_of(seal: Seal, start: dt.datetime, week: Week) -> dict[str, Any]:
    record = week.record
    live, entries, due = record["live"], record["entries"], _due(seal, start, week)
    return {
        "week": week.name, "settings": live["settings"], "trades": live["trades"],
        "matched": len(entries["matched"]), "missed": len(entries["missed"]), "extra": len(entries["extra"]),
        "reasons": [entry["reason"] for kind in ("missed", "extra") for entry in entries[kind]],
        "lines": {name: record["lines"][name] for name in seal.lines if name not in OWN and name in record["lines"]},
        # Themis's own remainder: live less replay money, less the sealed parts. A part the seal does not
        # name takes up nothing, and the record's own `unexplained` is held to it by forward/gap-explained.
        "unexplained": live["net"] - week.replay["net"] - math.fsum(  # type: ignore[index]
            record["gap"]["parts"].get(part, 0.0) for part in seal.gap_parts),
        "changes": record["conditions"]["changes"],
        "risk": {name: record["risk"][name] for name in seal.risk if name in record["risk"]},
        "range": {day: record["range"][day] for day in due if day in record["range"]},
        "range_due": due,
    }


def build(root: Path, manifest: Any, subject: str, rival: str | None = None, *, as_of: str | None = None) -> dict[str, Any]:
    """What the gate `forward` reads about one week: the seal's lines, and every week of the run up
    to that one, each as its record gives it: the match counts, the line values, the remainder, the
    changes, the risk numbers, the range values, the trades and the settings.

    `subject` is `<study>/week-YYYY-WW`. Raises ValueError, with a plain reason, when the run cannot
    be read, when the week has no record, or when a week up to it has no replay or trades other
    settings: `themis decide` then refuses, and stores nothing. `rival` and `as_of` are not read.
    """
    study, name = _subject(subject)
    root, read = Path(root), data.reader(Path(root))
    found = sealed(manifest, Git(root).all_files(), read)
    if study not in found:
        raise ValueError(f"{study} is not a study sealed as kind {KIND}")
    run = read_run(study, found[study], read)
    if run.problems or run.seal is None:
        shown = "; ".join(f"{what} ({where})" for where, what in run.problems[:3])
        raise ValueError(f"the forward run cannot be read: {shown}")
    weeks = run.upto(name)
    if not weeks or weeks[-1].name != name:
        raise ValueError(f"there is no record {study}/results/week-{name}.json")
    for week in weeks:
        live, replay = week.record["live"], week.replay
        if replay is None:
            raise ValueError(f"week {week.name} has no replay: replay the same settings over the same dates, from "
                             "the same start, before the week is decided")
        if live["settings"] != run.seal.settings:
            raise ValueError(f"week {week.name} traded the settings {live['settings']}, and the seal's are "
                             f"{run.seal.settings}: a settings change ends the run")
        if replay["settings"] != live["settings"]:
            raise ValueError(f"week {week.name}'s replay used the settings {replay['settings']}, and the live week "
                             f"{live['settings']}")
    start = run.weeks[0].period[0]
    return {"subject": f"{study}/week-{name}", "seal": run.seal.table(),
            "weeks": [_inputs_of(run.seal, start, week) for week in weeks]}


pack.inputs[GATE] = build


# -- the gate -----------------------------------------------------------------------------------

INPUT_LINE = {"worse": Required(Choice("higher", "lower")), "pass": Required(float), "stop": float,
              "running": Required(int), "min": Required(int)}
INPUT_WEEK = {
    "week": Required(str), "settings": Required(str), "trades": Required(int), "matched": Required(int),
    "missed": Required(int), "extra": Required(int), "reasons": Required([str]),
    "lines": Required({"*": LINE_VALUE}), "unexplained": Required(float),
    "changes": Required([CHANGE]), "risk": Required({"*": float}), "range": Required({"*": float}),
    "range_due": Required([str]),
}
INPUTS = {
    "subject": Required(str),
    "seal": Required({"settings": Required(str), "min_trades": Required(int), "lines": Required({"*": INPUT_LINE}),
                      "risk": Required({"*": RISK_TABLE}), "ranges": Required({"*": RANGE_TABLE}),
                      "reasons": Required([str]), "changes_allowed": Required([str]),
                      "changes_stop": Required([str])}),
    "weeks": Required([INPUT_WEEK]),
}

Answer = dict[str, Any]


def _answer(decision: str, verdict: str, enough: bool, reason: str, numbers: dict[str, Any]) -> Answer:
    return {"decision": decision, "verdict": verdict, "enough_evidence": enough, "reason": reason, "numbers": numbers}


def _malformed(inputs: Any) -> str | None:
    """Why the inputs cannot be judged, or None when they can."""
    if not isinstance(inputs, dict):
        return "the inputs are not a table"
    wrong = schema.problems(inputs, INPUTS, "the inputs") + _unfinite(inputs, "the inputs")
    if not wrong:
        wrong = [found for index, week in enumerate(inputs["weeks"])
                 for found in _line_values(week["lines"], f"the inputs.weeks[{index}].lines")]
    if wrong:
        return "the inputs cannot be read: " + "; ".join(wrong[:3])
    seal, weeks = inputs["seal"], inputs["weeks"]
    lines = seal["lines"]
    if not weeks:
        return "the inputs hold no week"
    if seal["min_trades"] < 1:
        return "the seal's min_trades must be 1 or more"
    for name in OWN:
        if name not in lines or lines[name]["worse"] != WORSE[name]:
            return f"the seal's lines must hold {name}, worse when it is {WORSE[name]}"
    for name, line in lines.items():
        if line["running"] < 1 or line["min"] < 0 or ("stop" in line and _past(line["pass"], line["stop"], line["worse"])):
            return f"the line {name} must run over 1 week or more, on a sample of 0 or more, with its stop past its pass"
    keys = [_key(week["week"]) if re.fullmatch(r"[0-9]{4}-[0-9]{2}", week["week"]) else None for week in weeks]
    if None in keys or keys != sorted(set(keys)):  # type: ignore[type-var]
        return "the weeks must each be named YYYY-WW, once each, oldest first"
    for week in weeks:
        said = f"week {week['week']}"
        if min(week["trades"], week["matched"], week["missed"], week["extra"],
               *(held["n"] for held in week["lines"].values())) < 0:
            return f"{said} holds a count below 0"
        if week["trades"] != week["matched"] + week["extra"]:
            return (f"{said} counts {week['trades']} trades, and holds {week['matched'] + week['extra']} live entries: "
                    "each live trade is a matched entry or an extra one")
        if week["settings"] != seal["settings"]:
            return f"{said} traded other settings than the seal's: a settings change ends the run"
        missing = [name for name in lines if name not in OWN and name not in week["lines"]]
        missing += [name for name in seal["risk"] if name not in week["risk"]]
        if missing:
            return f"{said} has no figure for the sealed line {missing[0]}"
        for day in week["range_due"]:
            if day not in seal["ranges"] or day not in week["range"]:
                return f"{said} reaches day {day} of the run, and holds no money for a range the seal draws for it"
    return None


def _value(name: str, week: dict[str, Any]) -> tuple[float | None, int]:
    """A line's value in one week, and the sample it is read on. Themis computes match, the share of the
    replay's entries that also appear live, read on matched and missed entries; and unexplained, the
    size of the gap's remainder, read on every entry of the week, matched, missed or extra."""
    if name == "match":
        seen = week["matched"] + week["missed"]
        return (week["matched"] / seen if seen else None), seen
    if name == "unexplained":
        return abs(week["unexplained"]), week["matched"] + week["missed"] + week["extra"]
    held = week["lines"][name]
    return held["value"], held["n"]


def _zone(line: dict[str, Any], value: float | None, n: int) -> str | None:
    """Where a value lies against its line: pass, look or stop. None when it cannot be judged: no
    value, a sample of none, or a sample under the line's `min`."""
    if value is None or n == 0 or n < line["min"]:
        return None
    if not _past(value, line["pass"], line["worse"]):
        return "pass"
    return "stop" if "stop" in line and _past(value, line["stop"], line["worse"]) else "look"


@pack.gate(GATE, version="1")
def forward(inputs: dict[str, Any]) -> Answer:
    """Is a forward run holding up against its replay, week by week?

    `inputs` is what `build` makes of one week: the seal's lines, and every week of the run up to
    this one. The answer, in this order:

    1. Malformed inputs: `defer`.
    2. A risk line passed in any week so far: `stop`. It stays: every later week is `stop` too.
    3. This week, a line past its stop and so for `running` weeks in a row, or a change the seal stops
       on: `stop`, for this week. A later week is judged on its own; its run of weeks looks back.
    4. This week, a line worse than its pass, a missed or extra entry for a reason the seal does not
       know, a change the seal does not allow, or a range day reached with the money outside: `look-closer`.
    5. Fewer trades so far than `min_trades`: `defer`.
    6. Otherwise `pass`.

    `stop` is a fail on enough evidence; `look-closer` a refusal on enough evidence, which a person
    reads; `defer` a refusal on too little. A look-closer is never read as a pass. A week a line
    cannot be judged on, because its sample is none or under `min`, is passed over: it neither ends a
    run of weeks past the stop nor adds to one. `numbers.conditions_changes` is the week's list of
    changes, as its record gives it, for forward/conditions-stable to read.
    """
    wrong = _malformed(inputs)
    if wrong:
        return _answer("defer", "refuse", False, wrong, {})
    seal, weeks = inputs["seal"], inputs["weeks"]
    now, trades = weeks[-1], sum(week["trades"] for week in weeks)
    stops: list[str] = [
        f"the risk line {name} was passed in week {week['week']}: {week['risk'][name]:g}, past its stop of "
        f"{line['stop']:g}"
        for week in weeks for name, line in seal["risk"].items()
        if _past(week["risk"][name], line["stop"], line["worse"])]
    lines: dict[str, dict[str, Any]] = {}
    for name, line in seal["lines"].items():
        run = 0
        for week in weeks:
            zone = _zone(line, *_value(name, week))
            if zone is None:
                continue  # passed over: it neither ends the run of weeks nor adds to it
            run = run + 1 if zone == "stop" else 0
        value, n = _value(name, now)
        zone = _zone(line, value, n)
        if zone == "stop" and run >= line["running"]:  # this week past its stop, and so for its run of weeks
            stops.append(f"{name} was past its stop of {line['stop']:g} for {run} week(s) in a row, to week "
                         f"{now['week']}")
        lines[name] = {"value": value, "n": n, "zone": zone, "weeks_past_stop": run if zone == "stop" else 0}
    stops += [f"the change of {change['what']} in week {now['week']} is one the seal stops on"
              for change in now["changes"] if change["what"] in seal["changes_stop"]]
    look = [f"{name} is {held['value']:g} this week, worse than its pass of {seal['lines'][name]['pass']:g}"
            for name, held in lines.items() if held["zone"] in ("look", "stop")]
    unknown = sorted({reason for reason in now["reasons"] if reason not in seal["reasons"]})
    if unknown:
        look.append("an entry was missed or extra for a reason the seal does not know: "
                    + ", ".join(reason if reason.strip() else "none given" for reason in unknown))
    look += [f"a change of {change['what']} that the seal does not allow" for change in now["changes"]
             if change["what"] not in seal["changes_allowed"] and change["what"] not in seal["changes_stop"]]
    for day in now["range_due"]:
        value, held = now["range"][day], seal["ranges"][day]
        if not held["low"] <= value <= held["high"]:
            look.append(f"the money on day {day} of the run is {value:g}, outside its range of {held['low']:g} to "
                        f"{held['high']:g}")
    numbers = {"week": now["week"], "weeks": len(weeks), "trades_to_date": trades, "min_trades": seal["min_trades"],
               "lines": lines, "risk": now["risk"], "range": now["range"], "unknown_reasons": unknown,
               "conditions_changes": now["changes"], "stops": stops, "look_closer": look}
    if stops:
        return _answer("stop", "fail", True, "; ".join(stops), numbers)
    if look:
        return _answer("look-closer", "refuse", True, "; ".join(look), numbers)
    if trades < seal["min_trades"]:
        return _answer("defer", "refuse", False,
                       f"{trades} trades so far, and the seal asks for {seal['min_trades']} before any pass", numbers)
    return _answer("pass", "pass", True,
                   f"every line is inside its pass and every entry's reason is known, on {trades} trades so far, where "
                   f"the seal asks for {seal['min_trades']}", numbers)


# -- calibration: every way a week can fall short, and a clean week past the count --------------

CASE_SEAL: dict[str, Any] = {
    "settings": "3f9a0c1d", "min_trades": 40,
    "lines": {"match": {"worse": "lower", "pass": 0.9, "stop": 0.8, "running": 2, "min": 10},
              "unexplained": {"worse": "higher", "pass": 20.0, "stop": 100.0, "running": 1, "min": 0},
              "entry-cost": {"worse": "higher", "pass": 0.43, "stop": 0.86, "running": 1, "min": 30}},
    "risk": {"day-loss": {"worse": "higher", "stop": 0.52}}, "ranges": {"10": {"low": 9000.0, "high": 12000.0}},
    "reasons": ["news pause"], "changes_allowed": ["spread"], "changes_stop": ["leverage"],
}
CASE_WEEK: dict[str, Any] = {
    "settings": "3f9a0c1d", "trades": 25, "matched": 24, "missed": 1, "extra": 1, "reasons": ["news pause"] * 2,
    "lines": {"entry-cost": {"value": 0.3, "n": 48}}, "unexplained": -5.0, "changes": [], "risk": {"day-loss": 0.2},
    "range": {}, "range_due": [],
}


def week_case(name: str, **changes: Any) -> dict[str, Any]:
    """One clean week of the gate's inputs: 25 trades, 24 of 25 entries matched, every line inside its pass."""
    return {**json.loads(json.dumps(CASE_WEEK)), "week": name, **changes}


def forward_case(*weeks: dict[str, Any], **seal: Any) -> dict[str, Any]:
    """The gate's inputs for the last of these weeks, under the case's seal with these changes."""
    last = weeks[-1]["week"] if weeks else "2026-48"
    return {"subject": f"work/fwd/week-{last}", "seal": {**json.loads(json.dumps(CASE_SEAL)), **seal},
            "weeks": list(weeks)}


def short_cases() -> list[dict[str, Any]]:
    """Every way a week of a forward run can fall short: each must not pass."""
    one, two = "2026-48", "2026-49"

    def change(what: str) -> list[dict[str, Any]]:
        return [{"at": "2026-11-24T10:00:00+00:00", "what": what, "from": 1.0, "to": 2.0}]

    second = [
        {"risk": {"day-loss": 0.6}},  # a risk line passed this week
        {"lines": {"entry-cost": {"value": 0.9, "n": 48}}},  # a line past its stop
        {"lines": {"entry-cost": {"value": 0.6, "n": 48}}},  # a line in its look zone
        {"matched": 17, "missed": 3, "trades": 18},  # match at 0.85, in its look zone
        {"matched": 15, "missed": 5, "trades": 16},  # match past its stop, one week of the two it needs
        {"trades": 40},  # more trades than the live entries it holds: malformed
        {"unexplained": 60.0},  # a remainder in its look zone
        {"unexplained": -300.0},  # a remainder past its stop
        {"reasons": ["a reason nobody sealed"]}, {"reasons": [""]},  # an unknown reason, and none
        {"changes": change("leverage")}, {"changes": change("commission")},  # a stop change, an unallowed one
        {"range_due": ["10"], "range": {"10": 8000.0}},  # the money outside its range
        {"range_due": ["10"], "range": {}}, {"lines": {}}, {"risk": {}}, {"settings": "77c0aa11"},  # malformed
    ]
    cases = [forward_case(week_case(one), week_case(two, **changes)) for changes in second]
    return cases + [
        forward_case(week_case(one, matched=15, missed=5, trades=16),  # two weeks past the stop
                     week_case(two, matched=15, missed=5, trades=16)),
        forward_case(week_case(one, risk={"day-loss": 0.6}), week_case(two)),  # a risk line passed before: it stays
        forward_case(week_case(one, matched=15, missed=5, trades=16),  # past the stop two judged weeks running,
                     week_case(two, matched=0, missed=0, trades=1),  # with a week match cannot be read on between
                     week_case("2026-50", matched=15, missed=5, trades=16)),
        forward_case(week_case(one)),  # too few trades so far
        forward_case(),  # no week at all
        forward_case(week_case(two), week_case(one)),  # weeks out of order
    ]


@pack.calibration(GATE, "noise", "every way a week of a forward run can fall short")
def forward_noise() -> float:
    cases = short_cases()
    return sum(forward(case)["verdict"] == "pass" for case in cases) / len(cases)


@pack.calibration(GATE, "planted", "two clean weeks, past the sealed number of trades")
def forward_planted() -> float:
    return float(forward(forward_case(week_case("2026-48"), week_case("2026-49")))["verdict"] == "pass")


# -- the rules ----------------------------------------------------------------------------------


def _runs(ctx: Context) -> list[Run]:
    """Every forward run that can be read. Stops the rule when no study is sealed as forward; a run
    whose seal or records cannot be read is refused, and nothing else of it is judged."""
    found = {unit: files for unit, files in sorted(units.studies(ctx).items()) if is_forward(ctx.read, unit, files)}
    if not found:
        ctx.not_configured("seal a study as kind forward, with kind: forward in its PRE-REG.md")
    runs = []
    for unit, files in found.items():
        run = read_run(unit, files, ctx.read)
        for where, what in run.problems:
            ctx.refuse(what, where=where, fix=READ_FIX)
        if not run.problems and run.seal is not None:
            runs.append(run)
    return runs


def _granted(ctx: Context, held: list[Any] | None, subject: str) -> tuple[bool, list[Any]]:
    """Whether the owner granted `forward` for this week, and the grants, read once."""
    held = ctx.records("grant") if held is None else held
    return find_grant(held, ACTION, subject) is not None, held


# -- forward/sealed-before-start ----------------------------------------------------------------


def _trade_times(record: Any) -> list[dt.datetime]:
    """Every live trade time a record holds, read leniently: its first_trade_at, and each matched and
    extra entry's live time. A value that is not a time with its offset is left out."""
    live = record.get("live") if isinstance(record, dict) else None
    entries = record.get("entries") if isinstance(record, dict) else None
    texts = [live.get("first_trade_at")] if isinstance(live, dict) else []
    for kind, key in (("matched", "live_at"), ("extra", "at")):
        held = entries.get(kind) if isinstance(entries, dict) else None
        texts += [entry.get(key) for entry in held if isinstance(entry, dict)] if isinstance(held, list) else []
    return [found for found in map(moment, texts) if found is not None]


def _first_trade(ctx: Context, run: Run, main: str) -> tuple[dt.datetime, str] | None:
    """The run's first live trade, and the record it is in: the earliest first_trade_at or live entry in
    any record of the run, as the tree holds it or as any version of it on the main line held it. A
    record edited, or removed, after it reached the main line cannot move the first trade later."""
    found = [(when, week.path) for week in run.weeks for when in _trade_times(week.record)]
    for path in sorted(ctx.git.last_changes(main)):
        if not (path.startswith(f"{run.study}/") and work.inside(run.study, [path], [RECORDS])):
            continue
        for text in ctx.git.versions(main, path):
            try:
                held = json.loads(text)
            except json.JSONDecodeError:
                continue
            found += [(when, path) for when in _trade_times(held)]
    return min(found, key=lambda item: item[0], default=None)


def _differs(ctx: Context, main: str, path: str) -> bool:
    """True when the file in the tree is not the file at the main line's tip."""
    return ctx.git.show(main, path) != ctx.read(path)


MARGIN = Param("margin_hours", float, 0, "higher", "how many hours before the first live trade the seal must arrive")


@rule("forward/sealed-before-start", "A forward run's seal reaches the main line before its first live trade.",
      pack="trading", params=(MARGIN,),
      learned="A forward run's lines were written down after its first live week was seen, and fitted that week.")
def sealed_before_start(ctx: Context) -> None:
    runs = _runs(ctx)
    main = ctx.git.main_ref(ctx.manifest.project.get("main"))
    margin = max(ctx.param("margin_hours") or 0, 0)
    amendments = ctx.records("amendment") if runs else []
    fix = ("merge a forward run's seal on its own before its first live trade; a run that traded first is sealed "
           "anew, in a folder of its own, before its next trade")
    for run in runs:
        if main is None:
            if run.weeks:
                ctx.inspect()
                ctx.refuse("there is no main line, so the seal's arrival cannot be read", where=run.seal.path,
                           fix="commit to main, or set project.main")
            continue
        first = _first_trade(ctx, run, main)
        if first is None:
            continue  # no live trade yet: nothing can have come before the seal
        ctx.inspect()
        changed_at, line = ctx.git.last_changes(main), ctx.git.main_line(main)
        mine = [record for record in amendments if str(record.get("seal", "")).strip("/") == run.seal.path]
        files = [run.seal.path, *(record.path for record in mine)]
        away = [path for path in files if path not in changed_at or _differs(ctx, main, path)]
        if away:
            said = (f"its seal, {away[0]}," if away[0] == run.seal.path else f"an amendment of its seal, {away[0]},")
            ctx.breach(f"this forward run has traded, and {said} is not on the main line as it stands", where=away[0],
                       fix=fix)
            continue
        # Dated by the last change of each file: an edit in place counts as made when it was merged.
        latest = max(changed_at[path] for path in files)
        what = "the seal" if latest == changed_at[run.seal.path] else "an amendment of the seal"
        arrived = moment(ctx.git.commit_time(line[latest]))
        if arrived is None:
            ctx.refuse(f"the main line's commit {line[latest][:12]} has no time that can be read", where=run.seal.path)
            continue
        if not arrived < first[0] - dt.timedelta(hours=margin):
            gap = (f"less than {margin:g} hour(s) before" if margin else "not before")
            ctx.breach(f"{what}, as it stands, reached the main line at {_shown(arrived)}, {gap} the first live "
                       f"trade at {_shown(first[0])}", where=first[1], fix=fix)


# -- forward/same-dates-control -----------------------------------------------------------------


FIELDS = Param("fields", [str], None, "larger",
               "further fingerprint fields the live week and its replay must both state, with one value")


@rule("forward/same-dates-control", "Each week of a forward run has a replay on the same dates, from the same start "
      "state, with the same settings.", pack="trading", params=(FIELDS,),
      learned="A live week was laid beside a replay of other dates, from another balance, and the gap was read as "
              "the cost of trading live.")
def same_dates_control(ctx: Context) -> None:
    fix = "replay the same settings over the same dates, from the same start, and write it into the week's record"
    for run in _runs(ctx):
        previous: Week | None = None
        for week in run.weeks:
            ctx.inspect()
            said, (begun, ended) = f"week {week.name}", week.period
            if previous is not None:
                expected, before = _next(previous.key), previous.period[1]
                if week.key != expected:
                    ctx.breach(f"week {_name(expected)} is missing: the run goes from week {previous.name} to week "
                               f"{week.name}", where=week.path, fix="write the missing week's record, and decide it")
                elif begun != before:
                    how = "two weeks overlap" if begun < before else "the time between is in no week"
                    ctx.breach(f"{said} starts at {_shown(begun)}, and week {previous.name} ends at {_shown(before)}: "
                               f"{how}", where=week.path, fix="give each week the period from one week's end to the next's")
            previous = week
            live, replay = week.record["live"], week.replay
            if replay is None:
                ctx.breach(f"{said} has no replay", where=week.path, fix=fix)
                continue
            ran = (moment(replay["period"]["from"]), moment(replay["period"]["to"]))
            if ran != (begun, ended):
                ctx.breach(f"{said}'s replay ran from {_shown(ran[0])} to {_shown(ran[1])}, and the live week from "
                           f"{_shown(begun)} to {_shown(ended)}", where=week.path, fix=fix)
            for key in START:
                mine, theirs = live["start"][key], replay["start"][key]
                same = moment(mine) == moment(theirs) if key == "at" else _basis(mine) == _basis(theirs)
                if not same:
                    ctx.breach(f"{said}'s replay started from another state: its start.{key} is {json.dumps(theirs)}, "
                               f"and the live week's is {json.dumps(mine)}", where=week.path, fix=fix)
            if replay["settings"] != live["settings"]:
                ctx.breach(f"{said}'s replay used the settings {replay['settings']}, and the live week "
                           f"{live['settings']}", where=week.path, fix=fix)
            for name in ctx.param("fields") or ():
                if live.get(name) in (None, "") or replay.get(name) in (None, ""):
                    ctx.breach(f"{said}'s live week or its replay states no {name}, so they cannot be shown to share it",
                               where=week.path, fix=f"record {name} beside the live week and beside its replay")
                elif _basis(live[name]) != _basis(replay[name]):
                    ctx.breach(f"{said}'s live week and its replay differ in {name}: live has "
                               f"{json.dumps(live[name])}, the replay {json.dumps(replay[name])}", where=week.path, fix=fix)


# -- forward/match ------------------------------------------------------------------------------


FLOOR = Param("floor", float, 0, "higher", "the lowest pass a forward seal may set for the line match")


def _moved(stored: dict[str, Any], rebuilt: dict[str, Any]) -> list[str]:
    """Where the stored inputs differ from a rebuild: each top-level key, and each key of the seal."""
    found = []
    for key in sorted(set(stored) | set(rebuilt)):
        mine, theirs = stored.get(key), rebuilt.get(key)
        if mine == theirs:
            continue
        if isinstance(mine, dict) and isinstance(theirs, dict):
            found += [f"{key}.{inner}" for inner in sorted(set(mine) | set(theirs)) if mine.get(inner) != theirs.get(inner)]
        else:
            found.append(key)
    return found


def _rebuilt(ctx: Context, record: Any, subject: str) -> None:
    """Breach when the numbers a gate's decision was made from differ from a rebuild; refuse when they
    cannot be read or built again."""
    path = record.get("inputs")
    try:
        stored = json.loads(ctx.read(path) or "") if path else None
    except json.JSONDecodeError:
        stored = None
    if not isinstance(stored, dict) or stored.get("subject") != subject:
        ctx.refuse("this decision does not name a readable file of the numbers it was made from", where=record.path,
                   fix=f"issue the decision with `themis decide {subject} --gate {GATE}`, which builds that file")
        return
    try:
        rebuilt = build(ctx.root, ctx.manifest, subject)
    except ValueError as error:
        ctx.refuse(f"the numbers cannot be built again: {error}", where=path)
        return
    moved = _moved(stored, rebuilt)
    if moved:
        ctx.breach(f"the numbers this decision was made from differ from the seal and the records in: {', '.join(moved)}",
                   where=path, fix=f"issue the decision again with `themis decide {subject} --gate {GATE}`; its "
                                   "numbers are never typed")


@rule("forward/match", "Each week's share of replay entries that also appear live is counted from the entries and "
      "read against the sealed lines.", pack="trading", params=(FLOOR,),
      learned="Live entries were paired with the replay's by hand, and the ones that did not fit were left out of "
              "the count.")
def match(ctx: Context) -> None:
    runs, decided, grants = _runs(ctx), units.decisions(ctx), None
    floor = ctx.param("floor") or 0
    for run in runs:
        ctx.inspect()
        sealed_pass = run.seal.lines["match"]["pass"]
        if sealed_pass < floor:
            ctx.breach(f"the seal sets the pass of match at {sealed_pass:g}, under this project's floor of {floor:g}",
                       where=run.seal.path, fix=f"seal match with a pass of {floor:g} or more")
        for week in run.weeks:
            ctx.inspect()
            said, entries, subject = f"week {week.name}", week.record["entries"], week.subject(run.study)
            for kind in ("missed", "extra"):
                for entry in entries[kind]:
                    if not entry["reason"].strip():
                        ctx.breach(f"the {kind} entry {entry['id']} in {said} gives no reason", where=week.path,
                                   fix="give each missed or extra entry its reason; one the seal does not know is "
                                       "read as look-closer")
            seen: dict[str, str] = {}
            for kind in ("matched", "missed", "extra"):
                for entry in entries[kind]:
                    if entry["id"] in seen:
                        ctx.breach(f"the entry {entry['id']} is listed twice in {said}: under {seen[entry['id']]} and "
                                   f"under {kind}", where=week.path, fix="list each entry once: matched, missed or extra")
                    seen.setdefault(entry["id"], kind)
            for name in (name for name in run.seal.lines if name not in OWN):
                if name not in week.record["lines"]:  # its n is read as written: Themis cannot know what it counts
                    ctx.breach(f"{said} has no value for the sealed line {name}", where=week.path,
                               fix=f"write {name} into the week's lines, with the n it is read on")
            found = decided.get(subject, [])
            if not found:
                ctx.breach(f"{said} has no decision from the gate", where=week.path,
                           fix=f"run `themis decide {subject} --gate {GATE}`")
            for record in found:
                if record.get("by") == "owner":
                    grants = _owner_pass(ctx, record, subject, grants)
                elif record.get("gate") == GATE:
                    _rebuilt(ctx, record, subject)
        names = {week.name for week in run.weeks}
        for subject, found in sorted(decided.items()):
            named = re.fullmatch(rf"{re.escape(run.study)}/week-([0-9]{{4}})-([0-9]{{2}})", subject)
            if named and f"{named[1]}-{named[2]}" not in names:
                for record in found:
                    ctx.inspect()
                    ctx.breach(f"the decision of week {named[1]}-{named[2]} names a record that is not there: "
                               f"{run.study}/results/week-{named[1]}-{named[2]}.json", where=record.path,
                               fix="restore the week's record from git: a week once decided keeps its record")


def _owner_pass(ctx: Context, record: Any, subject: str, grants: list[Any] | None) -> list[Any] | None:
    """Breach when the owner stored a pass the gate would not give, with no unspent forward grant for
    that week. Returns the grants, read once."""
    if record.get("verdict") != "pass":
        return grants
    try:
        answer = forward(build(ctx.root, ctx.manifest, subject))
        said = None if answer["verdict"] == "pass" else f"where the gate says {answer['decision']}"
    except ValueError as error:
        said = f"where the gate cannot decide ({error})"
    if said is None:
        return grants
    granted, grants = _granted(ctx, grants, subject)
    if not granted:
        ctx.breach(f"the owner passed {subject.rsplit('/', 1)[-1].replace('-', ' ', 1)}, {said}, with no unspent "
                   f"{ACTION} grant for that week", where=record.path,
                   fix=f"the owner runs `themis grant {ACTION} {subject} --reason ...` before a pass the gate does "
                       "not give")
    return grants


# -- forward/gap-explained ----------------------------------------------------------------------


TOLERANCE = Param("tolerance", float, 0.01, "lower",
                  "how far, in money, the parts and the remainder may add up from live less replay")


@rule("forward/gap-explained", "The gap between live and replay money is split into its sealed parts, and the "
      "remainder is read against its sealed line.", pack="trading", params=(TOLERANCE,),
      learned="The gap between live and replayed money was put down to costs, and nobody added the costs up to see "
              "that they fell short.")
def gap_explained(ctx: Context) -> None:
    tolerance = max(ctx.param("tolerance") or 0, 0)
    fix = "split the gap into the seal's parts, each once, and write what they leave as the remainder"
    for run in _runs(ctx):
        sealed_parts = set(run.seal.gap_parts)
        for week in run.weeks:
            ctx.inspect()
            gap, said = week.record["gap"], f"week {week.name}"
            unsealed, left = sorted(set(gap["parts"]) - sealed_parts), sorted(sealed_parts - set(gap["parts"]))
            if unsealed:
                ctx.breach(f"{said} splits the gap into {', '.join(unsealed)}, which the seal does not name: its parts "
                           f"are {', '.join(run.seal.gap_parts)}", where=week.path, fix=fix)
            if left:
                ctx.breach(f"{said} leaves out the sealed part(s) {', '.join(left)}", where=week.path, fix=fix)
            if week.replay is None:
                continue  # no replay to take from: forward/same-dates-control fails the week
            whole = week.record["live"]["net"] - week.replay["net"]
            told = math.fsum(gap["parts"].values()) + gap["unexplained"]
            if abs(told - whole) > tolerance + 1e-9:
                ctx.breach(f"in {said} the parts and the remainder add up to {told:g}, and live less replay is "
                           f"{whole:g}", where=week.path, fix=fix)


# -- forward/conditions-stable ------------------------------------------------------------------


@rule("forward/conditions-stable", "Every change in trading conditions recorded during a forward run is listed in "
      "that week's verdict.", pack="trading",
      learned="A venue widened its spreads in the middle of a run, and that week's verdict never said so.")
def conditions_stable(ctx: Context) -> None:
    runs, decided = _runs(ctx), units.decisions(ctx)
    for run in runs:
        for week in run.weeks:
            held = week.record["conditions"]["changes"]
            for record in decided.get(week.subject(run.study), []):
                if record.get("by") == "owner":
                    continue  # the owner's own call carries no numbers of the gate's
                ctx.inspect()
                listed = (record.get("numbers") or {}).get("conditions_changes")
                if not isinstance(listed, list) or _basis(listed) != _basis(held):
                    shown = len(listed) if isinstance(listed, list) else "none"
                    ctx.breach(f"the verdict of week {week.name} does not list the changes its record holds: the "
                               f"record holds {len(held)}, the verdict lists {shown}", where=record.path,
                               fix=f"issue the decision again with `themis decide {week.subject(run.study)} --gate "
                                   f"{GATE}`, which lists them")


# -- forward/no-retune --------------------------------------------------------------------------


@rule("forward/no-retune", "The settings fingerprint stays the same for the whole forward run.", pack="trading",
      learned="Settings were changed in the middle of a forward run, and its weeks were still read as one run.")
def no_retune(ctx: Context) -> None:
    for run in _runs(ctx):
        for week in run.weeks:
            ctx.inspect()
            used = week.record["live"]["settings"]
            if used != run.seal.settings:
                ctx.breach(f"week {week.name} traded the settings {used}, and the seal's are {run.seal.settings}",
                           where=week.path, fix="a settings change ends the forward run: stop it, and seal a new run, "
                                                "in a folder of its own, for the new settings")


# -- forward/enough-trades ----------------------------------------------------------------------


MIN_TRADES = Param("min_trades", int, 30, "higher", "the fewest trades a forward seal may ask for before any pass")


@rule("forward/enough-trades", "A forward run gets no pass before its sealed number of trades.", pack="trading",
      params=(MIN_TRADES,),
      learned="A forward run was called good after a handful of trades, and the next month undid it.")
def enough_trades(ctx: Context) -> None:
    runs, decided, grants = _runs(ctx), units.decisions(ctx), None
    least = ctx.param("min_trades")
    for run in runs:
        ctx.inspect()
        asked = run.seal.min_trades
        if least is not None and asked < least:
            ctx.breach(f"the seal asks for {asked} trades before any pass, under this project's floor of {least}",
                       where=run.seal.path, fix=f"seal min_trades at {least} or more")
        total = 0
        for week in run.weeks:
            total += week.record["live"]["trades"]
            subject = week.subject(run.study)
            for record in decided.get(subject, []):
                if record.get("verdict") != "pass":
                    continue
                ctx.inspect()
                if total >= asked:
                    continue
                if record.get("by") == "owner":
                    granted, grants = _granted(ctx, grants, subject)
                    if not granted:
                        ctx.breach(f"the owner passed week {week.name} at {total} of the {asked} trades the seal asks "
                                   f"for, with no {ACTION} grant for that week", where=record.path,
                                   fix=f"the owner runs `themis grant {ACTION} {subject} --reason ...` before a pass "
                                       "ahead of the count")
                    continue
                ctx.breach(f"week {week.name} is stored as a pass at {total} of the {asked} trades the seal asks for",
                           where=record.path, fix=f"issue the decision again with `themis decide {subject} --gate "
                                                  f"{GATE}`; it defers until the count is reached")


# -- forward/risk-line --------------------------------------------------------------------------


REQUIRED = Param("required", [str], None, "larger", "the risk ids every forward seal must draw a line for")


@rule("forward/risk-line", "A risk number past its sealed line stops a forward run, whatever else passes.",
      pack="trading", params=(REQUIRED,),
      learned="A run fell past its loss limit while its other lines still looked fine, and it went on trading.")
def risk_line(ctx: Context) -> None:
    runs, decided, grants = _runs(ctx), units.decisions(ctx), None
    for run in runs:
        ctx.inspect()
        for name in ctx.param("required") or ():
            if name not in run.seal.risk:
                ctx.breach(f"the seal draws no risk line for {name}, which this project requires", where=run.seal.path,
                           fix=f"seal {name} under risk, with {LINE}{name}: {EXAMPLES['risk line']}")
        passed: tuple[str, str, float, float] | None = None
        for week in run.weeks:
            ctx.inspect()
            figures, subject = week.record["risk"], week.subject(run.study)
            for name, line in run.seal.risk.items():
                if name not in figures:
                    ctx.breach(f"week {week.name} has no figure for the sealed risk line {name}", where=week.path,
                               fix=f"write {name} into the week's risk, every week")
                elif passed is None and _past(figures[name], line["stop"], line["worse"]):
                    passed = (week.name, name, figures[name], line["stop"])
            if passed is None:
                continue
            for record in decided.get(subject, []):
                if record.get("decision") == "stop" and record.get("verdict") == "fail":
                    continue  # a stop is the word and the verdict both
                if record.get("by") == "owner":
                    granted, grants = _granted(ctx, grants, subject)
                    if granted:
                        continue  # the owner overruled the stop, with a grant for this week
                ctx.breach(f"the risk line {passed[1]} was passed in week {passed[0]} ({passed[2]:g}, past its stop of "
                           f"{passed[3]:g}), and week {week.name} is stored as {record.get('decision')} with the "
                           f"verdict {record.get('verdict')}",
                           where=record.path, fix=f"a passed risk line stops the run: issue the decision again from the "
                                                  f"gate; only the owner overrules it, with `themis grant {ACTION} "
                                                  f"{subject}`")


# -- the proofs ---------------------------------------------------------------------------------

STUDY = "work/fwd"
SETTINGS = "3f9a0c1d"
MANIFEST = """
    [project]
    packs = ["trading"]

    [trading]
    work = "work/*"
"""
#: The seal of the proofs' forward run, as frontmatter: 40 trades before any pass.
SEAL = {
    "kind": "forward", "gate": "forward", "settings": SETTINGS, "min_trades": 40,
    "stop_rule": "the owner stops it; a restart is a new run, sealed anew", "lines": "[match, unexplained, entry-cost]",
    "line-match": '{worse = "lower", pass = 0.9, stop = 0.8, running = 2}',
    "line-unexplained": '{worse = "higher", pass = 20, stop = 100}',
    "line-entry-cost": '{worse = "higher", pass = 0.43, stop = 0.86, min = 30}',
    "risk": "[day-loss]", "line-day-loss": '{worse = "higher", stop = 0.52}', "ranges": "[]",
    "gap_parts": "[spread, commission, swap]", "reasons": "[news pause, server restart]",
    "changes_allowed": "[spread]", "changes_stop": "[leverage]",
}
DROP = object()  # a change that takes the key out


def seal_text(**changes: Any) -> str:
    """The proofs' seal, with these fields changed; None leaves a field out."""
    fields = {**SEAL, **changes}
    return "---\n" + "".join(f"{key}: {value}\n" for key, value in fields.items() if value is not None) + "---\n\nThe plan.\n"


def matched(number: int, count: int, step: float = 1.0, year: int = 2026, begin: float = 10) -> list[dict[str, Any]]:
    """`count` matched entries in ISO week `year`-`number`, `step` hours apart, the first `begin` + `step`
    hours after Monday 00:00 UTC."""
    monday = dt.datetime.combine(dt.date.fromisocalendar(year, number, 1), dt.time(), dt.timezone.utc)
    times = [(monday + dt.timedelta(hours=begin + n * step)).isoformat() for n in range(1, count + 1)]
    return [{"id": f"e{n}", "live_at": at, "replay_at": at} for n, at in enumerate(times, start=1)]


def week_record(number: int, index: int = 1, year: int = 2026) -> dict[str, Any]:
    """An honest week: ISO week `year`-`number`, the run's `index`th. 20 live trades: 19 of the replay's
    20 entries matched, one missed and one extra, each for a known reason; the gap split exactly into
    its parts."""
    monday = dt.datetime.combine(dt.date.fromisocalendar(year, number, 1), dt.time(), dt.timezone.utc)

    def at(hours: float) -> str:
        return (monday + dt.timedelta(hours=hours)).isoformat()

    period, state = {"from": at(0), "to": at(24 * 7)}, {"at": at(0), "balance": 10000.0, "open_positions": 0,
                                                         "peak": 10000.0}
    return {
        "week": _name((year, number)), "period": period,
        "live": {"run": f"live-{number}", "settings": SETTINGS, "start": state, "trades": 20, "net": 120.0,
                 "first_trade_at": at(11)},
        "replay": {"run": f"replay-{number}", "settings": SETTINGS, "period": dict(period), "start": dict(state),
                   "trades": 20, "net": 150.0},
        "entries": {"matched": matched(number, 19, year=year),
                    "missed": [{"id": "e20", "at": at(40), "reason": "news pause"}],
                    "extra": [{"id": "x1", "at": at(60), "reason": "server restart"}]},
        "fill_costs": {"entry": {"n": 19, "live": 9.5, "replay": 5.0}},
        "gap": {"parts": {"spread": -12.0, "commission": -15.0, "swap": 0.0}, "unexplained": -3.0},
        "lines": {"entry-cost": {"value": 0.3, "n": 19 * index}},
        "conditions": {"changes": []},
        "risk": {"day-loss": 0.2},
        "range": {},
    }


def changed(held: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """A copy with each change made: a dotted path, with a number for a place in a list, and its value.
    DROP takes the key out."""
    held = json.loads(json.dumps(held))
    for dotted, value in changes.items():
        *path, last = dotted.split(".")
        inside: Any = held
        for part in path:
            inside = inside[int(part)] if isinstance(inside, list) else inside[part]
        if isinstance(inside, list):
            inside[int(last)] = value
        elif value is DROP:
            del inside[last]
        else:
            inside[last] = value
    return held


def _week_path(number: int, study: str = STUDY) -> str:
    return f"{study}/results/week-2026-{number:02d}.json"


def _subject_of(number: int) -> str:
    return f"{STUDY}/week-2026-{number:02d}"


def _decided_at(number: int) -> str:
    return (dt.datetime.combine(dt.date.fromisocalendar(2026, number, 7), dt.time(23), dt.timezone.utc)).isoformat()


def decide(world: World, number: int, typed: dict[str, Any] | None = None, inputs: dict[str, Any] | None = None) -> None:
    """Decide a week as `themis decide` does: build the inputs, ask the gate, store both. `typed` is then
    typed over the stored decision, and `inputs` over the stored numbers."""
    from themis import manifest as manifests

    subject = _subject_of(number)
    built = build(world.root, manifests.load(world.root), subject)
    answer, name = forward(built), work.file_name(subject)
    world.write(f"decision-inputs/{name}.json", json.dumps(changed(built, inputs or {})))
    record = {"work": subject, "gate": GATE, "gate_version": "1", "decided_at": _decided_at(number),
              "inputs": f"decision-inputs/{name}.json", **answer}
    world.write(f"decisions/{name}.json", json.dumps(changed(record, typed or {})))


def owner(world: World, number: int, decision: str | tuple[str, str]) -> None:
    """The owner's own call on a week, as `themis decide --by owner` stores it: a decision word, with
    the verdict it usually goes with, or a (word, verdict) pair."""
    decision, verdict = decision if isinstance(decision, tuple) else (
        decision, {"pass": "pass", "stop": "fail"}.get(decision, "refuse"))
    subject = _subject_of(number)
    world.write(f"decisions/{work.file_name(subject)}.json", json.dumps({
        "work": subject, "decision": decision, "verdict": verdict, "gate": GATE, "gate_version": "owner",
        "decided_at": _decided_at(number), "by": "owner", "reason": "the owner's own call, with a reason in words"}))


def grant(world: World, number: int) -> None:
    world.write(f"grants/forward-{number}.toml", to_toml({
        "action": ACTION, "target": _subject_of(number), "granted_by": "owner",
        "granted_at": _decided_at(number), "reason": "the owner looked at the week"}))


def _forward(world: World, weeks: tuple[int, ...] = (48, 49), seal: dict[str, Any] | None = None,
             changes: dict[int, dict[str, Any]] | None = None, decided: tuple[int, ...] | None = (),
             typed: dict[int, dict[str, Any]] | None = None, inputs: dict[int, dict[str, Any]] | None = None,
             owned: dict[int, str] | None = None, granted: tuple[int, ...] = (),
             after: dict[int, dict[str, Any]] | None = None, rules: str = "",
             sealed_on: tuple[str, int] | None = ("2026-11-20", 9), amended_on: tuple[str, int] | None = None,
             commits: tuple[tuple[str, int, dict[str, str | None]], ...] = (),
             files: dict[str, str | None] | None = None) -> None:
    """A forward run: its seal merged on the main line on `sealed_on` (a day and an hour; None leaves it
    off the main line), and an honest record for each week but for its `changes`. The weeks in
    `decided` (every week when None) are decided by the gate, with `typed` and `inputs` typed over what
    is stored; the weeks in `owned` are the owner's own call (a decision word, or a word and a
    verdict), and those in `granted` hold the owner's grant. `after` changes a record once its week is
    decided. `amended_on` merges an amendment of the seal on that day and hour, and `commits` merges
    each (day, hour, files) after it, a file set to None removed. `files` are written last."""
    world.manifest(MANIFEST + rules)
    if sealed_on is None:
        world.commit("the project")
    else:
        world.on(*sealed_on)
    world.write(f"{STUDY}/PRE-REG.md", seal_text(**(seal or {})))
    if sealed_on is not None:
        world.commit("the seal, merged on its own")
    if amended_on is not None:
        world.on(*amended_on)
        world.write(AMENDMENT, amendment_text())
        world.commit("an amendment of the seal")
    for day, hour, made in commits:
        world.on(day, hour)
        _put(world, made)
        world.commit("a later change, merged on the main line")
    order = {number: index for index, number in enumerate(weeks, start=1)}
    for number, index in order.items():
        world.write(_week_path(number), json.dumps(changed(week_record(number, index), (changes or {}).get(number, {}))))
    for number in weeks if decided is None else decided:
        if number in (owned or {}):
            owner(world, number, (owned or {})[number])
        else:
            decide(world, number, (typed or {}).get(number), (inputs or {}).get(number))
    for number in granted:
        grant(world, number)
    for number, made in (after or {}).items():
        record = changed(week_record(number, order[number]), {**(changes or {}).get(number, {}), **made})
        world.write(_week_path(number), json.dumps(record))
    _put(world, files or {})


def _put(world: World, files: dict[str, str | None]) -> None:
    """Write each file, or remove it when its text is None."""
    for path, text in files.items():
        if text is None:
            world.remove(path)
        else:
            world.write(path, text)


AMENDMENT = f"{STUDY}/amendments/1.toml"


def amendment_text(sha256: str = "0" * 64) -> str:
    return (f'seal = "{STUDY}/PRE-REG.md"\nsha256 = "{sha256}"\n'
            'reason = "a sentence of the plan was put more plainly"\n')


def _prove(rule_id: str, cases: list[tuple[str, str, str | None, dict[str, Any]]]) -> None:
    """One proof for each case: (its name, the verdict, text the finding holds, what `_forward` is given)."""
    for name, expect, contains, given in cases:
        @proof(rule_id, name, expect=expect, contains=contains)
        def _(world: World, given: dict[str, Any] = given) -> None:
            _forward(world, **given)


def _rule(rule_id: str, setting: str) -> str:
    """The manifest's table for one rule, with one setting."""
    return f'\n    [rules."{rule_id}"]\n    {setting}\n'


def _at(number: int, hours: float) -> str:
    monday = dt.datetime.combine(dt.date.fromisocalendar(2026, number, 1), dt.time(), dt.timezone.utc)
    return (monday + dt.timedelta(hours=hours)).isoformat()


def _periods(begun: str, ended: str) -> dict[str, str]:
    """A week's period, and its replay's, set to these two moments."""
    return {"period.from": begun, "period.to": ended, "replay.period.from": begun, "replay.period.to": ended}


EVERY = None  # every week decided by the gate
RISKY = {48: {"risk.day-loss": 0.6}}  # week 48 falls past its risk line
STOPPED = {"decision": "stop", "verdict": "fail"}
CHANGE_48 = {48: {"conditions.changes": [{"at": _at(48, 30), "what": "spread", "from": 1.2, "to": 1.6}]}}

_prove("forward/sealed-before-start", [
    ("sealed days before the first live trade", "pass", None, {}),
    ("an amendment that reached the main line before the first trade", "pass", None,
     {"amended_on": ("2026-11-21", 9)}),
    ("the seal merged an hour after the first live trade", "fail",
     "not before the first live trade at 2026-11-23T11:00:00+00:00", {"sealed_on": ("2026-11-23", 12)}),
    ("an amendment merged after the first live trade", "fail", "an amendment of the seal, as it stands, reached the "
     "main line at 2026-11-24T09:00", {"amended_on": ("2026-11-24", 9)}),
    ("an amendment merged before the first trade, edited in place after it", "fail",
     "an amendment of the seal, as it stands, reached the main line at 2026-11-25T09:00",
     {"amended_on": ("2026-11-21", 9), "commits": (("2026-11-25", 9, {AMENDMENT: amendment_text("1" * 64)}),)}),
    ("the seal edited in place after the first trade", "fail",
     "the seal, as it stands, reached the main line at 2026-11-25T09:00", {"commits": (("2026-11-25", 9, {
         f"{STUDY}/PRE-REG.md": seal_text(**{"line-match": '{worse = "lower", pass = 0.5, stop = 0.3}'})}),)}),
    ("the seal edited in place before the first trade", "pass", None, {"commits": (("2026-11-22", 9, {
        f"{STUDY}/PRE-REG.md": seal_text(stop_rule="the owner stops it, and says why")}),)}),
    ("a seal loosened in the tree, not merged, after trading began", "fail",
     "its seal, work/fwd/PRE-REG.md, is not on the main line as it stands",
     {"files": {f"{STUDY}/PRE-REG.md": seal_text(**{"line-match": '{worse = "lower", pass = 0.5, stop = 0.3}'})}}),
    ("a first week removed after it reached the main line, and the seal amended after it", "fail",
     "not before the first live trade at 2026-11-23T11:00:00+00:00",
     {"weeks": (49,), "commits": (("2026-11-29", 9, {_week_path(48): json.dumps(week_record(48))}),
                                  ("2026-11-30", 3, {AMENDMENT: amendment_text()}),
                                  ("2026-11-30", 4, {_week_path(48): None}))}),
    ("first_trade_at typed later than an entry", "fail", "not before the first live trade at 2026-11-23T09:00:00+00:00",
     {"sealed_on": ("2026-11-23", 10), "changes": {48: {"live.first_trade_at": _at(48, 12),
                                                         "entries.matched.0.live_at": _at(48, 9)}}}),
    ("a seal one hour ahead, where the project asks for two", "fail",
     "less than 2 hour(s) before the first live trade at 2026-11-23T11:00:00+00:00",
     {"sealed_on": ("2026-11-23", 10), "rules": _rule("forward/sealed-before-start", "margin_hours = 2")}),
    ("a run that traded with its seal off the main line", "fail", "this forward run has traded, and its seal, "
     "work/fwd/PRE-REG.md, is not on the main line", {"sealed_on": None}),
    ("a trade time with no UTC offset", "refuse", "is not a time with its UTC offset",
     {"changes": {48: {"live.first_trade_at": "2026-11-23T11:00:00"}}}),
    ("a run with no week yet", "refuse", "nothing was inspected", {"weeks": ()}),
])

_prove("forward/same-dates-control", [
    ("three weeks in a row, each with its replay", "pass", None, {"weeks": (48, 49, 50)}),
    ("a start written as a whole number in the replay", "pass", None,
     {"changes": {48: {"replay.start.balance": 10000, "replay.start.at": "2026-11-23T07:00:00+07:00"}}}),
    ("a week with no replay", "fail", "week 2026-48 has no replay", {"changes": {48: {"replay": None}}}),
    ("a replay one day short", "fail", "week 2026-48's replay ran from 2026-11-23T00:00:00+00:00 to 2026-11-29",
     {"changes": {48: {"replay.period.to": "2026-11-29T00:00:00+00:00"}}}),
    ("a replay from another balance", "fail", "its start.balance is 9000.0, and the live week's is 10000.0",
     {"changes": {48: {"replay.start.balance": 9000.0}}}),
    ("week 49 missing", "fail", "week 2026-49 is missing: the run goes from week 2026-48 to week 2026-50",
     {"weeks": (48, 50)}),
    ("two weeks that overlap", "fail", "two weeks overlap",
     {"changes": {49: {"period.from": "2026-11-29T00:00:00+00:00", "replay.period.from": "2026-11-29T00:00:00+00:00"}}}),
    ("a replay on other settings", "fail", "week 2026-48's replay used the settings 77c0aa11",
     {"changes": {48: {"replay.settings": "77c0aa11"}}}),
    ("a fingerprint field the project names, differing", "fail", "differ in cost_model",
     {"rules": _rule("forward/same-dates-control", 'fields = ["cost_model"]'),
      "changes": {48: {"live.cost_model": "costs-1", "replay.cost_model": "costs-2"},
                  49: {"live.cost_model": "costs-1", "replay.cost_model": "costs-1"}}}),
    ("a fingerprint field the project names, left out", "fail", "states no cost_model",
     {"rules": _rule("forward/same-dates-control", 'fields = ["cost_model"]')}),
    ("a period with no UTC offset", "refuse", "is not a time with its UTC offset",
     {"changes": {48: {"period.from": "2026-11-23T00:00:00"}}}),
    ("weeks run on a broker's clock two hours ahead of UTC", "pass", None, {"changes": {
        48: _periods("2026-11-22T22:00:00+00:00", "2026-11-29T22:00:00+00:00"),
        49: _periods("2026-11-29T22:00:00+00:00", "2026-12-06T22:00:00+00:00")}}),
    ("a short first week, begun on a Wednesday", "pass", None, {"changes": {48: {
        **_periods("2026-11-25T00:00:00+00:00", "2026-11-30T00:00:00+00:00"), "entries.matched": matched(48, 19, begin=50),
        "entries.missed.0.at": _at(48, 100), "live.first_trade_at": _at(48, 51)}}}),
    ("a week across a change of clocks, 7 days and an hour long", "pass", None, {"weeks": (43,), "changes": {
        43: _periods("2026-10-18T21:00:00+00:00", "2026-10-25T22:00:00+00:00")}}),
    ("a week whose period runs for months", "refuse", "runs for 70 days, and a week's runs for 8 at most",
     {"changes": {48: _periods("2026-11-23T00:00:00+00:00", "2027-02-01T00:00:00+00:00")}}),
    ("week 48 holding the dates of another year", "refuse",
     "does not lie in ISO week 2026-48: its middle falls in week 2025-48",
     {"changes": {48: _periods("2025-11-24T00:00:00+00:00", "2025-12-01T00:00:00+00:00")}}),
    ("a cumulative log: week 49 holding week 48's entries too", "refuse",
     "the record's entries.matched[0].live_at, 2026-11-23T11:00:00+00:00, lies outside its period",
     {"changes": {49: {"entries.matched": matched(48, 19) + matched(49, 19), "live.trades": 39}}}),
    ("a change dated in the week before", "refuse", "the record's conditions.changes[0].at", {"changes": {
        49: {"conditions.changes": [{"at": _at(48, 30), "what": "spread", "from": 1.2, "to": 1.6}]}}}),
])

_prove("forward/match", [
    ("19 of 20 entries matched, one missed for a known reason, every week decided", "pass", None, {"decided": EVERY}),
    ("the owner's own call is not built again", "pass", None, {"decided": EVERY, "owned": {49: "defer"}}),
    ("looser lines typed into the inputs", "fail", "differ from the seal and the records in: seal.lines",
     {"decided": EVERY, "inputs": {48: {"seal.lines.match.pass": 0.5}}}),
    ("a week left undecided", "fail", "week 2026-49 has no decision from the gate", {"decided": (48,)}),
    ("a missed entry with no reason", "fail", "the missed entry e20 in week 2026-48 gives no reason",
     {"decided": EVERY, "changes": {48: {"entries.missed.0.reason": " "}}}),
    ("one entry in two lists", "fail", "the entry e20 is listed twice in week 2026-48: under missed and under extra",
     {"decided": EVERY, "changes": {48: {"entries.extra": [{"id": "e20", "at": _at(48, 41), "reason": "news pause"}]}}}),
    ("a project line read on 120 hours, in a week of 19 matched entries", "pass", None,
     {"decided": EVERY, "changes": {48: {"lines.entry-cost.n": 120}}}),
    ("a decision left behind when its week's record was removed", "fail",
     "the decision of week 2026-48 names a record that is not there", {"weeks": (49, 50), "decided": EVERY, "files": {
         "decisions/work-fwd-week-2026-48.json": json.dumps({
             "work": _subject_of(48), "decision": "stop", "verdict": "fail", "gate": GATE, "gate_version": "1",
             "decided_at": _decided_at(48), "enough_evidence": True, "reason": "the risk line day-loss was passed",
             "inputs": "decision-inputs/work-fwd-week-2026-48.json"})}}),
    ("the owner's pass over a line's stop, with no grant", "fail",
     "the owner passed week 2026-49, where the gate says stop, with no unspent forward grant for that week",
     {"decided": EVERY, "changes": {49: {"lines.entry-cost.value": 0.9}}, "owned": {49: "pass"}}),
    ("the owner's pass over a line's stop, with a grant for that week", "pass", None,
     {"decided": EVERY, "changes": {49: {"lines.entry-cost.value": 0.9}}, "owned": {49: "pass"}, "granted": (49,)}),
    ("the owner's pass where the gate passes too needs no grant", "pass", None,
     {"decided": EVERY, "owned": {49: "pass"}}),
    ("a sealed line left out of a week", "fail", "week 2026-48 has no value for the sealed line entry-cost",
     {"decided": EVERY, "changes": {48: {"lines": {}}}}),
    ("a match bar under the project's floor", "fail", "sets the pass of match at 0.9, under this project's floor of 0.95",
     {"decided": EVERY, "rules": _rule("forward/match", "floor = 0.95")}),
    ("a record edited after its week was decided", "fail", "differ from the seal and the records in: weeks",
     {"decided": EVERY, "after": {48: {"entries.matched.0.id": "e19", "entries.matched.18.id": "e1",
                                       "lines.entry-cost.value": 0.5}}}),
    ("a decision that names no file of its numbers", "refuse", "does not name a readable file",
     {"decided": EVERY, "typed": {49: {"inputs": DROP}}}),
    ("a seal whose frontmatter breaks after its weeks were recorded", "refuse",
     "the forward run's seal cannot be read: frontmatter line is not `key: value`",
     {"decided": EVERY, "files": {f"{STUDY}/PRE-REG.md": seal_text().replace("stop_rule: ", "stop_rule ")}}),
])

_prove("forward/gap-explained", [
    ("a gap split exactly into its sealed parts", "pass", None, {}),
    ("a split half a cent off", "pass", None, {"changes": {48: {"gap.unexplained": -3.005}}}),
    ("a part the seal does not name", "fail", "week 2026-48 splits the gap into other, which the seal does not name",
     {"changes": {48: {"gap.parts.other": 0.0}}}),
    ("parts that do not add up", "fail", "the parts and the remainder add up to -35, and live less replay is -30",
     {"changes": {48: {"gap.unexplained": -8.0}}}),
    ("a sealed part dropped", "fail", "week 2026-48 leaves out the sealed part(s) swap",
     {"changes": {48: {"gap.parts.swap": DROP}}}),
    ("half a cent off, where the project allows a tenth", "fail", "add up to -30.005, and live less replay is -30",
     {"changes": {48: {"gap.unexplained": -3.005}}, "rules": _rule("forward/gap-explained", "tolerance = 0.001")}),
    ("a part written as a word", "refuse", "the record.gap.parts.spread must be a number",
     {"changes": {48: {"gap.parts.spread": "a lot"}}}),
])

_prove("forward/conditions-stable", [
    ("one change, listed in its week's verdict", "pass", None, {"decided": EVERY, "changes": CHANGE_48}),
    ("the owner's own call carries no numbers", "pass", None,
     {"decided": EVERY, "changes": CHANGE_48, "owned": {48: "defer"}}),
    ("a change dropped from the stored numbers", "fail", "the record holds 1, the verdict lists 0",
     {"decided": EVERY, "changes": CHANGE_48, "typed": {48: {"numbers.conditions_changes": []}}}),
    ("a verdict with no numbers", "fail", "the record holds 1, the verdict lists none",
     {"decided": EVERY, "changes": CHANGE_48, "typed": {48: {"numbers": DROP}}}),
    ("no week decided yet", "refuse", "nothing was inspected", {"changes": CHANGE_48}),
])

_prove("forward/no-retune", [
    ("the same settings throughout", "pass", None, {"weeks": (48, 49, 50)}),
    ("a new run, sealed anew for new settings", "pass", None, {"files": {
        "work/fwd-2/PRE-REG.md": seal_text(settings="77c0aa11"),
        _week_path(50, "work/fwd-2"): json.dumps(changed(week_record(50), {"live.settings": "77c0aa11",
                                                                           "replay.settings": "77c0aa11"}))}}),
    ("week three on another fingerprint", "fail", "week 2026-50 traded the settings 77c0aa11, and the seal's are 3f9a0c1d",
     {"weeks": (48, 49, 50), "changes": {50: {"live.settings": "77c0aa11", "replay.settings": "77c0aa11"}}}),
    ("a record that is not JSON", "refuse", "the record is not valid JSON",
     {"files": {_week_path(50): '{"week": "2026-50"\n'}}),
])

FEW = {"seal": {"min_trades": 220},  # 40 live trades in week 48, 190 in week 49: each matched or extra
       "changes": {48: {"live.trades": 40, "entries.matched": matched(48, 39), "entries.missed.0.id": "m1"},
                   49: {"live.trades": 190, "entries.matched": matched(49, 189, 0.5), "entries.missed.0.id": "m1"}}}
_prove("forward/enough-trades", [
    ("a defer at 40 trades of 220, and a pass at 230", "pass", None, {**FEW, "decided": EVERY}),
    ("the owner's pass ahead of the count, with a grant for that week", "pass", None,
     {**FEW, "decided": EVERY, "owned": {48: "pass"}, "granted": (48,)}),
    ("a pass stored at 40 of 220 trades", "fail", "week 2026-48 is stored as a pass at 40 of the 220 trades",
     {**FEW, "decided": EVERY, "typed": {48: {"decision": "pass", "verdict": "pass"}}}),
    ("a seal that asks for 5 trades", "fail", "the seal asks for 5 trades before any pass, under this project's floor "
     "of 30", {"seal": {"min_trades": 5}}),
    ("the owner's pass with a grant for another week", "fail", "the owner passed week 2026-48 at 40 of the 220 trades "
     "the seal asks for, with no forward grant", {**FEW, "decided": EVERY, "owned": {48: "pass"}, "granted": (49,)}),
    ("a seal whose count cannot be read", "refuse", "the seal cannot be read as a forward seal",
     {"seal": {"min_trades": "many"}}),
    ("a count of live trades its entries do not hold", "refuse",
     "the record's live.trades is 200, and its entries hold 20 live entries",
     {**FEW, "changes": {48: {"live.trades": 200}}}),
])

_prove("forward/risk-line", [
    ("every week inside its risk line", "pass", None, {"decided": EVERY}),
    ("a fall past the line, stored as stop, and every week after it", "pass", None,
     {"decided": EVERY, "changes": RISKY}),
    ("the owner's overrule, with a grant for that week", "pass", None,
     {"decided": EVERY, "changes": RISKY, "owned": {49: "pass"}, "granted": (49,)}),
    ("a fall past the line stored as look-closer", "fail", "the risk line day-loss was passed in week 2026-48 (0.6, "
     "past its stop of 0.52), and week 2026-48 is stored as look-closer",
     {"decided": EVERY, "changes": RISKY, "typed": {48: {"decision": "look-closer", "verdict": "refuse"}}}),
    ("a later week passed", "fail", "and week 2026-49 is stored as pass",
     {"decided": EVERY, "changes": RISKY, "typed": {49: {"decision": "pass", "verdict": "pass"}}}),
    ("the owner's overrule with no grant", "fail", "and week 2026-49 is stored as pass",
     {"decided": EVERY, "changes": RISKY, "owned": {49: "pass"}}),
    ("the owner's stop word with a pass verdict, and no grant", "fail",
     "and week 2026-49 is stored as stop with the verdict pass",
     {"decided": EVERY, "changes": RISKY, "owned": {49: ("stop", "pass")}}),
    ("a risk figure missing from a week", "fail", "week 2026-49 has no figure for the sealed risk line day-loss",
     {"changes": {49: {"risk": {}}}}),
    ("a risk line the project requires, left out of the seal", "fail",
     "the seal draws no risk line for peak-drop, which this project requires",
     {"rules": _rule("forward/risk-line", 'required = ["peak-drop"]')}),
    ("a risk figure written as a word", "refuse", "the record.risk.day-loss must be a number",
     {"changes": {48: {"risk.day-loss": "high"}}}),
])
