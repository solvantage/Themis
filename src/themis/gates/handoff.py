"""Gate: handoff — the checkpoint is true and short.

A checkpoint is the file a working session leaves for the next one. Its place is `[homes]
checkpoint` in the manifest, else `CHECKPOINT.md`. A project with no checkpoint has nothing here to
check, and each of these rules says so: it is "not configured".
"""

from __future__ import annotations

import posixpath
from typing import Any

from themis import checkpoint, receipts
from themis.rule import Context, Param, proof, rule

WRITE_IT = "run `themis checkpoint`: it writes the headline's facts"


def _open(ctx: Context) -> tuple[str, checkpoint.Checkpoint | None]:
    """The checkpoint's path and what it holds: None, after a refusal, when it cannot be read."""
    path = checkpoint.home(ctx.manifest)
    if not ctx.exists(path):
        ctx.not_configured(f"write a checkpoint at {path}, or name its file as checkpoint under [homes]")
    text = ctx.read(path)
    if text is None:
        ctx.refuse("the checkpoint cannot be read as text", where=path, fix="save the file as plain UTF-8 text")
    return path, None if text is None else checkpoint.parse(text)


# -- the checkpoint of the worlds ---------------------------------------------------------------

STAMP = "**Last updated:** 2026-11-16 15:20 local (08:20 UTC). `main` at `{commit}` (#42)."
NO_COMMIT = "**Last updated:** 2026-11-16 15:20 local (08:20 UTC). All of it is merged."
CITED = "**Suite:** 1,204 pass / 3 skip<!--r:suite/t1-->, linter clean."
FIVE_LINES = checkpoint.NO_RECEIPT + "\n**Blocked:** nothing."  # with the other three, a headline of five lines
TRAP = "\n## Standing traps\n\n- A receipt for a changed tree proves nothing"
BODY = """
## Recently shipped

**2026-11-16 — the handoff gate (#40–#42):**

- The parser reads the headline and the dated entries.
- Each rule ships with its proofs.

## Standing traps

- A receipt for a changed tree proves nothing: see [the issue](docs/issues/stale-receipt.md).

## Do not re-propose

- Counting bullets by hand: closed in [its finding](docs/findings/count-by-hand.toml#decision).
"""


def _page(commit: str = "a1b2c3d", suite: str = checkpoint.NO_RECEIPT, body: str = BODY, stamp: str = STAMP) -> str:
    lines = [stamp.format(commit=commit), suite, "**Changed:** the gate reads the checkpoint.", "**Next:** wire it in."]
    return "\n".join([checkpoint.TITLE, "", *lines, body])


def _entries(*bullets: int) -> str:
    """A "Recently shipped" section with one dated entry for each count of bullets."""
    return "\n## Recently shipped\n" + "".join(
        f"\n**2026-11-{day:02d} — a theme:**\n\n" + "".join(f"- shipped item {item}\n" for item in range(count))
        for day, count in enumerate(bullets, start=10)
    )


def _padded(length: int, page: str) -> str:
    """The page, with plain lines added until it is exactly this many lines long."""
    page += "\n## Notes\n\n"
    return page + "A line of notes.\n" * (length - len(page.splitlines()))


def _work(world, name: str = "src/app.py") -> str:
    """One commit of work on the current branch. Returns the commit."""
    world.write(name, "print('hello')\n")
    return world.commit(f"work on {name}")


# -- checkpoint/shape ---------------------------------------------------------------------------


