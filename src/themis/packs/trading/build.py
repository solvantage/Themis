"""What `themis report <study>` builds: the scorecard and the report page, from the study's files.

Nothing on either is typed. The trades come from the study's trade table. What the scorecard
cannot work out from the trades is read from the `scorecard` table of the study's metrics file:

    start_capital    the money the test began with; needed whenever trades were booked
    baselines        the ending money of always_long and always_short
    oos_start        the first moment of the data the idea had never seen
    trial_sharpes    the per-trade Sharpe ratio of every idea tried, this one included
    sensitivity      the ending money of neighbouring settings

One that is left out leaves its scorecard line marked NOT RUN; a name that is not in this list
is refused, so a spelling mistake never becomes a blank line. The page says whether a second,
separate script checked the numbers, read from the status in AUDIT.md.

The page carries a digest of what it was built from: the trade table, the metrics file and the
audit. The core rule `report/generated` compares that digest with the files, so a page left
behind by a later run is caught.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from themis import records
from themis.gates import report as core_report
from themis.packs.trading import report as pages
from themis.packs.trading import scorecard, trades, units
from themis.packs.trading.pack import REPORT_INPUTS as INPUTS
from themis.packs.trading.pack import pack

OPTIONAL = ("baselines", "oos_start", "trial_sharpes", "sensitivity")
GIVEN = ("start_capital", *OPTIONAL)
AUDITED = ("reproduced", "differences-explained")
NO_TRADES = ("signal",)  # the kinds of study that may ship a scorecard with no trade booked


def _frontmatter(path: Path) -> dict[str, Any]:
    """A markdown file's frontmatter. Empty when the file is missing or has none."""
    if not path.is_file():
        return {}
    try:
        return records.frontmatter(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"the frontmatter of {path.name} cannot be read ({error})") from None


def _seal(root: Path, unit: str) -> dict[str, Any]:
    found = sorted(path for pattern in units.SEAL for path in (root / unit).glob(pattern))
    return _frontmatter(found[0]) if found else {}


def _given(root: Path, unit: str) -> dict[str, Any]:
    """The `scorecard` table of the study's metrics file. Empty when there is no file or no table."""
    where = f"{unit}/{units.METRICS}"
    path = root / where
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{where} cannot be read ({error})") from None
    given = data.get("scorecard", {}) if isinstance(data, dict) else None
    if not isinstance(given, dict):
        raise ValueError(f"{where} must hold a table, and its scorecard entry must be a table too")
    unknown = sorted(set(given) - set(GIVEN))
    if unknown:
        raise ValueError(f"{where}: scorecard holds {', '.join(unknown)}; it may hold {', '.join(GIVEN)}")
    return given


def report(root: Path, manifest: Any, unit: str) -> list[Path]:
    """Build the study's scorecard and report page, and return their paths.

    Raises ValueError, with a plain reason, when the study's files cannot carry a report. Nothing
    is written then.
    """
    root, seal = Path(root), _seal(Path(root), unit)
    table = root / unit / units.TRADES
    if table.is_file():
        try:
            booked = trades.read_trades(table)
        except ValueError as error:
            raise ValueError(f"{unit}/{units.TRADES} breaks the standard trade table: {error}") from None
    elif seal.get("kind") in NO_TRADES:
        booked = []
    else:
        raise ValueError(f"{unit} has no trade table at {units.TRADES}; a report is built from the closed trades")
    given = _given(root, unit)
    start = given.get("start_capital", 0 if not booked else None)
    if isinstance(start, bool) or not isinstance(start, (int, float)) or start < 0 or (booked and start <= 0):
        raise ValueError(f"{unit}/{units.METRICS} must give scorecard.start_capital, a number above 0: the money "
                         "the test began with")
    stated = {name: given[name] for name in OPTIONAL if name in given}
    try:
        lines = scorecard.compute(booked, start_capital=start, **stated)
    except (TypeError, KeyError, AttributeError) as error:
        raise ValueError(f"{unit}/{units.METRICS}: the scorecard table cannot be used "
                         f"({error.__class__.__name__}: {error})") from None
    audited = _frontmatter(root / unit / units.AUDIT).get("status") in AUDITED
    stamp = core_report.digest_comment(core_report.inputs_digest(root, unit, INPUTS))
    title = str(seal.get("title") or unit.rsplit("/", 1)[-1])
    card = scorecard.write_csv(lines, root / unit / units.SCORECARD)
    page = pages.write_report(root / unit / units.REPORT, lines, booked, title=title, start_capital=start,
                              digest_comment=stamp, audited=audited)
    return [card, page]


pack.report = report
