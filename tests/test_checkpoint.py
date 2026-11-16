"""The checkpoint library: reading the file's shape, and writing the facts into it."""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path

import pytest

from themis import checkpoint, engine, gates, proofs, receipts
from themis import manifest as manifests
from themis.proofs import World
from themis.rule import RULES
from themis.verdict import Verdict

gates.load_all()
RULE_IDS = ("checkpoint/git-true", "checkpoint/pointers", "checkpoint/shape", "checkpoint/suite-receipt")

PAGE = """\
# Checkpoint — where we left off

**Last updated:** 2026-11-16 15:20 local (08:20 UTC). `main` at `a1b2c3d4` (#42).
**Suite:** 1,204 pass / 3 skip<!--r:suite/abc123-->, linter clean.
**Changed:** the gate reads the checkpoint.
**Next:** wire the command.

## Recently shipped

**2026-11-16 — a theme (#40–#42):**

- a bullet of one sentence
- another bullet
  that runs on to a second line

**2026-11-15 — an older theme:**

- one bullet

## Standing traps

- a trap, with a link to [its home record](docs/issues/x.md)

## Do not re-propose

- a decision, with a link to [its record](decisions/y.json#why)
"""
HEAD = "**Last updated:** 2026-11-16 15:20 local (08:20 UTC). `main` at `a1b2c3d4`.\n"
FACTS = {"utc": "2026-11-16 08:20", "local": "2026-11-16 15:20", "main": "main", "commit": "a1b2c3d4",
         "tree": "0" * 40, "pull_request": 42, "suite": None}
RECEIPT = {"_path": "receipts/suite/abc123.json", "tree": "0" * 40, "passed": 1204, "skipped": 3, "failed": 0,
           "errors": 0}


# -- reading ------------------------------------------------------------------------------------


def test_the_headline_is_read() -> None:
    page = checkpoint.parse(PAGE)
    assert page.lines == len(PAGE.splitlines())
    assert page.headline_line == 3 and len(page.headline) == 4
    assert (page.main, page.commit) == ("main", "a1b2c3d4")
    assert page.suite_line == 4 and page.suite.startswith("**Suite:**")
    assert (page.receipt, page.passed, page.skipped, page.unverified) == ("abc123", 1204, 3, False)


def test_the_headline_ends_at_the_first_blank_line() -> None:
    page = checkpoint.parse(HEAD + "**Suite:** unverified.\n**Next:** ship.\n\n**Changed:** not part of it.\n")
    assert page.headline == (HEAD.strip(), "**Suite:** unverified.", "**Next:** ship.")


def test_a_page_with_no_headline_reads_as_empty() -> None:
    page = checkpoint.parse("# Notes\n\nNothing yet.\n")
    assert page.headline == () and page.headline_line is None and page.lines == 3
    assert page.commit is None and page.suite is None and page.receipt is None and not page.unverified
    assert checkpoint.parse("").lines == 0


@pytest.mark.parametrize(("stamp", "commit"), [
    ("`main` at `a1b2c3d`.", "a1b2c3d"),
    ("`origin/main` at `" + "ab" * 20 + "` (#9).", "ab" * 20),
    ("`main` at `a1b2c3`.", None),  # six characters name no commit
    ("`main` at `not-hex1`.", None),
    ("main at a1b2c3d4.", None),  # the shape is exact: both parts sit in backticks
])
def test_the_commit_the_headline_names(stamp: str, commit: str | None) -> None:
    assert checkpoint.parse(f"**Last updated:** today. {stamp}\n").commit == commit


@pytest.mark.parametrize(("line", "passed", "skipped"), [
    ("**Suite:** 1,204 pass / 3 skip.", 1204, 3),
    ("**Suite:** 12 passed, 0 skipped.", 12, 0),
    ("**Suite:** 1,234,567 pass.", 1234567, None),
    ("**Suite:** all green.", None, None),
    ("**Suite:** 1.204 pass.", None, None),  # not a separator this reader knows, so no number is guessed
    ("**Suite:** 12,04 pass.", None, None),
    ("**Suite:** 7 pass<!-- it was 9 skip -->.", 7, None),  # a comment is not part of what the line says
])
def test_the_counts_on_the_suite_line(line: str, passed: int | None, skipped: int | None) -> None:
    page = checkpoint.parse(HEAD + line + "\n")
    assert (page.passed, page.skipped) == (passed, skipped)


def test_the_label_unverified_is_read_in_any_case() -> None:
    assert checkpoint.parse(HEAD + "**Suite:** Unverified — no receipt for this tree.\n").unverified
    assert not checkpoint.parse(HEAD + "**Suite:** verified by hand.\n").unverified
    assert not checkpoint.parse(HEAD + "**Suite:** 3 pass<!-- unverified -->.\n").unverified


