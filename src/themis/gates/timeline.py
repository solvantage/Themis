"""Gate: timeline — each task's start and state are written so a machine can hold them to the record.

A timeline is one table, written by hand, of when each task starts and where it stands
(`themis.timeline` reads it). Its page, its heading and the project's states are named under
`[timeline]` in the manifest. A project with no `[timeline]` table has nothing here to check, and
each of these rules says so: it is "not configured".
"""

from __future__ import annotations

import datetime as dt
import posixpath
from typing import TYPE_CHECKING, Any

from themis import paths, timeline
from themis.manifest import MANIFEST_FILE
from themis.rule import Context, Param, proof, rule

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


Known = list[tuple[timeline.Row, dict[str, Any]]]


def _rows(ctx: Context) -> tuple[str, dict[str, Any], tuple[timeline.Row, ...], Known] | None:
    """As `_open`, for a rule that judges the rows: the page, the states, every row, and each row
    whose state is on the list with that state's table, every one of those counted as inspected. A
    page with no table is refused here, since timeline/shape names why, and a row off the list is
    left to timeline/shape."""
    opened = _open(ctx)
    if opened is None:
        return None
    page, states, found = opened
    if found.table_line is None:
        heading = ctx.manifest.table("timeline")["heading"]
        missing = f"the page has no heading {heading}" if found.heading_line is None else NO_TABLE
        ctx.refuse(f"the timeline cannot be read: {missing}", where=page,
                   fix="see timeline/shape: the page must be in its shape before this rule can judge it")
        return None
    known = [(row, states[row.state]) for row in found.rows if row.state in states]
    ctx.inspect(len(known))
    return page, states, found.rows, known


def _days(count: int) -> str:
    return "1 day" if count == 1 else f"{count} days"


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


# -- the worlds with history --------------------------------------------------------------------

RECORDS = {
    "docs/decisions.md": "# Decisions\n\n- 26 Nov 2026: the plan stays.\n",
    "docs/rehearsal.md": "# The rehearsal\n",
    "research/2026-11-26_check/PRE-REG.md": "# The forward check: its seal\n",
    **{f"plans/active/{name}.md": f"# The {name} plan\n"
       for name in ("dashboard", "look", "range", "check", "money", "forward", "explainer")},
}


def _merge(world: World, number: int) -> None:
    """Pull request #number: a branch of work, merged into main with the host's own message."""
    world.branch(f"topic-{number}")
    world.write(f"work/{number}.md", f"# The work of #{number}\n")
    world.commit(f"the work of #{number}")
    world.checkout("main")
    world.git("merge", "-q", "--no-ff", "-m", f"Merge pull request #{number} from team/topic-{number}",
              f"topic-{number}")


def _recorded(world: World, *rows: str, swap: tuple[str, str] | None = None, setup: str = "",
              merged: tuple[int, ...] = (12, 13, 14, 15)) -> None:
    """The timeline, its records committed on main, and its pull requests merged after them."""
    _timeline(world, *rows, swap=swap, setup=setup)
    for path, text in RECORDS.items():
        world.write(path, text)
    world.commit("the records")
    for number in merged:
        _merge(world, number)


