"""Gate: scorecard — a result a newcomer can read.

Four rules about what a study publishes beside its numbers: the scorecard and its report, five
answers about how far the result can be believed, one short page that explains it, and pages that
render as they were written.

A study is "published" here once it has anything under `results/`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from themis import work
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
_CODE_SPAN = re.compile(r"(`+).*?\1")
_BARE_DOLLAR = re.compile(r"(?<!\\)\$")


def _published(ctx: Context) -> list[tuple[str, list[str]]]:
    """The studies that have results, in order."""
    return [(unit, files) for unit, files in sorted(units.studies(ctx).items()) if units.has_results(unit, files)]


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
    learned="A finding was quoted for weeks before anyone asked how many independent cases it rested on.",
)
def believable(ctx: Context) -> None:
    fix = (f'add a heading "{QUESTION}" and answer under it, in a numbered list: what the independent unit is; '
           "how many were checked; what could be missed; whether the sources are independent; what is unexplained")
    for unit, _ in _published(ctx):
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


# -- scorecard/explainer ------------------------------------------------------------------------


@rule(
    "scorecard/explainer",
    "A published result has one short page for a newcomer, or says why it has none.",
    pack="trading",
    params=(
        Param("max_bytes", int, 200000, "lower", "the most bytes the explainer page may hold"),
        Param("max_controls", int, 2, "lower", "the most controls (inputs, buttons, selects) the explainer may hold"),
    ),
    learned="A result was explained by a page of sliders that no newcomer could follow.",
)
def explainer(ctx: Context) -> None:
    for unit, _ in _published(ctx):
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


# -- scorecard/rendering ------------------------------------------------------------------------


def _dollar_lines(text: str) -> list[tuple[int, int]]:
    """Each line that holds two or more bare dollar signs, as (line number, how many). A sign
    after a backslash, in a code span or in a fenced block is not bare."""
    found, fenced = [], False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith(_FENCE):
            fenced = not fenced
            continue
        count = 0 if fenced else len(_BARE_DOLLAR.findall(_CODE_SPAN.sub("", line)))
        if count >= 2:
            found.append((number, count))
    return found


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
        for path in files:
            if not path.lower().endswith(".md"):
                continue
            ctx.inspect()
            text = ctx.read(path)
            if text is None:
                ctx.refuse("this markdown file cannot be read as text", where=path)
                continue
            for number, count in _dollar_lines(text):
                ctx.breach(f"this line holds {count} bare dollar signs, so the words between them are read as "
                           "mathematics and vanish", where=path, line=number,
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


@proof("scorecard/rendering", "a picture over the project's cap", expect="fail", contains="over the cap of 200")
def _(world: World) -> None:
    _study(world, manifest=SMALL_CAP)
    world.write(f"{STUDY}/results/charts/equity.png", "x" * 300)


@proof("scorecard/rendering", "a page outside any study", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    world.manifest(MANIFEST)
    world.write("docs/prices.md", "It made $12 on a $100 stake.\n")