def test_dated_entries_and_their_bullets_are_counted() -> None:
    found = [(entry.date, entry.line, entry.bullets) for entry in checkpoint.parse(PAGE).entries]
    assert found == [("2026-11-16", 10, 2), ("2026-11-15", 16, 1)]


def test_each_heading_holds_its_bullets() -> None:
    page = checkpoint.parse(PAGE)
    assert list(page.sections)[1:] == ["Recently shipped", "Standing traps", "Do not re-propose"]
    assert [bullet.text for bullet in page.section("standing TRAPS")] == [
        "a trap, with a link to [its home record](docs/issues/x.md)"
    ]
    second = page.section("Recently shipped")[1]
    assert (second.text, second.line) == ("another bullet that runs on to a second line", 13)
    assert page.section("No such heading") == ()


def test_a_heading_holds_the_bullets_of_its_deeper_headings() -> None:
    page = checkpoint.parse("# Top\n\n## Traps\n\n- one\n\n### Older\n\n- two\n\n## Notes\n\n- three\n")
    assert [bullet.text for bullet in page.section("Traps")] == ["one", "two"]
    assert [bullet.text for bullet in page.section("Older")] == ["two"]
    assert [bullet.text for bullet in page.section("Notes")] == ["three"]
    assert [bullet.text for bullet in page.section("Top")] == ["one", "two", "three"]
    twice = checkpoint.parse("## Notes\n\n### Notes\n\n- once\n")
    assert [bullet.text for bullet in twice.section("Notes")] == ["once"]


def test_a_code_block_is_not_part_of_the_shape() -> None:
    example = "**Last updated:** an example. `main` at `fffffff`.\n**2026-01-01 — an example:**\n- one\n## Inside\n"
    page = checkpoint.parse("## Example\n\n```\n" + example + "```\n\n" + PAGE)
    assert page.commit == "a1b2c3d4" and len(page.entries) == 2
    assert "Inside" not in page.sections and page.section("Example") == ()


def test_every_bullet_mark_counts_and_a_drawn_line_does_not() -> None:
    page = checkpoint.parse("## Standing traps\n\n- - -\n\n* a trap\n+ another\n- a third\n**bold** is not a bullet\n")
    assert [bullet.text for bullet in page.section("Standing traps")] == [
        "a trap", "another", "a third **bold** is not a bullet"
    ]


def test_the_links_in_a_bullet() -> None:
    text = "see [one](docs/a.md#part), ![a view](shot.png), [two](<docs/b c.md>) and [three](https://example.invalid/x)"
    assert checkpoint.links(text) == ["docs/a.md#part", "docs/b c.md", "https://example.invalid/x"]


@pytest.mark.parametrize(("link", "folder", "path"), [
    ("docs/a.md", "", "docs/a.md"),
    ("docs/a.md#part", "", "docs/a.md"),
    ("../decisions/y.json", "docs", "decisions/y.json"),
    ("./a%20b.md", "docs", "docs/a b.md"),
    ("#part", "", None),
    ("https://example.invalid/x", "", None),
    ("mailto:owner@example.invalid", "", None),
    ("/docs/a.md", "", None),
    ("../outside.md", "", None),
])
def test_where_a_link_points(link: str, folder: str, path: str | None) -> None:
    assert checkpoint.target_path(link, folder) == path


def test_a_receipt_holds_four_whole_counts_or_none_at_all() -> None:
    assert checkpoint.counts(RECEIPT) == {"passed": 1204, "skipped": 3, "failed": 0, "errors": 0}
    assert checkpoint.counts({"passed": 1204, "skipped": 3}) is None  # two counts are missing
    for broken in ({"passed": "1204"}, {"failed": True}, {"errors": -1}, {"skipped": None}):
        assert checkpoint.counts({**RECEIPT, **broken}) is None


# -- the headline -------------------------------------------------------------------------------


def test_a_headline_with_no_receipt_says_unverified_and_leaves_two_lines_to_write() -> None:
    lines = checkpoint.headline(FACTS)
    assert lines == [
        "**Last updated:** 2026-11-16 15:20 local (08:20 UTC). `main` at `a1b2c3d4` (#42).",
        "**Suite:** unverified — no receipt for this tree.",
        "**Changed:** (write one line)",
        "**Next:** (write one line)",
    ]
    assert not re.search("[<>]", "".join(lines))


