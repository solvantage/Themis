"""Gate: compliance — the content breaks no platform or legal rule.

Platform and legal rules change, and they differ from place to place. So the pack ships none. A
project keeps its forbidden terms, its product table and its rulebooks as files, and these rules
check that each item was held to them. What only eyes can judge is never guessed at: it needs an
attestation made as the judge the row names.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import unicodedata
from collections.abc import Iterator
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from themis.grants import new_attestation, to_toml
from themis.packs.marketing import items
from themis.rule import Context, Param, proof, rule

if TYPE_CHECKING:
    from themis.proofs import World

Rows = list[dict[str, Any]]
COLUMNS = ("id", "name", "price", "link", "benefit")
NUMBER = r"\d[\d,]*(?:\.\d+)?"
LINK = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+", re.IGNORECASE)
SIGN = "\u00a4"  # the general currency sign, which stands in for every currency sign
VISUAL = "visual"  # the row that an attestation of the pictures answers
PRICE_WORDS = Param("price_words", [str], ["price"], "larger",
                    "words that mark the number beside them as a price, as a currency sign does")
PATTERNS = Param("patterns", {"*": str}, {}, "larger",
                 "for each forbidden kind, a regular expression matched against the item's text and spoken lines")
VISUAL_JUDGE = Param("visual_judge", str, "owner", None,
                     "the judge who attests that the pictures show nothing forbidden")
FLAG = Param("generated_flag", str, "ai_generated", None,
             "the disclosure flag that must be true when a voice or footage was generated")
TODAY = Param("today", str, None, "higher",
              "the day ages are counted from, as an ISO date; unset means the real current date")


def _briefs(ctx: Context) -> Iterator[tuple[str, dict[str, Any]]]:
    """Each item whose brief can be read, as (folder, brief). A brief that cannot is refused."""
    for unit in sorted(items.items(ctx)):
        brief = items.load(ctx, unit, "brief")
        if brief is not None:
            yield unit, brief


def _texts(brief: dict[str, Any]) -> list[tuple[str, str]]:
    """All that an item shows as text or says, as (where it is, the text with its spaces collapsed)."""
    found = [("the title", brief["title"]), ("the caption", brief.get("caption", ""))]
    for part in brief.get("parts", []):
        found += [(f"the on-screen text of part {part['id']}", part.get("text", "")),
                  (f"the spoken line of part {part['id']}", part.get("line", ""))]
    found += [(f"claim {number}", claim["text"]) for number, claim in enumerate(brief.get("claims", []), start=1)]
    return [(where, " ".join(text.split())) for where, text in found if text.strip()]


def _line(ctx: Context, path: str, text: str) -> int | None:
    """The first line of a file that holds the text, so a finding can point at it."""
    lines = enumerate((ctx.read(path) or "").splitlines(), start=1)
    return next((number for number, written in lines if text in " ".join(written.split())), None)


def _pattern(ctx: Context, source: str, where: str, what: str) -> re.Pattern[str] | None:
    """A pattern that ignores case. One that cannot be compiled is refused."""
    try:
        return re.compile(source, re.IGNORECASE)
    except re.error as error:
        ctx.refuse(f"{what} is not a valid pattern ({error})", where=where, fix="correct the regular expression")
        return None


def _attested(ctx: Context) -> set[tuple[str, Any, Any]]:
    """Every attestation on record, as (what was judged, the row it answers, the judge it was made as)."""
    return {(str(record.get("subject")).strip().removeprefix("./").rstrip("/"), record.get("row"), record.get("judge"))
            for record in ctx.records("attestation")}


def _date(value: Any) -> dt.date | None:
    """An ISO date, or the day of an ISO time. None when the text is neither."""
    try:
        return dt.datetime.fromisoformat(str(value).strip()).date()
    except ValueError:
        return None


# -- the world every proof starts from ----------------------------------------------------------

SETUP = """
    [project]
    packs = ["marketing"]

    [marketing]
    work = "content/*"
    banned_terms = { file = "rules/banned.txt" }
    products = { file = "products.csv" }

    [marketing.rulebooks.selling]
    file = "rules/selling.toml"
    max_age_days = 60
    applies_to = { kind = "content", purpose = ["sales"] }

    [rules."compliance/forbidden-content"]
    patterns = { before-and-after = "before and after" }

    [rules."compliance/rulebook-dated"]
    today = "2026-03-01"
