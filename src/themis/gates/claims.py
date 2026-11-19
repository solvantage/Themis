"""Gate: claims — no number without a receipt.

In a governed document a number is followed by an invisible tag that names the record it comes
from: `**+3.7 pp**<!--t:open-drive#uplift_half_stop-->`. `open-drive` is the folder name of a unit
of work, and `uplift_half_stop` is a key in that unit's metrics file. A decision is cited with
`<!--d:open-drive-->`. The reading of tags, numbers and links lives in `themis.claims`.
"""

from __future__ import annotations

import functools
import json
import posixpath
from collections.abc import Iterator
from typing import TYPE_CHECKING

from themis import claims, receipts, records, work
from themis.gates.order import WORK
from themis.rule import Context, Param, proof, rule
from themis.schema import Required

if TYPE_CHECKING:
    from themis.proofs import World
    from themis.records import Record

records.register("method", {"adopted": Required(str), "check": Required(str), "can_flip": [str]}, "method/*.toml")

GOVERNED = Param("governed", [str], None, "larger", "the governed documents, as path patterns, such as docs/**/*.md")
METRICS = Param("metrics", str, "results/metrics.json", None, "the metrics file, inside a unit")
PROVENANCE = Param("provenance", str, "results/provenance.json", None, "the fingerprint file, inside a unit")
SECTIONS = Param("sections", [str], None, "larger", "heading texts; when set, only the lines under them are governed")

FIX_RECORD = ("cite a unit by its folder name, or by its whole path when units share that name, and a key its "
              "metrics file holds, or run the work so it writes them")
FIX_DECISION = "issue the decision with its gate, or correct the work the tag names"


def _documents(ctx: Context) -> Iterator[tuple[str, str]]:
    """Each governed document with its text. One that cannot be read is a refusal."""
    for name in sorted({name for pattern in ctx.param("governed") for name in ctx.files(pattern)}):
        text = ctx.read(name)
        if text is None:
            ctx.refuse("this governed document cannot be read as text", where=name,
                       fix="save it as plain text, or take it out of the governed documents")
        else:
            yield name, text


def _units(ctx: Context) -> claims.UnitNames | None:
    """Each name a tag may use for a unit, or None after a refusal that says why the units cannot be listed."""
    try:
        return claims.unit_names(work.units(ctx.all_files, ctx.param("work")))
    except ValueError as error:
        ctx.refuse(str(error), where="themis.toml",
                   fix="name the unit folders at one depth, with one pattern or a list of them, such as work/*")
        return None


def _predating(ctx: Context) -> set[str]:
    """The names of the units whose results reached the main line before the rule's start date (its
    `since`): the files in the folder that holds the metrics file or the fingerprint. A tag that
    cites one of them is not checked: a record older than the rule is not held to it. A folder
    begun earlier still binds results first made after that date."""
    if ctx.since is None:
        return set()
    try:
        found = work.units(ctx.all_files, ctx.param("work"))
    except ValueError:
        return set()  # _units has already said why
    held = [inner.strip("/") for inner in (ctx.param("metrics"), ctx.param("provenance")) if inner]
    results = [f"{posixpath.dirname(inner)}/**" if "/" in inner else inner for inner in held]
    old = {unit for unit, files in found.items() if ctx.predates(work.inside(unit, files, results))}
    return {name for name, unit in claims.unit_names(found).items() if unit in old}


# -- claims/receipt -----------------------------------------------------------------------------


