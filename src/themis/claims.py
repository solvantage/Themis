"""Claims: the tags that tie a number in a document to the record it comes from.

In a governed document a number is followed by an invisible tag that names its record:

    The half-size stop gave an uplift of **+3.7 pp**<!--t:open-drive#uplift_half_stop-->.

`open-drive` is the folder name of a unit of work; `uplift_half_stop` is a key in that unit's
metrics file. A decision is cited the same way, with `<!--d:open-drive-->`. Nobody types such a
number: `cite` writes it, with its tag, from the record.

A bare number in prose is a claim, so it needs a tag. What is left alone is short and explicit:
code, HTML comments, and each entry of `EXEMPT`. Digits joined to the end of a word, as in `v2`,
`sha256` or `utf-8`, are part of that word, not a number. Ordinals and small counts are numbers.
"""

from __future__ import annotations

import hashlib
import json
import math
import posixpath
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Context, Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import unquote

_NAME = r"[\w.-]+"
_WORK = _NAME + r"(?:/" + _NAME + r")*"  # a unit by its folder name, or by its whole path when names are shared
TAG = re.compile(r"<!--\s*t:(?P<work>" + _WORK + r")#(?P<key>" + _NAME + r"?)(?:\s+(?P<flag>[^\W\d]\w*))?\s*-->")
DECISION = re.compile(r"<!--\s*d:(?P<work>" + _NAME + r"?)\s*-->")
#: A receipt citation: `<!--r:KIND/NAME-->`. It stands for every number before it on its line.
RECEIPT = re.compile(r"<!--\s*r:(?P<kind>" + _NAME + r")/(?P<name>[\w.+-]+)\s*-->")
_COMMENT = re.compile(r"<!--.*?-->", re.S)

# A sign counts only where a number can start. Digits joined to a word, directly or by `-` or `_`,
# are not a number; a lone `_` before a number is emphasis, as in `_3.7_`.
_SIGN = r"(?:(?<![\w.,)\]%])[+\-\u2212])?"
_ALONE = r"(?<![^\W_])(?<!\.)(?<![^\W\d_]-)(?<![^\W_]_)"
_DIGITS = r"(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?!\d)"
_NUMBER = _SIGN + _ALONE + _DIGITS
_BARE = re.compile(_NUMBER)
#: The number right before a tag: then a unit (%, pp, x or a short word), then the end of bold or code.
_BEFORE = re.compile(
    "(?P<number>" + _NUMBER + r")(?:[ \t\u00a0]?(?:%|\u2030|\u00d7|[^\W\d_]{1,12}))?[ \t]?[*_`]{0,4}$"
)

_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
_CODE = re.compile(r"(?<!`)(`+)(?!`)[^\n]+?(?<!`)\1(?!`)")
_CITED = re.compile(r"[*_]{0,3}<!--\s*t:")
_TITLE = r"(?:[ \t]+(?:\"[^\"\n]*\"|'[^'\n]*'))?"
_LINK = re.compile(r"\]\((?:<(?P<angle>[^<>\n]*)>|(?P<plain>[^()\s]*(?:\([^()\s]*\)[^()\s]*)*))" + _TITLE + r"\)")
#: `[label]: target`, with a title at most: a line that goes on in prose is not a definition.
_DEFINITION = re.compile(
    r"^ {0,3}\[(?!\^)[^\]\n]+\]:[ \t]*(?:<(?P<angle>[^<>\n]*)>|(?P<plain>\S+))" + _TITLE + r"[ \t\r]*$", re.M
)
_HEADING = re.compile(r" {0,3}(#{1,6})[ \t]+(.*?)[ \t#\r]*$")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:|//")

_DATE = r"\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
_CLOCK = r"(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d+)?)?"
_ZONE = r"(?:Z\b|[+-]\d{2}:?\d{2}\b|[ \t]?(?:UTC|GMT)(?:[+-]\d{1,2}(?::\d{2})?)?\b)?"

