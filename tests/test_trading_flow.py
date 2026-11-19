"""The trading pack, end to end: a study's files become its scorecard, its report and its decision.

The point of the pack is that none of the three is typed. These tests build them with the real
commands, check that the rules accept what was built, and then try to slip a typed one past.
"""

from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path

import pytest

from themis import engine
from themis import manifest as manifests
from themis.cli import EXIT_FAIL, EXIT_PASS, EXIT_REFUSE, main
from themis.packs.trading import data, gates, scorecard, units
from themis.packs.trading.trades import Trade, write_trades
from themis.proofs import World
from themis.verdict import Verdict

MANIFEST = """
[project]
name = "research"
packs = ["trading"]

[trading]
work = "work/*"

[trading.windows.holdout]
from = "2022-01-01"
to = "2024-12-31"
sealed = true
"""
SEAL = "---\nkind: {kind}\ntitle: Opening drive\n---\n\nThe plan.\n"
CARD = {"start_capital": 1000.0, "baselines": {"always_long": 1010.0, "always_short": 990.0},
        "oos_start": "2026-03-01", "trial_sharpes": [0.2, 0.1, 0.4], "sensitivity": [1020.0, 1005.0]}
BUILT = ("report/generated", "report/readable", "scorecard/complete", "scorecard/rendering", "validity/baselines")


def _trades(nets: tuple[float, ...] = (30.0, -12.0, 18.0, 9.0)) -> list[Trade]:
    return [Trade(dt.datetime(2026, month, 5, 10), dt.datetime(2026, month, 6, 10), "long" if month % 2 else "short",
                  1.0, 100.0, 100.0 + net, 1.0, net, mfe=abs(net) + 2.0)
            for month, net in enumerate(nets, start=1)]


def study(tmp_path: Path, kind: str = "strategy", card: dict | None = None, booked: bool = True) -> World:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest(MANIFEST)
    world.write("ledger/a.toml", 'work = "work/a"\n')
    world.write("work/a/PRE-REG.md", SEAL.format(kind=kind))
    world.write("work/a/results/metrics.json", json.dumps({"scorecard": CARD if card is None else card}))
    if booked:
        write_trades(_trades(), world.root / "work/a/results/trades.csv")
    return world


def run(world: World, *args: str) -> int:
    return main([args[0], "--root", str(world.root), *args[1:]])


def verdict(world: World, rule_id: str) -> Verdict | None:
    return engine.run(manifests.load(world.root), only={rule_id}).results[0].verdict


def page(world: World) -> str:
    return (world.root / "work/a" / units.REPORT).read_text(encoding="utf-8")


# -- the report ----------------------------------------------------------------------------------


def test_the_report_command_builds_a_scorecard_and_a_page_the_rules_accept(tmp_path: Path) -> None:
    world = study(tmp_path)
    assert run(world, "report", "a") == EXIT_PASS
    lines = {line.id: line for line in scorecard.read_csv(world.root / "work/a" / units.SCORECARD)}
    assert lines["end_money"].value == 1045.0 and not [line.id for line in lines.values() if line.not_run]
    assert "Opening drive" in page(world)
    for rule_id in BUILT:
        assert verdict(world, rule_id) is Verdict.PASS, rule_id


def test_a_page_left_behind_by_a_later_run_is_caught_and_building_again_clears_it(tmp_path: Path) -> None:
    world = study(tmp_path)
    assert run(world, "report", "work/a") == EXIT_PASS
    write_trades(_trades((30.0, -12.0, 18.0, -40.0)), world.root / "work/a/results/trades.csv")
    assert verdict(world, "report/generated") is Verdict.FAIL
    assert run(world, "report", "work/a") == EXIT_PASS
    assert verdict(world, "report/generated") is Verdict.PASS


def test_a_number_typed_into_the_page_does_not_survive_the_next_build(tmp_path: Path) -> None:
    world = study(tmp_path)
    assert run(world, "report", "a") == EXIT_PASS
    first = page(world)
    (world.root / "work/a" / units.REPORT).write_text(first.replace("1,045", "9,045"), encoding="utf-8")
    assert run(world, "report", "a") == EXIT_PASS
    assert page(world) == first  # the same files give the same page, byte for byte


def test_the_page_says_whether_a_second_script_checked_the_numbers(tmp_path: Path) -> None:
    world = study(tmp_path)
    assert run(world, "report", "a") == EXIT_PASS
    assert "Checked by a second, separate script: NOT RUN" in page(world)
    world.write("work/a/AUDIT.md", "---\nstatus: reproduced\nscript: audit.py\n---\n\nReproduced.\n")
    assert verdict(world, "report/generated") is Verdict.FAIL  # the audit is one of the page's inputs
    assert run(world, "report", "a") == EXIT_PASS
    assert "Checked by a second, separate script: YES" in page(world)


