"""Gate: attest — a check that needs eyes names who looked.

Some checks cannot be run by a program: does the picture look right, did a second reader agree,
did the owner sign the plan. Each such row of a checklist names its judge. An attestation records
who judged the row, and the hash of the file they judged.

A checklist is a TOML file of `[[rows]]`. Each row holds an `id`, the `judge` it needs, the
`subject` (the file it judges) and `done`, which is true once the row is ticked.
"""

from __future__ import annotations

import re
import tomllib
from typing import Any

from themis import paths, records
from themis.grants import file_hash, to_toml
from themis.rule import Context, Param, proof, rule
from themis.schema import Required

# The core's attestation, with two more fields a second reader needs: who made the subject, and
# what the reader was given. Registering the kind again replaces the earlier schema.
records.register("attestation", {
    "subject": Required(str), "row": Required(str), "judge": Required(str), "by": Required(str),
    "at": Required(str), "sha256": Required(str), "note": str, "author": str, "shown": [str],
}, "attestations/**/*.toml")

CHECKLISTS = Param("checklists", [str], None, "larger", "the checklist files, each a TOML file of [[rows]]")
JUDGES = Param("judges", {"*": [str]}, None, "smaller",
               "for each judge a row may name, who may attest as that judge")
INDEPENDENT = Param("independent", [str], None, "larger",
                    "the judges that must be independent of the author, such as reader")
WITHHELD = Param("withheld", [str], [], "larger", "what an independent reader must not be shown, such as code/**")
ROW_FIX = "write each row as a [[rows]] table that holds id, judge, subject and done"


def _path(value: Any) -> str:
    """A subject as a repository path, so `./a/b` and `a/b` name the same file."""
    return str(value).strip().removeprefix("./").strip("/")


def _same(one: Any, other: Any) -> bool:
    return str(one).strip().casefold() == str(other).strip().casefold()


def _rows(ctx: Context, name: str) -> list[tuple[int | None, dict[str, Any]]]:
    """A checklist's rows, each with its line. A checklist or a row that cannot be read is refused."""
    text = ctx.read(name)
    try:
        rows = tomllib.loads(text or "").get("rows")
    except tomllib.TOMLDecodeError:
        rows = None
    if text is None or not isinstance(rows, list) or not rows:
        ctx.refuse("this checklist cannot be read, or it holds no row", where=name, fix=ROW_FIX)
        return []
    found = []
    for number, row in enumerate(rows, start=1):
        named = isinstance(row, dict) and all(isinstance(row.get(key), str) and row[key].strip()
                                              for key in ("id", "judge", "subject"))
        if not named or not isinstance(row.get("done"), bool):
            ctx.refuse(f"row {number} of this checklist does not hold id, judge, subject and done", where=name,
                       fix=ROW_FIX)
            continue
        quoted = (f'"{row["id"]}"', f"'{row['id']}'")
        line = next((at for at, written in enumerate(text.splitlines(), start=1)
                     if re.match(r"\s*id\s*=", written) and any(mark in written for mark in quoted)), None)
        found.append((line, row))
    return found


def _attest(world, name: str = "a1", **fields: Any) -> None:
    data = {"subject": "work/a/plan.md", "row": "plan-signed", "judge": "owner", "by": "owner",
            "at": "2026-01-02T09:00:00+00:00", **fields}
    data.setdefault("sha256", file_hash(world.root / data["subject"]))
    world.write(f"attestations/{name}.toml", to_toml(data))


# -- attest/by-judge ----------------------------------------------------------------------------


@rule(
    "attest/by-judge",
    "A row is ticked only by the judge it names.",
    params=(CHECKLISTS, JUDGES),
    requires=("checklists", "judges"),
    learned="An agent ticked the row that was the owner's to judge.",
)
def by_judge(ctx: Context) -> None:
    judges = ctx.param("judges")
    made: dict[tuple[str, str], list[Any]] = {}
    for record in ctx.records("attestation"):
        made.setdefault((_path(record.get("subject")), record.get("row")), []).append(record)
    for name in sorted({name for pattern in ctx.param("checklists") for name in ctx.files(pattern)}):
        for line, row in _rows(ctx, name):
            ctx.inspect()
            row_id, judge, subject = row["id"], row["judge"], _path(row["subject"])
            if judge not in judges:
                ctx.refuse(f"row {row_id} names the judge {judge}, and the rule does not say who that is",
                           where=name, fix=f"add {judge} to `judges` for this rule, or correct the row")
                continue
            if not row["done"]:
                continue  # a row that is not ticked needs nobody's word yet
            found = made.get((subject, row_id), [])
            fix = (f"{' or '.join(judges[judge]) or 'the judge'} judges {subject} and runs `themis attest`; "
                   "nobody attests for another judge")
            if not found:
                ctx.breach(f"row {row_id} is ticked, and no attestation exists for it", where=name, line=line,
                           fix=f"{fix}. Until then, set the row back to done = false")
            for record in found:
                if record.get("judge") != judge:
                    ctx.breach(f"row {row_id} names the judge {judge}, and {record.path} was made as "
                               f"{record.get('judge')}", where=name, line=line, fix=f"{fix}. Remove {record.path}")
                elif record.get("by") not in judges[judge]:
                    ctx.breach(f"row {row_id} was attested by {record.get('by')}, who may not attest as {judge}",
                               where=name, line=line, fix=f"{fix}. Remove {record.path}")


