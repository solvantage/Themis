"""Gate: registry — past lessons stay findable.

Work that cannot be found is done again, and a lesson with no reason is argued again. So an index
lists every unit of work, a finding that was closed says what was decided, and an issue marked
enforced points at the test that now enforces it.
"""

from __future__ import annotations

import posixpath
import re
from typing import TYPE_CHECKING, Any

from themis import work
from themis.gates.order import WORK
from themis.rule import Context, Param, proof, rule

if TYPE_CHECKING:
    from themis.proofs import World

INDEX = Param("index", str, None, None, "the file that lists every unit of work, such as work/INDEX.md")
CLOSED = ("fixed", "wontfix", "refuted")
MANIFEST = """
    [project]
    name = "world"
"""


def _units(ctx: Context) -> dict[str, list[str]]:
    try:
        return work.units(ctx.all_files, ctx.param("work"))
    except ValueError as error:
        ctx.refuse(str(error), where="themis.toml", fix="name the unit folders at one depth, such as work/*")
        return {}


def _named(name: str, text: str) -> bool:
    """True when the text holds this name whole, and not only as part of a longer name."""
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text) is not None


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


# -- registry/indexed ---------------------------------------------------------------------------


@rule(
    "registry/indexed",
    "Every unit of work appears in the index.",
    params=(WORK, INDEX),
    requires=("work", "index"),
    learned="A piece of work was done a second time, because no list showed it had been done before.",
)
def indexed(ctx: Context) -> None:
    index = ctx.param("index").strip("/")
    text = ctx.read(index)
    if text is None:
        ctx.refuse("the index file is missing, or it cannot be read as text", where=index,
                   fix="create the index, and list every unit of work in it")
        return
    for unit in sorted(_units(ctx)):
        ctx.inspect()
        name = unit.rsplit("/", 1)[-1]
        if not _named(name, text):
            ctx.breach(f"the unit {name} does not appear in the index", where=unit,
                       fix=f"add a line for {name} to {index}: what was tried, and what came of it")


INDEXED = """
    [rules."registry/indexed"]
    work = "work/*"
    index = "work/INDEX.md"
"""
PLAN = "the plan\n"


@proof("registry/indexed", "every unit has its line in the index", expect="pass")
def _(world: World) -> None:
    world.manifest(INDEXED)
    world.write("work/run-1/PLAN.md", PLAN)
    world.write("work/run-2/PLAN.md", PLAN)
    world.write("work/INDEX.md", "# Work\n\n- [run-1](run-1/PLAN.md): the first try\n- run-2: the second try\n")


@proof("registry/indexed", "a unit the index does not list", expect="fail",
       contains="the unit run-2 does not appear in the index")
def _(world: World) -> None:
    world.manifest(INDEXED)
    world.write("work/run-1/PLAN.md", PLAN)
    world.write("work/run-2/PLAN.md", PLAN)
    world.write("work/INDEX.md", "# Work\n\n- run-1: the first try\n")


@proof("registry/indexed", "a longer name that holds the unit's name does not count", expect="fail",
       contains="the unit run-1 does not appear in the index")
def _(world: World) -> None:
    world.manifest(INDEXED)
    world.write("work/run-1/PLAN.md", PLAN)
    world.write("work/run-10/PLAN.md", PLAN)
    world.write("work/INDEX.md", "# Work\n\n- run-10: the tenth try\n")


@proof("registry/indexed", "work with no index file", expect="refuse", contains="index file is missing")
def _(world: World) -> None:
    world.manifest(INDEXED)
    world.write("work/run-1/PLAN.md", PLAN)