def test_an_input_left_out_is_a_line_marked_not_run_and_the_rule_asks_why(tmp_path: Path) -> None:
    world = study(tmp_path, card={"start_capital": 1000.0})
    assert run(world, "report", "a") == EXIT_PASS
    assert "NOT RUN" in page(world)
    assert verdict(world, "scorecard/complete") is Verdict.FAIL
    assert verdict(world, "validity/baselines") is Verdict.FAIL


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda world: (world.root / "work/a/results/trades.csv").unlink(), "has no trade table"),
        (lambda world: world.write("work/a/results/metrics.json", '{"scorecard": {"start_capitol": 1000}}'), "start_capitol"),
        (lambda world: world.write("work/a/results/metrics.json", "{}"), "start_capital"),
        (lambda world: world.write("work/a/results/trades.csv", "entry_time,net\n2026-01-05,3\n"), "standard trade table"),
        (lambda world: world.write("work/a/results/metrics.json", "{not json"), "cannot be read"),
    ],
    ids=["no trade table", "a misspelt input", "no starting money", "a table off the standard", "metrics that are not JSON"],
)
def test_a_study_that_cannot_carry_a_report_is_refused_and_nothing_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change, said: str,
) -> None:
    world = study(tmp_path)
    change(world)
    assert run(world, "report", "a") == EXIT_REFUSE
    assert said in capsys.readouterr().err
    assert not (world.root / "work/a" / units.REPORT).exists() and not (world.root / "work/a" / units.SCORECARD).exists()


def test_a_signal_study_that_books_no_trades_still_ships_a_page_that_says_so(tmp_path: Path) -> None:
    world = study(tmp_path, kind="signal", card={}, booked=False)
    assert run(world, "report", "a") == EXIT_PASS
    lines = {line.id: line for line in scorecard.read_csv(world.root / "work/a" / units.SCORECARD)}
    assert lines["trades"].value == 0
    assert verdict(world, "report/generated") is Verdict.PASS


# -- the decision --------------------------------------------------------------------------------


def decided(tmp_path: Path, edge: float) -> World:
    world = study(tmp_path)
    metrics = {**gates.entry_case(random.Random(7), edge), "mde": 0.5, "scorecard": CARD}
    world.write("work/a/results/metrics.json", json.dumps(metrics))
    return world


def test_the_gate_issues_the_decision_from_the_studys_numbers_and_it_checks_clean(tmp_path: Path) -> None:
    world = decided(tmp_path, edge=1.0)
    assert run(world, "decide", "a", "--gate", "entry") == EXIT_PASS
    stored = json.loads((world.root / "decisions/work-a.json").read_text())
    assert (stored["decision"], stored["verdict"]) == ("promote", "pass")
    assert verdict(world, "decision/issued-by-gate") is Verdict.PASS


def test_noise_is_not_promoted_and_a_kinder_decision_typed_over_it_fails(tmp_path: Path) -> None:
    world = decided(tmp_path, edge=0.0)
    assert run(world, "decide", "a", "--gate", "entry") in (EXIT_FAIL, EXIT_REFUSE)
    path = world.root / "decisions/work-a.json"
    stored = json.loads(path.read_text())
    assert stored["decision"] != "promote"
    path.write_text(json.dumps({**stored, "decision": "promote", "verdict": "pass"}))
    assert verdict(world, "decision/issued-by-gate") is Verdict.FAIL


@pytest.mark.parametrize(("used", "expected"), [("Real Ticks", Verdict.PASS), ("open prices only", Verdict.FAIL)])
def test_a_tune_pass_from_the_gate_carries_its_confirming_model_to_the_validity_rule(
        tmp_path: Path, used: str, expected: Verdict) -> None:
    world = study(tmp_path, kind="tune", booked=False)
    world.manifest(MANIFEST + '\n[trading.tune]\nconfirm_model = "real ticks"\n')
    world.write("work/a/results/metrics.json", json.dumps({**gates.tune_case(), "confirm_model": used}))
    assert run(world, "decide", "a", "--gate", "tune") == EXIT_PASS
    [stored] = [json.loads(path.read_text()) for path in (world.root / "decisions").glob("*.json")]
    assert (stored["decision"], stored["numbers"]["confirm_model"]) == ("full-pass", used)
    assert verdict(world, "validity/confirm-on-real-ticks") is expected


# -- the sealed window ---------------------------------------------------------------------------


def test_a_look_at_sealed_data_leaves_a_receipt_the_core_grant_rules_accept(tmp_path: Path) -> None:
    world = study(tmp_path)
    assert run(world, "grant", "holdout", "holdout", "--reason", "the plan is sealed") == EXIT_PASS
    grant = next((world.root / "grants").glob("*.toml")).stem
    assert data.window(world.root, manifests.load(world.root), "holdout", grant=grant, study="work/a") == (
        "2022-01-01", "2024-12-31")
    for rule_id in ("holdout/guarded", "grant/required", "grant/single-use"):
        assert verdict(world, rule_id) is Verdict.PASS, rule_id
    with pytest.raises(data.SealedWindow):  # the same yes does not open the window a second time
        data.window(world.root, manifests.load(world.root), "holdout", grant=grant, study="work/a")


def test_a_look_recorded_with_no_grant_fails_the_core_rule_too(tmp_path: Path) -> None:
    world = study(tmp_path)
    world.write("receipts/action/by-hand.json", json.dumps({
        "kind": "action", "action": "holdout", "target": "holdout", "at": "2026-03-04T12:00:00+00:00"}))
    assert verdict(world, "grant/required") is Verdict.FAIL
