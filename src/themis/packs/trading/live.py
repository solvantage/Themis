"""Gate: live — nothing trades live by default, and no money moves before its run has passed.

A project names its live-trading switches: for each, the files that carry it (a path pattern), a
regular expression whose one capture group is the switch's value, and the safe value. Every match
in every file the pattern selects must hold the safe value. A file that holds another value needs
the owner's grant for that file, `themis grant live <file>`, whether it was flipped on a branch or
written that way. The expression is read line by line (`^` and `$` match at each line).

A row of the timeline (`themis.timeline`) that commits money, by the words of its task or by a
Gate written in its row, names in its Gate cell the forward run it waits on: a link to that run's
seal, or `row N` for the row that will seal it. Once the row starts, the run's last decision on or
before the row's day must be a pass, or a week the owner overruled with a `forward` grant.
"""

from __future__ import annotations

import posixpath
import re
import zoneinfo
from typing import TYPE_CHECKING, Any

from themis import checkpoint, timeline, work
from themis.gates import timeline as timeline_gate
from themis.grants import find_grant, to_toml
from themis.manifest import MANIFEST_FILE
from themis.packs.trading import forward, units
from themis.rule import Context, Param, proof, rule
from themis.schema import Choice, Required

if TYPE_CHECKING:
    from themis.proofs import World

ACTION = "live"  # the grant action that lets one file hold a switch at its live value
SWITCHES = Param("switches", [{"files": Required(str), "pattern": Required(str), "safe": Required(str)}], None,
                 "larger", "each live-trading switch: files (a path pattern), pattern (one capture: the value), safe")
# "refuse" sorts before "skip", so the lower value is the stricter one.
ABSENT = Param("absent", Choice("refuse", "skip"), "refuse", "lower",
               "what a selected file that holds no switch gets: refuse (it must be there) or skip")


def _main(ctx: Context) -> str | None:
    return ctx.git.main_ref(ctx.manifest.project.get("main"))


def _compiled(ctx: Context, index: int, switch: dict[str, Any]) -> re.Pattern[str] | None:
    """The switch's expression, or None after a refusal that says why it cannot be used."""
    where, fix = "themis.toml", "write pattern as a regular expression with one capture group: the switch's value"
    try:
        pattern = re.compile(switch["pattern"], re.MULTILINE)
    except re.error as error:
        ctx.refuse(f"switches[{index}].pattern is not a regular expression: {error}", where=where, fix=fix)
        return None
    if pattern.groups != 1:
        ctx.refuse(f"switches[{index}].pattern has {pattern.groups} capture groups, and needs exactly one: the value",
                   where=where, fix=fix)
        return None
    return pattern


def _values(pattern: re.Pattern[str], text: str) -> list[tuple[int, str]]:
    """Each value the expression captures in the text, as (line, value)."""
    return [(text.count("\n", 0, found.start(1)) + 1, (found.group(1) or "").strip())
            for found in pattern.finditer(text)]


def _was_safe(ctx: Context, main: str | None, path: str, pattern: re.Pattern[str], safe: str) -> bool:
    """True when the main line holds this file with every switch at its safe value: a flip, not a default."""
    before = ctx.git.show(main, path) if main else None
    values = _values(pattern, before or "")
    return bool(values) and all(value == safe for _, value in values)


@rule(
    "live/off-by-default",
    "Every live-trading switch holds its safe value in the source, unless the owner granted that file its flip.",
    pack="trading",
    params=(SWITCHES, ABSENT),
    requires=("switches",),
    learned="A strategy shipped with live trading on by default, and one attached copy would have traded real money.",
)
def off_by_default(ctx: Context) -> None:
    main, granted = _main(ctx), None
    for index, switch in enumerate(ctx.param("switches")):
        pattern = _compiled(ctx, index, switch)
        if pattern is None:
            continue
        files, safe = ctx.files(switch["files"]), switch["safe"]
        if not files:
            ctx.refuse(f"no file matches switches[{index}].files, {switch['files']}", where="themis.toml",
                       fix="point files at the source that carries the switch, or remove the switch")
        for path in files:
            text = ctx.read(path)
            if text is None:
                ctx.refuse("this file cannot be read as text, so its switch cannot be checked", where=path)
                continue
            values = _values(pattern, text)
            if not values:
                if ctx.param("absent") == "refuse":
                    ctx.refuse(f"this file holds no switch that matches {switch['pattern']}", where=path,
                               fix=f"state the switch in the file, set to {safe}; or set absent = \"skip\"")
                continue
            ctx.inspect()
            unsafe = [(line, value) for line, value in values if value != safe]
            if not unsafe:
                continue
            granted = ctx.records("grant") if granted is None else granted
            if find_grant(granted, ACTION, path) is not None:
                continue  # the owner said yes to this file holding its live value
            flipped = _was_safe(ctx, main, path, pattern, safe)
            fix = f"set it back to {safe}; to trade live, the owner runs `themis grant {ACTION} {path} --reason ...`"
            for line, value in unsafe:
                said = (f"the switch was {safe} on the main line and now holds {value}, with no grant from the owner"
                        if flipped else f"the switch holds {value}, and its safe value is {safe}")
                ctx.breach(said, where=path, line=line, fix=fix)


