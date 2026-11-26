"""The timeline: one table, written by hand, of when each task starts and where it stands.

The table sits under one heading of one page, both named under `[timeline]` in the manifest: the
first table there whose header names the columns When, Task, Status, Who and Plan. Each row is one
task. Only the head of a cell is read; the words after it stay free.

- **When**: a day with its year (`Mon 30 Nov 2026`; a weekday, when written, must be that day's),
  a month or a span of months (`Feb – Mar 2027`), or `After 1, 2` for a row with no date. `~`
  reads a day as its month.
- **Task**: the task's number first (`9.`), when another row names it.
- **Status**: a state in bold, then, for a started state, its day (`**Built** 26 Nov 2026:`).
  After them, `on 1, 2` names the rows a wait is on, and `until` what restarts a stopped row: a
  day, rows, or a person's go.
- **Who** and **Plan**: someone, and a link.

A bare `#12` in a Status cell is a pull request of this repository. Another repository's is
written as a link, and kept apart. Rows are named as `1, 2`, `1 and 2` or `1–8`.

This module reads that shape for the timeline gate. Nothing here judges it: what cannot be read
is None, with the reason beside it.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass, field

from themis import checkpoint, markdown

COLUMNS = ("when", "task", "status", "who", "plan")  # the columns that mark the timeline's table
MONTHS = tuple(calendar.month_name)[1:]
WEEKDAYS = tuple(calendar.day_name)  # Monday first, as date.weekday() counts

_DASH = r"\s*[–—-]\s*"
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DAY = re.compile(rf"(?:(?P<weekday>(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?),?\s+)?(?P<day>\d{{1,2}})\s+"
                  rf"(?P<month>{_MONTH})(?:,?\s+(?P<year>\d{{4}}))?(?!\w)", re.IGNORECASE)
_MONTHS = re.compile(rf"(?P<month>{_MONTH})(?:\s+(?P<year>\d{{4}}))?(?:{_DASH}(?P<to>{_MONTH})\s+(?P<to_year>\d{{4}}))?"
                     r"(?!\w)", re.IGNORECASE)
_ITEM = rf"\d+[a-z]?(?:{_DASH}\d+[a-z]?)?"
_ROWS = rf"(?:rows?\s+)?{_ITEM}(?:\s*(?:,|and|&)\s*{_ITEM})*(?!\w)"
_AFTER = re.compile(rf"after\s+(?P<rows>{_ROWS})", re.IGNORECASE)
_ON = re.compile(rf"[\s:,]*on\s+(?P<rows>{_ROWS})", re.IGNORECASE)
_UNTIL = re.compile(r"[\s:,]*until\s+", re.IGNORECASE)
_LEAD_ROWS = re.compile(_ROWS, re.IGNORECASE)
_GO = re.compile(r"(?:[\w’'.-]+\s+){1,4}?go\b", re.IGNORECASE)  # a person's go: "your go", "the owner's go"
_STATE = re.compile(r"\*\*(?P<state>[^*]+?)\*\*")
_NUMBER = re.compile(r"\s*(\d+[a-z]?)\.(?=\s|$)", re.IGNORECASE)
_HEADING = re.compile(r" {0,3}(#{1,6})\s+(.*?)[\s#]*$")
_DELIMITER = re.compile(r"\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_FULL_LINK = re.compile(r"!?\[[^\]]*\]\([^)]*\)")
_PULL = re.compile(r"https?://\S+/pull/\d+")
_PR = re.compile(r"(?<![\w&#/])#(\d+)(?!\w)")


@dataclass(frozen=True)
class When:
    """What a When cell's head says."""

    text: str  # the head, as written
    by: dt.date | None = None  # the last day the row may start on: the day, or the end of its month or span
    after: tuple[str, ...] = ()  # the rows named after `After`


