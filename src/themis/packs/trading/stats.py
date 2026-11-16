"""Small statistics for the trading pack, on plain lists of numbers.

Every function here is pure: numbers in, numbers out. Nothing is read or written, and nothing
beyond the standard library is used. Each docstring says what the function computes and what it
assumes, because a statistic used outside its assumptions is a number with no meaning.

Three conventions hold throughout. A function raises `ValueError` when it is given too few numbers
to compute anything. A ratio whose bottom is zero returns `nan` ("not a number"), never a made-up
value, so a caller must look before it quotes. A correlation with a list that never changes is
0.0: such a list ranks nothing.
"""

from __future__ import annotations

import functools
import math
import operator
import random
from collections.abc import Sequence
from statistics import NormalDist

_NORMAL = NormalDist()
#: The Euler-Mascheroni constant, used for the largest value expected among many noisy tries.
EULER_MASCHERONI = 0.5772156649015329
#: Ranks are a little noisier than the raw values, so a rank correlation's Fisher z has this much
#: more variance than 1 / (n - 3).
RANK_VARIANCE = 1.06
#: Above this many no-skill draws, a test against the draws behaves as a test against a bell curve.
MOST_DRAWS = 1000
_GRID = 400  # the steps of the sum that stands in for an integral


def mean(values: Sequence[float]) -> float:
    """The arithmetic mean. Needs at least one number."""
    if not values:
        raise ValueError("a mean needs at least one number")
    return math.fsum(values) / len(values)


def stdev(values: Sequence[float]) -> float:
    """The sample standard deviation (the divisor is n - 1). Needs at least two numbers."""
    if len(values) < 2:
        raise ValueError("a standard deviation needs at least two numbers")
    centre = mean(values)
    return math.sqrt(math.fsum((value - centre) ** 2 for value in values) / (len(values) - 1))


def normal_cdf(x: float) -> float:
    """The share of a standard bell curve that lies at or below `x`."""
    return _NORMAL.cdf(x)


def normal_ppf(p: float) -> float:
    """The point of a standard bell curve with the share `p` at or below it. `p` is strictly
    between 0 and 1."""
    return _NORMAL.inv_cdf(p)


def ranks(values: Sequence[float]) -> list[float]:
    """Each value's rank, 1 for the smallest. Equal values share the average of their ranks."""
    order = sorted(range(len(values)), key=values.__getitem__)
    out = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for index in order[start:end + 1]:
            out[index] = (start + end) / 2 + 1
        start = end + 1
    return out


def _centred(values: Sequence[float]) -> tuple[list[float], float]:
    centre = mean(values)
    moved = [value - centre for value in values]
    return moved, math.fsum(value * value for value in moved)


def rank_correlation(x: Sequence[float], y: Sequence[float]) -> float:
    """Spearman's rank correlation: how well the order of `x` matches the order of `y`, from -1
    to 1. Ties take average ranks.

    It assumes nothing about the shape of either list, only that the pairs line up. It returns
    0.0 when either list never changes, because a list with one value ranks nothing.
    """
    if len(x) != len(y):
        raise ValueError("a rank correlation needs two lists of the same length")
    if len(x) < 2:
        raise ValueError("a rank correlation needs at least two pairs")
    (dx, sxx), (dy, syy) = _centred(ranks(x)), _centred(ranks(y))
    if sxx == 0 or syy == 0:
        return 0.0
    return math.fsum(map(operator.mul, dx, dy)) / math.sqrt(sxx * syy)


def circular_shift_null(
    signal: Sequence[float], forward: Sequence[float], shifts: int, rng: random.Random
) -> list[float]:
    """The rank correlations obtained by rotating `signal` against `forward` by random offsets.

    Rotating moves the whole signal along by an offset and wraps its end round to its start. Each
    list keeps its own order, so each keeps its own stickiness (a high value tends to follow a
    high value). A plain shuffle destroys that, and so makes a sticky signal look more surprising
    than it is.

    The offsets are drawn without repeats from 1 to n - 1. When `shifts` is n - 1 or more, every
    offset is used once, so the list returned can be shorter than `shifts`.

    It assumes each list behaves the same way along its whole length (no trend, no break), and
    that the list is much longer than its stickiness lasts. The one join where the end meets the
    start is ignored.
    """
    if len(signal) != len(forward):
        raise ValueError("the signal and the forward values must have the same length")
    size = len(signal)
    if size < 3 or shifts < 1:
        return []
    offsets = list(range(1, size)) if shifts >= size - 1 else rng.sample(range(1, size), shifts)
    (dx, sxx), (dy, syy) = _centred(ranks(signal)), _centred(ranks(forward))
    if sxx == 0 or syy == 0:
        return [0.0] * len(offsets)
    scale = math.sqrt(sxx * syy)
    return [sum(map(operator.mul, dx[offset:] + dx[:offset], dy)) / scale for offset in offsets]


