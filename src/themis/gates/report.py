"""Gate: report — a result a newcomer can read.

Finished work is read by people who were not there when it ran. So a unit of work that holds
results also holds its report, the report is built from the unit's own files and not typed by
hand, and the report explains itself.

A generated report says what it was built from. Its builder writes one comment into it, which
holds a digest of the input files:

    <!-- themis:inputs sha256=<64 hex characters> -->

A report builder calls `inputs_digest` for the digest and `digest_comment` for that line.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING

from themis import work
from themis.gates.order import RESULTS, WORK
from themis.rule import Context, Param, proof, rule

if TYPE_CHECKING:
    from themis.proofs import World

REPORT = Param("report", [str], None, "larger", "the report files, inside a unit, such as results/report.html")
INPUTS = Param("inputs", [str], ["results/metrics.json"], "larger",
               "the files a report is built from, inside a unit, by name and not by pattern")
GLOSSARY = Param("glossary", {"*": str}, {}, "larger", "each abbreviation a report may use, and what it stands for")

_DIGEST = re.compile(r"<!--\s*themis:inputs\s+sha256=([0-9a-f]{64})\s*-->")
_BRACKET = re.compile(r"\s*\(")
_CHART_TAGS = frozenset({"svg", "canvas", "img"})
_VOID = frozenset("area base br col embed hr img input link meta source track wbr".split())  # never closed
_HIDDEN = frozenset({"script", "style", "title"})  # their text is not on the page
_INLINE = frozenset("a abbr b code em i mark small span strong sub sup u".split())  # these do not end a word


def inputs_digest(root: Path, unit: str, input_files: Iterable[str]) -> str:
    """One sha256 over a unit's report inputs: the name inside the unit and the bytes of each input
    that exists, in sorted order. An input that is not there adds nothing."""
    digest = hashlib.sha256()
    for name in sorted({name.strip("/") for name in input_files}):
        try:
            data = (Path(root) / unit / name).read_bytes()
        except OSError:
            continue
        digest.update(f"{name}\0{len(data)}\0".encode("utf-8"))
        digest.update(data)
    return digest.hexdigest()


def digest_comment(digest: str) -> str:
    """The line a report builder writes into its report, to say which inputs the report was built from."""
    return f"<!-- themis:inputs sha256={digest} -->"


def _units(ctx: Context) -> dict[str, list[str]]:
    """The units this rule binds: a unit whose results and report reached the main line before the
    rule's start date (its `since`) is not held to it. A folder begun earlier still binds a report
    first made after that date."""
    made = [pattern for name in ("results", "report", "inputs") for pattern in ctx.param(name) or []]
    try:
        return ctx.bound(work.units(ctx.all_files, ctx.param("work")), made)
    except ValueError as error:
        ctx.refuse(str(error), where="themis.toml", fix="name the unit folders at one depth, such as work/*")
        return {}


def _reports(ctx: Context) -> list[tuple[str, list[str]]]:
    """Each unit that holds a report, with its report files."""
    found = []
    for unit, files in sorted(_units(ctx).items()):
        reports = work.inside(unit, files, ctx.param("report"))
        if reports:
            found.append((unit, reports))
    return found


class _Page(HTMLParser):
    """One report, read once: its charts, its how-to-read boxes, and the text a reader sees."""

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.charts = 0
        self.boxes = 0
        self.pieces: list[tuple[int, str]] = []  # the file line each piece of text starts on, and the text
        self._open: list[tuple[str, bool]] = []  # each open element, and whether it is a chart
        self.feed(source)
        self.close()

    @property
    def text(self) -> str:
        return "".join(piece for _, piece in self.pieces)

    def line_of(self, offset: int) -> int:
        """The file line that holds this place in the visible text."""
        for line, piece in self.pieces:
            if offset < len(piece):
                return line + piece.count("\n", 0, offset)
            offset -= len(piece)
        return 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        chart = tag in _CHART_TAGS or "chart" in classes
        if chart and not any(inside for _, inside in self._open):
            self.charts += 1  # a drawing inside a chart's own box is the same chart
        if "how-to-read" in classes:
            self.boxes += 1
        if tag not in _VOID:
            self._open.append((tag, chart))
        self._gap(tag)

    def handle_endtag(self, tag: str) -> None:
        names = [name for name, _ in self._open]
        if tag in names:  # closing an element also closes what was left open inside it
            del self._open[len(names) - 1 - names[::-1].index(tag):]
        self._gap(tag)

    def handle_data(self, data: str) -> None:
        if not any(name in _HIDDEN for name, _ in self._open):
            self.pieces.append((self.getpos()[0], data))

    def _gap(self, tag: str) -> None:
        if tag not in _INLINE:  # a table cell or a paragraph ends a word; bold text does not
            self.pieces.append((self.getpos()[0], " "))


# -- report/exists ------------------------------------------------------------------------------


@rule(
    "report/exists",
    "Finished work has the report its kind requires.",
    params=(WORK, RESULTS, REPORT),
    requires=("work", "results", "report"),
    learned="A finished piece of work left only raw numbers, and its reader had to guess what they meant.",
)
def exists(ctx: Context) -> None:
    for unit, files in sorted(_units(ctx).items()):
        if not work.inside(unit, files, ctx.param("results")):
            continue  # not finished: no result yet
        ctx.inspect()
        for wanted in ctx.param("report"):
            found = work.inside(unit, files, [wanted])
            if not found:
                ctx.breach(f"this unit holds results but not its report {wanted}", where=unit,
                           fix=f"build the report and save it as {unit}/{wanted.strip('/')}")
            for name in found:
                text = ctx.read(name)
                if text is not None and not text.strip():
                    ctx.breach("this report file is empty", where=name,
                               fix="build the report; an empty file says nothing")


EXISTS = """
    [rules."report/exists"]
    work = "work/*"
    results = ["results/**"]
    report = ["results/report.html"]
