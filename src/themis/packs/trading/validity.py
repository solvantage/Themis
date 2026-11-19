"""Gate: validity — the statistics can be trusted.

Seven rules about the numbers a study rests on. Beside the layout in `units.py`, they read:

    PRE-REG.md              frontmatter `cost_model`: a name declared under [trading.costs]
    results/scorecard.csv   a CSV with at least the columns `line` and `value`
    results/metrics.json    `net_of_cost`, which must be true, and `costs_paid`, 0 or more
    AUDIT.md                frontmatter `status` (reproduced, differences-explained or not-yet), `script` (a file
                            in the study folder) and `study_code` (the study's own modules, as a list)
    a decision record       `numbers.mde` and `numbers.power` on a fail but a tune kill; `numbers.confirm_model`
                            on a tune pass
    a comparison record     `runs`: two or more runs set side by side, each with `run` (its id) and the
                            fingerprint fields the project names, such as window, cost_model or session
"""

from __future__ import annotations

import ast
import csv
import io
import json
import math
import posixpath
from typing import TYPE_CHECKING, Any

from themis import records
from themis.packs.trading import trades, units
from themis.rule import Context, Param, proof, rule
from themis.schema import ANY, Required

if TYPE_CHECKING:
    from themis.proofs import World

records.register("comparison", {
    "what": str, "runs": Required([{"run": Required(str), "*": ANY}]), "*": ANY,
}, "comparisons/**/*.json")

SHOWN = 5  # the unfillable trades named one by one; the rest are counted
BASELINES = ("always_long", "always_short")
AUDITED = ("reproduced", "differences-explained")
MANIFEST = """
    [project]
    packs = ["trading"]

    [trading]
    work = "work/*"
"""
COSTED = MANIFEST + """
    [trading.costs.example]
    toll_per_side = 0.1
    derivation = "work/2026-01-10_cost-study"
"""
TUNED = MANIFEST + """
    [trading.tune]
    confirm_model = "real ticks"
"""
BOTH = ("net_return,412.5", "always_long,120", "always_short,-135.5")  # scorecard rows
NET = {"net_of_cost": True, "costs_paid": 12.5}  # a metrics file
KILL = {"decision": "kill", "verdict": "fail"}  # a decision's fields


