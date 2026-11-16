"""The trading pack's scorecard and its report page.

The scorecard is checked against four trades worked out by hand. The report is checked for what a
newcomer needs: every missing check named, every chart explained, nothing fetched from outside.
"""

from __future__ import annotations

import math
import random
import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

from themis.packs.trading import report, scorecard, stats
from themis.packs.trading.scorecard import LINES, NOT_RUN, Line

#: Four trades, one a month: +30 and +18 on buys, -12 and +9 on sells. Each cost 1 and was, at its
#: best moment, 2 further ahead than the size of its result.
TRADES = [
    {"entry_time": f"2026-0{month}-05T10:00:00", "exit_time": f"2026-0{month}-06T10:00:00", "side": side,
     "net": net, "costs": 1.0, "mfe": abs(net) + 2.0, "mae": -3.0}
    for month, side, net in ((1, "long", 30.0), (2, "short", -12.0), (3, "long", 18.0), (4, "short", 9.0))
]
EVERYTHING = {"baselines": {"always_long": 1010.0, "always_short": 990.0}, "oos_start": "2026-03-01",
              "trial_sharpes": [0.2, 0.1, 0.4], "sensitivity": [1020.0, 990.0]}
SKILL = ["practice_vs_new", "always_long", "always_short", "luck_adjusted_sharpe", "nearby_settings"]


def card(trades: list | None = None, **inputs: object) -> dict[str, Line]:
    lines = scorecard.compute(TRADES if trades is None else trades, start_capital=1000.0, **inputs)
    return {line.id: line for line in lines}


def many(count: int = 150, seed: int = 1) -> list[dict]:
    rng, start = random.Random(seed), datetime(2024, 1, 2, 9, 30)
    return [{"entry_time": start + timedelta(days=3 * index), "exit_time": start + timedelta(days=3 * index + 1),
             "side": "long" if index % 3 else "short", "net": rng.gauss(8, 60), "costs": 2.5} for index in range(count)]


# --- the statistics the scorecard quotes ------------------------------------------------------


def test_mean_and_stdev_agree_with_the_standard_library() -> None:
    values = [3.0, -1.5, 4.25, 0.0, 9.5]
    assert stats.mean(values) == pytest.approx(statistics.fmean(values))
    assert stats.stdev(values) == pytest.approx(statistics.stdev(values))
    with pytest.raises(ValueError):
        stats.mean([])
    with pytest.raises(ValueError):
        stats.stdev([1.0])


def test_drawdowns() -> None:
    assert stats.drawdowns([100, 110, 90, 120, 100]) == [0, 0, 20, 0, 20]
    assert stats.max_drawdown([100, 110, 90, 120, 95]) == 25
    assert stats.max_drawdown([1, 2, 3]) == 0 and stats.max_drawdown([]) == 0.0


def test_the_sharpe_ratio_is_per_observation() -> None:
    assert stats.sharpe([1.0, 2.0, 3.0]) == pytest.approx(2.0)  # a mean of 2 over a spread of 1
    assert stats.sharpe([10.0, 20.0, 30.0]) == pytest.approx(2.0)  # the unit of the results does not matter
    assert math.isnan(stats.sharpe([1.0, 1.0, 1.0]))


def test_skew_and_excess_kurtosis() -> None:
    assert stats.skew([1, 2, 3, 4, 5]) == pytest.approx(0.0)
    assert stats.skew([0, 0, 0, 0, 10]) > 1 and stats.skew([0, 10, 10, 10, 10]) < -1
    assert stats.excess_kurtosis([-1, 1, -1, 1]) == pytest.approx(-2.0)  # two points: the flattest there is
    rng = random.Random(6)
    assert abs(stats.excess_kurtosis([rng.gauss(0, 1) for _ in range(20000)])) < 0.15
    assert math.isnan(stats.skew([2, 2, 2])) and math.isnan(stats.excess_kurtosis([2, 2, 2]))


