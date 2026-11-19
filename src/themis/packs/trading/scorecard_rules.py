"""Gate: scorecard — a result a newcomer can read.

Four rules about what a study publishes beside its numbers: the scorecard and its report, five
answers about how far the result can be believed, one short page that explains it, and pages that
render as they were written.

A study is "published" here once it has anything under `results/`. `scorecard/believable` and
`scorecard/explainer` take the kinds of study they bind (`kinds`, every kind when unset). All four
honour `since`: a study whose seal reached the main line before that date is left alone.
`scorecard/rendering` reads a study's pages with the core's Markdown reader, the one
`docs/no-bare-dollar-pairs` uses, so a sign in code, HTML or a link target is never counted.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from themis import markdown, work
from themis.packs.trading import scorecard, units
from themis.rule import Context, Param, proof, rule

if TYPE_CHECKING:
    from themis.proofs import World

MANIFEST = """
    [project]
    packs = ["trading"]

    [trading]
    work = "work/*"
"""
STUDY = "work/a"
SCORED = ("strategy", "signal")  # the kinds of study that ship a scorecard
EXPLAINER = units.EXPLAINER
QUESTION = "How believable is this?"
ANSWERS = 5
REASON_WORDS = 3

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_ITEM = re.compile(r"^\s{0,3}\d+[.)]\s+\S")
_FENCE = ("```", "~~~")
_BOX = re.compile(r"""class\s*=\s*(["'])(?:[^"']*\s)?how-to-read(?:\s[^"']*)?\1""", re.IGNORECASE)
_CONTROL = re.compile(r"<(?:input|button|select)\b", re.IGNORECASE)
_NO_EXPLAINER = re.compile(r"^[ \t]*explainer:[ \t]*none\b(.*)$", re.IGNORECASE | re.MULTILINE)
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]*")


KINDS = Param("kinds", [str], list(units.KINDS), "larger",
              "the kinds of study the rule binds, such as strategy; every kind when unset")


def _published(ctx: Context) -> list[tuple[str, list[str]]]:
    """The studies that have results, in order."""
    return [(unit, files) for unit, files in sorted(units.studies(ctx).items()) if units.has_results(unit, files)]


def _sealed_before(ctx: Context, unit: str, files: list[str]) -> bool:
    """True when the study's seal reached the main line before the rule's start date (its `since`)."""
    return ctx.predates(work.inside(unit, files, units.SEAL))


def _bound(ctx: Context) -> list[tuple[str, list[str]]]:
    """The published studies this rule binds: of a kind it names, and not sealed before its date.
    A study whose kind cannot be read is bound, so a missing kind never excuses it."""
    wanted = ctx.param("kinds")
    unknown = sorted(set(wanted) - set(units.KINDS))
    if unknown:
        ctx.refuse(f"kinds names {', '.join(unknown)}, which is not a kind of study", where="themis.toml",
                   fix=f"name kinds from: {', '.join(units.KINDS)}")
        return []
    every = set(units.KINDS) <= set(wanted)
    return [(unit, files) for unit, files in _published(ctx)
            if (every or units.kind(ctx, unit, files) in (None, *wanted))
            and not _sealed_before(ctx, unit, files)]


def _study(world: World, kind: str = "strategy", seal: str = "", manifest: str = "") -> None:
    """A world with one study, sealed as that kind, and one result file."""
    world.manifest(MANIFEST + manifest)
    world.write(f"{STUDY}/PRE-REG.md", f"---\nkind: {kind}\n{seal}---\nThe plan.\n")
    world.write(f"{STUDY}/results/metrics.json", "{}\n")


# -- scorecard/complete -------------------------------------------------------------------------


@rule(
    "scorecard/complete",
    "A study that books trades or predicts ships its scorecard, with no line left unexplained.",
    pack="trading",
    learned="A scorecard left its checks of real skill blank, and the result was read as if they had passed.",
)
def complete(ctx: Context) -> None:
    for unit, files in _published(ctx):
        if _sealed_before(ctx, unit, files):
            continue
        sealed = units.seal(ctx, unit, files)
        if sealed is None or sealed[1].get("kind") not in SCORED:
            continue
        ctx.inspect()
        card, page = f"{unit}/{units.SCORECARD}", f"{unit}/{units.REPORT}"
        if not ctx.exists(page):
            ctx.breach("this study has results and no report", where=unit,
                       fix=f"build the report from the trades and the scorecard, at {units.REPORT}")
        if not ctx.exists(card):
            ctx.breach("this study has results and no scorecard", where=unit,
                       fix=f"compute the scorecard from the trade table and write it to {units.SCORECARD}")
            continue
        try:
            lines = scorecard.parse_csv(ctx.read(card) or "")
        except ValueError as error:
            ctx.refuse(f"the scorecard cannot be read: {error}", where=card,
                       fix="write the scorecard with its own writer: the columns are " + ", ".join(scorecard.COLUMNS))
            continue
        if not lines:
            ctx.breach("the scorecard holds no line", where=card, fix="compute the scorecard from the trade table")
        blank = [line.id for line in lines if line.group == 5 and line.not_run]
        reason = sealed[1].get("not_run_reason")
        if blank and not (isinstance(reason, str) and reason.strip()):
            ctx.breach(f"the scorecard leaves a check of real skill as {scorecard.NOT_RUN} ({', '.join(blank)}), "
                       "and the seal gives no not_run_reason", where=card,
                       fix="run the check, or say why it is not run in the seal's frontmatter: not_run_reason: ...")


TRADES = [
    {"entry_time": f"2026-0{month}-05T10:00:00", "exit_time": f"2026-0{month}-06T10:00:00", "side": side,
     "net": net, "costs": 1.0, "mfe": abs(net) + 2.0}
    for month, side, net in ((1, "long", 30.0), (2, "short", -12.0), (3, "long", 18.0), (4, "short", 9.0))
]
ALL_RUN = {"baselines": {"always_long": 1010.0, "always_short": 990.0}, "oos_start": "2026-03-01",
           "trial_sharpes": [0.2, 0.1, 0.4], "sensitivity": [1020.0, 1005.0]}


def _card(drop: tuple[str, ...] = (), trades: list[dict] | None = None) -> str:
    """A scorecard as its CSV text. `drop` names the inputs that are left out, so their lines are
    NOT RUN."""
    inputs = {name: value for name, value in ALL_RUN.items() if name not in drop}
    return scorecard.to_csv(scorecard.compute(TRADES if trades is None else trades, start_capital=1000.0, **inputs))


def _shipped(world: World, card: str | None = None, kind: str = "strategy", seal: str = "") -> None:
    _study(world, kind, seal)
    world.write(f"{STUDY}/{units.SCORECARD}", _card() if card is None else card)
    world.write(f"{STUDY}/{units.REPORT}", "<h1>The report</h1>\n")


@proof("scorecard/complete", "a scorecard with every line run, and its report", expect="pass")
def _(world: World) -> None:
    _shipped(world)


@proof("scorecard/complete", "a check that was not run, with the reason in the seal", expect="pass")
def _(world: World) -> None:
    _shipped(world, _card(drop=("baselines",)), seal="not_run_reason: the baselines need prices not held yet\n")


@proof("scorecard/complete", "a line outside the skill group may be left not run", expect="pass")
def _(world: World) -> None:
    _shipped(world, _card(trades=[{**trade, "mfe": None} for trade in TRADES]))


@proof("scorecard/complete", "results with no scorecard", expect="fail", contains="results and no scorecard")
def _(world: World) -> None:
    _shipped(world)
    world.remove(f"{STUDY}/{units.SCORECARD}")


@proof("scorecard/complete", "a signal study with no report", expect="fail", contains="results and no report")
def _(world: World) -> None:
    _shipped(world, kind="signal")
    world.remove(f"{STUDY}/{units.REPORT}")


@proof("scorecard/complete", "the baselines were not run, and the seal says nothing", expect="fail",
       contains="NOT RUN (always_long, always_short), and the seal gives no not_run_reason")
def _(world: World) -> None:
    _shipped(world, _card(drop=("baselines",)))


@proof("scorecard/complete", "an empty reason is no reason", expect="fail", contains="the seal gives no not_run_reason")
def _(world: World) -> None:
    _shipped(world, _card(drop=("sensitivity",)), seal='not_run_reason: ""\n')


@proof("scorecard/complete", "a scorecard with a header and no line", expect="fail", contains="holds no line")
def _(world: World) -> None:
    _shipped(world, ",".join(scorecard.COLUMNS) + "\n")


@proof("scorecard/complete", "a scorecard without its columns", expect="refuse", contains="cannot be read")
def _(world: World) -> None:
    _shipped(world, "line,value\nalways_long,1010\n")


@proof("scorecard/complete", "a data study owes no scorecard", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _study(world, kind="data")


def _shipped_early(world: World, since: str, card: str | None = None) -> None:
    """A study sealed and merged to main, then shipped with this scorecard, under the rule's start date."""
    world.manifest(MANIFEST + f'\n[rules."scorecard/complete"]\nsince = "{since}"\n')
    world.write(f"{STUDY}/PRE-REG.md", "---\nkind: strategy\n---\nThe plan.\n")
    world.commit("the seal, before the rule binds")
    world.write(f"{STUDY}/results/metrics.json", "{}\n")
    world.write(f"{STUDY}/{units.SCORECARD}", _card() if card is None else card)
    world.write("work/b/PRE-REG.md", "---\nkind: strategy\n---\nThe plan.\n")  # a study sealed later, shipped whole
    world.write("work/b/results/metrics.json", "{}\n")
    world.write(f"work/b/{units.SCORECARD}", _card())
    world.write(f"work/b/{units.REPORT}", "<h1>The report</h1>\n")


