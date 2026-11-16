"""The trading pack's statistics and gate functions.

A gate that passes noise does harm, so the tests here ask each gate the questions a doubter would:
does it turn noise down, does it find a planted effect, does it refuse when it knows too little,
and does it ever pass on bad inputs?
"""

from __future__ import annotations

import json
import math
import random
import time

import pytest

from themis import pack
from themis.pack import kit
from themis.packs.trading import gates, stats

trading = pack.load("trading")
GATES = ("entry", "signal", "tune")
KEYS = {"decision", "verdict", "enough_evidence", "reason", "numbers"}


# --- statistics --------------------------------------------------------------------------------


def test_the_bell_curve_helpers_are_each_others_inverse() -> None:
    assert stats.normal_ppf(0.975) == pytest.approx(1.959964, abs=1e-6)
    assert stats.normal_cdf(stats.normal_ppf(0.3)) == pytest.approx(0.3)


def test_equal_values_share_the_average_of_their_ranks() -> None:
    assert stats.ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]
    assert stats.ranks([5, 5, 5]) == [2.0, 2.0, 2.0]


def test_rank_correlation_on_cases_worked_by_hand() -> None:
    assert stats.rank_correlation([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == pytest.approx(1.0)
    assert stats.rank_correlation([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    # ranks 1, 2.5, 2.5, 4 against 1, 3, 2, 4: 4.5 / sqrt(4.5 * 5)
    assert stats.rank_correlation([1, 2, 2, 3], [1, 3, 2, 4]) == pytest.approx(4.5 / math.sqrt(22.5))
    # the textbook case with no ties: 1 - 6 * sum(d^2) / (n * (n^2 - 1)), with d = 0, 1, -1, 0, 0
    assert stats.rank_correlation([1, 2, 3, 4, 5], [1, 3, 2, 4, 5]) == pytest.approx(1 - 6 * 2 / (5 * 24))


def test_rank_correlation_reads_order_only() -> None:
    rng = random.Random(1)
    x, y = [rng.gauss(0, 1) for _ in range(50)], [rng.gauss(0, 1) for _ in range(50)]
    assert stats.rank_correlation([value ** 3 for value in x], [math.exp(value) for value in y]) == pytest.approx(
        stats.rank_correlation(x, y))
    assert stats.rank_correlation([1, 1, 1], [1, 2, 3]) == 0.0  # a list that never changes ranks nothing
    with pytest.raises(ValueError):
        stats.rank_correlation([1, 2, 3], [1, 2])


def test_the_circular_null_is_the_rank_correlation_of_each_rotation() -> None:
    rng = random.Random(2)
    x, y = [rng.gauss(0, 1) for _ in range(40)], [rng.gauss(0, 1) for _ in range(40)]
    every = stats.circular_shift_null(x, y, 1000, rng)  # more shifts than offsets: each offset once
    assert every == pytest.approx([stats.rank_correlation(x[k:] + x[:k], y) for k in range(1, 40)])
    some = stats.circular_shift_null(x, y, 10, random.Random(7))
    assert len(some) == 10 and all(any(value == pytest.approx(known) for known in every) for value in some)
    assert some == stats.circular_shift_null(x, y, 10, random.Random(7))  # the same seed, the same draws
    with pytest.raises(ValueError):
        stats.circular_shift_null(x, y[:-1], 10, rng)


def test_the_circular_null_keeps_stickiness_that_a_shuffle_destroys() -> None:
    """Two sticky series that know nothing of each other: rotating gives a wide null, as it
    should; shuffling gives a narrow one, which makes chance look like a finding."""
    rng = random.Random(3)
    x, y = gates.sticky(rng, 400, 0.95), gates.sticky(rng, 400, 0.95)
    rotated = stats.circular_shift_null(x, y, 399, rng)
    shuffled = []
    for _ in range(200):
        dealt = rng.sample(x, len(x))
        shuffled.append(stats.rank_correlation(dealt, y))
    assert stats.stdev(rotated) > 3 * stats.stdev(shuffled)


def test_stickiness_and_drift_are_measured() -> None:
    rng = random.Random(4)
    fresh = [rng.gauss(0, 1) for _ in range(500)]
    slow_a, slow_b = gates.sticky(rng, 500, 0.95), gates.sticky(rng, 500, 0.95)
    assert abs(stats.lag_one_correlation(fresh)) < 0.15 and stats.lag_one_correlation(slow_a) > 0.8
    assert stats.effective_sample_size(fresh, fresh[::-1]) > 450
    assert stats.effective_sample_size(slow_a, slow_b) < 100
    assert stats.effective_sample_size(slow_a, slow_b) <= 500
    rising = [index / 100 + rng.gauss(0, 1) for index in range(500)]
    also_rising = [index / 100 + rng.gauss(0, 1) for index in range(500)]
    assert stats.shared_drift(rising, also_rising) > 0.5
    assert abs(stats.shared_drift(fresh, rising)) < 0.1


def test_the_smallest_detectable_correlation() -> None:
    wanted = math.tanh((stats.normal_ppf(0.95) + stats.normal_ppf(0.8)) * math.sqrt(1.06 / 97))
    assert stats.min_detectable_correlation(100) == pytest.approx(wanted)
    assert stats.min_detectable_correlation(30) > stats.min_detectable_correlation(100) > (
        stats.min_detectable_correlation(1000))
    assert stats.min_detectable_correlation(100, power=0.9) > stats.min_detectable_correlation(100)
    assert stats.min_detectable_correlation(3) == 1.0


def test_the_smallest_detectable_correlation_is_found_about_four_times_in_five() -> None:
    """The formula's promise, checked by drawing: a true rank correlation at the detectable size,
    tested one-sided at 0.05 on 100 independent pairs, is found with a power near 0.8."""
    rng, size, found = random.Random(5), 100, 0
    target = stats.min_detectable_correlation(size)
    shared = 2 * math.sin(math.pi * target / 6)  # the plain correlation that gives this rank correlation
    bar = math.tanh(stats.normal_ppf(0.95) * math.sqrt(1.06 / (size - 3)))
    for _ in range(600):
        x = [rng.gauss(0, 1) for _ in range(size)]
        y = [shared * value + math.sqrt(1 - shared ** 2) * rng.gauss(0, 1) for value in x]
        found += stats.rank_correlation(x, y) > bar
    assert 0.74 <= found / 600 <= 0.86


def test_the_power_of_a_test_of_a_mean() -> None:
    effect = (stats.normal_ppf(0.95) + stats.normal_ppf(0.8)) * 2.0 / math.sqrt(50)
    assert stats.power_of_mean_test(effect, 2.0, 50) == pytest.approx(0.8)
    assert stats.power_of_mean_test(0.2, 1.0, 400) > stats.power_of_mean_test(0.2, 1.0, 100)
    assert stats.power_of_mean_test(0.2, 1.0, 100) > stats.power_of_mean_test(0.2, 2.0, 100)
    assert stats.power_of_mean_test(0.0, 1.0, 100) == 0.0 and stats.power_of_mean_test(0.2, 1.0, 0) == 0.0


def test_a_test_against_few_draws_is_weaker_than_the_bell_curve_says() -> None:
    """With 20 no-skill draws a result must beat every one of them, and the best of 20 is itself
    a matter of luck. The power is worked out for that test, and checked here by drawing."""
    plain = stats.power_of_mean_test(0.25, 1.0, 100)
    few, many = stats.power_of_mean_test(0.25, 1.0, 100, draws=20), stats.power_of_mean_test(0.25, 1.0, 100, draws=999)
    assert few < 0.75 < plain and many == pytest.approx(plain, abs=0.01)
    assert stats.power_of_mean_test(0.25, 1.0, 100, draws=5000) == plain
    assert stats.power_of_mean_test(0.25, 1.0, 100, draws=18) == 0.0  # 18 draws can never show a top 5%
    rng, found = random.Random(7), 0
    for _ in range(4000):
        result = rng.gauss(2.5, 1)  # 0.25 a trade over 100 trades, in standard errors
        found += all(rng.gauss(0, 1) < result for _ in range(20))
    assert found / 4000 == pytest.approx(few, abs=0.03)
    assert stats.min_detectable_correlation(100, draws=29) > stats.min_detectable_correlation(100, draws=200) > (
        stats.min_detectable_correlation(100))
    assert stats.min_detectable_correlation(100, draws=18) == 1.0


# --- every gate --------------------------------------------------------------------------------


PLANTED_ENTRY = gates.entry_case(random.Random(1), edge=0.5)
NOISE_ENTRY = gates.entry_case(random.Random(4), edge=0.0)
PLANTED_SIGNAL = gates.signal_case(random.Random(3), correlation=0.25)


def _noise_signal(size: int = 250, **changes: object) -> dict:
    return {**gates.signal_case(random.Random(4), correlation=0.0, size=size), **changes}


ANSWERS = {
    "entry passes": (gates.entry, PLANTED_ENTRY, "promote", "pass", True),
    "entry fails": (gates.entry, NOISE_ENTRY, "kill", "fail", True),
    "entry defers": (gates.entry, {**NOISE_ENTRY, "mde": 0.1}, "defer", "refuse", False),
    "signal passes": (gates.signal, PLANTED_SIGNAL, "promote", "pass", True),
    "signal fails": (gates.signal, _noise_signal(), "kill", "fail", True),
    "signal defers": (gates.signal, _noise_signal(mde=0.05), "defer", "refuse", False),
    "tune passes": (gates.tune, gates.tune_case(), "full-pass", "pass", True),
    "tune fails": (gates.tune, gates.tune_case(out_of_sample=False), "kill", "fail", True),
    "tune is not confirmed": (gates.tune, gates.tune_case(holdout=None), "not-confirmed", "refuse", False),
}


@pytest.mark.parametrize("name", sorted(ANSWERS))
def test_a_gate_answers_in_the_agreed_shape(name: str) -> None:
    gate, metrics, decision, verdict, enough = ANSWERS[name]
    answer = gate(metrics)
    assert set(answer) == KEYS
    assert (answer["decision"], answer["verdict"], answer["enough_evidence"]) == (decision, verdict, enough)
    assert answer["reason"].strip() and isinstance(answer["numbers"], dict)
    json.dumps(answer, allow_nan=False)  # the answer is stored as a decision record
    assert gate(json.loads(json.dumps(metrics))) == answer  # the same metrics, the same answer


def test_the_pack_holds_the_three_gates_each_with_a_version() -> None:
    assert set(GATES) <= set(trading.gates)
    assert all(trading.gate_versions[name] == "1" for name in GATES)
    assert [problem for problem in kit.problems(trading) if problem.startswith(("gate ", "calibration"))] == []


BAD_ENTRY = {
    "no trades": {"trades": None},
    "trades that are not numbers": {"trades": ["1.5", "2"] * 30},
    "a trade that is not a number at all": {"trades": [float("nan")] * 60},
    "true and false are not results": {"trades": [True] * 60},
    "no controls": {"controls": None},
    "controls that are one flat list": {"controls": [0.1] * 60},
    "a control draw of another length": {"controls": [[0.1] * 59] * 100},
    "an alpha that lets noise through": {"alpha": 0.5},
    "an alpha of zero": {"alpha": 0},
    "a smallest effect of zero": {"mde": 0},
    "a minimum of one trade": {"min_trades": 1},
    "a minimum set below the gate's own floor": {"min_trades": gates.MIN_TRADES - 1},
    "one side without the other": {"long": [1.0] * 60},
    "an empty side": {"long": [1.0] * 60, "short": []},
    "sides that are not the trades": {"long": [5.0] * 30, "short": [5.0] * 30},
}
BAD_SIGNAL = {
    "no signal": {"signal": None},
    "lists of different lengths": {"forward": [0.0] * 249},
    "a value that is not a number": {"forward": [None] * 250},
    "a horizon of zero": {"horizon": 0},
    "a horizon that is not whole": {"horizon": 2.5},
    "one block": {"blocks": 1},
    "more blocks than the samples can fill": {"blocks": 60},
    "too few rotations to reach the bar": {"shifts": 10},
    "a seed that is not a whole number": {"seed": "7"},
    "an alpha that lets noise through": {"alpha": 0.2},
    "a smallest effect below zero": {"mde": -0.1},
    "a signal that never changes": {"signal": [1.0] * 250},
}
BAD_TUNE = {
    "no in-sample result": {"in_sample": None},
    "a pass written as a word": {"out_of_sample": {"pass": "yes"}},
    "a stage given as a bare flag": {"in_sample": True},
    "no walk back": {"walk_back": None},
    "a walk back that needs nothing": {"walk_back": {"passed": 5, "total": 5, "min_pass": 0}},
    "a walk back that needs more than it has": {"walk_back": {"passed": 5, "total": 5, "min_pass": 6}},
    "more periods passed than exist": {"walk_back": {"passed": 6, "total": 5, "min_pass": 4}},
    "a count below zero": {"walk_back": {"passed": -1, "total": 5, "min_pass": 4}},
    "no count of settings": {"settings_tried": None},
    "a budget of zero": {"budget": 0},
    "a budget that is not whole": {"budget": 50.5},
    "a holdout written as a word": {"holdout": "passed"},
    "a holdout with no result in it": {"holdout": {}},
}
BAD = [(gate, base, name, change) for gate, base, cases in (
    (gates.entry, PLANTED_ENTRY, BAD_ENTRY), (gates.signal, PLANTED_SIGNAL, BAD_SIGNAL),
    (gates.tune, gates.tune_case(), BAD_TUNE)) for name, change in cases.items()]


@pytest.mark.parametrize(("gate", "base", "name", "change"), BAD, ids=[f"{bad[0].__name__}: {bad[2]}" for bad in BAD])
def test_a_gate_refuses_inputs_it_cannot_trust(gate, base: dict, name: str, change: dict) -> None:
    assert gate(base)["verdict"] == "pass"  # the same metrics pass until this one input goes bad
    answer = gate({**base, **change})
    assert (answer["verdict"], answer["decision"], answer["enough_evidence"]) == ("refuse", "defer", False), name


@pytest.mark.parametrize("gate", [gates.entry, gates.signal, gates.tune])
@pytest.mark.parametrize("metrics", [{}, None, [], "metrics", {"trades": []}])
def test_no_gate_passes_on_nothing(gate, metrics) -> None:
    assert gate(metrics)["verdict"] == "refuse"


# --- entry -------------------------------------------------------------------------------------


def _entry(mean: float, dumb: float, *, trades: int = 60, draws: int = 40, spread: float = 0.2, seed: int = 5) -> dict:
    rng = random.Random(seed)
    return {"trades": [mean + rng.gauss(0, spread) for _ in range(trades)],
            "controls": [[dumb + rng.gauss(0, spread) for _ in range(trades)] for _ in range(draws)]}


def test_entry_puts_economics_first() -> None:
    """The trades lose money, and the dumb entry loses far more. Beating it is not enough."""
    answer = gates.entry(_entry(mean=-0.1, dumb=-1.0))
    assert answer["numbers"]["controls_at_least_as_good"] == 0
    assert (answer["verdict"], answer["decision"]) == ("fail", "kill")
    assert "do not pay after costs" in answer["reason"] and "dumb" not in answer["reason"]


def test_entry_needs_to_beat_the_dumb_entry_not_only_to_pay() -> None:
    """In a rising market the dumb entry pays as well. Paying is not skill."""
    answer = gates.entry(_entry(mean=0.5, dumb=0.5))
    assert answer["numbers"]["mean"] > 0
    assert (answer["verdict"], answer["enough_evidence"]) == ("fail", True)
    assert "not better than a dumb entry" in answer["reason"]


def test_entry_needs_each_side_to_pay_when_two_sides_are_claimed() -> None:
    metrics = _entry(mean=0.5, dumb=0.0)
    paying, losing = [abs(value) + 1.0 for value in metrics["trades"][:30]], [-0.2] * 30
    metrics["trades"] = paying + losing
    assert gates.entry(metrics)["verdict"] == "pass"  # as one pool the trades pay and beat the dumb entry
    answer = gates.entry({**metrics, "long": paying, "short": losing})
    assert (answer["verdict"], answer["decision"]) == ("fail", "kill")
    assert "the short side does not pay on its own" in answer["reason"]
    both = gates.entry({**metrics, "long": metrics["trades"][::2], "short": metrics["trades"][1::2]})
    assert both["verdict"] == "pass" and both["numbers"]["long_mean"] > 0 and both["numbers"]["short_mean"] > 0


def test_entry_never_decides_on_too_few_trades_however_good_they_look() -> None:
    answer = gates.entry(_entry(mean=2.0, dumb=0.0, trades=29))
    assert answer["numbers"]["controls_at_least_as_good"] == 0
    assert (answer["verdict"], answer["decision"], answer["enough_evidence"]) == ("refuse", "defer", False)
    assert "29 trades, where 30 are needed" in answer["reason"]
    assert gates.entry(_entry(mean=2.0, dumb=0.0, trades=30))["verdict"] == "pass"
    assert gates.entry({**_entry(mean=2.0, dumb=0.0, trades=30), "min_trades": 50})["verdict"] == "refuse"


def test_entry_never_decides_on_too_few_dumb_draws() -> None:
    answer = gates.entry(_entry(mean=2.0, dumb=0.0, draws=19))
    assert (answer["verdict"], answer["decision"]) == ("refuse", "defer")
    assert "19 draws of the dumb entry, where 20 are needed" in answer["reason"]
    losing = gates.entry(_entry(mean=-1.0, dumb=0.0, draws=19))
    assert losing["verdict"] == "refuse"  # too little evidence is no kill either


def test_entry_counts_itself_among_the_draws() -> None:
    """With 20 draws, one dumb draw as good as the signal already puts the signal outside the top
    5%: 2 of 21 is above 0.05. A plain share, 1 of 20, would have let it through."""
    metrics = _entry(mean=0.3, dumb=0.0, draws=20)
    assert gates.entry(metrics)["verdict"] == "pass"
    metrics["controls"][0] = [value + 0.01 for value in metrics["trades"]]
    answer = gates.entry(metrics)
    assert answer["numbers"]["controls_at_least_as_good"] == 1
    assert answer["numbers"]["p_value"] == pytest.approx(2 / 21) and answer["verdict"] == "fail"


def test_an_underpowered_no_from_entry_is_a_deferral() -> None:
    weak = gates.entry({**_entry(mean=0.0, dumb=0.0, trades=30, spread=1.0), "mde": 0.2})
    assert (weak["verdict"], weak["decision"], weak["enough_evidence"]) == ("refuse", "defer", False)
    assert weak["numbers"]["power"] < 0.8 and "power" in weak["reason"] and "defer" in weak["reason"]
    strong = gates.entry({**_entry(mean=0.0, dumb=0.0, trades=400, spread=1.0), "mde": 0.2})
    assert (strong["verdict"], strong["decision"], strong["enough_evidence"]) == ("fail", "kill", True)
    assert strong["numbers"]["power"] >= 0.8


def test_the_power_of_entry_is_the_power_of_the_test_it_runs() -> None:
    """The same trades and the same smallest effect: against 200 dumb draws the no is a kill;
    against 20 the test is too weak, and the no is a deferral."""
    few = gates.entry({**_entry(mean=0.0, dumb=0.0, trades=100, draws=20, spread=1.0), "mde": 0.3})
    many = gates.entry({**_entry(mean=0.0, dumb=0.0, trades=100, draws=200, spread=1.0), "mde": 0.3})
    assert few["numbers"]["power"] < 0.8 <= many["numbers"]["power"]
    assert (few["verdict"], many["verdict"]) == ("refuse", "fail")


def test_an_underpowered_loss_is_a_deferral_too() -> None:
    answer = gates.entry({**_entry(mean=-0.1, dumb=0.0, trades=30, spread=1.0), "mde": 0.2})
    assert (answer["verdict"], answer["decision"]) == ("refuse", "defer")
    assert "do not pay after costs" in answer["reason"]


def test_what_the_dumb_entry_makes_comes_off_the_power() -> None:
    """A signal worth 0.2 a trade must still clear a dumb entry that makes 0.15. The test can see
    only the 0.05 between them, so its power is low and its no is a deferral."""
    flat = gates.entry({**_entry(mean=0.0, dumb=0.0, trades=400, spread=1.0), "mde": 0.2})
    rising = gates.entry({**_entry(mean=0.15, dumb=0.15, trades=400, spread=1.0), "mde": 0.2})
    assert rising["numbers"]["power"] < 0.5 < flat["numbers"]["power"]
    assert (flat["verdict"], rising["verdict"]) == ("fail", "refuse")


# --- signal ------------------------------------------------------------------------------------


def test_signal_reports_what_it_measured() -> None:
    answer = gates.signal(PLANTED_SIGNAL)
    numbers = answer["numbers"]
    assert answer["verdict"] == "pass"
    assert numbers["correlation"] > numbers["noise_floor"] > 0 and numbers["p_value"] <= 0.05
    assert numbers["samples"] == 250 and numbers["rotations"] == 200 and numbers["blocks_agreeing"] >= 3
    assert numbers["effective_samples"] <= 250


def test_signal_reads_only_samples_that_do_not_overlap() -> None:
    metrics = {**gates.signal_case(random.Random(8), correlation=0.4, size=600), "horizon": 5}
    numbers = gates.signal(metrics)["numbers"]
    assert (numbers["observations"], numbers["samples"]) == (600, 120)
    assert numbers["correlation"] == pytest.approx(
        stats.rank_correlation(metrics["signal"][::5], metrics["forward"][::5]))


def test_signal_never_decides_on_fewer_than_thirty_samples() -> None:
    strong = gates.signal_case(random.Random(9), correlation=0.95, size=145)
    answer = gates.signal({**strong, "horizon": 5})  # 145 steps, 29 samples that do not overlap
    assert (answer["verdict"], answer["decision"], answer["enough_evidence"]) == ("refuse", "defer", False)
    assert "29 non-overlapping samples, where 30 are needed" in answer["reason"]
    assert gates.signal(strong)["verdict"] == "pass"


def test_signal_puts_the_sign_first() -> None:
    """A signal that ranks the wrong way round is a no before any noise floor is read."""
    answer = gates.signal(gates.signal_case(random.Random(10), correlation=-0.4))
    assert (answer["verdict"], answer["decision"], answer["enough_evidence"]) == ("fail", "kill", True)
    assert "does not rank what follows" in answer["reason"] and "p_value" not in answer["numbers"]


def test_an_underpowered_no_from_signal_is_a_deferral() -> None:
    weak = gates.signal(_noise_signal(size=100, mde=0.05))
    assert (weak["verdict"], weak["decision"], weak["enough_evidence"]) == ("refuse", "defer", False)
    assert weak["numbers"]["min_detectable_correlation"] > 0.05 and "defer" in weak["reason"]
    strong = gates.signal(_noise_signal(size=250, mde=0.3))
    assert (strong["verdict"], strong["decision"], strong["enough_evidence"]) == ("fail", "kill", True)
    assert strong["numbers"]["min_detectable_correlation"] <= 0.3


def test_fewer_rotations_make_the_signal_test_weaker_and_it_says_so() -> None:
    many, few = gates.signal(_noise_signal(mde=0.17)), gates.signal(_noise_signal(mde=0.17, shifts=20))
    assert many["numbers"]["min_detectable_correlation"] <= 0.17 < few["numbers"]["min_detectable_correlation"]
    assert (many["verdict"], few["verdict"]) == ("fail", "refuse")
    assert few["numbers"]["min_detectable_correlation"] == pytest.approx(stats.min_detectable_correlation(
        few["numbers"]["effective_samples"], 0.8, 0.05, draws=20))


def test_signal_fails_a_link_that_does_not_hold_by_period() -> None:
    """Strong in the first half, the wrong way round in the second: above the noise floor as a
    whole, and not a signal anyone could have traded."""
    rng = random.Random(11)
    series = [rng.gauss(0, 1) for _ in range(400)]
    forward = [(value if index < 200 else -0.25 * value) + 0.3 * rng.gauss(0, 1) for index, value in enumerate(series)]
    answer = gates.signal({"signal": series, "forward": forward})
    assert answer["numbers"]["p_value"] <= 0.05 and answer["numbers"]["blocks_agreeing"] == 2
    assert (answer["verdict"], answer["decision"]) == ("fail", "kill")
    assert "not stable by period" in answer["reason"]


def test_signal_refuses_two_series_that_wander() -> None:
    """Two random walks are the classic false finding. Their samples are worth a handful."""
    rng = random.Random(12)
    walk_a, walk_b = [0.0], [0.0]
    for _ in range(599):
        walk_a.append(walk_a[-1] + rng.gauss(0, 1))
        walk_b.append(walk_b[-1] + rng.gauss(0, 1))
    answer = gates.signal({"signal": walk_a, "forward": walk_b})
    assert (answer["verdict"], answer["decision"]) == ("refuse", "defer")
    assert answer["numbers"]["effective_samples"] < 30 and "sticky" in answer["reason"]


def test_signal_takes_a_shared_drift_out_before_it_reads_the_noise_floor() -> None:
    metrics = gates.drift_case(random.Random(13), rise=3.0)
    numbers = gates.signal(metrics)["numbers"]
    assert gates.signal(metrics)["verdict"] == "fail"
    assert numbers["correlation"] > numbers["noise_floor"]  # the raw number alone would have passed
    assert numbers["correlation_without_drift"] < numbers["noise_floor"]
    assert numbers["shared_drift"] == pytest.approx(stats.shared_drift(metrics["signal"], metrics["forward"]))


def test_the_seed_is_part_of_the_metrics_so_the_answer_repeats() -> None:
    metrics = {**gates.signal_case(random.Random(14), correlation=0.1, size=1000), "shifts": 100}
    assert gates.signal({**metrics, "seed": 3}) == gates.signal({**metrics, "seed": 3})
    assert gates.signal({**metrics, "seed": 3})["numbers"]["noise_floor"] != (
        gates.signal({**metrics, "seed": 4})["numbers"]["noise_floor"])


# --- tune --------------------------------------------------------------------------------------


def test_tune_passes_with_the_holdout_and_is_not_confirmed_without_it() -> None:
    answer = gates.tune(gates.tune_case())
    assert (answer["decision"], answer["verdict"], answer["enough_evidence"]) == ("full-pass", "pass", True)
    assert gates.tune(gates.tune_case(tried=50))["verdict"] == "pass"  # the budget itself is allowed
    answer = gates.tune(gates.tune_case(holdout=None))
    assert (answer["decision"], answer["verdict"], answer["enough_evidence"]) == ("not-confirmed", "refuse", False)
    assert gates.tune({**gates.tune_case(holdout=None), "holdout": None})["decision"] == "not-confirmed"


def test_tune_fails_a_search_that_went_over_its_budget() -> None:
    answer = gates.tune(gates.tune_case(tried=51))
    assert (answer["decision"], answer["verdict"], answer["enough_evidence"]) == ("kill", "fail", True)
    assert "51 settings were tried, and the sealed budget allowed 50" in answer["reason"]


@pytest.mark.parametrize(("stage", "said"), [
    ("in_sample", "in sample"), ("out_of_sample", "out of sample"), ("walk_back", "walk back"),
])
def test_tune_fails_when_one_stage_fails(stage: str, said: str) -> None:
    for holdout in (True, False, None):  # a failed stage is a kill whatever the holdout says, or does not say
        answer = gates.tune(gates.tune_case(**{stage: False}, holdout=holdout))
        assert (answer["decision"], answer["verdict"], answer["enough_evidence"]) == ("kill", "fail", True)
        assert said in answer["reason"]


def test_tune_fails_on_a_failed_holdout() -> None:
    answer = gates.tune(gates.tune_case(holdout=False))
    assert (answer["decision"], answer["verdict"], answer["enough_evidence"]) == ("kill", "fail", True)
    assert "failed on the holdout" in answer["reason"]


def test_the_walk_back_passes_at_its_minimum_and_not_below() -> None:
    at_least = {**gates.tune_case(), "walk_back": {"passed": 4, "total": 5, "min_pass": 4}}
    below = {**gates.tune_case(), "walk_back": {"passed": 3, "total": 5, "min_pass": 4}}
    assert gates.tune(at_least)["verdict"] == "pass" and gates.tune(below)["verdict"] == "fail"


# --- calibration -------------------------------------------------------------------------------

CASES = [case for case in trading.calibrations if case.gate in GATES]


@pytest.fixture(scope="module")
def measured() -> dict[tuple[str, str, str], tuple[float, float]]:
    """Each calibration case's rate, and how long it took, measured once."""
    out = {}
    for case in CASES:
        started = time.perf_counter()
        out[(case.gate, case.kind, case.name)] = (case.run(), time.perf_counter() - started)
    return out


def test_every_gate_has_noise_and_a_planted_effect() -> None:
    for gate in GATES:
        assert {case.kind for case in CASES if case.gate == gate} == {"noise", "planted"}
    assert sum(case.gate == "signal" and case.kind == "noise" for case in CASES) >= 2
    assert any("sticky" in case.name and "overlapping" in case.name for case in CASES)


@pytest.mark.parametrize("case", CASES, ids=[f"{case.gate}/{case.kind}: {case.name}" for case in CASES])
def test_the_gate_is_calibrated(case, measured) -> None:
    rate, seconds = measured[(case.gate, case.kind, case.name)]
    assert 0.0 <= rate <= 1.0
    if case.kind == "noise":
        assert rate <= 0.10, f"the gate passed noise {rate:.1%} of the time"
    else:
        assert rate >= 0.80, f"the gate found the planted effect only {rate:.1%} of the time"
    assert seconds < 3.0


def test_the_rates_are_measured_over_many_draws_and_repeat_exactly(measured) -> None:
    assert gates.DRAWS >= 200
    assert gates.entry_noise() == measured[("entry", "noise", "trades drawn from the same pool as the dumb entries")][0]
    assert gates.tune_noise() == 0.0 and gates.tune_planted() == 1.0
    for gate in GATES:  # the kit reports the worst case of each kind
        noise = [rate for (name, kind, _), (rate, _) in measured.items() if name == gate and kind == "noise"]
        planted = [rate for (name, kind, _), (rate, _) in measured.items() if name == gate and kind == "planted"]
        assert max(noise) <= 0.10 and min(planted) >= 0.80


def test_the_sticky_case_is_one_a_plain_shuffle_gets_wrong(measured) -> None:
    """The same sticky, overlapping data, judged by shuffling the signal: it calls chance a
    finding far more often than one time in ten. The gate, on the same kind of data, does not."""
    rng, passed, draws = random.Random(31), 0, 60
    for _ in range(draws):
        case = gates.sticky_case(rng)
        dealt, forward = stats.ranks(case["signal"]), stats.ranks(case["forward"])
        observed = stats.rank_correlation(dealt, forward)
        beaten = 0
        for _ in range(59):
            rng.shuffle(dealt)
            beaten += stats.rank_correlation(dealt, forward) >= observed
        passed += (1 + beaten) / 60 <= 0.05
    assert passed / draws > 0.15
    assert measured[("signal", "noise", "two sticky series, with overlapping forward values")][0] <= 0.10