"""
BANNED = "# never promise these\nmiracle cure\nre:guarantee[ds]?\n"
PRODUCTS = "id,name,price,link,benefit\nbalm,Oat balm,19.00,https://shop.example/oat-balm,softens dry skin\n"
ENTRIES: Rows = [
    {"id": "no-cure", "check": "No line promises to cure a condition", "judge": "agent",
     "source": "https://rules.example/health-claims", "read_on": "2026-02-10"},
    {"id": "true-result", "check": "The footage shows no result the product cannot give", "judge": "owner",
     "source": "https://rules.example/advertising", "read_on": "2026-02-10"},
]
ROWS: Rows = [{"id": entry["id"], "check": entry["check"], "judge": entry["judge"], "done": False} for entry in ENTRIES]
EVIDENCE = {"id": "e1", "finding": "Oat extract softens dry skin", "tier": "official", "retrieved": "2026-02-20",
            "source": "https://health-agency.example/oat-extract", "quote": "Oat extract softened dry skin."}
BRIEF: dict[str, Any] = {
    "kind": "content", "title": "Three steps to soft hands", "purpose": "sales", "product": "balm",
    "caption": "Oat balm, price $19. In 3 steps: https://shop.example/oat-balm",
    "made_with": {"voice": "generated", "footage": "filmed"}, "disclosure": {"ai_generated": True},
    "parts": [{"id": "p1", "start_s": 0, "end_s": 4, "text": "Step 1 of 3", "line": "Wash and dry your hands."},
              {"id": "p2", "start_s": 4, "end_s": 9, "text": "Step 2 of 3", "line": "Rub in a little oat balm."}],
    "claims": [{"text": "Oat extract softens dry skin", "evidence": "e1"}],
}


def _toml(data: dict[str, Any]) -> str:
    """A TOML file from plain values, tables and lists of tables: all that an item's files hold."""
    lists = {key: rows for key, rows in data.items() if isinstance(rows, list) and rows and isinstance(rows[0], dict)}
    tables = {key: value for key, value in data.items() if isinstance(value, dict)}
    text = to_toml({key: value for key, value in data.items() if key not in lists and key not in tables})
    text += "".join(f"\n[{key}]\n{to_toml(value)}" for key, value in tables.items())
    return text + "".join(f"\n[[{key}]]\n{to_toml(row)}" for key, rows in lists.items() for row in rows)


def _item(world: World, *, rows: Rows = ROWS, entries: Rows = ENTRIES, **changes: Any) -> None:
    """One honest item that sells a product, beside the project's shared files. A proof changes one
    thing: a key of the brief (None takes it out), the checklist's rows or the rulebook's entries."""
    world.manifest(SETUP)
    world.write("rules/banned.txt", BANNED)
    world.write("products.csv", PRODUCTS)
    world.write("rules/selling.toml", _toml({"entries": entries}))
    brief = {key: value for key, value in {**BRIEF, **changes}.items() if value is not None}
    world.write("content/a/brief.toml", _toml(brief))
    world.write("content/a/evidence.toml", _toml({"rows": [EVIDENCE]}))
    world.write("content/a/checklist.toml", _toml({"rulebook": "selling", "rows": rows}))


def _said(line: str) -> Rows:
    """The honest parts, with another spoken line in the second one."""
    return [BRIEF["parts"][0], {**BRIEF["parts"][1], "line": line}]


# -- compliance/banned-terms --------------------------------------------------------------------


