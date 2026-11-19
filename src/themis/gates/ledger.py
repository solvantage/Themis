"""Gate: ledger — every attempt is counted.

The ledger holds one record for each unit of work, made before the work runs. A count of attempts
is honest only when it also holds the attempts that led nowhere, so these rules read the ledger
against the results on disk, and against the decisions that used its count.

A ledger record names its unit in `work`, by the unit's path or by its folder name alone, when no
other unit has that folder name. Beside
`work`, the rules here read these fields of a ledger record:

    state     "promised" (logged, no result yet), "done" (it has results) or "dropped" (stopped)
    reason    why a dropped attempt was stopped
    logged    the day the attempt was logged, as YYYY-MM-DD; a record with no day always counts
    group     optional: the family of attempts this one is counted with
"""

from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING, Any

from themis import work
from themis.gates.order import RESULTS, WORK
from themis.rule import Context, Param, proof, rule

if TYPE_CHECKING:
    from themis.proofs import World

STATES = ("promised", "done", "dropped")
GATES = Param("gates", [str], None, "larger", "the gates whose decisions depend on how many attempts were made")
COUNT_KEY = Param("count_key", str, "attempts", None, "the key under a decision's numbers that holds the count it used")


def _units(ctx: Context) -> dict[str, list[str]]:
    try:
        return work.units(ctx.all_files, ctx.param("work"))
    except ValueError as error:
        ctx.refuse(str(error), where="themis.toml", fix="name the unit folders at one depth, such as work/*")
        return {}


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _whole(value: Any) -> bool:
    """True for a whole number. True and false are not numbers, and 3.0 is as whole as 3."""
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, float) and value.is_integer())


def _day(value: Any) -> dt.date | None:
    """The calendar day in a date, a time or ISO text, or None when no day can be read."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(value.strip()[:10]) if isinstance(value, str) else None
    except ValueError:
        return None


# -- ledger/complete ----------------------------------------------------------------------------


@rule(
    "ledger/complete",
    "No result exists without a ledger record, and every ledger record ends with a result or a stated reason.",
    params=(WORK, RESULTS),
    requires=("work", "results"),
    learned="Attempts that led nowhere were left out of the ledger, so the one that worked looked like the only one.",
)
def complete(ctx: Context) -> None:
    units = _units(ctx)
    held = {unit: work.inside(unit, files, ctx.param("results")) for unit, files in sorted(units.items())}
    bound = ctx.bound(units)  # a unit begun before the rule's start date is not held to it
    rows = ctx.records("ledger")
    named = {work.named(held, str(row.get("work"))) for row in rows}
    for unit, results in held.items():
        if not results or unit not in bound:
            continue  # a folder with no result yet has nothing to count
        ctx.inspect()
        if unit not in named:
            ctx.breach("this unit holds results and no ledger record names it", where=unit,
                       fix="add a ledger record whose work is this unit; an attempt that failed is counted too; "
                           "a folder name that several units share names none of them")
    for row in rows:
        unit = work.named(held, str(row.get("work")))
        if ctx.predates([row.path]) or (unit is not None and unit not in bound):
            continue  # logged before the rule's start date, or the record of a unit begun before it
        ctx.inspect()
        state = row.get("state")
        results = held.get(unit or "", [])
        if state not in STATES:
            said = "has no state" if state is None else f"has the state {state!r}"
            ctx.breach(f"this ledger record {said}; a state is promised, done or dropped", where=row.path,
                       fix='set state to "promised", "done" or "dropped"')
        elif state == "done" and not results:
            ctx.breach("this ledger record says done, but its unit holds no result", where=row.path,
                       fix="add the unit's results, or set state to dropped and give the reason; "
                           "check that work names the unit's folder")
        elif state == "dropped" and not _text(row.get("reason")):
            ctx.breach("this ledger record says dropped and gives no reason", where=row.path,
                       fix="add a reason: one line on why the attempt was stopped")


COMPLETE_SETUP = """
    [rules."ledger/complete"]
    work = "work/*"
    results = ["results/**"]
