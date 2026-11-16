"""Gate: grant — the owner's yes is a file.

An action that cannot be taken back runs only with a grant: a small record the owner makes with a
command. The guarded code leaves an action receipt that names the grant it used. These rules
compare the receipts with the grants, so there is no value an agent can type to open the action.
"""

from __future__ import annotations

import json
import math
from typing import Any

from themis import receipts
from themis.grants import to_toml
from themis.rule import Context, Param, proof, rule

GUARDED = Param("guarded", [str], None, "larger", "the actions that cannot be taken back, such as publish")
SPENDING = Param("spending", [str], None, "larger", "the guarded actions that spend, each needing a ceiling")
RESTORE = "restore the receipt from git; a receipt is written by a tool, never by hand"
PLAIN = """
    [project]
    name = "world"
"""


def _actions(ctx: Context) -> list[dict[str, Any]]:
    """Every action receipt that can be read. One that cannot is a refusal, never a silent skip."""
    found = receipts.read_all(ctx.root, "action")
    kept = {path.relative_to(ctx.root).as_posix() for base in (receipts.LOCAL, receipts.COMMITTED)
            for path in (ctx.root / base / "action").glob("*.json")}
    for name in sorted(kept - {receipt["_path"] for receipt in found}):
        ctx.refuse("this action receipt cannot be read", where=name, fix=RESTORE)
    good: dict[str, dict[str, Any]] = {}
    for receipt in found:
        if not isinstance(receipt.get("action"), str) or not isinstance(receipt.get("target"), str):
            ctx.refuse("this action receipt does not name its action and its target", where=receipt["_path"],
                       fix=RESTORE)
            continue
        # A receipt copied from the local folder to the committed one is the same action, once.
        body = {key: value for key, value in receipt.items() if key != "_path"}
        good[receipt["_path"].rsplit("/", 1)[-1] + json.dumps(body, sort_keys=True)] = receipt
    return list(good.values())


def _grant_named(receipt: dict[str, Any]) -> str | None:
    name = receipt.get("grant")
    return name.strip() if isinstance(name, str) and name.strip() else None


def _number(value: Any) -> float | None:
    """The value as a number, or None when it is not one that can be compared."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _plain(number: float) -> str:
    return str(int(number)) if number.is_integer() else str(number)


def _grant(world, name: str = "g1", **fields: Any) -> None:
    data = {"action": "publish", "target": "episode-12", "granted_by": "owner",
            "granted_at": "2026-01-01T09:00:00+00:00", "reason": "the final cut was reviewed", **fields}
    world.write(f"grants/{name}.toml", to_toml(data))


def _action(world, name: str = "a1", folder: str = "receipts", **fields: Any) -> None:
    data = {"kind": "action", "action": "publish", "target": "episode-12", "at": "2026-01-01T10:00:00+00:00",
            "grant": "g1", **fields}
    held = {key: value for key, value in data.items() if value is not None}
    world.write(f"{folder}/action/{name}.json", json.dumps(held))


# -- grant/required -----------------------------------------------------------------------------


@rule(
    "grant/required",
    "An action declared irreversible runs only with a grant that names it and its target.",
    params=(GUARDED,),
    requires=("guarded",),
    learned="A flag typed in code opened an action that could not be taken back, and nobody had asked the owner.",
)
def required(ctx: Context) -> None:
    grants = {record.id: record for record in ctx.records("grant")}
    guarded = set(ctx.param("guarded"))
    for receipt in _actions(ctx):
        action, target, where = receipt["action"], receipt["target"], receipt["_path"]
        if action not in guarded:
            continue
        ctx.inspect()
        name = _grant_named(receipt)
        fix = f"the owner runs `themis grant {action} {target}` before the action runs; tell the owner about this run"
        if name is None:
            ctx.breach(f"the guarded action {action} ran on {target} with no grant", where=where, fix=fix)
        elif name not in grants:
            ctx.breach(f"the action {action} names the grant {name}, and no such grant is on file", where=where,
                       fix=fix)
        elif grants[name].get("action") != action:
            ctx.breach(f"the grant {name} is for the action {grants[name].get('action')}, and {action} ran",
                       where=where, fix=fix)
        elif grants[name].get("target") != target:
            ctx.breach(f"the grant {name} is for the target {grants[name].get('target')}, and the action ran on "
                       f"{target}", where=where, fix=fix)


REQUIRED = """
    [rules."grant/required"]
    guarded = ["publish", "spend"]
