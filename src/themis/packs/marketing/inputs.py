"""What the results gate reads, built from the records and never typed.

A gate that decides from a file anyone can edit decides nothing. So the file is built here: the
series' items come from the items' own result records, the baseline is computed from them, and the
thresholds are the project's, from `[marketing.results]`. The rule at the foot of this file builds
it again and compares.

A decision is as of a day. Only results read on or before that day are counted, so a result that
arrives later does not make an honest decision look wrong.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
import tomllib
from pathlib import Path
from typing import Any

from themis import work
from themis.gitlog import Git
from themis.packs.marketing.pack import pack
from themis.proofs import World
from themis.rule import Context, proof, rule

GATE = "results"
VIEWS = "views"
BASELINES = ("own-median",)


def _toml(root: Path, path: str) -> dict[str, Any] | None:
    try:
        return tomllib.loads((root / path).read_text(encoding="utf-8"))
    except OSError:
        return None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise ValueError(f"{path} cannot be read ({error})") from None


def build(root: Path, manifest: Any, subject: str, rival: str | None = None, *, as_of: str | None = None) -> dict[str, Any]:
    """The metrics for a decision about one series, as of a day (an ISO date; default today).

    Raises ValueError, with a plain reason, when the project has not said what is needed or a
    record cannot be read. Nothing is guessed.
    """
    table = manifest.table("marketing")
    results, purposes = table.get("results", {}), table.get("purposes", {})
    pattern = table.get("work")
    if not pattern:
        raise ValueError("the project has not said where its items live: set work under [marketing]")
    baseline = results.get("baseline")
    if baseline not in BASELINES:
        raise ValueError(f"the baseline must be one of {', '.join(BASELINES)}; [marketing.results] baseline is {baseline!r}")
    day = as_of or dt.date.today().isoformat()
    least_age, second_name = results.get("min_age_days", 0), results.get("second_number")
    series: dict[str, list[dict[str, Any]]] = {}
    for unit in sorted(work.units(Git(root).all_files(), pattern)):
        brief, result = _toml(root, f"{unit}/brief.toml"), _toml(root, f"{unit}/result.toml")
        if brief is None or result is None or not brief.get("series"):
            continue  # not published with a result yet, or not part of a series
        if str(result.get("read_at", ""))[:10] > day or result.get("age_days", 0) < least_age:
            continue  # read after the decision's day, or read too early to count
        goal_name = purposes.get(brief.get("purpose", ""), {}).get("goal")
        metrics = result.get("metrics", {})
        if goal_name is None:
            raise ValueError(f"{unit}: its purpose, {brief.get('purpose')!r}, has no goal under [marketing.purposes]")
        missing = [name for name in (goal_name, VIEWS, *([second_name] if second_name else [])) if name not in metrics]
        if missing:
            raise ValueError(f"{unit}/result.toml lacks the metric(s) {', '.join(missing)}")
        series.setdefault(brief["series"], []).append({
            "item": unit, "goal": metrics[goal_name], "second": metrics[second_name] if second_name else 0,
            VIEWS: metrics[VIEWS],
        })
    for name in (subject, *([rival] if rival else [])):
        series.setdefault(name, [])
    counted = [item[VIEWS] for held in series.values() for item in held]
    built: dict[str, Any] = {
        "series": series, "subject": subject, "baseline": baseline, "as_of": day,
        "baseline_views": statistics.median(counted) if counted else 1,
    }
    if rival:
        built["rival"] = rival
    limits = {
        "min_items_to_judge": results.get("min_items_to_judge"),
        "min_items_to_rank": results.get("min_items_to_rank"),
        "retire_views_share": results.get("retire", {}).get("views_below_share_of_baseline"),
        "standout_views_times": results.get("standout", {}).get("views_times_baseline"),
    }
    built.update({name: value for name, value in limits.items() if value is not None})
    return built


pack.inputs[GATE] = build


# -- results/inputs-rebuilt ---------------------------------------------------------------------


@rule(
    "results/inputs-rebuilt",
    "The numbers a results decision rests on are the result records and the project's own thresholds.",
    pack="marketing",
    learned="The thresholds a decision was made with lived in a file the deciding agent could edit.",
)
def inputs_rebuilt(ctx: Context) -> None:
    for record in ctx.records("decision"):
        if record.get("gate") != GATE or record.get("by") == "owner":
            continue
        ctx.inspect()
        path = record.get("inputs")
        try:
            stored = json.loads(ctx.read(path) or "") if path else None
        except json.JSONDecodeError:
            stored = None
        if not isinstance(stored, dict) or not isinstance(stored.get("subject"), str):
            ctx.refuse("this decision does not name a readable file of the numbers it was made from", where=record.path,
                       fix="issue the decision with `themis decide`, which builds that file from the records")
            continue
        try:
            rebuilt = build(ctx.root, ctx.manifest, stored["subject"], stored.get("rival"), as_of=stored.get("as_of"))
        except ValueError as error:
            ctx.refuse(f"the numbers cannot be built again: {error}", where=path)
            continue
        moved = sorted(key for key in set(stored) | set(rebuilt) if stored.get(key) != rebuilt.get(key))
        if moved:
            ctx.breach(f"the numbers this decision was made from differ from the records in: {', '.join(moved)}",
                       where=path, fix="issue the decision again with `themis decide`; its numbers are never typed")


MANIFEST = """
    [project]
    packs = ["marketing"]

    [marketing]
    work = "content/*"

    [marketing.purposes.growth]
    goal = "follows"

    [marketing.results]
    baseline = "own-median"
    second_number = "saves"
    min_items_to_judge = 3
    min_items_to_rank = 6
