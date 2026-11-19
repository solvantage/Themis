"""The guard on sealed data windows: a sealed window opens once for each grant, and leaves a look behind."""

from __future__ import annotations

import datetime as dt
import json
import tomllib
from pathlib import Path

import pytest

from themis import engine, grants, records
from themis import manifest as manifests
from themis.packs.trading import data
from themis.proofs import World
from themis.verdict import Verdict

MANIFEST = """
    [project]
    packs = ["trading"]

    [trading]
    work = "work/*"

    [trading.windows.train]
    from = "2015-01-01"
    to = "2021-12-31"

    [trading.windows.holdout]
    from = "2022-01-01"
    to = "2024-12-31"
    sealed = true
"""
NOON = dt.datetime(2026, 3, 4, 12, 0, tzinfo=dt.timezone.utc)
HOLDOUT = ("2022-01-01", "2024-12-31")
PIPELINE = {"kind": "pipeline", "scope": "the first 50 rows", "purpose": "show the loader reads the sealed files",
            "compared_against": "the row counts in the data inventory"}


def project(tmp_path: Path, manifest: str = MANIFEST) -> World:
    world = World(tmp_path / "repo")
    world.root.mkdir(parents=True)
    world.manifest(manifest)
    return world


def grant(world: World, name: str = "g1", action: str = "holdout", target: str = "holdout", extra: str = "") -> None:
    lines = [f'action = "{action}"', f'target = "{target}"', 'granted_by = "owner"',
             'granted_at = "2026-03-01T09:00:00+00:00"', 'reason = "the plan is sealed"', extra]
    world.write(f"grants/{name}.toml", "\n".join(lines) + "\n")


def read(world: World, path: str) -> dict:
    return tomllib.loads((world.root / path).read_text(encoding="utf-8"))


def ask(world: World, name: str = "holdout", **given: object) -> tuple[str, str]:
    return data.window(world.root, manifests.load(world.root), name, **{"now": NOON, **given})


def looks(world: World) -> list[str]:
    return sorted(path.relative_to(world.root).as_posix() for path in world.root.glob("looks/*"))


HOLDOUT_RULES = ("holdout/guarded", "holdout/one-signal-look", "holdout/pipeline-look-declared")


def judged(world: World, rule_id: str) -> engine.Result:
    """One rule's result in the world, with nobody else's rules run beside it."""
    return engine.run(manifests.load(world.root), only={rule_id}).results[0]


# -- windows that open ---------------------------------------------------------------------------


def test_a_window_that_is_not_sealed_is_handed_over_and_leaves_no_look(tmp_path: Path) -> None:
    world = project(tmp_path)
    assert ask(world, "train") == ("2015-01-01", "2021-12-31")
    assert ask(world, "train", kind="pipeline") == ("2015-01-01", "2021-12-31")
    assert looks(world) == []


def test_a_sealed_window_opens_with_its_grant_and_the_look_is_written_down(tmp_path: Path) -> None:
    world = project(tmp_path)
    grant(world)
    assert ask(world, grant="g1", study="work/a") == HOLDOUT
    assert looks(world) == ["looks/2026-03-04-holdout-1.toml"]
    assert read(world, looks(world)[0]) == {
        "window": "holdout", "kind": "signal", "at": "2026-03-04T12:00:00+00:00", "grant": "g1", "study": "work/a",
    }


def test_a_grant_written_by_the_grant_command_opens_the_window_it_names(tmp_path: Path) -> None:
    world = project(tmp_path)
    made = grants.new_grant(world.root, "holdout", "holdout", granted_by="owner", reason="the plan is sealed", now=NOON)
    assert ask(world, grant=made.stem) == HOLDOUT
    assert read(world, looks(world)[0])["grant"] == "2026-03-04-holdout-holdout"
    assert judged(world, "holdout/guarded").verdict is Verdict.PASS


def test_the_look_is_a_record_the_project_can_read(tmp_path: Path) -> None:
    world = project(tmp_path)
    grant(world)
    ask(world, grant="g1", **PIPELINE)
    held = records.load_kind(world.root, manifests.load(world.root), "look", looks(world))
    assert [(record.id, record.problems) for record in held] == [("2026-03-04-holdout-1", [])]
    assert {key: held[0].get(key) for key in PIPELINE} == PIPELINE
    assert held[0].get("forward_returns") is None  # the guard cannot vouch for what the caller computes


