"""Gate: timeline — each task's start and state are written so a machine can hold them to the record.

A timeline is one table, written by hand, of when each task starts and where it stands
(`themis.timeline` reads it). Its page, its heading and the project's states are named under
`[timeline]` in the manifest. A project with no `[timeline]` table has nothing here to check, and
each of these rules says so: it is "not configured".
"""

from __future__ import annotations

import posixpath
from typing import TYPE_CHECKING, Any

from themis import timeline
from themis.rule import Context, proof, rule

if TYPE_CHECKING:
    from themis.proofs import World

UNSET = "name the timeline's page, its heading and the project's states under [timeline]"
NO_TABLE = "no table under the heading has the columns When, Task, Status, Who and Plan"


def _open(ctx: Context) -> tuple[str, dict[str, Any], timeline.Timeline] | None:
    """The page, the states, and what the page holds; None, after a refusal, when it cannot be read."""
    config = ctx.manifest.table("timeline")
    if not config:
        ctx.not_configured(UNSET)
    page = config["page"]
    text = ctx.read(page)
    if text is None:
        ctx.refuse(f"the timeline's page {page} is missing or is not text", where=page,
                   fix="restore the page, or correct page under [timeline]")
        return None
    return page, config["states"], timeline.parse(text, config["heading"], posixpath.dirname(page))


def _someone(cell: str | None) -> bool:
    return (cell or "").strip() not in ("", "-", "–", "—")


# -- timeline/shape -----------------------------------------------------------------------------


@rule(
    "timeline/shape",
    "Each row has a start, a state from the project's list, a person and a plan, and no two rows share a number.",
    learned="A timeline's legend named five states and its rows used fourteen, so no reader could tell what had "
            "started.",
)
def shape(ctx: Context) -> None:
    opened = _open(ctx)
    if opened is None:
        return
    page, states, found = opened
    heading = ctx.manifest.table("timeline")["heading"]
    if found.heading_line is None:
        ctx.breach(f"the page has no heading {heading}", where=page,
                   fix="put the timeline under its heading, or correct heading under [timeline]")
        return
    if found.table_line is None:
        ctx.breach(NO_TABLE, where=page, line=found.heading_line,
                   fix="write the table under the heading: When, Task, Status, Who and Plan, one row a task")
        return
    numbered: dict[str, int] = {}
    for row in found.rows:
        ctx.inspect()

        def say(message: str, fix: str, row: timeline.Row = row) -> None:
            ctx.breach(f"{row.name}: {message}", where=page, line=row.line, fix=fix)

        if row.when is None:
            say(str(row.when_problem), "write a day with its year (Mon 30 Nov 2026), a month or a span of months "
                                       "(Feb – Mar 2027), or After and the rows (After 1, 2)")
        if row.state is None:
            say("the Status cell does not begin with a state in bold", "begin it with one of the states, as **Next**")
        elif row.state not in states:
            say(f"**{row.state}** is not one of the timeline's states ({', '.join(states)})",
                "write one of them; a new state is the owner's to add, under [timeline.states]")
        elif states[row.state].get("started", True) and row.day is None:
            say(row.day_problem or f"**{row.state}** is a started state, and the cell gives no day after it",
                f"write the day after the state, as **{row.state}** 26 Nov 2026")
        if row.until_problem:
            say(row.until_problem, "write until, then a day with its year, rows, or a person's go, as until your go")
        if not _someone(row.cells.get("who")):
            say("Who names no one", "write who does the task")
        if not row.plan_links:
            say("the Plan cell holds no link", "link the plan, even when the row above links the same one")
        if row.number in numbered:
            say(f"two rows are numbered {row.number}: lines {numbered[row.number]} and {row.line}",
                "give each task a number of its own")
        elif row.number:
            numbered[row.number] = row.line


# -- the worlds ---------------------------------------------------------------------------------