@proof("scorecard/complete", "a study sealed before the rule binds is left alone", expect="pass")
def _(world: World) -> None:
    _shipped_early(world, "2027-01-01")


@proof("scorecard/complete", "a study sealed on the day the rule binds is held to it", expect="fail",
       contains="this study has results and no report")
def _(world: World) -> None:
    _shipped_early(world, "2026-01-01")


# -- scorecard/believable -----------------------------------------------------------------------


def _answers(text: str) -> int | None:
    """How many numbered answers follow the heading, before the next heading of the same or a
    higher level. None when the heading is missing."""
    level, count, fenced = None, 0, False
    for line in text.splitlines():
        if line.lstrip().startswith(_FENCE):
            fenced = not fenced
        if fenced or line.lstrip().startswith(_FENCE):
            continue
        heading = _HEADING.match(line)
        if heading and level is not None and len(heading[1]) <= level:
            break
        if heading and level is None and QUESTION.lower() in heading[2].lower():
            level = len(heading[1])
        elif level is not None and _ITEM.match(line):
            count += 1
    return None if level is None else count


@rule(
    "scorecard/believable",
    "A published result answers five questions about how far it can be believed.",
    pack="trading",
    params=(KINDS,),
    learned="A finding was quoted for weeks before anyone asked how many independent cases it rested on.",
)
def believable(ctx: Context) -> None:
    fix = (f'add a heading "{QUESTION}" and answer under it, in a numbered list: what the independent unit is; '
           "how many were checked; what could be missed; whether the sources are independent; what is unexplained")
    for unit, _ in _bound(ctx):
        ctx.inspect()
        path = f"{unit}/{units.README}"
        text = ctx.read(path)
        if text is None:
            ctx.breach("this study has results and no README.md", where=unit, fix=fix)
            continue
        found = _answers(text)
        if found is None:
            ctx.breach(f'the README has no heading that holds "{QUESTION}"', where=path, fix=fix)
        elif found < ANSWERS:
            ctx.breach(f'the README answers {found} of the five questions under "{QUESTION}"', where=path, fix=fix)


