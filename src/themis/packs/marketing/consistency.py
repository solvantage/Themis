"""Gate: consistency — what is made matches what was approved.

The brief is the sealed plan of one item. Everything made after it follows the brief: the plan
derived from it, the assets, the spoken lines. These rules compare each of those with what the
owner approved, before any paid job is sent. The last rule does the same for a checker that keeps
its own copy of rule data: the copy must equal its reference file.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from themis.packs.marketing import items
from themis.rule import Context, Param, proof, rule
from themis.schema import Required

if TYPE_CHECKING:
    from themis.proofs import World

FIELDS = ("id", "start_s", "end_s", "text", "line")
RATE = Param("words_per_second", float, 2.5, "lower", "the fastest speaking rate allowed, in words a second")
PIN = {"checker": Required(str), "reference": Required(str), "marker": Required(str)}
PINS = Param("pins", [PIN], None, "larger",
             "each checker that holds a copy of rule data: its file, its reference file, and the marker round the copy")


def _part_line(text: str | None, index: int) -> int | None:
    """The line a part starts on, when the file writes its parts as [[parts]] tables."""
    heads = [at for at, line in enumerate((text or "").splitlines(), start=1) if line.strip() == "[[parts]]"]
    return heads[index] if index < len(heads) else None


# -- consistency/derived-matches ----------------------------------------------------------------


@rule(
    "consistency/derived-matches",
    "Each plan derived from the brief equals the brief.",
    pack="marketing",
    learned="A derived plan carried another end time than the approved brief, and the paid job followed the plan.",
)
def derived_matches(ctx: Context) -> None:
    fix = "derive the plan again from the brief; to change what was approved, amend the brief first"
    for unit in sorted(items.items(ctx)):
        brief, plan = items.load(ctx, unit, "brief"), items.load(ctx, unit, "plan")
        if brief is None or plan is None:
            continue  # no plan to compare yet, or a file that was refused above
        ctx.inspect()
        where = f"{unit}/plan.toml"
        text, made, approved = ctx.read(where), plan["parts"], brief.get("parts", [])
        if len(made) != len(approved):
            ctx.breach(f"the plan holds {len(made)} part(s) and the brief holds {len(approved)}", where=where, fix=fix)
        for index, (ours, theirs) in enumerate(zip(made, approved)):
            field = next((field for field in FIELDS if ours.get(field, "") != theirs.get(field, "")), None)
            if field:
                ctx.breach(f"part {index + 1} of the plan differs from the brief: {field} is {ours.get(field, '')!r} "
                           f"in the plan and {theirs.get(field, '')!r} in the brief",
                           where=where, line=_part_line(text, index), fix=fix)
        if "length_s" in plan and "length_s" in brief and plan["length_s"] != brief["length_s"]:
            ctx.breach(f"the plan's length is {plan['length_s']:g} s and the brief's length is {brief['length_s']:g} s",
                       where=where, fix=fix)
        for index, part in enumerate(made):
            clash = next((other["id"] for other in made[:index]
                          if part["start_s"] < other["end_s"] and other["start_s"] < part["end_s"]), None)
            at, named = _part_line(text, index), f"part {index + 1} ({part['id']})"
            if part["end_s"] < part["start_s"]:
                ctx.breach(f"{named} ends before it starts", where=where, line=at,
                           fix="give the part an end time after its start time")
            elif clash is not None:
                ctx.breach(f"{named} and the part {clash} overlap in time", where=where, line=at,
                           fix="give each part its own time; one part may start where another ends")


SETUP = """
    [project]
    packs = ["marketing"]

    [marketing]
    work = "content/*"
