"""An addition is not a weakening: a new table, entry or check adds to what is checked.

A removal is still a weakening, and so is a first start date, a new test skip, a home moved, and
any value changed whose direction nothing states.
"""

from __future__ import annotations

import pytest

from themis import configguard, gates

gates.load_all()

SKIP = {"test": "tests/test_slow.py::test_all", "reason": "no data here", "until": "2027-01-01"}
ORDER = {"work": "work/*", "seal": ["PLAN.md"], "results": ["results/**"]}


@pytest.mark.parametrize(
    ("old", "new", "kind"),
    [
        # additions
        ({}, {"field": {"work": "research/*"}}, "tightening"),
        ({"field": {"work": "research/*"}}, {"field": {"work": "research/*", "windows": {"oos": {"sealed": True}}}},
         "tightening"),
        ({"field": {"windows": {"oos": {"from": "2025-01-01"}}}},
         {"field": {"windows": {"oos": {"from": "2025-01-01", "sealed": True}}}}, "tightening"),
        ({}, {"views": {"docs/rules.md": "rules"}}, "tightening"),
        ({}, {"agents": {"host": "claude"}}, "tightening"),
        ({}, {"suite": {"command": "pytest -q"}}, "tightening"),
        ({"field": {"lists": ["a"]}}, {"field": {"lists": ["a", "b"]}}, "tightening"),
        ({}, {"rules": {"registry/indexed": {"work": "work/*", "index": "INDEX.md"}}}, "tightening"),
        ({}, {"rules": {"claims/receipt": {"governed": ["docs/**"], "work": "work/*"}}}, "tightening"),
        ({"rules": {"order/sealed-first": ORDER}},
         {"rules": {"order/sealed-first": {**ORDER, "work": ["work/*", "lab/*"]}}}, "tightening"),
        ({"suite": {"command": "pytest", "skips": [SKIP]}}, {"suite": {"command": "pytest"}}, "tightening"),
        # still weakenings
        ({"field": {"work": "research/*"}}, {}, "weakening"),
        ({"field": {"lists": ["a", "b"]}}, {"field": {"lists": ["a"]}}, "weakening"),
        ({"field": {"windows": {"oos": {"sealed": True}}}}, {"field": {"windows": {"oos": {"sealed": False}}}},
         "weakening"),
        ({"field": {"windows": {"oos": {"sealed": True}}}}, {"field": {"windows": {}}}, "weakening"),
        ({"suite": {"command": "pytest"}}, {"suite": {"command": "pytest", "skips": [SKIP]}}, "weakening"),
        ({"suite": {"command": "pytest", "skips": [SKIP]}},
         {"suite": {"command": "pytest", "skips": [{**SKIP, "until": "2099-01-01"}]}}, "weakening"),
        ({}, {"homes": {"ledger": "elsewhere/*.toml"}}, "weakening"),
        ({}, {"rules": {"registry/indexed": {"since": "2027-01-01"}}}, "weakening"),
        ({"rules": {"order/sealed-first": ORDER}},
         {"rules": {"order/sealed-first": {**ORDER, "work": ["lab/*"]}}}, "weakening"),
        ({"rules": {"order/sealed-first": ORDER}},
         {"rules": {"order/sealed-first": {**ORDER, "seal": ["PLAN.md", "README.md"]}}}, "weakening"),
    ],
)
def test_each_addition_and_removal_is_classified(old: dict, new: dict, kind: str) -> None:
    kinds = {change.kind for change in configguard.classify(old, new)}
    assert kinds == {kind}, configguard.classify(old, new)


def test_each_change_inside_a_table_is_named_by_its_place() -> None:
    old = {"field": {"windows": {"oos": {"sealed": True}}}}
    new = {"field": {"windows": {"oos": {"sealed": False}, "late": {"sealed": True}}}}
    said = {change.what: change.kind for change in configguard.classify(old, new)}
    assert said == {"[field.windows.late] added": "tightening",
                    "[field.windows.oos.sealed] changed, and its direction cannot be classified": "weakening"}