@rule(
    "checkpoint/shape",
    "The headline and each dated entry stay within their caps.",
    params=(
        Param("headline_lines", int, 5, "lower", "the most lines the headline may hold"),
        Param("entry_bullets", int, 10, "lower", "the most bullets one dated entry may hold"),
        Param("max_lines", int, 200, "lower", "the most lines the whole checkpoint may hold"),
    ),
    learned="A handoff file grew past a thousand lines, and the next session stopped reading it.",
)
def shape(ctx: Context) -> None:
    path, page = _open(ctx)
    if page is None:
        return
    ctx.inspect()
    headline, bullets, lines = (ctx.param(name) for name in ("headline_lines", "entry_bullets", "max_lines"))
    if page.lines > lines:
        ctx.breach(f"the checkpoint is {page.lines} lines long, and the cap is {lines}", where=path,
                   fix="move the oldest dated entries to an archive file")
    if page.headline_line is None:
        ctx.breach("the checkpoint has no headline: no line begins with **Last updated:**", where=path, fix=WRITE_IT)
    elif len(page.headline) > headline:
        ctx.breach(f"the headline is {len(page.headline)} lines long, and the cap is {headline}", where=path,
                   line=page.headline_line, fix="shorten the headline: move the rest under a heading below it")
    for entry in page.entries:
        ctx.inspect()
        if entry.bullets > bullets:
            ctx.breach(f"the entry dated {entry.date} holds {entry.bullets} bullets, and the cap is {bullets}",
                       where=path, line=entry.line, fix="merge bullets, or move detail to the records they point at")


@proof("checkpoint/shape", "a four-line headline and a short entry", expect="pass")
def _(world):
    world.write("CHECKPOINT.md", _page())


@proof("checkpoint/shape", "a headline, an entry and a file exactly at their caps", expect="pass")
def _(world):
    world.write("CHECKPOINT.md", _padded(200, _page(suite=FIVE_LINES, body=_entries(10))))


@proof("checkpoint/shape", "two entries are counted apart, and a list with no date has no cap", expect="pass")
def _(world):
    world.write("CHECKPOINT.md", _page(body=_entries(7, 7) + "\n## Standing traps\n\n" + "- a trap\n" * 12))


@proof("checkpoint/shape", "a checkpoint with no headline", expect="fail", contains="has no headline")
def _(world):
    world.write("CHECKPOINT.md", checkpoint.TITLE + "\n" + BODY)


@proof("checkpoint/shape", "a headline of six lines", expect="fail", contains="the headline is 6 lines long")
def _(world):
    world.write("CHECKPOINT.md", _page(suite=FIVE_LINES + "\n**Also:** one more thing."))


@proof("checkpoint/shape", "an entry of eleven bullets", expect="fail", contains="holds 11 bullets")
def _(world):
    world.write("CHECKPOINT.md", _page(body=_entries(2, 11)))


@proof("checkpoint/shape", "a file one line over its cap", expect="fail", contains="is 201 lines long")
def _(world):
    world.write("CHECKPOINT.md", _padded(201, _page()))


@proof("checkpoint/shape", "a project's tighter cap binds", expect="fail", contains="holds 4 bullets")
def _(world):
    world.manifest('[rules."checkpoint/shape"]\nentry_bullets = 3\n')
    world.write("CHECKPOINT.md", _page(body=_entries(4)))


@proof("checkpoint/shape", "the file named under [homes] is the one read", expect="fail", contains="has no headline")
def _(world):
    world.manifest('[homes]\ncheckpoint = "docs/HANDOFF.md"\n')
    world.write("CHECKPOINT.md", _page())
    world.write("docs/HANDOFF.md", "# Handoff\n\nNothing was written here.\n")


@proof("checkpoint/shape", "a checkpoint that is not text", expect="refuse", contains="cannot be read as text")
def _(world):
    (world.root / "CHECKPOINT.md").write_bytes(b"\xff\xfe\x00\x01")


# -- checkpoint/git-true ------------------------------------------------------------------------