#: The page of 26 Nov 2026 whose drift the design lists, names changed and words cut: five columns,
#: dates with no year, fourteen states, two rows cut from one task, Built rows citing no pull
#: request, and task 9 waiting on rows 1 to 8, among them the paused task 3.
INCIDENT = """# Plans

## Timeline

The home of every start date. Written 22 Nov 2026; status as of Wed 25 Nov.

Status: **Done** · **Under way** · **Next** (from Thu 26 Nov, 16:00) · **Waits** (on another row) · **Planned**.

| When | Task | Status | Who | Plan |
|---|---|---|---|---|
| Mon 23 Nov, ~08:00 | The look's branch pushed once parity ended | **Done** early, 22 Nov 23:56; PR #98 merged 23:59 | Opus | [the prop tool](active/prop.md) |
| Mon 23 Nov, 09:00 | The server rehearsal, trading off | **Under way**, the rest moved to Thursday (the owner) | You and Opus | [dashboard](active/dashboard.md) |
| **Thu 26 Nov, 16:00** | 0. **Finish the server rehearsal, first** | **Passed** 26 Nov, evening: tests 5b and 6; the seal's amendment merged (#128) | Opus, you | [dashboard](active/dashboard.md) |
| | 0b. **Move the old repository's research in**, one PR a repository | **Done** 26 Nov: this one's #123, the second's #1, the journal's #20; the data archived (#143) | Opus; Fable | [migration](active/migration.md) |
| | 1. Sell the tool or a signal: facts only | **Compared** 26 Nov (Fable): from our own site only ([compare](../docs/compare.md)) | Opus, Fable, you | [selling](future/selling.md) |
| | 2. The prop tool's look | **Under way**: parity scored 26 Nov; a slip recorded (#141) | Opus; you on the grant | [the prop tool](active/prop.md) |
| | 3. The range tool beside the first starts | **Paused** 26 Nov by the owner, for a session of its own | Opus; Fable designs | [range](active/range.md) |
| | 4. Reorg 5b and tuning | **Building** 5b: PRs 1–3 of 8 (#145, #147) | Opus; you give the goes | [reorg](active/reorg.md), [tune](active/tune.md) |
| | 5. The forward check of an old file | **Sealed** 26 Nov (#144; Fable agreed): one tester run, read once | Opus | [check](active/check.md) |
| | 6. The checkpoint; docs to finish | **Under way**: known issue 69 fixed 26 Nov (#135) | Opus | [docs](active/docs.md) |
| | 7. **Why the curve is flat early in the year** | **Built** 26 Nov: compounding from the high ([curve shape](../docs/curve.md)) | Opus; Fable judges | [the tool](../docs/tool.md) |
| | 8. **Why the offline estimate runs 12% under** | **Built** 26 Nov (Fable: yes): every part named ([the estimate](../docs/estimate.md)) | Opus; Fable judges | [money](active/money.md) |
| | 10. **Send the email to the firm**; its answer kept | **Sent** 26 Nov, checked line by line; the answer awaited, kept in the plan | You | [the prop tool](active/prop.md#2-the-email) |
| | 11. **The path beside plan B** | **Decided** 26 Nov (the owner): plan B stays ([the path](../docs/path.md), [decisions](../docs/decisions.md)) | You decide | [money](active/money.md) |
| After 1–8 | 9. The timeline as rules | **Waits** on 1–8: asked 22 Nov, not started | Fable designs; Opus builds | [timeline](active/timeline.md) |
| Sun 29 Nov | Trading switched on | **Ready**: task 0 passed 26 Nov | You | [forward](active/forward.md) |
| Mon 30 Nov | The forward run's day 1 | **Ready**: the seal merged 20 Nov (#61), amended 26 Nov (#128) | Opus checks | [forward](active/forward.md) |
| Mon 28 Dec | The month-1 check | **Planned** | Opus | [forward](active/forward.md) |
| ~22 Feb 2027 | The launch, at the earliest | **Waits** on 1 | You | [selling](future/selling.md) |
| **Apr 2027** | The firm's account bought | **Planned**: after the demo months pass | You | [the prop tool](active/prop.md) |
| Apr – Jun 2027 | More firms researched; you pick | **Planned** | Opus, Fable, you | the same |
"""


def _incident(world: World) -> None:
    """The page of 26 Nov, with its records and the pull requests it names that had merged."""
    world.manifest(STATES)
    world.write(PAGE, INCIDENT)
    for name in ("decisions", "compare", "curve", "estimate", "path", "tool"):
        world.write(f"docs/{name}.md", f"# The {name} record\n")
    world.commit("the records")
    for number in (61, 98, 123, 128, 135, 141, 143, 144, 145, 147):
        _merge(world, number)


@proof("timeline/shape", "the page of 26 Nov: fourteen states, no years, blank starts", expect="fail",
       contains="row 0: **Passed** is not one of the timeline's states")