FIVE = """\
1. The independent unit is one trading day: 212 of them.
2. All 212 days were checked, and none was dropped.
3. A slow change in costs would be missed.
4. Both price sources come from one feed, so they are not independent.
5. The weak result on Mondays is not explained.
"""


def _readme(world: World, text: str) -> None:
    _study(world)
    world.write(f"{STUDY}/README.md", text)


@proof("scorecard/believable", "five numbered answers under the heading", expect="pass")
def _(world: World) -> None:
    _readme(world, f"# The result\n\nIt held.\n\n## {QUESTION}\n\n{FIVE}\n## Next\n\nNothing.\n")


@proof("scorecard/believable", "the answers continue under a deeper heading", expect="pass")
def _(world: World) -> None:
    first, rest = FIVE.split("3. ", 1)
    _readme(world, f"### {QUESTION}\n\n{first}\n#### The weak points\n\n3. {rest}")


@proof("scorecard/believable", "results with no README", expect="fail", contains="results and no README.md")
def _(world: World) -> None:
    _study(world)


@proof("scorecard/believable", "a README without the heading", expect="fail", contains="has no heading")
def _(world: World) -> None:
    _readme(world, f"# The result\n\nIt held.\n\n{FIVE}")


@proof("scorecard/believable", "the question in a sentence is not a heading", expect="fail", contains="has no heading")
def _(world: World) -> None:
    _readme(world, f"# The result\n\n{QUESTION} Very.\n\n{FIVE}")


