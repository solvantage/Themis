"""The strategy scorecard: one fixed list of measurements, read from the standard trade table.

`compute` takes the closed trades and returns the scorecard's lines, in six groups. Each line has
a number, how that number reads to a person, and a one-sentence tip with a `$100` example. A line
whose inputs were not supplied is marked NOT RUN: it is shown, never dropped, so a missing check
is seen as missing.

The scorecard measures. It issues no verdict: that is a gate function's work.

Money is written as plain numbers, in whatever currency the trade table uses. The equity curve is
counted on finished trades, in the order they closed.
"""

from __future__ import annotations

import csv
import io
import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from themis.packs.trading import stats

NOT_RUN = "NOT RUN"
COLUMNS = ("group", "line", "label", "value", "text")
ORDERINGS = 1000  # how many random orders the luck test deals
GROUPS = {
    1: "Did it make money, after costs?",
    2: "Does each trade pay?",
    3: "How bumpy was the ride?",
    4: "Was it a few lucky trades?",
    5: "Is it real skill?",
    6: "What exactly was tested?",
}
#: line id -> (group, label, tip). The order here is the order of the scorecard.
LINES: dict[str, tuple[int, str, str]] = {
    "start_money": (1, "Money at the start", "The money the test began with: think of it as a $100 stake, and read "
                    "every other line as what became of it."),
    "end_money": (1, "Money at the end", "The money left after every trade and every cost: a $100 stake that ends "
                  "at 112 made 12."),
    "costs_paid": (1, "Costs paid", "What the trading itself cost in fees and spread: on a $100 stake, costs of 3 "
                   "mean the trades had to make 3 just to stand still."),
    "won_by_winners": (1, "Money won by winners", "Everything made by the trades that ended ahead, added up: on a "
                       "$100 stake, the winners might make 30 in total."),
    "lost_by_losers": (1, "Money lost by losers", "Everything lost by the trades that ended behind, added up: on a "
                       "$100 stake, the losers might give back 18 in total."),
    "trades": (1, "Number of trades", "How many trades were finished: a $100 stake traded 200 times tells you far "
               "more than one traded 10 times."),
    "avg_trade": (2, "Average money per trade", "What one trade made on average, after costs: on a $100 stake, "
                  "0.50 a trade over 40 trades adds up to 20."),
    "profit_factor": (2, "Profit factor", "Money won divided by money lost: a $100 stake that won 30 and lost 20 "
                      "has a profit factor of 1.5, and anything below 1 lost money."),
    "win_rate": (2, "How often it wins", "The share of trades that ended ahead: a $100 stake can grow with few "
                 "wins when each win is large, so read this beside the next lines."),
    "win_rate_buys": (2, "How often it wins on buys", "The share of buy trades (bets that the price will rise) "
                      "that ended ahead: if a $100 stake only grows on buys, the idea may just be riding a "
                      "rising market."),
    "win_rate_sells": (2, "How often it wins on sells", "The share of sell trades (bets that the price will fall) "
                       "that ended ahead: if a $100 stake only grows on sells, the idea may just be riding a "
                       "falling market."),
    "win_loss_ratio": (2, "Normal win against normal loss", "The average win divided by the average loss: on a "
                       "$100 stake, wins of 3 against losses of 2 give 1.5."),
    "breakeven_win_rate": (2, "Win rate needed to break even", "How often it must win just to stand still, given "
                           "its average win and loss: on a $100 stake, wins of 3 and losses of 2 need a win 40% "
                           "of the time."),
    "biggest_win": (2, "Biggest win", "The single best trade: if a $100 stake made 12 and one trade made 10 of it, "
                    "the result leans on that one trade."),
    "biggest_loss": (2, "Biggest loss", "The single worst trade: a $100 stake that can lose 15 in one trade can be "
                     "hurt badly by a few of them."),
    "kept_of_best": (2, "How much of the best moment was kept", "Of the most each trade was ahead at its best "
                     "moment, how much was still there at the close: a trade on a $100 stake that was 4 ahead "
                     "and closed 1 ahead kept a quarter."),
    "biggest_drop": (3, "Biggest drop, on finished trades", "The largest fall from a high point to a later low: a "
                     "$100 stake that climbed to 120 and then fell to 96 dropped 24."),
    "recovery_factor": (3, "Recovery factor", "Money made divided by the biggest drop: a $100 stake that made 30 "
                        "and at worst dropped 10 has a recovery factor of 3."),
    "longest_wait": (3, "Longest wait for a new high", "The longest time spent below an earlier high: a $100 "
                     "stake that reached 110 in March and next beat it in September waited six months."),
    "losing_streak": (3, "Most losses in a row", "The longest run of losing trades: a $100 stake has to live "
                      "through this run without the trader giving up."),
    "sharpe_trade": (3, "Sharpe ratio per trade", "The average trade divided by how much trades vary, not scaled "
                     "to a year: on a $100 stake, 0.50 a trade with a spread of 5 gives 0.1."),
    "top5_share": (4, "Share of the money from the best 5% of trades", "How much of the money came from the best "
                   "one trade in twenty: if a $100 stake made 20 and 15 of it came from those few, luck may "
                   "explain it."),
    "without_best_month": (4, "Money without the best month", "The ending money if the best calendar month had "
                           "never happened: a $100 stake that ends at 120, but at 101 without its best month, "
                           "depends on that month."),
    "luck_test": (4, "Luck test: the trades dealt again in random order", "The same trades in a random order, "
                  "many times over: if a $100 stake's real drop was 10 and most orders drop more, the real "
                  "order was a kind one."),
    "practice_vs_new": (5, "Practice data against new data", "The average trade on the data the idea was built "
                        "on, against data it had never seen: on a $100 stake, 0.50 a trade in practice and 0.10 "
                        "on new data is a warning."),
    "always_long": (5, "Always long: buy and hold", "What buying at the start and holding to the end would have "
                    "ended with: if a $100 stake ends at 115 this way, the strategy must beat 115 to add "
                    "anything."),
    "always_short": (5, "Always short: sell and stay sold", "What selling at the start and staying sold to the end "
                     "would have ended with: if a $100 stake ends at 85 this way, a strategy that only sells "
                     "must beat 85."),
    "luck_adjusted_sharpe": (5, "Luck-adjusted Sharpe ratio", "The chance the result beats what luck alone gives "
                             "the best of every idea tried: the best of 50 tries on a $100 stake looks good by "
                             "luck alone."),
    "nearby_settings": (5, "Nearby settings still work", "Whether slightly different settings also made money: if "
                        "a $100 stake grows at one setting and shrinks at its neighbours, the setting was fitted "
                        "to the past."),
    "first_trade": (6, "First trade date", "The day the first trade was opened: a $100 stake tested over one calm "
                    "year says little about a stormy one."),
    "last_trade": (6, "Last trade date", "The day the last trade was closed: what happened to a $100 stake after "
                   "this date is not in the test."),
}
_SIDES = {"long": "buy", "buy": "buy", "short": "sell", "sell": "sell"}