def test_one_trial_is_the_plain_probabilistic_sharpe_ratio_against_zero() -> None:
    plain = stats.normal_cdf(0.2 * math.sqrt(99) / math.sqrt(1 + 0.5 * 0.2 ** 2))  # a bell curve: no skew, no tails
    assert stats.deflated_sharpe(0.2, 100, 0.0, 0.0, 1, 0.04) == pytest.approx(plain)
    assert stats.deflated_sharpe(0.2, 100, -0.5, 3.0, 1, 0.04) == pytest.approx(
        stats.probabilistic_sharpe(0.2, 100, -0.5, 3.0))


def test_more_trials_lower_the_deflated_sharpe_and_a_larger_sharpe_raises_it() -> None:
    by_trials = [stats.deflated_sharpe(0.2, 100, 0.0, 0.0, trials, 0.01) for trials in (1, 2, 10, 100, 1000)]
    assert by_trials == sorted(by_trials, reverse=True) and len(set(by_trials)) == 5
    by_sharpe = [stats.deflated_sharpe(ratio, 100, 0.0, 0.0, 10, 0.01) for ratio in (0.0, 0.1, 0.2, 0.4)]
    assert by_sharpe == sorted(by_sharpe) and len(set(by_sharpe)) == 4
    assert stats.deflated_sharpe(0.2, 400, 0.0, 0.0, 10, 0.01) > stats.deflated_sharpe(0.2, 100, 0.0, 0.0, 10, 0.01)


def test_lopsided_losses_and_heavy_tails_lower_the_deflated_sharpe() -> None:
    plain = stats.deflated_sharpe(0.3, 100, 0.0, 0.0, 5, 0.01)
    assert stats.deflated_sharpe(0.3, 100, -1.0, 0.0, 5, 0.01) < plain
    assert stats.deflated_sharpe(0.3, 100, 0.0, 6.0, 5, 0.01) < plain
    assert math.isnan(stats.deflated_sharpe(0.3, 1, 0.0, 0.0, 5, 0.01))


def test_the_best_of_many_tries_with_no_skill() -> None:
    assert stats.expected_max_sharpe(1, 1.0) == 0.0
    assert stats.expected_max_sharpe(10, 1.0) == pytest.approx(1.54, abs=0.05)  # the known value for 10 draws
    assert stats.expected_max_sharpe(100, 1.0) == pytest.approx(2.51, abs=0.05)
    assert stats.expected_max_sharpe(10, 4.0) == pytest.approx(2 * stats.expected_max_sharpe(10, 1.0))


# --- the scorecard -----------------------------------------------------------------------------


def test_the_scorecard_is_always_the_same_lines_in_the_same_order() -> None:
    for trades, inputs in ((TRADES, EVERYTHING), (TRADES, {}), ([], {}), (many(), EVERYTHING)):
        lines = scorecard.compute(trades, start_capital=1000.0, **inputs)
        assert [line.id for line in lines] == list(LINES)
        assert [line.group for line in lines] == sorted(line.group for line in lines)
        assert all((line.group, line.label, line.tip) == LINES[line.id] for line in lines)
    by_group = [sum(group == wanted for group, _, _ in LINES.values()) for wanted in range(1, 7)]
    assert by_group == [6, 10, 5, 3, 5, 2] and set(scorecard.GROUPS) == set(range(1, 7))


def test_did_it_make_money_after_costs() -> None:
    lines = card()
    values = {line_id: lines[line_id].value for line_id in list(LINES)[:6]}
    assert values == {"start_money": 1000.0, "end_money": 1045.0, "costs_paid": 4.0, "won_by_winners": 57.0,
                      "lost_by_losers": 12.0, "trades": 4.0}
    assert lines["end_money"].text == "1,045.00 (up 4.5%)"


def test_does_each_trade_pay() -> None:
    lines = card()
    assert lines["avg_trade"].value == pytest.approx(11.25)
    assert lines["profit_factor"].value == pytest.approx(57 / 12)
    assert (lines["win_rate"].value, lines["win_rate_buys"].value, lines["win_rate_sells"].value) == (0.75, 1.0, 0.5)
    assert lines["win_rate_sells"].text == "50.0% (1 of 2 sell trades)"
    assert lines["win_loss_ratio"].value == pytest.approx(19 / 12)  # wins of 30, 18 and 9; one loss of 12
    assert lines["breakeven_win_rate"].value == pytest.approx(12 / (19 + 12))
    assert (lines["biggest_win"].value, lines["biggest_loss"].value) == (30.0, -12.0)
    assert lines["kept_of_best"].value == pytest.approx(45 / 77)  # ahead by 32, 14, 20 and 11 at best


