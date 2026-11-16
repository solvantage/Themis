"""Packs: how they are found, what the kit demands of them, and how a standard is held."""

from __future__ import annotations

from pathlib import Path

import pytest

from themis import engine, pack, standards
from themis import manifest as manifests
from themis.pack import Pack, kit
from themis.proofs import World
from themis.verdict import Verdict

#: A local pack with one proven rule, one gate with both calibration cases, and a standard.
GOOD_PACK = '''
from themis.pack import Pack, Standard
from themis.rule import Param, proof, rule

pack = Pack(name="{name}", schema={{"limit": int}})
pack.standards["{name}/1"] = Standard(
    "{name}/1", levels={{"{name}/short-notes": "enforce"}}, floors={{"{name}/short-notes": {{"max_lines": 5}}}},
)
pack.defaults = lambda manifest: {{"{name}/short-notes": {{"max_lines": manifest.table("{name}").get("limit", 5)}}}}


@rule("{name}/short-notes", "The notes file stays short.", pack="{name}",
      params=(Param("max_lines", int, 5, "lower", "the most lines the notes may hold"),))
def short_notes(ctx):
    text = ctx.read("notes.md")
    if text is None:
        ctx.refuse("there is no notes.md")
        return
    ctx.inspect()
    if len(text.splitlines()) > ctx.param("max_lines"):
        ctx.breach("the notes are too long", where="notes.md", fix="shorten them")


@proof("{name}/short-notes", "short notes", expect="pass")
def _(world):
    world.manifest('[project]\\npacks = []\\n')
    world.write("notes.md", "one\\n")


@proof("{name}/short-notes", "long notes", expect="fail", contains="too long")
def _(world):
    world.write("notes.md", "line\\n" * 9)


@pack.gate("threshold", version="2")
def threshold(metrics):
    return {{"decision": "keep" if metrics["score"] > 1 else "drop", "verdict": "pass" if metrics["score"] > 1 else "fail"}}


@pack.calibration("threshold", "noise", "scores of zero")
def _():
    return 0.0


@pack.calibration("threshold", "planted", "scores of two")
def _():
    return 1.0
'''


def project(tmp_path: Path, name: str, manifest: str, source: str = GOOD_PACK) -> World:
    world = World(tmp_path / "repo")
    world.root.mkdir(parents=True)
    world.write("pack/__init__.py", source.format(name=name))
    world.manifest(f'[project]\nlocal_pack = "pack"\n{manifest}')
    return world


def test_a_local_pack_adds_its_rules_its_table_and_its_defaults(tmp_path: Path) -> None:
    world = project(tmp_path, "alpha", "\n[alpha]\nlimit = 2\n")
    world.write("notes.md", "one\ntwo\nthree\n")
    manifest = manifests.load(world.root)
    assert manifest.problems == []
    result = next(r for r in engine.run(manifest).results if r.id == "alpha/short-notes")
    assert result.verdict is Verdict.FAIL  # three lines against the pack's own limit of two


def test_a_packs_table_is_read_as_strictly_as_the_rest(tmp_path: Path) -> None:
    world = project(tmp_path, "beta", "\n[beta]\nlimmit = 2\n")
    assert any("beta.limmit is not a known key" in problem for problem in manifests.load(world.root).problems)


def test_a_rule_of_a_pack_that_is_not_turned_on_is_unknown(tmp_path: Path) -> None:
    project(tmp_path / "a", "gamma", "")  # registers gamma's rule in this process
    other = World(tmp_path / "b")
    other.root.mkdir(parents=True)
    other.manifest('[rules]\n"gamma/short-notes" = "enforce"\n')
    manifests.load(tmp_path / "a" / "repo")
    assert any("is not a rule Themis knows" in problem for problem in manifests.load(other.root).problems)


def test_an_unknown_pack_and_an_unpublished_standard_are_problems(tmp_path: Path) -> None:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest('[project]\npacks = ["no-such-pack"]\n')
    assert any("no pack named" in problem for problem in manifests.load(world.root).problems)
    world.manifest('[project]\nstandard = "nobody/1"\n')
    assert any("published by no pack" in problem for problem in manifests.load(world.root).problems)