"""
METRICS = '{"uplift": 3.7, "sample": 212}\n'
HEADING = "<h1>Result</h1>\n"


@proof("report/exists", "a unit with results and its report, beside a unit with no result yet", expect="pass")
def _(world: World) -> None:
    world.manifest(EXISTS)
    world.write("work/a/results/metrics.json", METRICS)
    world.write("work/a/results/report.html", HEADING)
    world.write("work/b/PLAN.md", "the plan\n")


@proof("report/exists", "a unit with results and no report", expect="fail", contains="holds results but not its report")
def _(world: World) -> None:
    world.manifest(EXISTS)
    world.write("work/a/results/metrics.json", METRICS)


@proof("report/exists", "a report in another unit, or in the wrong folder, does not count", expect="fail",
       contains="holds results but not its report results/report.html")
def _(world: World) -> None:
    world.manifest(EXISTS)
    world.write("work/a/results/metrics.json", METRICS)
    world.write("work/a/report.html", HEADING)
    world.write("work/b/results/report.html", HEADING)


@proof("report/exists", "an empty file is not a report", expect="fail", contains="report file is empty")
def _(world: World) -> None:
    world.manifest(EXISTS)
    world.write("work/a/results/metrics.json", METRICS)
    world.write("work/a/results/report.html", "\n")


@proof("report/exists", "no unit holds a result yet", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    world.manifest(EXISTS)
    world.write("work/a/PLAN.md", "the plan\n")


# -- report/generated ---------------------------------------------------------------------------


@rule(
    "report/generated",
    "The report is rebuilt from the work's records and matches.",
    params=(WORK, REPORT, INPUTS),
    requires=("work", "report"),
    learned="A report was edited by hand, and after that it no longer matched the numbers under it.",
)
def generated(ctx: Context) -> None:
    inputs = ctx.param("inputs") or []
    for unit, reports in _reports(ctx):
        if not any(ctx.exists(f"{unit}/{name.strip('/')}") for name in inputs):
            ctx.refuse("none of this unit's report inputs exists, so its report cannot be checked", where=unit,
                       fix="keep the files the report is built from in the unit, or set inputs for this rule")
            continue
        now = inputs_digest(ctx.root, unit, inputs)
        for name in reports:
            ctx.inspect()
            text = ctx.read(name)
            stated = list(_DIGEST.finditer(text or ""))
            if text is None:
                ctx.refuse("this report cannot be read as text", where=name, fix="save the report as UTF-8 text")
            elif not stated:
                ctx.breach("this report holds no digest of its inputs, so nothing shows what it was built from",
                           where=name, fix="build the report with its builder, which writes the digest line")
            elif {found[1] for found in stated} != {now}:
                ctx.breach("the report was not rebuilt after its inputs changed", where=name,
                           line=text.count("\n", 0, stated[0].start()) + 1,
                           fix="run the report builder again, so the report matches its inputs")


GENERATED = """
    [rules."report/generated"]
    work = "work/*"
    report = ["results/report.html"]
