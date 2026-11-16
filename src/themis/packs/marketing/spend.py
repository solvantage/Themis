"""Gate: spend — every cost is a tool's figure, inside a budget.

A cost is never typed. Each paid job leaves a spend receipt, written by the tool that ran it:

    receipts/spend/<name>.json    item, amount, unit, tool, job, at, and kind (first-take or retake)

Each agent run leaves a run receipt:

    receipts/agent-run/<name>.json  role, at, cost, produced (a list of paths), flagged, reason

`item` is the item's folder. A receipt copied from `.themis/receipts/` to `receipts/` is the same
receipt, and is counted once. A receipt that cannot be read is refused, never skipped. In a
document, a cost is followed by an invisible tag that names the item whose spend it states, or
`total` for every item: `1,305<!--s:content/a-->`.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from themis import claims, receipts, schema
from themis.packs.marketing import items
from themis.rule import Context, Param, proof, rule
from themis.schema import ANY, Required

if TYPE_CHECKING:
    from themis.proofs import World

# A cost followed by `<!--s:ITEM-->` is cited: spend/figures-from-tools checks it against the spend
# receipts, so the core claims gate does not report it as a number with no record.
claims.register_citation("s")

SPEND = {"item": Required(str), "amount": Required(float), "tool": Required(str), "*": ANY}
DOCUMENTS = Param("documents", [str], None, "larger", "the documents that state costs, such as content/*/README.md")
MIN_LOOPS = Param("min_loops", int, 1, "lower",
                  "how many finished items, each with an estimate and a spend, before the overrun must be shown")
PAGES = ("README.md", "options.md")  # where an item shows its estimate to the owner
TOLERANCE = 0.05  # how far an overrun may sit from 1, or a stated overrun from the measured one
_TAG = re.compile(r"<!--\s*s:(?P<item>[^>]*?)\s*-->")
_NUMBER = r"(?<![\w.,])(?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_BEFORE = re.compile(_NUMBER + r"(?:[ \t]?[^\W\d_]{1,12})?[ \t]?[*_`]{0,4}$")  # 1,305 credits**<!--s:...-->
_STATED = re.compile(r"expected overrun[^\d\n]{0,20}(\d+(?:\.\d+)?)", re.IGNORECASE)


def money(value: float) -> str:
    """An amount as a page shows it: thousands separated, at most two decimals."""
    return f"{value:,.2f}".rstrip("0").rstrip(".")


#: The receipt of one agent run, kept apart from the core's `themis run` receipts, which record a
#: command and its exit status, not a cost and what was produced.
AGENT_RUN = "agent-run"


def read_receipts(root: Path, kind: str) -> list[dict[str, Any]]:
    """The receipts of one kind, each once: a committed copy of a local receipt is the same receipt."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for receipt in receipts.read_all(root, kind):
        data = {key: value for key, value in receipt.items() if key != "_path"}
        found.setdefault((Path(receipt["_path"]).name, json.dumps(data, sort_keys=True, default=str)), receipt)
    return list(found.values())