"""
PARTS = (
    ("hook", 0.0, 4.0, "Three steps", "Here are three easy steps for a better cup"),
    ("body", 4.0, 12.0, "Warm the pot", "First warm the pot and then add the leaves"),
)


Parts = tuple[tuple[Any, ...], ...]
BRIEF = 'kind = "content"\ntitle = "A better cup"\nseries = "howto"\nlength_s = 12.0\n'
LONG = "one two three four five six seven eight nine ten eleven"  # eleven words


def _parts(parts: Parts) -> str:
    part = '\n[[parts]]\nid = "{}"\nstart_s = {}\nend_s = {}\ntext = "{}"\nline = "{}"\n'
    return "".join(part.format(*fields) for fields in parts)


def _item(world: World, parts: Parts = PARTS, plan: str = "") -> None:
    """One honest item: a brief of two parts, a plan that repeats it, and one asset from the series' kit."""
    world.manifest(SETUP)
    world.write("content/a/brief.toml", BRIEF + _parts(parts))
    world.write("content/a/plan.toml", f"length_s = 12.0\n{plan}" + _parts(parts))
    world.write("content/a/assets/host.toml", 'kit_item = "host"\ntool = "picture-tool"\nseed = 7\n')
    world.write("series/howto.toml", 'audience = "home cooks"\nformat = "short"\nkit = ["host", "kitchen"]\n')


def _change(world: World, path: str, old: str, new: str) -> None:
    """Change one thing in a file of the world. The text to replace must occur exactly once."""
    text = (world.root / path).read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise ValueError(f"{old!r} occurs {text.count(old)} times in {path}; it must occur once")
    world.write(path, text.replace(old, new))


@proof("consistency/derived-matches", "a plan that repeats its brief", expect="pass")
def _(world: World) -> None:
    _item(world)


@proof("consistency/derived-matches", "a whole number in the plan where the brief writes a decimal", expect="pass")
def _(world: World) -> None:
    _item(world)
    _change(world, "content/a/plan.toml", "end_s = 12.0", "end_s = 12")


@proof("consistency/derived-matches", "one part's end time changed in the plan", expect="fail",
       contains="part 2 of the plan differs from the brief: end_s is 13.0 in the plan and 12.0 in the brief")
def _(world: World) -> None:
    _item(world)
    _change(world, "content/a/plan.toml", "end_s = 12.0", "end_s = 13.0")


@proof("consistency/derived-matches", "a part left out of the plan", expect="fail",
       contains="the plan holds 1 part(s) and the brief holds 2")
def _(world: World) -> None:
    _item(world)
    world.write("content/a/plan.toml", "length_s = 12.0\n" + _parts(PARTS[:1]))


@proof("consistency/derived-matches", "a plan longer than its brief", expect="fail",
       contains="the plan's length is 15 s and the brief's length is 12 s")
def _(world: World) -> None:
    _item(world)
    _change(world, "content/a/plan.toml", "length_s = 12.0", "length_s = 15.0")


@proof("consistency/derived-matches", "two parts that overlap in time, in the brief and in the plan", expect="fail",
       contains="part 2 (body) and the part hook overlap in time")
def _(world: World) -> None:
    _item(world, parts=(PARTS[0], ("body", 3.0, 12.0, "Warm the pot", "First warm the pot")))


@proof("consistency/derived-matches", "a part that ends before it starts", expect="fail",
       contains="part 2 (body) ends before it starts")
def _(world: World) -> None:
    _item(world, parts=(PARTS[0], ("body", 12.0, 4.0, "Warm the pot", "First warm the pot")))


@proof("consistency/derived-matches", "an item with a brief and no plan yet is left alone", expect="refuse",
       contains="nothing was inspected")
def _(world: World) -> None:
    _item(world)
    world.remove("content/a/plan.toml")


# -- consistency/assets-from-kit ----------------------------------------------------------------