SWITCH = r"^LIVE_TRADING\s*=\s*(\w+)"
SETUP = """
    [project]
    packs = ["trading"]

    [trading]
    work = "work/*"

    [rules."live/off-by-default"]
    switches = [{{files = "bots/**/*.py", pattern = '{switch}', safe = "False"}}]
    {extra}
"""
SAFE, LIVE = "LIVE_TRADING = False\n", "LIVE_TRADING = True\n"


def _bots(world: World, *bots: tuple[str, str], extra: str = "", switch: str = SWITCH) -> None:
    """The manifest, and each bot as (name, its source)."""
    world.manifest(SETUP.format(switch=switch, extra=extra))
    for name, source in bots:
        world.write(f"bots/{name}/bot.py", f'"""A bot."""\n\n{source}\nSIZE = 1\n')


def _grant(world: World, target: str) -> None:
    world.write("grants/live-1.toml", to_toml({
        "action": ACTION, "target": target, "granted_by": "owner", "granted_at": "2026-01-01T00:00:00+00:00",
        "reason": "a small live run, watched by the owner"}))


@proof("live/off-by-default", "every switch holds its safe value; a bot with none is skipped", expect="pass")
def _(world: World) -> None:
    _bots(world, ("trend", SAFE), ("carry", "# LIVE_TRADING = True, in a comment\n" + SAFE), ("notes", ""),
          extra='absent = "skip"')


@proof("live/off-by-default", "a bot written with live trading on", expect="fail",
       contains="the switch holds True, and its safe value is False")
def _(world: World) -> None:
    _bots(world, ("trend", SAFE), ("carry", LIVE))


@proof("live/off-by-default", "a bot with no switch, when a switch must be there", expect="refuse",
       contains="this file holds no switch that matches")
def _(world: World) -> None:
    _bots(world, ("trend", SAFE), ("carry", ""))


@proof("live/off-by-default", "a switch flipped on a branch with no grant", expect="fail",
       contains="the switch was False on the main line and now holds True, with no grant from the owner")
def _(world: World) -> None:
    _bots(world, ("trend", SAFE))
    world.commit("main")
    world.branch("go-live")
    _bots(world, ("trend", LIVE))
    world.commit("turn live trading on")


@proof("live/off-by-default", "a switch flipped with the owner's grant for that file", expect="pass")
def _(world: World) -> None:
    _bots(world, ("trend", SAFE), ("carry", SAFE))
    world.commit("main")
    world.branch("go-live")
    _bots(world, ("trend", LIVE), ("carry", SAFE))
    _grant(world, "bots/trend/bot.py")


@proof("live/off-by-default", "a grant for another file does not cover this one", expect="fail",
       contains="the switch was False on the main line and now holds True")
def _(world: World) -> None:
    _bots(world, ("trend", SAFE), ("carry", SAFE))
    world.commit("main")
    world.branch("go-live")
    _bots(world, ("trend", SAFE), ("carry", LIVE))
    _grant(world, "bots/trend/bot.py")


@proof("live/off-by-default", "a pattern with no capture group", expect="refuse", contains="needs exactly one")
def _(world: World) -> None:
    _bots(world, ("trend", SAFE), switch=r"^LIVE_TRADING\s*=\s*\w+")


# -- live/money-gated ---------------------------------------------------------------------------

