"""The onboarding guide's cases G1, T4 and T5, run as the guide tells them.

Each case runs in a world built from scratch: G1 in a plain docs-and-scripts site, T4 in a
trading project whose outside tester is a stand-in script, T5 in a forward run whose weekly script
is a stand-in too (tests/forward_journal.py). Everything Themis prints on the way is
gathered, and every message the guide quotes for the case, in its "What Themis says" column, must
be in it. So the guide cannot quote a message this release does not print, and a message that
changes fails here until the guide says it again.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from themis import engine, hooks
from themis import manifest as manifests
from themis.cli import EXIT_FAIL, EXIT_PASS, EXIT_REFUSE, main
from themis.proofs import World
from themis.verdict import Verdict

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/onboarding.md"
THEMIS = [sys.executable, "-c", "import sys; from themis.cli import main; sys.exit(main(sys.argv[1:]))"]
TICKED = re.compile(r"`([^`]+)`")


class Session:
    """One world, and everything Themis said in it."""

    def __init__(self, world: World) -> None:
        self.world, self.said = world, []

    def themis(self, *args: str) -> int:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([args[0], "--root", str(self.world.root), *args[1:]])
        self.said += [out.getvalue(), err.getvalue()]
        return code

    def script(self, *argv: str) -> int:
        done = subprocess.run([sys.executable, *argv], cwd=self.world.root, capture_output=True, text=True,
                              check=False)
        self.said += [done.stdout, done.stderr]
        return done.returncode

    def hook(self, command: str) -> None:
        """What the hook says before the agent runs this command, or nothing when it lets it run."""
        answer = hooks.pretool({"tool_name": "Bash", "tool_input": {"command": command}}, self.world.root)
        self.said.append(answer["hookSpecificOutput"]["permissionDecisionReason"] if answer else "")

    def verdict(self, rule_id: str) -> Verdict | None:
        return engine.run(manifests.load(self.world.root), only={rule_id}).results[0].verdict

    def text(self) -> str:
        return "\n".join(self.said)


def quotes(case: str) -> list[str]:
    """Every message the guide quotes for one case: each ticked text with a space in it in the
    last column of the case's tables, but a command."""
    text = GUIDE.read_text(encoding="utf-8")
    start = text.index(f"### {case}.")
    end = re.search(r"^#{2,3} ", text[start + 4:], re.MULTILINE)
    found = []
    for line in text[start:start + 4 + (end.start() if end else len(text))].splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s|:-]+\|$", line):
            last = line.strip().strip("|").split("|")[-1]
            found += [quote for quote in TICKED.findall(last) if " " in quote and not quote.startswith("themis ")]
    return found


def said_as_quoted(session: Session, case: str, **names: str) -> list[str]:
    """The quotes of the case that Themis did not say. `<study>` and the like stand for the names
    the case's world gave."""
    text = " ".join(session.text().split())
    missing = []
    for quote in quotes(case):
        for name, value in names.items():
            quote = quote.replace(f"<{name}>", value)
        if " ".join(quote.split()) not in text:
            missing.append(quote)
    return missing


# -- G1: a guarded command, in a project that is no trading project -----------------------------

SITE = """
[project]
name = "site"

[rules."grant/required"]
level = "enforce"
guarded = ["publish"]

[rules."grant/single-use"]
level = "enforce"
"""
#: The site's publish script. Its first step asks Themis whether it runs under `themis act`.
PUBLISH = f"""
import subprocess, sys
target = sys.argv[1]
if subprocess.run({THEMIS!r} + ["act", "--verify", "publish", target]).returncode != 0:
    sys.exit("refused: publish runs only through themis act")
open("published.txt", "a").write(target + "\\n")
"""


def site(tmp_path: Path) -> Session:
    world = World(tmp_path / "site")
    world.root.mkdir(parents=True)
    world.manifest(SITE)
    world.write(".gitignore", ".themis/\n__pycache__/\n")
    world.write("docs/index.md", "# The site\n")
    world.write("scripts/publish.py", PUBLISH)
    world.commit("start")
    return Session(world)


