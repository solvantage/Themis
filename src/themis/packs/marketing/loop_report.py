"""The loop report: what one loop of work made, and what it cost against its estimates.

A loop is a set of items worked on together. Its report is a markdown page with one row for each
item, the totals, the measured overrun, and the agent runs that produced nothing. Everything on it
is read from records: the briefs, the plans, the spend receipts and the run receipts. Nothing is
typed, so building it again from the same records gives the same page.

Each item's spend is written with its cost tag, as in `1,100<!--s:content/a-->`, so the rule
`spend/figures-from-tools` can hold the page to the receipts. A record that cannot be read is
named at the foot of the page and is not counted: the report never guesses a missing value.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from themis import receipts, schema, work
from themis.gitlog import Git
from themis.grants import slug
from themis.packs.marketing import items, spend
from themis.packs.marketing.pack import ITEM_REPORT, SERIES_REPORTS, pack

if TYPE_CHECKING:
    from themis.manifest import Manifest

NONE = "—"  # shown where there is no record to read a value from
HOW_TO_READ = (
    "How to read this: the estimate is the price of the item's plan, set before any paid job is sent. "
    "The spend is the sum of the item's spend receipts, each written by the tool that ran the job. "
    f"The difference is the spend less the estimate. Each total adds up its own column. A dash ({NONE}) means "
    "there is no record."
)


def _read(root: Path, path: str, spec: Any, unread: list[str]) -> dict[str, Any]:
    """A TOML file that matches its schema. Empty when it is missing; empty, and named in `unread`,
    when it is there and cannot be used."""
    if not (root / path).is_file():
        return {}
    try:
        data = tomllib.loads((root / path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        data = None
    if data is None or schema.problems(data, spec, path):
        unread.append(f"`{path}` cannot be read or does not match its schema, so nothing was taken from it")
        return {}
    return data


def _cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def _signed(value: float) -> str:
    return ("+" if value > 0 else "-" if value < 0 else "") + spend.money(abs(value))


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _runs(root: Path) -> list[str]:
    """The lines about agent runs: how many there were, and each one that produced nothing."""
    runs = sorted(spend.read_receipts(root, spend.AGENT_RUN),
                  key=lambda run: (str(run.get("at", "")), run["_path"]))
    idle = [run for run in runs if spend.produced_nothing(run)]
    if not runs:
        return ["No agent run is recorded."]

    def cost(held: list[dict[str, Any]]) -> str:
        return spend.money(sum(run["cost"] for run in held if _number(run.get("cost"))))

    lines = [f"{len(runs)} agent run(s) are recorded, at a total cost of {cost(runs)}. "
             f"{len(idle)} of them produced nothing, at a cost of {cost(idle)}."] + ([""] if idle else [])
    for run in idle:
        paid = f"cost {spend.money(run['cost'])}" if _number(run.get("cost")) else "no cost recorded"
        flag = f"flagged: {run['reason']}" if run.get("flagged") is True and run.get("reason") else "not flagged"
        lines.append(f"- `{run['_path']}`: {_cell(run.get('role', 'no role'))}, {_cell(run.get('at', 'no time'))}, "
                     f"{paid}, {_cell(flag)}")
    return lines


def build(root: Path, manifest: Manifest, item_paths: Iterable[str]) -> str:
    """The loop report for these item folders, as markdown."""
    root = Path(root)
    unit = manifest.table("marketing").get("spend", {}).get("unit")
    spent, uncounted = spend.spend_by_item(root, unit)
    unread = [f"`{path}` is not counted: {problem}" for path, problem in uncounted]
    unread += [f"`{path}` is not counted: this run receipt cannot be read"
               for path in receipts.unreadable(root, spend.AGENT_RUN)]
    rows, pairs, estimates, paid, gaps = [], [], [], [], []
    for item in sorted({str(path).strip("/") for path in item_paths}):
        brief = _read(root, f"{item}/brief.toml", items.BRIEF, unread)
        estimate = _read(root, f"{item}/plan.toml", items.PLAN, unread).get("estimate")
        cost = spend.total(spent[item]) if item in spent else None
        both = estimate is not None and cost is not None
        estimates += [] if estimate is None else [estimate]
        paid += [] if cost is None else [cost]
        pairs += [(estimate, cost)] if both else []
        gaps += [cost - estimate] if both else []
        rows.append([
            f"{_cell(brief['title'])} (`{item}`)" if brief else f"`{item}`",
            _cell(brief.get("purpose", NONE)),
            NONE if estimate is None else spend.money(estimate),
            NONE if cost is None else f"{spend.money(cost)}<!--s:{item}-->",
            _signed(cost - estimate) if both else NONE,
        ])
    rows.append(["**Total**", "", spend.money(sum(estimates)), spend.money(sum(paid)), _signed(sum(gaps))])
    measured = spend.overrun(pairs)
    lines = [
        "# Loop report", "",
        "This page is built from records: each item's brief and plan, the spend receipts and the agent run "
        "receipts. Nothing on it is typed." + (f" Amounts are in {unit}." if unit else ""), "",
        "| Item | Purpose | Estimate | Spend | Difference |", "| --- | --- | --- | --- | --- |",
        *("| " + " | ".join(row) + " |" for row in rows), "", HOW_TO_READ, "",
    ]
    if measured is None:
        lines.append("**Measured overrun: not measured.** No item here has both an estimate and a spend.")
    else:
        lines.append(f"**Measured overrun: {measured:.2f}.** This is the spend divided by the estimate, over the "
                     f"{len(pairs)} item(s) that have both. Above 1, the work cost more than its estimates.")
    lines += ["", "## Agent runs that produced nothing", "", *_runs(root)]
    if unread:
        lines += ["", "## Records that could not be read", "", *(f"- {line}" for line in unread)]
    return "\n".join(lines) + "\n"


def write(root: Path, manifest: Manifest, item_paths: Iterable[str], path: str | Path) -> Path:
    """Build the loop report and write it to `path`, inside the repository."""
    target = Path(root) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build(root, manifest, item_paths), encoding="utf-8")
    return target


def report(root: Path, manifest: Manifest, unit: str) -> list[Path]:
    """What `themis report <item>` builds: the item's own page, and its series' page when the item
    is part of a series. Both are built from records, so building them again changes nothing."""
    root = Path(root)
    written = [write(root, manifest, [unit], f"{unit}/{ITEM_REPORT}")]
    name = _read(root, f"{unit}/brief.toml", items.BRIEF, []).get("series")
    pattern = manifest.table("marketing").get("work")
    if name and pattern:
        folders = sorted(work.units(Git(root).all_files(), pattern))
        held = [folder for folder in folders if _read(root, f"{folder}/brief.toml", items.BRIEF, []).get("series") == name]
        written.append(write(root, manifest, held, f"{SERIES_REPORTS}/{slug(name)}.md"))
    return written


pack.report = report
