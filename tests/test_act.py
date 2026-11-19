"""`themis act`: a guarded command runs only with an unspent grant, spends it, and can tell it ran so.

Shown first in a world that is no trading project: a plain docs-and-scripts site whose publish
script refuses to run outside `act`. Then in a trading world, where `act holdout` writes the look
the holdout rules count, keyed by the study and the window.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from themis import engine
from themis import manifest as manifests
from themis.cli import EXIT_FAIL, EXIT_PASS, EXIT_REFUSE, main
from themis.proofs import World
from themis.verdict import Verdict

THEMIS = [sys.executable, "-c", "import sys; from themis.cli import main; sys.exit(main(sys.argv[1:]))"]
SITE = """
    [project]
    name = "site"

    [rules."grant/required"]
    guarded = ["publish"]
"""
#: The site's publish script: it asks Themis whether it runs under `act` before it does anything.
PUBLISH = f"""
import subprocess, sys
action, target = sys.argv[1], sys.argv[2]
asked = subprocess.run({THEMIS!r} + ["act", "--verify", action, target])
if asked.returncode != 0:
    print("refused: run me through themis act", file=sys.stderr)
    sys.exit(3)
open("published.txt", "a").write(target + "\\n")
sys.exit(int(sys.argv[3]) if len(sys.argv) > 3 else 0)
"""


def site(tmp_path: Path) -> World:
    world = World(tmp_path / "site")
    world.root.mkdir()
    world.manifest(SITE)
    world.write("docs/index.md", "# The site\n")
    world.write("scripts/publish.py", PUBLISH)
    world.commit("start")
    return world


def run(world: World, *args: str) -> int:
    return main([args[0], "--root", str(world.root), *args[1:]])


def publish(world: World, target: str = "site", *extra: str) -> int:
    return run(world, "act", "publish", target, "--", sys.executable, "scripts/publish.py", "publish", target, *extra)


def receipts_of(world: World) -> list[dict]:
    return [json.loads(path.read_text()) for path in sorted((world.root / "receipts/action").glob("*.json"))]


def verdict(world: World, rule_id: str) -> Verdict | None:
    return engine.run(manifests.load(world.root), only={rule_id}).results[0].verdict


def published(world: World) -> list[str]:
    path = world.root / "published.txt"
    return path.read_text().split() if path.exists() else []


# -- a plain project, no trading -------------------------------------------------------------------


def test_the_script_refuses_to_run_outside_act(tmp_path: Path) -> None:
    world = site(tmp_path)
    done = subprocess.run([sys.executable, "scripts/publish.py", "publish", "site"], cwd=world.root, check=False)
    assert done.returncode == 3
    assert published(world) == []


def test_with_no_grant_act_refuses_and_nothing_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = site(tmp_path)
    assert publish(world) == EXIT_REFUSE
    assert "there is no unspent grant for publish on site" in capsys.readouterr().err
    assert published(world) == []
    assert not (world.root / "receipts").exists()


def test_with_a_grant_the_command_runs_once_and_spends_it(tmp_path: Path) -> None:
    world = site(tmp_path)
    assert run(world, "grant", "publish", "site", "--reason", "the copy was read") == EXIT_PASS
    assert publish(world) == EXIT_PASS
    assert published(world) == ["site"]
    [receipt] = receipts_of(world)
    assert (receipt["action"], receipt["target"], receipt["exit_status"]) == ("publish", "site", 0)
    assert receipt["grant"] == next((world.root / "grants").glob("*.toml")).stem
    assert receipt["command"][-3:] == ["scripts/publish.py", "publish", "site"]
    assert len(receipt["token_sha256"]) == 64 and receipt["ended_at"]
    for rule_id in ("grant/required", "grant/single-use"):
        assert verdict(world, rule_id) is Verdict.PASS, rule_id
    assert publish(world) == EXIT_REFUSE  # the grant is spent
    assert published(world) == ["site"]


def test_a_grant_for_another_target_does_not_open_this_one(tmp_path: Path) -> None:
    world = site(tmp_path)
    run(world, "grant", "publish", "blog", "--reason", "the copy was read")
    assert publish(world) == EXIT_REFUSE
    assert published(world) == []


def test_a_token_is_good_only_for_its_own_action_and_target(tmp_path: Path) -> None:
    world = site(tmp_path)
    run(world, "grant", "publish", "site", "--reason", "the copy was read")
    command = [sys.executable, "scripts/publish.py", "publish", "blog"]  # asks about another target
    assert run(world, "act", "publish", "site", "--", *command) == EXIT_FAIL
    assert published(world) == []


def test_a_token_stops_working_when_its_act_ends(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = site(tmp_path)
    run(world, "grant", "publish", "site", "--reason", "the copy was read")
    keep = "import os, pathlib; pathlib.Path('token.txt').write_text(os.environ['THEMIS_ACT_TOKEN'])"
    assert run(world, "act", "publish", "site", "--", sys.executable, "-c", keep) == EXIT_PASS
    monkeypatch.setenv("THEMIS_ACT_TOKEN", (world.root / "token.txt").read_text())
    assert run(world, "act", "--verify", "publish", "site") == EXIT_REFUSE


def test_a_receipt_written_by_hand_does_not_pass_for_an_act(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                           capsys: pytest.CaptureFixture[str]) -> None:
    world = site(tmp_path)
    world.write("receipts/action/by-hand.json", json.dumps({
        "kind": "action", "action": "publish", "target": "site", "at": "2026-01-01T10:00:00+00:00",
        "token_sha256": "0" * 64}))
    for token in ("", "typed by an agent"):
        monkeypatch.setenv("THEMIS_ACT_TOKEN", token)
        assert run(world, "act", "--verify", "publish", "site") == EXIT_REFUSE
    assert "matches no action receipt" in capsys.readouterr().err
    assert verdict(world, "grant/required") is Verdict.FAIL


def test_a_command_that_fails_still_spends_the_grant(tmp_path: Path) -> None:
    world = site(tmp_path)
    run(world, "grant", "publish", "site", "--reason", "the copy was read")
    assert publish(world, "site", "5") == EXIT_FAIL
    assert [receipt["exit_status"] for receipt in receipts_of(world)] == [5]
    assert publish(world) == EXIT_REFUSE


def test_a_command_that_cannot_be_found_spends_nothing(tmp_path: Path) -> None:
    world = site(tmp_path)
    run(world, "grant", "publish", "site", "--reason", "the copy was read")
    assert run(world, "act", "publish", "site", "--", "no-such-program-here") == EXIT_REFUSE
    assert not (world.root / "receipts").exists()
    assert publish(world) == EXIT_PASS


def test_act_needs_a_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = site(tmp_path)
    run(world, "grant", "publish", "site", "--reason", "the copy was read")
    assert run(world, "act", "publish", "site") == EXIT_REFUSE
    assert "give the command to run after `--`" in capsys.readouterr().err


def test_act_is_listed_with_the_other_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "act" in capsys.readouterr().out


# -- a trading project: act holdout writes the look --------------------------------------------------

TRADING = """
    [project]
    packs = ["trading"]

    [trading]
    work = "work/*"

    [trading.windows.train]
    from = "2015-01-01"
    to = "2021-12-31"