"""


def _row(world: World, name: str, state: str | None = "done", **fields: Any) -> None:
    """A ledger record for the unit work/<name>, with its state and any other fields."""
    lines = [f'work = "work/{name}"'] + ([f'state = "{state}"'] if state is not None else [])
    lines += [f"{key} = {json.dumps(value)}" for key, value in fields.items()]
    world.write(f"ledger/{name}.toml", "\n".join(lines) + "\n")


@proof("ledger/complete", "a finished unit with its ledger record", expect="pass")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP)
    _row(world, "a")
    world.write("work/a/results/out.csv", "1\n")


@proof("ledger/complete", "a promise with no result yet is honest", expect="pass")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP)
    _row(world, "a", "promised")
    world.write("work/a/PLAN.md", "the plan\n")


@proof("ledger/complete", "a dropped attempt that says why", expect="pass")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP)
    _row(world, "a", "dropped", reason="the data source closed before the run")


@proof("ledger/complete", "a record that names its unit by folder name alone", expect="pass")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP)
    world.write("ledger/a.toml", 'work = "a"\nstate = "done"\n')
    world.write("work/a/results/out.csv", "1\n")


@proof("ledger/complete", "a folder that holds notes and no result needs no record", expect="pass")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP)
    _row(world, "a")
    world.write("work/a/results/out.csv", "1\n")
    world.write("work/b/notes.md", "an idea, not run yet\n")


@proof("ledger/complete", "work in two places, each unit with its record", expect="pass")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP.replace('"work/*"', '["work/*", "lab/*/runs"]'))
    _row(world, "a")
    world.write("work/a/results/out.csv", "1\n")
    world.write("ledger/b.toml", 'work = "lab/b/runs"\nstate = "done"\n')
    world.write("lab/b/runs/results/out.csv", "1\n")


@proof("ledger/complete", "work in two places, and a unit in the second with no record", expect="fail",
       contains="no ledger record names it")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP.replace('"work/*"', '["work/*", "lab/*/runs"]'))
    _row(world, "a")
    world.write("work/a/results/out.csv", "1\n")
    world.write("lab/b/runs/results/out.csv", "1\n")


@proof("ledger/complete", "results that no ledger record names", expect="fail", contains="no ledger record names it")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP)
    world.write("work/a/results/out.csv", "1\n")


@proof("ledger/complete", "units that share a folder name, each named by its path", expect="pass")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP.replace('"work/*"', '"work/*/*"'))
    for name in ("a", "b"):
        world.write(f"ledger/{name}.toml", f'work = "work/{name}/tune"\nstate = "done"\n')
        world.write(f"work/{name}/tune/results/out.csv", "1\n")


@proof("ledger/complete", "a folder name two units share names neither of them", expect="fail",
       contains="no ledger record names it")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP.replace('"work/*"', '"work/*/*"'))
    world.write("ledger/tune.toml", 'work = "tune"\nstate = "done"\n')
    world.write("work/a/tune/results/out.csv", "1\n")
    world.write("work/b/tune/results/out.csv", "1\n")


@proof("ledger/complete", "a record for another unit does not cover this one", expect="fail",
       contains="no ledger record names it")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP)
    _row(world, "a")
    world.write("work/a/results/out.csv", "1\n")
    world.write("work/b/results/out.csv", "1\n")


@proof("ledger/complete", "a record that says done, with no result in its unit", expect="fail",
       contains="its unit holds no result")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP)
    _row(world, "a")
    world.write("work/a/PLAN.md", "the plan\n")


@proof("ledger/complete", "a dropped attempt with no reason", expect="fail", contains="gives no reason")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP)
    _row(world, "a", "dropped")


@proof("ledger/complete", "a dropped attempt whose reason is blank", expect="fail", contains="gives no reason")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP)
    _row(world, "a", "dropped", reason="  ")


@proof("ledger/complete", "a state that is not one of the three", expect="fail", contains="has the state 'finished'")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP)
    _row(world, "a", "finished")
    world.write("work/a/results/out.csv", "1\n")


@proof("ledger/complete", "a record with no state", expect="fail", contains="has no state")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP)
    _row(world, "a", None)
    world.write("work/a/results/out.csv", "1\n")


@proof("ledger/complete", "a ledger record that cannot be read", expect="refuse", contains="is not valid TOML")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP)
    world.write("ledger/a.toml", 'work = "work/a\n')


@proof("ledger/complete", "a ledger record that names no unit", expect="refuse", contains="work is required")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP)
    world.write("ledger/a.toml", 'state = "promised"\n')


# -- ledger/count-used --------------------------------------------------------------------------


@rule(
    "ledger/count-used",
    "A decision that depends on how many attempts were made uses the ledger's own count.",
    params=(GATES, COUNT_KEY),
    requires=("gates",),
    learned="A result was judged as one attempt of a few, when the ledger held many more.",
)
def count_used(ctx: Context) -> None:
    key = ctx.param("count_key")
    decisions = [record for record in ctx.records("decision") if record.get("gate") in ctx.param("gates")]
    rows = ctx.records("ledger")
    if decisions and not rows:
        ctx.refuse("the ledger holds no record that can be read, so the attempts cannot be counted",
                   fix="log each attempt in the ledger before a decision counts them")
        return
    days = {row.path: _day(row.get("logged")) for row in rows}
    for row in rows:
        if row.get("logged") is not None and days[row.path] is None:
            ctx.refuse("this ledger record's logged day cannot be read", where=row.path,
                       fix="write logged as YYYY-MM-DD")
    for record in decisions:
        if ctx.predates([record.path]):
            continue  # a decision that reached the main line before the rule's start date
        ctx.inspect()
        decided = _day(record.get("decided_at"))
        if decided is None:
            ctx.refuse("this decision's date cannot be read, so the attempts before it cannot be counted",
                       where=record.path, fix="write decided_at as an ISO date, such as 2026-01-31")
            continue
        numbers = record.get("numbers") or {}
        group, stated = numbers.get("group"), numbers.get(key)
        count = sum(
            1 for row in rows
            if (group is None or row.get("group") == group) and (days[row.path] is None or days[row.path] <= decided)
        )
        scope = f" in the group {group}" if group is not None else ""
        if not _whole(stated):
            ctx.breach(f"this decision states no whole number under numbers.{key}", where=record.path,
                       fix=f"issue the decision again with the ledger's count{scope}, {count}, as numbers.{key}")
        elif stated < count:
            ctx.breach(f"this decision used a count of {int(stated)}, but the ledger holds {count} attempts{scope} "
                       f"up to {decided.isoformat()}", where=record.path,
                       fix="issue the decision again with the ledger's own count; every logged attempt counts")


@proof("ledger/complete", "units and records from before the start date are exempt", expect="pass")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP + '    since = "2026-06-01"\n')
    world.write("work/old/results/out.csv", "1\n")  # no record: it predates the rule
    _row(world, "gone", "dropped")  # no reason: it predates the rule
    world.commit("before the rule")
    world.on("2026-07-01")
    _row(world, "a")
    world.write("work/a/results/out.csv", "1\n")
    world.commit("after the rule")


@proof("ledger/complete", "a unit begun after the start date is still held to it", expect="fail",
       contains="no ledger record names it")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP + '    since = "2026-06-01"\n')
    world.write("work/old/results/out.csv", "1\n")
    world.commit("before the rule")
    world.on("2026-07-01")
    world.write("work/a/results/out.csv", "1\n")
    world.commit("after the rule")


@proof("ledger/complete", "a record logged after the start date is still held to it", expect="fail",
       contains="gives no reason")
def _(world: World) -> None:
    world.manifest(COMPLETE_SETUP + '    since = "2026-06-01"\n')
    world.commit("before the rule")
    world.on("2026-07-01")
    _row(world, "gone", "dropped")
    world.commit("after the rule")


COUNT_SETUP = """
    [rules."ledger/count-used"]
    gates = ["threshold"]
