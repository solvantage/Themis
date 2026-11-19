"""The layout, views and docs rules added in 0.2.0, on a plain project that is not a trading one.

A core rule must hold in any repository. So these rules are run together, at enforce, on a small
docs-and-scripts project built in a temporary folder: it passes as built, and each planted fault
fails it. The stricter directions of the new parameters are held here too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from themis import configguard, gates
from themis.cli import main
from themis.gates.views import stamp
from themis.proofs import World
from themis.verdict import EXIT_CODE, Verdict

gates.load_all()

MANIFEST = """
    [project]
    name = "plain"

    [rules."layout/required-files"]
    level = "enforce"
    kinds.script = { folders = "scripts/*", files = ["README.md"] }

    [rules."layout/retired-names"]
    level = "enforce"
    names = ["old-site"]
    allow = [{ file = "docs/history.md", line = "Formerly old-site." }]

    [rules."layout/no-ignored-citations"]
    level = "enforce"
    pages = ["**/*.md"]
    index = ["docs/kept-elsewhere.md"]

    [rules."views/untouched"]
    level = "enforce"
    pages = ["docs/**/*.md"]

    [rules."docs/no-bare-dollar-pairs"]
    level = "enforce"
    pages = ["**/*.md"]
"""
COMMANDS = "# Commands\n\n| Script | What it does |\n| --- | --- |\n| `scripts/deploy/run.sh` | Ships the site |\n"


def plain_project(tmp_path: Path) -> World:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest(MANIFEST)
    world.write(".gitignore", "/build/\n")
    world.write("README.md", "# The site\n\nIt costs \\$5 a month. See [the commands](docs/commands.md).\n")
    world.write("scripts/deploy/README.md", "# Deploy\n")
    world.write("scripts/deploy/run.sh", "echo ship\n")
    world.write("docs/history.md", "# History\n\nFormerly old-site.\n")
    world.write("docs/kept-elsewhere.md", "# Kept outside git\n\n- `build/`: rebuilt by `scripts/deploy/run.sh`\n")
    world.write("docs/commands.md", stamp(COMMANDS, "scripts/list.py --doc"))
    world.commit("start")
    return world


def _cite_an_ignored_folder(world: World) -> None:
    world.write(".gitignore", "/build/\n/notes/\n")
    world.write("docs/faq.md", "See `notes/plan.md`.\n")


PLANTS = {
    "required-files": lambda world: world.remove("scripts/deploy/README.md"),
    "retired-names": lambda world: world.write("docs/faq.md", "Is this the Old-Site? Yes.\n"),
    "no-ignored-citations": _cite_an_ignored_folder,
    "untouched": lambda world: world.write("docs/commands.md", stamp(COMMANDS, "x").replace("Ships the", "Ships")),
    "bare-dollar-pairs": lambda world: world.write("docs/faq.md", "It costs $5 a month or $50 a year.\n"),
}


def check(world: World) -> int:
    return main(["check", "--root", str(world.root)])


def test_the_plain_project_passes_as_built(tmp_path: Path) -> None:
    assert check(plain_project(tmp_path)) == EXIT_CODE[Verdict.PASS]


@pytest.mark.parametrize("plant", sorted(PLANTS))
def test_each_planted_fault_fails_the_plain_project(tmp_path: Path, plant: str,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    world = plain_project(tmp_path)
    PLANTS[plant](world)
    capsys.readouterr()
    assert check(world) == EXIT_CODE[Verdict.FAIL]
    assert plant in capsys.readouterr().out


KINDS = {"script": {"folders": "scripts/*", "files": ["README.md"]}}


@pytest.mark.parametrize(
    ("before", "after", "kind"),
    [
        ({}, KINDS, "tightening"),
        (KINDS, KINDS | {"guide": {"folders": "docs/*", "files": ["index.md"]}}, "tightening"),
        (KINDS, {"script": {"folders": "scripts/*", "files": ["README.md", "run.sh"]}}, "tightening"),
        (KINDS, {"script": {"folders": "scripts/*", "files": []}}, "weakening"),
        (KINDS, {"script": {"folders": "scripts/deploy", "files": ["README.md"]}}, "weakening"),
        (KINDS, {}, "weakening"),
    ],
)
def test_a_new_kind_or_a_new_file_is_a_tightening(before: dict, after: dict, kind: str) -> None:
    old = {"rules": {"layout/required-files": {"kinds": before}}}
    new = {"rules": {"layout/required-files": {"kinds": after}}}
    assert {change.kind for change in configguard.classify(old, new)} == {kind}


@pytest.mark.parametrize(
    ("rule_id", "name", "before", "after", "kind"),
    [
        ("layout/retired-names", "names", ["old"], ["old", "older"], "tightening"),
        ("layout/retired-names", "allow", [], [{"file": "a.md", "line": "old"}], "weakening"),
        ("layout/no-ignored-citations", "index", [], ["docs/archive.md"], "weakening"),
        ("layout/no-ignored-citations", "pages", ["docs/**"], ["docs/**", "**"], "tightening"),
        ("views/untouched", "pages", ["docs/**"], [], "weakening"),
        ("docs/no-bare-dollar-pairs", "pages", ["docs/**"], ["docs/**", "*.md"], "tightening"),
    ],
)
def test_each_new_parameter_tightens_its_own_way(rule_id: str, name: str, before: list, after: list,
                                                 kind: str) -> None:
    old, new = {"rules": {rule_id: {name: before}}}, {"rules": {rule_id: {name: after}}}
    assert {change.kind for change in configguard.classify(old, new)} == {kind}