WORDS = Param("words", [str], ["deposit", "bought", "fee"], "larger",
              "the words that mark a timeline row's task as one that commits money: each read whole, in any case, "
              "or with an s after it")
ROW_GATE = re.compile(r"row\s+(\d+[a-z]?)", re.IGNORECASE)
UNGATED = ("link the seal of the forward run it waits on in its Gate, or write row N for the row that will seal "
           "it")


def _seals(ctx: Context) -> dict[str, str]:
    """Each forward run's seal, by its path, with the run's study."""
    return {seal: unit for unit, files in forward.sealed(ctx.manifest, ctx.all_files, ctx.read).items()
            for seal in work.inside(unit, files, units.SEAL)[:1]}


ZONE = Param("zone", str, None, None, "the time zone the timeline's days are in, an IANA name such as Asia/Bangkok; "
                                      "unset, each time is read in its own UTC offset")


def _on_or_before(value: Any, day: Any, zone: zoneinfo.ZoneInfo | None) -> bool:
    """True when the time falls on or before the day, read in the page's zone."""
    found = forward.moment(value)
    return found is not None and (found.astimezone(zone) if zone else found).date() <= day


@rule(
    "live/money-gated",
    "A row that commits money names the sealed run it waits on, and starts only after that run's last decision is "
    "a pass.",
    pack="trading",
    params=(WORDS, ZONE),
    learned="A prop firm's account was to be bought \"after the demo months pass\", and only the words of its "
            "timeline row held it to that.",
)
def money_gated(ctx: Context) -> None:
    opened = timeline_gate._rows(ctx)
    if opened is None:
        return
    page, states, rows, known = opened
    named = ctx.param("zone")
    try:
        zone = None if named is None else zoneinfo.ZoneInfo(named)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        ctx.refuse(f"zone, {named!r}, is not a time zone this machine knows", where=MANIFEST_FILE,
                   fix="write an IANA name, such as Asia/Bangkok, or unset zone")
        return
    folder, seals = posixpath.dirname(page), _seals(ctx)
    numbered: dict[str, timeline.Row] = {}
    for row in rows:
        if row.number:
            numbered.setdefault(row.number, row)  # a second row with the number is timeline/shape's to name
    words = [re.compile(rf"\b{re.escape(word)}s?\b", re.IGNORECASE) for word in ctx.param("words")]
    decided: dict[str, list[Any]] | None = None
    grants: list[Any] | None = None
    for row, state in known:
        gate = (row.cells.get("gate") or "").strip()
        said = next((found[0] for found in (word.search(row.cells.get("task", "")) for word in words) if found), None)

        def say(message: str, fix: str, row: timeline.Row = row) -> None:
            ctx.breach(f"{row.name} {message}", where=page, line=row.line, fix=fix)

        if not timeline_gate._someone(gate):
            if said:
                say(f"commits money (its task says {said}), and its Gate names no sealed run it waits on", UNGATED)
            continue
        # The Gate: links to forward runs' seals, or the row that will seal one.
        links, number = checkpoint.links(gate), ROW_GATE.fullmatch(gate)
        if links:
            linked = [checkpoint.target_path(link, folder) or link for link in links]
            wrong = [path for path in linked if path not in seals]
            if wrong:
                say(f"has a Gate that links {wrong[0]}, which is not the seal of a forward run", UNGATED)
                continue
            waits = linked
        elif number:
            other = numbered.get(number[1].lower())
            theirs = states.get(other.state) if other is not None and other.state in states else None
            if other is None:
                say(f"is gated on row {number[1]}, which no row holds", "correct the number, or link the seal")
                continue
            if theirs is not None and theirs.get("finished"):
                say(f"is gated on row {other.number}, which is **{other.state}**: a finished row will seal nothing "
                    "more", "link in its Gate the seal that row made")
                continue
            waits = [path for path in other.cited if path in seals]
        else:
            say(f"has the Gate {gate!r}, which is neither a link to a forward run's seal nor row N", UNGATED)
            continue
        if not state.get("started", True):
            continue
        if row.day is None:
            say(f"is **{row.state}** and gives no day, so the decision it started on cannot be read",
                f"write the day after the state, as **{row.state}** 26 Nov 2026")
            continue
        if not waits:
            say(f"is **{row.state}** {row.day.isoformat()}, and {gate}, which its Gate waits on, has sealed nothing "
                "yet", "keep the row unstarted until the run it waits on is sealed and passes")
            continue
        # The pass: the run's last decision on or before the row's day, or the owner's forward grant for that week.
        decided = units.decisions(ctx) if decided is None else decided
        for seal in waits:
            study, weekly, undated = seals[seal], [], False
            for subject, found in decided.items():
                if not re.fullmatch(rf"{re.escape(study)}/week-[0-9]{{4}}-[0-9]{{2}}", subject):
                    continue
                for record in found:
                    if forward.moment(record.get("decided_at")) is None:
                        undated = True
                        ctx.refuse(f"the decision's decided_at, {record.get('decided_at')!r}, is not a time with its "
                                   "UTC offset, so the run's last decision cannot be read", where=record.path,
                                   fix="issue the decision again with themis decide")
                    elif _on_or_before(record.get("decided_at"), row.day, zone):
                        weekly.append((forward.moment(record.get("decided_at")), subject, record))
            if undated:
                continue  # any of them could be the last: the row is not judged on the rest
            if not weekly:
                say(f"started on {row.day.isoformat()}, and the forward run {study} had no decision by then",
                    "keep the row unstarted until a week of the run passes")
                continue
            _, subject, last = max(weekly, key=lambda held: held[:2])
            if last.get("verdict") == "pass":
                continue
            grants = ctx.records("grant") if grants is None else grants
            if find_grant(grants, forward.ACTION, subject) is not None:
                continue  # the owner overruled that week; a grant counts whenever given, as forward/match reads it
            week = subject.rsplit("/", 1)[-1].replace("-", " ", 1)
            say(f"started on {row.day.isoformat()}, and the last decision of {study} by then, for {week}, is "
                f"{last.get('decision')}: not a pass, and no {forward.ACTION} grant made it one",
                f"keep the row unstarted until a week of the run passes; only the owner overrules a week, with "
                f"`themis grant {forward.ACTION} {subject} --reason ...`")