def lag_one_correlation(values: Sequence[float]) -> float:
    """How strongly each value's rank follows the rank of the value before it, from -1 to 1.
    0.0 when the list never changes or holds fewer than three values."""
    if len(values) < 3:
        return 0.0
    moved, total = _centred(ranks(values))
    return math.fsum(map(operator.mul, moved[:-1], moved[1:])) / total if total else 0.0


def effective_sample_size(x: Sequence[float], y: Sequence[float]) -> float:
    """How many independent pairs two sticky lists are worth, for a correlation between them.

    With `a` and `b` the two lists' lag-one correlations, it is n * (1 - a*b) / (1 + a*b). It is
    never above n. It assumes each list's stickiness fades at a steady rate, which is the simplest
    model of a sticky series; a list with long memory is worth fewer pairs than this says.
    """
    product = min(max(lag_one_correlation(x) * lag_one_correlation(y), 0.0), 0.99)
    return len(x) * (1 - product) / (1 + product)


def shared_drift(x: Sequence[float], y: Sequence[float]) -> float:
    """The rank correlation that a steady drift shared by two lists in time order would give on
    its own: each list's rank correlation with its own position, multiplied together.

    Taking it off the measured rank correlation leaves the top line of the partial correlation
    given time. It assumes the drift is steady (a straight line through the ranks); it does not
    see a cycle or a sudden break that both lists share.
    """
    if len(x) != len(y):
        raise ValueError("the two lists must have the same length")
    position = list(range(len(x)))
    return rank_correlation(x, position) * rank_correlation(y, position)


def _power_at(shift: float, draws: int | None, alpha: float) -> float:
    """The chance that a result whose true place is `shift` standard errors above no skill lands
    in the top `alpha`: of a bell curve when `draws` is None, and otherwise of that many no-skill
    draws, the result itself counted among them.

    A test against few draws is weaker than the bell curve says. Its bar is the best few of the
    draws, which is itself a matter of luck, and with 20 draws the result must beat every one.
    """
    if draws is None or draws > MOST_DRAWS:
        return normal_cdf(shift - normal_ppf(1 - alpha))
    allowed = math.floor(alpha * (draws + 1)) - 1  # how many draws may do at least as well
    if allowed < 0:
        return 0.0
    ways, total = [math.comb(draws, count) for count in range(allowed + 1)], 0.0
    for step in range(_GRID):
        luck = -8 + 16 * (step + 0.5) / _GRID  # where the result fell around its true place
        beaten = normal_cdf(-(shift + luck))  # the chance that one draw does at least as well
        total += _NORMAL.pdf(luck) * math.fsum(
            way * beaten ** count * (1 - beaten) ** (draws - count) for count, way in enumerate(ways))
    return total * 16 / _GRID


@functools.lru_cache(maxsize=256)
def _detectable_shift(draws: int | None, alpha: float, power: float) -> float:
    """How many standard errors above no skill a true effect must sit to be found with `power`."""
    if draws is None or draws > MOST_DRAWS:
        return normal_ppf(1 - alpha) + normal_ppf(power)
    low, high = 0.0, 12.0
    if _power_at(high, draws, alpha) < power:
        return math.inf
    for _ in range(24):
        middle = (low + high) / 2
        low, high = (middle, high) if _power_at(middle, draws, alpha) < power else (low, middle)
    return high


def min_detectable_correlation(n: float, power: float = 0.8, alpha: float = 0.05, draws: int | None = None) -> float:
    """The smallest true rank correlation that a one-sided test on `n` independent pairs would
    find with the given power, by the Fisher z approximation.

    With `draws`, the test is the one a gate runs: the correlation must land in the top `alpha`
    of that many no-skill draws. Few draws make a weaker test, so the answer is larger.

    It assumes the pairs are independent. Sticky or overlapping pairs are worth fewer than their
    count, so pass the effective number. It returns 1.0 when `n` is 3 or less: nothing can be
    detected.
    """
    if n <= 3:
        return 1.0
    return math.tanh(_detectable_shift(draws, alpha, power) * math.sqrt(RANK_VARIANCE / (n - 3)))


