"""Gate: results — the numbers are complete and fairly compared.

A published item is judged on numbers read from a named source, at an agreed age, on the goal
number of the purpose it was sealed with. A series is compared only with the project's own
baseline, a new series changes one thing at a time, and a difference is called real only when it
is larger than the noise. The decisions themselves are issued by the results gate, in `gate.py`.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING, Any

from themis.packs.marketing import items
from themis.rule import Context, Param, proof, rule

if TYPE_CHECKING:
    from themis.proofs import World

GATE = "results"
ONE_THING = ("audience", "format", "purpose")
REAL = ("lead", "retire")  # the decisions that call a difference between two series real
TODAY = Param("today", str, None, None, "the day to count from, as YYYY-MM-DD; when unset, the real current date")


def _day(value: Any) -> dt.date | None:
    """The calendar day in ISO text, or None when no day can be read."""
    try:
        return dt.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _settings(ctx: Context) -> dict[str, Any]:
    return items.table(ctx).get("results", {})


def _issued(ctx: Context) -> list[Any]:
    """The decisions the results gate issued. An owner's overrule is the owner's word, not the gate's."""
    return [record for record in ctx.records("decision") if record.get("gate") == GATE and record.get("by") != "owner"]


# -- results/recorded ---------------------------------------------------------------------------


@rule(
    "results/recorded",
    "Each published item has a result with its source, read at the agreed age or later.",
    pack="marketing",
    params=(TODAY,),
    learned="An item was judged on numbers read a day after it was posted, before they had settled.",
)
def recorded(ctx: Context) -> None:
    least = _settings(ctx).get("min_age_days")
    if least is None:
        ctx.not_configured("set min_age_days under [marketing.results]: the age, in days, a result is read at")
    today = _day(ctx.param("today")) if ctx.param("today") else dt.date.today()
    if today is None:
        ctx.refuse("today cannot be read as a date", where="themis.toml", fix="write today as YYYY-MM-DD, or unset it")
        return
    for unit in sorted(items.items(ctx)):
        post = items.load(ctx, unit, "post")
        if post is None:
            continue  # not published yet
        ctx.inspect()
        where = f"{unit}/result.toml"
        result = items.load(ctx, unit, "result")
        if result is None and not ctx.exists(where):
            posted = _day(post["at"])
            if posted is None:
                ctx.refuse("the day this item was posted cannot be read", where=f"{unit}/post.toml",
                           fix="write at as an ISO date, such as 2026-03-01")
            elif (today - posted).days > 2 * least:
                ctx.breach(f"a published item has no result, {(today - posted).days} days after it was posted",
                           where=unit, fix="read its numbers from their source and record them in result.toml")
        elif result is not None:
            if result["age_days"] < least:
                ctx.breach(f"this result was read at {result['age_days']} day(s), and the agreed age is {least} days",
                           where=where, fix=f"read the numbers again once the item is {least} days old")
            if not result["source"].strip():
                ctx.breach("this result names no source", where=where,
                           fix="say where the numbers were read from: an export, a page, or the owner's own entry")


SETUP = """
    [project]
    packs = ["marketing"]

    [marketing]
    work = "content/*"

    [marketing.results]
    min_age_days = 7
    baseline = "own-median"

    [marketing.purposes.growth]
    goal = "follows_per_thousand_views"
"""
TODAY_IS = '\n    [rules."results/recorded"]\n    today = "{}"\n'
RESULT = 'read_at = "2026-03-08"\nage_days = 7\nsource = "the channel\'s own export"\n\n[metrics]\nviews = 1200\n'


def _item(world: World, unit: str = "content/a", today: str = "2026-03-20") -> None:
    """One honest item: sealed for growth, posted, and read seven days later on its goal number."""
    world.manifest(SETUP + TODAY_IS.format(today))
    world.write(f"{unit}/brief.toml", 'kind = "content"\ntitle = "A better cup"\npurpose = "growth"\n')
    world.write(f"{unit}/post.toml", 'platform = "main-channel"\nat = "2026-03-01T18:00:00+00:00"\n')
    world.write(f"{unit}/result.toml", RESULT + "follows_per_thousand_views = 4.5\n")