def _number(value: Any) -> bool:
    """True for a real, finite number. True and false are not numbers."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _shown(value: Any) -> str:
    """A value from a record, as its file shows it."""
    return "missing" if value is None else json.dumps(value)


def _study(world: World, kind: str = "strategy", name: str = "a", plan: str = "", manifest: str = MANIFEST) -> str:
    """A sealed study of that kind; the first one in a world also writes the manifest. Returns its folder."""
    if not (world.root / "themis.toml").exists():
        world.manifest(manifest)
    world.write(f"work/{name}/PRE-REG.md", f"---\nkind: {kind}\n{plan}---\n\nThe plan.\n")
    return f"work/{name}"


def _decided(world: World, kind: str = "strategy", name: str = "a", manifest: str = MANIFEST, **changes: Any) -> str:
    """A sealed study with a decision record: a pass, unless `changes` say otherwise."""
    fields = {"work": f"work/{name}", "decision": "keep", "verdict": "pass", "gate": "direction",
              "gate_version": "1", "decided_at": "2026-02-01T09:00:00+00:00"}
    world.write(f"decisions/{name}.json", json.dumps({**fields, **changes}))
    return _study(world, kind, name, manifest=manifest)


def _with(rule_id: str, setting: str) -> str:
    """The manifest, with one parameter of one rule set."""
    return MANIFEST + f'\n    [rules."{rule_id}"]\n    {setting}\n'


# -- validity/fills-on-tape ---------------------------------------------------------------------


@rule("validity/fills-on-tape", "Every simulated fill sits between its bar's low and high.", pack="trading",
      learned="A backtest booked fills at prices that never traded, and its profit was made of them.")
def fills_on_tape(ctx: Context) -> None:
    fix = "book each fill at a price its bar traded at, then run the study again"
    for unit, files in sorted(units.studies(ctx).items()):
        path = f"{unit}/{units.TRADES}"
        if path not in files:
            continue  # a study that books no trades has no fills
        try:
            booked = trades.read_trades(ctx.root / path)
        except (OSError, ValueError) as error:
            ctx.refuse(f"the trade table cannot be read: {error}", where=path,
                       fix="write the table with the standard columns, one closed trade to a row")
            continue
        bare = sum(trade.bar_low is None for trade in booked)
        ctx.inspect(len(booked) - bare)
        if bare:
            ctx.refuse(f"{bare} of the {len(booked)} trades carry no bar_low and bar_high, so their fills cannot be "
                       "checked", where=path, fix="add the low and high of the bar each trade was filled in")
        outside = trades.unfillable(booked)
        for number, trade in outside[:SHOWN]:
            low, high = trades.show(trade.bar_low), trades.show(trade.bar_high)
            ctx.breach(f"row {number}: the {trade.side} entry at {trades.show(trade.entry_price)} is outside its bar, "
                       f"which ran from {low} to {high}", where=path, fix=fix)
        if len(outside) > SHOWN:
            ctx.breach(f"{len(outside) - SHOWN} more fills in this table are outside their bars", where=path, fix=fix)


def _fills(world: World, *fills: str, columns: str = "entry_price,bar_low,bar_high") -> None:
    """A study whose trade table holds one long trade for each fill: its entry price, bar low and bar high."""
    rows = [f"2026-01-05T09:30:00,2026-01-05T10:30:00,long,1,102,0.1,0.9,{fill}" for fill in fills]
    table = "\n".join([f"entry_time,exit_time,side,size,exit_price,costs,net,{columns}", *rows])
    world.write(f"{_study(world)}/{units.TRADES}", table + "\n")


@proof("validity/fills-on-tape", "every fill inside its bar, one of them exactly at the high", expect="pass")
def _(world: World) -> None:
    _fills(world, "100.5,100,101", "101,100,101")
    _study(world, "signal", "b")  # a study that books no trades is left alone


@proof("validity/fills-on-tape", "one fill above its bar's high", expect="fail",
       contains="row 2: the long entry at 101.5 is outside its bar, which ran from 100 to 101")
def _(world: World) -> None:
    _fills(world, "100.5,100,101", "101.5,100,101")


@proof("validity/fills-on-tape", "seven fills below their bars: five named, two counted", expect="fail",
       contains="2 more fills in this table are outside their bars")
def _(world: World) -> None:
    _fills(world, *["99.5,100,101"] * 7)


@proof("validity/fills-on-tape", "a table with no bars", expect="refuse", contains="carry no bar_low and bar_high")
def _(world: World) -> None:
    _fills(world, "100.5", columns="entry_price")


@proof("validity/fills-on-tape", "a price written as a word", expect="refuse", contains="entry_price is not a number")
def _(world: World) -> None:
    _fills(world, "market,100,101")


# -- validity/baselines -------------------------------------------------------------------------


def _scorecard(ctx: Context, path: str) -> dict[str, str] | None:
    """The scorecard's value for each line, or None after a refusal that says it cannot be read."""
    reader = csv.DictReader(io.StringIO((ctx.read(path) or "").lstrip("\ufeff")), skipinitialspace=True)
    rows = list(reader)
    if not {"line", "value"} <= set(reader.fieldnames or []):
        ctx.refuse("the scorecard cannot be read as a CSV with the columns line and value", where=path,
                   fix="give the scorecard a header row with at least the columns line and value")
        return None
    return {(row["line"] or "").strip(): (row["value"] or "").strip() for row in rows}


@rule("validity/baselines", "The scorecard carries the always-long and always-short baselines.", pack="trading",
      params=(Param("extra", [str], [], "larger", "further baseline lines the scorecard must carry"),),
      learned="A strategy looked skilled until it was laid beside simply holding, which had done as well.")