def power_of_mean_test(mde: float, sd: float, n: int, alpha: float = 0.05, draws: int | None = None) -> float:
    """The power of a one-sided test of a mean against zero: the chance it finds a true mean of
    `mde`, when single results spread by `sd` and there are `n` of them.

    With `draws`, the test is the one a gate runs: the mean must land in the top `alpha` of that
    many no-skill means. Few draws make a weaker test, so the power is lower.

    It assumes independent results and a sample large enough for the mean to follow a bell curve.
    Results that cluster in time are worth fewer than their count, so the true power is lower.
    """
    if n < 1 or mde <= 0:
        return 0.0
    if sd <= 0:
        return 1.0
    return _power_at(mde * math.sqrt(n) / sd, draws, alpha)


def drawdowns(equity: Sequence[float]) -> list[float]:
    """At each point, how far the money stands below its best point so far, as a number at or
    above zero, in the units of `equity`."""
    out, best = [], -math.inf
    for value in equity:
        best = max(best, value)
        out.append(best - value)
    return out


def max_drawdown(equity: Sequence[float]) -> float:
    """The biggest drop from a best point to a later low, in the units of `equity`. 0.0 for a
    list that never falls or is empty."""
    return max(drawdowns(equity), default=0.0)


def sharpe(returns: Sequence[float]) -> float:
    """The Sharpe ratio per observation: the mean result divided by its sample standard
    deviation. It is NOT annualised: it is not scaled to a year, so it can be compared only with
    a ratio taken over the same kind of observation. `nan` when the results never change."""
    spread = stdev(returns)
    return mean(returns) / spread if spread else math.nan


def _moment(values: Sequence[float], power: int) -> float:
    centre = mean(values)
    return math.fsum((value - centre) ** power for value in values) / len(values)


def skew(values: Sequence[float]) -> float:
    """How lopsided the values are: above zero when a few large values sit on the high side.
    It is the third moment over the second to the power 1.5, both taken with the divisor n.
    `nan` when the values never change."""
    spread = _moment(values, 2)
    return _moment(values, 3) / spread ** 1.5 if spread else math.nan


def excess_kurtosis(values: Sequence[float]) -> float:
    """How heavy the tails are, compared with a bell curve: 0 for a bell curve, above zero when
    extreme values are more common. It is the fourth moment over the squared second, minus 3,
    both taken with the divisor n. `nan` when the values never change."""
    spread = _moment(values, 2)
    return _moment(values, 4) / spread ** 2 - 3 if spread else math.nan


def probabilistic_sharpe(sharpe: float, n_obs: int, skew: float, kurtosis: float, benchmark: float = 0.0) -> float:
    """The chance that the true Sharpe ratio is above `benchmark`, given the measured one.

    `sharpe` and `benchmark` are per observation, not annualised. `kurtosis` is the EXCESS
    kurtosis, as `excess_kurtosis` returns it: 0 for a bell curve. Lopsided or heavy-tailed
    results widen the uncertainty, and this allows for both.

    It assumes independent observations. `nan` when there are fewer than two observations or the
    uncertainty cannot be computed.
    """
    spread = 1 - skew * sharpe + (kurtosis + 2) / 4 * sharpe ** 2
    if n_obs < 2 or not spread > 0:
        return math.nan
    return normal_cdf((sharpe - benchmark) * math.sqrt(n_obs - 1) / math.sqrt(spread))


def expected_max_sharpe(n_trials: int, trial_sharpe_variance: float) -> float:
    """The best Sharpe ratio to expect from `n_trials` attempts that all have no skill, when the
    attempts' Sharpe ratios spread with the given variance. 0.0 for a single attempt."""
    if n_trials < 2 or trial_sharpe_variance <= 0:
        return 0.0
    first = normal_ppf(1 - 1 / n_trials)
    second = normal_ppf(1 - 1 / (n_trials * math.e))
    return math.sqrt(trial_sharpe_variance) * ((1 - EULER_MASCHERONI) * first + EULER_MASCHERONI * second)


def deflated_sharpe(
    sharpe: float, n_obs: int, skew: float, kurtosis: float, n_trials: int, trial_sharpe_variance: float
) -> float:
    """The deflated Sharpe ratio: the chance that the true Sharpe ratio is above the best one
    expected from `n_trials` attempts with no skill.

    Trying many ideas and keeping the best makes luck look like skill. This raises the bar to the
    best result luck alone would give, then asks how likely the measured ratio clears it. With one
    trial the bar is zero, and this equals `probabilistic_sharpe` against zero.

    `sharpe` is per observation, not annualised. `kurtosis` is the EXCESS kurtosis (0 for a bell
    curve). `trial_sharpe_variance` is the variance of the per-observation Sharpe ratios across
    the attempts. It assumes the attempts are independent of each other. Attempts that resemble
    each other count for fewer, so the true bar is lower than the one used here: this errs on the
    strict side.
    """
    return probabilistic_sharpe(sharpe, n_obs, skew, kurtosis, expected_max_sharpe(n_trials, trial_sharpe_variance))