@rule(
    "checkpoint/git-true",
    "The commit named in the headline exists and is on the main line.",
    learned="A handoff named a commit that was never merged, and the next session built on work that was not there.",
)
def git_true(ctx: Context) -> None:
    path, page = _open(ctx)
    if page is None:
        return
    main = ctx.git.main_ref(ctx.manifest.project.get("main"))
    if main is None:
        ctx.refuse("there is no main line, so the commit in the headline cannot be checked", where=path,
                   fix="commit to main, or set project.main")
        return
    ctx.inspect()
    if page.commit is None:
        ctx.breach("the headline names no commit", where=path, line=page.headline_line, fix=WRITE_IT)
    elif ctx.git.resolve(page.commit) is None:
        ctx.breach(f"the headline names the commit {page.commit}, and git does not know it", where=path,
                   line=page.headline_line, fix=WRITE_IT)
    elif not ctx.git.is_ancestor(page.commit, main):
        ctx.breach(f"the commit {page.commit} is not on the main line ({main})", where=path, line=page.headline_line,
                   fix="merge the work first, then run `themis checkpoint`")


@proof("checkpoint/git-true", "the headline names the commit main is at", expect="pass")
def _(world):
    world.write("CHECKPOINT.md", _page(_work(world)[:8]))


@proof("checkpoint/git-true", "a merged commit, named in full, with the checkpoint committed after it", expect="pass")
def _(world):
    _work(world)
    world.branch("topic")
    commit = _work(world, "src/topic.py")
    world.checkout("main")
    world.merge("topic")
    world.write("CHECKPOINT.md", _page(commit))
    world.commit("the checkpoint")


@proof("checkpoint/git-true", "a main line with another name, set under [project]", expect="pass")
def _(world):
    world.manifest('[project]\nmain = "trunk"\n')
    commit = _work(world)
    world.git("branch", "-m", "trunk")
    world.write("CHECKPOINT.md", _page(commit[:8], stamp=STAMP.replace("`main`", "`trunk`")))


@proof("checkpoint/git-true", "a headline that names no commit", expect="fail", contains="names no commit")
def _(world):
    _work(world)
    world.write("CHECKPOINT.md", _page(stamp=NO_COMMIT))


@proof("checkpoint/git-true", "a commit git does not know", expect="fail", contains="git does not know it")
def _(world):
    _work(world)
    world.write("CHECKPOINT.md", _page("0123abcd"))


@proof("checkpoint/git-true", "a commit on a branch never merged", expect="fail", contains="is not on the main line")
def _(world):
    _work(world)
    world.branch("topic")
    world.write("CHECKPOINT.md", _page(_work(world, "src/topic.py")[:8]))


@proof("checkpoint/git-true", "with no main line the rule cannot decide", expect="refuse", contains="no main line")
def _(world):
    world.write("CHECKPOINT.md", _page())


# -- checkpoint/suite-receipt -------------------------------------------------------------------


@rule(
    "checkpoint/suite-receipt",
    "The suite count cites a receipt for that commit, or is labelled unverified.",
    learned="A handoff quoted a test count from memory, and the suite had not run on that commit.",
)
def suite_receipt(ctx: Context) -> None:
    path, page = _open(ctx)
    if page is None:
        return
    ctx.inspect()
    if page.unverified:
        return  # the line says itself that nothing backs it: an honest line claims nothing
    if page.receipt is None:
        said = "the suite line cites no receipt and is not labelled unverified"
        ctx.breach(said if page.suite else "the headline has no **Suite:** line", where=path,
                   line=page.suite_line or page.headline_line,
                   fix="cite the receipt with `themis checkpoint`, or write the word unverified on the line")
        return
    receipt, again = checkpoint.receipt_named(ctx.root, page.receipt), "run the suite again: a tool writes the receipt"
    if receipt is None:
        file = f"{receipts.COMMITTED}/suite/{page.receipt}.json"
        if ctx.exists(file):
            ctx.refuse(f"the suite receipt {page.receipt} cannot be read", where=file, fix=again)
        else:
            ctx.breach(f"no suite receipt is named {page.receipt}", where=path, line=page.suite_line,
                       fix="run the suite, run `themis checkpoint`, and commit the receipt under receipts/suite/")
        return
    counts = checkpoint.counts(receipt)
    if counts is None:
        ctx.refuse(f"the suite receipt {page.receipt} does not hold its counts", where=receipt["_path"], fix=again)
        return
    wrote = "no count" if page.passed is None else f"{page.passed:,} pass and {page.skipped or 0:,} skip"
    holds = f"{counts['passed']:,} pass and {counts['skipped']:,} skip"
    if wrote != holds:
        ctx.breach(f"the suite line gives {wrote}; the receipt holds {holds}", where=path, line=page.suite_line,
                   fix=WRITE_IT)
    if counts["failed"] or counts["errors"]:
        ctx.breach(f"the suite did not pass: the receipt holds failed = {counts['failed']} and errors = "
                   f"{counts['errors']}", where=receipt["_path"], fix="mend the suite, run it again, then cite it")
    tree = ctx.git.run("rev-parse", "--verify", "--quiet", page.commit + "^{tree}") if page.commit else None
    if tree is None:
        ctx.refuse("the headline names no commit that git can read, so the receipt cannot be tied to one", where=path,
                   fix=WRITE_IT)
    elif receipt.get("tree") != tree.strip():
        ctx.breach("the receipt was taken on another tree than the commit named in the headline", where=path,
                   line=page.suite_line, fix="run the suite on that commit, then run `themis checkpoint`")


