"""Gate: evidence — content says only what a source says.

A factual line in a brief is a claim, and a claim cites an evidence row by its id. A row holds the
finding, its tier, its source, the day it was retrieved and the passage it rests on. These rules
check what the item recorded. They never open a page: whether a source still opens is read from a
link-check receipt, when the project keeps one.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from themis import receipts
from themis.grants import new_attestation, to_toml
from themis.packs.marketing import items
from themis.rule import Context, Param, proof, rule

if TYPE_CHECKING:
    from themis.proofs import World

Rows = list[dict[str, Any]]
TODAY = Param("today", str, None, "higher",
              "the day ages are counted from, as an ISO date; unset means the real current date")
JUDGE = Param("judge", str, "second-reader", None,
              "the judge who attests that each line says no more than its quoted passage")


def _date(value: Any) -> dt.date | None:
    """An ISO date, or the day of an ISO time. None when the text is neither."""
    try:
        return dt.datetime.fromisoformat(str(value).strip()).date()
    except ValueError:
        return None


def _each(ctx: Context) -> Iterator[tuple[str, Rows | None, str, Rows | None]]:
    """Each item as (brief path, claims, evidence path, rows). A list is empty when its file is
    absent, and None when its file was refused: the rule then says nothing more about that item."""
    for unit in sorted(items.items(ctx)):
        found: list[Any] = []
        for name, key in (("brief", "claims"), ("evidence", "rows")):
            data, path = items.load(ctx, unit, name), f"{unit}/{name}.toml"
            found += [path, None if data is None and ctx.exists(path) else (data or {}).get(key, [])]
        yield found[0], found[1], found[2], found[3]


def _line(ctx: Context, path: str, table: str, index: int) -> int | None:
    """The line where a file's n-th `[[table]]` starts, so a finding can point at it."""
    starts = [number for number, written in enumerate((ctx.read(path) or "").splitlines(), start=1)
              if re.fullmatch(rf"\s*\[\[\s*{table}\s*\]\]\s*(#.*)?", written)]
    return starts[index] if index < len(starts) else None


def _aged(ctx: Context, what: str, stated: str, today: dt.date, window: int, where: str, line: int | None,
          fix: str) -> None:
    """Hold one date to its window: refuse what is no date, breach what is too old or has not come."""
    day = _date(stated)
    if day is None:
        ctx.refuse(f"{what} {stated!r}, which is not an ISO date", where=where, fix="write the date as YYYY-MM-DD")
    elif (today - day).days > window:
        ctx.breach(f"{what} {(today - day).days} days ago, and the window is {window} days", where=where, line=line,
                   fix=fix)
    elif (today - day).days < -1:  # one day of grace: the writer's clock may be a time zone ahead
        ctx.breach(f"{what} {stated}, a day that has not come yet", where=where, line=line,
                   fix="record the day as it really was")


# -- the world every proof starts from ----------------------------------------------------------

SETUP = """
    [project]
    packs = ["marketing"]

    [marketing]
    work = "content/*"

    [marketing.evidence]
    max_age_days = 30
    page_max_age_days = { trend = 90 }
    tiers = ["official", "third-party", "vendor"]
    require = { health = ["official"] }

    [rules."evidence/fresh"]
    today = "2026-03-01"
"""
CLAIMS: Rows = [
    {"text": "Daily sunscreen slows visible skin ageing", "evidence": "e1", "kind": "health"},
    {"text": "Searches for mineral sunscreen doubled in a year", "evidence": "e2"},
]
ROWS: Rows = [
    {"id": "e1", "finding": "Daily sunscreen use slows visible skin ageing", "tier": "official",
     "source": "https://health-agency.example/sun-care", "retrieved": "2026-02-20",
     "quote": "Daily use of sunscreen slowed visible skin ageing over four years."},
    {"id": "e2", "finding": "Interest in mineral sunscreen is rising", "tier": "third-party",
     "source": "https://trend-watch.example/mineral-sunscreen", "retrieved": "2026-02-20", "page_date": "2026-01-15",
     "topic": "trend", "quote": "Searches for mineral sunscreen doubled over the past year."},
]


