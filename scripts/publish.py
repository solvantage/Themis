#!/usr/bin/env python3
"""The local publish pipeline: test, build, verify the built wheel, then copy it into a local index.

There is no hosted CI. This script is the release gate, run on the owner's machine:

    uv run python scripts/publish.py            publish the version in src/themis/__init__.py
    uv run python scripts/publish.py --dry-run  every stage, into a throwaway index; nothing is kept

It ends with one verdict, and the exit code says which:

    0  PASS    the release is in the index and its receipt is written
    1  FAIL    a rule was broken (a test failed, the version is already published, ...)
    2  REFUSE  the pipeline could not establish what it would publish (a dirty tree, no tests, a
               missing tool)

A blocking exit always prints a reason and a fix. The stages, in order:

    preflight  the folder is a clean git repository of its own; this version is not published yet
    test       the suite passes on the locked dependencies; zero tests is a REFUSE, never a pass
    build      one wheel and one source archive, built into an empty folder
    verify     the built wheel is installed into a fresh environment and `themis --version` is run
    publish    the two files are copied into the index; an existing file is never overwritten
    receipt    receipts/publish/<version>.json records the commit, the hashes and the test counts

The decisions are pure functions (the ``judge_*`` family), so tests/test_publish.py can attack
them without running a build.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import traceback
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path

PASS, FAIL, REFUSE = 0, 1, 2
VERDICT = {PASS: "PASS", FAIL: "FAIL", REFUSE: "REFUSE"}

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = "src/themis/__init__.py"
VERSION_LINE = re.compile(r'^__version__\s*=\s*"([^"]*)"\s*$', re.MULTILINE)
RELEASE = re.compile(r"^\d+\.\d+\.\d+((a|b|rc)\d+)?$")
TIMEOUT_S = 900


class Stop(Exception):
    """A stage ended the pipeline. It always carries a reason and a fix."""

    def __init__(self, code: int, reason: str, fix: str) -> None:
        if code not in (FAIL, REFUSE):
            raise ValueError("a stop is FAIL or REFUSE")
        if not reason.strip() or not fix.strip():
            raise ValueError("a stop always carries a reason and a fix")
        super().__init__(reason)
        self.code, self.reason, self.fix = code, reason, fix


# ---------------------------------------------------------------------------------------------
# The decisions. Pure: text and names in, an answer or a Stop out.
# ---------------------------------------------------------------------------------------------


def read_version(init_text: str) -> str:
    """The one version this tree would publish."""
    found = VERSION_LINE.findall(init_text)
    if len(found) != 1:
        raise Stop(
            REFUSE,
            f"{VERSION_FILE} must hold exactly one __version__ line; found {len(found)}",
            'state the version once, as __version__ = "X.Y.Z"',
        )
    if not RELEASE.match(found[0]):
        raise Stop(
            REFUSE,
            f"version {found[0]!r} is not a release version",
            "use X.Y.Z, optionally followed by a1, b1 or rc1",
        )
    return found[0]


def file_stem(dist_name: str) -> str:
    """A distribution name as wheel and source-archive file names spell it."""
    return re.sub(r"[-_.]+", "_", dist_name).lower()


def is_release_file(filename: str, dist_name: str, version: str) -> bool:
    stem = f"{file_stem(dist_name)}-{version}"
    return filename == f"{stem}.tar.gz" or (
        filename.startswith(f"{stem}-") and filename.endswith(".whl")
    )


def judge_tree(*, own_repo: bool, has_commit: bool, dirty: list[str], dry_run: bool) -> list[str]:
    """Warnings for a dry run; a REFUSE for a real one. A release must be tied to one commit."""
    problem = fix = ""
    if not own_repo:
        problem = "this folder is not a git repository of its own, so a release cannot be tied to a commit"
        fix = "run `git init`, commit the tree, then run again"
    elif not has_commit:
        problem = "the repository has no commit yet, so a release cannot be tied to one"
        fix = "commit the tree, then run again"
    elif dirty:
        shown = ", ".join(dirty[:5]) + (" ..." if len(dirty) > 5 else "")
        problem = f"the tree is dirty ({len(dirty)} path(s): {shown}); a release built from it pins nothing"
        fix = "commit or stash the changes, then run again"
    if not problem:
        return []
    if dry_run:
        return [f"{problem} (a real publish would be refused)"]
    raise Stop(REFUSE, problem, fix)


def judge_unpublished(
    index_files: Iterable[str], dist_name: str, version: str, *, has_receipt: bool
) -> None:
    """A published version is never replaced: not in the index, and not after its receipt."""
    taken = sorted(name for name in index_files if is_release_file(name, dist_name, version))
    if taken:
        raise Stop(
            FAIL,
            f"{dist_name} {version} is already in the index ({', '.join(taken)}); "
            "a published version is never replaced",
            f"raise __version__ in {VERSION_FILE}, commit, then run again",
        )
    if has_receipt:
        raise Stop(
            FAIL,
            f"{dist_name} {version} already has a publish receipt; the same version is never published twice",
            f"raise __version__ in {VERSION_FILE}, commit, then run again",
        )


def judge_tests(junit_xml: str) -> dict[str, int]:
    """Test counts from the suite's own report. Zero tests, or only skips, is a REFUSE."""
    by_hand = "run `uv run --locked pytest -q` by hand and read its output"
    try:
        root = ET.fromstring(junit_xml)
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        if not suites:
            raise ValueError("no testsuite element")
        counts = {
            key: sum(int(suite.get(key, "0") or "0") for suite in suites)
            for key in ("tests", "failures", "errors", "skipped")
        }
    except (ET.ParseError, ValueError) as error:
        raise Stop(REFUSE, f"the test report is unreadable ({error})", by_hand) from None
    counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    if counts["tests"] == 0:
        raise Stop(
            REFUSE,
            "the suite collected zero tests; an empty run proves nothing",
            "check testpaths in pyproject.toml and that tests/ holds tests",
        )
    if counts["failures"] or counts["errors"]:
        raise Stop(
            FAIL,
            f"the suite has {counts['failures']} failure(s) and {counts['errors']} error(s)",
            "run `uv run --locked pytest -q`, fix what fails, commit, then run again",
        )
    if counts["passed"] <= 0:
        raise Stop(REFUSE, "every test was skipped; nothing was checked", by_hand)
    return counts


