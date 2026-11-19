"""The forward kind: a live run, held week by week against a replay of the same dates.

The eight rules are proven by their own worlds (themis/packs/trading/forward.py), and the gate by
the shared gate tests. This file holds what lies between them: the builder that makes the gate's
inputs from the seal and the records, and `themis decide` and `themis calibrate` on a forward run.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from themis import engine, gates, pack
from themis import manifest as manifests
from themis.cli import EXIT_PASS, EXIT_REFUSE, main
from themis.packs.trading import forward
from themis.packs.trading.forward import STUDY, changed, seal_text, week_record
from themis.proofs import World
from themis.rule import RULES
from themis.verdict import Verdict

gates.load_all()
pack.load("trading")


def a_run(tmp_path: Path, **given: object) -> World:
    """A forward run as the proofs build it: the seal merged on its own, and an honest week 48 and 49."""
    world = World(tmp_path / "repo")
    world.root.mkdir(parents=True)
    forward._forward(world, **given)  # type: ignore[arg-type]
    return world


def built(world: World, week: str) -> dict:
    return forward.build(world.root, manifests.load(world.root), f"{STUDY}/week-{week}")


def verdict(world: World, rule_id: str) -> Verdict | None:
    return engine.run_rule(RULES[rule_id], manifests.load(world.root), force=True).verdict


def themis(world: World, *args: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main([args[0], "--root", str(world.root), *args[1:]])
    return code, out.getvalue()


# -- the inputs, built from the seal and the records --------------------------------------------


def test_the_inputs_hold_the_seals_lines_and_every_week_up_to_the_one_decided(tmp_path: Path) -> None:
    world = a_run(tmp_path, weeks=(48, 49, 50))
    first, second = built(world, "2026-48"), built(world, "2026-49")
    assert first["subject"] == f"{STUDY}/week-2026-48" and [week["week"] for week in first["weeks"]] == ["2026-48"]
    assert [week["week"] for week in second["weeks"]] == ["2026-48", "2026-49"]  # not week 50: it came later
    assert second["seal"]["lines"]["match"] == {"worse": "lower", "pass": 0.9, "stop": 0.8, "running": 2, "min": 0}
    assert second["seal"]["lines"]["unexplained"] == {"worse": "higher", "pass": 20.0, "stop": 100.0, "running": 1,
                                                      "min": 0}
    assert second["seal"]["risk"] == {"day-loss": {"worse": "higher", "stop": 0.52}}
    week = second["weeks"][1]
    assert (week["matched"], week["missed"], week["extra"], week["trades"]) == (19, 1, 0, 20)
    assert week["reasons"] == ["news pause"] and week["unexplained"] == -3.0
    assert week["lines"] == {"entry-cost": {"value": 0.3, "n": 38}} and week["risk"] == {"day-loss": 0.2}
    assert json.loads(json.dumps(second)) == second  # what is stored reads back as what was built
    answer = forward.forward(second)
    assert (answer["decision"], answer["numbers"]["trades_to_date"]) == ("pass", 40)


def test_a_range_day_is_read_in_the_week_that_holds_it(tmp_path: Path) -> None:
    """Day N is N days after the run's first week began: day 3 falls in its first week, day 10 in its second."""
    seal = {"ranges": "[3, 10]", "range-3": "{low = 9000, high = 11000}", "range-10": "{low = 9000, high = 11000}"}
    world = a_run(tmp_path, seal=seal, changes={48: {"range": {"3": 10100.0}}, 49: {"range": {"10": 12000.0}}})
    first, second = built(world, "2026-48")["weeks"][0], built(world, "2026-49")["weeks"][1]
    assert (first["range_due"], first["range"]) == (["3"], {"3": 10100.0})
    assert (second["range_due"], second["range"]) == (["10"], {"10": 12000.0})
    assert forward.forward(built(world, "2026-49"))["decision"] == "look-closer"  # 12000 is above the range