@proof("scorecard/believable", "four answers", expect="fail", contains="answers 4 of the five questions")
def _(world: World) -> None:
    _readme(world, f"## {QUESTION}\n\n{FIVE.rsplit('5. ', 1)[0]}")


@proof("scorecard/believable", "the fifth answer is under the next heading", expect="fail", contains="answers 4 of the")
def _(world: World) -> None:
    first, last = FIVE.rsplit("5. ", 1)
    _readme(world, f"## {QUESTION}\n\n{first}\n## What is left\n\n5. {last}")


@proof("scorecard/believable", "five bullets are not numbered answers", expect="fail", contains="answers 0 of the five")
def _(world: World) -> None:
    _readme(world, f"## {QUESTION}\n\n" + "".join(f"- {line.split('. ', 1)[1]}\n" for line in FIVE.splitlines()))


@proof("scorecard/believable", "five numbers with nothing after them", expect="fail", contains="answers 0 of the five")
def _(world: World) -> None:
    _readme(world, f"## {QUESTION}\n\n1.\n2.\n3.\n4.\n5.\n")


@proof("scorecard/believable", "no result yet, so no answers owed", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _study(world)
    world.remove(f"{STUDY}/results/metrics.json")


def _scoped(world: World, rule_id: str, setting: str, *studies: tuple[str, str, str | None]) -> None:
    """Studies with results, each (folder, kind, README or None), under one setting of the rule."""
    world.manifest(MANIFEST + f'\n[rules."{rule_id}"]\n{setting}\n')
    for unit, kind, readme in studies:
        world.write(f"{unit}/PRE-REG.md", f"---\nkind: {kind}\n---\nThe plan.\n")
        world.write(f"{unit}/results/metrics.json", "{}\n")
        if readme is not None:
            world.write(f"{unit}/README.md", readme)


def _sealed_early(world: World, rule_id: str, since: str, readme: str) -> None:
    """Study a, merged to main with no README; study b, not merged yet, with this README."""
    _scoped(world, rule_id, f'since = "{since}"', (STUDY, "strategy", None))
    world.commit("study a, before the rule binds")
    _scoped(world, rule_id, f'since = "{since}"', ("work/b", "signal", readme))


ANSWERED = f"## {QUESTION}\n\n{FIVE}"


@proof("scorecard/believable", "scoped to strategy and signal, a tune study owes no answers", expect="pass")
def _(world: World) -> None:
    _scoped(world, "scorecard/believable", 'kinds = ["strategy", "signal"]',
            (STUDY, "strategy", ANSWERED), ("work/b", "tune", None))


@proof("scorecard/believable", "scoped to strategy and signal, a signal study still owes them", expect="fail",
       contains="this study has results and no README.md")
def _(world: World) -> None:
    _scoped(world, "scorecard/believable", 'kinds = ["strategy", "signal"]',
            (STUDY, "tune", None), ("work/b", "signal", None))


@proof("scorecard/believable", "a kind that does not exist", expect="refuse", contains="kinds names stratgy, which")
def _(world: World) -> None:
    _scoped(world, "scorecard/believable", 'kinds = ["stratgy"]', (STUDY, "strategy", ANSWERED))


@proof("scorecard/believable", "a study sealed before the rule binds is left alone", expect="pass")
def _(world: World) -> None:
    _sealed_early(world, "scorecard/believable", "2027-01-01", ANSWERED)


@proof("scorecard/believable", "a study sealed on the day the rule binds is held to it", expect="fail",
       contains="this study has results and no README.md")
def _(world: World) -> None:
    _sealed_early(world, "scorecard/believable", "2026-01-01", ANSWERED)


# -- scorecard/explainer ------------------------------------------------------------------------


@rule(
    "scorecard/explainer",
    "A published result has one short page for a newcomer, or says why it has none.",
    pack="trading",
    params=(
        Param("max_bytes", int, 200000, "lower", "the most bytes the explainer page may hold"),
        Param("max_controls", int, 2, "lower", "the most controls (inputs, buttons, selects) the explainer may hold"),
        KINDS,
    ),
    learned="A result was explained by a page of sliders that no newcomer could follow.",
)
def explainer(ctx: Context) -> None:
    for unit, _ in _bound(ctx):
        ctx.inspect()
        path = f"{unit}/{EXPLAINER}"
        if not ctx.exists(path):
            stated = _NO_EXPLAINER.search(ctx.read(f"{unit}/{units.README}") or "")
            if stated is None:
                ctx.breach("this study has results, no explainer page, and no line in its README that starts "
                           "`explainer: none`", where=unit,
                           fix=f"write one short page at {EXPLAINER}, or add `explainer: none` and the reason")
            elif len(_WORD.findall(stated[1])) < REASON_WORDS:
                ctx.breach("the README says `explainer: none` and gives no reason of at least three words",
                           where=f"{unit}/{units.README}", fix="say after it, on the same line, why no page helps")
            continue
        size, text = (ctx.root / path).stat().st_size, ctx.read(path)
        if size > ctx.param("max_bytes"):
            ctx.breach(f"the explainer page is {size:,} bytes, over the cap of {ctx.param('max_bytes'):,}",
                       where=path, fix="one idea and one picture: cut the page down")
        if text is None:
            ctx.refuse("the explainer page cannot be read as text", where=path)
            continue
        boxes, controls = len(_BOX.findall(text)), len(_CONTROL.findall(text))
        if boxes > 1:
            ctx.breach(f"the explainer page holds {boxes} how-to-read boxes: it explains one idea, in one box",
                       where=path, fix="keep the one idea a newcomer needs, and move the rest to the report")
        if controls > ctx.param("max_controls"):
            ctx.breach(f"the explainer page holds {controls} controls, and the cap is {ctx.param('max_controls')}",
                       where=path, fix="keep the controls that change the one idea, and drop the others")


PAGE = """\
<h1>Why the stop matters</h1>
<svg viewBox="0 0 10 10"></svg>
<div class="how-to-read">Move the slider to change the stop. Watch how many trades end early.</div>
<input type="range" min="1" max="3"> <button>Reset</button>
"""


def _explained(world: World, page: str = PAGE, manifest: str = "") -> None:
    _study(world, manifest=manifest)
    world.write(f"{STUDY}/{EXPLAINER}", page)


@proof("scorecard/explainer", "one box and two controls", expect="pass")
def _(world: World) -> None:
    _explained(world)


@proof("scorecard/explainer", "a box of another class is not counted twice", expect="pass")
def _(world: World) -> None:
    _explained(world, PAGE + '<div class="note how-to-read-more">More on stops, for later.</div>\n')


@proof("scorecard/explainer", "no page, and the README says why", expect="pass")
def _(world: World) -> None:
    _study(world)
    world.write(f"{STUDY}/README.md", "# The result\n\nexplainer: none - the result is one table of numbers\n")


@proof("scorecard/explainer", "no page and no reason", expect="fail", contains="no explainer page")
def _(world: World) -> None:
    _study(world)
    world.write(f"{STUDY}/README.md", "# The result\n\nThe explainer comes later.\n")


@proof("scorecard/explainer", "none, with no reason after it", expect="fail", contains="gives no reason of at least")
def _(world: World) -> None:
    _study(world)
    world.write(f"{STUDY}/README.md", "explainer: none\n\nThe result is one table of numbers.\n")


@proof("scorecard/explainer", "one word is not a reason", expect="fail", contains="gives no reason of at least three")
def _(world: World) -> None:
    _study(world)
    world.write(f"{STUDY}/README.md", "explainer: none - later\n")


@proof("scorecard/explainer", "three controls", expect="fail", contains="holds 3 controls, and the cap is 2")
def _(world: World) -> None:
    _explained(world, PAGE + "<select><option>one</option></select>\n")


@proof("scorecard/explainer", "two how-to-read boxes", expect="fail", contains="holds 2 how-to-read boxes")
def _(world: World) -> None:
    _explained(world, PAGE + "<div class='wide how-to-read'>And a second idea.</div>\n")


@proof("scorecard/explainer", "a page over the project's cap", expect="fail", contains="over the cap of 300")
def _(world: World) -> None:
    _explained(world, PAGE + "<p>" + "more and more words " * 20 + "</p>\n",
               manifest='\n[rules."scorecard/explainer"]\nmax_bytes = 300\n')


@proof("scorecard/explainer", "the README does not excuse a broken page", expect="fail", contains="holds 3 controls")
def _(world: World) -> None:
    _explained(world, PAGE + "<button>Again</button>\n")
    world.write(f"{STUDY}/README.md", "explainer: none - the page is not ready yet\n")


@proof("scorecard/explainer", "no result yet, so no page is owed", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _study(world)
    world.remove(f"{STUDY}/results/metrics.json")


NO_PAGE = "explainer: none - the result is one table of numbers\n"


@proof("scorecard/explainer", "scoped to strategy and signal, a tune study owes no page", expect="pass")
def _(world: World) -> None:
    _scoped(world, "scorecard/explainer", 'kinds = ["strategy", "signal"]',
            (STUDY, "strategy", NO_PAGE), ("work/b", "tune", None))


@proof("scorecard/explainer", "scoped to strategy and signal, a signal study still owes one", expect="fail",
       contains="no explainer page")
def _(world: World) -> None:
    _scoped(world, "scorecard/explainer", 'kinds = ["strategy", "signal"]',
            (STUDY, "tune", None), ("work/b", "signal", None))


@proof("scorecard/explainer", "a kind that does not exist", expect="refuse", contains="kinds names stratgy, which")
def _(world: World) -> None:
    _scoped(world, "scorecard/explainer", 'kinds = ["stratgy"]', (STUDY, "strategy", NO_PAGE))


@proof("scorecard/explainer", "a study sealed before the rule binds is left alone", expect="pass")
def _(world: World) -> None:
    _sealed_early(world, "scorecard/explainer", "2027-01-01", NO_PAGE)


@proof("scorecard/explainer", "a study sealed on the day the rule binds is held to it", expect="fail",
       contains="no explainer page")
def _(world: World) -> None:
    _sealed_early(world, "scorecard/explainer", "2026-01-01", NO_PAGE)


# -- scorecard/rendering ------------------------------------------------------------------------


@rule(
    "scorecard/rendering",
    "No page puts two bare dollar signs in one line, and no chart file is oversized.",
    pack="trading",
    params=(Param("max_chart_bytes", int, 1000000, "lower", "the most bytes one page or picture under results/ "
                  "may hold"),),
    learned="A page showed two prices in one line, and the words between them were set as mathematics and lost.",
)
def rendering(ctx: Context) -> None:
    for unit, files in sorted(units.studies(ctx).items()):
        if _sealed_before(ctx, unit, files):
            continue
        for path in files:
            if not path.lower().endswith(".md"):
                continue
            ctx.inspect()
            text = ctx.read(path)
            if text is None:
                ctx.refuse("this markdown file cannot be read as text", where=path)
                continue
            for number, line in markdown.dollar_lines(text):  # the core reader: prose only, as CommonMark reads it
                ctx.breach(f"this line holds {len(markdown.bare_dollars(line))} bare dollar signs, so the words "
                           "between them are read as mathematics and vanish", where=path, line=number,
                           fix="write each sign as \\$, put the amounts in code spans, or keep one sign to a line")
        for path in work.inside(unit, files, ["results/**/*.html", "results/**/*.svg", "results/**/*.png"]):
            ctx.inspect()
            size = (ctx.root / path).stat().st_size
            if size > ctx.param("max_chart_bytes"):
                ctx.breach(f"this file is {size:,} bytes, over the cap of {ctx.param('max_chart_bytes'):,} for a "
                           "page or a picture", where=path, fix="draw fewer points, or split the page")


SMALL_CAP = '\n[rules."scorecard/rendering"]\nmax_chart_bytes = 200\n'
CLEAN = """\
# The result

A stake of $100 ended at 112.
It made \\$12 on a \\$100 stake.
The cost was `$3` on a `$100` stake.

```
fee = $1 + $2
```
"""


def _rendered_early(world: World, since: str) -> None:
    """A study sealed and merged to main, whose README later puts two bare signs on one line."""
    world.manifest(MANIFEST + f'\n[rules."scorecard/rendering"]\nsince = "{since}"\n')
    world.write(f"{STUDY}/PRE-REG.md", "---\nkind: strategy\n---\nThe plan.\n")
    world.commit("the seal, before the rule binds")
    world.write(f"{STUDY}/README.md", "It made $12 on a $100 stake.\n")
    world.write("work/b/README.md", "It made \\$12 on a \\$100 stake.\n")  # a study sealed later, written well


@proof("scorecard/rendering", "a study sealed before the rule binds is left alone", expect="pass")
def _(world: World) -> None:
    _rendered_early(world, "2027-01-01")


@proof("scorecard/rendering", "a study sealed on the day the rule binds is held to it", expect="fail",
       contains="2 bare dollar signs")
def _(world: World) -> None:
    _rendered_early(world, "2026-01-01")


@proof("scorecard/rendering", "one sign to a line, escaped signs, code spans and a code block", expect="pass")
def _(world: World) -> None:
    _study(world, manifest=SMALL_CAP)
    world.write(f"{STUDY}/README.md", CLEAN)
    world.write(f"{STUDY}/results/headline.svg", "<svg></svg>\n")
    world.write(f"{STUDY}/results/trades.csv", "net\n" + "12.5\n" * 100)  # a large table is not a chart


@proof("scorecard/rendering", "two prices in one line", expect="fail", contains="holds 2 bare dollar signs")
def _(world: World) -> None:
    _study(world)
    world.write(f"{STUDY}/README.md", "# The result\n\nIt made $12 on a $100 stake.\n")


@proof("scorecard/rendering", "the pair sits in the seal", expect="fail", contains="holds 2 bare dollar signs")
def _(world: World) -> None:
    _study(world)
    world.write(f"{STUDY}/PRE-REG.md", "---\nkind: strategy\n---\nRisk $1 to make $2 on each trade.\n")


@proof("scorecard/rendering", "one escaped sign and two bare ones", expect="fail", contains="holds 2 bare dollar signs")
def _(world: World) -> None:
    _study(world)
    world.write(f"{STUDY}/notes/costs.md", "The fee is \\$1, the spread $2 and the swap $3.\n")


@proof("scorecard/rendering", "pairs in an HTML block and in a diagram are not prose", expect="pass")
def _(world: World) -> None:
    _study(world)
    world.write(f"{STUDY}/README.md", '<div>\n$1 and $2\n</div>\n\n~~~mermaid\nA["$1"] --> B["$2"]\n~~~\n')


@proof("scorecard/rendering", "a shorter fence inside a long one does not close it", expect="fail",
       contains="holds 2 bare dollar signs")
def _(world: World) -> None:
    _study(world)
    world.write(f"{STUDY}/README.md", "````md\n```\n````\nIt made $12 on a $100 stake.\n")


@proof("scorecard/rendering", "a picture over the project's cap", expect="fail", contains="over the cap of 200")
def _(world: World) -> None:
    _study(world, manifest=SMALL_CAP)
    world.write(f"{STUDY}/results/charts/equity.png", "x" * 300)


@proof("scorecard/rendering", "a page outside any study", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    world.manifest(MANIFEST)
    world.write("docs/prices.md", "It made $12 on a $100 stake.\n")