BY_JUDGE = """
    [rules."attest/by-judge"]
    checklists = ["work/*/checklist.toml"]
    judges = { owner = ["owner"], agent = ["writer", "editor"] }
"""
ROW = """
    [[rows]]
    id = "{id}"
    judge = "{judge}"
    subject = "work/a/{subject}"
    done = {done}
"""


def _checklist(world, *rows: tuple[str, str, str, str]) -> None:
    """A world with one unit of work: a plan, a draft, and a checklist of (id, judge, subject, done)."""
    world.manifest(BY_JUDGE)
    world.write("work/a/plan.md", "the plan\n")
    world.write("work/a/draft.md", "the draft\n")
    world.write("work/a/checklist.toml", "".join(
        ROW.format(id=row_id, judge=judge, subject=subject, done=done) for row_id, judge, subject, done in rows
    ))


SIGNED = ("plan-signed", "owner", "plan.md", "true")
READ = ("draft-read", "agent", "draft.md", "true")


@proof("attest/by-judge", "each row ticked by the judge it names", expect="pass")
def _(world):
    _checklist(world, SIGNED, READ)
    _attest(world, "a1")
    _attest(world, "a2", subject="work/a/draft.md", row="draft-read", judge="agent", by="editor")


@proof("attest/by-judge", "a subject written as ./path names the same file", expect="pass")
def _(world):
    _checklist(world, SIGNED)
    _attest(world, subject="./work/a/plan.md")


@proof("attest/by-judge", "a row that is not ticked needs no attestation", expect="pass")
def _(world):
    _checklist(world, ("plan-signed", "owner", "plan.md", "false"))


@proof("attest/by-judge", "a ticked row with no attestation", expect="fail", contains="no attestation exists for it")
def _(world):
    _checklist(world, SIGNED)


@proof("attest/by-judge", "an agent ticks the row that is the owner's", expect="fail",
       contains="attested by writer, who may not attest as owner")
def _(world):
    _checklist(world, SIGNED)
    _attest(world, by="writer")


@proof("attest/by-judge", "an attestation made as another judge does not tick the owner's row", expect="fail",
       contains="was made as agent")
def _(world):
    _checklist(world, SIGNED)
    _attest(world, judge="agent", by="writer")


@proof("attest/by-judge", "an attestation of one row does not tick another row of the same file", expect="fail",
       contains="row budget-signed is ticked, and no attestation exists")
def _(world):
    _checklist(world, SIGNED, ("budget-signed", "owner", "plan.md", "true"))
    _attest(world)


@proof("attest/by-judge", "the owner's attestation beside an agent's own is still a breach", expect="fail",
       contains="attested by writer")
def _(world):
    _checklist(world, SIGNED)
    _attest(world, "a1")
    _attest(world, "a2", by="writer")


@proof("attest/by-judge", "a checklist that is not valid TOML", expect="refuse", contains="cannot be read")
def _(world):
    _checklist(world, SIGNED)
    world.write("work/a/checklist.toml", "[[rows]\nid = \n")


@proof("attest/by-judge", "a row whose judge the rule does not know", expect="refuse",
       contains="names the judge reader, and the rule does not say who that is")
def _(world):
    _checklist(world, ("second-read", "reader", "draft.md", "false"))


@proof("attest/by-judge", "a row with no judge at all", expect="refuse", contains="does not hold id, judge")
def _(world):
    _checklist(world, SIGNED)
    world.write("work/a/checklist.toml", '[[rows]]\nid = "plan-signed"\nsubject = "work/a/plan.md"\ndone = true\n')


# -- attest/bound -------------------------------------------------------------------------------


@rule(
    "attest/bound",
    "An attestation names the hash of what was judged, and a file that changed since then is refused.",
    learned="A file was approved, then edited, and the old approval was still read as covering it.",
)
def bound(ctx: Context) -> None:
    for record in ctx.records("attestation"):
        ctx.inspect()
        subject, recorded = _path(record.get("subject")), str(record.get("sha256")).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", recorded):
            ctx.breach("this attestation names no hash of what was judged", where=record.path,
                       fix="make an attestation with `themis attest`, which records the hash of the file")
            continue
        target = (ctx.root / subject).resolve()
        try:
            now = file_hash(target) if target.is_relative_to(ctx.root.resolve()) and target.is_file() else None
        except OSError:
            now = None
        if now is None:
            ctx.refuse(f"the file that was judged, {subject}, is missing or cannot be read", where=record.path,
                       fix=f"restore {subject}, or remove this record if the file is gone for good")
        elif now != recorded:
            ctx.refuse(f"{subject} changed after it was judged, so this attestation no longer covers it",
                       where=record.path, fix=f"the judge must judge the file again: look at {subject} as it is "
                                              "now, run `themis attest`, then remove this record")


