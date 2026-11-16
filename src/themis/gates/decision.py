"""Gate: decision — the numbers decide.

A decision is issued by a gate function, never typed by hand. A gate function lives in a pack,
under `Pack.gates`, by name. It is called with the work's metrics and returns its answer:

    gate(metrics: dict) -> dict

`metrics` is the work's metrics file, read as JSON. The answer holds at least `decision`, the
field's own word for the outcome, and `verdict`, which is "pass", "fail" or "refuse". A gate that
has too little evidence answers "refuse": it defers, it does not say no.

The rules here call the gate again on the same metrics and compare, ask a negative decision to
say its evidence was enough, and ask each gate for its calibration receipt: a JSON file under
`receipts/calibration/` with `gate`, `gate_version`, `false_alarm_rate` (the share of noise the
gate said yes to) and `power` (the share of planted effects it said yes to), both from 0 to 1.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from themis import receipts
from themis.rule import Context, Param, proof, rule

if TYPE_CHECKING:
    from themis.proofs import World
    from themis.records import Record

VERDICTS = ("pass", "fail", "refuse")
METRICS = Param("metrics", str, "results/metrics.json", None, "the metrics file, inside the unit a decision names")
MAX_FALSE_ALARM = Param("max_false_alarm", float, 0.1, "lower", "the largest share of noise a gate may say yes to")
MIN_POWER = Param("min_power", float, 0.8, "higher", "the smallest share of planted effects a gate must say yes to")


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _gate(ctx: Context, name: str) -> Callable[..., Any] | None:
    """The gate function of that name, from the first loaded pack that has one."""
    return next((loaded.gates[name] for loaded in ctx.manifest.packs if name in loaded.gates), None)


def _metrics(ctx: Context, record: Record) -> dict[str, Any] | None:
    """The metrics of the work a decision names, or None after a refusal that says why not.

    A decision about something that is not one folder of work, such as a comparison of two
    series, names the file the gate read in its own `inputs` field.
    """
    stated = record.get("inputs")
    path = str(stated).strip("/") if stated else f"{str(record.get('work')).strip('/')}/{ctx.param('metrics')}"
    if not (ctx.root / path).resolve().is_relative_to(ctx.root.resolve()):
        ctx.refuse("this decision's work points outside the repository", where=record.path,
                   fix="name the unit's folder, inside the repository, as the decision's work")
        return None
    text = ctx.read(path)
    if text is None:
        ctx.refuse(f"the metrics file {path} is missing or cannot be read", where=record.path,
                   fix="run the work so it writes its metrics, then issue the decision again")
        return None
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        ctx.refuse(f"the metrics file {path} is not a JSON object", where=path,
                   fix="run the work again so it writes its metrics as one JSON object")
        return None
    return data


# -- decision/issued-by-gate --------------------------------------------------------------------


@rule(
    "decision/issued-by-gate",
    "The stored decision equals what the gate returns on the work's records.",
    params=(METRICS,),
    learned="A decision was typed by hand after the numbers were seen, and it was kinder than the gate.",
)
def issued_by_gate(ctx: Context) -> None:
    for record in ctx.records("decision"):
        ctx.inspect()
        if record.get("by") == "owner":
            if not _text(record.get("reason")):
                ctx.breach("the owner overruled the gate and gave no reason", where=record.path,
                           fix="add a reason: one line on why the owner overruled the gate")
            continue  # the owner's overrule is the owner's own word; it is not compared with the gate
        name = record.get("gate")
        metrics = _metrics(ctx, record)
        if metrics is None:
            continue
        gate = _gate(ctx, name)
        if gate is None:
            ctx.refuse(f"no loaded pack has a gate named {name}", where=record.path,
                       fix="turn on the pack that supplies this gate, under [project] in themis.toml")
            continue
        try:
            answer = gate(metrics)
        except Exception as error:  # noqa: BLE001 - a gate that crashes has decided nothing
            ctx.refuse(f"the gate {name} failed on this work's metrics: {error.__class__.__name__}: {error}",
                       where=record.path, fix="correct the metrics file or the gate, then issue the decision again")
            continue
        if not isinstance(answer, dict) or not _text(answer.get("decision")) or answer.get("verdict") not in VERDICTS:
            ctx.refuse(f"the gate {name} did not return a decision and a verdict of pass, fail or refuse",
                       where=record.path, fix="a gate returns a table with decision and verdict; correct the gate")
            continue
        stored, issued = (record.get("decision"), record.get("verdict")), (answer["decision"], answer["verdict"])
        if stored != issued:
            ctx.breach(f"the stored decision is {stored[0]!r} with the verdict {stored[1]!r}, but the gate {name} "
                       f"returns {issued[0]!r} with the verdict {issued[1]!r}", where=record.path,
                       fix="issue the decision again from the gate; a decision is never typed by hand")


GATE_PACK = """
    from themis.pack import Pack


    def threshold(metrics):
        if metrics["samples"] < 30:
            return {"decision": "defer", "verdict": "refuse"}
        if metrics["uplift"] >= 0.05:
            return {"decision": "keep", "verdict": "pass"}
        return {"decision": "retire", "verdict": "fail"}


    pack = Pack(name="demo", gates={
        "threshold": threshold, "broken": lambda metrics: {"decision": "keep", "verdict": "keep"},
    })
