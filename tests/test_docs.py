"""The documents name the rules that exist, in the words the code uses.

A catalogue kept by hand drifts from the rules it lists. So each document's rule tables are held
to the code: every rule of the pack has a row, no row names a rule that does not exist, and the
promise in the row is the rule's own.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from themis import gates, pack
from themis.rule import RULES

ROOT = Path(__file__).resolve().parents[1]
ROW = re.compile(r"^\| `([a-z-]+/[a-z-]+)` \| (.*?) \|")
DOCUMENTS = {"core": "DESIGN.md", "trading": "docs/packs/trading.md", "marketing": "docs/packs/marketing.md"}

gates.load_all()
for name in ("trading", "marketing"):
    pack.load(name)


def rows(owner: str) -> list[tuple[str, str]]:
    """Every table row of the document that starts with a rule id, as (id, the next cell)."""
    lines = (ROOT / DOCUMENTS[owner]).read_text(encoding="utf-8").splitlines()
    return [(found.group(1), found.group(2)) for found in map(ROW.match, lines) if found]


@pytest.mark.parametrize("owner", DOCUMENTS)
def test_the_document_has_a_row_for_every_rule_of_its_pack(owner: str) -> None:
    listed = {rule_id for rule_id, _ in rows(owner)}
    missing = sorted(rule.id for rule in RULES.values() if rule.pack == owner and rule.id not in listed)
    assert not missing, f"{DOCUMENTS[owner]} has no row for: {', '.join(missing)}"


@pytest.mark.parametrize("owner", DOCUMENTS)
def test_the_document_names_no_rule_that_does_not_exist(owner: str) -> None:
    unknown = sorted({rule_id for rule_id, _ in rows(owner) if rule_id not in RULES})
    assert not unknown, f"{DOCUMENTS[owner]} names rules that are not registered: {', '.join(unknown)}"


@pytest.mark.parametrize("owner", DOCUMENTS)
def test_each_rules_promise_in_the_document_is_the_rules_own(owner: str) -> None:
    first: dict[str, str] = {}
    for rule_id, cell in rows(owner):
        if rule_id in RULES and RULES[rule_id].pack == owner:
            first.setdefault(rule_id, cell)
    wrong = [f"{rule_id}: the document says {cell!r}, the rule says {RULES[rule_id].promise!r}"
             for rule_id, cell in sorted(first.items()) if cell != RULES[rule_id].promise]
    assert not wrong, "\n".join(wrong)


def test_the_design_counts_the_core_rules_and_gates_as_they_are() -> None:
    core = [rule.id for rule in RULES.values() if rule.pack == "core"]
    rules, gates_ = len(core), len({rule_id.split("/")[0] for rule_id in core})
    ones = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    rules_said = {4: "Forty", 5: "Fifty", 6: "Sixty"}[rules // 10] + (f"-{ones[rules % 10]}" if rules % 10 else "")
    gates_said = ["fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"][gates_ - 14]
    assert f"{rules_said} rules in {gates_said} gates" in (ROOT / "DESIGN.md").read_text(encoding="utf-8")
