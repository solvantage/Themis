"""The lifecycle commands, end to end: log, seal, run, decide, cite, attest, grant, hand off.

One small project with a local pack walks the whole path. Each command is checked for what it
writes and for what it refuses.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest

from themis import manifest as manifests
from themis.cli import EXIT_FAIL, EXIT_PASS, EXIT_REFUSE, main
from themis.proofs import World

PACK = '''
from themis.pack import Pack

pack = Pack(name="{name}")


@pack.gate("threshold", version="3")
def threshold(metrics):
    if metrics["samples"] < 30:
        return {{"decision": "defer", "verdict": "refuse", "enough_evidence": False, "reason": "too few samples"}}
    good = metrics["uplift"] >= 0.05
    return {{"decision": "keep" if good else "drop", "verdict": "pass" if good else "fail",
            "enough_evidence": True, "reason": "the uplift was measured on enough samples", "numbers": {{"uplift": metrics["uplift"]}}}}
'''
MANIFEST = """
[project]
name = "demo"
local_pack = "pack"

[rules."order/sealed-first"]
work = "work/*"
seal = ["PLAN.md"]
results = ["results/**"]

[rules."order/logged-first"]
work = "work/*"
results = ["results/**"]

[rules."claims/receipt"]
governed = ["REPORT.md"]
work = "work/*"
"""


def project(tmp_path: Path, name: str) -> World:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.write("pack/__init__.py", PACK.format(name=name))
    world.manifest(MANIFEST)
    world.write(".gitignore", ".themis/\n__pycache__/\n")
    world.commit("start")
    return world


def run(world: World, *args: str) -> int:
    return main([args[0], "--root", str(world.root), *args[1:]])


def test_a_unit_is_logged_then_run_only_after_its_seal_is_merged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = project(tmp_path, "life-a")
    assert run(world, "new", "open drive", "--question", "does the open drive pay?", "--variants", "3") == EXIT_PASS
    [record] = list((world.root / "ledger").glob("*.toml"))
    logged = tomllib.loads(record.read_text())
    unit = logged["work"]
    assert logged["state"] == "promised" and logged["variants"] == 3 and unit.startswith("work/") and unit.endswith("_open-drive")
    world.commit("log the unit")

    world.branch("seal")
    world.write(f"{unit}/PLAN.md", "the plan\n")
    world.commit("the plan")  # sealed on a branch, not on the main line yet
    job = [sys.executable, "-c", "print('ran')"]
    assert run(world, "run", unit, "--", *job) == EXIT_REFUSE
    assert "not on the main line yet" in capsys.readouterr().err

    world.checkout("main")
    world.merge("seal")
    world.write("data.csv", "1,2,3\n")
    assert run(world, "run", unit, "--", *job) == EXIT_REFUSE  # the tree is dirty
    assert "dirty" in capsys.readouterr().err
    world.commit("the data")

    assert run(world, "run", unit, "--input", "data.csv", "--", *job) == EXIT_PASS
    [receipt] = [json.loads(path.read_text()) for path in (world.root / "receipts/run").glob("*.json")]
    assert receipt["work"] == unit and receipt["exit_status"] == 0 and receipt["commit"]
    provenance = json.loads((world.root / unit / "results/provenance.json").read_text())
    assert provenance["clean"] is True and list(provenance["inputs"]) == ["data.csv"]


def test_a_failing_command_fails_and_still_leaves_its_receipt(tmp_path: Path) -> None:
    world = project(tmp_path, "life-b")
    world.pull_request("seal", {"work/a/PLAN.md": "the plan\n"})
    assert run(world, "run", "a", "--", sys.executable, "-c", "raise SystemExit(3)") == EXIT_FAIL
    [receipt] = [json.loads(path.read_text()) for path in (world.root / "receipts/run").glob("*.json")]
    assert receipt["exit_status"] == 3
    assert not (world.root / "work/a/results/provenance.json").exists()


@pytest.mark.parametrize(
    ("metrics", "code", "decision", "verdict"),
    [
        ({"samples": 200, "uplift": 0.08}, EXIT_PASS, "keep", "pass"),
        ({"samples": 200, "uplift": 0.01}, EXIT_FAIL, "drop", "fail"),
        ({"samples": 12, "uplift": 0.50}, EXIT_REFUSE, "defer", "refuse"),
    ],
)
def test_the_gate_decides_and_the_stored_decision_checks_clean(tmp_path: Path, metrics: dict, code: int, decision: str, verdict: str) -> None:
    world = project(tmp_path, f"life-c-{verdict}")
    world.write("work/a/PLAN.md", "the plan\n")
    world.write("work/a/results/metrics.json", json.dumps(metrics))
    assert run(world, "decide", "a", "--gate", "threshold") == code
    stored = json.loads((world.root / "decisions/work-a.json").read_text())
    assert (stored["decision"], stored["verdict"], stored["gate_version"], stored["work"]) == (decision, verdict, "3", "work/a")
    assert run(world, "check", "decision/issued-by-gate", "decision/enough-evidence") == EXIT_PASS

    stored["decision"], stored["verdict"] = "keep", "pass"  # typed by hand, kinder than the gate
    (world.root / "decisions/work-a.json").write_text(json.dumps(stored))
    world.manifest(MANIFEST + '\n[rules]\n"decision/issued-by-gate" = "enforce"\n')
    expected = EXIT_PASS if verdict == "pass" else EXIT_FAIL
    assert run(world, "check", "decision/issued-by-gate") == expected


def test_the_owners_own_call_needs_a_reason_and_is_stored_as_the_owners(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = project(tmp_path, "life-d")
    world.write("work/a/PLAN.md", "the plan\n")
    assert run(world, "decide", "a", "--gate", "threshold", "--by", "owner", "--decision", "keep", "--verdict", "pass") == EXIT_REFUSE
    assert "--reason" in capsys.readouterr().err
    assert run(world, "decide", "a", "--gate", "threshold", "--by", "owner", "--decision", "keep", "--verdict", "pass",
               "--reason", "kept for a second look") == EXIT_PASS
    assert json.loads((world.root / "decisions/work-a.json").read_text())["by"] == "owner"


def test_an_unknown_gate_or_unit_is_refused(tmp_path: Path) -> None:
    world = project(tmp_path, "life-e")
    world.write("work/a/PLAN.md", "the plan\n")
    world.write("work/a/results/metrics.json", "{}")
    assert run(world, "decide", "a", "--gate", "no-such-gate") == EXIT_REFUSE
    assert run(world, "decide", "no-such-unit", "--gate", "threshold") == EXIT_REFUSE
    assert run(world, "decide", "a", "--gate", "threshold") == EXIT_REFUSE  # the metrics lack what the gate reads


def test_a_number_is_cited_from_its_record_and_then_checks_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = project(tmp_path, "life-f")
    world.write("work/a/PLAN.md", "the plan\n")
    world.write("work/a/results/metrics.json", json.dumps({"uplift": 0.0834}))
    assert run(world, "cite", "a", "uplift", "--decimals", "2") == EXIT_PASS
    pasted = capsys.readouterr().out.strip()
    assert pasted == "0.08<!--t:a#uplift-->"
    world.write("REPORT.md", f"The uplift was {pasted}.\n")
    world.manifest(MANIFEST + '\n[rules]\n"config/valid" = "enforce"\n')
    assert run(world, "check", "claims/receipt") == EXIT_PASS
    world.write("REPORT.md", "The uplift was 0.31.\n")  # typed from memory
    result = main(["check", "--root", str(world.root), "claims/receipt", "--reporter", "json"])
    assert "cites no record" in capsys.readouterr().out and result == EXIT_PASS  # the rule is at warn here
    assert run(world, "cite", "a", "no-such-key") == EXIT_REFUSE


def test_a_grant_and_an_attestation_are_files_that_name_what_they_cover(tmp_path: Path) -> None:
    world = project(tmp_path, "life-g")
    assert run(world, "grant", "publish", "item-7", "--reason", "reviewed at gate three") == EXIT_PASS
    assert run(world, "grant", "spend", "item-7", "--reason", "one retake", "--ceiling", "500", "--unit", "credits") == EXIT_PASS
    assert run(world, "grant", "config", "--reason", "the lock is brought in by stages") == EXIT_PASS
    grants = [tomllib.loads(path.read_text()) for path in sorted((world.root / "grants").glob("*.toml"))]
    by_action = {grant["action"]: grant for grant in grants}
    assert by_action["spend"]["ceiling"] == 500 and by_action["publish"]["target"] == "item-7"
    from themis import configguard

    assert by_action["config"]["target"] == configguard.effective_hash(manifests.load(world.root))
    assert run(world, "grant", "publish", "--reason", "no target named") == EXIT_REFUSE

    world.write("notes.md", "judged text\n")
    assert run(world, "attest", "notes.md", "C1", "--judge", "owner", "--by", "owner") == EXIT_PASS
    [attestation] = [tomllib.loads(path.read_text()) for path in (world.root / "attestations").rglob("*.toml")]
    assert attestation["subject"] == "notes.md" and len(attestation["sha256"]) == 64
    assert run(world, "attest", "no-such-file.md", "C1", "--judge", "owner", "--by", "owner") == EXIT_REFUSE


def test_the_checkpoint_states_only_what_a_receipt_backs(tmp_path: Path) -> None:
    world = project(tmp_path, "life-h")
    assert run(world, "checkpoint") == EXIT_PASS
    text = (world.root / "CHECKPOINT.md").read_text()
    assert "unverified" in text and "**Changed:**" in text and "**Next:**" in text
    assert run(world, "check", "checkpoint/shape", "checkpoint/suite-receipt") == EXIT_PASS