def judge_artifacts(filenames: Iterable[str], dist_name: str, version: str) -> tuple[str, str]:
    """Exactly one wheel and one source archive, both carrying this name and version."""
    names = sorted(filenames)
    wheels = [name for name in names if name.endswith(".whl")]
    sdists = [name for name in names if name.endswith(".tar.gz")]
    strays = [name for name in names if name not in wheels and name not in sdists]
    if len(wheels) != 1 or len(sdists) != 1 or strays:
        raise Stop(
            FAIL,
            f"the build must produce exactly one wheel and one source archive; found {names or 'nothing'}",
            "run `uv build` by hand and read its output",
        )
    if not all(is_release_file(name, dist_name, version) for name in (wheels[0], sdists[0])):
        raise Stop(
            FAIL,
            f"the built files ({wheels[0]}, {sdists[0]}) do not carry {dist_name} {version}",
            f"check [tool.hatch.version] in pyproject.toml and {VERSION_FILE}",
        )
    return wheels[0], sdists[0]


def judge_version_output(stdout: str, version: str) -> None:
    """The installed wheel must answer with the version being published."""
    if stdout.strip() != f"themis {version}":
        raise Stop(
            FAIL,
            f"the installed wheel answered {stdout.strip()!r} to --version; expected 'themis {version}'",
            "the wheel does not hold this tree's code: check [tool.hatch.build] in pyproject.toml",
        )


# ---------------------------------------------------------------------------------------------
# The shell. Everything below touches the disk or runs a process.
# ---------------------------------------------------------------------------------------------


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tail(text: str, lines: int = 12) -> str:
    kept = [line for line in text.strip().splitlines() if line.strip()][-lines:]
    return "\n      ".join(kept)


def clean_env() -> dict[str, str]:
    """The environment for a child process, without this process's own virtual environment."""
    return {key: value for key, value in os.environ.items() if key not in ("VIRTUAL_ENV", "PYTHONPATH")}


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command, cwd=cwd, env=env, capture_output=True, text=True, timeout=TIMEOUT_S, check=False
        )
    except FileNotFoundError:
        raise Stop(
            REFUSE,
            f"`{command[0]}` is not installed or not on PATH",
            f"install {command[0]}, then run again",
        ) from None
    except subprocess.TimeoutExpired:
        raise Stop(
            REFUSE,
            f"`{' '.join(command[:3])} ...` did not finish in {TIMEOUT_S} seconds",
            "run the command by hand to see where it hangs",
        ) from None