def test_a_headline_cites_the_receipt_and_reads_back_the_same() -> None:
    facts = {**FACTS, "suite": RECEIPT, "pull_request": None}
    lines = checkpoint.headline(facts, changed="two\nlines   here", next_step="ship it")
    assert lines[0].endswith("`main` at `a1b2c3d4`.")
    assert lines[1] == "**Suite:** 1,204 pass / 3 skip<!--r:suite/abc123-->."
    assert lines[2:] == ["**Changed:** two lines here", "**Next:** ship it"]
    page = checkpoint.parse("\n".join(lines))
    assert (page.commit, page.receipt, page.passed, page.skipped) == ("a1b2c3d4", "abc123", 1204, 3)


def test_a_failing_receipt_is_stated_not_hidden() -> None:
    suite = {**RECEIPT, "failed": 2, "errors": 1}
    assert checkpoint.headline({**FACTS, "suite": suite})[1] == (
        "**Suite:** 1,204 pass / 3 skip / 2 fail / 1 error<!--r:suite/abc123-->."
    )


def test_the_headline_says_only_what_the_facts_hold() -> None:
    late = checkpoint.headline({**FACTS, "local": "2026-11-17 01:20", "utc": "2026-11-16 18:20"})
    assert late[0].startswith("**Last updated:** 2026-11-17 01:20 local (2026-11-16 18:20 UTC).")
    bare = checkpoint.headline({**FACTS, "main": None, "commit": None})
    assert bare[0] == "**Last updated:** 2026-11-16 15:20 local (08:20 UTC)."


# -- the facts, and writing them ----------------------------------------------------------------


def project(tmp_path: Path, manifest: str = '[project]\nname = "demo"\n') -> World:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest(manifest)
    world.write("src/app.py", "print('hello')\n")
    world.commit("start (#7)")
    return world


def suite_ran(world: World, **changes: object) -> str:
    """A local suite receipt for the current tree, named as the test plugin names it. Returns the name."""
    tree = receipts.tree_fingerprint(world.root)
    counts = {"passed": 1204, "skipped": 3, "failed": 0, "errors": 0}
    receipts.write(world.root, "suite", tree, {"tree": tree, "at": receipts.now(), **counts, **changes})
    return tree


def refreshed(world: World) -> list[str]:
    return checkpoint.refresh(world.root, manifests.load(world.root)).read_text(encoding="utf-8").splitlines()


def verdict(world: World, rule_id: str) -> Verdict | None:
    return proofs.judge(world.root, rule_id).verdict


def test_the_facts_of_a_repository(tmp_path: Path) -> None:
    world = project(tmp_path)
    moment = dt.datetime(2026, 11, 16, 8, 20, tzinfo=dt.timezone.utc)
    known = checkpoint.facts(world.root, manifests.load(world.root), now=moment)
    assert known["utc"] == "2026-11-16 08:20" and re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", known["local"])
    assert known["main"] == "main" and world.git("rev-parse", "HEAD").startswith(known["commit"])
    assert len(known["commit"]) >= 7 and known["tree"] == world.git("rev-parse", "HEAD^{tree}").strip()
    assert known["pull_request"] == 7 and known["suite"] is None
    name = suite_ran(world)
    suite = checkpoint.facts(world.root, manifests.load(world.root))["suite"]
    assert (suite["passed"], suite["skipped"], checkpoint.receipt_name(suite)) == (1204, 3, name)


def test_a_folder_with_no_history_has_no_main_line_to_name(tmp_path: Path) -> None:
    known = checkpoint.facts(tmp_path, manifests.load(tmp_path))
    assert known["main"] is None and known["commit"] is None and known["suite"] is None


def test_a_receipt_is_found_by_name_and_the_committed_copy_comes_first(tmp_path: Path) -> None:
    assert checkpoint.receipt_named(tmp_path, "t1") is None
    receipts.write(tmp_path, "suite", "t1", {"passed": 1})
    assert checkpoint.receipt_named(tmp_path, "t1")["passed"] == 1
    receipts.write(tmp_path, "suite", "t1", {"passed": 2}, committed=True)
    assert checkpoint.receipt_named(tmp_path, "t1")["_path"] == "receipts/suite/t1.json"
    assert checkpoint.receipt_named(tmp_path, "t") is None


def test_a_first_refresh_writes_a_whole_checkpoint_that_passes_the_gate(tmp_path: Path) -> None:
    world = project(tmp_path)
    assert checkpoint.refresh(world.root, manifests.load(world.root)) == world.root / "CHECKPOINT.md"
    lines = (world.root / "CHECKPOINT.md").read_text(encoding="utf-8").splitlines()
    assert lines[0] == checkpoint.TITLE and lines[2].startswith("**Last updated:**")
    assert lines[3:6] == [checkpoint.NO_RECEIPT, "**Changed:** (write one line)", "**Next:** (write one line)"]
    headings = [line for line in lines if line.startswith("## ")]
    assert headings == ["## Recently shipped", "## Standing traps", "## Do not re-propose"]
    assert [verdict(world, rule_id) for rule_id in RULE_IDS] == [Verdict.PASS] * 4


