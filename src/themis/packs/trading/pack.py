"""The trading pack's own object: its table in the manifest, and what it sets for the core rules.

Every module of this pack imports `pack` from here and adds to it. Nothing here names an
instrument, a venue, an engine or a project: those are a project's parameters.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from themis.pack import Key, Pack, Standard, register
from themis.packs.trading import data, units
from themis.schema import ANY, Either, Required

SEAL, RESULTS = units.SEAL, units.RESULTS
#: What a study's report page is built from, inside the study. The page carries their digest.
REPORT_INPUTS = [units.TRADES, units.METRICS, units.AUDIT]
HOLDOUT = "holdout"  # the guarded action: one look at a sealed data window

pack = register(Pack(
    name="trading",
    schema={
        "work": Either(str, [str]),  # the folders that each hold one study: one glob, or a list of them
        "windows": {"*": data.WINDOW},
        "studies": {"*": {"windows": {"*": data.WINDOW}}},  # a study's own windows, keyed by its folder
        "costs": {"*": {"derivation": Required(str), "*": ANY}},
        "tune": {"risk_rules": str, "iterations": int, "confirm_model": str},
    },
    # Which way each key tightens, so a change to [trading] is classified. A key named nowhere here
    # (a window's dates, a cost model's figures) is a weakening when it is added or changed.
    keys={
        "work": Key("larger"),  # another study folder is another study checked
        "windows": Key("larger"),  # a new window adds a check, whatever it holds
        "windows.*.sealed": Key("higher", False),
        "windows.*.looks": Key("lower", 1),
        "studies": Key("larger"),
        "studies.*.windows": Key("larger"),
        "studies.*.windows.*.sealed": Key("higher", False),
        "studies.*.windows.*.looks": Key("lower", 1),
        "tune.confirm_model": Key(),  # first set turns validity/confirm-on-real-ticks on
        "tune.risk_rules": Key(),
        "tune.iterations": Key("lower"),  # a budget
    },
    kinds={
        "strategy": "books trades: the strategy scorecard, the report, an audit",
        "signal": "predicts and books no trades: the signal scorecard, the report, an audit",
        "data": "describes and selects nothing: charts with how-to-read boxes; costs no trial",
        "tune": "searches a strategy's settings: a sealed search, every setting a trial, one look at unseen data",
        "forward": "trades live under sealed settings, beside a replay of the same dates: a record and a decision a week",
    },
))


_SEALED: list[tuple[Any, bool]] = []  # the last few manifests asked about, and whether they seal a window


def _seals_a_window(manifest: Any) -> bool:
    """True when any window is sealed: the project's, a study table's or one a study's seal declares.

    The seals are read from the disk, so the answer is kept for the last few manifests asked about:
    the core asks once for every rule of a run.
    """
    for held, answer in _SEALED:
        if held is manifest:
            return answer
    table, root = manifest.table("trading"), Path(manifest.root)
    found = [path.relative_to(root).as_posix() for pattern in data.studies_patterns(table.get("work"))
             for seal in SEAL for path in root.glob(f"{pattern.strip('/')}/{seal}") if path.is_file()]
    answer = bool(data.collect(manifest, found, data.reader(root)).sealed())
    _SEALED[:] = [(manifest, answer), *_SEALED[:7]]
    return answer


def _defaults(manifest: Any) -> dict[str, dict[str, Any]]:
    """What the core's rules mean in trading: the pre-registration is the seal, everything under
    results/ is a result, the report page is built and never typed, and a look at a sealed window
    is an action that needs the owner's grant. A project that states its own guarded list replaces
    this one, so it keeps `holdout` in it."""
    table = manifest.table("trading")
    found: dict[str, dict[str, Any]] = {"grant/required": {"guarded": [HOLDOUT]}} if _seals_a_window(manifest) else {}
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
pack.actions[HOLDOUT] = data.act  # `themis act holdout <study>/<window>` writes the look the holdout rules count

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
