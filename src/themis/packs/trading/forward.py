"""Gate: forward — a live run, held week by week against a replay of the same dates.

A forward run trades live under sealed settings, and each week the same settings are replayed over
the same dates, from the same start. It is one study whose seal is of kind `forward`:

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
a line must be past its stop before it stops the run (1 when unset), and `min` the least sample it
is read on (0 when unset). A risk line has only a `stop`. A range is the live money on a day since
the start, `{low, high}`.
"""

from __future__ import annotations

import math
import re
import tomllib
from dataclasses import dataclass
from typing import Any

from themis import schema
from themis.schema import Choice, Required

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