@dataclass(frozen=True)
class Line:
    """One line of the scorecard."""

    id: str
    group: int
    label: str
    value: float | None
    text: str
    not_run: bool = False
    tip: str = ""


@dataclass(frozen=True)
class Row:
    """One closed trade, as the scorecard reads it."""

    entry: datetime
    exit: datetime
    side: str  # "buy" or "sell"
    net: float
    costs: float
    mfe: float | None = None


def when(value: Any) -> datetime:
    """A date-time from a datetime, a date or ISO text. A time zone is turned to UTC and dropped,
    so every time can be compared with every other."""
    if isinstance(value, datetime):
        found = value
    elif isinstance(value, date):
        found = datetime(value.year, value.month, value.day)
    else:
        found = datetime.fromisoformat(str(value).strip())
    return found.astimezone(timezone.utc).replace(tzinfo=None) if found.tzinfo else found


def _field(trade: Any, name: str) -> Any:
    return trade.get(name) if isinstance(trade, Mapping) else getattr(trade, name, None)


def rows(trades: Iterable[Any]) -> list[Row]:
    """The trades as rows, in the order they closed. Raises ValueError, naming the trade, when
    one cannot be read."""
    found = []
    for number, trade in enumerate(trades, start=1):
        try:
            side = _SIDES[str(_field(trade, "side")).strip().lower()]
            best = _field(trade, "mfe")
            row = Row(when(_field(trade, "entry_time")), when(_field(trade, "exit_time")), side,
                      float(_field(trade, "net")), float(_field(trade, "costs")),
                      None if best is None or best == "" else float(best))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"trade {number} cannot be read: it needs entry_time, exit_time, side (long or "
                             f"short), net and costs ({error.__class__.__name__}: {error})") from None
        if not all(math.isfinite(value) for value in (row.net, row.costs)):
            raise ValueError(f"trade {number} cannot be read: net and costs must be numbers")
        found.append(row)
    return sorted(found, key=lambda row: row.exit)