@rule(
    "compliance/banned-terms",
    "No forbidden term appears in any text or spoken line.",
    pack="marketing",
    learned="A spoken line promised a cure, and the list that forbade the word was only in the writer's instructions.",
)
def banned_terms(ctx: Context) -> None:
    listed = items.table(ctx).get("banned_terms", {}).get("file")
    if not listed:
        ctx.not_configured("set file under [marketing.banned_terms], the list of forbidden terms")
    terms = items.words(ctx, listed)
    if not terms:
        ctx.refuse("the list of forbidden terms " + ("does not exist" if terms is None else "holds no term"),
                   where=listed, fix="write one term a line; start a line with re: to give a regular expression")
        return
    patterns = {term: _pattern(ctx, term[3:].strip() if term.startswith("re:") else re.escape(" ".join(term.split())),
                               listed, f"the term {term!r}") for term in terms}
    for unit, brief in _briefs(ctx):
        ctx.inspect()
        path = f"{unit}/brief.toml"
        for where, text in _texts(brief):
            for term in (term for term, pattern in patterns.items() if pattern is not None and pattern.search(text)):
                ctx.breach(f"the forbidden term {term!r} appears in {where}", where=path, line=_line(ctx, path, text),
                           fix=f"reword it so that no term of {listed} appears")


@proof("compliance/banned-terms", "an item that uses no term of the list", expect="pass")
def _(world: World) -> None:
    _item(world)


@proof("compliance/banned-terms", "two words of a term, apart, are not the term", expect="pass")
def _(world: World) -> None:
    _item(world, parts=_said("No miracle, just a cure for dry hands."))


@proof("compliance/banned-terms", "a term in a spoken line, in other case and spacing", expect="fail",
       contains="the forbidden term 'miracle cure' appears in the spoken line of part p2")
def _(world: World) -> None:
    _item(world, parts=_said("Rub in this Miracle   Cure."))


@proof("compliance/banned-terms", "a pattern of the list matches the title", expect="fail",
       contains="the forbidden term 're:guarantee[ds]?' appears in the title")
def _(world: World) -> None:
    _item(world, title="Soft hands, guaranteed")


@proof("compliance/banned-terms", "the list is gone", expect="refuse", contains="forbidden terms does not exist")
def _(world: World) -> None:
    _item(world)
    world.remove("rules/banned.txt")


# -- compliance/source-facts --------------------------------------------------------------------


def _products(ctx: Context, path: str) -> dict[str, dict[str, str]] | None:
    """The product table by id. Refused, and None, when it is missing or lacks a column."""
    text = ctx.read(path)
    reader = csv.DictReader(io.StringIO(text or ""), skipinitialspace=True)
    missing = [name for name in COLUMNS if name not in (reader.fieldnames or [])]
    if text is None or missing:
        ctx.refuse("the product table does not exist" if text is None
                   else f"the product table lacks the column {', '.join(missing)}", where=path,
                   fix=f"keep it as a CSV file with the columns {', '.join(COLUMNS)}")
        return None
    return {row["id"].strip(): row for row in reader if (row["id"] or "").strip()}


def _prices(text: str, words: list[str]) -> list[Decimal]:
    """Each number written as a price: one with a currency sign or a price word right beside it."""
    signed = "".join(SIGN if unicodedata.category(char) == "Sc" else char for char in text)
    mark = "|".join([SIGN, *(rf"(?<![a-z]){re.escape(word)}(?![a-z])" for word in words)])
    found = re.finditer(rf"(?:{mark})\s*[:=]?\s*({NUMBER})|({NUMBER})\s*(?:{mark})", signed, re.IGNORECASE)
    return [Decimal((match[1] or match[2]).replace(",", "")) for match in found]


