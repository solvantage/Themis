"""The marketing pack, end to end: results come in, the gate decides, and the decision checks clean.

The point of the pack is that the agent cannot type the decision, the thresholds or the numbers.
These tests walk that path with the real command, then try each of the three.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from themis import claims, engine
from themis import manifest as manifests
from themis.cli import EXIT_FAIL, EXIT_PASS, EXIT_REFUSE, main
from themis.proofs import World
from themis.verdict import Verdict

MANIFEST = """
[project]
name = "content"
packs = ["marketing"]

[marketing]
work = "content/*"

[marketing.purposes.growth]
goal = "follows"

[marketing.results]
baseline = "own-median"
second_number = "saves"
min_age_days = 7
min_items_to_judge = 3
min_items_to_rank = 6

[rules]
"decision/issued-by-gate" = "enforce"
"decision/enough-evidence" = "enforce"
"results/inputs-rebuilt" = "enforce"
"results/own-baseline" = "enforce"
"results/noise-band" = "enforce"
"""
CHECKED = ["decision/issued-by-gate", "decision/enough-evidence", "results/inputs-rebuilt", "results/own-baseline",
           "results/noise-band"]


def project(tmp_path: Path, alpha: list[int], beta: list[int], views: int = 1000) -> World:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest(MANIFEST)
    for series, follows in (("alpha", alpha), ("beta", beta)):
        for number, value in enumerate(follows):
            unit = f"content/{series}-{number}"
            world.write(f"{unit}/brief.toml", f'kind = "content"\ntitle = "t"\npurpose = "growth"\nseries = "{series}"\n')
            world.write(f"{unit}/result.toml", f'read_at = "2026-03-01"\nage_days = 7\nsource = "an export"\n\n'
                                               f"[metrics]\nfollows = {value}\nsaves = 2\nviews = {views}\n")
    return world


def run(world: World, *args: str) -> int:
    return main([args[0], "--root", str(world.root), *args[1:]])


def decision(world: World, name: str = "alpha") -> dict:
    return json.loads((world.root / f"decisions/{name}.json").read_text())


def test_a_clear_leader_is_decided_from_the_records_and_checks_clean(tmp_path: Path) -> None:
    world = project(tmp_path, alpha=[9, 8, 9, 7, 9, 8], beta=[2, 3, 2, 1, 2, 3])
    assert run(world, "decide", "alpha", "--gate", "results", "--rival", "beta") == EXIT_PASS
    stored = decision(world)
    assert (stored["decision"], stored["verdict"], stored["numbers"]["within_noise"]) == ("lead", "pass", False)
    assert stored["numbers"]["baseline"] == "own-median" and stored["numbers"]["min_items_to_rank"] == 6
    assert run(world, "check", *CHECKED) == EXIT_PASS


def test_a_series_with_too_few_results_is_deferred_not_judged(tmp_path: Path) -> None:
    world = project(tmp_path, alpha=[9, 8], beta=[2, 3, 2, 1, 2, 3])
    assert run(world, "decide", "alpha", "--gate", "results", "--rival", "beta") == EXIT_REFUSE
    assert (decision(world)["decision"], decision(world)["verdict"]) == ("too-few", "refuse")


def test_a_difference_inside_the_noise_does_not_crown_a_leader(tmp_path: Path) -> None:
    world = project(tmp_path, alpha=[5, 3, 6, 2, 5, 4], beta=[4, 5, 2, 6, 3, 4])
    assert run(world, "decide", "alpha", "--gate", "results", "--rival", "beta") == EXIT_PASS
    assert decision(world)["decision"] == "keep"


@pytest.mark.parametrize(
    ("tamper", "rule"),
    [
        (lambda world: _retype(world, "decisions/alpha.json", decision="retire", verdict="fail"), "decision/issued-by-gate"),
        (lambda world: _retype(world, "decision-inputs/alpha.json", min_items_to_rank=1), "results/inputs-rebuilt"),
        (lambda world: _lift(world), "results/inputs-rebuilt"),
    ],
    ids=["the decision typed by hand", "a kinder threshold typed in", "a result typed higher"],
)
def test_nothing_the_decision_rests_on_can_be_typed(tmp_path: Path, tamper, rule: str) -> None:
    world = project(tmp_path, alpha=[9, 8, 9, 7, 9, 8], beta=[2, 3, 2, 1, 2, 3])
    assert run(world, "decide", "alpha", "--gate", "results", "--rival", "beta") == EXIT_PASS
    tamper(world)
    report = engine.run(manifests.load(world.root), only=set(CHECKED))
    failed = {result.id for result in report.results if result.verdict is Verdict.FAIL}
    assert rule in failed and report.exit_code == EXIT_FAIL


def _retype(world: World, path: str, **typed: object) -> None:
    target = world.root / path
    target.write_text(json.dumps({**json.loads(target.read_text()), **typed}))


def _lift(world: World) -> None:
    target = world.root / "decision-inputs/alpha.json"
    stored = json.loads(target.read_text())
    stored["series"]["alpha"][0]["goal"] = 900
    target.write_text(json.dumps(stored))


def test_a_spend_figure_with_its_tag_is_not_an_unreceipted_number() -> None:
    """The marketing pack registers its spend citation with the core claims gate."""
    from themis import pack

    pack.load("marketing")
    text = "The clips cost 1,305<!--s:content/a--> credits, and the brief said 40 seconds.\n"
    assert [number for _, number in claims.untagged_numbers(text)] == ["40"]
    with pytest.raises(ValueError):
        claims.register_citation("t")  # the core's own prefixes cannot be taken over


# -- the pages the pack builds, and the owner's yes to publish -----------------------------------

SPENDING = MANIFEST + '\n[marketing.spend]\nunit = "credits"\nrun_ceiling = 2000\n'


def _priced(world: World, unit: str, series: str, *spends: float) -> None:
    world.write(f"{unit}/brief.toml", f'kind = "content"\ntitle = "t"\npurpose = "growth"\nseries = "{series}"\n')
    world.write(f"{unit}/plan.toml", 'estimate = 1000\n\n[[parts]]\nid = "hook"\nstart_s = 0.0\nend_s = 4.0\n')
    for number, amount in enumerate(spends, start=1):
        _spend(world, f"{unit.rsplit('/', 1)[-1]}-{number}", unit, amount)


def _spend(world: World, name: str, unit: str, amount: float) -> None:
    world.write(f"receipts/spend/{name}.json", json.dumps({
        "item": unit, "amount": amount, "unit": "credits", "tool": "render-tool", "job": name,
        "at": "2026-03-02T10:00:00+00:00"}))


def _verdict(world: World, rule_id: str) -> Verdict | None:
    return engine.run(manifests.load(world.root), only={rule_id}).results[0].verdict


def test_the_report_command_builds_pages_that_are_held_to_the_spend_receipts(tmp_path: Path) -> None:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest(SPENDING)
    _priced(world, "content/a", "alpha", 600, 500)
    _priced(world, "content/b", "alpha", 450)
    _priced(world, "content/c", "beta", 300)
    assert run(world, "report", "content/a") == EXIT_PASS
    page, series = (world.root / "content/a/report.md").read_text(), (world.root / "reports/alpha.md").read_text()
    assert "1,100<!--s:content/a-->" in page and "content/b" not in page
    assert "450<!--s:content/b-->" in series and "content/c" not in series
    assert _verdict(world, "spend/figures-from-tools") is Verdict.PASS

    _spend(world, "a-3", "content/a", 300)  # a retake, paid for after the pages were built
    assert _verdict(world, "spend/figures-from-tools") is Verdict.FAIL
    assert run(world, "report", "a") == EXIT_PASS
    assert _verdict(world, "spend/figures-from-tools") is Verdict.PASS


def test_building_the_report_twice_writes_the_same_pages(tmp_path: Path) -> None:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest(SPENDING)
    _priced(world, "content/a", "alpha", 600, 500)
    assert run(world, "report", "content/a") == EXIT_PASS
    first = {name: (world.root / name).read_text() for name in ("content/a/report.md", "reports/alpha.md")}
    assert run(world, "report", "content/a") == EXIT_PASS
    assert first == {name: (world.root / name).read_text() for name in first}


def test_an_item_goes_out_only_on_the_owners_grant_for_it(tmp_path: Path) -> None:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest(SPENDING)
    _priced(world, "content/a", "alpha")
    world.write("content/a/post.toml", 'platform = "a platform"\nat = "2999-01-01T00:00:00+00:00"\n')
    assert _verdict(world, "publish/granted") is Verdict.FAIL  # posted with no grant at all

    assert run(world, "grant", "publish", "content/a", "--reason", "the review is done") == EXIT_PASS
    grant = next((world.root / "grants").glob("*.toml")).stem
    world.write("content/a/post.toml", f'platform = "a platform"\nat = "2999-01-01T00:00:00+00:00"\ngrant = "{grant}"\n')
    assert _verdict(world, "publish/granted") is Verdict.PASS

    world.write("content/b/brief.toml", 'kind = "content"\ntitle = "t"\n')
    world.write("content/b/post.toml", f'platform = "a platform"\nat = "2999-01-01T00:00:00+00:00"\ngrant = "{grant}"\n')
    assert _verdict(world, "publish/granted") is Verdict.FAIL  # the same yes does not open a second item


def test_a_core_run_receipt_is_not_read_as_an_agent_run(tmp_path: Path) -> None:
    """`themis run` records a command and its exit status. The pack's own agent-run receipts, which
    record a cost and what was produced, live in a folder of their own, so the two never mix."""
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest(SPENDING)
    world.write("receipts/run/a-1.json", json.dumps({"kind": "run", "work": "content/a", "command": ["make"],
                                                     "exit_status": 0, "at": "2026-03-02T10:00:00+00:00"}))
    world.write("receipts/agent-run/w-1.json", json.dumps({"role": "writer", "at": "2026-03-02T09:00:00+00:00",
                                                           "cost": 40, "produced": ["content/a/brief.toml"]}))
    assert _verdict(world, "spend/agent-runs") is Verdict.PASS