def _(world: World) -> None:
    _incident(world)


# -- timeline/state-cited -----------------------------------------------------------------------


@rule(
    "timeline/state-cited",
    "A row whose state claims a result cites the record that state requires, and the record is on the main line.",
    learned="Two rows read Built and cited no pull request: their merges were named only in the handoff.",
)
def state_cited(ctx: Context) -> None:
    opened = _rows(ctx)
    if opened is None:
        return
    page, _, _, known = opened
    main = ctx.git.main_ref(ctx.manifest.project.get("main"))
    if main is None:
        ctx.refuse("there is no main line, so no row's citation can be checked", where=page,
                   fix="commit to main, or set project.main")
        return
    merged = ctx.git.pull_requests(main)
    held = set((ctx.git.run("ls-tree", "-r", "-z", "--name-only", main) or "").split("\0"))
    for row, state in known:
        cites = state.get("cites") or []
        patterns = [cite for cite in cites if cite != "pr"]
        numbers = row.prs if "pr" in cites else ()
        records = [path for path in row.cited if paths.matches_any(path, patterns)]

        def say(message: str, fix: str, row: timeline.Row = row) -> None:
            ctx.breach(f"{row.name} {message}", where=page, line=row.line, fix=fix)

        if cites and not numbers and not records:
            needs = ["a merged pull request of this repository, as #12"] * ("pr" in cites)
            say(f"is **{row.state}** and cites nothing it requires: "
                + " or ".join(needs + [f"a link to {pattern}" for pattern in patterns]),
                "cite the record its state claims; a row turns Built or Done one pull request after the merge")
        for number in numbers:
            if number not in merged:
                say(f"cites #{number}, which is not merged on the main line ({main})",
                    "cite a merged pull request; another repository's is written as a link")
        for record in records:
            if record not in held:
                say(f"links {record}, which is not on the main line ({main})", "merge the record first, then cite it")


@proof("timeline/state-cited", "each claimed state cites its record, merged or on the main line", expect="pass")
def _(world: World) -> None:
    _recorded(world)


@proof("timeline/state-cited", "a Done row citing another repository's pull request by link and a record here",
       expect="pass")
def _(world: World) -> None:
    _recorded(world, swap=("**Done** 26 Nov 2026: #12, ", "**Done** 26 Nov 2026: "))


@proof("timeline/state-cited", "a pull request merged by squash, named in its subject", expect="pass")
def _(world: World) -> None:
    _recorded(world, swap=("#13. Compounding", "#16. Compounding"))
    world.write("work/16.md", "# The sizing, fixed\n")
    world.commit("Fix the sizing (#16)")


@proof("timeline/state-cited", "a Built row with no pull request", expect="fail",
       contains="row 4 is **Built** and cites nothing it requires")
def _(world: World) -> None:
    _recorded(world, swap=("#13. Compounding", "compounding, not the market"))


@proof("timeline/state-cited", "a Done row citing a pull request never merged", expect="fail",
       contains="row 1 cites #9999, which is not merged on the main line")
def _(world: World) -> None:
    _recorded(world, swap=("#12, [the other", "#9999, [the other"))


@proof("timeline/state-cited", "a Sealed row linking a seal that is only on a branch", expect="fail",
       contains="links research/2026-11-27_next/PRE-REG.md, which is not on the main line")
def _(world: World) -> None:
    _recorded(world)
    world.branch("next-seal")
    world.write("research/2026-11-27_next/PRE-REG.md", "# The next check: its seal\n")
    world.write(PAGE, _page(swap=("2026-11-26_check/PRE-REG.md", "2026-11-27_next/PRE-REG.md")))
    world.commit("the next seal")


@proof("timeline/state-cited", "the page of 26 Nov: tasks 7 and 8 Built, citing no pull request", expect="fail",
       contains="row 7 is **Built** and cites nothing it requires")
def _(world: World) -> None:
    _incident(world)


@proof("timeline/state-cited", "with no main line no citation can be checked", expect="refuse",
       contains="there is no main line")