def _suite(world, line: str = CITED, *, of: str | None = None, stamp: str = STAMP, **receipt: Any) -> None:
    """Work on main, a committed receipt for that commit's tree, and a checkpoint that names both."""
    commit = _work(world)
    tree = world.git("rev-parse", f"{of or commit}^{{tree}}").strip()
    counts = {"passed": 1204, "skipped": 3, "failed": 0, "errors": 0}
    receipts.write(world.root, "suite", "t1", {"tree": tree, "at": "2026-11-16T08:19:00+00:00", **counts, **receipt},
                   committed=True)
    world.write("CHECKPOINT.md", _page(commit[:8], line, stamp=stamp))


@proof("checkpoint/suite-receipt", "the count cites a receipt for the commit named", expect="pass")
def _(world):
    _suite(world)


@proof("checkpoint/suite-receipt", "the checkpoint and its receipt are committed after that commit", expect="pass")
def _(world):
    _suite(world)
    world.commit("the checkpoint")


@proof("checkpoint/suite-receipt", "a count written with no separator, in other words", expect="pass")
def _(world):
    _suite(world, "**Suite:** 1204 passed, 3 skipped<!--r:suite/t1-->.")


@proof("checkpoint/suite-receipt", "a count from memory, labelled unverified, claims nothing", expect="pass")
def _(world):
    world.write("CHECKPOINT.md", _page(_work(world)[:8], "**Suite:** about 1,200 pass, unverified."))


@proof("checkpoint/suite-receipt", "a count with no receipt and no label", expect="fail", contains="cites no receipt")
def _(world):
    _suite(world, "**Suite:** 1,204 pass / 3 skip, linter clean.")


@proof("checkpoint/suite-receipt", "a headline with no suite line", expect="fail", contains="has no **Suite:** line")
def _(world):
    _suite(world, "**Blocked:** nothing.")


@proof("checkpoint/suite-receipt", "a tag that names no receipt", expect="fail", contains="no suite receipt is named")
def _(world):
    _suite(world, CITED.replace("suite/t1", "suite/t2"))


@proof("checkpoint/suite-receipt", "a pass count that is not the receipt's", expect="fail", contains="gives 1,304 pass")
def _(world):
    _suite(world, CITED.replace("1,204", "1,304"))


@proof("checkpoint/suite-receipt", "skipped tests left out of the line", expect="fail", contains="pass and 0 skip;")
def _(world):
    _suite(world, "**Suite:** 1,204 pass<!--r:suite/t1-->.")


@proof("checkpoint/suite-receipt", "a receipt that shows a failure", expect="fail", contains="failed = 2")
def _(world):
    _suite(world, failed=2)


@proof("checkpoint/suite-receipt", "a receipt taken on an older commit", expect="fail", contains="on another tree")
def _(world):
    _suite(world, of=_work(world, "src/old.py"))