def spend_by_item(root: Path, unit: str | None = None) -> tuple[dict[str, list[dict[str, Any]]], list[tuple[str, str]]]:
    """The spend receipts by the item folder each names, and (path, problem) for each one that
    cannot be counted. `unit` is the unit the project counts in, when it set one."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    bad = [(path, "this spend receipt cannot be read") for path in receipts.unreadable(root, "spend")]
    for receipt in read_receipts(root, "spend"):
        data = {key: value for key, value in receipt.items() if key != "_path"}
        found = schema.problems(data, SPEND, "spend receipt")
        item = str(receipt.get("item", "")).strip("/")
        if not found and not math.isfinite(receipt["amount"]):
            found = ["spend receipt.amount must be a number"]
        if not found and (not item or ".." in item.split("/")):
            found = ["spend receipt.item must be an item's folder, inside the repository"]
        if not found and unit and receipt.get("unit") not in (None, unit):
            found = [f"this spend receipt is in {receipt['unit']}, and the project counts its spend in {unit}"]
        bad += [(receipt["_path"], problem) for problem in found]
        if not found:
            grouped.setdefault(item, []).append(receipt)
    return grouped, bad


def total(held: Iterable[dict[str, Any]]) -> float:
    return math.fsum(receipt["amount"] for receipt in held)


def overrun(pairs: Iterable[tuple[float, float]]) -> float | None:
    """Total spend over total estimate, for (estimate, spend) pairs. None when nothing was estimated."""
    pairs = list(pairs)
    estimated = math.fsum(estimate for estimate, _ in pairs)
    return math.fsum(spent for _, spent in pairs) / estimated if estimated > 0 else None


def produced_nothing(receipt: dict[str, Any]) -> bool:
    return receipt.get("produced") == []


def _spend(ctx: Context) -> dict[str, list[dict[str, Any]]]:
    grouped, bad = spend_by_item(ctx.root, items.table(ctx).get("spend", {}).get("unit"))
    for path, problem in bad:
        ctx.refuse(problem, where=path, fix="a receipt is written by a tool; run the tool's adapter again for this job")
    return grouped


# -- spend/priced-first -------------------------------------------------------------------------


@rule(
    "spend/priced-first",
    "No paid job is sent before its plan is priced and under its ceiling.",
    pack="marketing",
    learned="An approval pressed by mistake started a paid job that nobody had priced.",
)
def priced_first(ctx: Context) -> None:
    ceiling = items.table(ctx).get("spend", {}).get("run_ceiling")
    if ceiling is None:
        ctx.not_configured("set run_ceiling under [marketing.spend]: the most one item may cost")
    spent = _spend(ctx)
    for unit in sorted(set(spent) | set(items.items(ctx))):
        plan = items.load(ctx, unit, "plan")
        estimate = (plan or {}).get("estimate")
        if plan is None and ctx.exists(f"{unit}/plan.toml") or (estimate is None and unit not in spent):
            continue  # a plan that was refused above, or nothing priced and nothing spent yet
        ctx.inspect()
        paid = total(spent.get(unit, []))
        if estimate is None:
            ctx.breach(f"{money(paid)} was spent with no priced plan", where=unit,
                       fix="price the plan first: write its estimate into plan.toml before any paid job is sent")
        elif estimate > ceiling:
            ctx.breach(f"the plan's estimate of {money(estimate)} is above the run ceiling of {money(ceiling)}",
                       where=f"{unit}/plan.toml", fix="cut the plan to under the ceiling; only the owner raises it")
        if paid > ceiling:
            ctx.breach(f"this item has spent {money(paid)}, which is above the run ceiling of {money(ceiling)}",
                       where=unit, fix="send no more paid jobs for this item; only the owner raises a ceiling")


SETUP = """
    [project]
    packs = ["marketing"]

    [marketing]
    work = "content/*"

    [marketing.spend]
    unit = "credits"
    run_ceiling = 2000