@dataclass(frozen=True)
class Row:
    """One row of the timeline. A part that cannot be read is None, and its `*_problem` says why."""

    line: int
    cells: dict[str, str]  # column, in lower case -> the cell's text
    number: str | None = None  # the task's number, as "9" or "0b"
    when: When | None = None
    when_problem: str | None = None
    state: str | None = None  # the bold head of the Status cell
    day: dt.date | None = None  # the day written after the state
    day_problem: str | None = None
    on: tuple[str, ...] | None = None  # the rows after `on`
    until: str | None = None  # what `until` names, as written
    until_day: dt.date | None = None
    until_rows: tuple[str, ...] = ()
    until_problem: str | None = None
    prs: tuple[int, ...] = ()  # each bare #N of the Status cell: this repository's pull requests
    other_prs: tuple[str, ...] = ()  # the Status cell's links to another repository's pull requests
    cited: tuple[str, ...] = ()  # the repository paths the Status cell links
    linked: tuple[str, ...] = ()  # the repository paths any cell of the row links
    plan_links: tuple[str, ...] = ()  # the Plan cell's link targets, as written

    @property
    def name(self) -> str:
        return f"row {self.number}" if self.number else f"the row on line {self.line}"


@dataclass(frozen=True)
class Timeline:
    """What the page holds under the heading. Line numbers count from 1."""

    heading_line: int | None = None  # None: the page has no such heading
    table_line: int | None = None  # None: no table under it has the timeline's columns
    rows: tuple[Row, ...] = field(default_factory=tuple)


def _named(word: str, names: tuple[str, ...]) -> int | None:
    """The index of the name this word spells or shortens (Nov, Sept, Thurs), or None."""
    word = word.rstrip(".").casefold()
    return next((index for index, name in enumerate(names) if len(word) >= 3 and name.casefold().startswith(word)),
                None)


def _end_of_month(year: int, month: int) -> dt.date:
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def read_day(text: str) -> tuple[dt.date | None, int, str | None]:
    """A day at the start of the text: (the day, how many characters it takes, why it cannot be
    read). (None, 0, None) when the text does not start with a day at all."""
    found = _DAY.match(text)
    if not found:
        return None, 0, None
    written, end = found.group(0), found.end()
    month = _named(found["month"], MONTHS)
    if month is None:
        return None, end, f"{written} names no month"
    if not found["year"]:
        return None, end, f"the day {written} has no year"
    try:
        day = dt.date(int(found["year"]), month + 1, int(found["day"]))
    except ValueError:
        return None, end, f"{written} is not a day of the calendar"
    if found["weekday"]:
        weekday = _named(found["weekday"], WEEKDAYS)
        if weekday is None:
            return None, end, f"{found['weekday']} is not a day of the week"
        if weekday != day.weekday():
            return None, end, f"{written} is a {WEEKDAYS[day.weekday()]}"
    return day, end, None


def rows_named(text: str) -> tuple[str, ...]:
    """The row numbers a list names: `1, 2`, `1 and 2`, `0b`, or a span such as `1–8`."""
    found: list[str] = []
    for item in re.findall(_ITEM, re.sub(r"^rows?\s+", "", text.strip(), flags=re.IGNORECASE), re.IGNORECASE):
        ends = re.split(_DASH, item)
        if len(ends) == 2 and all(end.isdigit() for end in ends) and int(ends[0]) <= int(ends[1]):
            found += [str(number) for number in range(int(ends[0]), int(ends[1]) + 1)]
        else:
            found += [end.lower() for end in ends]
    return tuple(found)


def _when(cell: str) -> tuple[When | None, str | None]:
    text = cell.strip().strip("*_").strip()
    if not text:
        return None, "the When cell is blank"
    near = text.startswith("~")  # a day read as its month
    text = text[1:].lstrip() if near else text
    after = None if near else _AFTER.match(text)
    if after:
        return When(after.group(0), after=rows_named(after["rows"])), None
    day, used, problem = read_day(text)
    if used:
        if problem:
            return None, problem
        assert day is not None
        return When(text[:used], by=_end_of_month(day.year, day.month) if near else day), None
    found = _MONTHS.match(text)
    first = _named(found["month"], MONTHS) if found else None
    if found and first is not None:
        if found["to"]:
            last, year = _named(found["to"], MONTHS), int(found["to_year"])
            if last is not None:
                return When(found.group(0), by=_end_of_month(year, last + 1)), None
        elif found["year"]:
            return When(found.group(0), by=_end_of_month(int(found["year"]), first + 1)), None
        else:
            return None, f"the month {found.group(0)} has no year"
    shown = text if len(text) <= 40 else text[:39] + "…"
    return None, f"When reads {shown!r}: not a day with its year, a month, a span of months, or After and rows"