def _toml(key: str, rows: Rows, **plain: Any) -> str:
    """A TOML file of plain values and one list of tables, which is all these files hold."""
    return to_toml(plain) + "".join(f"\n[[{key}]]\n{to_toml(row)}" for row in rows)


def _with(rows: Rows, index: int, **changes: Any) -> Rows:
    """A copy of the rows with one of them changed. A value of None takes the key out."""
    changed = {key: value for key, value in {**rows[index], **changes}.items() if value is not None}
    return [*rows[:index], changed, *rows[index + 1:]]


def _item(world: World, *, claims: Rows = CLAIMS, rows: Rows | None = ROWS) -> None:
    """One honest item: a brief whose claims cite the rows of its evidence file. A proof changes
    one thing. With `rows` as None the item has no evidence file."""
    world.manifest(SETUP)
    world.write("content/a/brief.toml", _toml("claims", claims, kind="content", title="Sunscreen every morning"))
    if rows is not None:
        world.write("content/a/evidence.toml", _toml("rows", rows))


# -- evidence/sourced ---------------------------------------------------------------------------


@rule(
    "evidence/sourced",
    "Every factual line cites an evidence row, and every evidence row has a source.",
    pack="marketing",
    learned="A line was stated as fact, and the row behind it named no page anyone could open.",
)
def sourced(ctx: Context) -> None:
    for brief, claims, evidence, rows in _each(ctx):
        if claims is None or rows is None or not (ctx.exists(brief) or rows):
            continue  # refused already, or a folder that states no fact and holds no row
        ctx.inspect()
        if claims and not ctx.exists(evidence):
            ctx.breach("the brief states factual lines, and the item has no evidence.toml", where=brief,
                       fix=f"add {evidence} with a row for each line, or take the lines out of the brief")
            continue
        known = {row["id"] for row in rows}
        for index, claim in enumerate(claims):
            if claim["evidence"] not in known:
                ctx.breach(f"the line {claim['text']!r} cites the evidence row {claim['evidence']}, which the item "
                           "does not hold", where=brief, line=_line(ctx, brief, "claims", index),
                           fix=f"add that row to {evidence} with its source, or take the line out")
        for index, row in enumerate(rows):
            if not row["source"].strip():
                ctx.breach(f"the evidence row {row['id']} names no source", where=evidence,
                           line=_line(ctx, evidence, "rows", index),
                           fix="name the page the finding came from, or remove the row and each line resting on it")


@proof("evidence/sourced", "each line cites a row, and each row names its source", expect="pass")
def _(world: World) -> None:
    _item(world)


@proof("evidence/sourced", "an item with no factual line needs no evidence", expect="pass")
def _(world: World) -> None:
    _item(world, claims=[], rows=None)


@proof("evidence/sourced", "a line that cites a missing row", expect="fail", contains="cites the evidence row e9")
def _(world: World) -> None:
    _item(world, claims=_with(CLAIMS, 1, evidence="e9"))


@proof("evidence/sourced", "a row whose source is left blank", expect="fail", contains="row e2 names no source")
def _(world: World) -> None:
    _item(world, rows=_with(ROWS, 1, source=" "))


@proof("evidence/sourced", "factual lines and no evidence file", expect="fail", contains="has no evidence.toml")
def _(world: World) -> None:
    _item(world, rows=None)


@proof("evidence/sourced", "an evidence file that cannot be read", expect="refuse", contains="is not valid TOML")
def _(world: World) -> None:
    _item(world)
    world.write("content/a/evidence.toml", "[[rows]\nid = \n")


# -- evidence/fresh -----------------------------------------------------------------------------