def test_each_look_takes_the_next_free_number(tmp_path: Path) -> None:
    world = project(tmp_path)
    grant(world, "g1")
    grant(world, "g2")
    ask(world, grant="g1")
    ask(world, grant="g2", **PIPELINE)
    assert looks(world) == ["looks/2026-03-04-holdout-1.toml", "looks/2026-03-04-holdout-2.toml"]


def test_the_date_in_a_looks_name_is_the_utc_date(tmp_path: Path) -> None:
    world = project(tmp_path)
    grant(world)
    late = dt.datetime(2026, 3, 4, 23, 30, tzinfo=dt.timezone(dt.timedelta(hours=-7)))
    ask(world, grant="g1", now=late)
    assert looks(world) == ["looks/2026-03-05-holdout-1.toml"]
    assert read(world, looks(world)[0])["at"] == "2026-03-05T06:30:00+00:00"


def test_text_survives_the_trip_into_toml_and_back(tmp_path: Path) -> None:
    world = project(tmp_path)
    grant(world)
    odd = 'a "quoted" path\\with\ttabs,\nnew lines, an é, a \U0001f512 and a \x7f'
    ask(world, grant="g1", kind="pipeline", scope=odd, purpose="p", compared_against="c")
    assert read(world, looks(world)[0])["scope"] == odd


def test_it_works_the_same_inside_a_git_repository(tmp_path: Path) -> None:
    world = project(tmp_path)
    grant(world)
    world.commit("start")
    assert ask(world, grant="g1") == HOLDOUT  # the look is new and not committed yet
    with pytest.raises(data.SealedWindow, match="already used by the look looks/2026-03-04-holdout-1.toml"):
        ask(world, grant="g1")


def test_a_project_that_moved_its_look_records_gets_them_where_it_keeps_them(tmp_path: Path) -> None:
    world = project(tmp_path, MANIFEST + '\n    [homes]\n    look = "records/looks/*.toml"\n')
    grant(world)
    ask(world, grant="g1")
    assert (world.root / "records/looks/2026-03-04-holdout-1.toml").is_file()
    with pytest.raises(data.SealedWindow, match="already used"):
        ask(world, grant="g1")


# -- windows that stay shut ----------------------------------------------------------------------


@pytest.mark.parametrize("given", [{}, {"grant": ""}, {"grant": True}, {"kind": "pipeline", **PIPELINE}])
def test_a_sealed_window_stays_shut_with_no_grant(tmp_path: Path, given: dict) -> None:
    world = project(tmp_path)
    grant(world)
    with pytest.raises(data.SealedWindow, match="no grant is named"):
        ask(world, **given)
    assert looks(world) == []


@pytest.mark.parametrize(("fields", "said"), [
    ({"name": "g2"}, "no grant with the id g1 is on file"),
    ({"action": "publish"}, "is for the action publish, not holdout"),
    ({"target": "train"}, "is for the target train, not holdout"),
    ({"extra": 'spent_at = "2026-03-02T09:00:00+00:00"'}, "is marked as spent"),
    ({"extra": "ceiling = "}, "the grant g1 cannot be read"),
])
def test_a_grant_that_is_not_for_this_window_does_not_open_it(tmp_path: Path, fields: dict, said: str) -> None:
    world = project(tmp_path)
    grant(world, **fields)
    with pytest.raises(data.SealedWindow, match=said):
        ask(world, grant="g1")
    assert looks(world) == []


def test_a_grant_opens_a_sealed_window_once(tmp_path: Path) -> None:
    world = project(tmp_path)
    grant(world)
    ask(world, grant="g1")
    for kind in ({}, PIPELINE):
        with pytest.raises(data.SealedWindow, match="g1 was already used by the look looks/2026-03-04-holdout-1"):
            ask(world, grant="g1", **kind)
    assert len(looks(world)) == 1


def test_a_look_record_that_cannot_be_read_keeps_the_window_shut(tmp_path: Path) -> None:
    world = project(tmp_path)
    grant(world)
    world.write("looks/old.toml", 'window = "holdout\n')
    with pytest.raises(data.SealedWindow, match="looks/old.toml cannot be read"):
        ask(world, grant="g1")
    assert looks(world) == ["looks/old.toml"]