"""
NO_PACK = '[project]\nname = "world"\n'
WITH_PACK = NO_PACK + 'local_pack = "pack"\n'


def _decision(world: World, name: str = "a", **changes: Any) -> None:
    fields = {"work": "work/a", "decision": "keep", "verdict": "pass", "gate": "threshold", "gate_version": "1",
              "decided_at": "2026-02-01T09:00:00+00:00"}
    world.write(f"decisions/{name}.json", json.dumps({**fields, **changes}))


def _measured(world: World, manifest: str = WITH_PACK, **metrics: Any) -> None:
    """A world with the demo gate and the metrics of work/a: a clear effect unless told otherwise."""
    world.write("pack/__init__.py", GATE_PACK)
    world.manifest(manifest)
    world.write("work/a/results/metrics.json", json.dumps({"samples": 200, "uplift": 0.08, **metrics}))


@proof("decision/issued-by-gate", "the stored decision is the gate's answer", expect="pass")
def _(world: World) -> None:
    _measured(world)
    _decision(world)


@proof("decision/issued-by-gate", "a stored refusal, where the gate defers on too little evidence", expect="pass")
def _(world: World) -> None:
    _measured(world, samples=12)
    _decision(world, decision="defer", verdict="refuse")


@proof("decision/issued-by-gate", "the owner's overrule, with its reason, is not compared", expect="pass")
def _(world: World) -> None:
    _measured(world, uplift=0.01)
    _decision(world, by="owner", reason="kept for one more month while a second source is found")


@proof("decision/issued-by-gate", "a project's own metrics file is the one read", expect="pass")
def _(world: World) -> None:
    _measured(world, WITH_PACK + '[rules."decision/issued-by-gate"]\nmetrics = "out/numbers.json"\n')
    world.move("work/a/results/metrics.json", "work/a/out/numbers.json")
    _decision(world)


@proof("decision/issued-by-gate", "a kinder decision typed by hand", expect="fail",
       contains="is 'keep' with the verdict 'pass', but the gate threshold returns 'retire' with the verdict 'fail'")
def _(world: World) -> None:
    _measured(world, uplift=0.01)
    _decision(world)


@proof("decision/issued-by-gate", "the gate's word kept, with the verdict changed", expect="fail",
       contains="is 'retire' with the verdict 'pass', but the gate threshold returns 'retire' with the verdict 'fail'")
def _(world: World) -> None:
    _measured(world, uplift=0.01)
    _decision(world, decision="retire")


@proof("decision/issued-by-gate", "a stronger word typed over the gate's, with the verdict kept", expect="fail",
       contains="is 'lead' with the verdict 'pass', but the gate threshold returns 'keep' with the verdict 'pass'")
def _(world: World) -> None:
    _measured(world)
    _decision(world, decision="lead")


@proof("decision/issued-by-gate", "a no typed by hand where the gate defers", expect="fail",
       contains="but the gate threshold returns 'defer' with the verdict 'refuse'")
def _(world: World) -> None:
    _measured(world, samples=12)
    _decision(world, decision="retire", verdict="fail")


@proof("decision/issued-by-gate", "an overrule with no reason", expect="fail", contains="gave no reason")
def _(world: World) -> None:
    _measured(world, uplift=0.01)
    _decision(world, by="owner")


@proof("decision/issued-by-gate", "another name in the by field is no overrule", expect="fail",
       contains="but the gate threshold returns 'retire'")
def _(world: World) -> None:
    _measured(world, uplift=0.01)
    _decision(world, by="writer", reason="it looked good enough")


@proof("decision/issued-by-gate", "the work's metrics file is missing", expect="refuse",
       contains="work/a/results/metrics.json is missing")
def _(world: World) -> None:
    _measured(world)
    world.remove("work/a/results/metrics.json")
    _decision(world)


@proof("decision/issued-by-gate", "a metrics file that is not JSON", expect="refuse", contains="is not a JSON object")
def _(world: World) -> None:
    _measured(world)
    world.write("work/a/results/metrics.json", "samples: 200\n")
    _decision(world)


@proof("decision/issued-by-gate", "a decision whose work points outside the repository", expect="refuse",
       contains="points outside the repository")
def _(world: World) -> None:
    _measured(world)
    _decision(world, work="../elsewhere")


@proof("decision/issued-by-gate", "no loaded pack has the gate", expect="refuse",
       contains="no loaded pack has a gate named threshold")
def _(world: World) -> None:
    _measured(world, NO_PACK)
    _decision(world)


@proof("decision/issued-by-gate", "a gate that raises on the metrics", expect="refuse",
       contains="the gate threshold failed on this work's metrics: KeyError")
def _(world: World) -> None:
    _measured(world)
    world.write("work/a/results/metrics.json", json.dumps({"samples": 200}))
    _decision(world)


@proof("decision/issued-by-gate", "a gate whose verdict is not one of the three", expect="refuse",
       contains="the gate broken did not return a decision and a verdict")
def _(world: World) -> None:
    _measured(world)
    _decision(world, gate="broken")


# -- decision/enough-evidence -------------------------------------------------------------------


@rule(
    "decision/enough-evidence",
    "A negative decision states that the evidence was enough, and is otherwise recorded as a refusal.",
    learned="An idea was written off as failed after a test too small to show anything either way.",
)
def enough_evidence(ctx: Context) -> None:
    for record in ctx.records("decision"):
        ctx.inspect()
        enough = record.get("enough_evidence")
        if record.get("verdict") != "fail" or enough is True:
            continue
        said = "says the evidence was not enough" if enough is False else "does not state that the evidence was enough"
        ctx.breach(f"this negative decision {said}", where=record.path,
                   fix='a negative result on too little evidence is recorded as "refuse" (defer), not "fail"; '
                       "when the evidence was enough, the gate sets enough_evidence to true")


@proof("decision/enough-evidence", "a no that states the evidence was enough", expect="pass")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world, decision="retire", verdict="fail", enough_evidence=True)


@proof("decision/enough-evidence", "a yes needs no statement", expect="pass")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world)


@proof("decision/enough-evidence", "too little evidence, recorded as a refusal", expect="pass")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world, decision="defer", verdict="refuse", enough_evidence=False)


@proof("decision/enough-evidence", "a no that says nothing about its evidence", expect="fail",
       contains="does not state that the evidence was enough")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world, decision="retire", verdict="fail")


@proof("decision/enough-evidence", "a no on evidence that was not enough", expect="fail",
       contains="says the evidence was not enough")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world, decision="retire", verdict="fail", enough_evidence=False)


@proof("decision/enough-evidence", "one honest no does not cover another", expect="fail",
       contains="does not state that the evidence was enough")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world, decision="retire", verdict="fail", enough_evidence=True)
    _decision(world, "b", work="work/b", decision="retire", verdict="fail")


@proof("decision/enough-evidence", "a statement that is not true or false", expect="refuse",
       contains="enough_evidence must be true or false")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world, decision="retire", verdict="fail", enough_evidence="yes")


@proof("decision/enough-evidence", "a decision record that cannot be read", expect="refuse",
       contains="is not valid JSON")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    world.write("decisions/a.json", '{"work": "work/a", "verdict": "fail"\n')


# -- decision/calibrated ------------------------------------------------------------------------


def _rate(value: Any) -> bool:
    """True for a number from 0 to 1. True, false and a value that is not a number are not rates."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