@rule(
    "evidence/fresh",
    "Evidence is inside its window, by the date it was retrieved and by the page's own date.",
    pack="marketing",
    params=(TODAY,),
    learned="A line rested on a page read months earlier, and the page had since changed.",
)
def fresh(ctx: Context) -> None:
    settings = items.table(ctx).get("evidence", {})
    window, pages = settings.get("max_age_days"), settings.get("page_max_age_days", {})
    if window is None:
        ctx.not_configured("set max_age_days under [marketing.evidence]")
    today = dt.date.today() if ctx.param("today") is None else _date(ctx.param("today"))
    if today is None:
        ctx.refuse("this rule's `today` is not an ISO date", where="themis.toml",
                   fix="write it as YYYY-MM-DD, or take it out to use the real current date")
        return
    for _, _, path, rows in _each(ctx):
        for index, row in enumerate(rows or []):
            ctx.inspect()
            name, line, topic = f"the evidence row {row['id']}", _line(ctx, path, "rows", index), row.get("topic")
            _aged(ctx, f"{name} was retrieved", row["retrieved"], today, window, path, line,
                  "open the source again, record what it says now and the new date, and check each line resting on it")
            if topic in pages and not row.get("page_date", "").strip():
                ctx.breach(f"{name} is about {topic}, a topic with a window for the page's own date, and it holds no "
                           "page date", where=path, line=line, fix="record the date the page carries as page_date")
            elif topic in pages:
                _aged(ctx, f"{name} rests on a page dated", row["page_date"], today, pages[topic], path, line,
                      "find a newer page for this finding, or take out each line resting on it")


@proof("evidence/fresh", "a row retrieved on the last day of its window", expect="pass")
def _(world: World) -> None:
    _item(world, rows=_with(ROWS, 0, retrieved="2026-01-30"))


@proof("evidence/fresh", "a row retrieved a day past the window", expect="fail", contains="was retrieved 31 days ago")
def _(world: World) -> None:
    _item(world, rows=_with(ROWS, 0, retrieved="2026-01-29"))


@proof("evidence/fresh", "an old page on a topic that has no page window", expect="pass")
def _(world: World) -> None:
    _item(world, rows=_with(ROWS, 0, page_date="2019-06-01", topic="care"))


@proof("evidence/fresh", "a trend page older than its topic's window", expect="fail", contains="dated 120 days ago")
def _(world: World) -> None:
    _item(world, rows=_with(ROWS, 1, page_date="2025-11-01"))


@proof("evidence/fresh", "a trend row that holds no page date", expect="fail", contains="it holds no page date")
def _(world: World) -> None:
    _item(world, rows=_with(ROWS, 1, page_date=None))


@proof("evidence/fresh", "a row dated years ahead would never grow old", expect="fail", contains="has not come yet")
def _(world: World) -> None:
    _item(world, rows=_with(ROWS, 0, retrieved="2030-01-01"))


@proof("evidence/fresh", "a retrieval date that is no date", expect="refuse", contains="is not an ISO date")
def _(world: World) -> None:
    _item(world, rows=_with(ROWS, 0, retrieved="last week"))


# -- evidence/tier ------------------------------------------------------------------------------


@rule(
    "evidence/tier",
    "A claim of a guarded kind rests on a source of a required tier.",
    pack="marketing",
    learned="A health claim rested on nothing but the page of the seller who gained from it.",
)
def tier(ctx: Context) -> None:
    settings = items.table(ctx).get("evidence", {})
    tiers, require = settings.get("tiers"), settings.get("require")
    if not require:
        ctx.not_configured('set require under [marketing.evidence], such as require = { health = ["official"] }')
    for brief, claims, evidence, rows in _each(ctx):
        if claims is None or rows is None:
            continue  # refused already
        for index, row in enumerate(rows if tiers else []):
            ctx.inspect()
            if row["tier"] not in tiers:
                ctx.breach(f"the evidence row {row['id']} has the tier {row['tier']!r}, which is not a tier the "
                           "project recognises", where=evidence, line=_line(ctx, evidence, "rows", index),
                           fix=f"give the row one of the project's tiers: {', '.join(tiers)}")
        held = {row["id"]: row for row in rows}
        for index, claim in enumerate(claims):
            ctx.inspect()
            kind, row = claim.get("kind"), held.get(claim["evidence"])
            if kind not in require or (row is not None and row["tier"] in require[kind]):
                continue  # not a guarded kind, or resting on a tier it may rest on
            rests = (f"cites the evidence row {claim['evidence']}, which the item does not hold" if row is None
                     else f"rests on the evidence row {row['id']}, of the tier {row['tier']}")
            ctx.breach(f"the {kind} line {claim['text']!r} {rests}; a {kind} line needs {' or '.join(require[kind])}",
                       where=brief, line=_line(ctx, brief, "claims", index),
                       fix=f"cite a source of the tier {' or '.join(require[kind])}, or take the line out")


