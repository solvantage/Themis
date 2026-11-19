"""Proofs: every rule is shown a planted fault, and must be the one that fails.

Two kinds of proof live here.

A **world** is a small repository built from scratch in a temporary folder for one rule, with the
answer worked out by hand: an honest world must pass, a broken one must fail the named rule. Worlds
prove a rule's logic.

A **plant** is a change applied to a copy of a real repository, after which one of that project's
own external checks must fail, and fail for the planted reason. Plants prove a project's wiring.

Nothing is ever planted in the working tree.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from themis import engine, external
from themis import manifest as manifests
from themis.engine import Result
from themis.rule import PROOFS, RULES, Proof
from themis.verdict import Finding, Verdict

NOT_COPIED = (".venv", "node_modules", "__pycache__", ".pytest_cache", "wheelhouse", "dist", ".themis")
LINKED = (".venv", "node_modules")  # dependencies are linked into a copy, never copied
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "proof", "GIT_AUTHOR_EMAIL": "proof@example.invalid",
    "GIT_COMMITTER_NAME": "proof", "GIT_COMMITTER_EMAIL": "proof@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
}


class World:
    """A small repository, built step by step, in which one rule is judged."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._started = False
        self._clock = 0
        self._day = "2026-01-01"

    # -- files ----------------------------------------------------------------------------------

    def write(self, path: str, text: str = "x\n") -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text), encoding="utf-8")

    def remove(self, path: str) -> None:
        (self.root / path).unlink()

    def move(self, old: str, new: str) -> None:
        target = self.root / new
        target.parent.mkdir(parents=True, exist_ok=True)
        (self.root / old).rename(target)

    def manifest(self, text: str) -> None:
        self.write(manifests.MANIFEST_FILE, text)

    # -- history --------------------------------------------------------------------------------

    def git(self, *args: str) -> str:
        if not self._started:
            self._started = True
            self.git("init", "-q", "-b", "main")
        self._clock += 1
        stamp = f"{self._day}T00:{self._clock // 60:02d}:{self._clock % 60:02d}+00:00"
        env = {**os.environ, **_GIT_ENV, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
        done = subprocess.run(["git", *args], cwd=self.root, env=env, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed in a proof world: {done.stderr.strip()}")
        return done.stdout

    def on(self, day: str) -> None:
        """Date the commits that follow on this day (YYYY-MM-DD), so a world's history spans time."""
        self._day = day

    def commit(self, message: str = "work") -> str:
        """Commit everything on the current branch. The first commit starts the repository on `main`."""
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def branch(self, name: str) -> None:
        self.git("checkout", "-q", "-b", name)

    def checkout(self, name: str) -> None:
        self.git("checkout", "-q", name)

    def merge(self, name: str) -> None:
        """Merge a branch into the current one with a merge commit, as a pull request does."""
        self.git("merge", "-q", "--no-ff", "-m", f"merge {name}", name)

    def pull_request(self, name: str, *commits: dict[str, str]) -> None:
        """A branch off the current one, one commit for each dict of files, merged back."""
        base = self.git("rev-parse", "--abbrev-ref", "HEAD").strip()
        self.branch(name)
        for files in commits:
            for path, text in files.items():
                self.write(path, text)
            self.commit(f"{name}: {', '.join(sorted(files))}")
        self.checkout(base)
        self.merge(name)


@dataclass(frozen=True)
class Outcome:
    rule: str
    name: str
    expect: Verdict
    actual: Verdict | None
    held: bool
    detail: str = ""


def judge(root: Path, rule_id: str) -> Result:
    """Run one rule in a repository, whatever level the project set, and return its result."""
    manifest = manifests.load(root)
    report = engine.run(manifest, only={rule_id})
    for result in report.results:
        if result.id == rule_id:
            return result if result.status == "ran" else engine.run_rule(RULES[rule_id], manifest, force=True)
    if not manifest.problems and rule_id in RULES:
        # The world does not turn the rule's pack on: a local pack cannot be named from a world
        # built from scratch. The proof still judges the rule it names.
        return engine.run_rule(RULES[rule_id], manifest, force=True)
    refusal = Finding("refusal", "the world's manifest is not valid: " + "; ".join(manifest.problems))
    return Result(id=rule_id, gate=rule_id.split("/")[0], promise="", level="enforce", status="ran",
                  verdict=Verdict.REFUSE, findings=(refusal,))


def run_proof(proof: Proof) -> Outcome:
    with tempfile.TemporaryDirectory(prefix="themis-world-") as scratch:
        world = World(Path(scratch) / "repo")
        world.root.mkdir()
        try:
            proof.build(world)
        except Exception as error:  # noqa: BLE001 - a world that cannot be built proves nothing
            return Outcome(proof.rule, proof.name, proof.expect, None, False, f"the world could not be built: {error!r}")
        result = judge(world.root, proof.rule)
    said = " | ".join(finding.message for finding in result.findings)
    if result.status != "ran":
        return Outcome(proof.rule, proof.name, proof.expect, None, False, f"the rule did not run: {result.status}")
    if result.verdict != proof.expect:
        return Outcome(proof.rule, proof.name, proof.expect, result.verdict, False, said)
    if proof.contains and proof.contains not in said:
        return Outcome(proof.rule, proof.name, proof.expect, result.verdict, False,
                       f"the rule reached {proof.expect.value}, but not for the planted reason "
                       f"(expected to read {proof.contains!r}): {said}")
    return Outcome(proof.rule, proof.name, proof.expect, result.verdict, True)


def run_native(rule_ids: set[str] | None = None) -> list[Outcome]:
    """Run the world proofs of every registered rule, or of the rules named."""
    return [
        run_proof(proof)
        for rule_id in sorted(PROOFS)
        if rule_ids is None or rule_id in rule_ids
        for proof in PROOFS[rule_id]
    ]


def standing(rule_id: str) -> str:
    """Whether a rule has the proofs it needs: one it fails, and one it passes."""
    expects = {proof.expect for proof in PROOFS.get(rule_id, [])}
    said_no = expects & {Verdict.FAIL, Verdict.REFUSE}
    if said_no and Verdict.PASS in expects:
        return "proven"
    return "unproven: no proof at all" if not expects else (
        "unproven: no planted fault" if not said_no else "unproven: no honest case"
    )


# -- plants, for a project's own external checks ------------------------------------------------


class PlantError(Exception):
    pass


def apply_plant(root: Path, plant: dict[str, Any]) -> None:
    """Change one file in a copy. Exactly one action: append, content, delete, or find and replace."""
    target = (root / plant["file"]).resolve()
    if root.resolve() not in target.parents:
        raise PlantError(f"{plant['file']} is outside the repository")
    if plant.get("delete"):
        if not target.is_file():
            raise PlantError(f"{plant['file']} does not exist, so it cannot be deleted")
        target.unlink()
    elif "content" in plant:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(plant["content"], encoding="utf-8")
    elif "append" in plant:
        if not target.is_file():
            raise PlantError(f"{plant['file']} does not exist, so nothing can be appended")
        target.write_text(target.read_text(encoding="utf-8") + plant["append"], encoding="utf-8")
    else:
        if not target.is_file():
            raise PlantError(f"{plant['file']} does not exist")
        text = target.read_text(encoding="utf-8")
        if text.count(plant["find"]) != 1:
            raise PlantError(f"the text to replace occurs {text.count(plant['find'])} times in {plant['file']}; it must occur once")
        target.write_text(text.replace(plant["find"], plant["replace"]), encoding="utf-8")


def copy_repository(root: Path, into: Path) -> Path:
    """A private copy of a repository, history included, with its dependency folders linked in."""
    target = into / "repo"
    shutil.copytree(root, target, symlinks=True, ignore=shutil.ignore_patterns(*NOT_COPIED))
    for name in LINKED:
        if (root / name).is_dir():
            os.symlink(root / name, target / name)
    return target


def run_external(manifest: manifests.Manifest) -> list[Outcome]:
    """Run each external check's own proofs, each in a fresh copy of the repository."""
    outcomes = []
    for table in manifest.external:
        check = external.Check.from_table(table)
        for proof in check.proofs:
            expect = Verdict(proof["expect"])
            with tempfile.TemporaryDirectory(prefix="themis-plant-") as scratch:
                copy = copy_repository(manifest.root, Path(scratch))
                try:
                    if "plant" in proof:
                        apply_plant(copy, proof["plant"])
                except PlantError as error:
                    outcomes.append(Outcome(check.id, proof["name"], expect, None, False, f"the plant could not be applied: {error}"))
                    continue
                result = external.run(check, copy)
            wanted = proof.get("expect_output")
            if result.verdict != expect:
                detail = " | ".join(finding.message for finding in result.findings)
                outcomes.append(Outcome(check.id, proof["name"], expect, result.verdict, False, detail))
            elif wanted and not re.search(wanted, result.output):
                outcomes.append(Outcome(check.id, proof["name"], expect, result.verdict, False,
                                        f"the check reached {expect.value}, but its output does not match {wanted!r}"))
            else:
                outcomes.append(Outcome(check.id, proof["name"], expect, result.verdict, True))
    return outcomes


def external_standing(table: dict[str, Any]) -> str:
    expects = {proof["expect"] for proof in table.get("proofs", [])}
    if "fail" in expects and "pass" in expects:
        return "proven"
    return "unproven: no proof at all" if not expects else (
        "unproven: no planted fault" if "fail" not in expects else "unproven: no honest case"
    )
