"""Reading Markdown the way a renderer does: which lines are prose, and what sits inside them.

A rule that reads pages must not mistake an example for a claim. So code and HTML are told apart
from prose by CommonMark's own rules:

- A fence opens with three or more backticks or tildes, and closes only on a line of the same
  character, at least as long, with nothing after it. A backtick fence whose info string holds a
  backtick is not a fence.
- Indented code (four spaces or a tab) starts only where no paragraph is open and no list goes
  on; inside a list an indented line is the item's text.
- An HTML block starts under one of CommonMark's seven start conditions, and ends under its own
  end condition. The seventh, a whole tag alone on its line, cannot interrupt a paragraph.

Line numbers count `text.split("\\n")`, so a fix can edit the same list it was found in.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
#: Condition 1: raw text, until any of these closing tags.
HTML_RAW = ("script", "pre", "style", "textarea")
#: Condition 6: block tags, until a blank line.
HTML_BLOCK = frozenset("""address article aside base basefont blockquote body caption center col colgroup dd details
    dialog dir div dl dt fieldset figcaption figure footer form frame frameset h1 h2 h3 h4 h5 h6 head header hr html
    iframe legend li link main menu menuitem nav noframes ol optgroup option p param search section summary table
    tbody td tfoot th thead title tr track ul""".split())
HTML_TAG_START = re.compile(r"^ {0,3}<(/?)([A-Za-z][A-Za-z0-9-]*)(?=[\s/>]|$)")
#: Condition 7: one whole opening or closing tag, alone on its line.
HTML_ALONE = re.compile(r"^ {0,3}</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>\s*$")
INDENTED = re.compile(r"^(?: {4}|\t| {0,3}\t)")
LIST_ITEM = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:\s|$)")
ATX = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
BREAK = re.compile(r"^ {0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")
#: An inline tag, an HTML comment or an autolink: what a dollar sign inside it is not.
INLINE_TAG = re.compile(r"<(?:!--.*?--|/?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?|https?://[^<>\s]*)>")

#: An HTML block that runs until a blank line.
UNTIL_BLANK = ("",)


def lines_of(text: str) -> Iterator[tuple[int, str, bool]]:
    """(line number, line, code) for every line: code is True on a fence line and inside a fenced block."""
    opener = None
    for number, line in enumerate(text.split("\n"), 1):
        found = FENCE.match(line)
        if opener is None:
            if found and not (found.group(1)[0] == "`" and "`" in found.group(2)):
                opener = found.group(1)
                yield number, line, True
            else:
                yield number, line, False
        else:
            if (found and found.group(1)[0] == opener[0] and len(found.group(1)) >= len(opener)
                    and not found.group(2).strip()):
                opener = None
            yield number, line, True


def html_block(line: str, no_paragraph: bool) -> tuple[str, ...] | None:
    """How an HTML block that starts on this line ends.

    None when no block starts here; `()` for one that ends on this same line; UNTIL_BLANK for one
    that runs until a blank line; otherwise the texts, any of which ends it on a later line.
    """
    rest = line.lstrip(" ")
    if len(line) - len(rest) > 3 or not rest.startswith("<"):
        return None
    low = rest.lower()
    for start, ends in (("<!--", ("-->",)), ("<![cdata[", ("]]>",)), ("<?", ("?>",))):
        if low.startswith(start):  # conditions 2, 5 and 3
            return () if any(end in low[len(start):] for end in ends) else ends
    if re.match(r"<![a-z]", low):  # condition 4: a declaration, such as <!DOCTYPE html>
        return () if ">" in low[2:] else (">",)
    found = HTML_TAG_START.match(line)
    if not found:
        return None
    name = found.group(2).lower()
    if name in HTML_RAW and not found.group(1):  # condition 1
        ends = tuple(f"</{tag}>" for tag in HTML_RAW)
        return () if any(end in low for end in ends) else ends
    if name in HTML_BLOCK or (no_paragraph and HTML_ALONE.match(line)):  # conditions 6 and 7
        return UNTIL_BLANK
    return None


def prose_lines(text: str) -> Iterator[tuple[int, str]]:
    """(line number, line) for each line rendered as Markdown: not fenced or indented code, not an HTML block."""
    html: tuple[str, ...] | None = None
    paragraph = indented = in_list = False
    after_blank = True
    for number, line, code in lines_of(text):
        blank = not line.strip()
        if html:
            if (html == UNTIL_BLANK and blank) or (html != UNTIL_BLANK and any(end in line.lower() for end in html)):
                html = None
            paragraph = False
        elif code:
            paragraph = indented = False
        elif indented and (blank or INDENTED.match(line)):
            pass
        elif blank:
            indented = paragraph = False
        elif not paragraph and not in_list and INDENTED.match(line):
            indented = True
        else:
            indented = False
            block = html_block(line, not paragraph)
            if block is not None:
                html = block or None
                paragraph = False
            else:
                if LIST_ITEM.match(line):
                    in_list = True
                elif after_blank and not line[:1].isspace():
                    in_list = False
                paragraph = not (ATX.match(line) or BREAK.match(line))
                yield number, line
        after_blank = blank


def _code_end(line: str, start: int) -> tuple[int, int | None]:
    """For the backtick run at `start`: where scanning goes on, and where the span closes (None: no span)."""
    run = len(line[start:]) - len(line[start:].lstrip("`"))
    close = re.compile(r"(?<!`)" + "`" * run + r"(?!`)").search(line, start + run)
    return (close.end(), close.start()) if close else (start + run, None)


def bare_dollars(line: str) -> list[int]:
    """Positions of the dollar signs a renderer could pair into math: not escaped, and not inside a
    code span, an inline tag or a link target."""
    found, index = [], 0
    while index < len(line):
        char = line[index]
        if char == "\\":
            index += 2
            continue
        if char == "`":
            index = _code_end(line, index)[0]
            continue
        if char == "<" and (tag := INLINE_TAG.match(line, index)):
            index = tag.end()
            continue
        if line.startswith("](", index) and (end := line.find(")", index + 2)) != -1:
            index = end + 1
            continue
        if char == "$":
            found.append(index)
        index += 1
    return found


def dollar_lines(text: str) -> list[tuple[int, str]]:
    """(line number, line) for each prose line with two or more bare dollar signs."""
    return [(number, line) for number, line in prose_lines(text) if len(bare_dollars(line)) >= 2]


def escape_dollars(text: str) -> str:
    """The page with each bare dollar sign escaped, on every line that has two or more. Idempotent."""
    lines = text.split("\n")
    for number, line in dollar_lines(text):
        for index in reversed(bare_dollars(line)):
            line = line[:index] + "\\" + line[index:]
        lines[number - 1] = line
    return "\n".join(lines)


def code_spans(line: str) -> list[str]:
    """The text of each inline code span on a line, as written between its backticks, trimmed."""
    found, index = [], 0
    while index < len(line):
        if line[index] == "\\":
            index += 2
        elif line[index] == "`":
            after, close = _code_end(line, index)
            if close is not None:
                run = len(line[index:]) - len(line[index:].lstrip("`"))
                found.append(line[index + run:close].strip())
            index = after
        else:
            index += 1
    return found