@rule(
    "claims/receipt",
    "Each number in a governed document cites a record, and matches it.",
    params=(GOVERNED, WORK, METRICS, SECTIONS),
    requires=("governed", "work"),
    learned="A report quoted a result from memory, and no record held that number.",
)
def receipt(ctx: Context) -> None:
    units = _units(ctx)
    if units is None:
        return
    old = _predating(ctx)
    for path, text in _documents(ctx):
        lines = claims.governed_lines(text, ctx.param("sections"))
        if not lines:
            continue  # this document has none of the governed sections
        ctx.inspect()
        for line, number in claims.untagged_numbers(text):
            if line in lines:
                ctx.breach(f"the number {number} cites no record", where=path, line=line,
                           fix="paste the number with its tag, as `themis cite` prints it, or take the number out")
        for tag in claims.find_tags(text):
            if tag.line not in lines or tag.work in old:
                continue
            cited = f"{tag.work}#{tag.key}"
            if tag.number is None:
                ctx.breach(f"the tag t:{cited} has no number right before it", where=path, line=tag.line,
                           fix="put the tag right after its number, such as 3.7<!--t:WORK#KEY-->")
                continue
            try:
                value = claims.resolve(ctx.root, units, tag.work, tag.key, ctx.param("metrics"))
            except ValueError as error:
                ctx.refuse(f"the tag t:{cited} cannot be checked: {error}", where=path, fix=FIX_RECORD)
                continue
            if not claims.matches(tag.number, value):
                ctx.breach(f"the document says {tag.number}, but the record {cited} holds {value}", where=path,
                           line=tag.line, fix=f"run `themis cite {tag.work} {tag.key}` and paste what it prints")
        for cited_receipt in claims.find_receipt_tags(text):
            if cited_receipt.line in lines:
                _check_receipt(ctx, path, cited_receipt)


def _check_receipt(ctx: Context, path: str, cited: claims.ReceiptTag) -> None:
    """A receipt citation stands for every number before it on its line: each must be a figure
    the receipt holds."""
    name = f"{cited.kind}/{cited.name}"
    held = [found for found in receipts.read_all(ctx.root, cited.kind)
            if found["_path"].rsplit("/", 1)[-1] == f"{cited.name}.json"]
    if not held:
        ctx.refuse(f"the tag r:{name} names a receipt that is not on file", where=path,
                   fix="cite a receipt that exists; a receipt is written by a tool, never by hand")
        return
    figures = [value for value in held[0].values() if isinstance(value, (int, float)) and not isinstance(value, bool)]
    for number in cited.numbers:
        if not any(claims.matches(number, value) for value in figures):
            ctx.breach(f"the document says {number}, but the receipt {name} holds no such figure", where=path,
                       line=cited.line, fix="write the figures the receipt holds, or take the number out")


METRICS_FILE ='{"uplift_half_stop": 3.6953, "trades": 23656, "net_ev": {"value": 0.125, "unit": "R"}}\n'
ONE = "The half-size stop gave an uplift of 3.7<!--t:open-drive#uplift_half_stop--> pp.\n"
THREE = ("The half-size stop gave an uplift of **+3.7 pp**<!--t:open-drive#uplift_half_stop--> over\n"
         "`23,656`<!--t:open-drive#trades--> trades. Each trade made 0.125<!--t:open-drive#net_ev--> R.\n")
SECTIONED = "# Report\n\nBackground: 40 runs were planned.\n\n## Decision\n\n" + ONE
NOT_CLAIMS = ("**Last updated:** 2026-11-16 15:20 local (08:20 UTC). `main` at 0a1b2c3d (#42), release 1.2.3.\n\n"
              "## 3. Next\n\n1. Read [the plan](docs/2026/plan.md) and https://example.invalid/2026, run `step 4`.\n")
UNITS = 'work = "work/*"'


def _world(world: World, rule_id: str, text: str, params: str = UNITS, report: str = "REPORT.md") -> None:
    """A project with one governed report and one unit of work that holds its metrics."""
    world.manifest(f'[rules."{rule_id}"]\ngoverned = ["{report}"]\n{params}\n')
    world.write("work/open-drive/PLAN.md", "the plan\n")
    world.write("work/open-drive/results/metrics.json", METRICS_FILE)
    world.write(report, text)


@proof("claims/receipt", "numbers pasted with their tags, at the precision shown", expect="pass")
def _(world: World) -> None:
    _world(world, "claims/receipt", THREE)


@proof("claims/receipt", "dates, times, ids, versions, links and code are not claims", expect="pass")
def _(world: World) -> None:
    _world(world, "claims/receipt", NOT_CLAIMS)