@rule(
    "compliance/source-facts",
    "Product wording, price and link come only from the product record.",
    pack="marketing",
    params=(PRICE_WORDS,),
    learned="A price typed from memory into a caption was not the price in the product's own record.",
)
def source_facts(ctx: Context) -> None:
    listed = items.table(ctx).get("products", {}).get("file")
    if not listed:
        ctx.not_configured("set file under [marketing.products], the product table")
    products = _products(ctx, listed)
    for unit, brief in _briefs(ctx) if products is not None else []:
        path, product = f"{unit}/brief.toml", brief.get("product")
        if not product:
            continue  # an item that sells nothing has no product fact to get wrong
        ctx.inspect()
        row, fix = products.get(product), f"take it from the row {product} of {listed}, as it is written there"
        if row is None:
            ctx.breach(f"the brief names the product {product}, and the product table holds no row with that id",
                       where=path, fix=f"add the product to {listed}, or name one that it holds")
            continue
        price, link = re.search(NUMBER, row["price"] or ""), (row["link"] or "").strip()
        for where, text in _texts(brief):
            for written in _prices(text, ctx.param("price_words")):
                if price is None or written != Decimal(price[0].replace(",", "")):
                    ctx.breach(f"{where} gives the price {written}, and the product record of {product} says "
                               f"{price[0] if price else 'nothing'}", where=path, line=_line(ctx, path, text), fix=fix)
        for found in LINK.findall(brief.get("caption", "")):
            if found.rstrip(".,;:!?/") != link.rstrip("/"):
                ctx.breach(f"the caption links to {found}, and the product record of {product} says "
                           f"{link or 'nothing'}", where=path, line=_line(ctx, path, found), fix=fix)


@proof("compliance/source-facts", "the record's price and link; a count of steps is no price", expect="pass")
def _(world: World) -> None:
    _item(world)


@proof("compliance/source-facts", "a product the table does not hold", expect="fail",
       contains="names the product serum, and the product table holds no row with that id")
def _(world: World) -> None:
    _item(world, product="serum")


@proof("compliance/source-facts", "a price that is not the record's", expect="fail",
       contains="the caption gives the price 15, and the product record of balm says 19.00")
def _(world: World) -> None:
    _item(world, caption="Oat balm, now only $15. https://shop.example/oat-balm")


@proof("compliance/source-facts", "a link that is not the record's", expect="fail",
       contains="the caption links to https://shop.example/oat-balm?from=clip, and the product record")
def _(world: World) -> None:
    _item(world, caption="Oat balm, price $19. https://shop.example/oat-balm?from=clip")


@proof("compliance/source-facts", "a product table with two columns gone", expect="refuse",
       contains="the product table lacks the column link, benefit")
def _(world: World) -> None:
    _item(world)
    world.write("products.csv", "id,name,price\nbalm,Oat balm,19.00\n")


# -- compliance/forbidden-content ---------------------------------------------------------------


@rule(
    "compliance/forbidden-content",
    "Nothing shown or said is of a kind the rulebook forbids, and what only eyes can judge is attested.",
    pack="marketing",
    params=(PATTERNS, VISUAL_JUDGE),
    requires=("patterns",),
    learned="A generated clip showed a result the advertising rules forbid.",
)
def forbidden_content(ctx: Context) -> None:
    patterns = {kind: _pattern(ctx, source, "themis.toml", f"the pattern for the forbidden kind {kind}")
                for kind, source in ctx.param("patterns").items()}
    judge, made = ctx.param("visual_judge"), _attested(ctx)
    for unit, files in sorted(items.items(ctx).items()):
        brief, notes, path = items.load(ctx, unit, "brief"), items.assets(ctx, unit, files), f"{unit}/brief.toml"
        if brief is None and not notes:
            continue  # nothing written and nothing made: there is nothing to judge yet
        ctx.inspect()
        for where, text in _texts(brief) if brief else []:
            for kind, pattern in patterns.items():
                found = pattern.search(text) if pattern is not None else None
                if found:
                    ctx.breach(f"{where} holds {found[0]!r}, which is of the forbidden kind {kind}", where=path,
                               line=_line(ctx, path, text), fix="take it out, or reword it so it is not of this kind")
        if notes and not {(unit, VISUAL, judge), (f"{unit}/plan.toml", VISUAL, judge)} & made:
            ctx.breach(f"pictures or sound were made for this item, and no {judge} has attested that they show "
                       "nothing forbidden", where=unit,
                       fix=f"the {judge} looks at what was made, then runs `themis attest` on {unit}/plan.toml "
                           f"for the row {VISUAL}")


def _made(world: World, judge: str) -> None:
    """The honest item with its plan and one clip made, and the pictures attested as that judge."""
    _item(world)
    world.write("content/a/plan.toml", _toml({"parts": BRIEF["parts"]}))
    world.write("content/a/assets/clip-1.toml", to_toml({"tool": "clip-maker", "take": 1}))
    new_attestation(world.root, "content/a/plan.toml", VISUAL, judge, judge)