"""
ONE_INPUT = ("results/metrics.json",)
TWO_INPUTS = ("results/metrics.json", "results/sample.csv")
TWO = GENERATED + '    inputs = ["results/metrics.json", "results/sample.csv"]\n'


def _built(world: World, setup: str = GENERATED, inputs: Iterable[str] = ONE_INPUT, unit: str = "work/a") -> None:
    """A unit whose report was built from its inputs, the way a report builder does it."""
    world.manifest(setup)
    world.write(f"{unit}/results/metrics.json", METRICS)
    digest = inputs_digest(world.root, unit, inputs)
    world.write(f"{unit}/results/report.html", f"{HEADING}{digest_comment(digest)}\n")


@proof("report/generated", "a report built from its inputs, beside a unit with no report yet", expect="pass")
def _(world: World) -> None:
    _built(world)
    world.write("work/b/results/metrics.json", METRICS)


@proof("report/generated", "an input that is not there yet adds nothing to the digest", expect="pass")
def _(world: World) -> None:
    _built(world, TWO, TWO_INPUTS)


@proof("report/generated", "a report typed by hand", expect="fail", contains="holds no digest of its inputs")
def _(world: World) -> None:
    world.manifest(GENERATED)
    world.write("work/a/results/metrics.json", METRICS)
    world.write("work/a/results/report.html", HEADING + "<p>The uplift was 3.7.</p>\n")


@proof("report/generated", "the numbers changed after the report was built", expect="fail",
       contains="was not rebuilt after its inputs changed")
def _(world: World) -> None:
    _built(world)
    world.write("work/a/results/metrics.json", METRICS.replace("3.7", "9.9"))


@proof("report/generated", "an input that appeared after the report was built", expect="fail",
       contains="was not rebuilt after its inputs changed")
def _(world: World) -> None:
    _built(world, TWO, TWO_INPUTS)
    world.write("work/a/results/sample.csv", "week,uplift\n1,3.7\n")


@proof("report/generated", "a report copied from another unit", expect="fail",
       contains="was not rebuilt after its inputs changed")
def _(world: World) -> None:
    _built(world)
    world.write("work/b/results/metrics.json", METRICS.replace("3.7", "1.2"))
    world.write("work/b/results/report.html", (world.root / "work/a/results/report.html").read_text(encoding="utf-8"))


@proof("report/generated", "a report whose inputs are all missing", expect="refuse",
       contains="none of this unit's report inputs exists")
def _(world: World) -> None:
    world.manifest(GENERATED)
    world.write("work/a/results/report.html", f"{HEADING}{digest_comment('0' * 64)}\n")


# -- report/readable ----------------------------------------------------------------------------


@rule(
    "report/readable",
    "Each chart has a box that says how to read it, and each abbreviation is expanded where it first appears.",
    params=(WORK, REPORT, GLOSSARY),
    requires=("work", "report"),
    learned="A reader took a chart the wrong way round, because nothing on the page said how to read it.",
)
def readable(ctx: Context) -> None:
    glossary = ctx.param("glossary") or {}
    for name in (name for _, reports in _reports(ctx) for name in reports):
        ctx.inspect()
        source = ctx.read(name)
        if source is None:
            ctx.refuse("this report cannot be read as text", where=name, fix="save the report as UTF-8 text")
            continue
        page = _Page(source)
        if page.boxes < page.charts:
            ctx.breach(f"this report has fewer how-to-read boxes than charts: {page.boxes} for {page.charts}",
                       where=name, fix='beside each chart, add a box with class="how-to-read" that says what the '
                                       "axes are and what a good result looks like")
        text = page.text
        for abbreviation, meaning in sorted(glossary.items()):
            if not abbreviation.strip():
                continue
            first = re.search(rf"(?<!\w){re.escape(abbreviation)}(?!\w)", text)
            if first and not _BRACKET.match(text, first.end()):
                ctx.breach(f"the abbreviation {abbreviation} is not expanded where it first appears", where=name,
                           line=page.line_of(first.start()),
                           fix=f"write `{abbreviation} ({meaning})` the first time the report uses it")


READABLE = """
    [rules."report/readable"]
    work = "work/*"
    report = ["results/report.html"]

    [rules."report/readable".glossary]
    EV = "expected value"