def test_g1_a_guarded_command_runs_once_on_the_owners_grant(tmp_path: Path) -> None:
    session = site(tmp_path)
    act = ("act", "publish", "site", "--", sys.executable, "scripts/publish.py", "site")
    assert session.script("scripts/publish.py", "site") != 0  # run bare: the script refuses
    assert session.themis(*act) == EXIT_REFUSE  # under act, with no grant: nothing runs
    assert not (session.world.root / "published.txt").exists()
    session.hook("themis grant publish site --reason ready")  # the agent cannot give the grant
    session.hook("themis act publish site -- python scripts/publish.py site")  # and act is not stopped
    assert session.said[-1] == ""
    assert session.themis("grant", "publish", "site", "--reason", "the copy was read") == EXIT_PASS
    assert session.themis(*act) == EXIT_PASS
    assert (session.world.root / "published.txt").read_text() == "site\n"
    assert session.themis(*act) == EXIT_REFUSE  # the grant is spent
    session.world.commit("published")
    assert session.themis("check") == EXIT_PASS
    session.world.write("receipts/action/by-hand.json", json.dumps({
        "kind": "action", "action": "publish", "target": "site", "at": "2026-11-19T10:00:00+00:00"}))
    assert session.themis("check") == EXIT_FAIL  # a receipt written by hand names no grant
    assert len(quotes("G1")) >= 6
    assert said_as_quoted(session, "G1") == []


# -- T4: a strategy tuned in an outside tester --------------------------------------------------

TRADING = """
[project]
name = "tuning"
packs = ["trading"]

[trading]
work = "tuning/*"

[trading.windows.in-sample]
from = "2018-01-01"
to = "2022-12-31"

[trading.windows.out-of-sample]
from = "2023-01-01"
to = "2024-06-30"

[trading.tune]
confirm_model = "every tick"

[rules]
"config/valid" = "enforce"
"prereg/declared" = "enforce"
"trials/settings-counted" = "enforce"
"holdout/guarded" = "enforce"
"holdout/one-signal-look" = "enforce"
"grant/required" = "enforce"
"grant/single-use" = "enforce"
"validity/confirm-on-real-ticks" = "enforce"
"decision/issued-by-gate" = "enforce"

[rules."scorecard/believable"]
kinds = ["strategy", "signal"]      # a tune study ships no README of its own

[rules."scorecard/explainer"]
kinds = ["strategy", "signal"]
"""
SEAL = """---
kind: tune
title: Breakout, tuned in an outside tester
windows: [in-sample, out-of-sample, unseen]
window-unseen: {from = "2024-07-01", to = "2025-12-31", sealed = true}
gate: tune
iterations: 40
risk_rules: rules/risk.json
---

Map the breakout's two settings in-sample, tune inside the region that holds, keep the setting
that passes out of sample and on the walk back, then confirm it once on the unseen window.
"""
#: A stand-in for the outside tester. `runs` writes one run for each settings version, `stages`
#: what the screen and the tune found.
TESTER = """
import csv, json, pathlib, sys
study, stage = sys.argv[1], sys.argv[2]
results = pathlib.Path(study, "results")
results.mkdir(parents=True, exist_ok=True)
history = results / "run-history.csv"
if stage == "runs":
    first, last = int(sys.argv[3]), int(sys.argv[4])
    new = not history.exists()
    with history.open("a", newline="") as file:
        rows = csv.writer(file)
        if new:
            rows.writerow(["run", "settings_id"])
        for number in range(first, last + 1):
            rows.writerow([number, f"s{number}"])
else:
    (results / "metrics.json").write_text(json.dumps({
        "settings_tried": int(sys.argv[3]), "budget": 40, "in_sample": {"pass": True},
        "out_of_sample": {"pass": True}, "walk_back": {"passed": 5, "total": 5, "min_pass": 4}}))
"""
#: The confirming run: once, on the unseen window, under `themis act`. It adds the holdout's
#: outcome and the model it used to the metrics, and turns the tester's deals into the standard
#: trade table.
CONFIRM = f"""
import json, pathlib, subprocess, sys
from themis.packs.trading.trades import from_rows, write_trades
study, model = sys.argv[1], sys.argv[2]
if subprocess.run({THEMIS!r} + ["act", "--verify", "holdout", study + "/unseen"]).returncode != 0:
    sys.exit("refused: the confirming run goes through themis act")
results = pathlib.Path(study, "results")
metrics = json.loads((results / "metrics.json").read_text())
metrics.update(holdout={{"pass": True}}, confirm_model=model, scorecard={{
    "start_capital": 10000.0, "baselines": {{"always_long": 10100.0, "always_short": 9900.0}},
    "oos_start": "2023-01-01", "trial_sharpes": [0.1, 0.3, 0.2], "sensitivity": [10150.0, 10080.0]}})
(results / "metrics.json").write_text(json.dumps(metrics))
deals = [{{"Opened": f"2024-{{month:02d}}-03 10:00", "Closed": f"2024-{{month:02d}}-04 10:00", "Direction": "long",
           "Lots": 1, "Open": 100.0, "Close": 100.0 + profit + 1.0, "Fees": 1.0, "Profit": profit}}
         for month, profit in zip(range(7, 13), (40.0, -15.0, 25.0, 10.0, -5.0, 30.0))]
mapping = {{"entry_time": "Opened", "exit_time": "Closed", "side": "Direction", "size": "Lots",
           "entry_price": "Open", "exit_price": "Close", "costs": "Fees", "net": "Profit"}}
write_trades(from_rows(deals, mapping), results / "trades.csv")
"""