def equity(nets: Iterable[float], start_capital: float) -> list[float]:
    """The money after each finished trade, starting with the starting money."""
    out = [float(start_capital)]
    for net in nets:
        out.append(out[-1] + net)
    return out


def money(value: float) -> str:
    return f"{value:,.2f}"


def _share(value: float) -> str:
    return f"{value:.1%}"


def _line(line_id: str, value: float | None, text: str, not_run: bool = False) -> Line:
    group, label, tip = LINES[line_id]
    return Line(line_id, group, label, None if value is None else float(value), text, not_run, tip)


def _missing(line_id: str) -> Line:
    return _line(line_id, None, NOT_RUN, not_run=True)


def _win_rate(line_id: str, found: Sequence[Row], what: str) -> Line:
    if not found:
        return _line(line_id, None, f"no {what} to measure")
    wins = sum(row.net > 0 for row in found)
    return _line(line_id, wins / len(found), f"{_share(wins / len(found))} ({wins} of {len(found)} {what})")


def _longest_wait(found: Sequence[Row], start_capital: float) -> float:
    """The longest stretch without a new high, in days, the stretch to the end of the test included."""
    best, since, longest, total = start_capital, min(row.entry for row in found), 0.0, start_capital
    for row in found:
        total += row.net
        if total > best:
            longest, best, since = max(longest, (row.exit - since).total_seconds()), total, row.exit
    return max(longest, (found[-1].exit - since).total_seconds()) / 86400


def _losing_streak(found: Sequence[Row]) -> int:
    longest = run = 0
    for row in found:
        run = run + 1 if row.net < 0 else 0
        longest = max(longest, run)
    return longest


def _luck_test(nets: list[float], start_capital: float) -> float:
    """The share of random orders of the same trades whose biggest drop is at least the real one."""
    real = stats.max_drawdown(equity(nets, start_capital))
    rng, dealt, deeper = random.Random(0), list(nets), 0
    for _ in range(ORDERINGS):
        rng.shuffle(dealt)
        deeper += stats.max_drawdown(equity(dealt, start_capital)) >= real - 1e-9
    return deeper / ORDERINGS


def _each_trade(found: Sequence[Row], nets: list[float]) -> list[Line]:
    wins, losses = [net for net in nets if net > 0], [-net for net in nets if net < 0]
    won, lost = math.fsum(wins), math.fsum(losses)
    out = [
        _line("avg_trade", stats.mean(nets), f"{money(stats.mean(nets))} a trade"),
        _line("profit_factor", won / lost, f"{won / lost:.2f}") if lost else
        _line("profit_factor", None, "no trade lost money, so it cannot be computed"),
        _win_rate("win_rate", found, "trades"),
        _win_rate("win_rate_buys", [row for row in found if row.side == "buy"], "buy trades"),
        _win_rate("win_rate_sells", [row for row in found if row.side == "sell"], "sell trades"),
    ]
    if wins and losses:
        win, loss = stats.mean(wins), stats.mean(losses)
        out += [
            _line("win_loss_ratio", win / loss, f"{win / loss:.2f} to 1 (a normal win is {money(win)}, a normal "
                                                 f"loss is {money(loss)})"),
            _line("breakeven_win_rate", loss / (win + loss), f"{_share(loss / (win + loss))} of trades"),
        ]
    else:
        out += [_line(name, None, "it needs at least one win and one loss") for name in
                ("win_loss_ratio", "breakeven_win_rate")]
    out += [_line("biggest_win", max(nets), money(max(nets))), _line("biggest_loss", min(nets), money(min(nets)))]
    best = [row.mfe for row in found]
    if any(value is None for value in best):
        return [*out, _missing("kept_of_best")]
    ahead = math.fsum(max(value, 0.0) for value in best)
    return [*out, _line("kept_of_best", math.fsum(nets) / ahead, f"{_share(math.fsum(nets) / ahead)} of the "
                        f"{money(ahead)} the trades were ahead at their best") if ahead else
            _line("kept_of_best", None, "no trade was ever ahead")]