def baselines(ctx: Context) -> None:
    fix = "run each baseline over the same window and costs as the strategy, and give it its own scorecard line"
    for unit, files in sorted(units.studies(ctx).items()):
        path = f"{unit}/{units.SCORECARD}"
        if path not in files or units.kind(ctx, unit, files) != "strategy":
            continue
        ctx.inspect()
        lines = _scorecard(ctx, path)
        for name in (*BASELINES, *(ctx.param("extra") or ())) if lines is not None else ():
            if name not in lines:
                ctx.breach(f"the scorecard has no {name} line", where=path, fix=fix)
            elif not lines[name] or lines[name].upper().startswith("NOT RUN"):
                ctx.breach(f"the scorecard's {name} baseline was not run: its value is {lines[name] or 'empty'}",
                           where=path, fix=fix)


def _scored(world: World, *lines: str, kind: str = "strategy", name: str = "a", manifest: str = MANIFEST) -> None:
    """A study whose scorecard holds these rows."""
    unit = _study(world, kind, name, manifest=manifest)
    world.write(f"{unit}/{units.SCORECARD}", "\n".join(["line,value", *lines]) + "\n")


@proof("validity/baselines", "both baselines carry a value; another line was not run", expect="pass")
def _(world: World) -> None:
    _scored(world, *BOTH, "luck_adjusted_sharpe,NOT RUN")
    _scored(world, "forward_return,0.4", kind="signal", name="b")  # a signal books no trades to compare


@proof("validity/baselines", "no always-short line", expect="fail", contains="the scorecard has no always_short line")
def _(world: World) -> None:
    _scored(world, *BOTH[:2])


@proof("validity/baselines", "a baseline the project added, marked not run", expect="fail",
       contains="the scorecard's random_entry baseline was not run: its value is NOT RUN")
def _(world: World) -> None:
    _scored(world, *BOTH, "random_entry,NOT RUN", manifest=_with("validity/baselines", 'extra = ["random_entry"]'))


@proof("validity/baselines", "a scorecard with no value column", expect="refuse", contains="cannot be read as a CSV")
def _(world: World) -> None:
    world.write(f"{_study(world)}/{units.SCORECARD}", "line,result\nalways_long,120\nalways_short,-135.5\n")


# -- validity/net-of-cost -----------------------------------------------------------------------


@rule("validity/net-of-cost", "The binding number is net of a cost that cites how it was derived.", pack="trading",
      learned="A result was quoted before costs, and the edge was smaller than the cost of trading it.")
def net_of_cost(ctx: Context) -> None:
    declared = ctx.manifest.table("trading").get("costs", {})
    for unit, files in sorted(units.studies(ctx).items()):
        sealed = units.seal(ctx, unit, files) if units.has_results(unit, files) else None
        if sealed is None or sealed[1].get("kind") not in ("strategy", "tune"):
            continue
        ctx.inspect()
        name, path = sealed[1].get("cost_model"), f"{unit}/{units.METRICS}"
        if name is None or str(name) not in declared:
            ctx.breach(f"the seal names no cost model that the manifest declares: cost_model is {_shown(name)}",
                       where=sealed[0], fix="name a model declared under [trading.costs], which cites its derivation")
        metrics = units.read_json(ctx, path)
        if metrics is None:
            if not ctx.exists(path):
                ctx.refuse("this study has results and no metrics file, so its binding number cannot be read",
                           where=path, fix="run the study so that it writes results/metrics.json")
            continue
        net, paid = metrics.get("net_of_cost"), metrics.get("costs_paid")
        if net is not True or not _number(paid) or paid < 0:
            ctx.breach(f"the metrics do not state a number net of cost: net_of_cost is {_shown(net)} and costs_paid "
                       f"is {_shown(paid)}", where=path, fix="take the model's costs off every trade, then write "
                       "net_of_cost as true and costs_paid as the total paid in fees, spread and funding")


