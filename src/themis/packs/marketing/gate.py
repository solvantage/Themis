"""The results gate: which series leads, is kept or is retired. The numbers decide, never the agent.

The gate is called with one table of metrics:

    series                each series' name, with its items: {"goal": n, "second": n, "views": n}
    subject               the series being decided
    rival                 optional: the series it is compared with
    baseline_views        the account's own median views
    baseline              optional: the name of that baseline, copied into the answer's numbers
    min_items_to_judge    default 3: below this the decision is "too-few"
    min_items_to_rank     default 6: both series need this many items to lead or to retire
    retire_views_share    default 0.7: a retired series' median views are under this share of the baseline
    standout_views_times  default 5: one item with this many times the baseline's views is a standout
    noise_band            default true: a lead or a retire must be larger than the noise

`goal` is the goal number of the series' purpose and `second` is the project's second number. The
gate answers with a decision, a verdict, whether the evidence was enough, a reason in plain words,
and the numbers behind it, the thresholds it used among them. The decisions, in the order they are
tried:

    unreadable  refuse  an input is missing or malformed
    too-few     refuse  the subject has too few items with results to say anything
    standout    pass    one item of the subject is far above the baseline
    lead        pass    enough items in both series, and the subject is higher on the goal number
    retire      fail    enough items, lower on both numbers, and median views under the retire line
    keep        pass    everything else: lower on the goal number and higher on the second, a
                        difference inside the noise, no rival, or too few items to rank

The noise band is a permutation test. The two series' goal numbers are pooled and dealt out again
at random, 500 times, with a fixed seed. A lead or a retire is issued only when at most 5% of those
deals show a difference in the mean at least as large as the real one. Otherwise the series is kept.
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Any

from themis.packs.marketing.pack import pack

DEFAULTS: dict[str, Any] = {
    "min_items_to_judge": 3, "min_items_to_rank": 6, "retire_views_share": 0.7, "standout_views_times": 5,
    "noise_band": True,
}
FIELDS = ("goal", "second", "views")
SHUFFLES = 500
MOST_AS_LARGE = 0.05  # the largest share of shuffles that may match the real difference
SEED = 20261116
DRAWS, ITEMS, LIFT = 500, 8, 2.0  # the calibration: draws a case, items a series, the planted lift in deviations


def _number(value: Any) -> bool:
    """True for a finite number. True and false are not numbers."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _problem(metrics: Any) -> str | None:
    """Why the metrics cannot be read, or None when they can."""
    if not isinstance(metrics, dict):
        return "the metrics are not a table"
    series, subject, rival = metrics.get("series"), metrics.get("subject"), metrics.get("rival")
    if not isinstance(series, dict) or not all(isinstance(held, list) for held in series.values()):
        return "series must be a table of each series' name with the list of its items"
    for name, held in series.items():
        if not all(isinstance(item, dict) and all(_number(item.get(field)) for field in FIELDS) for item in held):
            return f"each item of the series {name} must hold the numbers goal, second and views"
    if not isinstance(subject, str) or subject not in series:
        return "subject must name a series in the series table"
    if rival is not None and (not isinstance(rival, str) or rival not in series or rival == subject):
        return "rival must name another series in the series table"
    for name in ("min_items_to_judge", "min_items_to_rank"):
        value = metrics.get(name, DEFAULTS[name])
        if not _number(value) or value < 1 or value != int(value):
            return f"{name} must be a whole number of at least 1"
    for name in ("retire_views_share", "standout_views_times", "baseline_views"):
        value = metrics.get(name, DEFAULTS.get(name, 1))
        if not _number(value) or value <= 0:
            return f"{name} must be a number above zero"
    if not isinstance(metrics.get("noise_band", True), bool):
        return "noise_band must be true or false"
    if not isinstance(metrics.get("baseline", ""), str):
        return "baseline must be the name of the baseline"
    return None


def _answer(decision: str, verdict: str, enough: bool, reason: str, numbers: dict[str, Any]) -> dict[str, Any]:
    return {"decision": decision, "verdict": verdict, "enough_evidence": enough, "reason": reason, "numbers": numbers}


def _mean(held: list[dict[str, Any]], field: str) -> float:
    return statistics.fmean(item[field] for item in held)


def noise_share(first: list[float], second: list[float], *, shuffles: int = SHUFFLES, seed: int = SEED) -> float:
    """The share of shuffles in which the two groups' means differ at least as much as they really do.

    The two groups' numbers are pooled and dealt out again at random, many times. A real difference
    that random dealing often matches is noise. The seed is fixed, so the same numbers always give
    the same share.
    """
    pooled, size, whole = first + second, len(first), math.fsum(first + second)

    def gap(dealt: float) -> float:
        return abs(dealt / size - (whole - dealt) / (len(pooled) - size))

    real, deal = gap(math.fsum(first)), random.Random(seed)
    as_large = sum(gap(math.fsum(deal.sample(pooled, size))) >= real * (1 - 1e-9) for _ in range(shuffles))
    return as_large / shuffles