"""


def _decision(world: World, name: str = "a", **changes: Any) -> None:
    fields = {"work": "work/a", "decision": "keep", "verdict": "pass", "gate": "threshold", "gate_version": "1",
              "decided_at": "2026-02-01T09:00:00+00:00", "numbers": {"attempts": 3}}
    world.write(f"decisions/{name}.json", json.dumps({**fields, **changes}))


def _three(world: World, **fields: Any) -> None:
    """Three attempts in the ledger, all logged in January, before the decision of 1 February."""
    world.manifest(COUNT_SETUP)
    for number, name in enumerate(("a", "b", "c"), start=10):
        _row(world, name, logged=f"2026-01-{number}", **fields)


@proof("ledger/count-used", "the decision used the ledger's count", expect="pass")
def _(world: World) -> None:
    _three(world)
    _decision(world)


@proof("ledger/count-used", "a count above the ledger's is not a breach", expect="pass")
def _(world: World) -> None:
    _three(world)
    _decision(world, numbers={"attempts": 5})


@proof("ledger/count-used", "an attempt logged after the decision is not counted", expect="pass")
def _(world: World) -> None:
    _three(world)
    _row(world, "d", "promised", logged="2026-02-02")
    _decision(world)


@proof("ledger/count-used", "a day written as a bare date is read like text", expect="pass")
def _(world: World) -> None:
    _three(world)
    world.write("ledger/d.toml", 'work = "work/d"\nstate = "promised"\nlogged = 2026-02-02\n')
    _decision(world)


@proof("ledger/count-used", "a decision that names a group counts only that group", expect="pass")
def _(world: World) -> None:
    _three(world, group="entries")
    _row(world, "d", logged="2026-01-20", group="exits")
    _decision(world, numbers={"attempts": 3, "group": "entries"})


@proof("ledger/count-used", "a decision from a gate that does not use the count is left alone", expect="pass")
def _(world: World) -> None:
    _three(world)
    _decision(world)
    _decision(world, "b", gate="checklist", numbers={})


@proof("ledger/count-used", "a decision that counted fewer attempts than the ledger holds", expect="fail",
       contains="used a count of 1, but the ledger holds 3 attempts")
def _(world: World) -> None:
    _three(world)
    _decision(world, numbers={"attempts": 1})


@proof("ledger/count-used", "an attempt logged on the decision's own day counts", expect="fail",
       contains="but the ledger holds 4 attempts")
def _(world: World) -> None:
    _three(world)
    _row(world, "d", "promised", logged="2026-02-01")
    _decision(world)


@proof("ledger/count-used", "an attempt with no logged day counts", expect="fail",
       contains="but the ledger holds 4 attempts")
def _(world: World) -> None:
    _three(world)
    _row(world, "d", "dropped", reason="stopped early")
    _decision(world)


@proof("ledger/count-used", "a group's count that is short", expect="fail",
       contains="the ledger holds 3 attempts in the group entries")
def _(world: World) -> None:
    _three(world, group="entries")
    _decision(world, numbers={"attempts": 2, "group": "entries"})


@proof("ledger/count-used", "a decision with no count", expect="fail", contains="states no whole number")
def _(world: World) -> None:
    _three(world)
    _decision(world, numbers={"uplift": 0.04})


@proof("ledger/count-used", "a count written as text", expect="fail", contains="states no whole number")
def _(world: World) -> None:
    _three(world)
    _decision(world, numbers={"attempts": "three"})


@proof("ledger/count-used", "a project's own count key is the one read", expect="fail",
       contains="states no whole number under numbers.trials")
def _(world: World) -> None:
    _three(world)
    world.manifest(COUNT_SETUP + '    count_key = "trials"\n')
    _decision(world)


@proof("ledger/count-used", "a decision from before the start date is exempt; a later one is held", expect="fail",
       contains="used a count of 1, but the ledger holds 3 attempts")
def _(world: World) -> None:
    _three(world)
    world.manifest(COUNT_SETUP + '    since = "2026-06-01"\n')
    _decision(world, "old", numbers={"attempts": 0})
    world.commit("before the rule")
    world.on("2026-07-01")
    _decision(world, numbers={"attempts": 1})
    world.commit("after the rule")


@proof("ledger/count-used", "only decisions from before the start date: nothing to hold", expect="refuse",
       contains="nothing was inspected")
def _(world: World) -> None:
    _three(world)
    world.manifest(COUNT_SETUP + '    since = "2026-06-01"\n')
    _decision(world, numbers={"attempts": 1})
    world.commit("before the rule")


@proof("ledger/count-used", "an empty ledger cannot be counted", expect="refuse", contains="the ledger holds no record")
def _(world: World) -> None:
    world.manifest(COUNT_SETUP)
    _decision(world, numbers={"attempts": 1})


@proof("ledger/count-used", "a decision whose date cannot be read", expect="refuse", contains="date cannot be read")
def _(world: World) -> None:
    _three(world)
    _decision(world, decided_at="last week")


@proof("ledger/count-used", "a logged day that cannot be read", expect="refuse", contains="logged day cannot be read")
def _(world: World) -> None:
    _three(world)
    _row(world, "d", "promised", logged="early January")
    _decision(world, numbers={"attempts": 4})