@proof("claims/receipt", "with sections set, a number outside them is left alone", expect="pass")
def _(world: World) -> None:
    _world(world, "claims/receipt", SECTIONED, UNITS + '\nsections = ["Decision"]')


SUITE_LINE = "**Suite:** 1,204 pass / 3 skip<!--r:suite/run-1-->, linter clean.\n"
SUITE_RECEIPT = '{"kind": "suite", "passed": 1204, "skipped": 3, "failed": 0, "errors": 0}\n'


@proof("claims/receipt", "counts that cite the receipt of the run that produced them", expect="pass")
def _(world: World) -> None:
    _world(world, "claims/receipt", SUITE_LINE)
    world.write("receipts/suite/run-1.json", SUITE_RECEIPT)


@proof("claims/receipt", "a count the cited receipt does not hold", expect="fail", contains="holds no such figure")
def _(world: World) -> None:
    _world(world, "claims/receipt", SUITE_LINE.replace("1,204", "1,300"))
    world.write("receipts/suite/run-1.json", SUITE_RECEIPT)


@proof("claims/receipt", "a count that cites a receipt nobody wrote", expect="refuse", contains="not on file")
def _(world: World) -> None:
    _world(world, "claims/receipt", SUITE_LINE)


@proof("claims/receipt", "a number typed with no tag", expect="fail", contains="the number 3.7 cites no record")
def _(world: World) -> None:
    _world(world, "claims/receipt", "The half-size stop gave an uplift of 3.7 pp.\n")


@proof("claims/receipt", "a tagged number that is not what the record holds", expect="fail", contains="holds 3.6953")
def _(world: World) -> None:
    _world(world, "claims/receipt", ONE.replace("3.7", "4.1"))


@proof("claims/receipt", "a number cut short instead of rounded", expect="fail", contains="the document says 3.69")
def _(world: World) -> None:
    _world(world, "claims/receipt", ONE.replace("3.7", "3.69"))


@proof("claims/receipt", "one tag does not cover a second number on its line", expect="fail", contains="the number 12")
def _(world: World) -> None:
    _world(world, "claims/receipt", ONE.replace("pp.", "pp in 12 days."))


@proof("claims/receipt", "a tag with no number before it", expect="fail", contains="has no number right before it")
def _(world: World) -> None:
    _world(world, "claims/receipt", "The uplift was large<!--t:open-drive#uplift_half_stop-->.\n")


@proof("claims/receipt", "with sections set, a bare number inside one still fails", expect="fail", contains="number 40")
def _(world: World) -> None:
    _world(world, "claims/receipt", SECTIONED, UNITS + '\nsections = ["Report"]')


