"""An addition is not a weakening: a new table, entry or check adds to what is checked.

A removal is still a weakening, and so is a first start date, a new test skip, a home moved, and
any value changed whose direction nothing states.
"""

from __future__ import annotations

import pytest

from themis import configguard, gates
from themis.cli import EXIT_FAIL, EXIT_PASS, main
from themis.proofs import World, judge

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
        # a key added to a table that was there, which no pack gives a direction
        ({"field": {"windows": {"oos": {"from": "2025-01-01"}}}},
         {"field": {"windows": {"oos": {"from": "2025-01-01", "sealed": True}}}}, "weakening"),
        ({"agents": {"host": "claude"}}, {"agents": {"host": "claude", "git_hooks": "elsewhere"}}, "weakening"),
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


# -- a value is compared with what was in force before it ---------------------------------------

TRADING = {"project": {"packs": ["trading"]}, "trading": {"work": "work/*"}}
SEALED = {"project": {"packs": ["trading"]},
          "trading": {"work": "work/*", "windows": {"holdout": {"from": "2022-01-01", "to": "2024-12-31",
                                                                "sealed": True}}}}


def _with_rule(base: dict, rule_id: str, **params: object) -> dict:
    return {**base, "rules": {rule_id: {"level": "warn", **params}}}


@pytest.mark.parametrize(
    ("base", "rule_id", "params", "kind"),
    [
        # the pack set work for order/sealed-first; a stated work that replaces it moves it elsewhere
        (TRADING, "order/sealed-first", {"work": "elsewhere/*"}, "weakening"),
        (TRADING, "order/sealed-first", {"work": ["work/*", "lab/*"]}, "tightening"),
        # a sealed window makes the pack guard `holdout`; a guarded list without it drops that guard
        (SEALED, "grant/required", {"guarded": ["deploy"]}, "weakening"),
        (SEALED, "grant/required", {"guarded": ["holdout", "deploy"]}, "tightening"),
    ],
)
def test_a_stated_parameter_is_compared_with_what_its_pack_had_set(tmp_path, base: dict, rule_id: str,
                                                                   params: dict, kind: str) -> None:
    old = {**base, "rules": {rule_id: "warn"}}
    new = _with_rule(base, rule_id, **params)
    assert {change.kind for change in configguard.classify(old, new, tmp_path)} == {kind}


def test_with_no_root_only_the_rules_own_defaults_count(tmp_path) -> None:
    """The pack's defaults may read the project's files, so they need the root."""
    old, new = TRADING, _with_rule(TRADING, "order/sealed-first", work="elsewhere/*")
    assert {change.kind for change in configguard.classify(old, new)} == {"tightening"}
    assert {change.kind for change in configguard.classify(old, new, tmp_path)} == {"weakening"}


# -- a pack states which way each key of its table tightens -------------------------------------

WINDOW = {"from": "2022-01-01", "to": "2024-12-31", "sealed": True}
COST = {"toll_per_side": 0.1, "derivation": "work/cost-study"}


def _trading(**table: object) -> dict:
    return {"project": {"packs": ["trading"]}, "trading": {"work": "work/*", **table}}