"""


@proof("grant/required", "a guarded action with a grant for it and its target", expect="pass")
def _(world):
    world.manifest(REQUIRED)
    _grant(world)
    _action(world)


@proof("grant/required", "an action that is not guarded needs no grant", expect="pass")
def _(world):
    world.manifest(REQUIRED)
    _grant(world)
    _action(world)
    _action(world, "a2", action="render", grant=None)


@proof("grant/required", "a guarded action with no grant", expect="fail", contains="with no grant")
def _(world):
    world.manifest(REQUIRED)
    _grant(world)
    _action(world, grant=None)


@proof("grant/required", "a receipt that names a grant nobody wrote", expect="fail",
       contains="no such grant is on file")
def _(world):
    world.manifest(REQUIRED)
    _grant(world)
    _action(world, grant="g2")


@proof("grant/required", "a grant for another action does not open this one", expect="fail",
       contains="is for the action publish")
def _(world):
    world.manifest(REQUIRED)
    _grant(world)
    _action(world, action="spend")


@proof("grant/required", "a grant for another target does not open this one", expect="fail",
       contains="is for the target episode-12")
def _(world):
    world.manifest(REQUIRED)
    _grant(world)
    _action(world, target="episode-13")


@proof("grant/required", "an action receipt that cannot be read", expect="refuse", contains="cannot be read")
def _(world):
    world.manifest(REQUIRED)
    _grant(world)
    _action(world)
    world.write("receipts/action/a2.json", '{"action": "publish", "target": ')


@proof("grant/required", "a receipt that does not say what the action ran on", expect="refuse",
       contains="does not name its action and its target")
def _(world):
    world.manifest(REQUIRED)
    _grant(world)
    _action(world, target=None)


@proof("grant/required", "no guarded action has run yet", expect="refuse", contains="nothing was inspected")
def _(world):
    world.manifest(REQUIRED)
    _grant(world)
    _action(world, action="render", grant=None)


# -- grant/single-use ---------------------------------------------------------------------------


@rule(
    "grant/single-use",
    "A grant is spent by one action and cannot be used again.",
    learned="One yes from the owner was used again for later actions the owner never saw.",
)
def single_use(ctx: Context) -> None:
    used: dict[str, list[dict[str, Any]]] = {}
    for receipt in _actions(ctx):
        name = _grant_named(receipt)
        if name:
            used.setdefault(name, []).append(receipt)
    for name in sorted({record.id for record in ctx.records("grant")} | set(used)):
        ctx.inspect()
        uses = sorted(used.get(name, []), key=lambda receipt: (str(receipt.get("at", "")), receipt["_path"]))
        for extra in uses[1:]:
            ctx.breach(f"the grant {name} was already spent by {uses[0]['_path']}, and this action used it again",
                       where=extra["_path"],
                       fix=f"the owner runs `themis grant {extra['action']} {extra['target']}` for each further action")


@proof("grant/single-use", "two actions, each with its own grant", expect="pass")
def _(world):
    world.manifest(PLAIN)
    _grant(world, "g1")
    _grant(world, "g2", target="episode-13")
    _action(world, "a1", grant="g1")
    _action(world, "a2", grant="g2", target="episode-13")


@proof("grant/single-use", "a grant that no action has used yet", expect="pass")
def _(world):
    world.manifest(PLAIN)
    _grant(world)


@proof("grant/single-use", "a local receipt and its committed copy are one action", expect="pass")
def _(world):
    world.manifest(PLAIN)
    _grant(world)
    _action(world, "a1", folder=".themis/receipts")
    _action(world, "a1", folder="receipts")


@proof("grant/single-use", "one grant used by two actions", expect="fail", contains="was already spent")
def _(world):
    world.manifest(PLAIN)
    _grant(world)
    _action(world, "a1")
    _action(world, "a2", at="2026-01-02T10:00:00+00:00")


@proof("grant/single-use", "one grant used again for another target", expect="fail",
       contains="was already spent by receipts/action/a1.json")
def _(world):
    world.manifest(PLAIN)
    _grant(world)
    _action(world, "a1")
    _action(world, "a2", target="episode-13", at="2026-01-02T10:00:00+00:00")


@proof("grant/single-use", "an action receipt that cannot be read", expect="refuse", contains="cannot be read")
def _(world):
    world.manifest(PLAIN)
    _grant(world)
    world.write("receipts/action/a1.json", "not json\n")


@proof("grant/single-use", "no grant and no action yet", expect="refuse", contains="nothing was inspected")
def _(world):
    world.manifest(PLAIN)


# -- grant/ceiling ------------------------------------------------------------------------------


@rule(
    "grant/ceiling",
    "An action that spends stays under the ceiling its grant names.",
    params=(SPENDING,),
    requires=("spending",),
    learned="A yes to spend named no limit, and the bill was far larger than the owner expected.",
)
def under_ceiling(ctx: Context) -> None:
    grants = {record.id: record for record in ctx.records("grant")}
    spending = set(ctx.param("spending"))
    for receipt in _actions(ctx):
        name, where = _grant_named(receipt), receipt["_path"]
        if receipt["action"] not in spending or name is None:
            continue  # an action that names no grant at all is for grant/required to report
        ctx.inspect()
        if name not in grants:
            ctx.refuse(f"the grant {name} is not on file, so its ceiling cannot be read", where=where,
                       fix="restore the grant record from git")
            continue
        grant = grants[name]
        limit, amount = _number(grant.get("ceiling")), _number(receipt.get("amount"))
        mine, theirs = receipt.get("unit") or "no unit", grant.get("unit") or "no unit"
        if limit is None:
            ctx.breach(f"the grant {name} names no ceiling, and the action it opened spends", where=grant.path,
                       fix="the owner grants again, this time with a ceiling and its unit")
        elif amount is None:
            ctx.breach("this action spends, and its receipt names no amount as a number", where=where,
                       fix="the guarded code records the amount it spent in the receipt")
        elif mine != theirs:
            ctx.breach(f"the amount is counted in {mine}, and the ceiling in {theirs}", where=where,
                       fix="record the amount in the unit the grant names")
        elif amount > limit:
            ctx.breach(f"the action spent {_plain(amount)} {mine}, above the ceiling of {_plain(limit)}",
                       where=where, fix="stop spending; the owner grants a higher ceiling before any more is spent")


CEILING = """
    [rules."grant/ceiling"]
    spending = ["spend"]
