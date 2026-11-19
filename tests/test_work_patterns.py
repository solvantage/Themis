"""Work lives in one place or in several: `work` is one pattern or a list, everywhere in the core."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest

from themis import manifest as manifests
from themis import work
from themis.cli import EXIT_PASS, EXIT_REFUSE, main
from themis.proofs import World

FILES = ["work/a/PLAN.md", "work/a/results/out.csv", "lab/x/runs/PLAN.md", "lab/y/runs/results/m.json", "lab/y/notes.md",
         "README.md"]


def test_one_pattern_and_a_list_of_one_find_the_same_units() -> None:
    assert work.units(FILES, "work/*") == work.units(FILES, ["work/*"]) == {
        "work/a": ["work/a/PLAN.md", "work/a/results/out.csv"]}


def test_a_list_finds_the_units_of_every_pattern_and_counts_a_file_once() -> None:
    found = work.units(FILES, ["work/*", "lab/*/runs", "work/*"])
    assert sorted(found) == ["lab/x/runs", "lab/y/runs", "work/a"]
    assert found["work/a"] == ["work/a/PLAN.md", "work/a/results/out.csv"]


def test_no_pattern_in_the_list_may_reach_any_depth() -> None:
    with pytest.raises(ValueError, match="cannot hold"):
        work.units(FILES, ["work/*", "lab/**"])


def test_patterns_reads_every_form() -> None:
    assert work.patterns(None) == [] and work.patterns("/work/*/") == ["work/*"]
    assert work.patterns(["work/*", "lab/*/runs"]) == ["work/*", "lab/*/runs"]


MANIFEST = """
[project]
name = "places"
local_pack = "pack"

[rules."order/logged-first"]
work = {work}
results = ["results/**"]

[rules."claims/receipt"]
governed = ["REPORT.md"]
work = {work}
"""
PACK = 'from themis.pack import Pack\n\npack = Pack(name="{name}")\n'


def project(tmp_path: Path, name: str, patterns: object) -> World:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.write("pack/__init__.py", PACK.format(name=name))
    world.manifest(MANIFEST.format(work=json.dumps(patterns)))
    world.write(".gitignore", ".themis/\n__pycache__/\n")
    world.write("lab/x/runs/results/metrics.json", '{"hit_rate": 0.4321}\n')
    world.commit("start")
    return world


def run(world: World, *args: str) -> int:
    return main([args[0], "--root", str(world.root), *args[1:]])


def test_a_list_is_a_valid_work_parameter_and_a_wrong_item_is_named(tmp_path: Path) -> None:
    world = project(tmp_path, "places-a", ["work/*", "lab/*/runs"])
    assert manifests.load(world.root).problems == []
    world.manifest(MANIFEST.format(work='["work/*", 3]'))
    assert any("work" in problem for problem in manifests.load(world.root).problems)


def test_new_logs_under_the_one_pattern_that_can_name_a_unit(tmp_path: Path) -> None:
    world = project(tmp_path, "places-b", ["work/*", "lab/*/*/runs"])
    assert run(world, "new", "first", "--question", "does it hold?") == EXIT_PASS
    [record] = (world.root / "ledger").glob("*.toml")
    assert tomllib.loads(record.read_text())["work"].startswith("work/")


def test_new_asks_which_place_when_several_could_hold_the_unit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = project(tmp_path, "places-c", ["work/*", "lab/*"])
    assert run(world, "new", "first", "--question", "does it hold?") == EXIT_REFUSE
    assert "--under" in capsys.readouterr().err
    assert run(world, "new", "first", "--question", "does it hold?", "--under", "elsewhere/*") == EXIT_REFUSE
    assert run(world, "new", "first", "--question", "does it hold?", "--under", "lab/*") == EXIT_PASS
    [record] = (world.root / "ledger").glob("*.toml")
    assert tomllib.loads(record.read_text())["work"].startswith("lab/")


def test_cite_and_run_find_a_unit_under_the_second_pattern(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = project(tmp_path, "places-d", ["work/*", "lab/*/runs"])
    assert run(world, "cite", "runs", "hit_rate") == EXIT_PASS  # a tag names a unit by its folder name
    assert capsys.readouterr().out.strip() == "0.4321<!--t:runs#hit_rate-->"
    assert run(world, "run", "lab/x/runs", "--", sys.executable, "-c", "pass") == EXIT_PASS
    [receipt] = (world.root / "receipts/run").glob("*.json")
    assert json.loads(receipt.read_text())["work"] == "lab/x/runs"
