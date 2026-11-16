"""The wrapper for JavaScript check runners: its own tests, and one run against the real themis."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from themis.proofs import World

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bridge" / "node"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed, so the JavaScript wrapper cannot be run")


def test_the_wrappers_own_attacks_pass() -> None:
    done = subprocess.run([NODE, "--test"], cwd=BRIDGE, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.parametrize(
    ("manifest", "verdict", "code"),
    [
        ('[rules]\n"config/valid" = "enforce"\n', "pass", 0),
        ('[rules]\n"config/locked" = "enforce"\n', "fail", 1),
        ('[rules]\n"config/no-silent-weakening" = "enforce"\n', "refuse", 2),
    ],
)
def test_the_wrapper_reports_what_the_real_themis_decides(tmp_path: Path, manifest: str, verdict: str, code: int) -> None:
    world = World(tmp_path / "repo")
    world.root.mkdir()
    world.manifest(manifest)
    script = (
        "import { themisCheck } from " + json.dumps(str(BRIDGE / "index.mjs")) + ";"
        "const outcome = themisCheck({ cwd: " + json.dumps(str(world.root)) + ", command: "
        + json.dumps([sys.executable, "-m", "themis.cli"]) + " });"
        "console.log(JSON.stringify([outcome.verdict, outcome.exitCode]));"
    )
    done = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, check=False)
    assert json.loads(done.stdout) == [verdict, code], done.stderr
