"""A record's frontmatter block, read as `records.frontmatter` reads it."""

from __future__ import annotations

import pytest

from themis import records


def block(*lines: str) -> str:
    return "---\n" + "\n".join(lines) + "\n---\n\nThe text.\n"


def test_a_list_splits_at_its_commas_but_inside_a_quoted_item() -> None:
    held = records.frontmatter(block('reasons: ["news, pause", server restart, \'a, b\']', "days: [30, 61]",
                                     "words: [the owner's call, it's late]", "empty: []"))
    assert held == {"reasons": ["news, pause", "server restart", "a, b"], "days": [30, 61],
                    "words": ["the owner's call", "it's late"], "empty": []}
    # Before 0.3.0 the quoted item split into two, each with a stray quote: the planted miss.
    assert records.frontmatter(block('stop: ["leverage, margin"]')) == {"stop": ["leverage, margin"]}


@pytest.mark.parametrize("line", ['stop: ["leverage, margin]', "stop: ['leverage]"])
def test_a_quote_a_list_item_does_not_close_is_refused(line: str) -> None:
    with pytest.raises(ValueError, match="a list item opens a quote it does not close"):
        records.frontmatter(block(line))