def _costed(world: World, plan: str = "cost_model: example\n", metrics: dict[str, Any] | None = NET,
            kind: str = "strategy", name: str = "a") -> None:
    """A study with results: its seal's plan, and its metrics file unless `metrics` is None."""
    unit = _study(world, kind, name, plan, COSTED)
    world.write(f"{unit}/results/report.html", "<p>the report</p>\n")
    if metrics is not None:
        world.write(f"{unit}/{units.METRICS}", json.dumps(metrics))


@proof("validity/net-of-cost", "a net number under a cost model the manifest declares", expect="pass")
def _(world: World) -> None:
    _costed(world)
    _costed(world, metrics={**NET, "costs_paid": 0}, kind="tune", name="b")  # nothing paid is still a number
    _costed(world, plan="", metrics={}, kind="data", name="c")  # a study that books nothing has no cost to net


@proof("validity/net-of-cost", "a cost model nobody declared", expect="fail", contains='cost_model is "guess"')
def _(world: World) -> None:
    _costed(world, plan="cost_model: guess\n")


@proof("validity/net-of-cost", "numbers stated before costs", expect="fail", contains="net_of_cost is false")
def _(world: World) -> None:
    _costed(world, metrics={**NET, "net_of_cost": False})


@proof("validity/net-of-cost", "metrics that leave out what was paid", expect="fail", contains="costs_paid is missing")
def _(world: World) -> None:
    _costed(world, metrics={"net_of_cost": True})


@proof("validity/net-of-cost", "results with no metrics file", expect="refuse", contains="results and no metrics file")
def _(world: World) -> None:
    _costed(world, metrics=None)


# -- validity/power-stated ----------------------------------------------------------------------


@rule("validity/power-stated",
      "A kill states the power it had, and a fail with too little power is recorded as a deferral.", pack="trading",
      params=(Param("min_power", float, 0.8, "higher", "the least power a test must have had for its fail to stand"),),
      learned="An idea was killed by a test too small to see the effect it was looking for.")
def power_stated(ctx: Context) -> None:
    studies, least = units.studies(ctx), ctx.param("min_power")
    fix = ('a fail with too little power is recorded with the verdict "refuse" and the decision "defer"; a fail '
           "that stands states numbers.mde, the smallest effect its test could have seen, and numbers.power")
    for unit, found in sorted(units.decisions(ctx).items()):
        if unit in studies and units.kind(ctx, unit, studies[unit]) == "tune":
            ctx.inspect(len(found))  # read and passed over, as a strategy's pass is
            continue  # a tune kill is a stage outcome, such as a budget spent or a stage failed: no weak test
        for record in found if unit in studies else ():
            ctx.inspect()
            if record.get("verdict") != "fail" or record.get("by") == "owner":
                continue  # not a kill, or the owner's own call
            numbers = record.get("numbers") or {}
            mde, power = numbers.get("mde"), numbers.get("power")
            if not _number(mde) or not _number(power) or not least <= power <= 1:
                ctx.breach("this fail does not show enough power to stand, so it is a deferral and not a kill: "
                           f"numbers.mde is {_shown(mde)}, numbers.power is {_shown(power)}, and this project asks "
                           f"for a power of at least {least}", where=record.path, fix=fix)


@proof("validity/power-stated", "a kill that states its power, a deferral, and the owner's own kill", expect="pass")
def _(world: World) -> None:
    _decided(world, **KILL, numbers={"mde": 0.02, "power": 0.8})
    _decided(world, name="b", decision="defer", verdict="refuse", numbers={"power": 0.3})
    _decided(world, name="c", **KILL, by="owner", reason="the venue closed, so the idea cannot be traded")
    _decided(world, name="d", work="notes/d", **KILL)  # a decision that names no study of this project


@proof("validity/power-stated", "a kill with no power statement", expect="fail", contains="numbers.power is missing")
def _(world: World) -> None:
    _decided(world, **KILL, numbers={"mde": 0.02})