def _(world: World) -> None:
    _timeline(world)


@proof("timeline/state-cited", "a page whose table cannot be read", expect="refuse",
       contains="the timeline cannot be read: the page has no heading Timeline")
def _(world: World) -> None:
    _recorded(world)
    world.write(PAGE, _page().replace("## Timeline", "## Dates"))


# -- timeline/not-stale -------------------------------------------------------------------------

TODAY = Param("today", str, None, "higher", "the day staleness is counted to, as an ISO date; unset means the real "
                                            "current date")
GRACE = Param("grace_days", int, 1, "lower", "the days a row may stay unstarted past its start, or stopped past its "
                                             "until, before it is stale")


@rule(
    "timeline/not-stale",
    "No row is still unstarted after its start date.",
    params=(TODAY, GRACE),
    learned="A task's date passed before it started, and a second row was written for the new date instead of the "
            "first one moved.",
)
def not_stale(ctx: Context) -> None:
    opened = _rows(ctx)
    if opened is None:
        return
    page, _, _, known = opened
    stated = ctx.param("today")
    try:
        today = dt.date.today() if stated is None else dt.date.fromisoformat(stated)
    except ValueError:
        ctx.refuse(f"today, {stated!r}, cannot be read as a date", where=MANIFEST_FILE,
                   fix="write today as YYYY-MM-DD, or unset it")
        return
    grace = ctx.param("grace_days")
    for row, state in known:
        start = row.when.by if row.when and not state.get("started", True) else None
        if start is not None and (today - start).days > grace:
            ctx.breach(f"{row.name} still reads **{row.state}**, and its start, {row.when.text}, passed "
                       f"{_days((today - start).days)} ago", where=page, line=row.line,
                       fix="say it started, or move its date in When: the old date and why go in its words, on this row")
        if state.get("names") == "until" and row.until_day and (today - row.until_day).days > grace:
            ctx.breach(f"{row.name} is **{row.state}** until {row.until}, {_days((today - row.until_day).days)} ago",
                       where=page, line=row.line, fix="restart it, or write the new until and why")


def _on(day: str, grace: int | None = None) -> str:
    """The rule's table in a world: today is this day, and the grace this many days."""
    return (f'\n    [rules."timeline/not-stale"]\n    today = "{day}"\n'
            + ("" if grace is None else f"    grace_days = {grace}\n"))


@proof("timeline/not-stale", "the honest page on the day it was written", expect="pass")
def _(world: World) -> None:
    _timeline(world, setup=_on("2026-11-26"))


@proof("timeline/not-stale", "a row one day past its start, within its day of grace", expect="pass")
def _(world: World) -> None:
    _timeline(world, setup=_on("2026-11-30"))


@proof("timeline/not-stale", "a month with no day, inside its month", expect="pass")
def _(world: World) -> None:
    _timeline(world, ROWS[9], ROWS[10], setup=_on("2026-12-20"))


@proof("timeline/not-stale", "a moved row: the new date in When, the old one in its words", expect="pass")
def _(world: World) -> None:
    _timeline(world, "| Thu 3 Dec 2026 | Switch on: planned for Sun 29 Nov 2026, moved by the owner | **Next** | You "
                     "| – | [forward](active/forward.md) |", setup=_on("2026-12-01"))


@proof("timeline/not-stale", "the rehearsal of 26 Nov: still planned three days after its date", expect="fail",
       contains="still reads **Planned**, and its start, Mon 23 Nov 2026, passed 3 days ago")
def _(world: World) -> None:
    _timeline(world, "| Mon 23 Nov 2026 | 0. The server rehearsal | **Planned** | You and Opus | – | "
                     "[dashboard](active/dashboard.md) |", setup=_on("2026-11-26"))


@proof("timeline/not-stale", "a row paused until a day gone", expect="fail",
       contains="row 3 is **Paused** until Mon 23 Nov 2026, 3 days ago")