"""


def _spend(world, amount: Any = 40, ceiling: Any = 50, unit: Any = "credits", grant_unit: Any = "credits") -> None:
    world.manifest(CEILING)
    fields = {"ceiling": ceiling, "unit": grant_unit}
    _grant(world, action="spend", target="ads", **{key: value for key, value in fields.items() if value is not None})
    _action(world, action="spend", target="ads", amount=amount, unit=unit)


@proof("grant/ceiling", "a spend under its ceiling", expect="pass")
def _(world):
    _spend(world)


@proof("grant/ceiling", "a spend of exactly the ceiling", expect="pass")
def _(world):
    _spend(world, amount=50)


@proof("grant/ceiling", "an action that does not spend needs no ceiling", expect="pass")
def _(world):
    _spend(world)
    _grant(world, "g2")
    _action(world, "a2", grant="g2")


@proof("grant/ceiling", "a spend above its ceiling", expect="fail",
       contains="spent 60 credits, above the ceiling of 50")
def _(world):
    _spend(world, amount=60)


@proof("grant/ceiling", "a grant to spend that names no ceiling", expect="fail", contains="names no ceiling")
def _(world):
    _spend(world, ceiling=None)


@proof("grant/ceiling", "a receipt that does not say how much was spent", expect="fail",
       contains="names no amount as a number")
def _(world):
    _spend(world, amount="a little")


@proof("grant/ceiling", "an amount in another unit than the ceiling", expect="fail",
       contains="counted in dollars, and the ceiling in credits")
def _(world):
    _spend(world, unit="dollars")


@proof("grant/ceiling", "an amount with no unit under a ceiling that has one", expect="fail",
       contains="counted in no unit")
def _(world):
    _spend(world, unit=None)


@proof("grant/ceiling", "a spend that names a grant nobody wrote", expect="refuse",
       contains="its ceiling cannot be read")
def _(world):
    _spend(world)
    _action(world, "a2", action="spend", target="ads", amount=10, unit="credits", grant="g9")


@proof("grant/ceiling", "a spend with no grant is left to grant/required", expect="refuse",
       contains="nothing was inspected")
def _(world):
    world.manifest(CEILING)
    _action(world, action="spend", target="ads", amount=10, unit="credits", grant=None)
