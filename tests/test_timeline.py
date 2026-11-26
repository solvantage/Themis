"""The timeline reader, the gate when nothing is configured, and the directions of [timeline]'s keys.

The rules' own worlds live beside them, in themis/gates/timeline.py. These tests hold the reader's
grammar to examples, and the configuration guard to the design: a new [timeline] table is a
tightening, a state added to it later is a weakening.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from themis import configguard, engine, gates, manifest, pack, timeline
from themis.gates.timeline import PAGE, STATES, _page
from themis.proofs import World
from themis.rule import RULES

gates.load_all()


def rows(*lines: str) -> tuple[timeline.Row, ...]:
    table = "## Timeline\n\n| When | Task | Status | Who | Plan |\n|---|---|---|---|---|\n" + "\n".join(lines) + "\n"
    return timeline.parse(table, "Timeline", "plans").rows


@pytest.mark.parametrize(("when", "by", "after"), [
    ("Mon 30 Nov 2026", dt.date(2026, 11, 30), ()),
    ("30 November 2026, 09:00", dt.date(2026, 11, 30), ()),
    ("~22 Feb 2027", dt.date(2027, 2, 28), ()),
    ("Mar 2027", dt.date(2027, 3, 31), ()),
    ("Feb – Mar 2027", dt.date(2027, 3, 31), ()),
    ("Nov 2026 - Jan 2027", dt.date(2027, 1, 31), ()),
    ("**Apr 2027**", dt.date(2027, 4, 30), ()),
    ("After 1–3, 0b and 7", None, ("1", "2", "3", "0b", "7")),
])
def test_each_kind_of_when_is_read(when: str, by: dt.date | None, after: tuple[str, ...]) -> None:
    [row] = rows(f"| {when} | A task | **Planned** | You | [plan](active/a.md) |")
    assert row.when is not None, row.when_problem
    assert (row.when.by, row.when.after) == (by, after)


@pytest.mark.parametrize(("when", "problem"), [
    ("", "the When cell is blank"),
    ("Mon 29 Nov 2026", "Mon 29 Nov 2026 is a Sunday"),
    ("Mon 23 Nov, ~08:00", "the day Mon 23 Nov has no year"),
    ("31 Nov 2026", "31 Nov 2026 is not a day of the calendar"),
    ("Mar", "the month Mar has no year"),
    ("Early Mar 2027", "When reads 'Early Mar 2027'"),
])
def test_a_when_that_cannot_be_read_says_why(when: str, problem: str) -> None:
    [row] = rows(f"| {when} | A task | **Planned** | You | [plan](active/a.md) |")
    assert row.when is None and problem in str(row.when_problem)


def test_the_status_cell_gives_its_state_day_waits_and_citations() -> None:
    done, waits, paused, gone, person = rows(
        "| Thu 26 Nov 2026 | 0b. Migrate | **Done** 26 Nov 2026: #123, [Other #1](https://git.example.invalid/o/r/pull/1),"
        " [the data](../research/x/README.md) (#143) | Opus | [plan](active/a.md) |",
        "| ~22 Feb 2027 | The launch | **Waits** on 1–3: after the check | You | [plan](active/a.md) |",
        "| Thu 26 Nov 2026 | 3. Range | **Paused** 26 Nov 2026 until 4 and 5 | Opus | [plan](active/b.md) |",
        "| Thu 26 Nov 2026 | 4. Look | **Paused** Thu 26 Nov 2026 until Mon 30 Nov 2026 | Opus | [plan](active/b.md) |",
        "| Thu 26 Nov 2026 | 5. Mirror | **Paused** 26 Nov 2026 until the owner’s go, later | Opus | [plan](active/b.md) |",
    )
    assert (done.number, done.state, done.day, done.prs) == ("0b", "Done", dt.date(2026, 11, 26), (123, 143))
    assert done.other_prs == ("https://git.example.invalid/o/r/pull/1",)
    assert done.cited == ("research/x/README.md",) and "plans/active/a.md" in done.linked
    assert (waits.state, waits.day, waits.on) == ("Waits", None, ("1", "2", "3"))
    assert (paused.until_rows, paused.until_day) == (("4", "5"), None)
    assert gone.until_day == dt.date(2026, 11, 30)
    assert person.until == "the owner’s go" and person.until_problem is None


def test_a_fenced_example_and_a_table_under_another_heading_are_not_read() -> None:
    fenced = "## Timeline\n\n```\n| When | Task | Status | Who | Plan |\n|---|---|---|---|---|\n```\n"
    assert timeline.parse(fenced, "Timeline").table_line is None
    found = timeline.parse(_page(), "Timeline", "plans")
    assert found.heading_line == 3 and len(found.rows) == 13
    assert timeline.parse(_page(), "Dates").heading_line is None


def test_the_gate_is_silent_in_a_project_with_no_timeline(tmp_path: Path) -> None:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.write("README.md", "# A project\n")
    loaded = manifest.load(world.root)
    result = engine.run_rule(RULES["timeline/shape"], loaded, force=True)
    assert (result.status, result.verdict, result.findings) == ("not configured", None, ())


def test_an_unknown_key_or_state_option_in_the_timeline_table_is_refused(tmp_path: Path) -> None:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest(STATES.replace("Planned = { started = false }", 'Planned = { started = false, colour = "red" }')
                   .replace('heading = "Timeline"', 'heading = "Timeline"\n    extra = 1'))
    world.write(PAGE, _page())
    problems = manifest.load(world.root).problems
    assert any("colour is not a known key" in problem for problem in problems), problems
    assert any("timeline.extra is not a known key" in problem for problem in problems), problems


TIMELINE = {"page": "plans/README.md", "heading": "Timeline",
            "states": {"Planned": {"started": False}, "Built": {"finished": True, "cites": ["pr"]}}}


def _with(**states: dict) -> dict:
    return {"timeline": {**TIMELINE, "states": {**TIMELINE["states"], **states}}}


def _without(name: str) -> dict:
    return {"timeline": {**TIMELINE, "states": {key: value for key, value in TIMELINE["states"].items() if key != name}}}


@pytest.mark.parametrize(("old", "new", "kind"), [
    ({}, {"timeline": TIMELINE}, "tightening"),  # a new table, its states among it
    ({"timeline": TIMELINE}, _with(Ready={}), "weakening"),  # a state added later lets a row pass
    ({"timeline": TIMELINE}, _without("Planned"), "tightening"),
    ({"timeline": TIMELINE}, _with(Planned={"started": False, "names": "rows"}), "tightening"),  # a wait must name rows
    ({"timeline": TIMELINE}, _with(Built={"finished": True, "cites": ["pr", "docs/**"]}), "weakening"),
    ({"timeline": TIMELINE}, _with(Built={"finished": True}), "weakening"),
    ({"timeline": TIMELINE}, _with(Planned={"started": True}), "weakening"),
    ({"timeline": TIMELINE}, {"timeline": {**TIMELINE, "page": "docs/plans.md"}}, "weakening"),
    ({"timeline": TIMELINE}, {}, "weakening"),
])
def test_each_change_to_the_timeline_table_is_classified(old: dict, new: dict, kind: str) -> None:
    kinds = {change.kind for change in configguard.classify(old, new)}
    assert kinds == {kind}, configguard.classify(old, new)


def test_a_new_allow_table_inside_a_table_in_force_is_still_a_weakening() -> None:
    """Only a new [timeline] as a whole is read as a tightening. A table of entries a pack declares
    smaller (it allows), first written in a new sub-table of a table already in force, lets more through."""
    keys = {"gates.allow": pack.Key("smaller")}
    old, new = {"work": "research/*"}, {"work": "research/*", "gates": {"allow": {"quick": {"looks": 2}}}}
    changes = configguard._table_changes("[field]", old, new, keys)
    assert {change.kind for change in changes} == {"weakening"}, changes