#: The proofs' timeline: a forward run's day 1, the check that will seal the live month (row 2),
#: and money rows gated on a seal or on row 2. The rental of a server, and feedback on a free trial,
#: commit no money by the default words.
MONEY_ROWS = (
    "| Mon 30 Nov 2026 | 1. The forward run's day 1 | **Under way** 30 Nov 2026 | Opus | – | "
    "[forward](active/forward.md) |",
    "| Mon 4 Jan 2027 | 2. The month-1 check, which seals the live month | **Planned** | Opus | – | "
    "[forward](active/forward.md) |",
    "| Mon 7 Dec 2026 | 3. You deposit the real start | **Planned**: its preset ready | You | "
    "[the seal](../work/fwd/PRE-REG.md) | [money](active/money.md) |",
    "| Feb 2027 | The firm's account bought | **Planned** | You | row 2 | [money](active/money.md) |",
    "| Tue 1 Dec 2026 | The server's rental, 3 months | **Under way** 1 Dec 2026 | You | – | "
    "[dashboard](active/dashboard.md) |",
    "| Mon 30 Nov 2026 | Feedback on the free trial | **Next** | You | – | [money](active/money.md) |",
)
DEPOSITED = ("**Planned**: its preset ready", "**Under way** 7 Dec 2026: the deposit made")


def _money(world: World, *rows: str, swap: tuple[str, str] | None = None, setup: str = "", **run: Any) -> None:
    """A forward run as the forward proofs build it (`run` is what `forward._forward` is given: weeks
    48 and 49 of 2026, decided on Sundays 29 Nov and 6 Dec at 23:00 UTC), and the timeline over it."""
    forward._forward(world, rules=timeline_gate.STATES + setup, **run)
    world.write(timeline_gate.PAGE, timeline_gate._page(*(rows or MONEY_ROWS), swap=swap))


def _overruled(world: World, number: int, at: str) -> None:
    """The owner's forward grant for one week, given at this time."""
    world.write(f"grants/forward-{number}.toml", to_toml({
        "action": forward.ACTION, "target": forward._subject_of(number), "granted_by": "owner", "granted_at": at,
        "reason": "the owner looked at the week"}))


