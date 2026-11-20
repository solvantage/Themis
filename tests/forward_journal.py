"""A stand-in for a project's own weekly script, and the logs it reads, for the forward kind's tests.

Themis ships no adapter for any tester or venue. A project that runs a forward run writes its own
script, which `themis run <study> --input <live log> --input <replay> -- <the script>` runs once a
week. This one reads two small JSON logs, the live week's and the replay's, pairs their entries by
id, and writes the weekly record (docs/extending.md, Adapters):

    python journal.py <study> <week> <live log> [<replay log>]

A trade in a log is `{"id", "at", "gross", "cost"}`, its net `gross - cost`. The gap between live
and replay money is split into three parts: `costs`, what the live run paid more on matched entries;
`missed`, what the replay made on the entries the live run missed; and `extra`, what the live run
made on its own. What is left, a price move on a matched entry, is the remainder. The paired line
`entry-cost` is the mean extra cost of a matched entry, read on the entries matched that week.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

SETTINGS = "3f9a0c1d"

JOURNAL = """
import json, pathlib, sys
study, week, live_path = sys.argv[1], sys.argv[2], sys.argv[3]
replay_path = sys.argv[4] if len(sys.argv) > 4 else None
live = json.loads(pathlib.Path(live_path).read_text())
replay = json.loads(pathlib.Path(replay_path).read_text()) if replay_path else None
net = lambda trade: trade["gross"] - trade["cost"]
mine = {trade["id"]: trade for trade in live["trades"]}
theirs = {trade["id"]: trade for trade in replay["trades"]} if replay else {}
both = [name for name in theirs if name in mine]
missed = [name for name in theirs if name not in mine]
extra = [name for name in mine if name not in theirs]  # with no replay, every live trade is extra
why = live.get("reasons", {})
live_net = round(sum(net(trade) for trade in mine.values()), 2)
record = {
    "week": week, "period": live["period"],
    "live": {"run": live["run"], "settings": live["settings"], "start": live["start"], "trades": len(mine),
             "net": live_net, "first_trade_at": min((trade["at"] for trade in mine.values()), default="")},
    "replay": None,
    "entries": {"matched": [{"id": name, "live_at": mine[name]["at"], "replay_at": theirs[name]["at"]} for name in both],
                "missed": [{"id": name, "at": theirs[name]["at"], "reason": why.get(name, "")} for name in missed],
                "extra": [{"id": name, "at": mine[name]["at"], "reason": why.get(name, "")} for name in extra]},
    "fill_costs": {"entry": {"n": len(both), "live": round(sum(mine[name]["cost"] for name in both), 2),
                             "replay": round(sum(theirs[name]["cost"] for name in both), 2)}},
    "gap": {"parts": {"costs": 0.0, "missed": 0.0, "extra": 0.0}, "unexplained": 0.0},
    "lines": {"entry-cost": {"value": round(sum(mine[name]["cost"] - theirs[name]["cost"] for name in both)
                                            / len(both), 4) if both else 0.0, "n": len(both)}},
    "conditions": {"changes": live.get("changes", [])}, "risk": live["risk"], "range": live.get("range", {}),
}
if replay:
    replay_net = round(sum(net(trade) for trade in theirs.values()), 2)
    record["replay"] = {"run": replay["run"], "settings": replay["settings"], "period": replay["period"],
                        "start": replay["start"], "trades": len(theirs), "net": replay_net}
    parts = {"costs": round(sum(theirs[name]["cost"] - mine[name]["cost"] for name in both), 2),
             "missed": round(-sum(net(theirs[name]) for name in missed), 2),
             "extra": round(sum(net(mine[name]) for name in extra), 2)}
    record["gap"] = {"parts": parts, "unexplained": round(live_net - replay_net - sum(parts.values()), 2)}
out = pathlib.Path(study, "results", f"week-{week}.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(record, indent=1))
"""


def monday(week: str) -> dt.datetime:
    year, number = (int(part) for part in week.split("-"))
    return dt.datetime.combine(dt.date.fromisocalendar(year, number, 1), dt.time(), dt.timezone.utc)


def trades(week: str, count: int, cost: float = 0.1) -> list[dict[str, Any]]:
    """`count` trades in the week, an hour apart from Monday 10:00 UTC: two wins of 5 for each loss of 4."""
    start = monday(week)
    return [{"id": f"{week}-{number}", "at": (start + dt.timedelta(hours=9 + number)).isoformat(),
             "gross": 5.0 if number % 3 else -4.0, "cost": cost} for number in range(1, count + 1)]


def write_logs(root: Path, week: str, live: list[dict[str, Any]], replay: list[dict[str, Any]] | None, *,
               settings: str = SETTINGS, risk: float = 0.2, reasons: dict[str, str] | None = None,
               changes: list[dict[str, Any]] | None = None) -> list[str]:
    """The live log and, unless `replay` is None, the replay log of one week, under logs/. Returns
    their paths, live first."""
    start = monday(week)
    period = {"from": start.isoformat(), "to": (start + dt.timedelta(days=7)).isoformat()}
    state = {"at": start.isoformat(), "balance": 10000.0, "open_positions": 0, "peak": 10000.0}
    logs = {f"logs/live-{week}.json": {"run": f"live-{week}", "settings": settings, "period": period, "start": state,
                                       "trades": live, "reasons": reasons or {}, "changes": changes or [],
                                       "risk": {"day-loss": risk}, "range": {}}}
    if replay is not None:
        logs[f"logs/replay-{week}.json"] = {"run": f"replay-{week}", "settings": SETTINGS, "period": period,
                                            "start": state, "trades": replay}
    for path, held in logs.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(json.dumps(held), encoding="utf-8")
    return list(logs)