def test_a_refresh_cites_the_receipt_and_leaves_a_copy_for_the_next_reader(tmp_path: Path) -> None:
    world = project(tmp_path)
    name = suite_ran(world)
    page = checkpoint.parse("\n".join(refreshed(world)))
    assert (page.receipt, page.passed, page.skipped) == (name, 1204, 3)
    copy = json.loads((world.root / "receipts" / "suite" / f"{name}.json").read_text(encoding="utf-8"))
    assert copy["tree"] == name and copy["passed"] == 1204 and "_path" not in copy
    shutil.rmtree(world.root / ".themis")  # the next reader has only what was committed
    world.commit("the checkpoint")
    assert [verdict(world, rule_id) for rule_id in RULE_IDS] == [Verdict.PASS] * 4


def test_a_second_refresh_still_cites_the_receipt(tmp_path: Path) -> None:
    world = project(tmp_path)
    name = suite_ran(world)
    refreshed(world)  # the checkpoint and the copied receipt now make the tree differ from its commit
    assert checkpoint.parse("\n".join(refreshed(world))).receipt == name
    assert verdict(world, "checkpoint/suite-receipt") is Verdict.PASS


def test_a_receipt_for_another_tree_is_never_cited(tmp_path: Path) -> None:
    world = project(tmp_path)
    world.branch("topic")
    world.write("src/more.py", "x = 1\n")
    world.commit("more")
    suite_ran(world)  # the suite ran on the branch, not on the commit main is at
    page = checkpoint.parse("\n".join(refreshed(world)))
    assert page.unverified and page.receipt is None and not (world.root / "receipts").exists()
    assert world.git("rev-parse", "main").startswith(page.commit)
    assert [verdict(world, rule_id) for rule_id in RULE_IDS] == [Verdict.PASS] * 4


def test_a_refresh_keeps_what_the_agent_wrote(tmp_path: Path) -> None:
    world = project(tmp_path)
    world.write("CHECKPOINT.md", PAGE)
    before, after = PAGE.splitlines(), refreshed(world)
    assert world.git("rev-parse", "--short=8", "HEAD").strip() in after[2] and "a1b2c3d4" not in after[2]
    assert after[3] == checkpoint.NO_RECEIPT
    assert after[:2] == before[:2] and after[4:] == before[4:]


def test_a_refresh_gives_a_headline_to_a_page_that_has_none(tmp_path: Path) -> None:
    world = project(tmp_path)
    world.write("CHECKPOINT.md", "# Handoff\n\n## Standing traps\n\n- a trap\n")
    lines = refreshed(world)
    assert lines[:2] == ["# Handoff", ""] and lines[2].startswith("**Last updated:**")
    assert lines[5:] == ["**Next:** (write one line)", "", "## Standing traps", "", "- a trap"]


def test_a_refresh_completes_a_headline_that_lost_its_lines(tmp_path: Path) -> None:
    world = project(tmp_path)
    world.write("CHECKPOINT.md", "**Last updated:** long ago.\n**Next:** ship it.\n\nNotes.\n")
    lines = refreshed(world)
    assert lines[1:] == [checkpoint.NO_RECEIPT, "**Next:** ship it.", "**Changed:** (write one line)", "", "Notes."]


def test_a_refresh_writes_to_the_home_the_manifest_names(tmp_path: Path) -> None:
    world = project(tmp_path, '[homes]\ncheckpoint = "docs/HANDOFF.md"\n')
    assert checkpoint.refresh(world.root, manifests.load(world.root)) == world.root / "docs" / "HANDOFF.md"
    assert not (world.root / "CHECKPOINT.md").exists()


def test_a_refresh_keeps_the_line_endings_of_the_file(tmp_path: Path) -> None:
    world = project(tmp_path)
    (world.root / "CHECKPOINT.md").write_bytes(PAGE.replace("\n", "\r\n").encode("utf-8"))
    written = checkpoint.refresh(world.root, manifests.load(world.root)).read_bytes()
    assert written.count(b"\r\n") == len(PAGE.splitlines()) and b"\n" not in written.replace(b"\r\n", b"")


# -- the gate, where a world cannot show it -----------------------------------------------------


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_a_project_with_no_checkpoint_is_not_configured(tmp_path: Path, rule_id: str) -> None:
    world = project(tmp_path)
    result = engine.run_rule(RULES[rule_id], manifests.load(world.root), force=True)
    assert result.status == "not configured" and "CHECKPOINT.md" in result.note