@proof("live/money-gated", "money rows unstarted, gated on a seal and on the row that will seal it; the words read "
       "whole", expect="pass")
def _(world: World) -> None:
    _money(world)


@proof("live/money-gated", "a money row started after its run's week passed", expect="pass")
def _(world: World) -> None:
    _money(world, swap=DEPOSITED, decided=forward.EVERY)


@proof("live/money-gated", "a money row started on the owner's forward grant over a stop", expect="pass")
def _(world: World) -> None:
    _money(world, swap=DEPOSITED, decided=forward.EVERY, changes=forward.RISKY, granted=(49,))


@proof("live/money-gated", "a money row started on the owner's own pass, with a grant for that week", expect="pass")
def _(world: World) -> None:
    _money(world, swap=DEPOSITED, decided=forward.EVERY, changes=forward.RISKY, owned={49: "pass"}, granted=(49,))


@proof("live/money-gated", "gated on row 2 once row 2 sealed the run, and started after a pass", expect="pass")
def _(world: World) -> None:
    _money(world, MONEY_ROWS[0], MONEY_ROWS[1].replace(
        "**Planned**", "**Sealed** 20 Nov 2026: [the seal](../work/fwd/PRE-REG.md)"),
        "| Mon 7 Dec 2026 | You deposit the real start | **Under way** 7 Dec 2026 | You | row 2 | "
        "[money](active/money.md) |", decided=forward.EVERY)


@proof("live/money-gated", "a task that says deposit, with Gate –", expect="fail",
       contains="row 3 commits money (its task says deposit), and its Gate names no sealed run it waits on")
def _(world: World) -> None:
    _money(world, swap=("| You | [the seal](../work/fwd/PRE-REG.md) |", "| You | – |"))


@proof("live/money-gated", "a money row under way while its run's last decision is a stop", expect="fail",
       contains="for week 2026-49, is stop: not a pass, and no forward grant made it one")
def _(world: World) -> None:
    _money(world, swap=DEPOSITED, decided=forward.EVERY, changes=forward.RISKY)


@proof("live/money-gated", "a money row started on a defer: the pass a week later does not reach back", expect="fail",
       contains="row 3 started on 2026-11-30, and the last decision of work/fwd by then, for week 2026-48, is defer")
def _(world: World) -> None:
    _money(world, swap=("**Planned**: its preset ready", "**Under way** 30 Nov 2026"), decided=forward.EVERY)


@proof("live/money-gated", "a money row started before its run had a decision", expect="fail",
       contains="row 3 started on 2026-11-25, and the forward run work/fwd had no decision by then")
def _(world: World) -> None:
    _money(world, swap=("**Planned**: its preset ready", "**Under way** 25 Nov 2026"), decided=forward.EVERY)


@proof("live/money-gated", "a grant for another week does not overrule the last one", expect="fail",
       contains="for week 2026-49, is stop")
def _(world: World) -> None:
    _money(world, swap=DEPOSITED, decided=forward.EVERY, changes=forward.RISKY, granted=(48,))


@proof("live/money-gated", "the owner's grant given after the row started still overrules the week", expect="pass")
def _(world: World) -> None:
    _money(world, swap=DEPOSITED, decided=forward.EVERY, changes=forward.RISKY)
    _overruled(world, 49, "2026-12-10T09:00:00+00:00")


REISSUED = {49: {"decided_at": "2026-12-20T03:00:00+00:00"}}  # week 49's pass, issued again on 20 Dec


@proof("live/money-gated", "a decision issued again is dated anew: the row's day then reads the week before",
       expect="fail", contains="row 3 started on 2026-12-07, and the last decision of work/fwd by then, for week "
                               "2026-48, is defer")
def _(world: World) -> None:
    _money(world, swap=DEPOSITED, decided=forward.EVERY, typed=REISSUED)


@proof("live/money-gated", "the pass a row started on, issued again later, and the owner's grant for the week before",
       expect="pass")
def _(world: World) -> None:
    _money(world, swap=DEPOSITED, decided=forward.EVERY, typed=REISSUED)
    _overruled(world, 48, "2026-12-21T09:00:00+00:00")


def _zone(name: str = "Asia/Bangkok") -> str:
    return f'\n    [rules."live/money-gated"]\n    zone = "{name}"\n'