@proof("evidence/tier", "a health line that rests on an official source", expect="pass")
def _(world: World) -> None:
    _item(world)


@proof("evidence/tier", "a line of no guarded kind may rest on a seller's page", expect="pass")
def _(world: World) -> None:
    _item(world, rows=_with(ROWS, 1, tier="vendor"))


@proof("evidence/tier", "a health line that rests on a seller's page", expect="fail", contains="of the tier vendor")
def _(world: World) -> None:
    _item(world, rows=_with(ROWS, 0, tier="vendor"))


@proof("evidence/tier", "a row with a tier the project does not know", expect="fail", contains="has the tier 'forum'")
def _(world: World) -> None:
    _item(world, rows=_with(ROWS, 1, tier="forum"))


@proof("evidence/tier", "a health line that cites a missing row", expect="fail", contains="e9, which the item does")
def _(world: World) -> None:
    _item(world, claims=_with(CLAIMS, 0, evidence="e9"))


@proof("evidence/tier", "an evidence file that cannot be read is no breach", expect="refuse", contains="not valid TOML")
def _(world: World) -> None:
    _item(world)
    world.write("content/a/evidence.toml", "[[rows]\nid = \n")


# -- evidence/quoted ----------------------------------------------------------------------------


@rule(
    "evidence/quoted",
    "Each evidence row holds the passage it rests on, and a second reader has agreed the line says no more.",
    pack="marketing",
    params=(JUDGE,),
    learned="A line promised more than the page it cited, and nobody had put the two side by side.",
)
def quoted(ctx: Context) -> None:
    claimed = [found for found in _each(ctx) if found[1] and found[3] is not None]
    judge = ctx.param("judge")
    read = {str(record.get("subject")).strip().removeprefix("./")
            for record in (ctx.records("attestation") if claimed else []) if record.get("judge") == judge}
    for brief, claims, evidence, rows in claimed:
        ctx.inspect()
        held = {row["id"]: (index, row) for index, row in enumerate(rows)}
        for cited in dict.fromkeys(claim["evidence"] for claim in claims):
            if cited not in held:
                ctx.breach(f"the brief cites the evidence row {cited}, which the item does not hold, so there is no "
                           "passage to hold the line to", where=brief,
                           fix=f"add that row to {evidence} with its quoted passage, or take the line out")
            elif not held[cited][1].get("quote", "").strip():
                ctx.breach(f"the evidence row {cited} holds no quoted passage, so the line that cites it cannot be "
                           "held to its source", where=evidence, line=_line(ctx, evidence, "rows", held[cited][0]),
                           fix="copy the passage from the source into the row's quote, word for word")
        if ctx.exists(evidence) and evidence not in read:
            ctx.breach(f"no {judge} has attested that the item's lines say no more than the quoted passages",
                       where=evidence,
                       fix=f"a {judge} compares each line with its quote, then runs `themis attest` on {evidence}")


def _read(world: World, judge: str = "second-reader") -> None:
    new_attestation(world.root, "content/a/evidence.toml", "lines-match-quotes", judge, "editor")


@proof("evidence/quoted", "each cited row holds its passage, and a second reader attested", expect="pass")
def _(world: World) -> None:
    _item(world)
    _read(world)


@proof("evidence/quoted", "a row that no line cites needs no passage", expect="pass")
def _(world: World) -> None:
    _item(world, rows=[*ROWS, {**ROWS[0], "id": "e3", "quote": ""}])
    _read(world)


@proof("evidence/quoted", "a cited row with no quoted passage", expect="fail", contains="e1 holds no quoted passage")
def _(world: World) -> None:
    _item(world, rows=_with(ROWS, 0, quote=None))
    _read(world)


@proof("evidence/quoted", "nobody attested the lines", expect="fail", contains="no second-reader has attested")
def _(world: World) -> None:
    _item(world)


@proof("evidence/quoted", "the writer's own attestation does not count", expect="fail", contains="no second-reader")
def _(world: World) -> None:
    _item(world)
    _read(world, judge="writer")


