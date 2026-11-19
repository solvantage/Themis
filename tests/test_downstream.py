"""A manifest written for 0.1.0 loads unchanged under this version.

A downstream project upgrades Themis with its manifest as it is: the manifest must still be valid,
and it must still hash to the lock 0.1.0 wrote, or the upgrade itself would read as a change to
the configuration. The fixture has the structure of a real downstream manifest (every table, rule
entry, skip, external check and proof), with neutral names and two stand-in scripts.
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

from themis import configguard, engine, gates
from themis import manifest as manifests
from themis.rule import RULES

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "downstream"
#: The fixture's effective hash as 0.1.0 computes it (its configguard.effective_hash, run on this folder).
HASH_010 = "f9456098c6eeb47a7a6e4d2ef32322300eab9d747664ce661ef5e5562653ba20"

gates.load_all()


def loaded(tmp_path: Path) -> manifests.Manifest:
    copy = tmp_path / "downstream"
    shutil.copytree(FIXTURE, copy)
    return manifests.load(copy)


def test_the_manifest_written_for_0_1_0_is_still_valid(tmp_path: Path) -> None:
    manifest = loaded(tmp_path)
    assert manifest.problems == []
    result = engine.run_rule(RULES["config/valid"], manifest)
    assert result.verdict is not None and result.verdict.value == "pass"


def test_it_hashes_to_the_lock_0_1_0_wrote(tmp_path: Path) -> None:
    manifest = loaded(tmp_path)
    assert configguard.effective_hash(manifest) == HASH_010
    assert configguard.read_lock(manifest.root) == {"themis_lock": 1, "hash": HASH_010}
    result = engine.run_rule(RULES["config/locked"], manifest, force=True)
    assert result.verdict is not None and result.verdict.value == "pass", result.findings


def test_reading_it_again_is_no_change(tmp_path: Path) -> None:
    raw = tomllib.loads((FIXTURE / manifests.MANIFEST_FILE).read_text(encoding="utf-8"))
    assert configguard.classify(raw, loaded(tmp_path).raw) == []


def test_the_hash_moves_when_a_judging_script_does(tmp_path: Path) -> None:
    """The pinned hash covers the scripts too: the fixture's stand-ins are read, not skipped."""
    manifest = loaded(tmp_path)
    (manifest.root / "scripts" / "docs_check.py").write_text("# edited to pass everything\n", encoding="utf-8")
    assert configguard.effective_hash(manifest) != HASH_010