def _links(cell: str, folder: str) -> tuple[list[str], list[str]]:
    """The repository paths a cell links, and its links to another repository's pull requests."""
    targets = checkpoint.links(cell)
    paths = [path for target in targets if (path := checkpoint.target_path(target, folder))]
    return paths, [target for target in targets if _PULL.match(target)]


def _row(line: int, cells: dict[str, str], folder: str) -> Row:
    found: dict = {}
    found["when"], found["when_problem"] = _when(cells.get("when", ""))
    number = _NUMBER.match(cells.get("task", ""))
    found["number"] = number[1].lower() if number else None
    status = cells.get("status", "").strip()
    head = _STATE.match(status)
    if head:
        found["state"] = head["state"].strip()
        rest = status[head.end():]
        day, used, found["day_problem"] = read_day(rest.lstrip(" "))
        found["day"] = day
        rest = rest.lstrip(" ")[used:] if used else rest
        on = _ON.match(rest)
        found["on"] = rows_named(on["rows"]) if on else None
        until = _UNTIL.match(rest)
        if until:
            what = rest[until.end():]
            day, used, problem = read_day(what)
            lead = _LEAD_ROWS.match(what)
            go = _GO.match(what)
            if used:
                found.update(until=what[:used], until_day=day, until_problem=problem)
            elif lead:
                found.update(until=lead.group(0), until_rows=rows_named(lead.group(0)))
            elif go:
                found.update(until=go.group(0))
            else:
                found["until_problem"] = "until names no day, rows or a person's go"
    paths, others = _links(status, folder)
    found["prs"] = tuple(int(number) for number in _PR.findall(_FULL_LINK.sub(" ", status)))
    found.update(cited=tuple(paths), other_prs=tuple(others))
    found["linked"] = tuple(path for cell in cells.values() for path in _links(cell, folder)[0])
    found["plan_links"] = tuple(checkpoint.links(cells.get("plan", "")))
    return Row(line=line, cells=cells, **found)


def _cells(line: str) -> list[str]:
    """A table line's cells: split at each pipe that is not escaped, with `\\|` read as a pipe."""
    line = line.strip()
    line = line[1:] if line.startswith("|") else line
    line = line[:-1] if line.endswith("|") and not line.endswith("\\|") else line
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", line)]


def parse(text: str, heading: str, folder: str = "") -> Timeline:
    """Read the timeline under the heading. `folder` is the page's own, which its links are read from.

    The section runs to the next heading of the same depth or higher. A fenced block is an example
    and is never read. The first table whose header names When, Task, Status, Who and Plan, in
    any order and case, is the timeline's.
    """
    lines = text.split("\n")
    fenced = {number for number, _, code in markdown.lines_of(text) if code}
    plain = [None if number in fenced else line for number, line in enumerate(lines, start=1)]
    start = depth = None
    end = len(lines)
    for index, line in enumerate(plain):
        found = _HEADING.match(line) if line is not None else None
        if not found:
            continue
        if start is None and found[2].strip().casefold() == heading.strip().casefold():
            start, depth = index, len(found[1])
        elif start is not None and depth is not None and len(found[1]) <= depth:
            end = index
            break
    if start is None:
        return Timeline()

    def is_row(index: int) -> bool:
        return index < end and plain[index] is not None and plain[index].strip().startswith("|")

    index = start + 1
    while index < end - 1:
        if not (is_row(index) and plain[index + 1] is not None and _DELIMITER.match(plain[index + 1])):
            index += 1
            continue
        columns = [cell.casefold() for cell in _cells(lines[index])]
        stop = index + 2
        while is_row(stop):
            stop += 1
        if set(COLUMNS) <= set(columns):
            rows = tuple(_row(number + 1, dict(zip(columns, _cells(lines[number]))), folder)
                         for number in range(index + 2, stop))
            return Timeline(heading_line=start + 1, table_line=index + 1, rows=rows)
        index = stop
    return Timeline(heading_line=start + 1)