@rule(
    "consistency/assets-from-kit",
    "Every asset used is an approved asset of the item's series.",
    pack="marketing",
    learned="An item used a design the owner had never approved for that series.",
)
def assets_from_kit(ctx: Context) -> None:
    for unit, files in sorted(items.items(ctx).items()):
        notes = items.assets(ctx, unit, files)
        if not notes:
            continue  # an item with no asset note has used no asset
        brief = items.load(ctx, unit, "brief")
        name = (brief or {}).get("series", "")
        if brief is None and ctx.exists(f"{unit}/brief.toml"):
            continue  # the brief was refused above
        if not name or name.startswith(".") or "/" in name:
            ctx.refuse("this item holds assets, and its brief names no series whose kit can be read", where=unit,
                       fix="name the item's series in its brief, by the name of its file under series/")
            continue
        series = items.series(ctx, name)
        if series is None:
            if not ctx.exists(f"series/{name}.toml"):
                ctx.refuse(f"the brief names the series {name}, which has no series file", where=f"{unit}/brief.toml",
                           fix=f"add series/{name}.toml with the kit the owner approved")
            continue
        for path, note in sorted(notes.items()):
            ctx.inspect()
            used = note.get("kit_item")
            if not used:
                ctx.breach("this asset names no kit item, so it cannot be shown to be approved", where=path,
                           fix="set kit_item to the approved asset this one was made from")
            elif used not in series.get("kit", []):
                ctx.breach(f"this asset was made from {used!r}, which is not in the kit of the series {name}",
                           where=path, fix="use an approved asset of the series, or have the owner add it to the kit")


@proof("consistency/assets-from-kit", "an asset made from the series' kit", expect="pass")
def _(world: World) -> None:
    _item(world)


@proof("consistency/assets-from-kit", "an item with no asset note is left alone, whatever its series", expect="pass")
def _(world: World) -> None:
    _item(world)
    world.write("content/b/brief.toml", 'kind = "research"\ntitle = "Which topics"\nseries = "not-started"\n')


@proof("consistency/assets-from-kit", "an asset that is not in the kit", expect="fail",
       contains="was made from 'mascot', which is not in the kit of the series howto")
def _(world: World) -> None:
    _item(world)
    _change(world, "content/a/assets/host.toml", 'kit_item = "host"', 'kit_item = "mascot"')


@proof("consistency/assets-from-kit", "an asset that names no kit item", expect="fail", contains="names no kit item")
def _(world: World) -> None:
    _item(world)
    _change(world, "content/a/assets/host.toml", 'kit_item = "host"\n', "")


@proof("consistency/assets-from-kit", "an asset approved for another series, beside an approved one", expect="fail",
       contains="was made from 'narrator', which is not in the kit of the series howto")
def _(world: World) -> None:
    _item(world)
    world.write("series/stories.toml", 'kit = ["narrator"]\n')
    world.write("content/a/assets/voice.toml", 'kit_item = "narrator"\ntool = "voice-tool"\nsetting = "calm"\n')


@proof("consistency/assets-from-kit", "the brief names a series that has no file", expect="refuse",
       contains="the brief names the series howto, which has no series file")
def _(world: World) -> None:
    _item(world)
    world.remove("series/howto.toml")


@proof("consistency/assets-from-kit", "assets under a brief that names no series", expect="refuse",
       contains="its brief names no series")
def _(world: World) -> None:
    _item(world)
    _change(world, "content/a/brief.toml", 'series = "howto"\n', "")


# -- consistency/timing-fits --------------------------------------------------------------------


def _words(line: str) -> float:
    """How many words a spoken line holds. A line with no space at all is measured by its length,
    four characters to a word, so a language written without spaces is still measured."""
    return float(len(line.split())) if re.search(r"\s", line) else len(line) / 4