def test_the_break_even_win_rate_really_breaks_even() -> None:
    lines = card()
    rate, win, loss = lines["breakeven_win_rate"].value, 19.0, 12.0
    assert rate * win - (1 - rate) * loss == pytest.approx(0.0)


def test_how_bumpy_was_the_ride() -> None:
    lines = card()  # the money goes 1000, 1030, 1018, 1036, 1045
    assert lines["biggest_drop"].value == 12.0 and lines["biggest_drop"].text.startswith("12.00 (1.2% of the high")
    assert lines["recovery_factor"].value == pytest.approx(45 / 12)
    assert lines["longest_wait"].value == pytest.approx(59.0)  # from the high of 6 January to that of 6 March
    assert lines["losing_streak"].value == 1.0
    spread = math.sqrt((18.75 ** 2 + 23.25 ** 2 + 6.75 ** 2 + 2.25 ** 2) / 3)
    assert lines["sharpe_trade"].value == pytest.approx(11.25 / spread)
    assert "not scaled to a year" in lines["sharpe_trade"].text


def test_was_it_a_few_lucky_trades() -> None:
    lines = card()
    assert lines["top5_share"].value == pytest.approx(30 / 45)  # the best one of four trades
    assert lines["without_best_month"].value == 1015.0 and "2026-01" in lines["without_best_month"].text
    assert 0.0 <= lines["luck_test"].value <= 1.0


def test_the_luck_test_tells_a_kind_order_from_an_unkind_one() -> None:
    def trades(nets: list[float]) -> list[dict]:
        start = datetime(2026, 1, 1)
        return [{"entry_time": start + timedelta(days=index), "exit_time": start + timedelta(days=index, hours=1),
                 "side": "long", "net": net, "costs": 0.0} for index, net in enumerate(nets)]

    unkind = card(trades([-10.0] * 10 + [10.0] * 10))["luck_test"]  # every loss first: the deepest drop there is
    kind = card(trades([10.0, -10.0] * 10))["luck_test"]  # a loss never follows a loss: the shallowest
    assert unkind.value < 0.01 and kind.value == 1.0
    assert card(trades([10.0, -10.0] * 10))["luck_test"] == kind  # dealt from a fixed seed: it repeats


def test_is_it_real_skill() -> None:
    lines = card(**EVERYTHING)
    assert lines["practice_vs_new"].value == pytest.approx(13.5 / 9.0)  # 30 and -12 before March; 18 and 9 after
    assert lines["always_long"].value == 1010.0 and lines["always_long"].text.endswith("ended 35.00 above it)")
    assert lines["always_short"].value == 990.0
    assert 0.0 < lines["luck_adjusted_sharpe"].value < 1.0 and "3 tries" in lines["luck_adjusted_sharpe"].text
    assert lines["nearby_settings"].value == 0.5 and lines["nearby_settings"].text.startswith("1 of 2 nearby")
    assert not any(lines[line_id].not_run for line_id in LINES)


def test_more_tries_lower_the_luck_adjusted_sharpe() -> None:
    few = card(trial_sharpes=[0.2, 0.1, 0.4])["luck_adjusted_sharpe"].value
    lots = card(trial_sharpes=[0.2, 0.1, 0.4] * 10)["luck_adjusted_sharpe"].value
    assert lots < few < card(trial_sharpes=[0.3])["luck_adjusted_sharpe"].value


def test_what_exactly_was_tested() -> None:
    lines = card()
    assert (lines["first_trade"].text, lines["last_trade"].text) == ("2026-01-05", "2026-04-06")
    assert lines["first_trade"].value is None