@proof("validity/power-stated", "a tune kill is a stage outcome, not an under-powered test", expect="pass")
def _(world: World) -> None:
    _decided(world, "tune", **KILL, numbers={"settings_tried": 51, "budget": 50})
    _decided(world, name="b", **KILL, numbers={"mde": 0.02, "power": 0.8})


@proof("validity/power-stated", "only a tune kill, read and passed over", expect="pass")
def _(world: World) -> None:
    _decided(world, "tune", **KILL, numbers={"settings_tried": 51, "budget": 50})


@proof("validity/power-stated", "a strategy kill with no power, beside a tune kill", expect="fail",
       contains="numbers.mde is missing, numbers.power is missing")
def _(world: World) -> None:
    _decided(world, "tune", **KILL, numbers={"settings_tried": 51, "budget": 50})
    _decided(world, name="b", **KILL)


@proof("validity/power-stated", "a kill with no smallest effect", expect="fail", contains="numbers.mde is missing")
def _(world: World) -> None:
    _decided(world, **KILL, numbers={"power": 0.9})


@proof("validity/power-stated", "a kill with less power than the project asks for", expect="fail",
       contains="numbers.power is 0.85, and this project asks for a power of at least 0.9")
def _(world: World) -> None:
    _decided(world, manifest=_with("validity/power-stated", "min_power = 0.9"), **KILL,
             numbers={"mde": 0.02, "power": 0.85})


@proof("validity/power-stated", "a decision record that cannot be read", expect="refuse", contains="is not valid JSON")
def _(world: World) -> None:
    _decided(world)
    world.write("decisions/a.json", '{"work": "work/a", "verdict": "fail"\n')


# -- validity/audit-reproduced ------------------------------------------------------------------


def _imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Each name a script imports, as (line, dotted name). `from a import b` is a.b, which lies under a."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            base = getattr(node, "module", None) or ""
            found += [(node.lineno, f"{base}.{alias.name}".strip(".*")) for alias in node.names]
    return found


def _covers(name: Any, module: str) -> bool:
    """True when the module is the one named, or lies under it. The name may be written as a file."""
    name = str(name).strip().removesuffix(".py").replace("/", ".")
    return module == name or module.startswith(name + ".")


def _separate(ctx: Context, script: str, own: Any) -> None:
    """Breach for each import, in an audit script, of the study's own code or of code the project forbids."""
    try:
        tree = ast.parse(ctx.read(script))
    except (SyntaxError, ValueError, TypeError):  # not Python, or not text at all
        ctx.refuse("the audit script cannot be read as Python, so its imports cannot be checked", where=script,
                   fix="write the audit script in Python")
        return
    own = own if isinstance(own, list) else [own or ""]
    for line, module in _imports(tree):
        mine = any(_covers(name, module) for name in own)
        if mine or any(_covers(name, module) for name in ctx.param("forbidden") or ()):
            whose = "the study's own code" if mine else "code this project forbids an audit to use"
            ctx.breach(f"the audit script imports {module}, {whose}", where=script, line=line,
                       fix="an audit rebuilds the numbers from the study's inputs with code of its own")


@rule("validity/audit-reproduced",
      "A study's numbers are decided on only after a separate script reproduces them.", pack="trading",
      params=(Param("forbidden", [str], [], "larger", "modules, and those under them, no audit script may import"),),
      learned="A study stopped reproducing its own numbers, and the check that should have seen it shared its code.")