#: What is not a claim, in the order it is blanked out. Each entry has a test of its own.
EXEMPT: dict[str, re.Pattern[str]] = {
    "link definition": _DEFINITION,  # [label]: target
    "link target": _LINK,  # the (target) of [text](target)
    "link label": re.compile(r"(?<=\])\[[^\]\n]*\]|\[\^[^\]\s]+\]"),  # [text][2] and the footnote mark [^2]
    "url": re.compile(r"(?:\b[a-z][a-z0-9+.-]*://|\bmailto:|\bwww\.)[^\s<>]+", re.I),
    "date": re.compile(r"(?<![\w.])" + _DATE + "(?:[T ]" + _CLOCK + _ZONE + r")?(?!\d)"),  # 2026-11-16
    "time": re.compile(r"(?<![\w.:])" + _CLOCK + _ZONE + r"(?![\d:])"),  # 15:20, 08:20 UTC
    "version": re.compile(r"(?<![\w.])[vV]?\d+(?:\.\d+){2,}(?!\d)"),  # two or more dots: 1.2.3
    "commit id": re.compile(r"(?<![\w.])(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?!\w)"),  # hex, with a letter
    "record id": re.compile(r"#\d+"),  # a record or a pull request: #42
    "heading number": re.compile(r"^ {0,3}#{1,6}[ \t]+(?P<hide>\d+(?:\.\d+)*[.)])(?=[ \t]|$)", re.M),  # ## 3. Title
    "list number": re.compile(r"^[ \t]*(?:>[ \t]*)*(?P<hide>\d{1,9}[.)])(?=[ \t]|$)", re.M),  # 1. item
}

_WIDE = Context(prec=1000)  # room to round any number a metrics file can hold


@dataclass(frozen=True)
class Tag:
    """One `<!--t:WORK#KEY-->` tag, and the number written right before it."""

    line: int
    work: str  # the folder name of a unit of work
    key: str  # a key in that unit's metrics file
    flag: str | None = None  # a word after the key, such as `stale`
    number: str | None = None  # as written, sign and separators kept; None when no number sits before the tag


# -- reading a document -------------------------------------------------------------------------


def _spaces(text: str) -> str:
    return re.sub(r"[^\n]", " ", text)


def _blank(pattern: re.Pattern[str], text: str, only_if: Callable[[re.Match[str]], bool] | None = None) -> str:
    """Put spaces over each match, or over its `hide` group, so line numbers and columns stay true."""
    group = "hide" if "hide" in pattern.groupindex else 0

    def cover(found: re.Match[str]) -> str:
        start, end = (edge - found.start() for edge in found.span(group))
        whole = found.group()
        return whole if only_if and not only_if(found) else whole[:start] + _spaces(whole[start:end]) + whole[end:]

    return pattern.sub(cover, text)


def _starts_item(found: re.Match[str]) -> bool:
    """True when a number at the start of a line begins a list item, not a wrapped line of a paragraph.

    As in the markdown rules, only a list that starts with 1 can interrupt a paragraph. So the number
    counts as list numbering after a blank line or a heading, after the list item before it, when the
    line steps back out of an indent, or when it is 1.
    """
    end = max(found.start() - 1, 0)
    before = found.string[found.string.rfind("\n", 0, end) + 1:end]
    lead, mine = len(before) - len(before.lstrip(" \t>")), found.start("hide") - found.start()
    sibling = mine == lead and EXEMPT["list number"].match(before) is not None
    return (found["hide"][:-1] == "1" or not before.strip() or before.lstrip().startswith("#") or mine < lead
            or sibling)


#: An exemption that also depends on the lines around the match.
_ONLY_IF: dict[str, Callable[[re.Match[str]], bool]] = {"list number": _starts_item}