@proof("registry/indexed", "an index with no unit of work to list", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    world.manifest(INDEXED)
    world.write("work/INDEX.md", "# Work\n\nNothing yet.\n")


# -- registry/closed-says-why -------------------------------------------------------------------


@rule(
    "registry/closed-says-why",
    "A closed finding states its decision, and a finding left unfixed names what would reopen it.",
    learned="A finding was closed with no reason, so the same finding was raised and argued again.",
)
def closed_says_why(ctx: Context) -> None:
    for finding in ctx.records("finding"):
        ctx.inspect()
        status = finding.get("status")
        if status not in CLOSED:
            continue  # an open finding has nothing to explain yet
        if _blank(finding.get("decision")):
            ctx.breach(f"this finding is closed as {status} but states no decision", where=finding.path,
                       fix="add decision: what was decided, and why")
        if status == "wontfix" and _blank(finding.get("reopens_if")):
            ctx.breach("this finding is left unfixed but does not say what would reopen it", where=finding.path,
                       fix="add reopens_if: the event or the evidence that would bring the finding back")


def _finding(world: World, name: str, status: str, **fields: str) -> None:
    lines = [f'title = "{name}"', f'status = "{status}"', *(f'{key} = "{value}"' for key, value in fields.items())]
    world.manifest(MANIFEST)
    world.write(f"docs/findings/2026-01-05-{name}.toml", "\n".join(lines) + "\n")


@proof("registry/closed-says-why", "closed findings that say why, beside an open one", expect="pass")
def _(world: World) -> None:
    _finding(world, "stale-cache", "fixed", decision="the cache is now cleared on every start")
    _finding(world, "slow-start", "wontfix", decision="a start takes two seconds, and nobody waits on it",
             reopens_if="a start takes longer than ten seconds")
    _finding(world, "lost-rows", "refuted", decision="the rows were filtered on purpose; the count matches")
    _finding(world, "odd-total", "open")


@proof("registry/closed-says-why", "a finding marked fixed with no decision", expect="fail",
       contains="closed as fixed but states no decision")
def _(world: World) -> None:
    _finding(world, "stale-cache", "fixed")


@proof("registry/closed-says-why", "a refuted finding whose decision is blank", expect="fail",
       contains="closed as refuted but states no decision")
def _(world: World) -> None:
    _finding(world, "lost-rows", "refuted", decision="  ")


@proof("registry/closed-says-why", "a finding left unfixed with nothing that would reopen it", expect="fail",
       contains="does not say what would reopen it")
def _(world: World) -> None:
    _finding(world, "slow-start", "wontfix", decision="a start takes two seconds, and nobody waits on it")


@proof("registry/closed-says-why", "a finding with a status nobody defined", expect="refuse", contains="must be one of")
def _(world: World) -> None:
    _finding(world, "stale-cache", "done", decision="the cache is now cleared on every start")


@proof("registry/closed-says-why", "a project with no finding at all", expect="refuse",
       contains="nothing was inspected")
def _(world: World) -> None:
    world.manifest(MANIFEST)
    world.write("docs/README.md", "No audit has run yet.\n")


# -- registry/graduated -------------------------------------------------------------------------


@rule(
    "registry/graduated",
    "An issue marked enforced names a test that exists.",
    learned="An issue was marked as enforced, but the test it named had been deleted.",
)
def graduated(ctx: Context) -> None:
    files = set(ctx.all_files)
    for issue in ctx.records("issue"):
        ctx.inspect()
        if issue.get("status") != "enforced":
            continue  # only an enforced issue claims that a test guards it
        named = issue.get("enforced_by")
        if _blank(named):
            ctx.breach("this issue is marked enforced but names no test", where=issue.path,
                       fix="add enforced_by: the test file, or file::test, that fails when the issue comes back")
            continue
        first, *tests = (part.strip() for part in named.split("::"))
        path = posixpath.normpath(first)
        if path not in files:
            ctx.breach(f"this issue is enforced by {path}, which does not exist", where=issue.path,
                       fix="name the test that enforces the issue, or set its status back to open")
            continue
        text = ctx.read(path)
        for test in (test.split("[", 1)[0] for test in tests):
            if text is not None and test and not _named(test, text):
                ctx.breach(f"this issue is enforced by {named}, but {path} holds no test named {test}",
                           where=issue.path, fix="name a test that is still there, or set the status back to open")


A_TEST = "def test_cache_is_fresh():\n    assert True\n"


def _issue(world: World, name: str, status: str, enforced_by: str = "") -> None:
    lines = ["---", f"title: {name}", f"status: {status}", *([f"enforced_by: {enforced_by}"] if enforced_by else []),
             "---", "", "What went wrong, and what catches it now.", ""]
    world.manifest(MANIFEST)
    world.write(f"docs/issues/{name}.md", "\n".join(lines))


@proof("registry/graduated", "enforced issues that name tests which exist, beside an open one", expect="pass")
def _(world: World) -> None:
    world.write("tests/test_cache.py", A_TEST)
    _issue(world, "stale-cache", "enforced", "tests/test_cache.py::test_cache_is_fresh")
    _issue(world, "stale-cache-on-start", "enforced", "tests/test_cache.py::test_cache_is_fresh[on start]")
    _issue(world, "cold-cache", "enforced", "tests/test_cache.py")
    _issue(world, "slow-start", "open")


@proof("registry/graduated", "an enforced issue that names no test", expect="fail", contains="names no test")
def _(world: World) -> None:
    world.write("tests/test_cache.py", A_TEST)
    _issue(world, "stale-cache", "enforced")


@proof("registry/graduated", "an enforced issue whose test file is gone", expect="fail",
       contains="tests/test_cache.py, which does not exist")
def _(world: World) -> None:
    world.write("tests/test_start.py", A_TEST)
    _issue(world, "stale-cache", "enforced", "tests/test_cache.py::test_cache_is_fresh")


@proof("registry/graduated", "the file is still there, but the named test is gone", expect="fail",
       contains="holds no test named test_cache_is_fresh")
def _(world: World) -> None:
    world.write("tests/test_cache.py", "def test_cache_is_fresh_on_start():\n    assert True\n")
    _issue(world, "stale-cache", "enforced", "tests/test_cache.py::test_cache_is_fresh")


@proof("registry/graduated", "an issue file with no frontmatter block", expect="refuse",
       contains="has no frontmatter block")
def _(world: World) -> None:
    world.manifest(MANIFEST)
    world.write("docs/issues/stale-cache.md", "# Stale cache\n\nstatus: enforced\n")