def git_state(root: Path) -> tuple[bool, str | None, list[str]]:
    """(this folder is its own repository, the HEAD commit or None, the dirty paths)."""
    top = run(["git", "rev-parse", "--show-toplevel"], cwd=root)
    own_repo = top.returncode == 0 and os.path.realpath(top.stdout.strip()) == os.path.realpath(root)
    if not own_repo:
        return False, None, []
    head = run(["git", "rev-parse", "HEAD"], cwd=root)
    commit = head.stdout.strip() if head.returncode == 0 else None
    status = run(["git", "status", "--porcelain"], cwd=root)
    if status.returncode != 0:
        raise Stop(REFUSE, "git could not report the state of the tree", "run `git status` by hand")
    return True, commit, [line[3:] for line in status.stdout.splitlines() if line.strip()]


def stage_preflight(root: Path, index: Path, *, dry_run: bool) -> tuple[str, str, str | None, list[str]]:
    name = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["name"]
    version = read_version((root / VERSION_FILE).read_text(encoding="utf-8"))
    own_repo, commit, dirty = git_state(root)
    warnings = judge_tree(own_repo=own_repo, has_commit=commit is not None, dirty=dirty, dry_run=dry_run)
    index_files = [path.name for path in index.iterdir()] if index.is_dir() else []
    has_receipt = receipt_path(root, version).exists()
    try:
        judge_unpublished(index_files, name, version, has_receipt=has_receipt)
    except Stop as stop:
        if not dry_run:
            raise
        warnings.append(f"{stop.reason} (a real publish would fail)")
    return name, version, commit, warnings


def stage_test(root: Path, work: Path) -> dict[str, int]:
    report = work / "junit.xml"
    done = run(
        ["uv", "run", "--locked", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}"],
        cwd=root,
    )
    if not report.exists():
        raise Stop(
            REFUSE,
            f"the suite did not produce a report (exit {done.returncode}):\n      {tail(done.stderr or done.stdout)}",
            "run `uv run --locked pytest -q` by hand; if uv.lock is missing or stale, run `uv lock` and commit it",
        )
    counts = judge_tests(report.read_text(encoding="utf-8"))
    if done.returncode != 0:
        raise Stop(
            FAIL,
            f"pytest exited {done.returncode} though its report shows no failure:\n      {tail(done.stdout)}",
            "run `uv run --locked pytest -q` by hand and read its output",
        )
    return counts


def stage_build(root: Path, work: Path, name: str, version: str) -> tuple[Path, Path]:
    out = work / "dist"
    done = run(["uv", "build", "--out-dir", str(out)], cwd=root)
    if done.returncode != 0:
        raise Stop(
            FAIL,
            f"the build failed (exit {done.returncode}):\n      {tail(done.stderr or done.stdout)}",
            "run `uv build` by hand and read its output",
        )
    built = [path.name for path in out.iterdir() if path.is_file() and not path.name.startswith(".")]
    wheel, sdist = judge_artifacts(built, name, version)
    return out / wheel, out / sdist


def stage_verify(work: Path, wheel: Path, version: str) -> None:
    """Install the wheel that will be published, away from the source tree, and run it."""
    venv, env = work / "venv", clean_env()
    made = run(["uv", "venv", str(venv), "--quiet", "--python", sys.executable], cwd=work, env=env)
    if made.returncode != 0:
        raise Stop(
            REFUSE,
            f"a fresh environment could not be created:\n      {tail(made.stderr)}",
            "run `uv venv` by hand to see why",
        )
    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    python = bin_dir / ("python.exe" if os.name == "nt" else "python")
    installed = run(["uv", "pip", "install", "--quiet", "--python", str(python), str(wheel)], cwd=work, env=env)
    if installed.returncode != 0:
        raise Stop(
            FAIL,
            f"the built wheel does not install:\n      {tail(installed.stderr)}",
            "check the dependencies and the build settings in pyproject.toml",
        )
    answered = run([str(bin_dir / "themis"), "--version"], cwd=work, env=env)
    if answered.returncode != 0:
        raise Stop(
            FAIL,
            f"the installed `themis --version` exited {answered.returncode}:\n      {tail(answered.stderr)}",
            "check [project.scripts] in pyproject.toml",
        )
    judge_version_output(answered.stdout, version)


