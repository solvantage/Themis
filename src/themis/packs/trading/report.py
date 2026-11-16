"""The report page: one self-contained HTML file that a newcomer can read.

`write_report` lays out, in this order: the title, with the stake in four figures; a warnings box
that lists every scorecard line marked NOT RUN; four charts, each followed by a box that says how
to read it; the scorecard as a table; and, as the last line of the page, whether a second,
separate script checked the numbers.

The page holds no script and no outside asset. Every chart is inline SVG written by hand. Hover
text is the browser's own: a chart mark carries a `<title>`, and a scorecard label carries its tip
as a `title` attribute. The page is the same for the same inputs, so it can be rebuilt and
compared.
"""

from __future__ import annotations

import html
import math
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from themis.packs.trading import scorecard, stats
from themis.packs.trading.scorecard import Line, Row

AUDIT = "Checked by a second, separate script: "
WIDTH, HEIGHT = 720, 240
LEFT, RIGHT, TOP, BOTTOM = 64, 648, 16, 206  # the plot's edges inside the picture
MOST_POINTS = 600  # a longer line is thinned to this many points, keeping every high and low
HOW_TO_READ = {
    "money": "The line is the money after each finished trade, starting from the starting money on the left. "
             "A line that climbs steadily is better than one that jumps, so look for long flat or falling "
             "stretches.",
    "drop": "This shows how far the money stood below its best point so far, and zero at the top means a new "
            "high. The deepest point is the biggest drop, and a wide dip is a long wait for a new high.",
    "months": "Each bar is the money made or lost in one calendar month, with gains above the line and losses "
              "below it. Look at whether a few tall bars made most of the money.",
    "spread": "Each bar counts the trades whose result fell in that range, with losses left of zero and wins "
              "right of it. A result you can lean on has no single far-off bar doing all the work.",
}
STYLE = """
:root{color-scheme:light dark;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--series:#2a78d6;--loss:#e34948;--warn:#fff4d6;--warn-edge:#eda100}
@media (prefers-color-scheme:dark){:root{--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--grid:#2c2c2a;--axis:#383835;--series:#3987e5;--loss:#e66767;--warn:#33290a;--warn-edge:#c98500}}
body{margin:0 auto;max-width:800px;padding:24px 16px;background:var(--page);color:var(--ink);
font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
h1{font-size:28px;margin:0 0 8px}h2{font-size:20px;margin:32px 0 8px}h3{font-size:16px;margin:24px 0 4px}
.stake{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}
.stake div{flex:1 1 150px;background:var(--surface);border:1px solid var(--grid);border-radius:8px;padding:8px 12px}
.stake span{display:block;color:var(--ink2);font-size:14px}.stake b{font-size:20px}
.warnings{background:var(--warn);border-left:4px solid var(--warn-edge);border-radius:4px;padding:8px 16px}
.warnings h2{margin-top:8px}
svg{display:block;width:100%;height:auto;background:var(--surface);border:1px solid var(--grid);border-radius:8px}
.how-to-read{color:var(--ink2);font-size:14px;margin:6px 0 0;padding:6px 12px;border-left:3px solid var(--axis)}
.grid{stroke:var(--grid);stroke-width:1}.axis{stroke:var(--axis);stroke-width:1}
.line{fill:none;stroke:var(--series);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.wash{fill:var(--series);opacity:.1}.bar{fill:var(--series)}.bar.loss{fill:var(--loss)}
.dot{fill:var(--series);stroke:var(--surface);stroke-width:2}
.tick{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}.mark{fill:var(--ink);font-size:12px}
table{border-collapse:collapse;width:100%;background:var(--surface)}
td,th{border-bottom:1px solid var(--grid);padding:6px 10px;text-align:left;vertical-align:top}
th.group{background:var(--page);padding-top:16px}td.label{width:42%;cursor:help}
tr.not-run td{color:var(--ink2);font-style:italic}
.audit{margin-top:32px;padding-top:12px;border-top:1px solid var(--axis);color:var(--ink2)}
"""


def _esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _ticks(low: float, high: float, about: int = 4) -> list[float]:
    """Round numbers that span the range, about `about` of them."""
    raw = ((high - low) or abs(high) or 1.0) / about
    power = 10.0 ** math.floor(math.log10(raw))
    step = next(times for times in (1, 2, 5, 10) if times * power >= raw) * power
    count = math.floor((high - math.ceil(low / step) * step) / step + 1e-9)
    return [round((math.ceil(low / step) + index) * step, 10) for index in range(count + 1)] or [low]