def audit_reproduced(ctx: Context) -> None:
    decided = units.decisions(ctx)
    fix = "reproduce the headline numbers with a separate script in the study folder, and name it in AUDIT.md"
    for unit, files in sorted(units.studies(ctx).items()):
        if unit not in decided or units.kind(ctx, unit, files) not in ("strategy", "signal"):
            continue
        ctx.inspect()
        path = f"{unit}/{units.AUDIT}"
        if path not in files:
            ctx.breach("this study has a decision and no audit", where=unit, fix=fix)
            continue
        try:
            audit = records.frontmatter(ctx.read(path) or "")
        except ValueError:
            audit = None
        if audit is None:
            ctx.refuse("the audit's frontmatter cannot be read", where=path,
                       fix="start AUDIT.md with a block between two --- lines that holds status and script")
            continue
        status, named = audit.get("status"), str(audit.get("script") or "")
        script = posixpath.normpath(f"{unit}/{named}")
        if status not in AUDITED:
            ctx.breach(f"this study has a decision, but its audit's status is {status or 'missing'}", where=path,
                       fix="decide only once the audit's status is reproduced or differences-explained")
        elif script not in files:
            ctx.breach(f"the audit names no script that is in the study folder: script is {named or 'missing'}",
                       where=path, fix=fix)
        else:
            own = audit.get("study_code")
            if any(name and _covers(name, named.removesuffix(".py").replace("/", "."))
                   for name in (own if isinstance(own, list) else [own])):
                ctx.breach(f"the audit names the study's own code, {named}, as the script that checked it",
                           where=path, fix="an audit rebuilds the numbers with a script of its own")
            _separate(ctx, script, own)


def _audited(world: World, status: str = "reproduced", source: str | None = "import csv\n",
             code: str = "study_code: [run, lib.model]\n", name: str = "a", manifest: str = MANIFEST) -> None:
    """A decided study with its AUDIT.md, and the script the audit names unless `source` is None."""
    unit = _decided(world, name=name, manifest=manifest)
    world.write(f"{unit}/AUDIT.md", f"---\nstatus: {status}\nscript: audit.py\n{code}---\n\nHow the check ended.\n")
    if source is not None:
        world.write(f"{unit}/audit.py", source)


@proof("validity/audit-reproduced", "a separate script reproduced the numbers", expect="pass")
def _(world: World) -> None:
    _audited(world, source="import csv\nimport runpy  # not the study's run module\nfrom statistics import mean\n")
    _audited(world, "differences-explained", name="b")
    _decided(world, "data", "c")  # a study that selects nothing needs no audit
    _study(world, name="d")  # nor does a study that has no decision yet


@proof("validity/audit-reproduced", "a decision with no audit", expect="fail", contains="has a decision and no audit")
def _(world: World) -> None:
    _decided(world, "signal")


@proof("validity/audit-reproduced", "a decision before its audit was done", expect="fail", contains="status is not-yet")
def _(world: World) -> None:
    _audited(world, "not-yet")


@proof("validity/audit-reproduced", "an audit script that imports the study's own code", expect="fail",
       contains="the audit script imports run.backtest, the study's own code")
def _(world: World) -> None:
    _audited(world, source="import csv\nfrom run import backtest\n")


@proof("validity/audit-reproduced", "the study's own run script named as its audit", expect="fail",
       contains="the audit names the study's own code, run.py, as the script that checked it")
def _(world: World) -> None:
    unit = _decided(world)
    world.write(f"{unit}/AUDIT.md",
                "---\nstatus: reproduced\nscript: run.py\nstudy_code: [run, lib.model]\n---\n\nDone.\n")
    world.write(f"{unit}/run.py", "import csv\n")


@proof("validity/audit-reproduced", "an audit script that imports a library the project forbids", expect="fail",
       contains="the audit script imports research.lib.costs, code this project forbids an audit to use")
def _(world: World) -> None:
    _audited(world, source="from research.lib import costs\n", code="",
             manifest=_with("validity/audit-reproduced", 'forbidden = ["research.lib.costs"]'))


@proof("validity/audit-reproduced", "an audit that names a script that is not there", expect="fail",
       contains="names no script that is in the study folder: script is audit.py")
def _(world: World) -> None:
    _audited(world, source=None)


@proof("validity/audit-reproduced", "an audit in plain prose", expect="refuse", contains="frontmatter cannot be read")
def _(world: World) -> None:
    world.write(f"{_decided(world)}/AUDIT.md", "Reproduced. See audit.py.\n")