def test_a_line_whose_inputs_were_not_supplied_is_not_run() -> None:
    lines = card()
    assert [line_id for line_id in LINES if lines[line_id].not_run] == SKILL
    assert all(lines[line_id].text == NOT_RUN and lines[line_id].value is None for line_id in SKILL)
    no_best = card([{name: value for name, value in trade.items() if name != "mfe"} for trade in TRADES])
    assert no_best["kept_of_best"].not_run and no_best["kept_of_best"].text == NOT_RUN
    half = card(baselines={"always_long": 1010.0})
    assert not half["always_long"].not_run and half["always_short"].not_run
    assert card(sensitivity=[])["nearby_settings"].not_run and card(trial_sharpes=[])["luck_adjusted_sharpe"].not_run


def test_a_line_that_cannot_be_computed_says_so_and_is_not_marked_not_run() -> None:
    winners = card([trade for trade in TRADES if trade["net"] > 0])
    for line_id in ("profit_factor", "win_loss_ratio", "breakeven_win_rate", "recovery_factor"):
        assert winners[line_id].value is None and not winners[line_id].not_run and winners[line_id].text != NOT_RUN
    assert winners["biggest_drop"].value == 0.0
    assert card(oos_start="2027-01-01")["practice_vs_new"].value is None  # no trade on new data
    assert "0 on new data" in card(oos_start="2027-01-01")["practice_vs_new"].text


def test_no_trades_is_measured_as_no_trades() -> None:
    lines = card([])
    assert (lines["trades"].value, lines["end_money"].value, lines["costs_paid"].value) == (0.0, 1000.0, 0.0)
    assert lines["avg_trade"].text == "no trades to measure" and lines["first_trade"].text == "no trades to measure"
    assert [line_id for line_id in LINES if lines[line_id].not_run] == SKILL


@dataclass
class Booked:
    entry_time: datetime
    exit_time: datetime
    side: str
    net: float
    costs: float
    mfe: float | None = None


def test_trades_may_be_objects_and_times_may_carry_a_zone() -> None:
    zone = timezone(timedelta(hours=7))
    booked = [Booked(datetime.fromisoformat(trade["entry_time"]).replace(tzinfo=timezone.utc).astimezone(zone),
                     datetime.fromisoformat(trade["exit_time"]).replace(tzinfo=timezone.utc).astimezone(zone),
                     {"long": "buy", "short": "sell"}[trade["side"]], trade["net"], trade["costs"], trade["mfe"])
              for trade in reversed(TRADES)]  # in the wrong order, too: the scorecard sorts by the close
    assert scorecard.compute(booked, start_capital=1000.0, **EVERYTHING) == (
        scorecard.compute(TRADES, start_capital=1000.0, **EVERYTHING))


@pytest.mark.parametrize("change", [{"side": "flat"}, {"net": "a lot"}, {"exit_time": "soon"}, {"costs": None},
                                    {"net": float("nan")}])
def test_a_trade_that_cannot_be_read_is_named(change: dict) -> None:
    with pytest.raises(ValueError, match="trade 2 cannot be read"):
        scorecard.compute([TRADES[0], {**TRADES[1], **change}], start_capital=1000.0)


def test_every_tip_carries_one_hundred_dollar_example_and_no_text_holds_a_dollar_sign() -> None:
    assert all("$100" in tip and tip.count("$") == 1 and tip.endswith(".") for _, _, tip in LINES.values())
    for lines in (card(**EVERYTHING), card(), card([])):
        assert not any("$" in line.text or "$" in line.label for line in lines.values())


def test_the_scorecard_measures_and_issues_no_verdict() -> None:
    words = re.compile(r"\b(pass|passed|fail|failed|verdict|promote|kill|approved|rejected)\b", re.IGNORECASE)
    for line in card(**EVERYTHING).values():
        assert not words.search(line.text) and not words.search(line.label)


def test_the_scorecard_goes_to_a_csv_and_comes_back(tmp_path: Path) -> None:
    lines = scorecard.compute(many(), start_capital=10000.0, baselines={"always_long": 10400.0})
    path = scorecard.write_csv(lines, tmp_path / "results" / "scorecard.csv")
    text = path.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "group,line,label,value,text"
    assert "5,always_short,Always short: sell and stay sold,,NOT RUN" in text.splitlines()
    assert "1,trades,Number of trades,150,150" in text.splitlines()
    assert scorecard.read_csv(path) == lines


