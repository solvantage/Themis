"""The standard trade table: what it accepts, what it refuses and why, and the adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from themis.packs.trading import trades
from themis.packs.trading.trades import Trade

HEADER = "entry_time,exit_time,side,size,entry_price,exit_price,costs,net"
GOOD = "2026-01-05T09:30:00,2026-01-05T10:30:00,long,2,100.5,101.5,0.2,1.8"


def table(tmp_path: Path, *rows: str, header: str = HEADER) -> Path:
    path = tmp_path / "trades.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def a_trade(**changes: object) -> Trade:
    fields = {"entry_time": datetime(2026, 1, 5, 9, 30), "exit_time": datetime(2026, 1, 5, 10, 30), "side": "long",
              "size": 2.0, "entry_price": 100.5, "exit_price": 101.5, "costs": 0.2, "net": 1.8}
    return Trade(**{**fields, **changes})


# --- reading -----------------------------------------------------------------------------------


def test_a_standard_table_is_read_one_trade_for_each_row(tmp_path: Path) -> None:
    short = "2026-01-06T09:30:00+00:00,2026-01-07T09:30:00+00:00,short,1,101,99.5,0.1,1.4"
    found = trades.read_trades(table(tmp_path, GOOD, short))
    assert found[0] == a_trade()
    assert (found[1].side, found[1].size, found[1].net) == ("short", 1.0, 1.4)
    assert found[1].entry_time == datetime(2026, 1, 6, 9, 30, tzinfo=timezone.utc)
    assert (found[0].bar_low, found[0].bar_high, found[0].mfe, found[0].mae) == (None, None, None, None)


def test_the_optional_columns_are_read_when_present_and_may_be_left_empty(tmp_path: Path) -> None:
    header = HEADER + ",bar_low,bar_high,mfe,mae"
    found = trades.read_trades(table(tmp_path, GOOD + ",100,101,2.5,-0.75", GOOD + ",,,,", header=header))
    assert (found[0].bar_low, found[0].bar_high, found[0].mfe, found[0].mae) == (100.0, 101.0, 2.5, -0.75)
    assert (found[1].bar_low, found[1].bar_high, found[1].mfe, found[1].mae) == (None, None, None, None)


def test_columns_the_standard_does_not_have_blank_lines_and_a_header_only_table_are_fine(tmp_path: Path) -> None:
    path = tmp_path / "trades.csv"
    path.write_text(f"\ufeffsymbol, {HEADER}\n\nabc,{GOOD}\n\n", encoding="utf-8")
    assert trades.read_trades(path) == [a_trade()]
    assert trades.read_trades(table(tmp_path)) == []


def test_a_side_is_read_whatever_its_capitals(tmp_path: Path) -> None:
    assert trades.read_trades(table(tmp_path, GOOD.replace("long", " Long ")))[0].side == "long"


@pytest.mark.parametrize(
    ("row", "said"),
    [
        (GOOD.replace(",2,", ",two,"), "row 2: size is not a number: 'two'"),
        (GOOD.replace(",1.8", ",nan"), "row 2: net is not a number: 'nan'"),
        (GOOD.replace(",1.8", ",\"1,800\""), "row 2: net is not a number: '1,800'"),
        (GOOD.replace("long", "buy"), "row 2: side is neither long nor short: 'buy'"),
        (GOOD.replace("T10:30", "T08:30"),
         "row 2: the exit (2026-01-05T08:30:00) is before the entry (2026-01-05T09:30:00)"),
        (GOOD.replace(",0.2,", ",-0.2,"), "row 2: costs must be 0 or more, and is -0.2"),
        (GOOD.replace(",2,", ",0,"), "row 2: size must be above 0, and is 0"),
        (GOOD.replace(",100.5,", ",-100.5,"), "row 2: entry_price must be above 0, and is -100.5"),
        (GOOD.replace(",101.5,", ",0,"), "row 2: exit_price must be above 0, and is 0"),
        (GOOD.replace("2026-01-05T09:30:00", "05/01/2026 09:30"), "row 2: entry_time is not an ISO date-time"),
        (GOOD.replace(",0.2,", ",,"), "row 2: costs is empty"),
        (GOOD + ",7", "row 2: it has 9 values, and the header has 8 columns"),
        (GOOD.replace("T10:30:00", "T10:30:00+00:00"), "row 2: entry_time and exit_time must both carry a time zone"),
    ],
)
def test_a_row_that_breaks_the_standard_is_named_with_its_reason(tmp_path: Path, row: str, said: str) -> None:
    with pytest.raises(ValueError) as caught:
        trades.read_trades(table(tmp_path, GOOD, row, GOOD))
    assert said in str(caught.value)


def test_the_first_bad_row_is_the_one_named(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="^row 1: side is neither long nor short"):
        trades.read_trades(table(tmp_path, GOOD.replace("long", "flat"), GOOD + ",7"))


@pytest.mark.parametrize("column", trades.REQUIRED)
def test_a_missing_required_column_is_named(tmp_path: Path, column: str) -> None:
    kept = [index for index, name in enumerate(HEADER.split(",")) if name != column]
    header = ",".join(HEADER.split(",")[index] for index in kept)
    row = ",".join(GOOD.split(",")[index] for index in kept)
    with pytest.raises(ValueError) as caught:
        trades.read_trades(table(tmp_path, row, header=header))
    assert str(caught.value) == f"row 0 (the header): there is no column named {column}"


def test_an_empty_file_a_repeated_column_and_bytes_that_are_not_text_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "trades.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="the table is empty"):
        trades.read_trades(path)
    with pytest.raises(ValueError, match="the column net is named twice"):
        trades.read_trades(table(tmp_path, GOOD + ",1.8", header=HEADER + ",net"))
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ValueError, match="not UTF-8 text"):
        trades.read_trades(path)


def test_half_a_bar_and_a_bar_upside_down_are_refused(tmp_path: Path) -> None:
    header = HEADER + ",bar_low,bar_high"
    with pytest.raises(ValueError, match="row 1: bar_low and bar_high come together"):
        trades.read_trades(table(tmp_path, GOOD + ",100,", header=header))
    with pytest.raises(ValueError, match=r"row 1: bar_low \(101\) is above bar_high \(100\)"):
        trades.read_trades(table(tmp_path, GOOD + ",101,100", header=header))


def test_a_trade_that_breaks_the_standard_cannot_be_built_by_hand_either() -> None:
    with pytest.raises(ValueError, match="side is neither long nor short"):
        a_trade(side="flat")
    with pytest.raises(ValueError, match="size must be above 0"):
        a_trade(size=float("nan"))
    with pytest.raises(ValueError, match="costs must be 0 or more"):
        a_trade(costs=-1.0)
    assert a_trade(exit_time=datetime(2026, 1, 5, 9, 30)).exit_time == a_trade().entry_time  # same moment: allowed


# --- the adapter -------------------------------------------------------------------------------

EXPORT = {"Open Time": "2026-01-05 09:30:00", "Close Time": "2026-01-05 10:30:00", "Type": "LONG", "Volume": "2",
          "Open Price": "100.5", "Close Price": "101.5", "Fees": "0.2", "Profit": "1.8", "Comment": "first signal"}
MAPPING = {"entry_time": "Open Time", "exit_time": "Close Time", "side": "Type", "size": "Volume",
           "entry_price": "Open Price", "exit_price": "Close Price", "costs": "Fees", "net": "Profit"}


def test_rows_with_other_column_names_become_standard_trades() -> None:
    assert trades.from_rows([EXPORT], MAPPING) == [a_trade()]


def test_the_mapping_names_only_the_columns_that_differ() -> None:
    row = {"entry_time": "2026-01-05T09:30:00", "exit_time": "2026-01-05T10:30:00", "side": "long", "size": 2,
           "entry_price": 100.5, "exit_price": 101.5, "costs": 0.2, "pnl": 1.8, "low": 100, "high": 101}
    found = trades.from_rows([row], {"net": "pnl", "bar_low": "low", "bar_high": "high"})
    assert found == [a_trade(bar_low=100.0, bar_high=101.0)]


def test_rows_already_in_the_standard_need_no_mapping_and_may_hold_real_values() -> None:
    row = {"entry_time": datetime(2026, 1, 5, 9, 30), "exit_time": datetime(2026, 1, 5, 10, 30), "side": "long",
           "size": 2, "entry_price": 100.5, "exit_price": 101.5, "costs": 0.2, "net": 1.8, "mfe": None}
    assert trades.from_rows([row]) == [a_trade()]
    assert trades.from_rows([]) == []


def test_a_bad_row_from_the_adapter_names_its_row_and_their_column() -> None:
    with pytest.raises(ValueError) as caught:
        trades.from_rows([EXPORT, {**EXPORT, "Profit": "n/a"}], MAPPING)
    assert str(caught.value) == "row 2: net (the column Profit) is not a number: 'n/a'"
    with pytest.raises(ValueError, match="^row 1: side is neither long nor short: 'buy'$"):
        trades.from_rows([{**EXPORT, "Type": "buy"}], MAPPING)
    with pytest.raises(ValueError, match=r"^row 1: size \(the column Volume\) is not a number: 'True'$"):
        trades.from_rows([{**EXPORT, "Volume": True}], MAPPING)


def test_a_row_without_a_required_column_names_the_column_it_looked_for() -> None:
    without = {key: value for key, value in EXPORT.items() if key != "Fees"}
    with pytest.raises(ValueError, match="^row 2: there is no column named Fees$"):
        trades.from_rows([EXPORT, without], MAPPING)
    with pytest.raises(ValueError, match="^row 1: there is no column named net$"):
        trades.from_rows([EXPORT], {key: value for key, value in MAPPING.items() if key != "net"})


def test_a_mapping_for_a_column_the_standard_does_not_have_is_refused() -> None:
    with pytest.raises(ValueError, match="the mapping names profit, which the standard trade table does not have"):
        trades.from_rows([EXPORT], {**MAPPING, "profit": "Profit"})


# --- writing -----------------------------------------------------------------------------------


def test_what_is_written_reads_back_the_same(tmp_path: Path) -> None:
    booked = [
        a_trade(bar_low=100.0, bar_high=101.0, mfe=2.5),
        a_trade(side="short", entry_time=datetime(2026, 1, 6, 9, 30, tzinfo=timezone.utc),
                exit_time=datetime(2026, 1, 7, 9, 30, tzinfo=timezone.utc), net=-0.1 - 0.2),
    ]
    path = tmp_path / "study" / "results" / "trades.csv"
    trades.write_trades(booked, path)
    assert trades.read_trades(path) == booked
    assert path.read_text(encoding="utf-8").splitlines()[0] == HEADER + ",bar_low,bar_high,mfe"


def test_a_table_with_no_optional_values_holds_only_the_required_columns(tmp_path: Path) -> None:
    path = tmp_path / "trades.csv"
    trades.write_trades([a_trade()], path)
    row = "2026-01-05T09:30:00,2026-01-05T10:30:00,long,2.0,100.5,101.5,0.2,1.8"
    assert path.read_text(encoding="utf-8") == f"{HEADER}\n{row}\n"
    trades.write_trades([], path)
    assert trades.read_trades(path) == []


# --- fills on the tape -------------------------------------------------------------------------


def test_a_fill_outside_its_bar_is_found_with_its_row_number() -> None:
    booked = [
        a_trade(bar_low=100.0, bar_high=101.0),                     # 1: inside
        a_trade(entry_price=101.5, bar_low=100.0, bar_high=101.0),  # 2: above the high
        a_trade(entry_price=101.0, bar_low=100.0, bar_high=101.0),  # 3: at the high, which did trade
        a_trade(entry_price=100.0, bar_low=100.0, bar_high=101.0),  # 4: at the low, which did trade
        a_trade(entry_price=99.99, bar_low=100.0, bar_high=101.0),  # 5: below the low
        a_trade(entry_price=250.0),                                 # 6: no bar, so it cannot be judged
    ]
    assert trades.unfillable(booked) == [(2, booked[1]), (5, booked[4])]
    assert trades.unfillable([]) == []
