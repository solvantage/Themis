"""The engine, the manifest, the schema, external checks, the configuration guard and the reports."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from themis import configguard, engine, external, reporters, schema
from themis import manifest as manifests
from themis.proofs import World
from themis.schema import ANY, Choice, Either, Required
from themis.verdict import Finding, Verdict, worst


def world(tmp_path: Path, manifest: str = '[project]\nname = "w"\n') -> World:
    built = World(tmp_path / "repo")
    built.root.mkdir(parents=True)
    built.manifest(manifest)
    return built


def check_table(command: list[str], **extra) -> str:
    lines = ["[[checks.external]]", 'id = "ext/check"', 'description = "The check passes"', f"command = {json.dumps(command)}"]
    lines += [f"{key} = {json.dumps(value)}" for key, value in extra.items()]
    return "\n".join(lines) + "\n"


def script(built: World, body: str) -> list[str]:
    built.write("tools/check.py", body)
    return [sys.executable, "tools/check.py"]


# --- verdicts ----------------------------------------------------------------------------------


def test_refuse_outranks_fail_and_fail_outranks_pass() -> None:
    assert worst([Verdict.PASS, Verdict.FAIL]) is Verdict.FAIL
    assert worst([Verdict.FAIL, Verdict.REFUSE, Verdict.PASS]) is Verdict.REFUSE
    assert worst([]) is None


def test_a_finding_always_says_something() -> None:
    with pytest.raises(ValueError):
        Finding("breach", "  ")
    with pytest.raises(ValueError):
        Finding("note", "something")


# --- the schema --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "spec"),
    [
        ("text", str), (3, int), (3, float), (2.5, float), (True, bool), ("warn", Choice("warn", "off")),
        (["a", "b"], [str]), ({"x": 1, "y": 2}, {"*": int}), ({"name": "n"}, {"name": Required(str), "note": str}),
        ("warn", Either(Choice("warn"), {"level": str})), ({"level": "warn"}, Either(Choice("warn"), {"level": str})),
        ({"work": "a", "extra": [1]}, {"work": Required(str), "*": ANY}),
    ],
)
def test_an_honest_value_has_no_problem(value, spec) -> None:
    assert schema.problems(value, spec, "v") == []


@pytest.mark.parametrize(
    ("value", "spec", "said"),
    [
        (3, str, "must be text"), (True, int, "whole number"), ("3", int, "whole number"),
        ("strict", Choice("warn", "off"), "one of warn, off"), ([1], [str], "v[0] must be text"),
        ({"nmae": "n"}, {"name": str}, "v.nmae is not a known key"), ({}, {"name": Required(str)}, "v.name is required"),
        ({"work": 1}, {"work": Required(str), "*": ANY}, "v.work must be text"),
    ],
)
def test_a_wrong_value_is_named_by_its_place(value, spec, said) -> None:
    assert any(said in problem for problem in schema.problems(value, spec, "v"))


# --- levels and the run's verdict --------------------------------------------------------------


def test_a_rule_at_warn_is_shown_and_cannot_fail_the_run(tmp_path: Path) -> None:
    built = world(tmp_path)  # config/locked will fail: there is no lock
    report = engine.run(manifests.load(built.root))
    locked = next(result for result in report.results if result.id == "config/locked")
    assert locked.level == "warn" and locked.verdict is Verdict.FAIL
    assert report.verdict is Verdict.PASS and report.exit_code == 0


def test_an_enforced_rule_decides_the_run(tmp_path: Path) -> None:
    built = world(tmp_path, '[rules]\n"config/locked" = "enforce"\n')
    report = engine.run(manifests.load(built.root))
    assert report.verdict is Verdict.FAIL and report.exit_code == 1


def test_a_rule_that_is_off_does_not_run(tmp_path: Path) -> None:
    built = world(tmp_path, '[rules]\n"config/locked" = "off"\n')
    result = next(r for r in engine.run(manifests.load(built.root)).results if r.id == "config/locked")
    assert result.status == "off" and result.verdict is None


def test_a_rule_without_its_parameters_is_not_configured(tmp_path: Path) -> None:
    built = world(tmp_path)
    result = next(r for r in engine.run(manifests.load(built.root)).results if r.id == "order/sealed-first")
    assert result.status == "not configured" and "work" in result.note


def test_an_invalid_manifest_refuses_and_runs_nothing_else(tmp_path: Path) -> None:
    built = world(tmp_path, '[project]\nnmae = "w"\n')
    report = engine.run(manifests.load(built.root))
    assert report.verdict is Verdict.REFUSE and report.exit_code == 2
    assert [result.id for result in report.results] == ["config/valid"]


def test_a_refusal_outranks_a_failure_in_the_exit_code(tmp_path: Path) -> None:
    built = world(tmp_path, '[rules]\n"config/locked" = "enforce"\n"config/no-silent-weakening" = "enforce"\n')
    report = engine.run(manifests.load(built.root))  # no lock (fail) and no main line (refuse)
    assert report.exit_code == 2


def test_an_empty_inspection_can_be_allowed_by_the_project(tmp_path: Path) -> None:
    setup = '[rules."order/sealed-first"]\nwork = "work/*"\nseal = ["PLAN.md"]\nresults = ["results/**"]\n'
    built = world(tmp_path, setup)
    built.commit("start")
    refused = next(r for r in engine.run(manifests.load(built.root)).results if r.id == "order/sealed-first")
    assert refused.verdict is Verdict.REFUSE
    built.manifest(setup + 'empty = "allow"\n')
    allowed = next(r for r in engine.run(manifests.load(built.root)).results if r.id == "order/sealed-first")
    assert allowed.verdict is Verdict.PASS


# --- external checks ---------------------------------------------------------------------------


def run_script(tmp_path: Path, body: str, **extra) -> external.Outcome:
    built = world(tmp_path)
    command = script(built, body)
    table = {"id": "ext/check", "description": "d", "command": command, **extra}
    return external.run(external.Check.from_table(table), built.root)


def test_exit_zero_passes_and_exit_one_fails(tmp_path: Path) -> None:
    assert run_script(tmp_path / "a", "raise SystemExit(0)\n").verdict is Verdict.PASS
    failed = run_script(tmp_path / "b", "print('it broke')\nraise SystemExit(1)\n")
    assert failed.verdict is Verdict.FAIL and "it broke" in failed.findings[0].message


@pytest.mark.parametrize(
    ("body", "extra", "said"),
    [
        ("raise SystemExit(3)\n", {}, "exited 3"),
        ("import time\ntime.sleep(30)\n", {"timeout_s": 1}, "did not finish"),
        ("import os, signal\nos.kill(os.getpid(), signal.SIGTERM)\n", {}, "stopped by signal"),
        ("print('{not json')\nraise SystemExit(1)\n", {"output": "json-lines"}, "not in the json-lines form"),
    ],
)
def test_anything_unclear_is_a_refusal_never_a_pass(tmp_path: Path, body: str, extra: dict, said: str) -> None:
    outcome = run_script(tmp_path, body, **extra)
    assert outcome.verdict is Verdict.REFUSE and said in outcome.findings[0].message


def test_a_program_that_is_not_installed_is_a_refusal(tmp_path: Path) -> None:
    built = world(tmp_path)
    check = external.Check.from_table({"id": "ext/x", "description": "d", "command": ["no-such-program-anywhere"]})
    assert external.run(check, built.root).verdict is Verdict.REFUSE


def test_located_lines_become_located_breaches(tmp_path: Path) -> None:
    body = "print('docs/a.md:12: heading has no space')\nprint('summary: 1 error')\nraise SystemExit(1)\n"
    outcome = run_script(tmp_path, body, output="path-line-message")
    assert [(f.where, f.line, f.message) for f in outcome.findings] == [("docs/a.md", 12, "heading has no space")]


def test_a_check_runs_only_when_its_paths_changed(tmp_path: Path) -> None:
    built = world(tmp_path)
    built.manifest(check_table(script(built, "raise SystemExit(1)\n"), when=["docs/**"]))
    manifest = manifests.load(built.root)
    skipped = engine.run(manifest, changed=["src/a.py"]).results[-1]
    ran = engine.run(manifest, changed=["docs/a.md"]).results[-1]
    assert skipped.status == "not triggered" and ran.verdict is Verdict.FAIL


def test_an_external_check_is_enforced_unless_the_project_says_otherwise(tmp_path: Path) -> None:
    built = world(tmp_path)
    built.manifest(check_table(script(built, "raise SystemExit(1)\n")))
    assert engine.run(manifests.load(built.root)).exit_code == 1
    built.manifest(check_table(script(built, "raise SystemExit(1)\n"), level="warn"))
    assert engine.run(manifests.load(built.root)).exit_code == 0


# --- telling a tightening from a weakening -----------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "kind"),
    [
        ({"rules": {"config/locked": "enforce"}}, {"rules": {"config/locked": "warn"}}, "weakening"),
        ({"rules": {"config/locked": "warn"}}, {"rules": {"config/locked": "enforce"}}, "tightening"),
        ({"rules": {"config/locked": "enforce"}}, {}, "weakening"),
        ({"rules": {"x/y": {"since": "2026-01-01"}}}, {"rules": {"x/y": {"since": "2026-06-01"}}}, "weakening"),
        ({"rules": {"x/y": {"empty": "refuse"}}}, {"rules": {"x/y": {"empty": "allow"}}}, "weakening"),
        ({"roles": {"w": {"paths": ["a/**"]}}}, {"roles": {"w": {"paths": ["a/**", "b/**"]}}}, "weakening"),
        ({"roles": {"w": {"paths": ["a/**", "b/**"]}}}, {"roles": {"w": {"paths": ["a/**"]}}}, "tightening"),
        ({"roles": {"w": {"paths": ["a/**"]}}}, {}, "weakening"),
        ({"config": {"protected": ["t/**"]}}, {"config": {}}, "weakening"),
        ({"project": {"packs": ["p"]}}, {"project": {"packs": []}}, "weakening"),
        ({"project": {"strict": True}}, {"project": {"strict": False}}, "weakening"),
        ({"suite": {"command": "pytest"}}, {"suite": {"command": "true"}}, "weakening"),
        ({"checks": {"external": [{"id": "ext/a", "command": ["x"]}]}}, {"checks": {"external": []}}, "weakening"),
        ({"checks": {"external": [{"id": "ext/a", "command": ["x"]}]}},
         {"checks": {"external": [{"id": "ext/a", "command": ["true"]}]}}, "weakening"),
        ({}, {"checks": {"external": [{"id": "ext/a", "command": ["x"]}]}}, "tightening"),
        ({"project": {"name": "a"}}, {"project": {"name": "b"}}, "neutral"),
    ],
)
def test_each_kind_of_change_is_classified(old: dict, new: dict, kind: str) -> None:
    kinds = {change.kind for change in configguard.classify(old, new)}
    assert kinds == {kind}


def test_no_change_is_no_change() -> None:
    same = {"rules": {"config/locked": "enforce"}, "roles": {"w": {"paths": ["a/**"]}}}
    assert configguard.classify(same, same) == []


# --- reports -----------------------------------------------------------------------------------


def a_report(tmp_path: Path) -> engine.Report:
    built = world(tmp_path, '[rules]\n"config/locked" = "enforce"\n"config/no-silent-weakening" = "enforce"\n')
    return engine.run(manifests.load(built.root))


def test_the_json_report_names_each_rule_its_verdict_and_its_fix(tmp_path: Path) -> None:
    document = json.loads(reporters.as_json(a_report(tmp_path)))
    assert document["verdict"] == "refuse" and document["exit_code"] == 2
    locked = next(result for result in document["results"] if result["rule"] == "config/locked")
    assert locked["verdict"] == "fail" and locked["findings"][0]["fix"]
    assert locked["promise"] and locked["learned"]


def test_sarif_keeps_a_refusal_out_of_the_results(tmp_path: Path) -> None:
    run = json.loads(reporters.sarif(a_report(tmp_path)))["runs"][0]
    assert {result["ruleId"] for result in run["results"]} == {"config/locked"}
    notices = run["invocations"][0]["toolExecutionNotifications"]
    assert any(notice["associatedRule"]["id"] == "config/no-silent-weakening" for notice in notices)


def test_the_compact_report_is_one_line_a_finding(tmp_path: Path) -> None:
    lines = reporters.compact(a_report(tmp_path)).splitlines()
    assert any(line.startswith("themis.lock: error themis[config/locked]:") for line in lines)
    assert any("could not decide" in line for line in lines)


def test_the_terminal_report_ends_with_the_verdict(tmp_path: Path) -> None:
    assert reporters.terminal(a_report(tmp_path)).rstrip().endswith("REFUSE")