def _change(world: World, path: str, old: str, new: str) -> None:
    """Change one thing in a file of the world. The text to replace must occur exactly once."""
    text = (world.root / path).read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise ValueError(f"{old!r} occurs {text.count(old)} times in {path}; it must occur once")
    world.write(path, text.replace(old, new))


@proof("results/recorded", "a result with its source, read at the agreed age", expect="pass")
def _(world: World) -> None:
    _item(world)


@proof("results/recorded", "a young post with no result yet is left to the ledger", expect="pass")
def _(world: World) -> None:
    _item(world, today="2026-03-15")
    world.remove("content/a/result.toml")


@proof("results/recorded", "a result read too early", expect="fail",
       contains="this result was read at 2 day(s), and the agreed age is 7 days")
def _(world: World) -> None:
    _item(world)
    _change(world, "content/a/result.toml", "age_days = 7", "age_days = 2")


@proof("results/recorded", "a result that names no source", expect="fail", contains="this result names no source")
def _(world: World) -> None:
    _item(world)
    _change(world, "content/a/result.toml", "the channel's own export", " ")


@proof("results/recorded", "an item posted long ago with no result", expect="fail",
       contains="a published item has no result, 19 days after it was posted")
def _(world: World) -> None:
    _item(world)
    world.remove("content/a/result.toml")