@pytest.mark.parametrize(("subject", "changes", "said"), [
    ("work/fwd", {}, "named <study>/week-YYYY-WW"),
    ("work/other/week-2026-48", {}, "work/other is not a study sealed as kind forward"),
    (f"{STUDY}/week-2026-51", {}, f"there is no record {STUDY}/results/week-2026-51.json"),
    (f"{STUDY}/week-2026-49", {48: {"replay": None}}, "week 2026-48 has no replay"),
    (f"{STUDY}/week-2026-48", {48: {"live.settings": "77c0aa11", "replay.settings": "77c0aa11"}},
     "week 2026-48 traded the settings 77c0aa11, and the seal's are 3f9a0c1d: a settings change ends the run"),
    (f"{STUDY}/week-2026-48", {48: {"replay.settings": "77c0aa11"}}, "week 2026-48's replay used the settings 77c0aa11"),
    (f"{STUDY}/week-2026-48", {49: {"period.from": "2026-11-30T00:00:00"}}, "the forward run cannot be read"),
])
def test_the_builder_refuses_what_it_cannot_build(tmp_path: Path, subject: str, changes: dict, said: str) -> None:
    world = a_run(tmp_path, changes=changes)
    with pytest.raises(ValueError, match=said.replace("(", r"\(").replace(".", r"\.")):
        forward.build(world.root, manifests.load(world.root), subject)


# -- themis decide and themis calibrate ---------------------------------------------------------


def test_a_week_is_decided_from_its_records_and_the_gate_is_calibrated(tmp_path: Path) -> None:
    world = a_run(tmp_path)
    world.commit("two weeks")
    code, said = themis(world, "decide", f"{STUDY}/week-2026-48", "--gate", "forward")
    assert code == EXIT_REFUSE and "defer. 20 trades so far, and the seal asks for 40 before any pass" in said
    code, said = themis(world, "decide", f"{STUDY}/week-2026-49", "--gate", "forward")
    assert code == EXIT_PASS and "PASS: pass. every line is inside its pass" in said
    stored = json.loads((world.root / "decisions/work-fwd-week-2026-49.json").read_text())
    assert stored["inputs"] == "decision-inputs/work-fwd-week-2026-49.json" and stored["gate_version"] == "1"
    assert stored["numbers"]["conditions_changes"] == [] and stored["enough_evidence"] is True
    code, said = themis(world, "calibrate", "forward")
    assert code == EXIT_PASS and "trading/forward v1: says yes to noise 0.0% of the time" in said
    receipt = json.loads((world.root / "receipts/calibration/trading-forward.json").read_text())
    assert (receipt["false_alarm_rate"], receipt["power"]) == (0.0, 1.0)
    for rule_id in ("decision/issued-by-gate", "decision/enough-evidence", "decision/calibrated", "forward/match",
                    "forward/conditions-stable", "forward/enough-trades", "forward/risk-line"):
        assert verdict(world, rule_id) is Verdict.PASS, rule_id


def test_a_week_with_no_replay_is_refused_at_decide_and_nothing_is_stored(tmp_path: Path) -> None:
    world = a_run(tmp_path, changes={48: {"replay": None}})
    code, said = themis(world, "decide", f"{STUDY}/week-2026-48", "--gate", "forward")
    assert code == EXIT_REFUSE and "week 2026-48 has no replay" in said
    assert not (world.root / "decisions").exists() and not (world.root / "decision-inputs").exists()


def test_a_kinder_line_typed_into_the_stored_inputs_fails_the_rebuild_and_not_the_gate(tmp_path: Path) -> None:
    """The gate reads only what it is given, so a decision re-asked of it on typed inputs agrees: it is
    the rebuild that catches the typing."""
    world = a_run(tmp_path, decided=None, changes={49: {"entries.matched": [], "entries.missed": [
        {"id": f"e{n}", "at": forward._at(49, 10 + n), "reason": "news pause"} for n in range(1, 21)]}},
        inputs={49: {"seal.lines.match.pass": 0.0, "seal.lines.match.stop": 0.0}},
        typed={49: {"decision": "pass", "verdict": "pass"}})
    assert verdict(world, "decision/issued-by-gate") is Verdict.PASS
    assert verdict(world, "forward/match") is Verdict.FAIL


# -- a project with no forward run, and the rules that bind every kind --------------------------