@rule(
    "decision/calibrated",
    "The gate holds a receipt showing it says no to noise and yes to a planted effect.",
    params=(MAX_FALSE_ALARM, MIN_POWER),
    learned="A gate that had never been shown plain noise said yes to it.",
)
def calibrated(ctx: Context) -> None:
    used: dict[tuple[str, str], str] = {}  # each gate and version in use, with the first decision that used it
    for record in ctx.records("decision"):
        used.setdefault((record.get("gate"), record.get("gate_version")), record.path)
    held = receipts.read_all(ctx.root, "calibration")
    most, least = ctx.param("max_false_alarm"), ctx.param("min_power")
    again = "correct the gate, run `themis calibrate` again, and issue the gate's decisions again"
    for (gate, version), first in sorted(used.items()):
        ctx.inspect()
        which = f"the gate {gate}, version {version},"
        found = [receipt for receipt in held
                 if receipt.get("gate") == gate and str(receipt.get("gate_version")) == version]
        if not found:
            ctx.breach(f"{which} holds no calibration receipt", where=first,
                       fix="run `themis calibrate` on this version of the gate, and commit the receipt it writes")
        for receipt in found:
            false_alarm, power = receipt.get("false_alarm_rate"), receipt.get("power")
            if not _rate(false_alarm) or not _rate(power):
                ctx.refuse("this calibration receipt does not state a false-alarm rate and a power from 0 to 1",
                           where=receipt["_path"], fix="run `themis calibrate` again; a tool writes a receipt")
                continue
            if false_alarm > most:
                ctx.breach(f"{which} said yes to noise too often: a false-alarm rate of {false_alarm:g}, "
                           f"and the most allowed is {most:g}", where=receipt["_path"], fix=again)
            if power < least:
                ctx.breach(f"{which} missed a planted effect too often: a power of {power:g}, "
                           f"and the least allowed is {least:g}", where=receipt["_path"], fix=again)