def test_a_manifest_with_a_mistake_opens_no_window_at_all(tmp_path: Path) -> None:
    world = project(tmp_path, MANIFEST.replace("sealed = true", "seeled = true"))
    grant(world)
    for name in ("holdout", "train"):  # a mistyped seal must not turn into an open window
        with pytest.raises(data.SealedWindow, match="the manifest has problems"):
            ask(world, name, grant="g1")


def test_look_records_with_no_one_folder_to_write_in_keep_the_window_shut(tmp_path: Path) -> None:
    world = project(tmp_path, MANIFEST + '\n    [homes]\n    look = "**/looks/*.toml"\n')
    grant(world)
    with pytest.raises(data.SealedWindow, match="names no one folder"):
        ask(world, grant="g1")


# -- requests that are wrong ---------------------------------------------------------------------


def test_a_window_the_manifest_does_not_declare_is_a_key_error(tmp_path: Path) -> None:
    world = project(tmp_path)
    with pytest.raises(KeyError, match="no data window named 'live'"):
        ask(world, "live")


@pytest.mark.parametrize(("given", "said"), [
    ({"kind": "peek"}, "a look's kind is signal or pipeline"),
    ({"kind": "pipeline", "scope": "the first 50 rows"}, "give purpose, compared_against"),
    ({"kind": "pipeline", **PIPELINE, "purpose": "  "}, "give purpose"),
    ({"study": 7}, "study must be text"),
    ({"study": "half a character: \ud800"}, "not valid Unicode"),
])
def test_a_badly_described_look_is_refused_before_anything_is_written(tmp_path: Path, given: dict, said: str) -> None:
    world = project(tmp_path)
    grant(world)
    with pytest.raises(ValueError, match=said):
        ask(world, grant="g1", **given)
    assert looks(world) == []


# -- the guard and the gate agree ----------------------------------------------------------------


def test_what_the_guard_writes_the_holdout_gate_accepts(tmp_path: Path) -> None:
    world = project(tmp_path)
    grant(world, "g1")
    grant(world, "g2")
    ask(world, grant="g1", study="work/a")
    ask(world, grant="g2", **PIPELINE)
    for rule_id in HOLDOUT_RULES:
        assert judged(world, rule_id).verdict is Verdict.PASS, rule_id


def test_a_second_signal_look_gets_past_the_guard_and_is_caught_by_the_gate(tmp_path: Path) -> None:
    world = project(tmp_path)
    grant(world, "g1")
    grant(world, "g2")
    ask(world, grant="g1")
    ask(world, grant="g2", now=NOON + dt.timedelta(days=1))  # the owner granted it, so the guard opens
    assert judged(world, "holdout/guarded").verdict is Verdict.PASS
    assert judged(world, "holdout/one-signal-look").verdict is Verdict.FAIL


def test_a_look_written_by_hand_with_no_grant_fails_the_gate(tmp_path: Path) -> None:
    world = project(tmp_path)
    world.write("looks/by-hand.toml", 'window = "holdout"\nkind = "signal"\nat = "2026-03-04T12:00:00+00:00"\n')
    assert judged(world, "holdout/guarded").verdict is Verdict.FAIL


def test_with_no_sealed_window_the_holdout_rules_are_not_configured(tmp_path: Path) -> None:
    world = project(tmp_path, MANIFEST.replace("    sealed = true\n", ""))
    for rule_id in HOLDOUT_RULES:
        result = judged(world, rule_id)
        assert (result.status, result.verdict) == ("not configured", None), rule_id
        assert "sealed = true" in result.note


# -- a study's own windows -----------------------------------------------------------------------

OWN = '{from = "2025-01-01", to = "2025-12-31", sealed = true}'


def seal(world: World, study: str = "work/a", **windows: str) -> None:
    """A study's seal that declares its own windows, each as an inline table, and reads them and train."""
    names = ", ".join(["train", *windows])
    lines = [f"window-{name}: {table}" for name, table in windows.items()]
    plan = ["kind: tune", f"windows: [{names}]", *lines, "gate: tune", "iterations: 9", "risk_rules: r.json"]
    world.write(f"{study}/PRE-REG.md", "\n".join(["---", *plan, "---", ""]))


