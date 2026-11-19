"""What git knows: a file's arrival is a place on the whole main line.

A main line also holds commits that add nothing: an edit, a merge of edits. A position read from
`arrivals` must still index `main_line`, or a rule reads the wrong commit's date, or reads a seal
at a commit where it does not exist yet.
"""

from __future__ import annotations

from pathlib import Path

from themis import engine, gates
from themis import manifest as manifests
from themis.gitlog import Git
from themis.proofs import World
from themis.rule import RULES

gates.load_all()


def a_line_with_edits(tmp_path: Path) -> World:
    """start · an edit · a merge of edits · the seal's merge · an edit · a merge of edits."""
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest('[rules."order/unchanged"]\nwork = "work/*"\nseal = ["PLAN.md"]\n')
    world.write("notes.md", "one\n")
    world.commit("start")
    world.write("notes.md", "two\n")
    world.commit("an edit that adds nothing")
    world.pull_request("edits", {"notes.md": "three\n"})
    world.pull_request("seal", {"work/a/PLAN.md": "the plan\n"})
    world.write("notes.md", "four\n")
    world.commit("another edit")
    world.pull_request("more", {"notes.md": "five\n"})
    return world


def test_each_arrival_indexes_the_whole_main_line(tmp_path: Path) -> None:
    world = a_line_with_edits(tmp_path)
    git = Git(world.root)
    line, arrivals = git.main_line("main"), git.arrivals("main")
    assert len(line) == 6
    assert arrivals["notes.md"] == 0 and arrivals["themis.toml"] == 0
    assert arrivals["work/a/PLAN.md"] == 3
    assert git.show(line[arrivals["work/a/PLAN.md"]], "work/a/PLAN.md") == "the plan\n"
    assert git.show(line[arrivals["work/a/PLAN.md"] - 1], "work/a/PLAN.md") is None


def test_a_renamed_file_arrives_where_it_was_renamed(tmp_path: Path) -> None:
    world = a_line_with_edits(tmp_path)
    world.move("work/a/PLAN.md", "work/a/SEAL.md")
    world.commit("rename")
    git = Git(world.root)
    assert git.arrivals("main")["work/a/SEAL.md"] == len(git.main_line("main")) - 1


def test_a_seal_among_edits_is_read_at_its_own_merge(tmp_path: Path) -> None:
    """Before the fix the seal was read one place too early, where it did not exist: a refusal."""
    world = a_line_with_edits(tmp_path)
    result = engine.run_rule(RULES["order/unchanged"], manifests.load(world.root), force=True)
    assert result.verdict.value == "pass", [finding.message for finding in result.findings]
    assert result.inspected == 1