def tuning(tmp_path: Path) -> tuple[Session, str]:
    """T4 up to its seal: the project, the logged study, and its plan merged on its own."""
    world = World(tmp_path / "tuning")
    world.root.mkdir(parents=True)
    world.manifest(TRADING)
    world.write(".gitignore", ".themis/\n__pycache__/\n")
    world.write("tester.py", TESTER)
    world.write("confirm.py", CONFIRM)
    world.write("data/prices.csv", "day,close\n2018-01-02,100.0\n")
    world.write("rules/risk.json", '{"max_daily_loss": 0.02}\n')
    world.commit("start")
    session = Session(world)
    assert session.themis("new", "breakout", "--question", "which settings hold up out of sample?") == EXIT_PASS
    [ledger] = (world.root / "ledger").glob("*.toml")
    study = tomllib.loads(ledger.read_text())["work"]
    world.commit("log the study")
    world.pull_request("seal", {f"{study}/PRE-REG.md": SEAL})
    return session, study


def count(session: Session, variants: int) -> None:
    """Log the search's size before it runs: the trial's variants."""
    [ledger] = (session.world.root / "ledger").glob("*.toml")
    ledger.write_text(re.sub(r"(?m)^variants = \d+$", f"variants = {variants}", ledger.read_text()))
    session.world.commit(f"the search covers {variants} settings")


def search(session: Session, study: str, last: int = 12) -> None:
    """Map 8 settings in-sample, then tune 4 more inside the region that held, each counted first."""
    count(session, 8)
    assert session.themis("run", study, "--input", "data/prices.csv", "--", sys.executable, "tester.py", study,
                          "runs", "1", "8") == EXIT_PASS
    session.world.commit("the map")
    count(session, 12)
    assert session.themis("run", study, "--input", "data/prices.csv", "--", sys.executable, "tester.py", study,
                          "runs", "9", str(last)) == EXIT_PASS
    session.world.commit("the tune")
    assert session.themis("run", study, "--", sys.executable, "tester.py", study, "stages", str(last)) == EXIT_PASS
    session.world.commit("the stages")


def confirm(session: Session, study: str, model: str = "every tick") -> int:
    return session.themis("act", "holdout", f"{study}/unseen", "--", sys.executable, "confirm.py", study, model)