@proof("validity/audit-reproduced", "an audit script that is not Python", expect="refuse", contains="be read as Python")
def _(world: World) -> None:
    _audited(world, source="reproduce <- function(trades) sum(trades$net)\n")


# -- validity/confirm-on-real-ticks -------------------------------------------------------------


@rule("validity/confirm-on-real-ticks",
      "A tuning study's confirming run uses the most faithful model the project named.", pack="trading",
      learned="Tuned settings passed on a coarse price model, and lost once every tick was replayed.")
def confirm_on_real_ticks(ctx: Context) -> None:
    wanted = ctx.manifest.table("trading").get("tune", {}).get("confirm_model")
    if not wanted:
        ctx.not_configured('set confirm_model under [trading.tune], such as confirm_model = "real ticks"')
    decided = units.decisions(ctx)
    fix = f"run the confirming run on the model {_shown(wanted)}, and issue the decision again from that run"
    for unit, files in sorted(units.studies(ctx).items()):
        if unit not in decided or units.kind(ctx, unit, files) != "tune":
            continue
        for record in decided[unit]:
            if record.get("verdict") != "pass":
                continue  # only a pass rests on the confirming run; a fail or a refusal ships nothing
            ctx.inspect()
            used = (record.get("numbers") or {}).get("confirm_model")
            if used is None or " ".join(str(used).split()).casefold() != " ".join(wanted.split()).casefold():
                ctx.breach(f"the confirming run did not use the model this project named, {_shown(wanted)}: "
                           f"numbers.confirm_model is {_shown(used)}", where=record.path, fix=fix)


@proof("validity/confirm-on-real-ticks", "confirmed on the model the project named", expect="pass")
def _(world: World) -> None:
    _decided(world, "tune", manifest=TUNED, numbers={"confirm_model": "Real ticks"})
    _decided(world, name="b")  # a strategy study has no confirming run
    _study(world, "tune", "c")  # a tuning study that has no decision yet has nothing to confirm


@proof("validity/confirm-on-real-ticks", "a study that failed needs no confirming run", expect="pass")
def _(world: World) -> None:
    _decided(world, "tune", manifest=TUNED, numbers={"confirm_model": "Real ticks"})
    _decided(world, "tune", "b", decision="kill", verdict="fail", numbers={"trades": 12})


@proof("validity/confirm-on-real-ticks", "confirmed on a coarser model", expect="fail",
       contains='the model this project named, "real ticks": numbers.confirm_model is "open prices only"')
def _(world: World) -> None:
    _decided(world, "tune", manifest=TUNED, numbers={"confirm_model": "open prices only"})


@proof("validity/confirm-on-real-ticks", "a decision with no model", expect="fail", contains="confirm_model is missing")
def _(world: World) -> None:
    _decided(world, "tune", manifest=TUNED, numbers={"trades": 412})


@proof("validity/confirm-on-real-ticks", "a decision that cannot be read", expect="refuse", contains="not valid JSON")
def _(world: World) -> None:
    _decided(world, "tune", manifest=TUNED)
    world.write("decisions/a.json", '{"work": "work/a", "numbers": {"confirm_model": "real ticks"}\n')


# -- validity/same-basis ------------------------------------------------------------------------


@rule("validity/same-basis",
      "A comparison sets side by side only runs that share every fingerprint field the project names.",
      pack="trading",
      params=(Param("fields", [str], None, "larger",
                    "the fingerprint fields every run in a comparison must share, such as window or cost_model"),),
      requires=("fields",),
      learned="Two runs were ranked against each other though their costs came from different days, and the "
              "ranking measured the costs.")