@proof("claims/receipt", "sections that no document has", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _world(world, "claims/receipt", SECTIONED, UNITS + '\nsections = ["Verdict"]')


@proof("claims/receipt", "a tag that names no unit of work", expect="refuse", contains="has the folder name open-drvie")
def _(world: World) -> None:
    _world(world, "claims/receipt", ONE.replace("open-drive", "open-drvie"))


TUNES = 'work = ["setups/*/tune", "work/*"]'


def _tunes(world: World, rule_id: str, text: str) -> None:
    """Two setups whose work each lives in a folder named tune, beside the report's own unit."""
    _world(world, rule_id, text, TUNES)
    for setup, rate in (("a", 0.4321), ("b", 0.25)):
        world.write(f"setups/{setup}/tune/results/metrics.json", json.dumps({"hit_rate": rate}))


@proof("claims/receipt", "units that share a folder name, each cited by its path", expect="pass")
def _(world: World) -> None:
    _tunes(world, "claims/receipt", ONE + "Setup a hit 0.43<!--t:setups/a/tune#hit_rate--> of its trades, and b "
                                          "0.25<!--t:setups/b/tune#hit_rate-->.\n")


@proof("claims/receipt", "a tag that names a folder name two units share", expect="refuse",
       contains="the folder name tune is shared by setups/a/tune, setups/b/tune: name the unit by its whole path")
def _(world: World) -> None:
    _tunes(world, "claims/receipt", ONE + "Setup a hit 0.43<!--t:tune#hit_rate--> of its trades.\n")


@proof("claims/links", "a tag that names a folder name two units share does not resolve", expect="fail",
       contains="does not resolve: the folder name tune is shared by")
def _(world: World) -> None:
    _tunes(world, "claims/links", ONE + "Setup a hit 0.43<!--t:tune#hit_rate--> of its trades.\n")


@proof("claims/receipt", "a tag whose key the metrics do not hold", expect="refuse", contains="hold no number under")
def _(world: World) -> None:
    _world(world, "claims/receipt", ONE.replace("uplift_half_stop", "uplift_full_stop"))


@proof("claims/receipt", "a unit with no metrics file", expect="refuse", contains="metrics.json is missing")
def _(world: World) -> None:
    _world(world, "claims/receipt", ONE)
    world.remove("work/open-drive/results/metrics.json")


# -- claims/fresh -------------------------------------------------------------------------------


@rule(
    "claims/fresh",
    "The cited record still verifies against its fingerprint.",
    params=(GOVERNED, WORK, PROVENANCE),
    requires=("governed", "work"),
    learned="A study stopped reproducing its own numbers, and nothing had recorded what its inputs were.",
)
def fresh(ctx: Context) -> None:
    units = _units(ctx)
    if units is None:
        return

    @functools.cache
    def changed(unit: str) -> list[str]:
        """The unit's inputs that no longer match their fingerprint. A fingerprint that cannot be used is a refusal."""
        try:
            return claims.changed_inputs(ctx.root, unit, ctx.param("provenance"))
        except ValueError as error:
            ctx.refuse(str(error), where=unit,
                       fix="run the work again so it writes its fingerprint, with an input that is in the repository")
            return []

    old = _predating(ctx)
    for path, text in _documents(ctx):
        for tag in claims.find_tags(text):
            if tag.work in old:
                continue  # it cites a unit begun before the rule's start date
            ctx.inspect()
            try:
                unit = units.unit(tag.work)
            except ValueError as error:
                ctx.refuse(f"the tag t:{tag.work}#{tag.key} names no unit of work that can be told apart: {error}",
                           where=path, fix=FIX_RECORD)
                continue
            if (moved := changed(unit)) and tag.flag != "stale":
                ctx.breach(f"the tag t:{tag.work}#{tag.key} cites a record whose input {moved[0]} changed since the "
                           "record was made", where=path, line=tag.line,
                           fix="run the work again and cite the new number, or mark the tag: <!--t:WORK#KEY stale-->")


DATA = "day,fill\n1,10.5\n"
STALE = ONE.replace("-->", " stale-->")


def _fingerprint(world: World, text: str, **inputs: str) -> None:
    """The world above, with a data file and a fingerprint that names it."""
    _world(world, "claims/fresh", text)
    world.write("data/fills.csv", DATA)
    listed = {"data/fills.csv": work.text_hash(DATA), **inputs}
    world.write("work/open-drive/results/provenance.json", json.dumps({"inputs": listed}))


@proof("claims/fresh", "unchanged inputs; one kept outside the repository is not compared", expect="pass")
def _(world: World) -> None:
    _fingerprint(world, THREE, **{"data/ticks.bin": "0" * 64})


@proof("claims/fresh", "an edited input, with the tag marked stale", expect="pass")
def _(world: World) -> None:
    _fingerprint(world, STALE)
    world.write("data/fills.csv", DATA + "2,10.7\n")


@proof("claims/fresh", "an input edited after the record was made", expect="fail", contains="data/fills.csv changed")
def _(world: World) -> None:
    _fingerprint(world, ONE)
    world.write("data/fills.csv", DATA + "2,10.7\n")


@proof("claims/fresh", "a stale mark does not cover the next tag", expect="fail", contains="t:open-drive#trades cites")
def _(world: World) -> None:
    _fingerprint(world, STALE + "It took 23,656<!--t:open-drive#trades--> trades.\n")
    world.write("data/fills.csv", DATA + "2,10.7\n")


@proof("claims/fresh", "a unit with no provenance file", expect="refuse", contains="provenance.json is missing")
def _(world: World) -> None:
    _world(world, "claims/fresh", ONE)


@proof("claims/fresh", "no listed input is in the repository", expect="refuse", contains="so nothing can be compared")
def _(world: World) -> None:
    _fingerprint(world, ONE)
    world.remove("data/fills.csv")


@proof("claims/fresh", "a tag that names no unit of work", expect="refuse", contains="names no unit of work")
def _(world: World) -> None:
    _fingerprint(world, ONE.replace("open-drive", "open-drvie"))


@proof("claims/fresh", "a document that cites no record", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _fingerprint(world, "The work is still running.\n")


# -- claims/dated -------------------------------------------------------------------------------


@rule(
    "claims/dated",
    "A cited decision carries its date and method version, and one that a later method change could flip is "
    "marked provisional.",
    params=(GOVERNED,),
    requires=("governed",),
    learned="A decision was still quoted as final after the check behind it had been tightened.",
)
def dated(ctx: Context) -> None:
    def when(record: Record, field: str) -> str | None:
        """The date at the start of that field, or None after a refusal that says it is not one."""
        date = claims.date_of(str(record.get(field)))
        if date is None:
            ctx.refuse(f"the {record.kind} record's {field} is not a date", where=record.path,
                       fix="write the date as YYYY-MM-DD, such as 2026-11-16")
        return date

    def missing(shown: str, date: str, record: Record) -> list[str]:
        """What a line that cites this decision does not say yet."""
        wanted = {"date": date, "method version": str(record.get("gate_version"))}
        return [f"{what}, {word}" for what, word in wanted.items() if not claims.has_word(shown, word)]

    decisions: dict[str, list[tuple[str, Record]]] = {}
    for record in ctx.records("decision"):
        if date := when(record, "decided_at"):
            decisions.setdefault(claims.folder_name(str(record.get("work"))), []).append((date, record))
    changes = [(date, record) for record in ctx.records("method") if (date := when(record, "adopted"))]
    for path, text in _documents(ctx):
        for line, name in claims.find_decisions(text):
            ctx.inspect()
            newest_first = sorted(decisions.get(name, []), key=lambda pair: pair[0], reverse=True)
            if not newest_first:
                ctx.refuse(f"the tag d:{name} matches no decision record", where=path, fix=FIX_DECISION)
                continue
            shown = claims.line_text(text, line)
            date, record = min(newest_first, key=lambda pair: len(missing(shown, *pair)))  # the one this line cites
            if lacks := missing(shown, date, record):
                ctx.breach(f"this line cites the decision on {name} without its {' and its '.join(lacks)}",
                           where=path, line=line, fix="write the decision's date and method version on this line")
            elif not claims.has_word(shown, "provisional"):
                for adopted, change in changes:
                    if adopted > date and record.get("gate") in change.get("can_flip", []):
                        ctx.breach(f"the method changed on {adopted} ({change.get('check')}) and could flip this "
                                   "decision, but the line does not say provisional", where=path, line=line,
                                   fix="mark the citation provisional, or decide again under the new method")
                        break


DECIDED = "Decision: keep, on 2026-03-02 (edge gate, version 2)<!--d:open-drive-->.\n"
CHANGE = 'adopted = "2026-04-01"\ncheck = "every fill must be a price that traded"\ncan_flip = ["edge"]\n'


def _decided(world: World, rule_id: str, text: str, change: str = "", params: str = "", **where: str) -> None:
    """The world above, with the decision on its unit of work, and a method change when one is given."""
    _world(world, rule_id, text, params, **where)
    world.write("decisions/open-drive.json", json.dumps({
        "work": "work/open-drive", "decision": "keep", "verdict": "pass", "gate": "edge", "gate_version": "2",
        "decided_at": "2026-03-02T10:00:00+00:00",
    }))
    if change:
        world.write("method/fills.toml", change)


@proof("claims/dated", "a decision cited with its date and method version", expect="pass")
def _(world: World) -> None:
    _decided(world, "claims/dated", DECIDED)


@proof("claims/dated", "method changes that came earlier, or cannot flip this gate", expect="pass")
def _(world: World) -> None:
    _decided(world, "claims/dated", DECIDED, CHANGE.replace("2026-04-01", "2026-02-01"))
    world.write("method/costs.toml", CHANGE.replace('"edge"', '"cost"'))


@proof("claims/dated", "a later method change, and the citation marked provisional", expect="pass")
def _(world: World) -> None:
    _decided(world, "claims/dated", DECIDED.replace("Decision:", "Provisional decision:"), CHANGE)


@proof("claims/dated", "a later method change that can flip it, and no mark", expect="fail", contains="provisional")
def _(world: World) -> None:
    _decided(world, "claims/dated", DECIDED, CHANGE)


@proof("claims/dated", "a decision cited with no date", expect="fail", contains="without its date, 2026-03-02")
def _(world: World) -> None:
    _decided(world, "claims/dated", DECIDED.replace("on 2026-03-02 ", ""))


@proof("claims/dated", "a date or a hidden comment is not the method version", expect="fail", contains="version, 2")
def _(world: World) -> None:
    _decided(world, "claims/dated", DECIDED.replace(", version 2)", ")<!-- version 2 -->"))


@proof("claims/dated", "a tag that matches no decision record", expect="refuse", contains="matches no decision record")
def _(world: World) -> None:
    _decided(world, "claims/dated", DECIDED.replace("d:open-drive", "d:close-drive"))


@proof("claims/dated", "a method record whose date cannot be read", expect="refuse", contains="adopted is not a date")
def _(world: World) -> None:
    _decided(world, "claims/dated", DECIDED, CHANGE.replace("2026-04-01", "last spring"))


# -- claims/links -------------------------------------------------------------------------------


@rule(
    "claims/links",
    "Every link and every cited record resolves.",
    params=(GOVERNED, WORK, METRICS),
    requires=("governed", "work"),
    learned="A handoff pointed at a record that had moved, and the next reader could not find it.",
)
def links(ctx: Context) -> None:
    units = _units(ctx)
    if units is None:
        return
    files = set(ctx.all_files)  # the repository's own files, so a link resolves the same way on every machine
    old = _predating(ctx)
    decided = functools.cache(lambda: {claims.folder_name(str(row.get("work"))) for row in ctx.records("decision")})
    for path, text in _documents(ctx):
        ctx.inspect()
        for line, target in claims.find_links(text):
            name = claims.link_path(path, target)
            if name and name not in files and not any(other.startswith(f"{name}/") for other in files):
                ctx.breach(f"the link {target} points at {name}, which is not in the repository", where=path,
                           line=line, fix="correct the link, or restore the file it points at")
        for tag in claims.find_tags(text):
            if tag.work in old:
                continue  # it cites a unit begun before the rule's start date
            try:
                claims.resolve(ctx.root, units, tag.work, tag.key, ctx.param("metrics"))
            except ValueError as error:
                ctx.breach(f"the tag t:{tag.work}#{tag.key} does not resolve: {error}", where=path, line=tag.line,
                           fix=FIX_RECORD)
        for line, name in claims.find_decisions(text):
            if name not in decided():
                ctx.breach(f"the tag d:{name} names a work that has no decision record", where=path, line=line,
                           fix=FIX_DECISION)


NOTES = "docs/notes/status.md"
LINKED = ("See [the plan](../../work/open-drive/PLAN.md#stop), [the unit](../../work/open-drive/), [the top](#top),\n"
          "[the site](https://example.invalid/a) and [the owner](mailto:owner@example.invalid).\n"
          "A link is written as `[text](missing.md)`.\n" + ONE + DECIDED)


@proof("claims/links", "links from the document's own folder, a tag and a decision that all resolve", expect="pass")
def _(world: World) -> None:
    _decided(world, "claims/links", LINKED, params=UNITS, report=NOTES)


@proof("claims/links", "a link that only resolves from the repository root", expect="fail",
       contains="points at docs/notes/work/open-drive/PLAN.md, which is not in the repository")
def _(world: World) -> None:
    _world(world, "claims/links", "See [the plan](work/open-drive/PLAN.md).\n", report=NOTES)


@proof("claims/links", "a tag that names no unit of work", expect="fail", contains="has the folder name open-drvie")
def _(world: World) -> None:
    _world(world, "claims/links", ONE.replace("open-drive", "open-drvie"))


@proof("claims/links", "a tag whose key the metrics do not hold", expect="fail", contains="hold no number under")
def _(world: World) -> None:
    _world(world, "claims/links", ONE.replace("uplift_half_stop", "uplift_full_stop"))


@proof("claims/links", "a decision tag with no decision record", expect="fail", contains="has no decision record")
def _(world: World) -> None:
    _world(world, "claims/links", DECIDED)


@proof("claims/links", "no governed document is there", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _world(world, "claims/links", ONE)
    world.remove("REPORT.md")


# -- a start date: a tag that cites work begun before it is not checked --------------------------

SINCE = '\nsince = "2026-06-01"'
LATE_METRICS = '{"hit_rate": 0.4321}\n'


def _old_and_late(world: World, rule_id: str, late_tag: str) -> None:
    """open-drive is committed before the rule's start date; the unit late, and the report, after it."""
    _world(world, rule_id, "", UNITS + SINCE)
    world.commit("before the rule")
    world.on("2026-07-01")
    world.write("work/late/results/metrics.json", LATE_METRICS)
    world.write("REPORT.md", ONE.replace("3.7", "4.1") + late_tag)
    world.commit("after the rule")


@proof("claims/receipt", "a folder begun before the start date, with results first made after it, is checked",
       expect="fail", contains="the document says 0.51, but the record late#hit_rate holds 0.4321")
def _(world: World) -> None:
    _world(world, "claims/receipt", "", UNITS + SINCE)
    world.write("work/late/PLAN.md", "the plan, written before the rule\n")
    world.commit("before the rule")
    world.on("2026-07-01")
    world.write("work/late/results/metrics.json", LATE_METRICS)
    world.write("REPORT.md", "The hit rate was 0.51<!--t:late#hit_rate-->.\n")
    world.commit("after the rule")


@proof("claims/receipt", "a wrong number citing work from before the start date is not checked", expect="pass")
def _(world: World) -> None:
    _old_and_late(world, "claims/receipt", "The hit rate was 0.43<!--t:late#hit_rate-->.\n")


@proof("claims/receipt", "a wrong number citing work begun after the start date is still caught", expect="fail",
       contains="the document says 0.51, but the record late#hit_rate holds 0.4321")
def _(world: World) -> None:
    _old_and_late(world, "claims/receipt", "The hit rate was 0.51<!--t:late#hit_rate-->.\n")


@proof("claims/links", "a dead key citing work from before the start date is not checked", expect="pass")
def _(world: World) -> None:
    _old_and_late(world, "claims/links", "Old: 1<!--t:open-drive#gone--> and 0.43<!--t:late#hit_rate-->.\n")


@proof("claims/links", "a dead key citing work begun after the start date is still caught", expect="fail",
       contains="the metrics of late hold no number under the key gone")
def _(world: World) -> None:
    _old_and_late(world, "claims/links", "New: 1<!--t:late#gone-->.\n")


@proof("claims/fresh", "a record from before the start date has no fingerprint, and is not checked", expect="pass")
def _(world: World) -> None:
    _old_and_late(world, "claims/fresh", "The hit rate was 0.43<!--t:late#hit_rate-->.\n")
    world.write("data/fills.csv", DATA)
    world.write("work/late/results/provenance.json", json.dumps({"inputs": {"data/fills.csv": work.text_hash(DATA)}}))
    world.commit("the late fingerprint")


@proof("claims/fresh", "a record begun after the start date with no fingerprint is still refused", expect="refuse",
       contains="work/late/results/provenance.json is missing")
def _(world: World) -> None:
    _old_and_late(world, "claims/fresh", "The hit rate was 0.43<!--t:late#hit_rate-->.\n")