def test_t4_a_strategy_tuned_in_an_outside_tester_start_to_finish_and_its_corners_cut(tmp_path: Path) -> None:
    session, study = tuning(tmp_path / "honest")
    assert session.verdict("prereg/declared") is Verdict.PASS
    search(session, study)
    assert session.verdict("trials/settings-counted") is Verdict.PASS
    assert confirm(session, study) == EXIT_REFUSE  # no grant yet: the tester never starts
    session.hook(f"themis grant holdout {study}/unseen --reason done")
    assert session.themis("grant", "holdout", f"{study}/unseen", "--reason", "the search is done") == EXIT_PASS
    assert confirm(session, study) == EXIT_PASS
    session.world.commit("the confirming run")
    for rule_id in ("holdout/guarded", "holdout/one-signal-look", "grant/required", "grant/single-use"):
        assert session.verdict(rule_id) is Verdict.PASS, rule_id
    assert session.themis("decide", study, "--gate", "tune") == EXIT_PASS
    assert session.verdict("validity/confirm-on-real-ticks") is Verdict.PASS
    assert session.themis("report", study) == EXIT_PASS
    assert (session.world.root / study / "results/report.html").is_file()
    session.world.commit("the decision and the report")
    assert session.themis("check") == EXIT_PASS
    sessions = [session]

    # Corners cut, one world each.
    session, study = tuning(tmp_path / "uncounted")
    search(session, study, last=13)  # a thirteenth settings version, and the ledger still says 12
    assert session.themis("check", "trials/settings-counted") == EXIT_FAIL
    sessions.append(session)

    session, study = tuning(tmp_path / "by-hand")
    search(session, study)
    session.themis("grant", "holdout", f"{study}/unseen", "--reason", "the search is done")
    assert session.script("confirm.py", study, "every tick") != 0  # the confirming run started by hand
    sessions.append(session)

    session, study = tuning(tmp_path / "cheaper")
    search(session, study)
    session.themis("grant", "holdout", f"{study}/unseen", "--reason", "the search is done")
    assert confirm(session, study, "open prices") == EXIT_PASS  # confirmed on a cheaper model
    session.world.commit("the confirming run")
    assert session.themis("decide", study, "--gate", "tune") == EXIT_PASS  # the gate reads outcomes only
    assert session.themis("check", "validity/confirm-on-real-ticks") == EXIT_FAIL
    sessions.append(session)

    session, study = tuning(tmp_path / "second-look")
    search(session, study)
    session.themis("grant", "holdout", f"{study}/unseen", "--reason", "the search is done")
    assert confirm(session, study) == EXIT_PASS
    assert confirm(session, study) == EXIT_REFUSE  # the same grant does not open it twice
    session.themis("grant", "holdout", f"{study}/unseen", "--reason", "one more look")
    assert confirm(session, study) == EXIT_PASS  # the owner granted it, so act opens it
    session.world.commit("two looks")
    assert session.themis("check", "holdout/one-signal-look") == EXIT_FAIL
    sessions.append(session)

    every = Session(session.world)
    every.said = [each.text() for each in sessions]
    assert len(quotes("T4")) >= 8
    assert said_as_quoted(every, "T4", study=study) == []


# -- T5: a forward run, week by week ------------------------------------------------------------

FORWARD_RULES = ("sealed-before-start", "same-dates-control", "match", "gap-explained", "conditions-stable",
                 "no-retune", "enough-trades", "risk-line")
FORWARD = """
[project]
name = "forward"
packs = ["trading"]

[trading]
work = "forward/*"

[rules]
"config/valid" = "enforce"
"prereg/declared" = "enforce"
"decision/issued-by-gate" = "enforce"
"decision/calibrated" = "enforce"
""" + "".join(f'"forward/{name}" = "enforce"\n' for name in FORWARD_RULES) + """
[rules."scorecard/believable"]
kinds = ["strategy", "signal"]      # a forward run ships no README of its own

[rules."scorecard/explainer"]
kinds = ["strategy", "signal"]
"""
FORWARD_SEAL = """---
kind: forward
title: Breakout, live beside its replay
gate: forward
settings: 3f9a0c1d
min_trades: 60
stop_rule: the owner stops the run; a restart is a new run, sealed anew
lines: [match, unexplained, entry-cost]
line-match: {worse = "lower", pass = 0.90, stop = 0.80, running = 2}
line-unexplained: {worse = "higher", pass = 20, stop = 100}
line-entry-cost: {worse = "higher", pass = 0.43, stop = 0.86}
risk: [day-loss]
line-day-loss: {worse = "higher", stop = 0.52}
ranges: []
gap_parts: [costs, missed, extra]
reasons: [news pause]
changes_allowed: [spread]
changes_stop: [leverage]
---

Trade the tuned settings live, replay them over each week's own dates from the week's own start, and
read each week against the lines above.
"""


def forward_run(tmp_path: Path) -> tuple[Session, str]:
    """T5 up to its seal: the project, the logged run, and its seal merged on its own before day 1."""
    from forward_journal import JOURNAL

    world = World(tmp_path / "forward")
    world.root.mkdir(parents=True)
    world.manifest(FORWARD)
    world.write(".gitignore", ".themis/\n__pycache__/\n")
    world.write("journal.py", JOURNAL)
    world.commit("start")
    session = Session(world)
    assert session.themis("new", "breakout-live", "--question", "does the live run hold up against its replay?") == (
        EXIT_PASS)
    [ledger] = (world.root / "ledger").glob("*.toml")
    study = tomllib.loads(ledger.read_text())["work"]
    world.commit("log the run")
    world.pull_request("seal", {f"{study}/PRE-REG.md": FORWARD_SEAL})
    assert session.themis("calibrate", "forward") == EXIT_PASS
    world.commit("the forward gate's calibration receipt")
    return session, study