@pytest.mark.parametrize(
    ("old", "new", "kind"),
    [
        (_trading(), _trading(windows={"holdout": WINDOW}), "tightening"),  # a new window adds a check
        (_trading(windows={"holdout": WINDOW}), _trading(windows={"holdout": {**WINDOW, "looks": 3}}), "weakening"),
        (_trading(windows={"holdout": {**WINDOW, "looks": 2}}), _trading(windows={"holdout": WINDOW}), "tightening"),
        (_trading(windows={"holdout": {**WINDOW, "sealed": False}}), _trading(windows={"holdout": WINDOW}),
         "tightening"),
        (_trading(windows={"holdout": WINDOW}), _trading(windows={"holdout": {**WINDOW, "to": "2025-12-31"}}),
         "weakening"),
        (_trading(studies={"work/a": {"windows": {"oos": WINDOW}}}),
         _trading(studies={"work/a": {"windows": {"oos": {**WINDOW, "looks": 2}}}}), "weakening"),
        (_trading(tune={"iterations": 50}), _trading(tune={"iterations": 50, "confirm_model": "real ticks"}),
         "tightening"),
        (_trading(tune={"confirm_model": "real ticks"}), _trading(tune={"confirm_model": "open prices"}), "weakening"),
        (_trading(tune={"confirm_model": "real ticks"}),
         _trading(tune={"confirm_model": "real ticks", "iterations": 50}), "tightening"),
        (_trading(tune={"iterations": 50}), _trading(tune={"iterations": 80}), "weakening"),
        (_trading(costs={"example": COST}), _trading(costs={"example": {**COST, "spread": 0.0}}), "weakening"),
        (_trading(costs={"example": COST}), _trading(costs={"example": {**COST, "toll_per_side": 0.0}}), "weakening"),
        ({"project": {"packs": ["trading"]}}, _trading(windows={"holdout": WINDOW}, costs={"example": COST},
                                                       tune={"confirm_model": "real ticks"}), "tightening"),
        (_trading(), {"project": {"packs": ["trading"]}, "trading": {"work": ["work/*", "lab/*"]}}, "tightening"),
        ({"project": {"packs": ["trading"]}, "trading": {"work": ["work/*", "lab/*"]}}, _trading(), "weakening"),
        ({"project": {"packs": ["marketing"]}, "marketing": {"work": "items/*"}},
         {"project": {"packs": ["marketing"]}, "marketing": {"work": "items/*", "results": {"min_items_to_judge": 1}}},
         "weakening"),  # a new table that lowers a minimum below the pack's default
        ({"project": {"packs": ["marketing"]}, "marketing": {"work": "items/*"}},
         {"project": {"packs": ["marketing"]}, "marketing": {"work": "items/*", "results": {"min_items_to_judge": 5}}},
         "tightening"),
        ({"project": {"packs": ["marketing"]}, "marketing": {"evidence": {"tiers": ["official"]}}},
         {"project": {"packs": ["marketing"]}, "marketing": {"evidence": {"tiers": ["official", "vendor"]}}},
         "weakening"),  # a set that allows, grown
        # a table no pack describes: one pattern and a list of patterns are the same set
        ({"field": {"work": "a/*"}}, {"field": {"work": ["a/*", "b/*"]}}, "tightening"),
        ({"field": {"work": ["a/*", "b/*"]}}, {"field": {"work": "b/*"}}, "weakening"),
    ],
)
def test_each_key_of_a_pack_table_moves_its_own_way(old: dict, new: dict, kind: str) -> None:
    assert {change.kind for change in configguard.classify(old, new)} == {kind}, configguard.classify(old, new)


def test_a_key_set_to_its_default_or_a_pattern_made_a_list_of_one_is_no_change() -> None:
    assert configguard.classify(_trading(windows={"holdout": WINDOW}),
                                _trading(windows={"holdout": {**WINDOW, "looks": 1}})) == []
    assert configguard.classify({"field": {"work": "a/*"}}, {"field": {"work": ["a/*"]}}) == []


# -- in a scratch world: a plain docs-and-scripts project with a local pack ---------------------

NOTES_PACK = '''
from themis.pack import Pack

pack = Pack(name="{name}", schema={{"work": str}})


def _defaults(manifest):
    work = manifest.table("{name}").get("work")
    return {{"order/sealed-first": {{"work": work, "seal": ["PLAN.md"], "results": ["out/**"]}}}} if work else {{}}


pack.defaults = _defaults
'''


def _notes(tmp_path, name: str, rule: str) -> tuple[World, int]:
    """A project whose local pack sets order/sealed-first, with this rule table stated on a branch."""
    world = World(tmp_path / name)
    world.root.mkdir()
    world.write("notes/__init__.py", NOTES_PACK.format(name=name))
    manifest = f'[project]\nname = "docs"\nlocal_pack = "notes"\n\n[{name}]\nwork = "scripts/*"\n'
    world.manifest(manifest + '\n[rules]\n"order/sealed-first" = "warn"\n')
    world.write(".gitignore", "__pycache__/\n.themis/\n")
    world.write("README.md", "# Scripts\n")
    world.write("scripts/build/PLAN.md", "build the site\n")
    world.commit("start")
    world.branch("change")
    world.manifest(manifest + f'\n[rules."order/sealed-first"]\n{rule}\n')
    world.commit("the change")
    return world, main(["config", "diff", "--root", str(world.root)])


def test_replacing_what_a_local_pack_set_is_a_weakening_and_widening_it_is_not(tmp_path, capsys) -> None:
    world, code = _notes(tmp_path, "notesa", 'work = "elsewhere/*"\nseal = ["PLAN.md"]\nresults = ["out/**"]')
    assert code == EXIT_FAIL and "order/sealed-first: work 'scripts/*' to 'elsewhere/*'" in capsys.readouterr().out
    assert judge(world.root, "config/no-silent-weakening").verdict.value == "fail"
    world, code = _notes(tmp_path, "notesb", 'work = ["scripts/*", "docs/*"]\nseal = ["PLAN.md"]\nresults = ["out/**"]')
    assert code == EXIT_PASS and "Tightened only." in capsys.readouterr().out
    assert judge(world.root, "config/no-silent-weakening").verdict.value == "pass"