@proof("compliance/forbidden-content", "text of no forbidden kind, and nothing made yet", expect="pass")
def _(world: World) -> None:
    _item(world, parts=_said("Use it before bed, and after washing up."))


@proof("compliance/forbidden-content", "a clip was made, and the owner attested the pictures", expect="pass")
def _(world: World) -> None:
    _made(world, "owner")


@proof("compliance/forbidden-content", "a spoken line of a forbidden kind", expect="fail",
       contains="the spoken line of part p2 holds 'before and after', which is of the forbidden kind before-and-after")
def _(world: World) -> None:
    _item(world, parts=_said("See my hands before and after one week."))


@proof("compliance/forbidden-content", "the agent that made the clip attested it itself", expect="fail",
       contains="no owner has attested that they show nothing forbidden")
def _(world: World) -> None:
    _made(world, "agent")


@proof("compliance/forbidden-content", "a pattern that cannot be compiled", expect="refuse",
       contains="the pattern for the forbidden kind before-and-after is not a valid pattern")
def _(world: World) -> None:
    _item(world)
    world.manifest(SETUP.replace('"before and after"', '"before (and after"'))


# -- compliance/disclosure ----------------------------------------------------------------------


@rule(
    "compliance/disclosure",
    "The disclosure flags follow the way the item was made, and the post shows them set.",
    pack="marketing",
    params=(FLAG,),
    learned="An item with a generated voice was published with the platform's disclosure setting left off.",
)
def disclosure(ctx: Context) -> None:
    flag = ctx.param("generated_flag")
    for unit, brief in _briefs(ctx):
        made, path = brief.get("made_with"), f"{unit}/brief.toml"
        if not made and brief["kind"] != "content":
            continue  # research and reusable designs are not published as they are
        ctx.inspect()
        if not made:
            ctx.refuse("the brief does not say how the item is made, so its disclosure cannot be checked", where=path,
                       fix="add [made_with] to the brief, with its voice and its footage")
            continue
        generated = [f"its {what} is {made[what]}" for what in ("voice", "footage")
                     if made.get(what) in ("generated", "mixed")]
        stated, post = brief.get("disclosure", {}).get(flag) is True, items.load(ctx, unit, "post")
        if generated and not stated:
            ctx.breach(f"{' and '.join(generated)}, and the brief does not set the disclosure flag {flag}", where=path,
                       fix=f"set {flag} = true under [disclosure] in the brief")
        shown, wanted = (post or {}).get("disclosure", {}).get(flag) is True, stated or bool(generated)
        if post is not None and shown != wanted:
            ctx.breach(f"the post record shows the disclosure flag {flag} {'set' if shown else 'not set'}, and the "
                       f"brief {'needs it set' if wanted else 'does not set it'}", where=f"{unit}/post.toml",
                       fix="change the setting where the item is published, then record it in post.toml as it now is")


def _post(world: World, **flags: bool) -> None:
    posted = {"platform": "short-video", "at": "2026-03-02T09:00:00+00:00", "disclosure": flags}
    world.write("content/a/post.toml", _toml(posted))


@proof("compliance/disclosure", "a generated voice, disclosed in the brief and in the post", expect="pass")
def _(world: World) -> None:
    _item(world)
    _post(world, ai_generated=True)


@proof("compliance/disclosure", "a human voice over filmed footage needs no flag", expect="pass")
def _(world: World) -> None:
    _item(world, made_with={"voice": "human", "footage": "filmed"}, disclosure=None)


@proof("compliance/disclosure", "generated work with the flag left off in the brief", expect="fail",
       contains="its voice is generated and its footage is mixed, and the brief does not set the disclosure flag")
def _(world: World) -> None:
    _item(world, made_with={"voice": "generated", "footage": "mixed"}, disclosure={"ai_generated": False})


@proof("compliance/disclosure", "the brief discloses, and the post does not", expect="fail",
       contains="the post record shows the disclosure flag ai_generated not set, and the brief needs it set")
def _(world: World) -> None:
    _item(world)
    _post(world, ai_generated=False)


