"""A unit is named by its whole path wherever a record is stored for it.

Units that share a folder name, such as two setups whose work each lives in a `tune` folder, must
never share a decision, a run receipt or a ledger record.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from themis import work
from themis.cli import EXIT_PASS, EXIT_REFUSE, main
from themis.proofs import World

PACK = '''
from themis.pack import Pack

pack = Pack(name="{name}")


@pack.gate("threshold", version="1")
def threshold(metrics):
    good = metrics["uplift"] >= 0.05
    return {{"decision": "keep" if good else "drop", "verdict": "pass" if good else "fail", "reason": "measured"}}
'''
MANIFEST = """
[project]
name = "demo"
local_pack = "pack"

[rules."order/logged-first"]
work = "setups/*/tune"
results = ["results/**"]
"""


def project(tmp_path: Path, name: str) -> World:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.write("pack/__init__.py", PACK.format(name=name))
    world.manifest(MANIFEST)
    world.write(".gitignore", ".themis/\n__pycache__/\n")
    for setup, uplift in (("a", 0.08), ("b", 0.01)):
        world.write(f"setups/{setup}/tune/PLAN.md", "the plan\n")
        world.write(f"setups/{setup}/tune/results/metrics.json", json.dumps({"uplift": uplift}))
    world.commit("start")
    return world


def run(world: World, *args: str) -> int:
    return main([args[0], "--root", str(world.root), *args[1:]])


def test_the_name_helpers() -> None:
    units = ["setups/a/tune", "setups/b/tune", "work/solo"]
    assert work.file_name("setups/a/tune/") == "setups-a-tune"
    assert work.named(units, "setups/a/tune") == "setups/a/tune"
    assert work.named(units, "solo") == "work/solo"
    assert work.named(units, "tune") is None  # two units share it, so it names neither
    assert work.named(units, "missing") is None


def test_two_units_that_share_a_folder_name_keep_a_decision_each(tmp_path: Path) -> None:
    world = project(tmp_path, "names-a")
    assert run(world, "decide", "setups/a/tune", "--gate", "threshold") == EXIT_PASS
    assert run(world, "decide", "setups/b/tune", "--gate", "threshold") != EXIT_PASS
    stored = {path.name: json.loads(path.read_text())["work"] for path in (world.root / "decisions").glob("*.json")}
    assert stored == {"setups-a-tune.json": "setups/a/tune", "setups-b-tune.json": "setups/b/tune"}


def test_a_decision_under_the_old_folder_name_moves_to_the_units_own_name(tmp_path: Path) -> None:
    world = project(tmp_path, "names-b")
    world.write("decisions/tune.json", json.dumps({"work": "setups/a/tune", "verdict": "fail"}))
    assert run(world, "decide", "setups/a/tune", "--gate", "threshold") == EXIT_PASS
    assert sorted(path.name for path in (world.root / "decisions").glob("*.json")) == ["setups-a-tune.json"]


def test_a_decision_file_that_holds_another_units_decision_is_never_overwritten(tmp_path: Path) -> None:
    world = project(tmp_path, "names-c")
    world.write("decisions/setups-a-tune.json", json.dumps({"work": "setups-a/tune", "verdict": "pass"}))
    assert run(world, "decide", "setups/a/tune", "--gate", "threshold") == EXIT_REFUSE
    assert json.loads((world.root / "decisions/setups-a-tune.json").read_text())["work"] == "setups-a/tune"


def test_run_receipts_are_named_by_the_units_whole_path(tmp_path: Path) -> None:
    world = project(tmp_path, "names-d")
    for setup in ("a", "b"):
        assert run(world, "run", f"setups/{setup}/tune", "--", sys.executable, "-c", "pass") == EXIT_PASS
        world.commit(f"the receipt of {setup}")
    names = sorted(path.name for path in (world.root / "receipts/run").glob("*.json"))
    assert [name.rsplit("-", 1)[0] for name in names] == ["setups-a-tune", "setups-b-tune"]