def _line(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def _blank_code(text: str) -> str:
    """The text with fenced code blocks and inline code spans blanked out.

    A code span that sits right before a tag is kept: it is the cited number, written as code.
    """
    lines, fence = [], ""
    for line in text.split("\n"):
        mark = _FENCE.match(line)
        closes = bool(fence) and line.strip().startswith(fence) and not line.strip().strip(fence[0])
        if fence or mark:
            lines.append(" " * len(line))
            fence = "" if closes else fence or mark[1]
        else:
            lines.append(line)
    text = "\n".join(lines)

    def span(found: re.Match[str]) -> str:
        keep = "<!--" not in found.group() and _CITED.match(text, found.end())
        return found.group() if keep else _spaces(found.group())

    return _CODE.sub(span, text)


def _read(text: str) -> tuple[list[Tag], str]:
    """Every tag, and the text with code, the tagged numbers and HTML comments blanked out."""
    text = _blank_code(text)
    tags, chars = [], list(text)
    for found in TAG.finditer(text):
        start = text.rfind("\n", 0, found.start()) + 1
        before = _BEFORE.search(text[start:found.start()])
        if before:
            first, last = (start + edge for edge in before.span("number"))
            chars[first:last] = " " * (last - first)
        number = before["number"] if before else None
        tags.append(Tag(_line(text, found.start()), found["work"], found["key"], found["flag"], number))
    for found in RECEIPT.finditer(text):  # a receipt tag covers every number before it on its line
        start = text.rfind("\n", 0, found.start()) + 1
        for number in _BARE.finditer(text, start, found.start()):
            chars[number.start():number.end()] = " " * (number.end() - number.start())
    for prefix in sorted(CITATIONS):  # a pack's own citation: the number right before it is cited
        for found in re.finditer(r"<!--\s*" + re.escape(prefix) + r":[^>]*?-->", text):
            start = text.rfind("\n", 0, found.start()) + 1
            before = _BEFORE.search(text[start:found.start()])
            if before:
                first, last = (start + edge for edge in before.span("number"))
                chars[first:last] = " " * (last - first)
    return tags, _blank(_COMMENT, "".join(chars))


#: Citation prefixes that packs have registered. Each must have a rule that checks its numbers:
#: a prefix nothing verifies would let any number escape by wearing its tag.
CITATIONS: set[str] = set()


def register_citation(prefix: str) -> None:
    """Tell the claims gate that `<!--PREFIX:...-->` after a number is a citation another rule
    verifies. Called by the pack whose rule does the verifying."""
    if not re.fullmatch(r"[a-z]", prefix) or prefix in ("t", "d", "r"):
        raise ValueError("a pack's citation prefix is one lower-case letter the core does not use")
    CITATIONS.add(prefix)


@dataclass(frozen=True)
class ReceiptTag:
    """A `<!--r:KIND/NAME-->` tag: its line, the receipt it names, and the numbers it stands for."""

    line: int
    kind: str
    name: str
    numbers: tuple[str, ...]


def find_receipt_tags(text: str) -> list[ReceiptTag]:
    """Every receipt citation outside code, with the numbers written before it on its line.

    Dates, times, ids and the other exempt forms on that line are not counted as its numbers.
    """
    text = _blank_code(text)
    found = []
    for tag in RECEIPT.finditer(text):
        start = text.rfind("\n", 0, tag.start()) + 1
        segment = _blank(_COMMENT, text[start:tag.start()])
        for name, pattern in EXEMPT.items():
            segment = _blank(pattern, segment, _ONLY_IF.get(name))
        numbers = tuple(number.group() for number in _BARE.finditer(segment))
        found.append(ReceiptTag(_line(text, tag.start()), tag["kind"], tag["name"], numbers))
    return found


def find_tags(text: str) -> list[Tag]:
    """Every `<!--t:WORK#KEY-->` tag outside code, with the number written right before it."""
    return _read(text)[0]


def find_decisions(text: str) -> list[tuple[int, str]]:
    """Every `<!--d:WORK-->` tag outside code: its line, and the work whose decision it cites."""
    text = _blank_code(text)
    return [(_line(text, found.start()), found["work"]) for found in DECISION.finditer(text)]


def untagged_numbers(text: str) -> list[tuple[int, str]]:
    """Each bare number that has no tag after it, with its line, once everything exempt is set aside."""
    text = _read(text)[1]
    for name, pattern in EXEMPT.items():
        text = _blank(pattern, text, _ONLY_IF.get(name))
    return [(_line(text, found.start()), found.group()) for found in _BARE.finditer(text)]


def _heading(text: str) -> str:
    """A heading's text as it is compared: no numbering, no emphasis marks, case and spacing ignored."""
    text = re.sub(r"^\d+(?:\.\d+)*[.)][ \t]+", "", text.strip())
    return " ".join(re.sub(r"[*_`]", "", text).split()).casefold()


def governed_lines(text: str, sections: Iterable[str] | None = None) -> set[int]:
    """The numbers of the governed lines: every line, or only those under the `#` headings named.

    A section holds its heading's own line and runs to the next heading of the same depth or a
    shallower one, so it keeps its sub-sections.
    """
    lines = _blank_code(text).split("\n")
    if not sections:
        return set(range(1, len(lines) + 1))
    wanted = {_heading(name) for name in sections}
    found: set[int] = set()
    depth = 0  # the depth of the governed heading we are under; 0 when under none
    for number, line in enumerate(lines, start=1):
        heading = _HEADING.match(line)
        if heading:
            if depth and len(heading[1]) <= depth:
                depth = 0
            if not depth and _heading(heading[2]) in wanted:
                depth = len(heading[1])
        if depth:
            found.add(number)
    return found


def find_links(text: str) -> list[tuple[int, str]]:
    """Each markdown link target outside code, with its line: `[text](target)`, an image, or `[label]: target`."""
    text = _blank(_COMMENT, _blank_code(text))
    found = [
        (link.start(), link["angle"] if link["angle"] is not None else link["plain"])
        for pattern in (_LINK, _DEFINITION)
        for link in pattern.finditer(text)
    ]
    return [(_line(text, position), target) for position, target in sorted(found)]


def link_path(document: str, target: str) -> str | None:
    """The repository path a link in that document points at, resolved from the document's folder.

    None when the link is not to a file here: a web or mail address, or an anchor in the same page.
    A path that leaves the repository comes back starting with `..`.
    """
    target = target.strip()
    if _SCHEME.match(target):
        return None
    path = unquote(re.split(r"[#?]", target, maxsplit=1)[0])
    if not path:
        return None
    base = "" if path.startswith("/") else posixpath.dirname(document)
    resolved = posixpath.normpath(posixpath.join(base, path.lstrip("/")))
    return "" if resolved == "." else resolved


def line_text(text: str, line: int) -> str:
    """What a reader sees on that line: the line without its HTML comments."""
    lines = text.split("\n")
    return _COMMENT.sub(" ", lines[line - 1]) if 0 < line <= len(lines) else ""


def has_word(text: str, word: str) -> bool:
    """True when the text holds the word on its own: not inside a longer word, a number, a date or a time.

    A version may be written with a `v` before it, so `v2` holds the word `2`.
    """
    word = word.strip()
    if not word:
        return False
    if EXEMPT["date"].fullmatch(word):
        return re.search(r"(?<![\w.])" + re.escape(word) + r"(?!\d)", text) is not None
    text = _blank(EXEMPT["time"], _blank(EXEMPT["date"], text))
    return re.search(r"(?<![\w.#])[vV]?" + re.escape(word) + r"(?!\w|[.,]\d)", text, re.I) is not None


def date_of(stamp: str) -> str | None:
    """The YYYY-MM-DD at the start of a date or a time stamp, or None when it does not start with one."""
    found = re.match(_DATE + r"(?!\d)", stamp.strip())
    return found.group() if found else None


# -- the records a tag names --------------------------------------------------------------------


def folder_name(folder: str) -> str:
    """The name a tag uses for a unit of work: the last segment of its folder."""
    return folder.strip("/").rsplit("/", 1)[-1]


class UnitNames(dict):
    """Name -> unit folder: each unit by its whole path, and by its folder name when no other unit
    has that folder name. `shared` holds each folder name several units have, with those units."""

    def __init__(self, units: Iterable[str]) -> None:
        units = sorted(units)
        super().__init__({unit.strip("/"): unit for unit in units})
        held: dict[str, list[str]] = {}
        for unit in units:
            held.setdefault(folder_name(unit), []).append(unit)
        self.shared = {name: found for name, found in held.items() if len(found) > 1}
        for name, found in held.items():
            if len(found) == 1:
                self.setdefault(name, found[0])

    def unit(self, work: str) -> str:
        """The unit a tag names. Raises ValueError, saying why, when it names none or names a folder
        name several units share."""
        if work.strip("/") in self:
            return self[work.strip("/")]
        if work in self.shared:
            raise ValueError(f"the folder name {work} is shared by {', '.join(self.shared[work])}: name the unit "
                             "by its whole path, such as " + self.shared[work][0].strip("/"))
        raise ValueError(f"no unit of work has the folder name {work}, nor has it as its path")


def unit_names(units: Iterable[str]) -> UnitNames:
    """Each name a tag may use for a unit: its whole path, or its folder name when no other unit
    shares it. Units that share a folder name are named by their paths, and only a tag that uses
    the shared name is wrong."""
    return UnitNames(units)


def _load(root: Path, unit_folder: str, inner: str, what: str) -> tuple[str, dict[str, Any]]:
    """A JSON object kept inside a unit, with its repository path. Raises ValueError with a plain reason."""
    name = f"{unit_folder.strip('/')}/{inner.strip('/')}"
    if ".." in name.split("/"):
        raise ValueError(f"the {what} file {name} points outside its unit")
    path = Path(root) / name
    if not path.is_file():
        raise ValueError(f"the {what} file {name} is missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError(f"the {what} file {name} cannot be read as JSON") from None
    if not isinstance(data, dict):
        raise ValueError(f"the {what} file {name} is not a JSON object")
    return name, data


def _exact(value: Any) -> Decimal | None:
    """The number as its file shows it, or None when it is not a finite number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return Decimal(repr(value))


def load_metrics(root: Path, unit_folder: str, metrics_path: str) -> dict[str, float]:
    """A unit's metrics, key -> number. Raises ValueError when the file is missing or unreadable.

    A metric is a bare number, `"uplift": 3.7`, or a table, `"uplift": {"value": 3.7, "unit": "pp"}`.
    An entry that holds no finite number is not a metric and is left out.
    """
    _, data = _load(root, unit_folder, metrics_path, "metrics")
    found = {}
    for key, entry in data.items():
        value = entry.get("value") if isinstance(entry, dict) else entry
        if _exact(value) is not None:
            found[key] = value
    return found


def resolve(root: Path, names: Mapping[str, str], work: str, key: str, metrics_path: str) -> float:
    """The number a tag names. `names` is what `unit_names` returns.

    Raises ValueError with a plain reason when the unit, its metrics file or the key cannot be found.
    """
    unit = names.unit(work) if isinstance(names, UnitNames) else names.get(work)
    if unit is None:
        raise ValueError(f"no unit of work has the folder name {work}")
    metrics = load_metrics(root, unit, metrics_path)
    if key not in metrics:
        raise ValueError(f"the metrics of {work} hold no number under the key {key}")
    return metrics[key]


def load_provenance(root: Path, unit_folder: str, provenance_path: str) -> dict[str, str]:
    """A unit's fingerprint: each input's repository path -> the sha256 it had when the result was made.

    The file holds `{"inputs": {"<repo path>": "<sha256>"}}`. Raises ValueError when it is missing or
    unreadable.
    """
    name, data = _load(root, unit_folder, provenance_path, "provenance")
    inputs = data.get("inputs")
    if not isinstance(inputs, dict) or not all(isinstance(digest, str) for digest in inputs.values()):
        raise ValueError(f"the provenance file {name} has no `inputs` table of path to sha256")
    return dict(inputs)


def changed_inputs(root: Path, unit_folder: str, provenance_path: str) -> list[str]:
    """The inputs of a unit that no longer match the sha256 its provenance file holds for them.

    An input that is not in the repository, such as data kept elsewhere, cannot be compared and is
    skipped. Raises ValueError when the file is missing or unreadable, or when no input it lists is
    in the repository: then nothing was compared, and that is not a pass.
    """
    checked, changed = 0, []
    for name, recorded in sorted(load_provenance(root, unit_folder, provenance_path).items()):
        path = Path(root) / name
        if Path(name).is_absolute() or ".." in Path(name).parts or not path.is_file():
            continue
        checked += 1
        try:
            now = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            now = "unreadable"
        if now != recorded.strip().lower().removeprefix("sha256:"):
            changed.append(name)
    if not checked:
        raise ValueError(f"no input listed for {unit_folder} is in the repository, so nothing can be compared")
    return changed


# -- comparing and writing a number -------------------------------------------------------------


def _written(text: str) -> Decimal | None:
    """The number a document shows, or None when the text is not a number."""
    try:
        shown = Decimal(text.strip().replace(",", "").replace("\u2212", "-"))
    except InvalidOperation:
        return None
    return shown if shown.is_finite() else None


def matches(written: str, value: float) -> bool:
    """True when the metric, rounded to the number of decimals the document shows, is the written number.

    `3.7` matches 3.6953 and does not match 3.76. `23,656` matches 23656. The sign counts. A value
    that sits exactly half way may be rounded either way, so an honest number is never refused.
    """
    shown, exact = _written(written), _exact(value)
    if shown is None or exact is None:
        return False
    places = max(0, -int(shown.as_tuple().exponent))
    step = Decimal(1).scaleb(-places)
    try:
        rounded = {exact.quantize(step, rounding=mode, context=_WIDE) for mode in (ROUND_HALF_UP, ROUND_HALF_EVEN)}
    except InvalidOperation:
        return False
    if isinstance(value, float):
        rounded.add(Decimal(format(value, f".{places}f")))  # how the usual number formatting rounds
    return shown in rounded


def format_number(value: float, decimals: int | None = None) -> str:
    """The number as a document should show it, with no exponent. Half rounds up.

    With `decimals`, exactly that many. Without, the number's own precision: up to four decimals,
    or four significant ones for a number below 1, with trailing zeros dropped.
    """
    exact = _exact(value)
    if exact is None:
        raise ValueError(f"{value!r} is not a finite number")
    if decimals is not None and decimals < 0:
        raise ValueError("decimals cannot be below zero")
    places = decimals if decimals is not None else 4 + max(0, -exact.adjusted() - 1)
    rounded = exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP, context=_WIDE)
    text = format(abs(rounded) if rounded.is_zero() else rounded, "f")
    return text.rstrip("0").rstrip(".") if decimals is None and "." in text else text


def cite(root: Path, units: Mapping[str, Any], work: str, key: str, metrics_path: str,
         decimals: int | None = None) -> str:
    """The formatted number followed by its tag, ready to paste: `3.7<!--t:open-drive#uplift_half_stop-->`.

    `units` holds the unit folders, as `themis.work.units` returns them. `work` is a unit's folder
    name, or its whole path when another unit has the same folder name. Raises ValueError when the
    work or the key is unknown, or the metrics cannot be read.
    """
    value = resolve(root, unit_names(units), work, key, metrics_path)
    for name, pattern in ((work.strip("/"), _WORK), (key, _NAME)):
        if not re.fullmatch(pattern, name):
            raise ValueError(f"{name!r} cannot be written in a tag; a tag holds letters, digits, `_`, `.` and `-`, "
                             "and `/` between the folders of a unit's path")
    work = work.strip("/")
    return f"{format_number(value, decimals)}<!--t:{work}#{key}-->"