def week(session: Session, study: str, name: str, live: list, replay: list | None, **given: object) -> int:
    """One week as the guide runs it: the logs committed, `themis run` writing the record through the
    project's script, then `themis decide`. Returns what decide exited with."""
    from forward_journal import write_logs

    logs = write_logs(session.world.root, name, live, replay, **given)  # type: ignore[arg-type]
    session.world.commit(f"the logs of week {name}")
    inputs = [part for path in logs for part in ("--input", path)]
    assert session.themis("run", study, *inputs, "--", sys.executable, "journal.py", study, name, *logs) == EXIT_PASS
    session.world.commit(f"week {name}")
    code = session.themis("decide", f"{study}/week-{name}", "--gate", "forward")
    session.world.commit(f"week {name}, decided")
    return code


def test_t5_a_forward_run_week_by_week_and_its_corners_cut(tmp_path: Path) -> None:
    from forward_journal import trades

    session, study = forward_run(tmp_path / "honest")
    assert session.verdict("prereg/declared") is Verdict.PASS
    first = trades("2026-48", 20)
    assert week(session, study, "2026-48", first, first) == EXIT_REFUSE  # defer: 20 trades of 60
    second = trades("2026-49", 20)
    assert week(session, study, "2026-49", second[3:], second,
                reasons={trade["id"]: "news pause" for trade in second[:3]}) == EXIT_REFUSE  # look-closer: 0.85
    third = trades("2026-50", 25)
    assert week(session, study, "2026-50", third, third) == EXIT_PASS  # 62 trades, every line inside
    fourth = trades("2026-51", 20)
    assert week(session, study, "2026-51", fourth, fourth, risk=0.61) == EXIT_FAIL  # stop
    for rule_id in ("decision/issued-by-gate", "decision/calibrated", *(f"forward/{name}" for name in FORWARD_RULES)):
        assert session.verdict(rule_id) is Verdict.PASS, rule_id
    assert session.themis("check") == EXIT_PASS
    sessions = [session]

    # Corners cut, one world each.
    session, study = forward_run(tmp_path / "retune")
    first, second = trades("2026-48", 20), trades("2026-49", 20)
    assert week(session, study, "2026-48", first, first) == EXIT_REFUSE
    assert week(session, study, "2026-49", second, second, settings="77c0aa11") == EXIT_REFUSE  # nothing stored
    assert not (session.world.root / "decisions" / f"{study.replace('/', '-')}-week-2026-49.json").exists()
    assert session.themis("check", "forward/no-retune") == EXIT_FAIL
    sessions.append(session)

    session, study = forward_run(tmp_path / "no-replay")
    assert week(session, study, "2026-48", trades("2026-48", 20), None) == EXIT_REFUSE
    assert session.themis("check", "forward/same-dates-control") == EXIT_FAIL
    sessions.append(session)

    session, study = forward_run(tmp_path / "by-hand")
    first = trades("2026-48", 20)
    assert week(session, study, "2026-48", first, first) == EXIT_REFUSE
    stored = session.world.root / "decisions" / f"{study.replace('/', '-')}-week-2026-48.json"
    stored.write_text(json.dumps({**json.loads(stored.read_text()), "decision": "pass", "verdict": "pass"}))
    session.world.commit("a kinder verdict, typed")
    assert session.themis("check", "decision/issued-by-gate") == EXIT_FAIL
    assert session.themis("check", "forward/enough-trades") == EXIT_FAIL
    sessions.append(session)

    every = Session(session.world)
    every.said = [each.text() for each in sessions]
    assert len(quotes("T5")) >= 8
    assert said_as_quoted(every, "T5", study=study) == []


@pytest.mark.parametrize("case", ["G1", "T4", "T5"])
def test_the_guide_has_the_case(case: str) -> None:
    assert quotes(case)


def test_a_quote_this_release_does_not_print_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session(World(tmp_path))
    session.said = ["themis: the command exited 0. The grant is spent; receipt: receipts/action/a.json"]
    monkeypatch.setattr(sys.modules[__name__], "quotes", lambda case: ["the command exited 0", "The grant is kept"])
    assert said_as_quoted(session, "G1") == ["The grant is kept"]
