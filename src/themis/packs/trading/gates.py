"""The trading pack's gate functions: the numbers decide, not a person.

A gate function reads a study's metrics and returns its answer:

    gate(metrics: dict) -> {"decision", "verdict", "enough_evidence", "reason", "numbers"}

`verdict` is "pass", "fail" or "refuse". `decision` is the trading word for it: "promote", "kill"
or "defer" (the tuning gate says "full-pass", "kill" or "not-confirmed"). `enough_evidence` is
true when the evidence was enough to reach the verdict. `numbers` holds everything the gate
computed, so a reader can check the reason against them.

Every gate here obeys the same rules, in this order:

1. Missing or malformed inputs are a refusal. A gate never guesses, and never passes on a guess.
2. Too small a sample is a refusal, whatever its numbers look like.
3. Economics first. A result that does not pay after costs is a no before any significance is
   read.
4. A no from a test too weak to have seen the effect is a refusal ("defer"), not a "kill".

Each gate comes with calibration cases: data with nothing in it, which it must turn down, and data
with a known effect, which it must find. Each case returns a rate over many seeded draws.
"""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Callable
from typing import Any

from themis.packs.trading import stats
from themis.packs.trading.pack import pack

ENOUGH_POWER = 0.8  # the least power a test needs before its "no" counts as a "kill"
MIN_TRADES = 30  # the fewest trades an entry is judged on; a study may ask for more, never for fewer
MIN_CONTROL_DRAWS = 20  # fewer draws of the dumb entry cannot place a signal in the top 5%
MIN_SAMPLES = 30  # the fewest non-overlapping samples a rank correlation is read on
MIN_BLOCK = 5  # the fewest samples in one block for its sign to mean anything
MAX_ALPHA = 0.10  # no project may let a gate say yes to noise more often than this

Answer = dict[str, Any]


def _answer(decision: str, verdict: str, enough: bool, reason: str, numbers: dict[str, Any]) -> Answer:
    return {"decision": decision, "verdict": verdict, "enough_evidence": enough, "reason": reason, "numbers": numbers}


def _refuse(reason: str, numbers: dict[str, Any] | None = None) -> Answer:
    return _answer("defer", "refuse", False, reason, numbers or {})


def _no(powered: bool, reason: str, weak: str, numbers: dict[str, Any]) -> Answer:
    """A negative result: a kill when the test could have seen the effect, a deferral when not."""
    if powered:
        return _answer("kill", "fail", True, reason, numbers)
    return _answer("defer", "refuse", False, f"{reason}; but {weak}, so this is no verdict: defer", numbers)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _numbers(value: Any) -> list[float] | None:
    """The value as a list of numbers, or None when it is anything else."""
    if not isinstance(value, list) or not all(_number(item) for item in value):
        return None
    return [float(item) for item in value]