PAGE = "plans/README.md"
STATES = """
    [timeline]
    page = "plans/README.md"
    heading = "Timeline"

    [timeline.states]
    Planned = { started = false }
    Next = { started = false }
    Waits = { started = false, names = "rows" }
    "Under way" = {}
    Paused = { names = "until" }
    Sealed = { cites = ["research/*/PRE-REG*.md"] }
    Sent = { cites = ["plans/**", "docs/**"] }
    Built = { finished = true, cites = ["pr"] }
    Decided = { finished = true, cites = ["docs/decisions.md"] }
    Done = { finished = true, cites = ["pr", "docs/**", "research/**"] }
"""
HEAD = """# Plans

## Timeline

The home of every start date. One row a task; only the head of each cell is read.

| State | Means |
|---|---|
| **Planned** · **Next** | Not started: a later date · free to start |
| **Waits** | Not started, on other rows |

| When | Task | Status | Who | Gate | Plan |
|---|---|---|---|---|---|
"""
TAIL = """
## Later

| When | Task | Status | Who | Gate | Plan |
|---|---|---|---|---|---|
| Someday | Not read: under another heading | **Ready** | | – | the same |
"""
#: The honest page, in the shape the rules hold it to: every state, each kind of When, a moved row,
#: another repository's pull request beside a record here, and a wait on a row under way.
ROWS = (
    "| Thu 26 Nov 2026 | 1. **Finish the rehearsal:** begun Mon 23 Nov 2026, the rest moved to Thursday | "
    "**Done** 26 Nov 2026: #12, [the other repo's #3](https://git.example.invalid/team/other/pull/3); "
    "[the record](../docs/rehearsal.md) | Opus, you | – | [dashboard](active/dashboard.md) |",
    "| Thu 26 Nov 2026 | 2. The look | **Under way** 22 Nov 2026: parity scored (#14) | Opus | – | "
    "[the look](active/look.md) |",
    "| Thu 26 Nov 2026 | 3. The range tool | **Paused** 26 Nov 2026 until your go, for a session of its own | "
    "Opus; Fable designs | – | [range](active/range.md) |",
    "| Thu 26 Nov 2026 | 4. Why the curve is flat | **Built** 26 Nov 2026: #13. Compounding | Opus | – | "
    "[curve](../docs/curve.md) |",
    "| Thu 26 Nov 2026 | 5. The forward check | **Sealed** 26 Nov 2026: "
    "[the seal](../research/2026-11-26_check/PRE-REG.md) (#15) | Opus | – | [check](active/check.md) |",
    "| Thu 26 Nov 2026 | 6. Send the email | **Sent** 26 Nov 2026: [the email](active/look.md#the-email) | You | – | "
    "[the look](active/look.md) |",
    "| Thu 26 Nov 2026 | 7. The path | **Decided** 26 Nov 2026: [decisions](../docs/decisions.md): the plan stays | "
    "You decide | – | [money](active/money.md) |",
    "| Sun 29 Nov 2026 | Switch on | **Next**: task 1 done | You | – | [forward](active/forward.md) |",
    "| Mon 30 Nov 2026 | The forward run's day 1 | **Planned** | Opus | – | [forward](active/forward.md) |",
    "| Dec 2026 | 8. The month-1 check | **Planned** | Opus | – | [forward](active/forward.md) |",
    "| Feb – Mar 2027 | The first live month | **Planned** | You | row 8 | [money](active/money.md) |",
    "| ~22 Feb 2027 | The launch | **Waits** on 2 | You | – | [selling](../docs/selling.md) |",
    "| After 8 | 9. The next step | **Planned** | Opus | – | [money](active/money.md) |",
)


def _page(*rows: str, swap: tuple[str, str] | None = None) -> str:
    """The timeline page with these rows (the honest ones when none are given), and one text swapped."""
    text = HEAD + "\n".join(rows or ROWS) + "\n" + TAIL
    if swap is not None:
        if text.count(swap[0]) != 1:
            raise ValueError(f"the text to swap occurs {text.count(swap[0])} times: {swap[0]!r}")
        text = text.replace(*swap)
    return text


def _timeline(world: World, *rows: str, swap: tuple[str, str] | None = None, setup: str = "") -> None:
    world.manifest(STATES + setup)
    world.write(PAGE, _page(*rows, swap=swap))


# -- timeline/shape's proofs --------------------------------------------------------------------


@proof("timeline/shape", "the honest page: every state, each kind of When, the legend and a later table unread",
       expect="pass")
def _(world: World) -> None:
    _timeline(world)


