"""The marketing pack's results gate, its calibration, and the loop report.

Each decision path of the gate is walked with numbers small enough to check by hand. The gate is
then shown plain noise and a planted effect, and held to the limits the core sets for any gate.
The rules of the consistency, spend and results gates are proven by their own worlds, which
`test_proofs.py` runs; here they are only shown to stay silent until a project configures them.
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

import pytest

from themis import engine, pack, proofs
from themis import manifest as manifests
from themis.pack import kit
from themis.packs.marketing import loop_report, spend
from themis.packs.marketing.gate import gate, noise_share
from themis.proofs import World
from themis.rule import PROOFS, Proof
from themis.verdict import Verdict

marketing = pack.load("marketing")
HIGH = [14, 15, 16, 14, 15, 16]  # six goal numbers with a mean of 15
LOW = [9, 10, 11, 9, 10, 11]  # six goal numbers with a mean of 10
NEAR = [10.2, 9.8, 11, 9, 10.5, 10.1]  # a mean of 10.1, against 10: a difference far inside the spread
SETUP = """
    [project]
    packs = ["marketing"]

    [marketing]
    work = "content/*"

    [marketing.spend]
    unit = "credits"

    [marketing.results]
    baseline = "own-median"
"""


def items_of(goals: list[float], second: float = 20, views: float = 1000) -> list[dict[str, float]]:
    return [{"goal": goal, "second": second, "views": views} for goal in goals]


def metrics(ours: list[dict[str, float]], theirs: list[dict[str, float]] | None = None, **more: Any) -> dict[str, Any]:
    """The subject `new`, its rival `old` when one is given, and a baseline of 1,000 views."""
    series = {"new": ours} if theirs is None else {"new": ours, "old": theirs}
    rival = None if theirs is None else "old"
    return {"series": series, "subject": "new", "rival": rival, "baseline_views": 1000, **more}


def decided(table: dict[str, Any]) -> tuple[str, str, bool]:
    answer = gate(table)
    assert set(answer) == {"decision", "verdict", "enough_evidence", "reason", "numbers"}
    assert answer["reason"].strip()
    return answer["decision"], answer["verdict"], answer["enough_evidence"]


def world(tmp_path: Path, setup: str = SETUP) -> World:
    built = World(tmp_path / "repo")
    built.root.mkdir(parents=True)
    built.manifest(setup)
    return built


# --- too few -----------------------------------------------------------------------------------


def test_too_few_items_is_a_refusal_and_not_a_no() -> None:
    weak = items_of([1, 1], second=1, views=100)  # lower than its rival on everything, but only two items
    assert decided(metrics(weak, items_of(HIGH))) == ("too-few", "refuse", False)
    assert gate(metrics(weak, items_of(HIGH)))["numbers"]["items"] == 2


def test_too_few_is_said_before_anything_else_is_asked_for() -> None:
    table = metrics(items_of([1, 1], views=9000))  # a standout by its views, and still too few
    del table["baseline_views"]
    assert decided(table) == ("too-few", "refuse", False)


def test_the_project_sets_how_many_items_are_enough_to_judge() -> None:
    assert decided(metrics(items_of([1, 1]), min_items_to_judge=2)) == ("keep", "pass", True)
    assert decided(metrics(items_of([1, 1, 1]), min_items_to_judge=4)) == ("too-few", "refuse", False)


# --- standout ----------------------------------------------------------------------------------


def test_one_item_far_above_the_baseline_is_a_standout_whatever_the_rival_says() -> None:
    ours = items_of(LOW, second=1, views=500)
    ours[2]["views"] = 5000  # exactly five times the baseline
    assert decided(metrics(ours, items_of(HIGH))) == ("standout", "pass", True)
    assert gate(metrics(ours, items_of(HIGH)))["numbers"]["top_views"] == 5000


def test_an_item_just_under_the_standout_line_is_not_one() -> None:
    ours = items_of(LOW, second=30)
    ours[2]["views"] = 4999
    assert decided(metrics(ours, items_of(HIGH)))[0] == "keep"
    assert decided(metrics(ours, items_of(HIGH), standout_views_times=4))[0] == "standout"


# --- lead, keep, retire ------------------------------------------------------------------------


def test_the_series_higher_on_the_goal_number_leads() -> None:
    answer = gate(metrics(items_of(HIGH), items_of(LOW)))
    assert (answer["decision"], answer["verdict"], answer["enough_evidence"]) == ("lead", "pass", True)
    numbers = answer["numbers"]
    assert (numbers["mean_goal"], numbers["rival_mean_goal"], numbers["within_noise"]) == (15, 10, False)
    assert numbers["noise_share"] <= 0.05


def test_lower_on_the_goal_number_and_higher_on_the_second_is_kept() -> None:
    answer = gate(metrics(items_of(LOW, second=30, views=500), items_of(HIGH)))
    assert (answer["decision"], answer["verdict"]) == ("keep", "pass")
    assert "higher on the second number" in answer["reason"]


def test_lower_on_both_numbers_with_weak_views_is_retired_with_enough_evidence() -> None:
    answer = gate(metrics(items_of(LOW, second=10, views=500), items_of(HIGH)))
    assert (answer["decision"], answer["verdict"], answer["enough_evidence"]) == ("retire", "fail", True)
    assert answer["numbers"]["within_noise"] is False
    assert answer["numbers"]["median_views"] == 500


def test_lower_on_both_numbers_is_kept_while_its_views_hold_up() -> None:
    on_the_line = items_of(LOW, second=10, views=700)  # 0.7 of the baseline exactly: not under it
    assert decided(metrics(on_the_line, items_of(HIGH))) == ("keep", "pass", True)
    assert decided(metrics(items_of(LOW, second=10, views=699), items_of(HIGH)))[0] == "retire"
    assert decided(metrics(items_of(LOW, second=10, views=500), items_of(HIGH), retire_views_share=0.4))[0] == "keep"


def test_a_tie_on_either_number_is_kept() -> None:
    assert decided(metrics(items_of(LOW, second=10, views=500), items_of(LOW)))[0] == "keep"  # the same goal number
    assert decided(metrics(items_of(LOW, views=500), items_of(HIGH)))[0] == "keep"  # the same second number


def test_a_series_with_no_rival_or_too_few_items_to_rank_is_kept() -> None:
    assert decided(metrics(items_of(HIGH))) == ("keep", "pass", True)
    answer = gate(metrics(items_of(HIGH[:5]), items_of(LOW)))
    assert (answer["decision"], "ranking needs 6 items" in answer["reason"]) == ("keep", True)
    assert decided(metrics(items_of(LOW, second=10, views=500), items_of(HIGH[:5])))[0] == "keep"  # the rival is short


def test_the_project_sets_how_many_items_are_enough_to_rank() -> None:
    four = metrics(items_of(HIGH[:4]), items_of(LOW[:4]))
    assert decided(four)[0] == "keep"
    assert decided({**four, "min_items_to_rank": 4})[0] == "lead"


# --- the noise band ----------------------------------------------------------------------------


def test_a_difference_inside_the_noise_is_kept_and_says_so() -> None:
    answer = gate(metrics(items_of(NEAR), items_of(LOW)))
    assert (answer["decision"], answer["verdict"]) == ("keep", "pass")
    assert "within the noise" in answer["reason"]
    assert answer["numbers"]["within_noise"] is True


def test_with_the_noise_band_off_the_same_numbers_lead_and_carry_no_test() -> None:
    answer = gate(metrics(items_of(NEAR), items_of(LOW), noise_band=False))
    assert answer["decision"] == "lead"
    assert "within_noise" not in answer["numbers"]  # so the rule results/noise-band flags the decision


def test_a_weak_series_is_not_retired_on_a_difference_inside_the_noise() -> None:
    answer = gate(metrics(items_of(LOW, second=10, views=500), items_of(NEAR)))
    assert (answer["decision"], answer["numbers"]["within_noise"]) == ("keep", True)


@pytest.mark.parametrize("seed", range(6))
def test_results_shuffled_between_two_series_show_no_lead(seed: int) -> None:
    pooled = HIGH + LOW  # a clear lead, until the numbers are dealt out again at random
    random.Random(seed).shuffle(pooled)
    assert decided(metrics(items_of(pooled[:6]), items_of(pooled[6:])))[0] == "keep"


def test_the_share_of_shuffles_is_all_of_them_for_equal_groups_and_none_for_groups_far_apart() -> None:
    assert noise_share([1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6]) == 1.0
    assert noise_share([1, 2, 3, 4, 5, 6], [11, 12, 13, 14, 15, 16]) <= 0.01
    assert noise_share(NEAR, LOW) == noise_share(NEAR, LOW)  # a fixed seed: the same numbers, the same share


# --- missing and malformed inputs --------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"series": None}, "series must be a table"),
        ({"series": {"new": "six items"}}, "series must be a table"),
        ({"series": {"new": [{"goal": 1, "second": 2}]}}, "must hold the numbers goal, second and views"),
        ({"series": {"new": [{"goal": True, "second": 2, "views": 3}]}}, "must hold the numbers"),
        ({"series": {"new": [{"goal": float("nan"), "second": 2, "views": 3}]}}, "must hold the numbers"),
        ({"series": {"new": ["an item"]}}, "must hold the numbers"),
        ({"subject": None}, "subject must name a series"),
        ({"subject": "missing"}, "subject must name a series"),
        ({"rival": "missing"}, "rival must name another series"),
        ({"rival": "new"}, "rival must name another series"),
        ({"baseline_views": 0}, "baseline_views must be a number above zero"),
        ({"baseline_views": "high"}, "baseline_views must be a number above zero"),
        ({"baseline_views": None}, "baseline_views must be a number above zero"),
        ({"min_items_to_judge": 2.5}, "min_items_to_judge must be a whole number"),
        ({"min_items_to_rank": 0}, "min_items_to_rank must be a whole number"),
        ({"retire_views_share": -1}, "retire_views_share must be a number above zero"),
        ({"standout_views_times": "five"}, "standout_views_times must be a number above zero"),
        ({"noise_band": "yes"}, "noise_band must be true or false"),
        ({"baseline": 3}, "baseline must be the name"),
    ],
)
def test_a_malformed_input_is_refused_and_named(change: dict[str, Any], said: str) -> None:
    answer = gate({**metrics(items_of(HIGH), items_of(LOW)), **change})
    assert (answer["decision"], answer["verdict"], answer["enough_evidence"]) == ("unreadable", "refuse", False)
    assert said in answer["reason"]


@pytest.mark.parametrize("table", ["a sentence", None, [], {}])
def test_metrics_that_are_not_a_filled_table_are_refused(table: Any) -> None:
    assert decided(table) == ("unreadable", "refuse", False)


def test_a_missing_baseline_is_refused_once_there_are_enough_items_to_judge() -> None:
    table = metrics(items_of(HIGH), items_of(LOW))
    del table["baseline_views"]
    answer = gate(table)
    assert (answer["decision"], answer["verdict"]) == ("unreadable", "refuse")
    assert "baseline_views" in answer["reason"]


# --- the same numbers, the same answer ---------------------------------------------------------


def test_the_gate_gives_the_same_answer_twice_and_leaves_its_metrics_alone() -> None:
    table = metrics(items_of(NEAR, second=10, views=500), items_of(HIGH), baseline="own-median")
    before = copy.deepcopy(table)
    assert gate(table) == gate(table)
    assert table == before


def test_the_baselines_name_is_copied_into_every_answer_that_was_read() -> None:
    assert gate(metrics(items_of(HIGH), items_of(LOW), baseline="own-median"))["numbers"]["baseline"] == "own-median"
    assert gate(metrics(items_of([1]), baseline="own-median"))["numbers"]["baseline"] == "own-median"
    assert "baseline" not in gate(metrics(items_of(HIGH)))["numbers"]


def test_the_thresholds_the_gate_used_are_in_its_numbers() -> None:
    numbers = gate(metrics(items_of(HIGH), items_of(LOW), min_items_to_rank=5, retire_views_share=0.6))["numbers"]
    used = {name: numbers[name] for name in ("min_items_to_judge", "min_items_to_rank", "retire_views_share",
                                              "standout_views_times", "noise_band")}
    assert used == {"min_items_to_judge": 3, "min_items_to_rank": 5, "retire_views_share": 0.6,
                    "standout_views_times": 5, "noise_band": True}


# --- calibration: the gate says no to noise and yes to a planted effect ------------------------


@pytest.fixture(scope="module")
def measured() -> dict[str, Any]:
    return kit.calibrate(marketing, "results")


def test_the_gate_rarely_calls_noise_a_difference(measured: dict[str, Any]) -> None:
    assert measured["false_alarm_rate"] is not None
    assert measured["false_alarm_rate"] <= 0.10


def test_the_gate_finds_a_planted_effect(measured: dict[str, Any]) -> None:
    assert measured["power"] is not None
    assert measured["power"] >= 0.80


def test_the_calibration_has_a_noise_case_and_a_planted_case(measured: dict[str, Any]) -> None:
    assert sorted(case["kind"] for case in measured["cases"]) == ["noise", "planted"]
    assert (marketing.gates["results"], measured["gate_version"]) == (gate, "1")
    assert not [problem for problem in kit.problems(marketing) if problem.startswith(("gate ", "calibration"))]


# --- the gate under the core's decision rules --------------------------------------------------


def issue(built: World, table: dict[str, Any], **changes: Any) -> None:
    """Write the metrics of the series `new`, and the decision the gate issues on them."""
    built.write("series/new/results/metrics.json", json.dumps(table))
    record = {"work": "series/new", "gate": "results", "gate_version": "1", "decided_at": "2026-03-10T09:00:00+00:00"}
    built.write("decisions/new.json", json.dumps({**record, **gate(table), **changes}))


CHECKED = ("decision/issued-by-gate", "decision/enough-evidence", "results/own-baseline", "results/noise-band")
ISSUED = {
    "lead": (items_of(HIGH), items_of(LOW)),
    "retire": (items_of(LOW, second=10, views=500), items_of(HIGH)),
    "keep": (items_of(NEAR), items_of(LOW)),
    "too-few": (items_of([1]), items_of(LOW)),
}


@pytest.mark.parametrize("rule_id", CHECKED)
@pytest.mark.parametrize("decision", sorted(ISSUED))
def test_a_decision_issued_by_the_gate_holds_under_the_rules(tmp_path: Path, decision: str, rule_id: str) -> None:
    built = world(tmp_path)
    table = metrics(*ISSUED[decision], baseline="own-median")
    assert gate(table)["decision"] == decision
    issue(built, table)
    result = proofs.judge(built.root, rule_id)
    assert result.verdict is Verdict.PASS, [finding.message for finding in result.findings]


def test_a_kinder_decision_typed_over_the_gates_answer_fails(tmp_path: Path) -> None:
    built = world(tmp_path)
    issue(built, metrics(items_of(NEAR), items_of(LOW), baseline="own-median"), decision="lead")
    result = proofs.judge(built.root, "decision/issued-by-gate")
    assert result.verdict is Verdict.FAIL
    assert "but the gate results returns 'keep'" in result.findings[0].message
    assert proofs.judge(built.root, "results/noise-band").verdict is Verdict.FAIL  # a lead, inside the noise


def test_a_lead_issued_with_the_noise_band_off_is_flagged(tmp_path: Path) -> None:
    built = world(tmp_path)
    issue(built, metrics(items_of(NEAR), items_of(LOW), baseline="own-median", noise_band=False))
    assert proofs.judge(built.root, "decision/issued-by-gate").verdict is Verdict.PASS
    found = proofs.judge(built.root, "results/noise-band")
    assert found.verdict is Verdict.FAIL
    assert "was never tested against the noise" in found.findings[0].message


# --- rules that a project has not configured do not run ----------------------------------------


@pytest.mark.parametrize(
    ("rule_id", "missing"),
    [
        ("spend/priced-first", "run_ceiling"), ("results/recorded", "min_age_days"),
        ("results/purpose-sealed", "[marketing.purposes]"), ("consistency/rulebook-pinned", "pins"),
        ("spend/figures-from-tools", "documents"), ("consistency/derived-matches", "work"),
    ],
)
def test_a_rule_the_project_has_not_configured_is_not_run_and_says_what_to_set(
    tmp_path: Path, rule_id: str, missing: str,
) -> None:
    built = world(tmp_path, '[project]\npacks = ["marketing"]\n')
    report = engine.run(manifests.load(built.root), only={rule_id})
    assert [(result.status, result.verdict) for result in report.results] == [("not configured", None)]
    assert missing in report.results[0].note


def test_the_baseline_rule_waits_for_a_declared_baseline(tmp_path: Path) -> None:
    built = world(tmp_path, '[project]\npacks = ["marketing"]\n\n[marketing]\nwork = "content/*"\n')
    result = engine.run(manifests.load(built.root), only={"results/own-baseline"}).results[0]
    assert (result.status, "baseline" in result.note) == ("not configured", True)


# --- what a finding carries --------------------------------------------------------------------

MINE = ("consistency/", "spend/", "results/")
PLANTED = [proof for rule_id in sorted(PROOFS) if rule_id.startswith(MINE) for proof in PROOFS[rule_id]
           if proof.expect is Verdict.FAIL]


@pytest.mark.parametrize("planted", PLANTED, ids=[f"{proof.rule}: {proof.name}" for proof in PLANTED])
def test_every_breach_says_where_it_is_and_how_to_fix_it(tmp_path: Path, planted: Proof) -> None:
    built = world(tmp_path)
    planted.build(built)
    breaches = [finding for finding in proofs.judge(built.root, planted.rule).findings if finding.kind == "breach"]
    assert breaches
    assert all(finding.where and finding.fix for finding in breaches), breaches


def test_a_breach_inside_a_file_names_its_line(tmp_path: Path) -> None:
    built = world(tmp_path, SETUP + """
        [rules."spend/figures-from-tools"]
        documents = ["docs/*.md"]

        [[rules."consistency/rulebook-pinned".pins]]
        checker = "tools/check_terms.py"
        reference = "rules/terms.txt"
        marker = "terms"
    """)
    part = '[[parts]]\nid = "{}"\nstart_s = {}\nend_s = {}\nline = "{}"\n'
    hook, long = part.format("hook", 0, 4, "a short line"), part.format("body", 4, 5, "far too many words for a second")
    built.write("content/a/brief.toml", f'kind = "content"\ntitle = "A better cup"\n\n{hook}\n{long}')
    built.write("content/a/plan.toml", f"{hook}\n" + part.format("body", 4, 6, "x"))
    built.write("tools/check_terms.py", "TERMS = [\n    # terms begin\n    'guaranteed result',\n    'new entry',\n"
                "    # terms end\n]\n")
    built.write("rules/terms.txt", "guaranteed result\n")
    built.write("docs/costs.md", "# Costs\n\nThis item cost 90<!--s:content/a-->.\n")
    built.write("receipts/spend/a-1.json", json.dumps({"item": "content/a", "amount": 75, "tool": "render-tool"}))
    wanted = {
        "consistency/derived-matches": ("content/a/plan.toml", 7),  # the second [[parts]] table of the plan
        "consistency/timing-fits": ("content/a/brief.toml", 10),  # the second [[parts]] table of the brief
        "consistency/rulebook-pinned": ("tools/check_terms.py", 4),  # the entry the reference does not hold
        "spend/figures-from-tools": ("docs/costs.md", 3),
    }
    for rule_id, place in wanted.items():
        found = proofs.judge(built.root, rule_id).findings
        assert [(finding.where, finding.line) for finding in found] == [place], rule_id


# --- reading costs in a document ---------------------------------------------------------------


def test_a_cost_tag_is_read_with_the_number_right_before_it() -> None:
    page = "Cost: **1,305.50 credits**<!--s:content/a-->.\nAbout a thousand<!-- s:total -->.\nv2<!--s:content/b/-->\n"
    assert spend.tagged_costs(page) == [(1, "content/a", "1,305.50"), (2, "total", None), (3, "content/b", None)]
    assert spend.tagged_costs("```\n9<!--s:content/a-->\n```\n8<!--s:content/a-->\n") == [(4, "content/a", "8")]
    assert [spend.money(value) for value in (1100, 1304.6, 0, 0.5, 1234567.891)] == ["1,100", "1,304.6", "0", "0.5",
                                                                                 "1,234,567.89"]


# --- the loop report ---------------------------------------------------------------------------


def loop(tmp_path: Path) -> World:
    """Two items: one priced at 1,000 that spent 1,250, and one priced at 800 that has spent nothing."""
    built = world(tmp_path)
    part = '\n[[parts]]\nid = "hook"\nstart_s = 0.0\nend_s = 4.0\n'
    built.write("content/a/brief.toml", 'kind = "content"\ntitle = "A better cup"\npurpose = "growth"\n')
    built.write("content/a/plan.toml", "estimate = 1000\n" + part)
    built.write("content/b/brief.toml", 'kind = "content"\ntitle = "Three mistakes"\npurpose = "sales"\n')
    built.write("content/b/plan.toml", "estimate = 800\n" + part)
    for name, amount in (("a-1", 750), ("a-2", 500)):
        receipt = {"item": "content/a", "amount": amount, "tool": "render-tool"}
        built.write(f"receipts/spend/{name}.json", json.dumps(receipt))
    run = {"role": "writer", "at": "2026-03-02T09:00:00+00:00", "cost": 40, "produced": ["content/a/brief.toml"]}
    idle = {**run, "at": "2026-03-03T09:00:00+00:00", "cost": 55, "produced": [], "flagged": True}
    built.write("receipts/run/r1.json", json.dumps(run))
    built.write("receipts/run/r2.json", json.dumps({**idle, "reason": "topic dropped"}))
    return built


def test_the_loop_report_shows_each_item_the_totals_the_overrun_and_the_idle_runs(tmp_path: Path) -> None:
    built = loop(tmp_path)
    page = loop_report.build(built.root, manifests.load(built.root), ["content/a", "content/b"])
    assert "| A better cup (`content/a`) | growth | 1,000 | 1,250<!--s:content/a--> | +250 |" in page
    assert "| Three mistakes (`content/b`) | sales | 800 | — | — |" in page
    assert "| **Total** |  | 1,800 | 1,250 | +250 |" in page
    assert "**Measured overrun: 1.25.**" in page and "over the 1 item(s) that have both" in page
    assert "Amounts are in credits." in page
    assert "2 agent run(s) are recorded, at a total cost of 95. 1 of them produced nothing, at a cost of 55." in page
    assert "- `receipts/run/r2.json`: writer, 2026-03-03T09:00:00+00:00, cost 55, flagged: topic dropped" in page
    assert "receipts/run/r1.json" not in page  # a run that produced something is not listed


def test_the_loop_report_is_the_same_page_whatever_order_it_is_asked_in(tmp_path: Path) -> None:
    built = loop(tmp_path)
    manifest = manifests.load(built.root)
    page = loop_report.build(built.root, manifest, ["content/a", "content/b"])
    assert page == loop_report.build(built.root, manifest, ["content/b/", "content/a", "content/a"])
    target = loop_report.write(built.root, manifest, ["content/a", "content/b"], "reports/loop-1.md")
    assert target == built.root / "reports/loop-1.md"
    assert target.read_text(encoding="utf-8") == page


def test_the_loop_report_never_guesses_a_value_it_cannot_read(tmp_path: Path) -> None:
    built = loop(tmp_path)
    built.write("content/b/plan.toml", "estimate = \n")
    built.write("receipts/spend/a-3.json", json.dumps({"item": "content/a", "amount": "a lot", "tool": "render-tool"}))
    built.write("receipts/spend/a-4.json", '{"item": "content/a", "amount": 900\n')
    built.write("receipts/run/r3.json", "not a receipt\n")
    page = loop_report.build(built.root, manifests.load(built.root), ["content/a", "content/b", "content/c"])
    assert "| Three mistakes (`content/b`) | sales | — | — | — |" in page
    assert "| `content/c` | — | — | — | — |" in page
    assert "1,250<!--s:content/a-->" in page  # the receipt that cannot be read is not counted
    assert "- `receipts/spend/a-3.json` is not counted: spend receipt.amount must be a number" in page
    assert "- `receipts/spend/a-4.json` is not counted: this spend receipt cannot be read" in page
    assert "- `receipts/run/r3.json` is not counted: this run receipt cannot be read" in page
    assert "- `content/b/plan.toml` cannot be read" in page
    empty = loop_report.build(built.root, manifests.load(built.root), ["content/c"])
    assert "**Measured overrun: not measured.**" in empty


def test_the_loop_report_holds_under_the_cost_rule_until_a_receipt_is_added(tmp_path: Path) -> None:
    built = loop(tmp_path)
    built.manifest(SETUP + '\n    [rules."spend/figures-from-tools"]\n    documents = ["reports/*.md"]\n')
    loop_report.write(built.root, manifests.load(built.root), ["content/a", "content/b"], "reports/loop-1.md")
    assert proofs.judge(built.root, "spend/figures-from-tools").verdict is Verdict.PASS
    retake = {"item": "content/a", "amount": 300, "tool": "render-tool", "kind": "retake"}
    built.write("receipts/spend/a-3.json", json.dumps(retake))
    stale = proofs.judge(built.root, "spend/figures-from-tools")
    assert stale.verdict is Verdict.FAIL
    assert "says 1,250 for content/a, and its spend receipts add up to 1,550" in stale.findings[0].message