"""
PART = '\n[[parts]]\nid = "hook"\nstart_s = 0.0\nend_s = 4.0\n'


def _receipt(world: World, name: str, item: str = "content/a", amount: Any = 600, **more: Any) -> None:
    fields = {"item": item, "amount": amount, "unit": "credits", "tool": "render-tool", "job": name,
              "at": "2026-03-02T10:00:00+00:00", **more}
    stated = {key: value for key, value in fields.items() if value is not None}
    world.write(f"receipts/spend/{name}.json", json.dumps(stated))


def _item(world: World, unit: str = "content/a", estimate: Any = 1000, spends: tuple[float, ...] = (600, 500),
          posted: bool = False, page: str = "") -> None:
    """One honest item: a plan priced at 1,000, and two receipts that add up to 1,100."""
    world.manifest(SETUP)
    world.write(f"{unit}/brief.toml", 'kind = "content"\ntitle = "A better cup"\n')
    world.write(f"{unit}/plan.toml", ("" if estimate is None else f"estimate = {estimate}\n") + PART)
    world.write(f"{unit}/README.md", page or "The plan is priced at 1,000 credits.\n")
    if posted:
        world.write(f"{unit}/post.toml", 'platform = "main-channel"\nat = "2026-03-03"\n')
    for number, amount in enumerate(spends, start=1):
        _receipt(world, f"{unit.rsplit('/', 1)[-1]}-{number}", unit, amount)


@proof("spend/priced-first", "a priced plan, and a spend over the estimate but under the ceiling", expect="pass")
def _(world: World) -> None:
    _item(world)


@proof("spend/priced-first", "an estimate and a spend that sit exactly on the ceiling", expect="pass")
def _(world: World) -> None:
    _item(world, estimate=2000, spends=(1500, 500))


@proof("spend/priced-first", "a plan priced above its ceiling, before anything is spent", expect="fail",
       contains="the plan's estimate of 2,400 is above the run ceiling of 2,000")
def _(world: World) -> None:
    _item(world, estimate=2400, spends=())


@proof("spend/priced-first", "a paid job with no plan", expect="fail", contains="600 was spent with no priced plan")
def _(world: World) -> None:
    _item(world)
    _receipt(world, "b-1", "content/b")


@proof("spend/priced-first", "retakes that carry the item past its ceiling", expect="fail",
       contains="this item has spent 2,100, which is above the run ceiling of 2,000")
def _(world: World) -> None:
    _item(world)
    _receipt(world, "a-3", amount=1000, kind="retake")


@proof("spend/priced-first", "a committed copy of a local receipt is counted once", expect="pass")
def _(world: World) -> None:
    _item(world, spends=(1500,))
    world.write(".themis/receipts/spend/a-1.json", (world.root / "receipts/spend/a-1.json").read_text(encoding="utf-8"))


@proof("spend/priced-first", "nothing priced and nothing spent yet", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _item(world, estimate=None, spends=())


@proof("spend/priced-first", "a receipt that is not valid JSON", expect="refuse", contains="receipt cannot be read")
def _(world: World) -> None:
    _item(world)
    world.write("receipts/spend/a-3.json", '{"item": "content/a", "amount": 900\n')


@proof("spend/priced-first", "a receipt in another unit cannot be added up", expect="refuse",
       contains="this spend receipt is in dollars, and the project counts its spend in credits")
def _(world: World) -> None:
    _item(world)
    _receipt(world, "a-3", unit="dollars")


# -- spend/figures-from-tools -------------------------------------------------------------------


def tagged_costs(text: str) -> list[tuple[int, str, str | None]]:
    """(line, the item a cost tag names, the number written right before it) for each cost tag
    outside a fenced code block. The number is None when no number sits right before the tag."""
    found, fenced = [], False
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        for tag in _TAG.finditer("" if fenced else line):
            before = _BEFORE.search(line[:tag.start()])
            found.append((line_number, tag["item"].strip("/ "), before["number"] if before else None))
    return found


@rule(
    "spend/figures-from-tools",
    "Every cost in a document equals a spend record.",
    pack="marketing",
    params=(DOCUMENTS,),
    requires=("documents",),
    learned="A cost stated in the owner's own pages was wrong: it had been typed, not read from the tool.",
)
def figures_from_tools(ctx: Context) -> None:
    spent = _spend(ctx)
    for path in sorted({path for pattern in ctx.param("documents") for path in ctx.files(pattern)}):
        for line, item, written in tagged_costs(ctx.read(path) or ""):
            ctx.inspect()
            held = [receipt for group in spent.values() for receipt in group] if item == "total" else spent.get(item)
            if not held or written is None:
                said = f"names {item}, which has no spend receipt" if not held else "has no number right before it"
                ctx.refuse(f"the cost tag on line {line} {said}", where=path,
                           fix="write the figure, then its tag, and name an item that has spend receipts")
                continue
            paid, decimals = total(held), len(written.partition(".")[2])
            if abs(float(written.replace(",", "")) - paid) > 0.5 * 10 ** -decimals + 1e-9:
                ctx.breach(f"this document says {written} for {item}, and its spend receipts add up to {money(paid)}",
                           where=path, line=line, fix="write the figure from the spend receipts; a cost is never typed")


COSTS = '\n    [rules."spend/figures-from-tools"]\n    documents = ["content/*/README.md", "docs/costs.md"]\n'


def _stated(world: World, page: str, path: str = "content/a/README.md") -> None:
    _item(world)
    world.manifest(SETUP + COSTS)
    world.write(path, page)


@proof("spend/figures-from-tools", "a cost that equals the item's receipts", expect="pass")
def _(world: World) -> None:
    _stated(world, "This item cost **1,100 credits**<!--s:content/a--> over 3 days.\n")


@proof("spend/figures-from-tools", "a rounded cost, a total over two items, and a tag shown inside a code block",
       expect="pass")
def _(world: World) -> None:
    _stated(world, "Both items cost 1,551<!--s:total-->.\n\n```\nwrite 9<!--s:content/a-->\n```\n", "docs/costs.md")
    _receipt(world, "b-1", "content/b", 450.6)


@proof("spend/figures-from-tools", "a cost that was typed and is wrong", expect="fail",
       contains="this document says 1,000 for content/a, and its spend receipts add up to 1,100")
def _(world: World) -> None:
    _stated(world, "This item cost 1,000<!--s:content/a-->.\n")


@proof("spend/figures-from-tools", "a total left behind by a later retake", expect="fail",
       contains="this document says 1,100 for total, and its spend receipts add up to 1,400")
def _(world: World) -> None:
    _stated(world, "Everything so far cost 1,100<!--s:total-->.\n", "docs/costs.md")
    _receipt(world, "a-3", amount=300, kind="retake")


@proof("spend/figures-from-tools", "a cost for an item that has no receipt", expect="refuse",
       contains="names content/b, which has no spend receipt")
def _(world: World) -> None:
    _stated(world, "The next item cost 800<!--s:content/b-->.\n")


@proof("spend/figures-from-tools", "a tag with no number before it", expect="refuse", contains="has no number right")
def _(world: World) -> None:
    _stated(world, "This item cost about a thousand<!--s:content/a-->.\n")


@proof("spend/figures-from-tools", "documents that tag no cost", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _stated(world, "This item cost 1,100 credits.\n")


# -- spend/estimate-calibrated ------------------------------------------------------------------


@rule(
    "spend/estimate-calibrated",
    "An estimate shown to the owner carries the measured overrun of past work.",
    pack="marketing",
    params=(MIN_LOOPS,),
    learned="An estimate fell a quarter short of the spend, and the next estimate was made the same way.",
)
def estimate_calibrated(ctx: Context) -> None:
    spent = _spend(ctx)
    finished, waiting = [], []
    for unit in sorted(items.items(ctx)):
        estimate = (items.load(ctx, unit, "plan") or {}).get("estimate")
        if estimate is None:
            continue  # no estimate is shown, so there is nothing to calibrate
        if not ctx.exists(f"{unit}/post.toml"):
            waiting.append(unit)
        elif estimate > 0 and unit in spent:
            finished.append((estimate, total(spent[unit])))
    ctx.inspect()
    measured = overrun(finished)
    if len(finished) < ctx.param("min_loops") or measured is None or measured <= 1 + TOLERANCE:
        return  # too little finished work to measure, or past work stayed near its estimates
    for unit in waiting:
        ctx.inspect()
        stated = [float(number) for page in PAGES for number in _STATED.findall(ctx.read(f"{unit}/{page}") or "")]
        if any(abs(value - measured) <= TOLERANCE + 1e-9 for value in stated):
            continue
        said = (f"states an expected overrun of {stated[0]:g}" if stated
                else "shows an estimate with no expected overrun")
        ctx.breach(f"this item {said}, and finished work cost {measured:.2f} times its estimates", where=unit,
                   fix=f"write `expected overrun: {measured:.2f}` beside the estimate, in README.md or options.md")


BARE = "Priced at 800 credits.\n"


def _loop(world: World, page: str = "Priced at 800 credits; expected overrun: 1.25.\n",
          spends: tuple[float, ...] = (750, 500)) -> None:
    """A finished item that cost 1.25 times its estimate, and a new item that shows its estimate."""
    _item(world, spends=spends, posted=True)
    _item(world, "content/b", estimate=800, spends=(), page=page)


@proof("spend/estimate-calibrated", "the new estimate carries the measured overrun", expect="pass")
def _(world: World) -> None:
    _loop(world)


@proof("spend/estimate-calibrated", "an overrun stated a little off, in the options page", expect="pass")
def _(world: World) -> None:
    _loop(world, BARE)
    world.write("content/b/options.md", "Plan B. Expected overrun of 1.21, from the last loop.\n")


@proof("spend/estimate-calibrated", "past work that stayed near its estimate asks for nothing", expect="pass")
def _(world: World) -> None:
    _loop(world, BARE, spends=(600, 440))


@proof("spend/estimate-calibrated", "too few finished items to measure an overrun", expect="pass")
def _(world: World) -> None:
    _loop(world, BARE)
    world.manifest(SETUP + '\n    [rules."spend/estimate-calibrated"]\n    min_loops = 2\n')


@proof("spend/estimate-calibrated", "a new estimate that says nothing of the overrun", expect="fail",
       contains="shows an estimate with no expected overrun, and finished work cost 1.25 times its estimates")
def _(world: World) -> None:
    _loop(world, BARE)


@proof("spend/estimate-calibrated", "an overrun left from an earlier, cheaper loop", expect="fail",
       contains="states an expected overrun of 1.1, and finished work cost 1.25 times its estimates")
def _(world: World) -> None:
    _loop(world, "Priced at 800 credits; expected overrun: 1.10.\n")


@proof("spend/estimate-calibrated", "a finished item whose receipt cannot be counted", expect="refuse",
       contains="spend receipt.amount must be a number")
def _(world: World) -> None:
    _loop(world)
    _receipt(world, "a-2", amount="five hundred")


# -- spend/agent-runs ---------------------------------------------------------------------------


@rule(
    "spend/agent-runs",
    "Each agent run records its cost and what it produced, and a run that produced nothing is flagged.",
    pack="marketing",
    learned="An agent run cost money and produced nothing, and nobody was told.",
)
def agent_runs(ctx: Context) -> None:
    for path in receipts.unreadable(ctx.root, AGENT_RUN):
        ctx.refuse("this run receipt cannot be read", where=path,
                   fix="a receipt is written by a tool; run the run's adapter again")
    for receipt in read_receipts(ctx.root, AGENT_RUN):
        ctx.inspect()
        where, cost, produced = receipt["_path"], receipt.get("cost"), receipt.get("produced")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost):
            ctx.breach("this agent run records no cost as a number", where=where,
                       fix="a run receipt is written by the run's adapter, with the cost the tool reported")
        said_why = receipt.get("flagged") is True and str(receipt.get("reason") or "").strip()
        if not isinstance(produced, list):
            ctx.breach("this agent run does not record what it produced", where=where,
                       fix="list the paths the run produced; an empty list says that it produced nothing")
        elif not produced and not said_why:
            ctx.breach("this agent run produced nothing, and it is not flagged with a reason", where=where,
                       fix="set flagged to true and give the reason, so the loop report lists the run")


def _run(world: World, name: str = "writer-1", **changes: Any) -> None:
    fields = {"role": "writer", "at": "2026-03-02T09:00:00+00:00", "cost": 40, "produced": ["content/a/brief.toml"]}
    world.manifest(SETUP)
    world.write(f"receipts/{AGENT_RUN}/{name}.json", json.dumps({**fields, **changes}))


@proof("spend/agent-runs", "a run with its cost and what it produced, a free run, and an idle run that says why",
       expect="pass")
def _(world: World) -> None:
    _run(world)
    _run(world, "writer-2", cost=0)
    _run(world, "writer-3", produced=[], flagged=True, reason="the topic was dropped by the owner")


@proof("spend/agent-runs", "a run receipt that is not valid JSON", expect="refuse", contains="receipt cannot be read")
def _(world: World) -> None:
    _run(world)
    world.write(f"receipts/{AGENT_RUN}/writer-2.json", '{"role": "writer", "cost": 40\n')


@proof("spend/agent-runs", "a cost written as text", expect="fail", contains="records no cost as a number")
def _(world: World) -> None:
    _run(world, cost="about forty")


@proof("spend/agent-runs", "a run that produced nothing and is not flagged", expect="fail",
       contains="produced nothing, and it is not flagged with a reason")
def _(world: World) -> None:
    _run(world)
    _run(world, "writer-2", produced=[])


@proof("spend/agent-runs", "a flag with no reason", expect="fail", contains="it is not flagged with a reason")
def _(world: World) -> None:
    _run(world, produced=[], flagged=True)


@proof("spend/agent-runs", "a run that does not say what it produced", expect="fail",
       contains="does not record what it produced")
def _(world: World) -> None:
    _run(world, produced=None)


@proof("spend/agent-runs", "no run receipt at all", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    world.manifest(SETUP)