@pack.gate("results", version="1")
def gate(metrics: dict[str, Any]) -> dict[str, Any]:
    """Decide one series from its results. The same metrics always give the same answer."""
    problem = _problem(metrics)
    if problem:
        return _answer("unreadable", "refuse", False, problem, {})
    limits = {name: metrics.get(name, default) for name, default in DEFAULTS.items()}
    subject, rival = metrics["subject"], metrics.get("rival")
    ours = metrics["series"][subject]
    numbers: dict[str, Any] = {"items": len(ours), **limits}  # the thresholds used are part of the answer
    if "baseline" in metrics:
        numbers["baseline"] = metrics["baseline"]
    if len(ours) < limits["min_items_to_judge"]:
        return _answer("too-few", "refuse", False, f"{subject} has {len(ours)} item(s) with results, and "
                       f"{limits['min_items_to_judge']} are needed to say anything", numbers)
    baseline = metrics.get("baseline_views")
    if baseline is None:
        return _answer("unreadable", "refuse", False, "baseline_views, the account's own median views, is missing",
                       numbers)
    views = [item["views"] for item in ours]
    numbers.update(baseline_views=baseline, top_views=max(views), median_views=statistics.median(views),
                   mean_goal=_mean(ours, "goal"), mean_second=_mean(ours, "second"))
    if max(views) >= limits["standout_views_times"] * baseline:
        return _answer("standout", "pass", True, f"one item of {subject} reached {max(views):g} views, at least "
                       f"{limits['standout_views_times']:g} times the baseline of {baseline:g}", numbers)
    if rival is None:
        return _answer("keep", "pass", True, f"{subject} has no series to be compared with, so it is kept", numbers)
    theirs, least = metrics["series"][rival], limits["min_items_to_rank"]
    numbers["rival_items"] = len(theirs)
    if len(ours) < least or len(theirs) < least:
        return _answer("keep", "pass", True, f"ranking needs {least} items in each series; {subject} has {len(ours)} "
                       f"and {rival} has {len(theirs)}, so {subject} is kept", numbers)
    numbers.update(rival_mean_goal=_mean(theirs, "goal"), rival_mean_second=_mean(theirs, "second"))
    goal = numbers["mean_goal"] - numbers["rival_mean_goal"]
    second = numbers["mean_second"] - numbers["rival_mean_second"]
    line = limits["retire_views_share"]
    if goal > 0:
        decision, reason = "lead", f"{subject} is higher than {rival} on the goal number"
    elif goal < 0 and second < 0 and numbers["median_views"] < line * baseline:
        decision, reason = "retire", (f"{subject} is lower than {rival} on the goal number and on the second number, "
                                      f"and its median views are under {line:g} of the baseline")
    elif goal < 0 and second > 0:
        return _answer("keep", "pass", True, f"{subject} is lower than {rival} on the goal number and higher on the "
                       "second number, so it is kept", numbers)
    else:
        return _answer("keep", "pass", True, f"{subject} is neither higher than {rival} on the goal number, nor lower "
                       "on both numbers with weak views, so it is kept", numbers)
    if limits["noise_band"]:
        share = noise_share([item["goal"] for item in ours], [item["goal"] for item in theirs])
        numbers.update(noise_share=share, within_noise=share > MOST_AS_LARGE)
        if share > MOST_AS_LARGE:
            return _answer("keep", "pass", True, f"the difference between {subject} and {rival} on the goal number is "
                           f"within the noise: {share:.0%} of shuffles showed one at least as large, so {subject} "
                           "is kept", numbers)
        reason += ", and the difference is larger than the noise"
    return _answer(decision, "pass" if decision == "lead" else "fail", True, reason, numbers)


# -- calibration: the gate is shown plain noise, and a planted effect ---------------------------


def _drawn(deal: random.Random, lift: float = 0.0) -> dict[str, Any]:
    """Two series drawn from one distribution, with views weak enough for a retire to be possible.
    `lift` raises the subject's goal number, in standard deviations."""

    def series(raised: float) -> list[dict[str, float]]:
        return [{"goal": deal.gauss(10 + 3 * raised, 3), "second": deal.gauss(20, 5),
                 "views": 600 * deal.lognormvariate(0, 0.3)} for _ in range(ITEMS)]

    drawn = {"new": series(lift), "old": series(0.0)}
    return {"series": drawn, "subject": "new", "rival": "old", "baseline_views": 1000}


@pack.calibration("results", "noise", "two series of eight items drawn from one distribution, both with weak views")
def noise() -> float:
    """How often the gate issued a lead or a retire when there was nothing to find."""
    deal = random.Random(1)
    return sum(gate(_drawn(deal))["decision"] in ("lead", "retire") for _ in range(DRAWS)) / DRAWS


@pack.calibration("results", "planted", "the subject's goal number raised by two standard deviations")
def planted() -> float:
    """How often the gate issued a lead when the subject's goal number really was higher."""
    deal = random.Random(2)
    return sum(gate(_drawn(deal, LIFT))["decision"] == "lead" for _ in range(DRAWS)) / DRAWS