def stage_publish(index: Path, artifacts: list[Path], copied: list[Path]) -> list[dict[str, object]]:
    """Copy into the index. `copied` collects what landed, so a later failure can take it back."""
    index.mkdir(parents=True, exist_ok=True)
    for source in artifacts:
        if (index / source.name).exists():
            raise Stop(
                FAIL,
                f"{source.name} is already in the index; a published file is never overwritten",
                f"raise __version__ in {VERSION_FILE}, commit, then run again",
            )
    records: list[dict[str, object]] = []
    for source in artifacts:
        target = index / source.name
        shutil.copy2(source, target)
        copied.append(target)
        digest = sha256(source)
        if sha256(target) != digest:
            raise Stop(
                REFUSE,
                f"the copy of {source.name} in the index differs from the built file",
                "check the disk the index is on, then run again",
            )
        records.append({"file": source.name, "sha256": digest, "bytes": source.stat().st_size})
    return records


def receipt_path(root: Path, version: str) -> Path:
    return root / "receipts" / "publish" / f"{version}.json"


def stage_receipt(
    root: Path, *, name: str, version: str, commit: str | None, tests: dict[str, int],
    artifacts: list[dict[str, object]], index: Path,
) -> Path:
    uv = run(["uv", "--version"], cwd=root)
    now = dt.datetime.now(dt.timezone.utc)
    receipt = {
        "package": name,
        "version": version,
        "commit": commit,
        "clean_tree": True,
        "published_at_utc": now.isoformat(timespec="seconds"),
        "published_at_local": now.astimezone().isoformat(timespec="seconds"),
        "tests": tests,
        "artifacts": artifacts,
        "index": str(index),
        "tools": {"uv": uv.stdout.strip(), "python": sys.version.split()[0]},
    }
    path = receipt_path(root, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


def pipeline(root: Path, index: Path, *, dry_run: bool) -> int:
    stage = "preflight"
    copied: list[Path] = []

    def say(text: str) -> None:
        print(f"  -> {stage:<10}{text}", flush=True)

    with tempfile.TemporaryDirectory(prefix="themis-publish-") as scratch:
        work = Path(scratch)
        target = work / "index" if dry_run else index
        try:
            name, version, commit, warnings = stage_preflight(root, index, dry_run=dry_run)
            print(f"{name} {version} -> {target if not dry_run else 'a throwaway index (dry run)'}")
            for warning in warnings:
                print(f"  !  {warning}")
            say(f"tree clean at {commit[:8]}; version not published yet" if commit and not warnings else "checked")

            stage = "test"
            tests = stage_test(root, work)
            say(f"{tests['passed']} passed, {tests['skipped']} skipped")

            stage = "build"
            wheel, sdist = stage_build(root, work, name, version)
            say(f"{wheel.name} + {sdist.name}")

            stage = "verify"
            stage_verify(work, wheel, version)
            say(f"a fresh install answers `themis {version}`")

            stage = "publish"
            artifacts = stage_publish(target, [wheel, sdist], copied)
            say(f"{len(artifacts)} files copied, hashes match")

            if dry_run:
                print("DRY RUN PASS - every stage held; nothing was published and no receipt was written")
                return PASS

            stage = "receipt"
            path = stage_receipt(
                root, name=name, version=version, commit=commit, tests=tests, artifacts=artifacts, index=index
            )
            say(str(path.relative_to(root)))
            print(f"PASS - {name} {version} is published. Commit the receipt.")
            return PASS
        except Stop as stop:
            code, reason, fix = stop.code, stop.reason, stop.fix
        except Exception:  # noqa: BLE001 - a crash is not a verdict about the release
            code = REFUSE
            reason = f"the pipeline itself crashed:\n      {tail(traceback.format_exc(), lines=8)}"
            fix = "this is a bug in scripts/publish.py; nothing can be concluded about the release"
        for path in copied:  # an index never keeps half a release
            path.unlink(missing_ok=True)
        print(f"  x  {stage}: {reason}", file=sys.stderr)
        print(f"     fix: {fix}", file=sys.stderr)
        print(f"{VERDICT[code]} - nothing was published", file=sys.stderr)
        return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish Themis to a local package index.")
    parser.add_argument("--dry-run", action="store_true", help="run every stage into a throwaway index")
    parser.add_argument("--index", help="the index folder (default: $THEMIS_INDEX, else ./wheelhouse)")
    args = parser.parse_args(argv)
    chosen = args.index or os.environ.get("THEMIS_INDEX") or str(ROOT / "wheelhouse")
    return pipeline(ROOT, Path(chosen).expanduser().resolve(), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