def test_a_study_reads_its_own_sealed_window_with_a_grant_for_the_study_and_the_window(tmp_path: Path) -> None:
    world = project(tmp_path)
    seal(world, oos=OWN)
    grant(world, target="work/a/oos")
    assert ask(world, "oos", grant="g1", study="work/a") == ("2025-01-01", "2025-12-31")
    assert read(world, looks(world)[0])["study"] == "work/a"
    receipt = json.loads(next((world.root / "receipts/action").glob("*.json")).read_text())
    assert (receipt["action"], receipt["target"], receipt["grant"]) == ("holdout", "work/a/oos", "g1")
    for rule_id in (*HOLDOUT_RULES[:2], "grant/required", "grant/single-use", "prereg/declared"):
        assert judged(world, rule_id).verdict is Verdict.PASS, rule_id


def test_a_project_window_opens_with_a_grant_for_the_study_too(tmp_path: Path) -> None:
    world = project(tmp_path)
    grant(world, target="work/a/holdout")
    assert ask(world, grant="g1", study="work/a") == HOLDOUT
    assert judged(world, "holdout/guarded").verdict is Verdict.PASS


@pytest.mark.parametrize(("target", "study", "said"), [
    ("oos", "work/a", "is for the target oos, not work/a/oos"),
    ("work/b/oos", "work/a", "is for the target work/b/oos, not work/a/oos"),
])
def test_a_study_s_own_window_needs_a_grant_for_that_study(tmp_path: Path, target: str, study: str, said: str) -> None:
    world = project(tmp_path)
    seal(world, oos=OWN)
    seal(world, "work/b", oos=OWN)
    grant(world, target=target)
    with pytest.raises(data.SealedWindow, match=said):
        ask(world, "oos", grant="g1", study=study)
    assert looks(world) == []


def test_another_study_s_window_is_not_this_study_s(tmp_path: Path) -> None:
    world = project(tmp_path)
    seal(world, "work/b", oos=OWN)
    grant(world, target="work/a/oos")
    with pytest.raises(KeyError, match="the study work/a declares none of its own"):
        ask(world, "oos", grant="g1", study="work/a")


@pytest.mark.parametrize("declared", [
    {"holdout": '{from = "2023-01-01", to = "2024-12-31", sealed = true}'},  # the project's id, other dates
    {"train": '{from = "2015-01-01", to = "2021-12-31", seeled = true}'},    # a mistyped seal
    {"train": "2015-01-01 to 2021-12-31"},                                   # not a table
])
def test_a_window_declared_two_ways_or_unreadably_is_not_opened(tmp_path: Path, declared: dict) -> None:
    world = project(tmp_path)
    seal(world, **declared)
    grant(world, target=f"work/a/{next(iter(declared))}")
    with pytest.raises(data.SealedWindow, match="was not opened"):  # a mistyped seal never opens a window
        ask(world, next(iter(declared)), grant="g1", study="work/a")
    assert looks(world) == []
    assert judged(world, "prereg/declared").verdict is Verdict.FAIL


def test_sibling_studies_that_share_a_window_count_their_looks_together(tmp_path: Path) -> None:
    world = project(tmp_path)
    seal(world, oos=OWN)
    seal(world, "work/b", oos=OWN)
    grant(world, "g1", target="work/a/oos")
    grant(world, "g2", target="work/b/oos")
    ask(world, "oos", grant="g1", study="work/a")
    assert judged(world, "holdout/one-signal-look").verdict is Verdict.PASS
    ask(world, "oos", grant="g2", study="work/b", now=NOON + dt.timedelta(days=1))
    assert judged(world, "holdout/guarded").verdict is Verdict.PASS
    assert judged(world, "holdout/one-signal-look").verdict is Verdict.FAIL


def test_a_window_sealed_only_in_a_study_s_seal_puts_holdout_under_grant_required(tmp_path: Path) -> None:
    world = project(tmp_path, MANIFEST.replace("    sealed = true\n", ""))
    rule = next(rule for rule in manifests.load(world.root).active_rules() if rule.id == "grant/required")
    assert manifests.load(world.root).setting(rule).params["guarded"] is None
    seal(world, oos=OWN)
    assert manifests.load(world.root).setting(rule).params["guarded"] == ["holdout"]