def _receipt(world: World, name: str = "threshold", **changes: Any) -> None:
    fields = {"kind": "calibration", "gate": "threshold", "gate_version": "1", "false_alarm_rate": 0.04, "power": 0.9}
    world.write(f"receipts/calibration/{name}.json", json.dumps({**fields, **changes}))


@proof("decision/calibrated", "a receipt inside both limits", expect="pass")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world)
    _receipt(world)


@proof("decision/calibrated", "rates that sit exactly on the limits", expect="pass")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world)
    _receipt(world, false_alarm_rate=0.1, power=0.8)


@proof("decision/calibrated", "a gate with no receipt at all", expect="fail",
       contains="the gate threshold, version 1, holds no calibration receipt")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world)


@proof("decision/calibrated", "a receipt for an older version of the gate does not count", expect="fail",
       contains="the gate threshold, version 2, holds no calibration receipt")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world, gate_version="2")
    _receipt(world)


@proof("decision/calibrated", "a receipt for another gate does not count", expect="fail",
       contains="the gate checklist, version 1, holds no calibration receipt")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world)
    _decision(world, "b", work="work/b", gate="checklist")
    _receipt(world)


@proof("decision/calibrated", "a gate that says yes to noise", expect="fail", contains="said yes to noise too often")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world)
    _receipt(world, false_alarm_rate=0.3)


@proof("decision/calibrated", "a gate that misses a planted effect", expect="fail",
       contains="missed a planted effect too often")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world)
    _receipt(world, power=0.5)


@proof("decision/calibrated", "a project's tighter limit is the one used", expect="fail",
       contains="a false-alarm rate of 0.04, and the most allowed is 0.01")
def _(world: World) -> None:
    world.manifest(NO_PACK + '[rules."decision/calibrated"]\nmax_false_alarm = 0.01\n')
    _decision(world)
    _receipt(world)


@proof("decision/calibrated", "a receipt with no power", expect="refuse", contains="does not state a false-alarm rate")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world)
    _receipt(world, power=None)


@proof("decision/calibrated", "a rate written as a percentage", expect="refuse", contains="a power from 0 to 1")
def _(world: World) -> None:
    world.manifest(NO_PACK)
    _decision(world)
    _receipt(world, power=90)