def _short(value: float, step: float = 1.0) -> str:
    """A number for an axis: written in full under 10,000, and as 12K or 3.4M above."""
    if abs(value) >= 1e6:
        return f"{value / 1e6:.3g}M"
    if abs(value) >= 1e4:
        return f"{value / 1e3:.3g}K"
    places = min(2, max(0, -math.floor(math.log10(step)))) if step < 1 else 0
    return f"{value:,.{places}f}"


def _place(value: float, low: float, high: float, start: float, end: float) -> float:
    return (start + end) / 2 if high == low else start + (value - low) / (high - low) * (end - start)


def _thin(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """At most MOST_POINTS points: each stretch keeps its lowest and its highest, so no drop is lost."""
    if len(points) <= MOST_POINTS:
        return list(points)
    size, out = math.ceil(len(points) / (MOST_POINTS // 2)), [points[0]]
    for start in range(1, len(points) - 1, size):
        chunk = points[start:start + size]
        out += sorted({min(chunk, key=lambda point: point[1]), max(chunk, key=lambda point: point[1])})
    return [*out, points[-1]]


def _svg(label: str, inner: str) -> str:
    return (f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{_esc(label)}">'
            f"<title>{_esc(label)}</title>{inner}</svg>")


def _empty(label: str) -> str:
    return _svg(label, f'<text class="tick" x="{WIDTH / 2}" y="{HEIGHT / 2}" text-anchor="middle">'
                       "No trades to draw.</text>")


def _rows_y(low: float, high: float) -> tuple[str, float, float]:
    """The gridlines and their labels for a value axis, and the range once it holds every tick."""
    ticks = _ticks(low, high)
    step = ticks[1] - ticks[0] if len(ticks) > 1 else 1.0
    low, high = min(low, ticks[0]), max(high, ticks[-1])
    out = []
    for tick in ticks:
        y = _place(tick, low, high, BOTTOM, TOP)
        out.append(f'<line class="grid" x1="{LEFT}" x2="{RIGHT}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<text class="tick" x="{LEFT - 6}" y="{y + 4:.1f}" text-anchor="end">{_short(tick, step)}</text>')
    return "".join(out), low, high


def _dates(found: Sequence[Row]) -> str:
    """The first, middle and last dates under a time axis."""
    start, end = min(row.entry for row in found), found[-1].exit
    marks = [(LEFT, "start", start), ((LEFT + RIGHT) / 2, "middle", start + (end - start) / 2), (RIGHT, "end", end)]
    return "".join(f'<text class="tick" x="{x:.1f}" y="{HEIGHT - 10}" text-anchor="{anchor}">'
                   f"{moment.date().isoformat()}</text>" for x, anchor, moment in marks)


def _over_time(found: Sequence[Row], values: Sequence[float]) -> list[tuple[float, float]]:
    """Each value against the moment it was reached: the first entry, then each trade's exit."""
    start = min(row.entry for row in found)
    span = (found[-1].exit - start).total_seconds()
    moments = [0.0] + [(row.exit - start).total_seconds() for row in found]
    return [(_place(moment, 0.0, span, LEFT, RIGHT), value) for moment, value in zip(moments, values, strict=True)]


def _path(points: Sequence[tuple[float, float]]) -> str:
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points)


def money_chart(found: Sequence[Row], start_capital: float) -> str:
    """Money over time: the money after each finished trade."""
    label = "Money over time"
    if not found:
        return _empty(label)
    curve = scorecard.equity([row.net for row in found], start_capital)
    grid, low, high = _rows_y(min(curve), max(curve))
    points = _thin([(x, _place(value, low, high, BOTTOM, TOP)) for x, value in _over_time(found, curve)])
    base = _place(start_capital, low, high, BOTTOM, TOP)
    (end_x, end_y) = points[-1]
    return _svg(label, grid + _dates(found)
                + f'<line class="axis" x1="{LEFT}" x2="{RIGHT}" y1="{base:.1f}" y2="{base:.1f}">'
                  f"<title>Starting money: {scorecard.money(start_capital)}</title></line>"
                + f'<path class="wash" d="{_path(points)} L{end_x:.1f},{BOTTOM} L{LEFT},{BOTTOM} Z"/>'
                + f'<path class="line" d="{_path(points)}"/>'
                + f'<circle class="dot" cx="{end_x:.1f}" cy="{end_y:.1f}" r="4"/>'
                + f'<text class="mark" x="{end_x + 8:.1f}" y="{end_y + 4:.1f}">{_short(curve[-1])}</text>')


def drop_chart(found: Sequence[Row], start_capital: float) -> str:
    """The drop from the best point so far, drawn downwards from zero."""
    label = "The drop from the best point so far"
    if not found:
        return _empty(label)
    drops = [-drop for drop in stats.drawdowns(scorecard.equity([row.net for row in found], start_capital))]
    grid, low, high = _rows_y(min(drops), 0.0)
    points = _thin([(x, _place(value, low, high, BOTTOM, TOP)) for x, value in _over_time(found, drops)])
    deep_x, deep_y = max(points, key=lambda point: point[1])
    top = _place(0.0, low, high, BOTTOM, TOP)
    mark = "" if min(drops) == 0 else (
        f'<circle class="dot" cx="{deep_x:.1f}" cy="{deep_y:.1f}" r="4"/><text class="mark" x="{deep_x + 8:.1f}" '
        f'y="{deep_y + 4:.1f}">{_short(min(drops))}</text>')
    return _svg(label, grid + _dates(found)
                + f'<path class="wash" d="{_path(points)} L{points[-1][0]:.1f},{top:.1f} L{LEFT},{top:.1f} Z"/>'
                + f'<path class="line" d="{_path(points)}"/>' + mark)


def _bar(x: float, width: float, y: float, base: float, tip: str, loss: bool = False) -> str:
    """A bar from the baseline to `y`, with its far end rounded, and its hover text."""
    top, tall = min(y, base), abs(y - base)
    round_by = min(4.0, width / 2, tall)
    if y <= base:  # the bar rises: round its top
        shape = (f"M{x:.1f},{base:.1f} V{top + round_by:.1f} Q{x:.1f},{top:.1f} {x + round_by:.1f},{top:.1f} "
                 f"H{x + width - round_by:.1f} Q{x + width:.1f},{top:.1f} {x + width:.1f},{top + round_by:.1f} "
                 f"V{base:.1f} Z")
    else:  # the bar hangs: round its bottom
        shape = (f"M{x:.1f},{base:.1f} V{y - round_by:.1f} Q{x:.1f},{y:.1f} {x + round_by:.1f},{y:.1f} "
                 f"H{x + width - round_by:.1f} Q{x + width:.1f},{y:.1f} {x + width:.1f},{y - round_by:.1f} "
                 f"V{base:.1f} Z")
    return f'<path class="bar{" loss" if loss else ""}" d="{shape}"><title>{_esc(tip)}</title></path>'


def _months(found: Sequence[Row]) -> list[tuple[str, float]]:
    """The money made in each calendar month from the first exit to the last, quiet months included."""
    made: dict[str, float] = {}
    for row in found:
        made[row.exit.strftime("%Y-%m")] = made.get(row.exit.strftime("%Y-%m"), 0.0) + row.net
    year, month, out = found[0].exit.year, found[0].exit.month, []
    while (year, month) <= (found[-1].exit.year, found[-1].exit.month):
        out.append((f"{year}-{month:02d}", made.get(f"{year}-{month:02d}", 0.0)))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def _bars(values: Sequence[float], tips: Sequence[str], names: dict[int, str], *, split: bool, edges: bool) -> str:
    """A row of bars on one baseline at zero. `names` puts a label under some of the bars: under
    the bar's middle, or under its left edge when the labels name the edges of ranges."""
    grid, low, high = _rows_y(min(0.0, *values), max(0.0, *values))
    slot = (RIGHT - LEFT) / len(values)
    # A range's bar fills its slot, less a gap; a month's bar stays thin.
    width, base = max(1.0, slot - 2 if edges else min(24.0, slot - 2)), _place(0.0, low, high, BOTTOM, TOP)
    out = [grid]
    for index, value in enumerate(values):
        x = LEFT + slot * index + (slot - width) / 2
        if value:
            out.append(_bar(x, width, _place(value, low, high, BOTTOM, TOP), base, tips[index], split and value < 0))
        if index in names:
            out.append(f'<text class="tick" x="{LEFT + slot * index if edges else x + width / 2:.1f}" '
                       f'y="{HEIGHT - 10}" text-anchor="middle">{_esc(names[index])}</text>')
    return "".join(out) + f'<line class="axis" x1="{LEFT}" x2="{RIGHT}" y1="{base:.1f}" y2="{base:.1f}"/>'


def month_chart(found: Sequence[Row]) -> str:
    """Money made each month: one bar a calendar month, gains above the line and losses below."""
    label = "Money made each month"
    if not found:
        return _empty(label)
    months = _months(found)
    every = math.ceil(len(months) / 6)
    names = {index: name for index, (name, _) in enumerate(months) if index % every == 0}
    tips = [f"{name}: {scorecard.money(made)}" for name, made in months]
    return _svg(label, _bars([made for _, made in months], tips, names, split=True, edges=False))


def spread_chart(found: Sequence[Row]) -> str:
    """The spread of trade results: how many trades fell in each range of money, with zero an edge."""
    label = "The spread of trade results"
    if not found:
        return _empty(label)
    nets = [row.net for row in found]
    low, high = min(0.0, *nets), max(0.0, *nets)
    step = _ticks(low, high, 12)
    width = step[1] - step[0] if len(step) > 1 else (high - low or 1.0)
    first = math.floor(low / width)
    counts = [0] * max(1, math.ceil(high / width) - first)
    for net in nets:
        counts[min(len(counts) - 1, math.floor(net / width) - first)] += 1
    edges = [(first + index) * width for index in range(len(counts) + 1)]
    tips = [f"{scorecard.money(edges[index])} to {scorecard.money(edges[index + 1])}: {count} trades"
            for index, count in enumerate(counts)]
    every = math.ceil(len(counts) / 6)
    names = {index: _short(edges[index], width) for index in range(len(counts)) if (index + first) % every == 0}
    zero = LEFT - first * (RIGHT - LEFT) / len(counts)
    return _svg(label, _bars(counts, tips, names, split=False, edges=True)
                + f'<line class="axis" x1="{zero:.1f}" x2="{zero:.1f}" y1="{TOP}" y2="{BOTTOM}"/>')


def _stake(lines: dict[str, Line]) -> str:
    parts = []
    for line_id, name in (("start_money", "Starting money"), ("end_money", "Ending money"),
                          ("biggest_drop", "Biggest drop"), ("costs_paid", "Costs paid")):
        if line_id in lines:
            parts.append(f"<div><span>{_esc(name)}</span><b>{_esc(lines[line_id].text)}</b></div>")
    return f'<div class="stake">{"".join(parts)}</div>' if parts else ""


def _warnings(lines: Sequence[Line]) -> str:
    missing = [line for line in lines if line.not_run]
    if not missing:
        return '<div class="warnings"><h2>Warnings</h2><p>Every line of the scorecard was run.</p></div>'
    items = "".join(f"<li>{_esc(line.label)}: {scorecard.NOT_RUN}</li>" for line in missing)
    return ('<div class="warnings"><h2>Warnings</h2><p>These checks were not run. Until they are, this page '
            f"cannot answer the questions they ask.</p><ul>{items}</ul></div>")


def _table(lines: Sequence[Line]) -> str:
    out = ["<table>"]
    for group in sorted({line.group for line in lines}):
        name = scorecard.GROUPS.get(group, "Other")
        out.append(f'<tbody><tr><th class="group" colspan="2" scope="colgroup">{group}. {_esc(name)}</th></tr>')
        for line in lines:
            if line.group == group:
                out.append(f'<tr{" class=" + chr(34) + "not-run" + chr(34) if line.not_run else ""}>'
                           f'<td class="label" title="{_esc(line.tip)}">{_esc(line.label)}</td>'
                           f"<td>{_esc(line.text)}</td></tr>")
        out.append("</tbody>")
    return "\n".join([*out, "</table>"])


def write_report(path: str | Path, lines: Iterable[Line], trades: Iterable[Any], *, title: str, start_capital: float,
                 digest_comment: str = "", audited: bool = False) -> Path:
    """Write the report page and return its path.

    `lines` is the scorecard from `scorecard.compute`, and `trades` the same trades it was
    computed from. `digest_comment` is placed as it is, unescaped, at the top of the body: the
    caller passes an HTML comment that records a digest of the report's inputs. `audited` says
    whether a second, separate script has reproduced the numbers.
    """
    lines, found = list(lines), scorecard.rows(trades)
    charts = [
        ("Money over time", money_chart(found, start_capital), "money"),
        ("The drop from the best point so far", drop_chart(found, start_capital), "drop"),
        ("Money made each month", month_chart(found), "months"),
        ("The spread of trade results", spread_chart(found), "spread"),
    ]
    body = [
        digest_comment,
        f"<h1>{_esc(title)}</h1>",
        "<p>Every money figure on this page is a stake: what was put in, what it became, how far it fell on the "
        "way, and what the trading cost.</p>",
        _stake({line.id: line for line in lines}),
        _warnings(lines),
        "<h2>Charts</h2>",
        *(f'<h3>{_esc(name)}</h3>\n{chart}\n<div class="how-to-read">{_esc(HOW_TO_READ[key])}</div>'
          for name, chart, key in charts),
        "<h2>Scorecard</h2>",
        "<p>Rest the pointer on a label to read what the line means. The scorecard measures, and gives no "
        "verdict.</p>",
        _table(lines),
        f'<p class="audit">{AUDIT}{"YES" if audited else scorecard.NOT_RUN}</p></body></html>',
    ]
    page = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{_esc(title)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n"
            + "\n".join(part for part in body if part) + "\n")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    return target