@proof("checkpoint/suite-receipt", "a receipt with no counts", expect="refuse", contains="does not hold its counts")
def _(world):
    _suite(world, passed=None)


@proof("checkpoint/suite-receipt", "a receipt file that cannot be read", expect="refuse", contains="cannot be read")
def _(world):
    _suite(world)
    world.write("receipts/suite/t1.json", "this is not a receipt\n")


@proof("checkpoint/suite-receipt", "a headline that names no commit", expect="refuse", contains="cannot be tied to one")
def _(world):
    _suite(world, stamp=NO_COMMIT)


# -- checkpoint/pointers ------------------------------------------------------------------------


@rule(
    "checkpoint/pointers",
    "Each standing trap and each closed decision points at its home record.",
    params=(
        Param("sections", [str], ["Standing traps", "Do not re-propose"], "larger",
              "the headings whose bullets must each link to a record"),
    ),
    learned="A closed question was proposed again, because the handoff did not say where its decision lived.",
)
def pointers(ctx: Context) -> None:
    path, page = _open(ctx)
    if page is None:
        return
    ctx.inspect()
    for name in ctx.param("sections"):
        for bullet in page.section(name):
            ctx.inspect()
            targets = [checkpoint.target_path(link, posixpath.dirname(path)) for link in checkpoint.links(bullet.text)]
            homes = [target for target in targets if target and target != path]
            if not homes:
                ctx.breach(f"a bullet under {name} holds no link to its home record", where=path, line=bullet.line,
                           fix="link the bullet to the file that records it, as [the record](docs/issues/name.md)")
            elif not any(ctx.exists(target) for target in homes):
                ctx.breach(f"a bullet under {name} links to {homes[0]}, and no such file exists", where=path,
                           line=bullet.line, fix="correct the link, or write the record it should point at")


def _records(world) -> None:
    world.write("docs/issues/stale-receipt.md", "---\ntitle: A receipt for a changed tree\nstatus: open\n---\n")
    world.write("docs/findings/count-by-hand.toml", 'title = "Count bullets by hand"\nstatus = "wontfix"\n')


@proof("checkpoint/pointers", "each trap and each closed decision links to a file that exists", expect="pass")
def _(world):
    _records(world)
    world.write("CHECKPOINT.md", _page())


@proof("checkpoint/pointers", "a checkpoint with no such section", expect="pass")
def _(world):
    world.write("CHECKPOINT.md", _page(body=_entries(2)))


@proof("checkpoint/pointers", "a link on a bullet's second line, read from the checkpoint's own folder", expect="pass")
def _(world):
    world.manifest('[homes]\ncheckpoint = "docs/HANDOFF.md"\n')
    _records(world)
    world.write("docs/HANDOFF.md", _page(body=TRAP + ".\n  See [the issue](issues/stale-receipt.md).\n"))


@proof("checkpoint/pointers", "a bullet with no link, under a deeper heading", expect="fail", contains="holds no link")
def _(world):
    _records(world)
    world.write("CHECKPOINT.md", _page(body=BODY + "\n### Older\n\n- Never trust a count typed by hand.\n"))


@proof("checkpoint/pointers", "a link to a record that does not exist", expect="fail", contains="no such file exists")
def _(world):
    world.write("CHECKPOINT.md", _page())


@proof("checkpoint/pointers", "a web address, or a link back to the checkpoint, is not a home record", expect="fail",
       contains="holds no link")
def _(world):
    links = "[a thread](https://example.invalid/thread/1) and [above](CHECKPOINT.md#recently-shipped)"
    world.write("CHECKPOINT.md", _page(body=f"{TRAP}: see {links}.\n"))


@proof("checkpoint/pointers", "a section the project added is held to the rule", expect="fail", contains="Open risks")
def _(world):
    world.manifest('[rules."checkpoint/pointers"]\nsections = ["Open risks"]\n')
    world.write("CHECKPOINT.md", _page(body="\n## Open risks\n\n- The cache may hold an old answer.\n"))