@rule(
    "consistency/timing-fits",
    "Each spoken line fits its part's time.",
    pack="marketing",
    params=(RATE,),
    learned="A spoken line was too long for its part, and the paid job had to be run again.",
)
def timing_fits(ctx: Context) -> None:
    allowed = ctx.param("words_per_second")
    for unit in sorted(items.items(ctx)):
        brief = items.load(ctx, unit, "brief")
        if brief is None:
            continue
        plan = items.load(ctx, unit, "plan") or {}
        rate = min(allowed, plan.get("speaking_rate") or allowed)  # a plan may slow the voice down, never speed it up
        where = f"{unit}/brief.toml"
        text = ctx.read(where)
        for index, part in enumerate(brief.get("parts", [])):
            line = part.get("line", "").strip()
            if not line:
                continue  # nothing is spoken in this part
            ctx.inspect()
            seconds = part["end_s"] - part["start_s"]
            if _words(line) > seconds * rate + 1e-9:
                ctx.breach(f"the line of part {index + 1} ({part['id']}) holds {_words(line):g} words, and "
                           f"{seconds:g} s at {rate:g} words a second allows {max(seconds * rate, 0):g}",
                           where=where, line=_part_line(text, index),
                           fix="shorten the line or give the part more time, before any paid job is priced")


NO_SPACES = "茶" * 40  # forty characters with no space: ten words


@proof("consistency/timing-fits", "lines that fit their parts", expect="pass")
def _(world: World) -> None:
    _item(world)


@proof("consistency/timing-fits", "a line that fills its part exactly", expect="pass")
def _(world: World) -> None:
    _item(world, parts=(("hook", 0.0, 4.0, "Three steps", LONG.removesuffix(" eleven")),))


@proof("consistency/timing-fits", "a line with no spaces that fits, measured by its length", expect="pass")
def _(world: World) -> None:
    _item(world, parts=(("hook", 0.0, 4.0, "Three steps", NO_SPACES),))


@proof("consistency/timing-fits", "one word too many for the part", expect="fail",
       contains="the line of part 1 (hook) holds 11 words, and 4 s at 2.5 words a second allows 10")
def _(world: World) -> None:
    _item(world, parts=(("hook", 0.0, 4.0, "Three steps", LONG),))


@proof("consistency/timing-fits", "a line with no spaces that is too long", expect="fail",
       contains="holds 10 words, and 3 s at 2.5 words a second allows 7.5")
def _(world: World) -> None:
    _item(world, parts=(("hook", 0.0, 3.0, "Three steps", NO_SPACES),))


@proof("consistency/timing-fits", "a plan with a slower voice is held to its own rate", expect="fail",
       contains="holds 9 words, and 4 s at 2 words a second allows 8")
def _(world: World) -> None:
    _item(world, plan="speaking_rate = 2.0\n")


@proof("consistency/timing-fits", "a plan cannot speed the voice up past the project's rate", expect="fail",
       contains="holds 11 words, and 4 s at 2.5 words a second allows 10")
def _(world: World) -> None:
    _item(world, parts=(("hook", 0.0, 4.0, "Three steps", LONG),), plan="speaking_rate = 5.0\n")


