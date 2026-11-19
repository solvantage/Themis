"""The trading pack's own object: its table in the manifest, and what it sets for the core rules.

Every module of this pack imports `pack` from here and adds to it. Nothing here names an
instrument, a venue, an engine or a project: those are a project's parameters.
"""

from __future__ import annotations

from typing import Any

from themis.pack import Pack, Standard, register
from themis.packs.trading import units
from themis.schema import ANY, Required

SEAL, RESULTS = units.SEAL, units.RESULTS
#: What a study's report page is built from, inside the study. The page carries their digest.
REPORT_INPUTS = [units.TRADES, units.METRICS, units.AUDIT]
HOLDOUT = "holdout"  # the guarded action: one look at a sealed data window

pack = register(Pack(
    name="trading",
    schema={
        "work": str,  # the folders that each hold one study, such as research/experiments/*
        "windows": {"*": {"from": Required(str), "to": Required(str), "sealed": bool, "looks": int}},
        "costs": {"*": {"derivation": Required(str), "*": ANY}},
        "tune": {"risk_rules": str, "iterations": int, "confirm_model": str},
    },
    kinds={
        "strategy": "books trades: the strategy scorecard, the report, an audit",
        "signal": "predicts and books no trades: the signal scorecard, the report, an audit",
        "data": "describes and selects nothing: charts with how-to-read boxes; costs no trial",
        "tune": "searches a strategy's settings: a sealed search, every setting a trial, one look at unseen data",
    },
))


def _defaults(manifest: Any) -> dict[str, dict[str, Any]]:
    """What the core's rules mean in trading: the pre-registration is the seal, everything under
    results/ is a result, the report page is built and never typed, and a look at a sealed window
    is an action that needs the owner's grant."""
    table = manifest.table("trading")
    windows = table.get("windows", {})
    sealed = isinstance(windows, dict) and any(isinstance(window, dict) and window.get("sealed") is True
                                               for window in windows.values())
    found: dict[str, dict[str, Any]] = {"grant/required": {"guarded": [HOLDOUT]}} if sealed else {}
    work = table.get("work")
    if work:
        found.update({
            "order/sealed-first": {"work": work, "seal": SEAL, "results": RESULTS},
            "order/logged-first": {"work": work, "results": RESULTS},
            "order/unchanged": {"work": work, "seal": SEAL},
            "ledger/complete": {"work": work, "results": RESULTS},
            "report/generated": {"work": work, "report": [units.REPORT], "inputs": REPORT_INPUTS},
            "report/readable": {"work": work, "report": [units.REPORT]},
        })
    return found


pack.defaults = _defaults

#: The floor a project holds when it declares this standard. It may tighten anything. The rules
#: named here keep a result from being chosen after the fact, counted short, shown unseen data
#: twice, booked at prices that never traded, decided by hand, or shipped trading live.
pack.standards["themis-trading/1"] = Standard(
    "themis-trading/1",
    levels={rule_id: "enforce" for rule_id in (
        "config/locked", "config/no-silent-weakening",
        "order/sealed-first", "order/logged-first", "order/unchanged", "ledger/complete",
        "prereg/declared", "prereg/provenance",
        "trials/settings-counted", "trials/count-feeds-adjustment",
        "holdout/guarded", "holdout/one-signal-look", "holdout/pipeline-look-declared",
        "validity/fills-on-tape", "validity/net-of-cost", "validity/baselines", "validity/power-stated",
        "validity/audit-reproduced", "validity/same-basis", "live/off-by-default",
        "decision/issued-by-gate", "decision/enough-evidence", "decision/calibrated",
        "scorecard/complete", "scorecard/believable", "report/generated",
    )},
    floors={
        "decision/calibrated": {"max_false_alarm": 0.1, "min_power": 0.8},
        "validity/power-stated": {"min_power": 0.8},
        "trials/count-feeds-adjustment": {"penalty": 0},
        "live/off-by-default": {"absent": "refuse"},
    },
)