def _(world: World) -> None:
    _timeline(world, swap=("until your go", "until Mon 23 Nov 2026"), setup=_on("2026-11-26"))


@proof("timeline/not-stale", "a span of months gone by, still planned", expect="fail",
       contains="its start, Feb – Mar 2027, passed 5 days ago")
def _(world: World) -> None:
    _timeline(world, ROWS[10], setup=_on("2027-04-05"))


@proof("timeline/not-stale", "a project's shorter grace binds", expect="fail",
       contains="its start, Sun 29 Nov 2026, passed 1 day ago")
def _(world: World) -> None:
    _timeline(world, setup=_on("2026-11-30", grace=0))


@proof("timeline/not-stale", "a today that is no date", expect="refuse", contains="cannot be read as a date")
def _(world: World) -> None:
    _timeline(world, setup=_on("26 Nov 2026"))


# -- timeline/waits-resolve ---------------------------------------------------------------------


@rule(
    "timeline/waits-resolve",
    "A stopped row names what restarts it, and each row it waits on exists, is not finished and is not paused.",
    learned="A task waited on eight rows, one of them paused, so its wait could never end.",
)
def waits_resolve(ctx: Context) -> None:
    opened = _rows(ctx)
    if opened is None:
        return
    page, states, rows, known = opened
    numbered: dict[str, timeline.Row] = {}
    for row in rows:
        if row.number:
            numbered.setdefault(row.number, row)  # a second row with the number is timeline/shape's to name
    for row, state in known:
        names, unstarted = state.get("names"), not state.get("started", True)

        def say(message: str, fix: str, row: timeline.Row = row) -> None:
            ctx.breach(f"{row.name} {message}", where=page, line=row.line, fix=fix)

        if names == "rows" and row.on is None:
            say(f"is **{row.state}** and names no rows it waits on", "write on, then the rows, as on 1, 2")
        if names == "until" and row.until is None:
            said = f": {row.until_problem}" if row.until_problem else ""
            say(f"is **{row.state}** and names nothing that restarts it{said}",
                "write until, then a day, rows or a person's go, as until your go")
        waited = ((row.on or ()) if names == "rows" else ()) + (row.until_rows if names == "until" else ()) \
            + (row.when.after if unstarted and row.when else ())
        for number in dict.fromkeys(waited):
            other = numbered.get(number)
            theirs = states.get(other.state) if other is not None and other.state in states else None
            if other is None:
                say(f"waits on row {number}, which no row holds", "correct the number, or write the row it means")
            elif theirs is not None and theirs.get("names") == "until":
                say(f"waits on row {number}, which is **{other.state}**: the wait cannot end while that row is stopped",
                    "wait on what restarts that row, or restart it first")
            elif theirs is not None and theirs.get("finished"):
                say(f"waits on row {number}, which is **{other.state}**: a finished row holds no wait",
                    "take it out of the wait; a row with nothing left to wait on is free to start")


@proof("timeline/waits-resolve", "a wait on a row under way, a row after a planned one, a pause until a go",
       expect="pass")
def _(world: World) -> None:
    _timeline(world)


@proof("timeline/waits-resolve", "a pause until rows under way, and one until a day", expect="pass")
def _(world: World) -> None:
    _timeline(world, ROWS[1], ROWS[2].replace("until your go", "until 2"),
              ROWS[3].replace("**Built** 26 Nov 2026: #13. Compounding",
                              "**Paused** 26 Nov 2026 until Mon 7 Dec 2026, after the check"))


@proof("timeline/waits-resolve", "a wait on a row no row holds", expect="fail",
       contains="waits on row 99, which no row holds")
def _(world: World) -> None:
    _timeline(world, swap=("**Waits** on 2", "**Waits** on 99"))


@proof("timeline/waits-resolve", "a wait on a paused row", expect="fail", contains="waits on row 3, which is **Paused**")
def _(world: World) -> None:
    _timeline(world, swap=("**Waits** on 2", "**Waits** on 3"))


@proof("timeline/waits-resolve", "a wait on rows all finished", expect="fail",
       contains="waits on row 4, which is **Built**: a finished row holds no wait")