@proof("compliance/disclosure", "a brief that does not say how the item is made", expect="refuse",
       contains="does not say how the item is made")
def _(world: World) -> None:
    _item(world, made_with=None)


# -- compliance/checklist -----------------------------------------------------------------------


@rule(
    "compliance/checklist",
    "Every item carries the full checklist for its kind and purpose, and a row is ticked only by its judge.",
    pack="marketing",
    learned="An item to sell with went out on the shorter checklist, with the owner's row ticked by the agent.",
)
def checklist(ctx: Context) -> None:
    declared, made = items.table(ctx).get("rulebooks", {}), _attested(ctx)
    books: dict[str, Any] = {}
    for unit, brief in _briefs(ctx):
        path, held = f"{unit}/checklist.toml", items.load(ctx, unit, "checklist")
        if held is None and (ctx.exists(path) or brief["kind"] != "content"):
            continue  # refused already, or a kind of work that needs no checklist
        ctx.inspect()
        name = held["rulebook"] if held else None
        if held is None or name not in declared:
            ctx.breach("this content item has no checklist" if held is None
                       else f"the checklist names the rulebook {name}, which the project has not declared",
                       where=unit if held is None else path,
                       fix="give the item the checklist of a rulebook declared under [marketing.rulebooks]")
            continue
        books[name] = books[name] if name in books else items.rulebook(ctx, name)
        if books[name] is None:
            continue  # the rulebook was refused
        applies, kind, purpose = books[name][0].get("applies_to", {}), brief["kind"], brief.get("purpose", "unset")
        if applies.get("kind", kind) != kind or purpose not in (applies.get("purpose") or [purpose]):
            ctx.breach(f"the rulebook {name} does not apply to an item of the kind {kind} with the purpose {purpose}",
                       where=path, fix="carry the checklist of the rulebook that applies to this kind and purpose")
        want = [(entry["id"], entry["check"].strip(), entry["judge"]) for entry in books[name][1].values()]
        have = [(row["id"], row["check"].strip(), row["judge"]) for row in held["rows"]]
        odd = next((row[0] for row in want + have if row not in want or row not in have), None)
        if have != want:
            ctx.breach(f"the checklist does not repeat the rulebook {name} row for row: "
                       + (f"the row {odd} is left out, added or changed" if odd else "the order differs"), where=path,
                       fix=f"copy the rows of {declared[name]['file']} as they are; only `done` is the item's own")
        for row in held["rows"]:
            # The attestation is bound to the file that was judged, never to the checklist: ticking a
            # row changes the checklist, and that must not make every earlier attestation stale.
            judged = f"{unit}/{JUDGED_FILE.get(row.get('judged_from', 'script'), 'brief.toml')}"
            if row.get("done") and (judged, row["id"], row["judge"]) not in made:
                ctx.breach(f"the row {row['id']} is ticked, and no attestation made as its judge, {row['judge']}, "
                           "exists for it", where=path, line=_line(ctx, path, f'"{row["id"]}"'),
                           fix=f"{row['judge']} judges the row and runs `themis attest {judged} {row['id']}`; until "
                               "then, set the row back to done = false")


#: What a row is judged from, and the file of the item that stands for it.
JUDGED_FILE = {"script": "brief.toml", "brief": "brief.toml", "plan": "plan.toml", "footage": "plan.toml",
               "render": "plan.toml", "post": "post.toml"}


def _ticked(world: World, judge: str) -> None:
    """The honest item with the owner's row ticked, and that row attested as the judge given."""
    _item(world, rows=[ROWS[0], {**ROWS[1], "done": True}])
    new_attestation(world.root, "content/a/brief.toml", "true-result", judge, judge)


@proof("compliance/checklist", "the rulebook's rows, one open and one ticked by its judge", expect="pass")
def _(world: World) -> None:
    _ticked(world, "owner")


@proof("compliance/checklist", "a content item with no checklist", expect="fail", contains="has no checklist")
def _(world: World) -> None:
    _item(world)
    world.remove("content/a/checklist.toml")


