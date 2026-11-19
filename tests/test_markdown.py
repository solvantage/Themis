"""Markdown is read as a renderer reads it: code, HTML and prose told apart by CommonMark's rules."""

from __future__ import annotations

import pytest

from themis import markdown


def prose(text: str) -> list[int]:
    return [number for number, _ in markdown.prose_lines(text)]


@pytest.mark.parametrize(
    ("text", "lines"),
    [
        ("<!DOCTYPE html>\nprose\n", [2]),                          # condition 4 ends on its own line
        ("<![CDATA[\n$1 $2\n]]>\nprose\n", [4]),                    # condition 5
        ("<?php\n$1 $2\n?>\nprose\n", [4]),                         # condition 3
        ("<pre>\n$1 $2\n</style>\nprose\n", [4]),                   # condition 1 ends on any raw closing tag
        ("<table>\n<tr>\n\nprose\n", [4]),                          # condition 6 ends at a blank line
        ("text\n<div>\nstill html\n", [1]),                         # condition 6 interrupts a paragraph
        ("text\n<em>\nstill prose\n", [1, 2, 3]),                   # condition 7 does not
        ("<em>\nhtml until the blank\n\nprose\n", [4]),
        ("    code\nprose\n", [2]),
        ("prose\n    lazy text, not code\n", [1, 2]),
        ("```js `x`\nstill prose, not a fence\n", [1, 2]),          # a backtick in a backtick info string
    ],
)
def test_which_lines_are_prose(text: str, lines: list[int]) -> None:
    assert prose(text) == lines


def test_escaping_is_idempotent_and_leaves_single_signs_alone() -> None:
    text = "It made $12 on a $100 stake.\nOne sign: $3.\n`$1 $2` in code.\n"
    once = markdown.escape_dollars(text)
    assert once == "It made \\$12 on a \\$100 stake.\nOne sign: $3.\n`$1 $2` in code.\n"
    assert markdown.escape_dollars(once) == once
    assert markdown.dollar_lines(once) == []


def test_code_spans_are_read_between_matching_runs() -> None:
    assert markdown.code_spans("see `a/b.md`, ``x ` y`` and \\`not/code`") == ["a/b.md", "x ` y"]
    assert markdown.code_spans("an unclosed `run") == []