def _(world: World) -> None:
    _timeline(world, swap=("**Waits** on 2", "**Waits** on 1 and 4"))


@proof("timeline/waits-resolve", "a pause with no until", expect="fail",
       contains="row 3 is **Paused** and names nothing that restarts it")
def _(world: World) -> None:
    _timeline(world, swap=("until your go, for", "for"))


@proof("timeline/waits-resolve", "a wait that names no rows", expect="fail", contains="names no rows it waits on")
def _(world: World) -> None:
    _timeline(world, swap=("**Waits** on 2", "**Waits** for the check"))


@proof("timeline/waits-resolve", "a row after a row no row holds", expect="fail",
       contains="row 9 waits on row 10, which no row holds")
def _(world: World) -> None:
    _timeline(world, swap=("| After 8 |", "| After 10 |"))


@proof("timeline/waits-resolve", "the page of 26 Nov: task 9 waits on rows 1 to 8, and task 3 is paused",
       expect="fail", contains="row 9 waits on row 3, which is **Paused**")
def _(world: World) -> None:
    _incident(world)


# -- timeline/plans-listed ----------------------------------------------------------------------

PLANS = Param("plans", [str], [], "larger", "the open plans, as path patterns, such as plans/active/*.md")
CLOSED = Param("closed", [str], [], "smaller", "open plans that need no row, such as one closed in place: paths or "
                                               "patterns")


@rule(
    "timeline/plans-listed",
    "Every open plan is linked from a row.",
    params=(PLANS, CLOSED),
    requires=("plans",),
    learned="An open plan had no row in the timeline, so its start date lived only inside the plan.",
)
def plans_listed(ctx: Context) -> None:
    opened = _rows(ctx)
    if opened is None:
        return
    page, _, rows, _ = opened
    plans = sorted({name for pattern in ctx.param("plans") for name in ctx.files(pattern)} - {page})
    if not plans:
        ctx.refuse("no file matches plans, so there is no open plan to look for", where=MANIFEST_FILE,
                   fix="correct the patterns under plans")
        return
    linked = {path for row in rows for path in row.linked}
    closed = ctx.param("closed")
    for plan in plans:
        if plan not in linked and not paths.matches_any(plan, closed):
            ctx.breach(f"the open plan {plan} is linked from no row of the timeline", where=page,
                       fix='link it from its row, or list it under closed in [rules."timeline/plans-listed"]')
    for entry in closed:
        if not any(paths.matches(plan, entry) for plan in plans):
            ctx.refuse(f"closed names {entry}, which matches no open plan", where=MANIFEST_FILE,
                       fix="take it out of closed")


LISTED = """
    [rules."timeline/plans-listed"]
    plans = ["plans/active/*.md"]
    closed = ["plans/active/explainer.md"]
"""


@proof("timeline/plans-listed", "every open plan is linked, from any cell, and the one closed in place is listed",
       expect="pass")
def _(world: World) -> None:
    _recorded(world, swap=("9. The next step", "9. The next step, from [the notes](active/notes.md)"),
              setup=LISTED)
    world.write("plans/active/notes.md", "# Notes\n")


@proof("timeline/plans-listed", "a new plan no row links", expect="fail",
       contains="the open plan plans/active/new.md is linked from no row")
def _(world: World) -> None:
    _recorded(world, setup=LISTED)
    world.write("plans/active/new.md", "# A new plan\n")


@proof("timeline/plans-listed", "a closed plan that is no longer there", expect="refuse",
       contains="closed names plans/active/gone.md, which matches no open plan")
def _(world: World) -> None:
    _recorded(world, setup=LISTED.replace("explainer.md", "gone.md"))
    world.remove("plans/active/explainer.md")


@proof("timeline/plans-listed", "patterns that match no plan", expect="refuse", contains="no file matches plans")
def _(world: World) -> None:
    _recorded(world, setup=LISTED.replace("plans/active/*.md", "plans/open/*.md"))