SUNDAY = ("**Planned**: its preset ready", "**Under way** 6 Dec 2026")  # week 49 is decided Mon 7 Dec 06:00 in BKK


@proof("live/money-gated", "in the page's zone, a pass decided Sunday 23:00 UTC is Monday's: a row started Sunday "
       "did not start on it", expect="fail",
       contains="row 3 started on 2026-12-06, and the last decision of work/fwd by then, for week 2026-48, is defer")
def _(world: World) -> None:
    _money(world, swap=SUNDAY, decided=forward.EVERY, setup=_zone())


@proof("live/money-gated", "in the page's zone, a stop decided Sunday 23:00 UTC lands Monday: a row started Sunday on "
       "a pass holds", expect="pass")
def _(world: World) -> None:
    _money(world, swap=SUNDAY, decided=forward.EVERY, changes={49: {"risk.day-loss": 0.6}}, owned={48: "pass"},
           granted=(48,), setup=_zone())


@proof("live/money-gated", "a zone that is no time zone", expect="refuse",
       contains="zone, 'Mars/Olympus', is not a time zone")
def _(world: World) -> None:
    _money(world, swap=DEPOSITED, decided=forward.EVERY, setup=_zone("Mars/Olympus"))


@proof("live/money-gated", "a Gate on a finished row", expect="fail",
       contains="is gated on row 2, which is **Done**: a finished row will seal nothing more")
def _(world: World) -> None:
    _money(world, swap=("seals the live month | **Planned**", "seals the live month | **Done** 26 Nov 2026: #12"))


@proof("live/money-gated", "a Gate on a row no row holds", expect="fail", contains="is gated on row 9, which no row holds")
def _(world: World) -> None:
    _money(world, swap=("| You | row 2 |", "| You | row 9 |"))


@proof("live/money-gated", "a money row started while the row it is gated on has sealed nothing", expect="fail",
       contains="is **Under way** 2026-12-07, and row 2, which its Gate waits on, has sealed nothing yet")
def _(world: World) -> None:
    _money(world, swap=("| Feb 2027 | The firm's account bought | **Planned** |",
                        "| Feb 2027 | The firm's account bought | **Under way** 7 Dec 2026 |"), decided=forward.EVERY)


@proof("live/money-gated", "a Gate that links a plan, not a forward run's seal", expect="fail",
       contains="has a Gate that links plans/active/money.md, which is not the seal of a forward run")
def _(world: World) -> None:
    _money(world, swap=("[the seal](../work/fwd/PRE-REG.md)", "[the plan](active/money.md)"))


@proof("live/money-gated", "a Gate in words", expect="fail",
       contains="has the Gate 'after the checks', which is neither a link to a forward run's seal nor row N")
def _(world: World) -> None:
    _money(world, swap=("| You | row 2 |", "| You | after the checks |"))


@proof("live/money-gated", "a started money row that gives no day", expect="fail",
       contains="is **Under way** and gives no day")
def _(world: World) -> None:
    _money(world, swap=("**Planned**: its preset ready", "**Under way**: the deposit made"))


@proof("live/money-gated", "a project's own money words bind: the server's rental", expect="fail",
       contains="commits money (its task says rental)")
def _(world: World) -> None:
    _money(world, setup='\n    [rules."live/money-gated"]\n    words = ["deposit", "bought", "fee", "rental"]\n')


@proof("live/money-gated", "the page of 26 Nov: the firm's account bought, with no Gate", expect="fail",
       contains="commits money (its task says bought)")
def _(world: World) -> None:
    timeline_gate._incident(world)
    world.manifest(forward.MANIFEST + timeline_gate.STATES)


@proof("live/money-gated", "a decision whose time cannot be read", expect="refuse",
       contains="the decision's decided_at, 'Sunday night', is not a time with its UTC offset")
def _(world: World) -> None:
    _money(world, swap=DEPOSITED, decided=forward.EVERY, typed={49: {"decided_at": "Sunday night"}})


@proof("live/money-gated", "a page whose table cannot be read", expect="refuse",
       contains="the timeline cannot be read: the page has no heading Timeline")
def _(world: World) -> None:
    _money(world)
    world.write(timeline_gate.PAGE, timeline_gate._page(*MONEY_ROWS).replace("## Timeline", "## Dates"))