def _ride(found: Sequence[Row], nets: list[float], start: float) -> list[Line]:
    curve = equity(nets, start)
    drops = stats.drawdowns(curve)
    drop = max(drops)
    high = curve[drops.index(drop)] + drop
    made, wait = curve[-1] - start, _longest_wait(found, start)
    ratio = stats.sharpe(nets) if len(nets) > 1 else math.nan
    return [
        _line("biggest_drop", drop, f"{money(drop)} ({_share(drop / high)} of the high before it)" if high > 0
              else money(drop)),
        _line("recovery_factor", made / drop, f"{made / drop:.2f}") if drop else
        _line("recovery_factor", None, "the money never dropped, so it cannot be computed"),
        _line("longest_wait", wait, f"{wait:,.0f} days"),
        _line("losing_streak", _losing_streak(found), f"{_losing_streak(found)} trades"),
        _line("sharpe_trade", ratio, f"{ratio:.3f} per trade, not scaled to a year") if math.isfinite(ratio) else
        _line("sharpe_trade", None, "it needs at least two trades with different results"),
    ]


def _luck(found: Sequence[Row], nets: list[float], start: float) -> list[Line]:
    total, few = math.fsum(nets), max(1, math.ceil(len(nets) * 0.05))
    top = math.fsum(sorted(nets, reverse=True)[:few])
    months: dict[str, float] = {}
    for row in found:
        months[row.exit.strftime("%Y-%m")] = months.get(row.exit.strftime("%Y-%m"), 0.0) + row.net
    best = max(months, key=months.__getitem__)
    dealt = _luck_test(nets, start) if len(nets) > 1 else None
    return [
        _line("top5_share", top / total, f"{_share(top / total)} came from the best {few} of {len(nets)} trades"
              + (" (the other trades lost money between them)" if top > total else ""))
        if total > 0 else _line("top5_share", None, "the trades made no money in total, so there is no share"),
        _line("without_best_month", start + total - months[best],
              f"{money(start + total - months[best])} (the best month, {best}, made {money(months[best])})"),
        _line("luck_test", dealt, f"in {_share(dealt)} of {ORDERINGS:,} random orders the biggest drop was at "
                                  "least as deep as the real one") if dealt is not None else
        _line("luck_test", None, "it needs at least two trades"),
    ]


def _practice(found: Sequence[Row], oos_start: Any) -> Line:
    if oos_start is None:
        return _missing("practice_vs_new")
    split = when(oos_start)
    old = [row.net for row in found if row.entry < split]
    new = [row.net for row in found if row.entry >= split]
    if not old or not new:
        return _line("practice_vs_new", None, f"{len(old)} trades on practice data and {len(new)} on new data: "
                                              "both are needed")
    before, after = stats.mean(old), stats.mean(new)
    text = (f"practice data: {money(before)} a trade over {len(old)} trades; new data: {money(after)} a trade "
            f"over {len(new)} trades")
    if before <= 0:
        return _line("practice_vs_new", None, text)
    return _line("practice_vs_new", after / before, f"{text} ({_share(after / before)} of practice)")


def _baseline(line_id: str, baselines: Mapping[str, Any] | None, end: float) -> Line:
    value = (baselines or {}).get(line_id)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return _missing(line_id)
    gap = end - value
    return _line(line_id, value, f"{money(value)} (the strategy ended {money(abs(gap))} "
                                 f"{'above' if gap >= 0 else 'below'} it)")


def _skill(found: Sequence[Row], nets: list[float], start: float, baselines: Mapping[str, Any] | None,
           oos_start: Any, trial_sharpes: Sequence[float] | None, sensitivity: Sequence[float] | None) -> list[Line]:
    end = start + math.fsum(nets)
    out = [_practice(found, oos_start), _baseline("always_long", baselines, end),
           _baseline("always_short", baselines, end)]
    if not trial_sharpes:
        out.append(_missing("luck_adjusted_sharpe"))
    else:
        ratio = stats.sharpe(nets) if len(nets) > 1 else math.nan
        spread = stats.stdev(trial_sharpes) ** 2 if len(trial_sharpes) > 1 else 0.0
        chance = math.nan if not math.isfinite(ratio) else stats.deflated_sharpe(
            ratio, len(nets), stats.skew(nets), stats.excess_kurtosis(nets), len(trial_sharpes), spread)
        out.append(_line("luck_adjusted_sharpe", chance, f"a {_share(chance)} chance that the result beats what "
                         f"luck alone gives the best of {len(trial_sharpes)} tries") if math.isfinite(chance) else
                   _line("luck_adjusted_sharpe", None, "it needs at least two trades with different results"))
    if not sensitivity:
        return [*out, _missing("nearby_settings")]
    held = sum(value > start for value in sensitivity)
    return [*out, _line("nearby_settings", held / len(sensitivity),
                        f"{held} of {len(sensitivity)} nearby settings ended above the starting money (worst "
                        f"{money(min(sensitivity))}, best {money(max(sensitivity))})")]