@proof("compliance/checklist", "a checklist of a rulebook nobody declared", expect="fail",
       contains="names the rulebook homemade, which the project has not declared")
def _(world: World) -> None:
    _item(world)
    world.write("content/a/checklist.toml", _toml({"rulebook": "homemade", "rows": ROWS}))


@proof("compliance/checklist", "a checklist for selling on an item with another purpose", expect="fail",
       contains="the rulebook selling does not apply to an item of the kind content with the purpose growth")
def _(world: World) -> None:
    _item(world, purpose="growth")


@proof("compliance/checklist", "a row of the rulebook is left out", expect="fail",
       contains="does not repeat the rulebook selling row for row: the row true-result is left out, added or changed")
def _(world: World) -> None:
    _item(world, rows=ROWS[:1])


@proof("compliance/checklist", "the owner's row ticked on the agent's word", expect="fail",
       contains="the row true-result is ticked, and no attestation made as its judge, owner, exists for it")
def _(world: World) -> None:
    _ticked(world, "agent")


@proof("compliance/checklist", "the rulebook's file is gone", expect="refuse", contains="a file that does not exist")
def _(world: World) -> None:
    _item(world)
    world.remove("rules/selling.toml")


# -- compliance/rulebook-dated ------------------------------------------------------------------


@rule(
    "compliance/rulebook-dated",
    "Each rule cites its page and the date it was read, and a rulebook past its window blocks publishing.",
    pack="marketing",
    params=(TODAY,),
    learned="A platform changed its rules, and the checklist went on checking items against the old page.",
)
def rulebook_dated(ctx: Context) -> None:
    declared = items.table(ctx).get("rulebooks", {})
    if not declared:
        ctx.not_configured("declare a rulebook under [marketing.rulebooks]")
    today = dt.date.today() if ctx.param("today") is None else _date(ctx.param("today"))
    if today is None:
        ctx.refuse("this rule's `today` is not an ISO date", where="themis.toml",
                   fix="write it as YYYY-MM-DD, or take it out to use the real current date")
        return
    for name in sorted(declared):
        found, path, window = items.rulebook(ctx, name), declared[name]["file"], declared[name].get("max_age_days")
        for entry in found[1].values() if found else []:
            ctx.inspect()
            what, read_on = f"the entry {entry['id']} of the rulebook {name}", _date(entry["read_on"])
            line, age = _line(ctx, path, f'"{entry["id"]}"'), (today - read_on).days if read_on else 0
            if not entry["source"].strip():
                ctx.breach(f"{what} cites no page", where=path, line=line, fix="name the page the rule was read from")
            if read_on is None:
                ctx.refuse(f"{what} was read on {entry['read_on']!r}, which is not an ISO date", where=path,
                           fix="write the date as YYYY-MM-DD")
            elif age < -1 or (window is not None and age > window):
                ctx.breach(f"{what} was read on {entry['read_on']}, a day that has not come yet" if age < 0
                           else f"{what} was read {age} days ago, and the window is {window} days", where=path,
                           line=line, fix="read the page again, correct the entry if it changed, and date it anew")


def _read_on(world: World, day: str, **changes: Any) -> None:
    """The honest item, with the first entry of its rulebook read on that day."""
    _item(world, entries=[{**ENTRIES[0], "read_on": day, **changes}, ENTRIES[1]])


@proof("compliance/rulebook-dated", "an entry read on the last day of its window", expect="pass")
def _(world: World) -> None:
    _read_on(world, "2025-12-31")


@proof("compliance/rulebook-dated", "an entry read one day past the window", expect="fail",
       contains="the entry no-cure of the rulebook selling was read 61 days ago, and the window is 60 days")
def _(world: World) -> None:
    _read_on(world, "2025-12-30")


@proof("compliance/rulebook-dated", "an entry that cites no page", expect="fail",
       contains="the entry no-cure of the rulebook selling cites no page")
def _(world: World) -> None:
    _read_on(world, "2026-02-10", source="")


@proof("compliance/rulebook-dated", "an entry whose date is not a date", expect="refuse",
       contains="was read on 'in spring', which is not an ISO date")
def _(world: World) -> None:
    _read_on(world, "in spring")
