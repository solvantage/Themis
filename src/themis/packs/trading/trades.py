"""The standard trade table: one row for each closed trade, whatever engine booked it.

A study that books trades keeps the table at `results/trades.csv`. Every strategy uses the same
columns, so a strategy from any engine can be laid beside any other, and one scorecard reads them
all.

    entry_time, exit_time     ISO date-times; the exit is never before the entry
    side                      long or short
    size                      a number above 0
    entry_price, exit_price   numbers above 0
    costs                     0 or more: what the trade paid in fees, spread and funding
    net                       the trade's result in money, after costs
    bar_low, bar_high         optional: the low and high of the bar the trade was filled in
    mfe, mae                  optional: the best and the worst moment of the trade, in money

Rows are numbered from 1, the first trade. The header is row 0. A table that breaks the standard
is never read in part: the readers raise ValueError, naming the row and the reason in plain words.

`from_rows` is the adapter: it takes rows whose columns are named differently, as any engine or
tester exports them, and a mapping from the standard names to theirs.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED = ("entry_time", "exit_time", "side", "size", "entry_price", "exit_price", "costs", "net")
OPTIONAL = ("bar_low", "bar_high", "mfe", "mae")
COLUMNS = REQUIRED + OPTIONAL
SIDES = ("long", "short")
_TIMES = ("entry_time", "exit_time")


def show(value: float) -> str:
    """A number as a person would write it: 101.5, and 100 rather than 100.0."""
    return f"{value:.10g}"


@dataclass(frozen=True)
class Trade:
    """One closed trade. A trade that breaks the standard cannot be built: it raises ValueError."""

    entry_time: datetime
    exit_time: datetime
    side: str
    size: float
    entry_price: float
    exit_price: float
    costs: float
    net: float
    bar_low: float | None = None
    bar_high: float | None = None
    mfe: float | None = None
    mae: float | None = None

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValueError(f"side is neither long nor short: {self.side!r}")
        for name in ("size", "entry_price", "exit_price"):
            if not getattr(self, name) > 0:
                raise ValueError(f"{name} must be above 0, and is {show(getattr(self, name))}")
        if not self.costs >= 0:
            raise ValueError(f"costs must be 0 or more, and is {show(self.costs)}")
        try:
            early = self.exit_time < self.entry_time
        except TypeError:
            raise ValueError("entry_time and exit_time must both carry a time zone, or neither") from None
        if early:
            raise ValueError(f"the exit ({self.exit_time.isoformat()}) is before the entry "
                             f"({self.entry_time.isoformat()})")
        if (self.bar_low is None) != (self.bar_high is None):
            raise ValueError("bar_low and bar_high come together, and one is given without the other")
        if self.bar_low is not None and self.bar_high is not None and self.bar_low > self.bar_high:
            raise ValueError(f"bar_low ({show(self.bar_low)}) is above bar_high ({show(self.bar_high)})")


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _number(value: Any, label: str) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    else:
        try:
            number = float(str(value).strip())
        except ValueError:
            raise ValueError(f"{label} is not a number: {str(value).strip()!r}") from None
    if not math.isfinite(number):
        raise ValueError(f"{label} is not a number: {str(value).strip()!r}")
    return number


def _time(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).strip())
    except ValueError:
        raise ValueError(f"{label} is not an ISO date-time such as 2026-01-05T09:30:00: "
                         f"{str(value).strip()!r}") from None


def _names(mapping: Mapping[str, str] | None) -> dict[str, str]:
    """Each standard column with the name the rows use for it."""
    unknown = sorted(set(mapping or {}) - set(COLUMNS))
    if unknown:
        raise ValueError(f"the mapping names {', '.join(unknown)}, which the standard trade table does not have; "
                         f"its columns are {', '.join(COLUMNS)}")
    return {column: (mapping or {}).get(column, column) for column in COLUMNS}


def _trade(row: Mapping[str, Any], names: Mapping[str, str]) -> Trade:
    """One row as a trade. Raises ValueError with the reason; the caller adds the row number."""
    values: dict[str, Any] = {}
    for column in COLUMNS:
        theirs = names[column]
        label = column if theirs == column else f"{column} (the column {theirs})"
        if column in REQUIRED and theirs not in row:
            raise ValueError(f"there is no column named {theirs}")
        value = row.get(theirs)
        if _empty(value):
            if column in REQUIRED:
                raise ValueError(f"{label} is empty")
            values[column] = None
        elif column in _TIMES:
            values[column] = _time(value, label)
        elif column == "side":
            values[column] = str(value).strip().lower()
        else:
            values[column] = _number(value, label)
    return Trade(**values)


def from_rows(rows: Iterable[Mapping[str, Any]], mapping: Mapping[str, str] | None = None) -> list[Trade]:
    """Trades from rows whose columns are named differently.

    `mapping` is standard name -> their name, for each column that differs, such as
    `{"entry_time": "Open Time", "net": "Profit"}`. A column the mapping leaves out keeps its
    standard name. Columns the standard does not have are ignored. Values may be text, numbers or
    datetimes.
    """
    names = _names(mapping)
    found = []
    for number, row in enumerate(rows, start=1):
        try:
            found.append(_trade(row, names))
        except ValueError as error:
            raise ValueError(f"row {number}: {error}") from None
    return found


def parse_trades(text: str) -> list[Trade]:
    """The trades in the text of a standard trade table. Blank lines are skipped."""
    try:
        rows = [row for row in csv.reader(io.StringIO(text.lstrip("\ufeff"))) if any(cell.strip() for cell in row)]
    except csv.Error as error:
        raise ValueError(f"the table is not a CSV that can be read ({error})") from None
    if not rows:
        raise ValueError("row 0 (the header): the table is empty")
    header = [name.strip() for name in rows[0]]
    missing = [name for name in REQUIRED if name not in header]
    if missing:
        raise ValueError(f"row 0 (the header): there is no column named {', '.join(missing)}")
    twice = sorted({name for name in header if name in COLUMNS and header.count(name) > 1})
    if twice:
        raise ValueError(f"row 0 (the header): the column {', '.join(twice)} is named twice")
    return from_rows(_records(header, rows[1:]))


def _records(header: list[str], rows: list[list[str]]) -> Iterable[dict[str, str]]:
    for number, cells in enumerate(rows, start=1):
        if len(cells) != len(header):
            raise ValueError(f"row {number}: it has {len(cells)} values, and the header has {len(header)} columns")
        yield dict(zip(header, cells, strict=True))


def read_trades(path: str | Path) -> list[Trade]:
    """Read and check a standard trade table. Raises ValueError with the row number and the
    reason when the table breaks the standard."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ValueError("the table is not UTF-8 text") from None
    return parse_trades(text)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return repr(float(value)) if isinstance(value, (int, float)) else str(value)


def write_trades(trades: Iterable[Trade], path: str | Path) -> None:
    """Write the standard trade table. An optional column is written when any trade carries it."""
    trades = list(trades)
    columns = list(REQUIRED) + [name for name in OPTIONAL if any(getattr(trade, name) is not None for trade in trades)]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for trade in trades:
            writer.writerow([_cell(getattr(trade, name)) for name in columns])


def unfillable(trades: Iterable[Trade]) -> list[tuple[int, Trade]]:
    """The (row number, trade) pairs whose entry price is outside its bar's low and high.

    A price equal to the low or the high did trade, so it is inside. A trade that carries no bar
    cannot be judged, and is left out.
    """
    return [
        (number, trade)
        for number, trade in enumerate(trades, start=1)
        if trade.bar_low is not None and trade.bar_high is not None
        and not trade.bar_low <= trade.entry_price <= trade.bar_high
    ]