"""
PAGE = """
    <html><head><title>EV by week</title><style>.chart { width: 40em; }</style></head><body>
    <h1>Result</h1>
    <p>The <b>EV</b> (expected value) rose in each week. A higher EV is better.</p>
    <svg viewBox="0 0 10 10"><rect width="4" height="9"/></svg>
    <p class="how-to-read">Each bar is one week. A taller bar is a better week.</p>
    </body></html>
"""


def _page(world: World, page: str = PAGE) -> None:
    world.manifest(READABLE)
    world.write("work/a/results/report.html", page)


@proof("report/readable", "a chart with its box, and an abbreviation expanded at its first use", expect="pass")
def _(world: World) -> None:
    _page(world)


@proof("report/readable", "a drawing inside its own chart box is one chart, not two", expect="pass")
def _(world: World) -> None:
    _page(world, PAGE.replace("<svg", '<div class="chart wide"><svg').replace("</svg>", "</svg></div>"))


@proof("report/readable", "the same letters in a longer word, a script, a tag or a comment are not the abbreviation",
       expect="pass")
def _(world: World) -> None:
    _page(world, PAGE.replace(HEADING, '<h1 data-key="EV">REVIEW of each EVENT</h1><script>var EV = 1;</script>'
                                       "<!-- EV -->\n"))


@proof("report/readable", "a chart with no box that says how to read it", expect="fail",
       contains="fewer how-to-read boxes than charts: 0 for 1")
def _(world: World) -> None:
    _page(world, PAGE.replace('class="how-to-read"', 'class="note"'))


@proof("report/readable", "two charts that share one box", expect="fail",
       contains="fewer how-to-read boxes than charts: 1 for 2")
def _(world: World) -> None:
    _page(world, PAGE.replace(HEADING, HEADING + '<img src="trend.png" alt="the trend">\n'))


@proof("report/readable", "an abbreviation used in the heading, before it is expanded", expect="fail",
       contains="EV is not expanded where it first appears")
def _(world: World) -> None:
    _page(world, PAGE.replace(HEADING, "<h1>EV by week</h1>\n"))


@proof("report/readable", "an abbreviation that is never expanded", expect="fail",
       contains="EV is not expanded where it first appears")
def _(world: World) -> None:
    _page(world, PAGE.replace(" (expected value)", ""))


@proof("report/readable", "a unit with no report yet", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    world.manifest(READABLE)
    world.write("work/a/results/metrics.json", METRICS)


@proof("report/readable", "a report that is not text", expect="refuse", contains="cannot be read as text")
def _(world: World) -> None:
    _page(world)
    (world.root / "work/a/results/report.html").write_bytes(b"\xff\xfe\x00\x01")


# -- a start date: work begun before it is not held to these rules -----------------------------

SINCE = '    since = "2026-06-01"\n'
LATE = "2026-07-01"


@proof("report/exists", "a unit from before the start date needs no report; a later one has its own", expect="pass")
def _(world: World) -> None:
    world.manifest(EXISTS + SINCE)
    world.write("work/old/results/metrics.json", METRICS)
    world.commit("before the rule")
    world.on(LATE)
    world.write("work/a/results/metrics.json", METRICS)
    world.write("work/a/results/report.html", HEADING)
    world.commit("after the rule")


@proof("report/exists", "a unit begun after the start date is still held to it", expect="fail",
       contains="holds results but not its report")
def _(world: World) -> None:
    world.manifest(EXISTS + SINCE)
    world.commit("before the rule")
    world.on(LATE)
    world.write("work/a/results/metrics.json", METRICS)
    world.commit("after the rule")


@proof("report/exists", "a folder begun before the start date, with results first made after it, is held",
       expect="fail", contains="holds results but not its report")
def _(world: World) -> None:
    world.manifest(EXISTS + SINCE)
    world.write("work/a/PLAN.md", "the plan, written before the rule\n")
    world.commit("before the rule")
    world.on(LATE)
    world.write("work/a/results/metrics.json", METRICS)
    world.commit("after the rule")


@proof("report/generated", "a hand-typed report from before the start date is exempt", expect="pass")
def _(world: World) -> None:
    world.manifest(GENERATED + SINCE)
    world.write("work/old/results/metrics.json", METRICS)
    world.write("work/old/results/report.html", HEADING)
    world.commit("before the rule")
    world.on(LATE)
    _built(world, GENERATED + SINCE)
    world.commit("after the rule")


@proof("report/generated", "a hand-typed report begun after the start date is still held", expect="fail",
       contains="holds no digest of its inputs")
def _(world: World) -> None:
    world.manifest(GENERATED + SINCE)
    world.commit("before the rule")
    world.on(LATE)
    world.write("work/a/results/metrics.json", METRICS)
    world.write("work/a/results/report.html", HEADING)
    world.commit("after the rule")


@proof("report/generated", "a folder begun before the start date, with a report typed after it, is held",
       expect="fail", contains="holds no digest of its inputs")
def _(world: World) -> None:
    world.manifest(GENERATED + SINCE)
    world.write("work/a/PLAN.md", "the plan, written before the rule\n")
    world.commit("before the rule")
    world.on(LATE)
    world.write("work/a/results/metrics.json", METRICS)
    world.write("work/a/results/report.html", HEADING)
    world.commit("after the rule")


@proof("report/readable", "a report from before the start date is exempt; a later one reads well", expect="pass")
def _(world: World) -> None:
    world.manifest(READABLE.replace('report = ["results/report.html"]\n', 'report = ["results/report.html"]\n' + SINCE))
    world.write("work/old/results/report.html", PAGE.replace('class="how-to-read"', 'class="note"'))
    world.commit("before the rule")
    world.on(LATE)
    world.write("work/a/results/report.html", PAGE)
    world.commit("after the rule")


@proof("report/readable", "a report begun after the start date is still held", expect="fail",
       contains="fewer how-to-read boxes than charts")
def _(world: World) -> None:
    world.manifest(READABLE.replace('report = ["results/report.html"]\n', 'report = ["results/report.html"]\n' + SINCE))
    world.commit("before the rule")
    world.on(LATE)
    world.write("work/a/results/report.html", PAGE.replace('class="how-to-read"', 'class="note"'))
    world.commit("after the rule")