def test_a_file_that_is_not_a_scorecard_is_not_read(tmp_path: Path) -> None:
    (tmp_path / "card.csv").write_text("line,value\nalways_long,120\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no column named group, label, text"):
        scorecard.read_csv(tmp_path / "card.csv")
    (tmp_path / "card.csv").write_text("group,line,label,value,text\nfive,a,b,1,c\n", encoding="utf-8")
    with pytest.raises(ValueError, match="row 1 of the scorecard cannot be read"):
        scorecard.read_csv(tmp_path / "card.csv")


# --- the report --------------------------------------------------------------------------------


class Page(HTMLParser):
    """Collects every piece of text and every attribute a reader could be shown."""

    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=True)
        self.texts: list[str] = []
        self.attributes: list[tuple[str, str, str]] = []
        self.tags: list[str] = []
        self.feed(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes += [(tag, name, value or "") for name, value in attrs]

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.texts.append(data.strip())


def page(tmp_path: Path, trades: list | None = None, title: str = "Breakout test", **options: object) -> str:
    trades = many() if trades is None else trades
    inputs = options.pop("inputs", {"baselines": {"always_long": 10400.0}})
    lines = scorecard.compute(trades, start_capital=10000.0, **inputs)
    path = report.write_report(tmp_path / "results" / "report.html", lines, trades, title=title,
                               start_capital=10000.0, **options)
    assert path == tmp_path / "results" / "report.html"
    return path.read_text(encoding="utf-8")


def test_the_page_is_one_file_with_no_script_and_no_outside_asset(tmp_path: Path) -> None:
    text = page(tmp_path)
    found = Page(text)
    assert text.startswith("<!DOCTYPE html>")
    assert not {"script", "link", "img", "iframe", "object", "embed", "audio", "video"} & set(found.tags)
    assert not [name for _, name, _ in found.attributes if name in ("src", "href", "srcset") or name.startswith("on")]
    assert "http" not in text.lower() and "url(" not in text.lower() and "@import" not in text.lower()


def test_the_page_is_laid_out_in_the_agreed_order(tmp_path: Path) -> None:
    text = page(tmp_path, digest_comment="<!-- inputs sha256: 0123abcd -->")
    marks = ["<body>\n<!-- inputs sha256: 0123abcd -->\n<h1>Breakout test</h1>", '<div class="warnings">', "<svg ",
             "<table>", '<p class="audit">']
    places = [text.index(mark) for mark in marks]
    assert places == sorted(places)
    assert text.count("<svg ") == 4 and text.rindex("</svg>") < text.index("<table>")


def test_the_warnings_box_lists_every_line_that_was_not_run(tmp_path: Path) -> None:
    text = page(tmp_path)
    box = text[text.index('<div class="warnings">'):text.index("<h2>Charts</h2>")]
    not_run = ["kept_of_best", *(line_id for line_id in SKILL if line_id != "always_long")]  # no best moments given
    assert re.findall(r"<li>(.*?)</li>", box) == [f"{LINES[line_id][1]}: NOT RUN" for line_id in not_run]
    assert "Always long" not in box
    clean = page(tmp_path, [{**trade, "mfe": 1.0} for trade in many()], inputs={
        "baselines": {"always_long": 10400.0, "always_short": 9600.0}, "oos_start": "2024-09-01",
        "trial_sharpes": [0.1, 0.2], "sensitivity": [10100.0]})
    assert "<li>" not in clean and "Every line of the scorecard was run." in clean


def test_every_chart_is_followed_by_two_plain_sentences_on_how_to_read_it(tmp_path: Path) -> None:
    text = page(tmp_path)
    boxes = re.findall(r'</svg>\n<div class="how-to-read">(.*?)</div>', text)
    assert len(boxes) == 4 == text.count('class="how-to-read"')
    for box in boxes:
        sentences = [part for part in re.split(r"(?<=\.)\s+", box) if part]
        assert len(sentences) == 2 and all(len(sentence.split()) <= 30 for sentence in sentences)
    for name in ("Money over time", "The drop from the best point so far", "Money made each month",
                 "The spread of trade results"):
        assert f'aria-label="{name}"' in text and f"<h3>{name}</h3>" in text


def test_the_table_holds_every_line_in_its_group_with_its_tip(tmp_path: Path) -> None:
    text = page(tmp_path)
    table = text[text.index("<table>"):text.index("</table>")]
    found = Page(table)
    assert [title for _, name, title in found.attributes if name == "title"] == [tip for _, _, tip in LINES.values()]
    headings = [f"{number}. {name}" for number, name in scorecard.GROUPS.items()]
    assert [heading for heading in found.texts if heading in headings] == headings
    for label in (label for _, label, _ in LINES.values()):
        assert label in found.texts
    assert table.count('<tr class="not-run">') == 5 == table.count("<td>NOT RUN</td>")


def test_the_last_line_of_the_page_is_always_the_audit_line(tmp_path: Path) -> None:
    last = page(tmp_path).splitlines()[-1]
    assert last == '<p class="audit">Checked by a second, separate script: NOT RUN</p></body></html>'
    audited = page(tmp_path, audited=True).splitlines()[-1]
    assert audited == '<p class="audit">Checked by a second, separate script: YES</p></body></html>'


def test_all_text_is_escaped_and_the_digest_comment_is_not(tmp_path: Path) -> None:
    text = page(tmp_path, title='A <b>bold</b> & "quoted" test', digest_comment="<!-- a < b -->")
    assert "<b>bold</b>" not in text and "A &lt;b&gt;bold&lt;/b&gt; &amp; &quot;quoted&quot; test" in text
    assert "<!-- a < b -->" in text
    assert "A <b>bold</b> & \"quoted\" test" in Page(text).texts


def test_no_text_on_the_page_holds_two_dollar_signs(tmp_path: Path) -> None:
    found = Page(page(tmp_path))
    assert max(text.count("$") for text in found.texts) == 0
    assert max(value.count("$") for _, _, value in found.attributes) == 1  # a tip's one example


def test_money_is_framed_as_a_stake(tmp_path: Path) -> None:
    text = page(tmp_path)
    stake = text[text.index('<div class="stake">'):text.index('<div class="warnings">')]
    assert [name for name in Page(stake).texts if not name[0].isdigit()] == [
        "Starting money", "Ending money", "Biggest drop", "Costs paid"]
    assert "10,000.00" in stake and "375.00" in stake  # 150 trades at 2.50 each


def test_the_page_is_written_in_everyday_words(tmp_path: Path) -> None:
    shown = " ".join(Page(page(tmp_path)).texts).lower()
    for jargon in ("drawdown", "equity", "p&l", "pnl", "in-sample", "out-of-sample", "mfe", "mae", "expectancy"):
        assert jargon not in shown, jargon


def test_the_same_inputs_give_the_same_page(tmp_path: Path) -> None:
    assert page(tmp_path / "a") == page(tmp_path / "b")


def test_a_page_with_no_trades_and_a_page_with_one_trade_are_still_pages(tmp_path: Path) -> None:
    empty = page(tmp_path, [])
    assert empty.count("No trades to draw.") == 4 and empty.count('class="how-to-read"') == 4
    one = page(tmp_path, TRADES[:1])
    assert one.count("<svg ") == 4 and "nan" not in one.lower() and "inf" not in Page(one).texts
    flat = [{**trade, "net": 0.0} for trade in TRADES]  # trades that made nothing, on a stake that is no round number
    path = report.write_report(tmp_path / "flat.html", scorecard.compute(flat, start_capital=7300.0), flat,
                               title="Flat", start_capital=7300.0)
    assert path.read_text(encoding="utf-8").count("<svg ") == 4


def test_a_long_history_stays_a_small_page(tmp_path: Path) -> None:
    text = page(tmp_path, many(6000, seed=2))
    assert len(text.encode("utf-8")) < 150_000
    assert "nan" not in text.lower()