def compute(trades: Iterable[Any], *, start_capital: float, baselines: Mapping[str, Any] | None = None,
            oos_start: Any = None, trial_sharpes: Sequence[float] | None = None,
            sensitivity: Sequence[float] | None = None) -> list[Line]:
    """The scorecard's lines for these closed trades, always the same lines in the same order.

    `trades` are objects or tables with `entry_time`, `exit_time`, `side`, `net`, `costs` and,
    when the engine gives them, `mfe` and `mae`. `baselines` holds the ending money of
    `always_long` and `always_short`; `oos_start` is the first moment of the data the idea had
    never seen; `trial_sharpes` holds the per-trade Sharpe ratio of every idea tried, this one
    included; `sensitivity` holds the ending money of neighbouring settings. A line whose input
    is left out is marked NOT RUN.
    """
    found, start = rows(trades), float(start_capital)
    nets = [row.net for row in found]
    wins, losses = math.fsum(net for net in nets if net > 0), math.fsum(-net for net in nets if net < 0)
    end = start + math.fsum(nets)
    change = "" if start <= 0 or end == start else (
        f" ({'up' if end > start else 'down'} {_share(abs(end - start) / start)})")
    out = [
        _line("start_money", start, money(start)),
        _line("end_money", end, money(end) + change),
        _line("costs_paid", math.fsum(row.costs for row in found), money(math.fsum(row.costs for row in found))),
        _line("won_by_winners", wins, money(wins)),
        _line("lost_by_losers", losses, money(losses)),
        _line("trades", len(found), f"{len(found):,}"),
    ]
    out += _skill(found, nets, start, baselines, oos_start, trial_sharpes, sensitivity)
    if found:
        out += _each_trade(found, nets) + _ride(found, nets, start) + _luck(found, nets, start)
        out += [_line("first_trade", None, min(row.entry for row in found).date().isoformat()),
                _line("last_trade", None, max(row.exit for row in found).date().isoformat())]
    done = {line.id: line for line in out}
    return [done.get(line_id) or _line(line_id, None, "no trades to measure") for line_id in LINES]


def _cell(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if value == int(value) and abs(value) < 1e15 else repr(value)


def to_csv(lines: Iterable[Line]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for line in lines:
        writer.writerow([line.group, line.id, line.label, _cell(line.value), line.text])
    return out.getvalue()


def parse_csv(text: str) -> list[Line]:
    """The lines of a scorecard written by `to_csv`. Raises ValueError when the text is not one."""
    reader = csv.DictReader(io.StringIO(text))
    missing = [name for name in COLUMNS if name not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"the scorecard has no column named {', '.join(missing)}")
    out = []
    for number, row in enumerate(reader, start=1):
        try:
            value = None if not (row["value"] or "").strip() else float(row["value"])
            group = int(row["group"])
        except (TypeError, ValueError):
            raise ValueError(f"row {number} of the scorecard cannot be read") from None
        text_shown = (row["text"] or "").strip()
        out.append(Line(row["line"], group, row["label"], value, text_shown, text_shown == NOT_RUN,
                        LINES.get(row["line"], (0, "", ""))[2]))
    return out


def write_csv(lines: Iterable[Line], path: str | Path) -> Path:
    """Write the scorecard as a CSV with the columns group, line, label, value and text."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_csv(lines), encoding="utf-8")
    return target


def read_csv(path: str | Path) -> list[Line]:
    """Read a scorecard written by `write_csv`. The tips come back from this module's own table."""
    return parse_csv(Path(path).read_text(encoding="utf-8"))