@proof("results/recorded", "no item is published yet", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _item(world)
    world.remove("content/a/post.toml")


@proof("results/recorded", "a result that does not match its schema", expect="refuse",
       contains="result.age_days must be a whole number")
def _(world: World) -> None:
    _item(world)
    _change(world, "content/a/result.toml", "age_days = 7", 'age_days = "a week"')


@proof("results/recorded", "a post whose date cannot be read", expect="refuse",
       contains="the day this item was posted cannot be read")
def _(world: World) -> None:
    _item(world)
    world.remove("content/a/result.toml")
    _change(world, "content/a/post.toml", "2026-03-01T18:00:00+00:00", "last week")


# -- results/purpose-sealed ---------------------------------------------------------------------


@rule(
    "results/purpose-sealed",
    "An item is judged on the goal number of the purpose it was sealed with.",
    pack="marketing",
    learned="An item made to sell was praised for its views after it had sold nothing.",
)
def purpose_sealed(ctx: Context) -> None:
    purposes = items.table(ctx).get("purposes", {})
    if not purposes:
        ctx.not_configured("declare each purpose and its goal number under [marketing.purposes]")
    for unit in sorted(items.items(ctx)):
        result = items.load(ctx, unit, "result")
        if result is None:
            continue  # nothing is judged yet
        ctx.inspect()
        brief = items.load(ctx, unit, "brief")
        if brief is None:
            if not ctx.exists(f"{unit}/brief.toml"):
                ctx.refuse("this item has a result and no brief, so its purpose cannot be read", where=unit,
                           fix="restore the item's brief; a result rests on a sealed brief")
            continue
        purpose = brief.get("purpose")
        if purpose not in purposes:
            said = f"the purpose {purpose!r}, which is not declared" if purpose else "no purpose"
            ctx.breach(f"this item was sealed with {said}, so it has no goal number to be judged on",
                       where=f"{unit}/brief.toml", fix="seal each item with a purpose from [marketing.purposes]")
        elif purposes[purpose]["goal"] not in result["metrics"]:
            ctx.breach(f"the result holds no {purposes[purpose]['goal']}, the goal number of the purpose {purpose}",
                       where=f"{unit}/result.toml", fix="read the goal number from the same source, into the metrics")


@proof("results/purpose-sealed", "a result that holds its purpose's goal number", expect="pass")
def _(world: World) -> None:
    _item(world)


@proof("results/purpose-sealed", "an item with no result yet is not judged, whatever its purpose", expect="pass")
def _(world: World) -> None:
    _item(world)
    world.write("content/b/brief.toml", 'kind = "content"\ntitle = "Three mistakes"\npurpose = "reach"\n')


@proof("results/purpose-sealed", "a result with views and no goal number", expect="fail",
       contains="the result holds no follows_per_thousand_views, the goal number of the purpose growth")
def _(world: World) -> None:
    _item(world)
    _change(world, "content/a/result.toml", "follows_per_thousand_views = 4.5\n", "shares = 30\n")


@proof("results/purpose-sealed", "an item sealed with a purpose the project never declared", expect="fail",
       contains="sealed with the purpose 'reach', which is not declared")
def _(world: World) -> None:
    _item(world)
    _change(world, "content/a/brief.toml", 'purpose = "growth"', 'purpose = "reach"')


@proof("results/purpose-sealed", "an item sealed with no purpose", expect="fail", contains="sealed with no purpose")
def _(world: World) -> None:
    _item(world)
    _change(world, "content/a/brief.toml", 'purpose = "growth"\n', "")


@proof("results/purpose-sealed", "a result with no brief beside it", expect="refuse",
       contains="has a result and no brief, so its purpose cannot be read")
def _(world: World) -> None:
    _item(world)
    world.remove("content/a/brief.toml")


@proof("results/purpose-sealed", "no item has a result yet", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _item(world)
    world.remove("content/a/result.toml")


# -- results/own-baseline -----------------------------------------------------------------------


@rule(
    "results/own-baseline",
    "Results are compared only with the baseline the project declared.",
    pack="marketing",
    learned="A series was called weak against an outside benchmark the project had never chosen.",
)
def own_baseline(ctx: Context) -> None:
    declared = _settings(ctx).get("baseline")
    if not declared:
        ctx.not_configured("set baseline under [marketing.results], such as baseline = \"own-median\"")
    for record in _issued(ctx):
        ctx.inspect()
        used = (record.get("numbers") or {}).get("baseline")
        if used != declared:
            said = "does not say which baseline it used" if used is None else f"was made against the baseline {used!r}"
            ctx.breach(f"this decision {said}; the project declared {declared!r}", where=record.path,
                       fix="issue the decision again from the gate, with the views of the declared baseline")


def _decision(world: World, name: str = "howto-short", **changes: Any) -> None:
    """One honest decision of the results gate: a lead, against the declared baseline, outside the noise."""
    fields = {"work": f"series/{name}", "decision": "lead", "verdict": "pass", "gate": "results", "gate_version": "1",
              "decided_at": "2026-03-10T09:00:00+00:00", "numbers": {"baseline": "own-median", "within_noise": False}}
    world.manifest(SETUP)
    world.write(f"decisions/{name}.json", json.dumps({**fields, **changes}))


@proof("results/own-baseline", "a decision made against the declared baseline", expect="pass")
def _(world: World) -> None:
    _decision(world)


@proof("results/own-baseline", "another gate's decision, and the owner's overrule, are not this rule's", expect="pass")
def _(world: World) -> None:
    _decision(world)
    _decision(world, "other", gate="threshold", numbers={})
    _decision(world, "owner", by="owner", reason="kept for the season", numbers={})


@proof("results/own-baseline", "a decision made against an outside benchmark", expect="fail",
       contains="was made against the baseline 'category-average'; the project declared 'own-median'")
def _(world: World) -> None:
    _decision(world, numbers={"baseline": "category-average", "within_noise": False})


@proof("results/own-baseline", "a decision that does not name its baseline", expect="fail",
       contains="does not say which baseline it used")
def _(world: World) -> None:
    _decision(world, numbers={"within_noise": False})


@proof("results/own-baseline", "no decision of the results gate yet", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _decision(world, gate="threshold")


@proof("results/own-baseline", "a decision record that cannot be read", expect="refuse", contains="is not valid JSON")
def _(world: World) -> None:
    _decision(world)
    world.write("decisions/broken.json", '{"gate": "results"\n')


# -- results/one-change -------------------------------------------------------------------------


@rule(
    "results/one-change",
    "A new series changes one thing from the series it is compared with.",
    pack="marketing",
    learned="A new series changed its audience and its format at once, so nobody could say which change helped.",
)
def one_change(ctx: Context) -> None:
    for path in ctx.files("series/*.toml"):
        name = path.removeprefix("series/").removesuffix(".toml")
        new = items.series(ctx, name)
        if new is None or "compared_with" not in new:
            continue  # a first series is compared with nothing
        ctx.inspect()
        other, changed = new["compared_with"], new.get("changed")
        old = items.series(ctx, other) if ctx.exists(f"series/{other}.toml") else None
        if old is None:
            if not ctx.exists(f"series/{other}.toml"):
                ctx.refuse(f"this series is compared with {other}, which has no series file", where=path,
                           fix=f"add series/{other}.toml, or correct compared_with")
            continue
        differs = [field for field in ONE_THING if new.get(field) != old.get(field)]
        if changed not in ONE_THING:
            ctx.breach("this series does not say which one thing it changed: audience, format or purpose", where=path,
                       fix='set changed to "audience", "format" or "purpose"')
        elif differs != [changed]:
            said = ", ".join(differs) if differs else "nothing"
            ctx.breach(f"this series says it changed {changed}, and what differs from {other} is {said}", where=path,
                       fix="change one thing at a time, so a difference in results has one cause")


def _series(world: World, **changes: str) -> None:
    """An honest pair: a first series, and a new one that changed its format only."""
    first = {"audience": "home cooks", "format": "long", "purpose": "growth", "status": "active"}
    new = {**first, "format": "short", "compared_with": "howto", "changed": "format", **changes}
    world.manifest(SETUP)
    world.write("series/howto.toml", "".join(f'{key} = "{value}"\n' for key, value in first.items()))
    world.write("series/howto-short.toml", "".join(f'{key} = "{value}"\n' for key, value in new.items()))


@proof("results/one-change", "a new series that changed its format only", expect="pass")
def _(world: World) -> None:
    _series(world)


@proof("results/one-change", "a change of audience only; a series' status is not one of the three", expect="pass")
def _(world: World) -> None:
    _series(world, audience="students", format="long", changed="audience", status="parked")


@proof("results/one-change", "a new audience and a new format at once", expect="fail",
       contains="says it changed format, and what differs from howto is audience, format")
def _(world: World) -> None:
    _series(world, audience="students")


@proof("results/one-change", "the change that is named is not the one that was made", expect="fail",
       contains="says it changed purpose, and what differs from howto is format")
def _(world: World) -> None:
    _series(world, changed="purpose")


@proof("results/one-change", "a copy that changed nothing", expect="fail",
       contains="says it changed format, and what differs from howto is nothing")
def _(world: World) -> None:
    _series(world, format="long")


@proof("results/one-change", "a change that is none of the three", expect="fail",
       contains="does not say which one thing it changed")
def _(world: World) -> None:
    _series(world, changed="length")


@proof("results/one-change", "compared with a series that has no file", expect="refuse",
       contains="is compared with howto-long, which has no series file")
def _(world: World) -> None:
    _series(world, compared_with="howto-long")


@proof("results/one-change", "no series is compared with another", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _series(world)
    world.remove("series/howto-short.toml")


# -- results/noise-band -------------------------------------------------------------------------


@rule(
    "results/noise-band",
    "A difference between two series is called real only when it is larger than the spread among their own items.",
    pack="marketing",
    learned="A series was retired on a difference smaller than the spread among its own items.",
)
def noise_band(ctx: Context) -> None:
    for record in _issued(ctx):
        ctx.inspect()
        inside = (record.get("numbers") or {}).get("within_noise")
        if record.get("decision") in REAL and inside is not False:
            said = "is inside the noise, by its own numbers" if inside is True else "was never tested against the noise"
            ctx.breach(f"this decision is a {record.get('decision')}, and the difference behind it {said}",
                       where=record.path, fix="issue the decision again from the gate with noise_band on; "
                       "a difference inside the noise is a keep")


@proof("results/noise-band", "a lead whose difference is larger than the noise", expect="pass")
def _(world: World) -> None:
    _decision(world)


@proof("results/noise-band", "a keep makes no claim of a difference, so it needs no test", expect="pass")
def _(world: World) -> None:
    _decision(world, decision="keep", numbers={"baseline": "own-median"})


@proof("results/noise-band", "a lead inside the noise", expect="fail",
       contains="this decision is a lead, and the difference behind it is inside the noise")
def _(world: World) -> None:
    _decision(world, numbers={"baseline": "own-median", "within_noise": True})


@proof("results/noise-band", "a retire that was never tested", expect="fail",
       contains="this decision is a retire, and the difference behind it was never tested against the noise")
def _(world: World) -> None:
    _decision(world, decision="retire", verdict="fail", enough_evidence=True, numbers={"baseline": "own-median"})


@proof("results/noise-band", "no decision of the results gate yet", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    world.manifest(SETUP)