@proof("timeline/shape", "rows with no number, and a span of months across a year", expect="pass")
def _(world: World) -> None:
    _timeline(world, ROWS[7], "| Nov 2026 – Jan 2027 | The quarter | **Planned** | You | – | [money](active/money.md) |")


@proof("timeline/shape", "a state off the list", expect="fail", contains="**Ready** is not one of the timeline's states")
def _(world: World) -> None:
    _timeline(world, swap=("**Next**: task 1 done", "**Ready**: task 1 done"))


@proof("timeline/shape", "a weekday that is not the day's", expect="fail", contains="Mon 29 Nov 2026 is a Sunday")
def _(world: World) -> None:
    _timeline(world, swap=("| Sun 29 Nov 2026 |", "| Mon 29 Nov 2026 |"))


@proof("timeline/shape", "a date with no year", expect="fail", contains="the day Mon 30 Nov has no year")
def _(world: World) -> None:
    _timeline(world, swap=("| Mon 30 Nov 2026 |", "| Mon 30 Nov |"))


@proof("timeline/shape", "two rows numbered 9", expect="fail", contains="two rows are numbered 9")
def _(world: World) -> None:
    _timeline(world, swap=("8. The month-1 check", "9. The month-1 check"))


@proof("timeline/shape", "a blank When", expect="fail", contains="the When cell is blank")
def _(world: World) -> None:
    _timeline(world, swap=("| Dec 2026 |", "| |"))


@proof("timeline/shape", "a When that is no date", expect="fail", contains="When reads 'After your calls'")
def _(world: World) -> None:
    _timeline(world, swap=("| After 8 |", "| After your calls |"))


@proof("timeline/shape", "a started state that gives no day", expect="fail",
       contains="**Under way** is a started state, and the cell gives no day")
def _(world: World) -> None:
    _timeline(world, swap=("**Under way** 22 Nov 2026:", "**Under way**:"))


@proof("timeline/shape", "a started state whose day has no year", expect="fail", contains="the day 26 Nov has no year")
def _(world: World) -> None:
    _timeline(world, swap=("**Built** 26 Nov 2026:", "**Built** 26 Nov:"))


@proof("timeline/shape", "a pause until a day with no year", expect="fail",
       contains="row 3: the day Mon 23 Nov has no year")
def _(world: World) -> None:
    _timeline(world, swap=("until your go", "until Mon 23 Nov"))


@proof("timeline/shape", "a pause until a weekday that is not the day's", expect="fail",
       contains="row 3: Wed 1 Dec 2026 is a Tuesday")
def _(world: World) -> None:
    _timeline(world, swap=("until your go", "until Wed 1 Dec 2026"))


@proof("timeline/shape", "a Status cell with no state", expect="fail", contains="does not begin with a state in bold")
def _(world: World) -> None:
    _timeline(world, swap=("**Waits** on 2", "waits on 2"))


@proof("timeline/shape", "no one in Who", expect="fail", contains="Who names no one")
def _(world: World) -> None:
    _timeline(world, swap=("| You | row 8 |", "| – | row 8 |"))


@proof("timeline/shape", "a plan written as the same", expect="fail", contains="the Plan cell holds no link")
def _(world: World) -> None:
    _timeline(world, swap=("| Opus | – | [money](active/money.md) |", "| Opus | – | the same |"))


@proof("timeline/shape", "a project's own list of states binds", expect="fail",
       contains="**Sent** is not one of the timeline's states")
def _(world: World) -> None:
    world.manifest(STATES.replace('    Sent = { cites = ["plans/**", "docs/**"] }\n', ""))
    world.write(PAGE, _page())


@proof("timeline/shape", "the page has no such heading", expect="fail", contains="the page has no heading Timeline")
def _(world: World) -> None:
    _timeline(world)
    world.write(PAGE, _page().replace("## Timeline", "## Dates"))


@proof("timeline/shape", "the table lost a column", expect="fail", contains=NO_TABLE)
def _(world: World) -> None:
    _timeline(world)
    world.write(PAGE, _page().replace("| When | Task | Status | Who | Gate | Plan |\n|---|", "| When | Task |\n|---|", 1))


@proof("timeline/shape", "the page is missing", expect="refuse", contains="is missing or is not text")
def _(world: World) -> None:
    world.manifest(STATES)
    world.write("README.md", "# A project\n")