def _whole(value: Any, least: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= least


def _common(metrics: dict[str, Any]) -> tuple[float, float | None] | str:
    """The alpha and the smallest effect worth seeing, or the reason they cannot be used."""
    alpha, mde = metrics.get("alpha", 0.05), metrics.get("mde")
    if not _number(alpha) or not 0 < alpha <= MAX_ALPHA:
        return f"`alpha` must be a number above 0 and at most {MAX_ALPHA}"
    if mde is not None and (not _number(mde) or mde <= 0):
        return "`mde`, the smallest effect worth seeing, must be a number above zero"
    return float(alpha), None if mde is None else float(mde)


# -- entry: is the signal better than a dumb entry? ---------------------------------------------


@pack.gate("entry", version="1")
def entry(metrics: dict[str, Any]) -> Answer:
    """Is an entry or exit signal better than a dumb entry taken on the same days?

    `trades` holds the signal's net result on each trade, in risk units, after costs. `controls`
    holds draws of the dumb entry: each draw is one dumb entry for each of the signal's trades,
    on the same day, in the same window, on the same side. `long` and `short` hold the two sides'
    results when the claim is that both sides pay.

    A pass needs the trades to pay on average, each side to pay when two sides are claimed, and
    the signal's mean to sit in the top `alpha` of the dumb draws.

    It assumes the dumb draws are a fair picture of what the signal would have made with no
    skill. A draw of a different length from `trades` is refused: its mean would be steadier or
    shakier than the signal's, and the comparison would be rigged.
    """
    if not isinstance(metrics, dict):
        return _refuse("the metrics are not a table")
    common = _common(metrics)
    if isinstance(common, str):
        return _refuse(common)
    alpha, mde = common
    trades, min_trades = _numbers(metrics.get("trades")), metrics.get("min_trades", MIN_TRADES)
    if not trades:
        return _refuse("`trades` must be a list of numbers: the signal's net result on each trade")
    if not _whole(min_trades, MIN_TRADES):
        return _refuse(f"`min_trades` must be a whole number, {MIN_TRADES} or more: a study may ask for more "
                       "trades than that, never for fewer")
    raw = metrics.get("controls")
    controls = [_numbers(draw) for draw in raw] if isinstance(raw, list) else []
    if not controls or any(draw is None or len(draw) != len(trades) for draw in controls):
        return _refuse("`controls` must be a list of draws, each holding one dumb entry's net result "
                       "for each of the signal's trades")
    sides = {name: _numbers(metrics[name]) for name in ("long", "short") if metrics.get(name) is not None}
    if len(sides) == 1 or any(not side for side in sides.values()):
        return _refuse("give both `long` and `short`, each a list of numbers with at least one trade, or neither")
    if sides and (len(sides["long"]) + len(sides["short"]) != len(trades)
                  or not math.isclose(math.fsum(sides["long"]) + math.fsum(sides["short"]), math.fsum(trades),
                                      rel_tol=1e-9, abs_tol=1e-9)):
        return _refuse("`long` and `short` must together hold exactly the trades in `trades`")

    average = stats.mean(trades)
    at_least = sum(1 for draw in controls if stats.mean(draw) >= average)
    numbers: dict[str, Any] = {
        "trades": len(trades), "min_trades": min_trades, "mean": average, "alpha": alpha, "mde": mde,
        "control_draws": len(controls), "control_mean": stats.mean([stats.mean(draw) for draw in controls]),
        "controls_at_least_as_good": at_least, "p_value": (1 + at_least) / (1 + len(controls)),
        **{f"{name}_mean": stats.mean(side) for name, side in sides.items()},
    }
    short_of = []
    if len(trades) < min_trades:
        short_of.append(f"{len(trades)} trades, where {min_trades} are needed")
    if len(controls) < MIN_CONTROL_DRAWS:
        short_of.append(f"{len(controls)} draws of the dumb entry, where {MIN_CONTROL_DRAWS} are needed")
    if short_of:
        return _refuse("too little evidence to decide: " + " and ".join(short_of), numbers)

    # The power is not flattered: the spread is the larger of the signal's and the dumb entry's, and
    # what the dumb entry makes on average is taken off the effect, because the signal must clear it.
    spread = max(stats.stdev(trades), stats.stdev([result for draw in controls for result in draw]))
    edge = None if mde is None else mde - max(numbers["control_mean"], 0.0)
    power = None if edge is None else stats.power_of_mean_test(edge, spread, len(trades), alpha, len(controls))
    numbers.update(stdev=spread, power=power)
    powered = power is None or power >= ENOUGH_POWER
    weak = f"the test had a power of {power or 0:.2f} to see a mean of {mde}, below {ENOUGH_POWER}"

    if average <= 0:
        return _no(powered, f"the trades do not pay after costs: the mean result is {average:.4g}", weak, numbers)
    for name, side in sides.items():
        if stats.mean(side) <= 0:
            return _no(powered, f"the {name} side does not pay on its own: its mean result is "
                                f"{stats.mean(side):.4g}", weak, numbers)
    if numbers["p_value"] > alpha:
        return _no(powered, f"the signal is not better than a dumb entry: {at_least} of {len(controls)} dumb "
                            f"draws did at least as well (p = {numbers['p_value']:.3f}, and {alpha} is the bar)",
                   weak, numbers)
    return _answer("promote", "pass", True,
                   f"the trades pay after costs and beat the dumb entry: {at_least} of {len(controls)} dumb "
                   f"draws did at least as well (p = {numbers['p_value']:.3f})", numbers)


# -- signal: does the signal rank what follows? -------------------------------------------------


def _block_correlations(xs: list[float], ys: list[float], blocks: int) -> list[float]:
    """The rank correlation inside each of `blocks` consecutive stretches of the samples."""
    edges = [round(index * len(xs) / blocks) for index in range(blocks + 1)]
    return [stats.rank_correlation(xs[start:end], ys[start:end]) for start, end in itertools.pairwise(edges)]


@pack.gate("signal", version="1")
def signal(metrics: dict[str, Any]) -> Answer:
    """Does a signal rank what follows: do higher values come before higher forward values?

    `signal` and `forward` are two lists of the same length, in time order. `horizon` says how
    many steps each forward value spans; the gate reads every horizon-th pair, so no two samples
    share a step.

    A pass needs a rank correlation above zero, above the noise floor (the top `alpha` of the
    correlations the same two lists give when the signal is rotated against the forward values),
    and of the same sign in all but one of `blocks` consecutive blocks. Before it is held against
    the noise floor, the correlation loses whatever a drift shared by both lists would give alone:
    two lists that both rise over the years are correlated, and neither ranks the other.

    The samples must also be worth `MIN_SAMPLES` independent ones. Two sticky lists hold less
    evidence than their length says, and two lists that wander without limit hold almost none.

    The test is one-sided: a signal expected to rank the other way round is negated before it is
    given to the gate. The gate has no cost input, so "economics first" is here the plain demand
    that the correlation is above zero.

    It assumes each list behaves the same way along its length, apart from a steady drift. It
    cannot tell a real link from a cycle or a break that both lists share.
    """
    if not isinstance(metrics, dict):
        return _refuse("the metrics are not a table")
    common = _common(metrics)
    if isinstance(common, str):
        return _refuse(common)
    alpha, mde = common
    series, forward = _numbers(metrics.get("signal")), _numbers(metrics.get("forward"))
    if not series or not forward or len(series) != len(forward):
        return _refuse("`signal` and `forward` must be two lists of numbers of the same length")
    horizon, shifts = metrics.get("horizon", 1), metrics.get("shifts", 200)
    seed, blocks = metrics.get("seed", 0), metrics.get("blocks", 4)
    if not _whole(horizon, 1) or not _whole(shifts, 1) or not _whole(seed, 0) or not _whole(blocks, 2):
        return _refuse("`horizon` and `shifts` must be whole numbers of 1 or more, `seed` a whole number of 0 "
                       "or more, and `blocks` a whole number of 2 or more")

    xs, ys = series[::horizon], forward[::horizon]
    rotations = min(shifts, len(xs) - 1)
    numbers: dict[str, Any] = {"observations": len(series), "horizon": horizon, "samples": len(xs),
                               "alpha": alpha, "mde": mde, "blocks": blocks, "rotations": rotations}
    if len(xs) < MIN_SAMPLES:
        return _refuse(f"too little evidence to decide: {len(xs)} non-overlapping samples, where {MIN_SAMPLES} "
                       "are needed", numbers)
    if len(xs) < blocks * MIN_BLOCK:
        return _refuse(f"{blocks} blocks of {len(xs)} samples leave fewer than {MIN_BLOCK} in a block; "
                       "use fewer blocks", numbers)
    if 1 / (1 + rotations) > alpha:
        return _refuse(f"{rotations} rotations cannot show a result in the top {alpha} of the noise; "
                       "allow more shifts or bring more samples", numbers)
    if len(set(xs)) == 1 or len(set(ys)) == 1:
        return _refuse("the signal or the forward values never change, so there is nothing to rank", numbers)

    worth = stats.effective_sample_size(xs, ys)
    numbers.update(effective_samples=worth)
    if worth < MIN_SAMPLES:
        return _refuse(f"too little evidence to decide: both lists are sticky, so the {len(xs)} samples are worth "
                       f"about {worth:.0f} independent ones, where {MIN_SAMPLES} are needed", numbers)
    correlation = stats.rank_correlation(xs, ys)
    drift = max(stats.shared_drift(xs, ys), 0.0)
    detectable = stats.min_detectable_correlation(worth, ENOUGH_POWER, alpha, rotations)
    net = correlation - drift
    shown = f"{correlation:.4f} ({net:.4f} once a drift both lists share is taken out)"
    numbers.update(correlation=correlation, shared_drift=drift, correlation_without_drift=net,
                   min_detectable_correlation=detectable)
    powered = mde is None or detectable <= mde
    weak = f"the smallest correlation this test could see is {detectable:.3f}, above the {mde} worth seeing"

    if correlation <= 0:
        return _no(powered, f"the signal does not rank what follows: the rank correlation is {correlation:.4f}",
                   weak, numbers)
    null = sorted(stats.circular_shift_null(xs, ys, shifts, random.Random(seed)), reverse=True)
    at_least = sum(1 for value in null if value >= net)
    p_value = (1 + at_least) / (1 + len(null))
    numbers.update(p_value=p_value, rotations_at_least_as_high=at_least,
                   noise_floor=null[math.floor(alpha * (len(null) + 1)) - 1])
    if p_value > alpha:
        return _no(powered, f"the rank correlation of {shown} is inside its own noise: {at_least} of {len(null)} "
                            f"rotations gave at least as much (p = {p_value:.3f}, and {alpha} is the bar)",
                   weak, numbers)
    by_block = _block_correlations(xs, ys, blocks)
    agree = sum(1 for value in by_block if value > 0)
    numbers.update(block_correlations=by_block, blocks_agreeing=agree)
    if agree < blocks - 1:
        return _no(powered, f"the signal is not stable by period: it ranks the right way in only {agree} of "
                            f"{blocks} blocks", weak, numbers)
    return _answer("promote", "pass", True,
                   f"the rank correlation of {shown} is above its noise floor of {numbers['noise_floor']:.4f} "
                   f"(p = {p_value:.3f}) and holds in {agree} of {blocks} blocks", numbers)


# -- tune: did a tuned setting earn its confirmation? -------------------------------------------


def _passed(value: Any) -> bool | None:
    """A stage's outcome, or None when it is not `{"pass": true}` or `{"pass": false}`."""
    return value["pass"] if isinstance(value, dict) and isinstance(value.get("pass"), bool) else None


@pack.gate("tune", version="1")
def tune(metrics: dict[str, Any]) -> Answer:
    """Did a tuned setting earn its confirmation?

    The stages are read in the order they are run: the search stayed inside its sealed budget;
    the setting passed in-sample, out-of-sample and the walk back over untouched periods; and
    then, once, the sealed holdout. A stage that failed is a "kill". Every earlier stage passed
    and no holdout result yet is "not-confirmed": a refusal, never a pass.

    This gate reads outcomes, not prices. Whether a stage pays after costs is decided inside that
    stage, under the project's risk rules.
    """
    if not isinstance(metrics, dict):
        return _refuse("the metrics are not a table")
    tried, budget, walk = metrics.get("settings_tried"), metrics.get("budget"), metrics.get("walk_back")
    if not _whole(tried, 1) or not _whole(budget, 1):
        return _refuse("`settings_tried` and `budget` must be whole numbers of 1 or more")
    stages = {name: _passed(metrics.get(name)) for name in ("in_sample", "out_of_sample")}
    if None in stages.values():
        return _refuse('`in_sample` and `out_of_sample` must each be a table holding `pass`, true or false')
    if not isinstance(walk, dict) or not all(_whole(walk.get(key), 0) for key in ("passed", "total", "min_pass")):
        return _refuse("`walk_back` must hold the whole numbers `passed`, `total` and `min_pass`")
    if not 1 <= walk["min_pass"] <= walk["total"] or walk["passed"] > walk["total"]:
        return _refuse("`walk_back` must need at least one period, and no more periods than it has")
    holdout = None if metrics.get("holdout") is None else _passed(metrics["holdout"])
    if metrics.get("holdout") is not None and holdout is None:
        return _refuse("`holdout` must be a table holding `pass`, true or false, or be left out")

    stages["walk_back"] = walk["passed"] >= walk["min_pass"]
    numbers = {"settings_tried": tried, "budget": budget, **stages, "walk_back_passed": walk["passed"],
               "walk_back_total": walk["total"], "walk_back_min_pass": walk["min_pass"], "holdout": holdout}
    if tried > budget:
        return _answer("kill", "fail", True, f"{tried} settings were tried, and the sealed budget allowed {budget}",
                       numbers)
    failed = [name.replace("_", " ") for name, ok in stages.items() if not ok]
    if failed:
        return _answer("kill", "fail", True, "the setting did not pass: " + ", ".join(failed), numbers)
    if holdout is None:
        return _answer("not-confirmed", "refuse", False,
                       "every stage before the holdout passed, and the holdout has not been looked at yet", numbers)
    if not holdout:
        return _answer("kill", "fail", True, "the setting passed every earlier stage and failed on the holdout",
                       numbers)
    return _answer("full-pass", "pass", True, "the setting passed every stage, the holdout included", numbers)


# -- calibration: each gate is shown noise, and a planted effect --------------------------------

DRAWS = 600  # how many seeded draws a rate is measured over


def _rate(gate: Callable[[dict[str, Any]], Answer], case: Callable[[random.Random], dict[str, Any]], seed: int,
          draws: int = DRAWS) -> float:
    """How often the gate passes the case, over seeded draws."""
    rng = random.Random(seed)
    return sum(gate(case(rng))["verdict"] == "pass" for _ in range(draws)) / draws


def _result(rng: random.Random, average: float) -> float:
    """One trade's result in risk units: many small losses and a few large wins, around `average`."""
    return average + rng.expovariate(1.0) - 1.0


def entry_case(rng: random.Random, edge: float, trades: int = 60, draws: int = 100, drift: float = 0.1) -> dict:
    """A signal whose trades average `edge` more than the dumb entry's. The dumb entry itself
    makes `drift` a trade, as in a rising market, so paying after costs proves nothing alone."""
    return {
        "trades": [_result(rng, drift + edge) for _ in range(trades)],
        "controls": [[_result(rng, drift) for _ in range(trades)] for _ in range(draws)],
    }


def sticky(rng: random.Random, size: int, memory: float) -> list[float]:
    """A sticky series: each value is `memory` times the last one, plus fresh noise."""
    out, value = [], rng.gauss(0, 1)
    for _ in range(size):
        out.append(value)
        value = memory * value + math.sqrt(1 - memory * memory) * rng.gauss(0, 1)
    return out


def signal_case(rng: random.Random, correlation: float, size: int = 250) -> dict:
    """Independent draws, where the forward value shares `correlation` with the signal."""
    series = [rng.gauss(0, 1) for _ in range(size)]
    rest = math.sqrt(1 - correlation * correlation)
    return {"signal": series, "forward": [correlation * value + rest * rng.gauss(0, 1) for value in series]}


def sticky_case(rng: random.Random, size: int = 600, horizon: int = 5, memory: float = 0.9) -> dict:
    """A sticky signal, and forward values that overlap: each is the sum of the next `horizon`
    steps of a second sticky series that knows nothing of the signal."""
    steps = sticky(rng, size + horizon, memory)
    forward = [sum(steps[index + 1:index + 1 + horizon]) for index in range(size)]
    return {"signal": sticky(rng, size, memory), "forward": forward, "horizon": horizon}


def drift_case(rng: random.Random, size: int = 300, rise: float = 2.0) -> dict:
    """Two series of fresh noise that both rise by `rise` over the sample, and share nothing else."""
    return {"signal": [rise * index / size + rng.gauss(0, 1) for index in range(size)],
            "forward": [rise * index / size + rng.gauss(0, 1) for index in range(size)]}


@pack.calibration("entry", "noise", "trades drawn from the same pool as the dumb entries")
def entry_noise() -> float:
    return _rate(entry, lambda rng: entry_case(rng, edge=0.0), seed=11)


@pack.calibration("entry", "planted", "a mean 0.5 risk units above the dumb entry, over 60 trades")
def entry_planted() -> float:
    return _rate(entry, lambda rng: entry_case(rng, edge=0.5), seed=12)


@pack.calibration("signal", "noise", "two independent series")
def signal_noise() -> float:
    return _rate(signal, lambda rng: signal_case(rng, correlation=0.0), seed=21)


@pack.calibration("signal", "noise", "two sticky series, with overlapping forward values")
def signal_sticky_noise() -> float:
    return _rate(signal, sticky_case, seed=22)


@pack.calibration("signal", "noise", "two series that share a drift and nothing else")
def signal_drift_noise() -> float:
    return _rate(signal, drift_case, seed=24)


@pack.calibration("signal", "planted", "a true correlation of 0.25, over 250 samples")
def signal_planted() -> float:
    return _rate(signal, lambda rng: signal_case(rng, correlation=0.25), seed=23)


def tune_case(*, in_sample: bool = True, out_of_sample: bool = True, walk_back: bool = True,
              holdout: bool | None = True, tried: int = 20) -> dict:
    """A tuning run with a budget of 50 settings and a walk back that needs 4 periods of 5."""
    metrics = {"in_sample": {"pass": in_sample}, "out_of_sample": {"pass": out_of_sample},
               "walk_back": {"passed": 5 if walk_back else 3, "total": 5, "min_pass": 4},
               "settings_tried": tried, "budget": 50}
    return metrics if holdout is None else {**metrics, "holdout": {"pass": holdout}}


@pack.calibration("tune", "noise", "every way a tuning run can fall short")
def tune_noise() -> float:
    flags = [(a, b, c, d) for a in (True, False) for b in (True, False) for c in (True, False) for d in (True, False)]
    cases = [tune_case(in_sample=a, out_of_sample=b, walk_back=c, holdout=d) for a, b, c, d in flags if not all(
        (a, b, c, d))]
    cases += [tune_case(holdout=None), tune_case(tried=51)]
    return sum(tune(case)["verdict"] == "pass" for case in cases) / len(cases)


@pack.calibration("tune", "planted", "every stage passed, the holdout included")
def tune_planted() -> float:
    return float(tune(tune_case())["verdict"] == "pass")