"""


def _items(world: World, series: str, follows: list[int]) -> None:
    for number, value in enumerate(follows):
        unit = f"content/{series}-{number}"
        world.write(f"{unit}/brief.toml", f'kind = "content"\ntitle = "t"\npurpose = "growth"\nseries = "{series}"\n')
        world.write(f"{unit}/result.toml", f'read_at = "2026-03-01"\nage_days = 7\nsource = "an export"\n\n'
                                           f"[metrics]\nfollows = {value}\nsaves = 2\nviews = 1000\n")


def _decided(world: World, **typed: Any) -> None:
    """Two series with results, and a decision whose numbers were built from them, then altered
    by whatever the proof types over them."""
    from themis import manifest as manifests

    world.manifest(MANIFEST)
    _items(world, "alpha", [9, 8, 9, 7, 9, 8])
    _items(world, "beta", [2, 3, 2, 1, 2, 3])
    built = {**build(world.root, manifests.load(world.root), "alpha", "beta", as_of="2026-03-02"), **typed}
    world.write("decision-inputs/alpha.json", json.dumps(built))
    world.write("decisions/alpha.json", json.dumps({
        "work": "series/alpha", "decision": "lead", "verdict": "pass", "gate": GATE, "gate_version": "1",
        "decided_at": "2026-03-02T00:00:00+00:00", "inputs": "decision-inputs/alpha.json",
    }))


@proof("results/inputs-rebuilt", "numbers built from the result records", expect="pass")
def _(world: World) -> None:
    _decided(world)


@proof("results/inputs-rebuilt", "a result that arrived after the decision's day changes nothing", expect="pass")
def _(world: World) -> None:
    _decided(world)
    world.write("content/beta-9/brief.toml", 'kind = "content"\ntitle = "t"\npurpose = "growth"\nseries = "beta"\n')
    world.write("content/beta-9/result.toml", 'read_at = "2026-04-01"\nage_days = 7\nsource = "an export"\n\n'
                                              "[metrics]\nfollows = 99\nsaves = 2\nviews = 1000\n")


@proof("results/inputs-rebuilt", "a kinder threshold typed into the numbers", expect="fail", contains="min_items_to_rank")
def _(world: World) -> None:
    _decided(world, min_items_to_rank=2)


@proof("results/inputs-rebuilt", "an item's result typed higher than its record", expect="fail", contains="differ from the records in: series")
def _(world: World) -> None:
    from themis import manifest as manifests

    _decided(world)
    built = build(world.root, manifests.load(world.root), "alpha", "beta", as_of="2026-03-02")
    built["series"]["alpha"][0]["goal"] = 90
    world.write("decision-inputs/alpha.json", json.dumps(built))


@proof("results/inputs-rebuilt", "a result record edited after the decision", expect="fail", contains="differ from the records in")
def _(world: World) -> None:
    _decided(world)
    world.write("content/alpha-0/result.toml", 'read_at = "2026-03-01"\nage_days = 7\nsource = "an export"\n\n'
                                               "[metrics]\nfollows = 1\nsaves = 2\nviews = 1000\n")


@proof("results/inputs-rebuilt", "a decision that names no file of its numbers", expect="refuse", contains="does not name a readable file")
def _(world: World) -> None:
    _decided(world)
    world.remove("decision-inputs/alpha.json")


@proof("results/inputs-rebuilt", "the owner's own call is not rebuilt", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    world.manifest(MANIFEST)
    world.write("decisions/alpha.json", json.dumps({
        "work": "series/alpha", "decision": "keep", "verdict": "pass", "gate": GATE, "gate_version": "owner",
        "decided_at": "2026-03-02T00:00:00+00:00", "by": "owner", "reason": "kept while a rival is planned",
    }))