PLAIN = """
    [project]
    name = "world"
"""


def _judged(world) -> None:
    world.manifest(PLAIN)
    world.write("work/a/plan.md", "the plan\n")
    world.write("work/a/draft.md", "the draft\n")
    _attest(world)


@proof("attest/bound", "a file left as it was judged", expect="pass")
def _(world):
    _judged(world)


@proof("attest/bound", "another file changed, the judged one did not", expect="pass")
def _(world):
    _judged(world)
    world.write("work/a/draft.md", "the draft, rewritten\n")


@proof("attest/bound", "a file judged again after it changed, in place of the stale record", expect="pass")
def _(world):
    _judged(world)
    world.write("work/a/plan.md", "the plan, with a tighter bar\n")
    _attest(world)


@proof("attest/bound", "a file edited after it was judged", expect="refuse", contains="changed after it was judged")
def _(world):
    _judged(world)
    world.write("work/a/plan.md", "the plan, with a looser bar\n")


@proof("attest/bound", "the file that was judged is gone", expect="refuse", contains="is missing or cannot be read")
def _(world):
    _judged(world)
    world.remove("work/a/plan.md")


@proof("attest/bound", "a subject outside the repository is not read", expect="refuse",
       contains="is missing or cannot be read")
def _(world):
    _judged(world)
    (world.root.parent / "outside.md").write_text("not this project's\n", encoding="utf-8")
    _attest(world, "a2", subject="../outside.md")


@proof("attest/bound", "an attestation that holds a word where the hash belongs", expect="fail",
       contains="names no hash of what was judged")
def _(world):
    _judged(world)
    _attest(world, sha256="looked fine to me")


# -- attest/independent -------------------------------------------------------------------------


@rule(
    "attest/independent",
    "A second reader is not the author and was not given the author's own work.",
    params=(INDEPENDENT, WITHHELD),
    requires=("independent",),
    learned="A second reading repeated the author's mistake, because the reader started from the author's code.",
)
def independent(ctx: Context) -> None:
    wanted, withheld = set(ctx.param("independent")), ctx.param("withheld") or []
    for record in ctx.records("attestation"):
        if record.get("judge") not in wanted:
            continue
        ctx.inspect()
        by, author, shown = record.get("by"), record.get("author"), record.get("shown")
        again = "someone who did not make the file judges it, and runs `themis attest` again"
        if not str(author or "").strip():
            ctx.breach("this attestation does not name the author, so the reader cannot be shown to be independent",
                       where=record.path, fix="attest again, and name who made the file")
        elif _same(by, author):
            ctx.breach(f"{by} judged their own work as a second reader", where=record.path, fix=again)
        elif withheld and shown is None:
            ctx.refuse("this attestation does not say what the reader was shown", where=record.path,
                       fix="attest again, and list what the reader was given")
        for item in shown or []:
            if paths.matches_any(_path(item), withheld):
                ctx.breach(f"the reader was shown {item}, which a second reader must not be given", where=record.path,
                           fix=f"{again}, without being given {item}")


INDEPENDENT_SETUP = """
    [rules."attest/independent"]
    independent = ["reader"]
    withheld = ["code/**", "work/*/notes.md"]
"""


def _second_read(world, **fields: Any) -> None:
    world.manifest(INDEPENDENT_SETUP)
    world.write("work/a/plan.md", "the plan\n")
    world.write("work/a/result.md", "the answer is 42\n")
    given = {"subject": "work/a/result.md", "row": "second-read", "judge": "reader", "by": "editor",
             "author": "writer", "shown": ["work/a/question.md", "data/input.csv"], **fields}
    _attest(world, "r1", **{key: value for key, value in given.items() if value is not None})


@proof("attest/independent", "a reader who is not the author, given only the question and the data", expect="pass")
def _(world):
    _second_read(world)


@proof("attest/independent", "a judge that need not be independent may sign their own plan", expect="pass")
def _(world):
    _second_read(world)
    _attest(world, "a1", author="owner")


@proof("attest/independent", "the author reads their own result", expect="fail", contains="judged their own work")
def _(world):
    _second_read(world, by="Writer")


@proof("attest/independent", "a second reading that names no author", expect="fail",
       contains="does not name the author")
def _(world):
    _second_read(world, author=None)


@proof("attest/independent", "the reader was given the author's code", expect="fail",
       contains="was shown code/model.py, which a second reader must not be given")
def _(world):
    _second_read(world, shown=["work/a/question.md", "code/model.py"])


@proof("attest/independent", "nothing says what the reader was shown", expect="refuse",
       contains="does not say what the reader was shown")
def _(world):
    _second_read(world, shown=None)


@proof("attest/independent", "no second reading has been made yet", expect="refuse", contains="nothing was inspected")
def _(world):
    world.manifest(INDEPENDENT_SETUP)
    world.write("work/a/plan.md", "the plan\n")
    _attest(world)
