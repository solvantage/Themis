"""`themis describe` counts what is not in force the same way with or without --status, and
`themis describe --markdown` prints the whole catalogue, written from the rules themselves."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from themis import gates, pack
from themis.cli import EXIT_PASS, EXIT_REFUSE, main
from themis.proofs import World
from themis.rule import PROOFS, RULES

MANIFEST = """
[project]
name = "notes"

[rules."registry/indexed"]
work = "notes/*"
index = "notes/INDEX.md"
"""


def a_project(tmp_path: Path) -> World:
    """A plain docs-and-scripts project. Rules such as agents/hooks-installed need a table it has
    not written, which only running them reveals."""
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest(MANIFEST)
    world.write("notes/first/README.md", "# First\n")
    world.write("notes/INDEX.md", "- first\n")
    world.write("scripts/build.sh", "echo built\n")
    world.commit("start")
    return world


def described(world: World, capsys: pytest.CaptureFixture[str], *flags: str) -> str:
    assert main(["describe", "--root", str(world.root), *flags]) == EXIT_PASS
    return capsys.readouterr().out


def test_describe_and_its_status_count_the_same(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = a_project(tmp_path)
    plain, status = described(world, capsys), described(world, capsys, "--status")
    count = re.compile(r"(\d+) rule\(s\) are off, not configured or unproven")
    assert count.search(plain).group(1) == count.search(status).group(1)
    for text in (plain, status):
        line = next(line for line in text.splitlines() if "agents/hooks-installed" in line)
        assert "not configured" in line  # needs [agents], which this project has not written
    assert "now: pass" in next(line for line in status.splitlines() if "registry/indexed" in line)
    assert "now:" not in plain


def test_the_catalogue_lists_every_rule_with_its_gate_promise_level_and_proofs(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = a_project(tmp_path)
    text = described(world, capsys, "--markdown")
    plain = described(world, capsys)
    states = {match[0]: match[1] for match in re.findall(r"^   ([a-z-]+/[a-z-]+)\s+(not configured|off|warn|enforce)\s",
                                                       plain, flags=re.M)}
    gates.load_all()
    for name in ("trading", "marketing"):
        pack.load(name)
    found = re.findall(r"^\| `([a-z-]+/[a-z-]+)` \| ([a-z-]+) \| (.*) \| (.*) \| (\d+) \|$", text, flags=re.M)
    rows = {row[0]: row for row in found}
    assert len(rows) == len(found)  # one row a rule
    assert set(rows) == set(RULES)
    for rule_id, (_, gate, promise, level, count) in rows.items():
        rule = RULES[rule_id]
        assert gate == rule.gate and promise == rule.promise.replace("|", "\\|")
        assert int(count) == len(PROOFS.get(rule_id, []))
        assert level == ("pack off" if rule.pack != "core" else states[rule_id])  # as plain describe says
    assert rows["agents/hooks-installed"][3] == "not configured" and rows["registry/indexed"][3] == "warn"
    assert f"## core\n\n{sum(rule.pack == 'core' for rule in RULES.values())} rules in" in text


def test_the_catalogue_needs_no_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["describe", "--root", str(tmp_path), "--markdown"]) == EXIT_PASS
    text = capsys.readouterr().out
    assert "a rule a project does not name runs at `warn`" in text and "## trading" in text
    assert main(["describe", "--root", str(tmp_path)]) == EXIT_REFUSE  # the plain listing describes a project