FORWARD_RULES = sorted(rule_id for rule_id in RULES if rule_id.startswith("forward/"))
STANDARD = """
[project]
name = "research"
packs = ["trading"]
standard = "themis-trading/1"

[trading]
work = "work/*"

[rules]
"prereg/declared" = "enforce"
""" + "".join(f'"{rule_id}" = "enforce"\n' for rule_id in FORWARD_RULES)


def test_a_standard_project_with_no_forward_run_finds_each_forward_rule_not_configured(tmp_path: Path) -> None:
    """The standard holds the eight forward rules at enforce. A project that runs no forward run sets
    them so and is not refused for it: each says what it would need, and decides nothing."""
    from themis import standards

    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest(STANDARD)
    world.write("work/a/PRE-REG.md", "---\nkind: tune\nwindows: [w]\nwindow-w: {from = \"2025-01-01\", to = "
                                     "\"2025-12-31\"}\ngate: tune\niterations: 9\nrisk_rules: r.json\n---\n")
    world.commit("a tune study, and no forward run")
    manifest = manifests.load(world.root)
    report = engine.run(manifest)
    found = {result.id: result for result in report.results}
    assert len(FORWARD_RULES) == 8
    for rule_id in FORWARD_RULES:
        assert found[rule_id].status == "not configured", rule_id
        assert "seal a study as kind forward" in found[rule_id].note and not found[rule_id].counts
    assert found["prereg/declared"].verdict is Verdict.PASS and report.verdict is Verdict.PASS
    standard = standards.declared(manifest)
    assert standard is not None and set(FORWARD_RULES) <= set(standard.levels)
    assert standard.floors["forward/enough-trades"] == {"min_trades": 30}
    assert not [found for found in standards.deviations(manifest, standard) if found.rule.startswith("forward/")]
    (world.root / "themis.toml").write_text(STANDARD.replace('"forward/match" = "enforce"', ""), encoding="utf-8")
    below = standards.deviations(manifests.load(world.root), standard)
    assert [(found.rule, found.what) for found in below if found.rule.startswith("forward/")] == [
        ("forward/match", "level is warn; the standard requires enforce")]


@pytest.mark.parametrize("rule_id", ["scorecard/believable", "scorecard/explainer"])
def test_the_scorecard_rules_bind_a_forward_run_unless_kinds_says_otherwise(tmp_path: Path, rule_id: str) -> None:
    world = a_run(tmp_path)
    assert verdict(world, rule_id) is Verdict.FAIL  # a forward run with records answers like any study
    world.manifest(forward.MANIFEST + forward._rule(rule_id, 'kinds = ["strategy", "signal"]'))
    assert verdict(world, rule_id) is Verdict.REFUSE  # not bound: nothing is left to inspect


def test_the_seal_and_the_weekly_record_read_as_their_schemas_say() -> None:
    from themis import records

    assert set(forward.WEEK) == {"week", "period", "live", "replay", "entries", "fill_costs", "gap", "lines",
                                 "conditions", "risk", "range"}
    seal, problems = forward.read_seal(f"{STUDY}/PRE-REG.md", records.frontmatter(seal_text()) or {})
    assert problems == [] and seal is not None and (seal.min_trades, seal.gap_parts) == (40, ("spread", "commission",
                                                                                               "swap"))
    week, problems = forward.read_week(f"{STUDY}/results/week-2026-48.json", json.dumps(week_record(48)))
    assert problems == [] and week is not None and week.name == "2026-48"
    assert forward.read_week(f"{STUDY}/results/week-2026-54.json", "{}")[1] == ["2026 has no ISO week 54"]
    assert "named by its ISO week" in forward.read_week(f"{STUDY}/results/week-48.json", "{}")[1][0]
    typed = changed(week_record(48), {"lines.match": {"value": 1.0, "n": 20}})
    assert "which Themis computes from the record itself" in forward.read_week(
        f"{STUDY}/results/week-2026-48.json", json.dumps(typed))[1][0]
    missing = changed(week_record(48), {"fill_costs": forward.DROP})
    assert forward.read_week(f"{STUDY}/results/week-2026-48.json", json.dumps(missing))[1] == [
        "the record.fill_costs is required"]