@proof("evidence/quoted", "an item with no factual line", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _item(world, claims=[])


# -- evidence/reachable -------------------------------------------------------------------------


def _real(ctx: Context, source: str) -> bool:
    """True for a full web address, and for the path of a file kept in the repository."""
    path = source.removeprefix("./")
    return bool(re.fullmatch(r"(?i)https?://[^\s/?#]+\S*", source)) or (
        bool(path) and not path.startswith("/") and ".." not in path.split("/") and ctx.exists(path))


def _link_check(ctx: Context) -> dict[str, Any] | None:
    """The newest link-check receipt, or None when the project keeps none. One that cannot be read
    is a refusal, never a skip."""
    kept = {path.relative_to(ctx.root).as_posix() for base in (receipts.LOCAL, receipts.COMMITTED)
            for path in (ctx.root / base / "links").glob("*.json")}
    good = [found for found in receipts.read_all(ctx.root, "links") if isinstance(found.get("checked"), dict)]
    for name in sorted(kept - {found["_path"] for found in good}):
        ctx.refuse("this link-check receipt cannot be read, or holds no `checked` table", where=name,
                   fix="restore the receipt from git; a receipt is written by a tool, never by hand")
    return max(good, key=lambda found: str(found.get("at", "")), default=None)


@rule(
    "evidence/reachable",
    "A source is a real address, and one that no longer opens is recorded as such.",
    pack="marketing",
    learned="A line went out resting on a page that had been taken down weeks before.",
)
def reachable(ctx: Context) -> None:
    newest = _link_check(ctx)
    for _, _, path, rows in _each(ctx):
        for index, row in enumerate(rows or []):
            ctx.inspect()
            source, line = row["source"].strip(), _line(ctx, path, "rows", index)
            if not _real(ctx, source):
                ctx.breach(f"the source of the evidence row {row['id']} is {source!r}, which is neither a web address "
                           "nor a file in this repository", where=path, line=line,
                           fix="write the page's full address, starting with https://, or the path of a file kept here")
            elif newest is not None and newest["checked"].get(source) is False:
                ctx.breach(f"the source of the evidence row {row['id']} no longer opens, by the link check "
                           f"{newest['_path']}", where=path, line=line,
                           fix="find where the page moved and read it again, or take out each line resting on it")


def _checked(world: World, day: str, **opens: bool) -> None:
    """A link-check receipt taken on that day, for the honest rows' sources, named by row id."""
    checked = {row["source"]: opens[row["id"]] for row in ROWS}
    receipts.write(world.root, "links", day, {"at": f"{day}T06:00:00+00:00", "checked": checked}, committed=True)


@proof("evidence/reachable", "each source is a full web address, and no link check is kept", expect="pass")
def _(world: World) -> None:
    _item(world)


@proof("evidence/reachable", "a source that is a file kept in the repository", expect="pass")
def _(world: World) -> None:
    _item(world, rows=_with(ROWS, 0, source="sources/sun-care-leaflet.md"))
    world.write("sources/sun-care-leaflet.md", "Daily use of sunscreen slowed visible skin ageing over four years.\n")


@proof("evidence/reachable", "a source that is a description", expect="fail", contains="is 'the leaflet in the box'")
def _(world: World) -> None:
    _item(world, rows=_with(ROWS, 0, source="the leaflet in the box"))


@proof("evidence/reachable", "the newest link check found a dead source", expect="fail", contains="e2 no longer opens")
def _(world: World) -> None:
    _item(world)
    _checked(world, "2026-02-01", e1=True, e2=True)
    _checked(world, "2026-02-21", e1=True, e2=False)


@proof("evidence/reachable", "a source that failed an older link check and opens in the newest", expect="pass")
def _(world: World) -> None:
    _item(world)
    _checked(world, "2026-02-01", e1=True, e2=False)
    _checked(world, "2026-02-21", e1=True, e2=True)


@proof("evidence/reachable", "a link-check receipt with no results", expect="refuse", contains="no `checked` table")
def _(world: World) -> None:
    _item(world)
    receipts.write(world.root, "links", "2026-02-21", {"at": "2026-02-21T06:00:00+00:00"}, committed=True)