def same_basis(ctx: Context) -> None:
    fix = "compare only runs made on the same basis: run them again on one basis, or drop this comparison"
    for record in ctx.records("comparison"):
        ctx.inspect()
        runs = record.get("runs")
        named = sorted({run["run"] for run in runs})
        if len(named) < 2:
            held = (f"holds {len(runs)} piece{'s' * (len(runs) > 1)} of {_shown(named[0])}: one run cut into "
                    "pieces, such as by year, is not a comparison") if named else "lists no run"
            ctx.breach(f"a comparison sets two or more runs side by side, and this one {held}", where=record.path,
                       fix="write a comparison record only for two or more runs, and none for one run's pieces")
            continue
        for field in ctx.param("fields"):
            bare = [run["run"] for run in runs if run.get(field) in (None, "")]
            if bare:
                ctx.breach(f"{', '.join(bare)} state{'s' * (len(bare) == 1)} no {field}, so the runs cannot be "
                           "shown to share it", where=record.path, fix=f"record each run's {field} beside it")
                continue
            held = [(run["run"], json.dumps(run[field], sort_keys=True)) for run in runs]
            if len({json.dumps(_basis(run[field]), sort_keys=True) for run in runs}) > 1:
                ctx.breach(f"the runs differ in {field}: " + ", ".join(f"{run} has {value}" for run, value in held),
                           where=record.path, fix=fix)


def _basis(value: Any) -> Any:
    """A fingerprint value as it is compared: a whole number is one number, written as 2 or as 2.0."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _basis(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_basis(item) for item in value]
    return value


BASIS = MANIFEST + """
    [rules."validity/same-basis"]
    fields = ["window", "cost_model", "session"]
"""
RUN = {"window": "2020-01-01..2024-12-31", "cost_model": "example", "session": "2026-03-02"}


def _compared(world: World, *runs: dict[str, Any], name: str = "a") -> None:
    """A comparison record of these runs, each the shared basis with its own changes."""
    if not (world.root / "themis.toml").exists():
        world.manifest(BASIS)
    world.write(f"comparisons/{name}.json", json.dumps({"what": "which settings did better",
                                                         "runs": [{**RUN, **run} for run in runs]}))


@proof("validity/same-basis", "two settings compared on one basis", expect="pass")
def _(world: World) -> None:
    _compared(world, {"run": "a-1", "settings": "3f9a"}, {"run": "b-1", "settings": "77c0"})
    _compared(world, {"run": "a-1"}, {"run": "b-1"}, {"run": "c-1", "note": "a third"}, name="b")


@proof("validity/same-basis", "one cost written as a whole number in one run and with a point in the other",
       expect="pass")
def _(world: World) -> None:
    _compared(world, {"run": "a-1", "cost_model": {"toll": 2, "spread": [1, 0.5]}},
              {"run": "b-1", "cost_model": {"spread": [1.0, 0.5], "toll": 2.0}})


@proof("validity/same-basis", "two costs that differ, written as numbers", expect="fail",
       contains="the runs differ in cost_model")
def _(world: World) -> None:
    _compared(world, {"run": "a-1", "cost_model": {"toll": 2}}, {"run": "b-1", "cost_model": {"toll": 2.5}})


@proof("validity/same-basis", "runs from two different sessions", expect="fail",
       contains='the runs differ in session: a-1 has "2026-03-02", b-1 has "2026-03-03"')
def _(world: World) -> None:
    _compared(world, {"run": "a-1"}, {"run": "b-1", "session": "2026-03-03"})


@proof("validity/same-basis", "a run that does not state its cost model", expect="fail",
       contains="b-1 states no cost_model")
def _(world: World) -> None:
    _compared(world, {"run": "a-1"}, {"run": "b-1", "cost_model": None})


@proof("validity/same-basis", "one run cut into years, recorded as a comparison", expect="fail",
       contains='holds 2 pieces of "a-1": one run cut into pieces, such as by year, is not a comparison')
def _(world: World) -> None:
    _compared(world, {"run": "a-1", "window": "2023"}, {"run": "a-1", "window": "2024"})


@proof("validity/same-basis", "a run with no id", expect="refuse", contains="comparison.runs[1].run is required")
def _(world: World) -> None:
    _compared(world, {"run": "a-1"}, {"settings": "77c0"})
