"""Gate: live — nothing trades live by default.

A project names its live-trading switches: for each, the files that carry it (a path pattern), a
regular expression whose one capture group is the switch's value, and the safe value. Every match
in every file the pattern selects must hold the safe value. A file that holds another value needs
the owner's grant for that file, `themis grant live <file>`, whether it was flipped on a branch or
written that way. The expression is read line by line (`^` and `$` match at each line).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from themis.grants import find_grant, to_toml
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