"""
SEAL = """---
kind: tune
windows: [train, oos]
window-oos: {from = "2025-01-01", to = "2025-12-31", sealed = true}
gate: tune
iterations: 9
risk_rules: rules/risk.json
---
"""
HOLDOUT_RULES = ("holdout/guarded", "holdout/one-signal-look", "grant/required", "grant/single-use")


def studies(tmp_path: Path) -> World:
    """Two sibling studies that share the sealed window oos, declared in each one's seal."""
    world = World(tmp_path / "research")
    world.root.mkdir()
    world.manifest(TRADING)
    world.write("work/a/PRE-REG.md", SEAL)
    world.write("work/b/PRE-REG.md", SEAL)
    world.write("confirm.py", PUBLISH.replace("published.txt", "confirmed.txt"))
    world.commit("the seals")
    return world


def confirm(world: World, target: str) -> int:
    return run(world, "act", "holdout", target, "--", sys.executable, "confirm.py", "holdout", target)


def looks(world: World) -> list[dict]:
    return [tomllib.loads(path.read_text()) for path in sorted((world.root / "looks").glob("*.toml"))]


def test_act_holdout_writes_the_look_the_holdout_rules_count(tmp_path: Path) -> None:
    world = studies(tmp_path)
    run(world, "grant", "holdout", "work/a/oos", "--reason", "the search is done")
    assert confirm(world, "work/a/oos") == EXIT_PASS
    assert (world.root / "confirmed.txt").read_text() == "work/a/oos\n"
    [look] = looks(world)
    assert (look["study"], look["window"], look["kind"]) == ("work/a", "oos", "signal")
    [receipt] = receipts_of(world)
    assert (receipt["target"], receipt["grant"], receipt["wrote"]) == ("work/a/oos", look["grant"],
                                                                      [f"looks/{look['at'][:10]}-oos-1.toml"])
    for rule_id in HOLDOUT_RULES:
        assert verdict(world, rule_id) is Verdict.PASS, rule_id


def test_a_sibling_s_look_at_a_shared_window_is_the_second_look(tmp_path: Path) -> None:
    world = studies(tmp_path)
    run(world, "grant", "holdout", "work/a/oos", "--reason", "the search is done")
    assert confirm(world, "work/b/oos") == EXIT_REFUSE  # a grant for one study opens no other
    run(world, "grant", "holdout", "work/b/oos", "--reason", "the sibling's search is done")
    assert confirm(world, "work/a/oos") == EXIT_PASS
    assert confirm(world, "work/b/oos") == EXIT_PASS  # the owner granted it, so act opens it
    assert verdict(world, "holdout/guarded") is Verdict.PASS
    assert verdict(world, "holdout/one-signal-look") is Verdict.FAIL


@pytest.mark.parametrize(("target", "said"), [
    ("work/a/train", "the window train is not sealed"),
    ("work/a/live", "no data window named 'live'"),
])
def test_act_holdout_refuses_a_window_with_no_seal_to_open(tmp_path: Path, target: str, said: str,
                                                            capsys: pytest.CaptureFixture[str]) -> None:
    world = studies(tmp_path)
    run(world, "grant", "holdout", target, "--reason", "the search is done")
    assert confirm(world, target) == EXIT_REFUSE
    assert said in capsys.readouterr().err
    assert not (world.root / "looks").exists() and not (world.root / "receipts").exists()
    assert not (world.root / "confirmed.txt").exists()


def test_a_holdout_receipt_with_no_grant_fails_under_the_pack_s_default_list(tmp_path: Path) -> None:
    world = studies(tmp_path)
    world.write("receipts/action/by-hand.json", json.dumps({
        "kind": "action", "action": "holdout", "target": "work/a/oos", "at": "2026-01-01T10:00:00+00:00"}))
    assert verdict(world, "grant/required") is Verdict.FAIL