def test_a_project_below_its_standard_is_listed_as_deviating(tmp_path: Path) -> None:
    rules = '\n[rules."delta/short-notes"]\nlevel = "warn"\nmax_lines = 9\n'
    world = project(tmp_path, "delta", 'standard = "delta/1"\n' + rules)
    manifest = manifests.load(world.root)
    found = standards.deviations(manifest, standards.declared(manifest))
    assert [deviation.what for deviation in found] == [
        "level is warn; the standard requires enforce", "max_lines = 9; the floor is 5",
    ]


def test_a_project_tighter_than_its_standard_conforms(tmp_path: Path) -> None:
    rules = '\n[rules."epsilon/short-notes"]\nlevel = "enforce"\nmax_lines = 3\n'
    world = project(tmp_path, "epsilon", 'standard = "epsilon/1"\n' + rules)
    manifest = manifests.load(world.root)
    assert standards.deviations(manifest, standards.declared(manifest)) == []


# --- the kit -----------------------------------------------------------------------------------


def loaded(tmp_path: Path, name: str, source: str = GOOD_PACK) -> Pack:
    world = project(tmp_path, name, "", source)
    manifest = manifests.load(world.root)
    assert manifest.problems == [], manifest.problems
    return manifest.packs[0]


def test_a_complete_pack_passes_the_kit(tmp_path: Path) -> None:
    assert kit.problems(loaded(tmp_path, "zeta")) == []


@pytest.mark.parametrize(
    ("name", "old", "new", "said"),
    [
        ("eta", 'expect="fail", contains="too long"', 'expect="pass"', "unproven: no planted fault"),
        ("theta", '"lower", "the most lines the notes may hold"', '"lower", ""', "has no line of help"),
        ("iota", '"The notes file stays short."', '"The notes file stays short"', "one full sentence"),
        ("kappa", '@pack.calibration("threshold", "noise", "scores of zero")', '@pack.calibration("threshold", "planted", "more")',
         "never shown to say no"),
        ("lam", 'floors={{"{name}/short-notes": {{"max_lines": 5}}}}', 'floors={{"{name}/short-notes": {{"max_words": 5}}}}',
         "has no parameter max_words"),
        ("mu", 'levels={{"{name}/short-notes": "enforce"}}', 'levels={{"{name}/no-such-rule": "enforce"}}', "there is no rule"),
    ],
)
def test_the_kit_names_each_way_a_pack_falls_short(tmp_path: Path, name: str, old: str, new: str, said: str) -> None:
    assert GOOD_PACK.count(old) == 1
    found = kit.problems(loaded(tmp_path, name, GOOD_PACK.replace(old, new)))
    assert any(said in problem for problem in found), found


def test_prove_fails_a_project_whose_pack_falls_short_of_the_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from themis.cli import EXIT_FAIL, EXIT_PASS, main

    good = project(tmp_path / "good", "omicron", "")
    assert main(["prove", "--root", str(good.root)]) == EXIT_PASS
    weak = project(tmp_path / "weak", "pi", "", GOOD_PACK.replace('"The notes file stays short."',
                                                                    '"The notes file stays short"'))
    assert main(["prove", "--root", str(weak.root)]) == EXIT_FAIL
    assert "the pack pi falls short of the pack contract" in capsys.readouterr().out


def test_calibration_reports_the_worst_case_of_each_kind(tmp_path: Path) -> None:
    measured = kit.calibrate(loaded(tmp_path, "nu"), "threshold")
    assert (measured["false_alarm_rate"], measured["power"], measured["gate_version"]) == (0.0, 1.0, "2")


def test_a_local_pack_must_define_a_pack(tmp_path: Path) -> None:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.write("pack/__init__.py", "nothing = 1\n")
    world.manifest('[project]\nlocal_pack = "pack"\n')
    assert any("must define `pack`" in problem for problem in manifests.load(world.root).problems)


def test_every_pack_shipped_with_themis_passes_the_kit() -> None:
    for name in ("trading", "marketing"):
        try:
            shipped = pack.load(name)
        except pack.PackError:
            continue  # not built yet
        assert kit.problems(shipped) == [], name