@proof("consistency/timing-fits", "no brief holds a spoken line", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _item(world, parts=(("card", 0.0, 4.0, "Three steps", ""),))


# -- consistency/rulebook-pinned ----------------------------------------------------------------


def _data(lines: list[str], first: int) -> list[tuple[int, str]]:
    """The lines that hold rule data, each with its line number: quotes, commas and space stripped;
    blank lines and comment lines left out."""
    found = []
    for number, line in enumerate(lines, start=first):
        text = line.strip().rstrip(",").strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
            text = text[1:-1].strip()
        if text and not text.startswith("#"):
            found.append((number, text))
    return found


@rule(
    "consistency/rulebook-pinned",
    "Rule data held inside a checker equals its reference file.",
    pack="marketing",
    params=(PINS,),
    requires=("pins",),
    learned="A checker kept its own copy of a rule list, and the copy fell behind the reference.",
)
def rulebook_pinned(ctx: Context) -> None:
    fix = "copy the reference into the checker again, between the two marker lines; the reference is the one home"
    for pin in ctx.param("pins"):
        ctx.inspect()
        checker, reference, marker = pin["checker"], pin["reference"], pin["marker"]
        held, source = ctx.read(checker), ctx.read(reference)
        if held is None or source is None:
            ctx.refuse(f"the {'checker' if held is None else 'reference file'} is missing or cannot be read",
                       where=checker if held is None else reference, fix="correct the path under pins, or restore it")
            continue
        lines = [" ".join(line.split()) for line in held.splitlines()]
        try:
            begin = lines.index(f"# {marker} begin")
            end = lines.index(f"# {marker} end", begin)
        except ValueError:
            ctx.refuse(f"the checker does not hold the lines `# {marker} begin` and `# {marker} end`, in that order",
                       where=checker, fix="put the checker's copy of the rule data between those two lines")
            continue
        copy = _data(held.splitlines()[begin + 1:end], begin + 2)
        wanted = [text for _, text in _data(source.splitlines(), 1)]
        if not wanted:
            ctx.refuse("the reference file holds no rule data to compare with", where=reference,
                       fix="write the rule data in the reference file, one entry a line")
            continue
        copied = [text for _, text in copy]
        if copied == wanted:
            continue
        extra = next(((number, text) for number, text in copy if text not in wanted), None)
        lacking = next((text for text in wanted if text not in copied), None)
        said = (f"holds {extra[1]!r}, which is not in its reference" if extra
                else f"lacks {lacking!r}, which its reference holds" if lacking
                else "holds the entries of its reference in another order, or another number of times")
        ctx.breach(f"the checker's copy {said}", where=checker, line=extra[0] if extra else begin + 1, fix=fix)


PINNED = SETUP + """
    [[rules."consistency/rulebook-pinned".pins]]
    checker = "tools/check_terms.py"
    reference = "rules/terms.txt"
    marker = "terms"
"""
CHECKER = """
    TERMS = [
        # terms begin
        "guaranteed result",
        'overnight cure',
        # terms end
    ]
"""
TERMS = "guaranteed result\novernight cure\n"


def _pinned(world: World, checker: str = CHECKER, reference: str = TERMS) -> None:
    world.manifest(PINNED)
    world.write("tools/check_terms.py", checker)
    world.write("rules/terms.txt", reference)


@proof("consistency/rulebook-pinned", "a copy that equals its reference", expect="pass")
def _(world: World) -> None:
    _pinned(world)


@proof("consistency/rulebook-pinned", "blank lines and comments in the reference, and a copy written as plain lines",
       expect="pass")
def _(world: World) -> None:
    _pinned(world, checker="# terms begin\nguaranteed result\novernight cure\n# terms end\n",
            reference="# what an item may never promise\n\nguaranteed result\n\novernight cure\n")


@proof("consistency/rulebook-pinned", "an entry added to the reference and not to the checker", expect="fail",
       contains="the checker's copy lacks 'instant relief', which its reference holds")
def _(world: World) -> None:
    _pinned(world, reference=TERMS + "instant relief\n")


@proof("consistency/rulebook-pinned", "an entry reworded in the checker only", expect="fail",
       contains="the checker's copy holds 'overnight fix', which is not in its reference")
def _(world: World) -> None:
    _pinned(world, checker=CHECKER.replace("overnight cure", "overnight fix"))


@proof("consistency/rulebook-pinned", "the same entries in another order", expect="fail", contains="in another order")
def _(world: World) -> None:
    _pinned(world, reference="overnight cure\nguaranteed result\n")


@proof("consistency/rulebook-pinned", "a checker with no marker lines", expect="refuse",
       contains="does not hold the lines `# terms begin` and `# terms end`")
def _(world: World) -> None:
    _pinned(world, checker=CHECKER.replace("# terms end", "# the end"))


@proof("consistency/rulebook-pinned", "a reference file that is not there", expect="refuse",
       contains="the reference file is missing or cannot be read")
def _(world: World) -> None:
    _pinned(world)
    world.remove("rules/terms.txt")


@proof("consistency/rulebook-pinned", "a reference with nothing in it proves nothing", expect="refuse",
       contains="holds no rule data to compare with")
def _(world: World) -> None:
    _pinned(world, checker="# terms begin\n# terms end\n", reference="# nothing yet\n")
