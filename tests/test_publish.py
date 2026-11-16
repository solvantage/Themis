"""Attacks on scripts/publish.py, the local publish pipeline.

Three kinds:

1. **Refusals.** Each decision is handed the input it must stop on, and must stop with the right
   verdict: FAIL for a broken rule, REFUSE when nothing can be established.
2. **No false alarm.** The honest inputs pass, among them the near misses: another version, another
   package whose name starts the same way.
3. **Planted bugs.** The pipeline's own source, broken one line at a time and run in memory (the
   file on disk is never written). Each plant names the one case it must flip, and must flip it.
"""

from __future__ import annotations

import types
from collections.abc import Callable
from pathlib import Path

import pytest

import publish
from publish import FAIL, REFUSE, Stop

NAME, VERSION = "themis-guardrails", "0.0.1"
WHEEL, SDIST = "themis_guardrails-0.0.1-py3-none-any.whl", "themis_guardrails-0.0.1.tar.gz"
SOURCE = Path(publish.__file__).read_text(encoding="utf-8")


def report(*, tests: int, failures: int = 0, errors: int = 0, skipped: int = 0) -> str:
    return (
        f'<testsuites><testsuite name="pytest" tests="{tests}" failures="{failures}" '
        f'errors="{errors}" skipped="{skipped}"/></testsuites>'
    )


def stopped(module: types.ModuleType, code: int, call: Callable[[], object]) -> bool:
    """True when `call` ends in that module's Stop with this verdict."""
    try:
        call()
    except module.Stop as stop:
        return stop.code == code
    return False


# --- the version -------------------------------------------------------------------------------


@pytest.mark.parametrize("version", ["0.0.1", "1.2.3", "10.20.30", "1.0.0rc1", "2.0.0a3", "0.9.0b12"])
def test_a_release_version_is_read(version: str) -> None:
    assert publish.read_version(f'"""doc"""\n\n__version__ = "{version}"\n') == version


@pytest.mark.parametrize(
    "text",
    [
        "",
        "version = '0.0.1'\n",
        '__version__ = "0.0.1"\n__version__ = "0.0.2"\n',
        '__version__ = "0.1"\n',
        '__version__ = "1.0.0.dev1"\n',
        '__version__ = "1.0.0+local"\n',
        '__version__ = ""\n',
    ],
)
def test_an_unclear_version_is_refused(text: str) -> None:
    assert stopped(publish, REFUSE, lambda: publish.read_version(text))


def test_file_names_spell_the_distribution_name_with_underscores() -> None:
    assert publish.file_stem("themis-guardrails") == "themis_guardrails"
    assert publish.file_stem("Themis.Guard--rails") == "themis_guard_rails"


# --- the tree ----------------------------------------------------------------------------------


def test_a_clean_committed_repository_passes() -> None:
    assert publish.judge_tree(own_repo=True, has_commit=True, dirty=[], dry_run=False) == []


@pytest.mark.parametrize(
    "state",
    [
        {"own_repo": False, "has_commit": False, "dirty": []},
        {"own_repo": True, "has_commit": False, "dirty": []},
        {"own_repo": True, "has_commit": True, "dirty": ["src/themis/cli.py"]},
    ],
)
def test_a_tree_that_pins_nothing_is_refused_and_only_warned_about_in_a_dry_run(state: dict) -> None:
    assert stopped(publish, REFUSE, lambda: publish.judge_tree(**state, dry_run=False))
    warnings = publish.judge_tree(**state, dry_run=True)
    assert len(warnings) == 1 and "would be refused" in warnings[0]


# --- a published version is never replaced -----------------------------------------------------


@pytest.mark.parametrize(
    "index_files",
    [
        [],
        ["themis_guardrails-0.0.2-py3-none-any.whl", "themis_guardrails-0.0.2.tar.gz"],
        ["themis_guardrails-0.0.10-py3-none-any.whl", "themis_guardrails-0.0.10.tar.gz"],
        ["themis_guardrails_extra-0.0.1-py3-none-any.whl", "themis_guardrails_extra-0.0.1.tar.gz"],
        ["README.txt", ".gitignore"],
    ],
)
def test_other_versions_and_other_packages_do_not_block(index_files: list[str]) -> None:
    publish.judge_unpublished(index_files, NAME, VERSION, has_receipt=False)


@pytest.mark.parametrize("index_files", [[WHEEL], [SDIST], [WHEEL, SDIST]])
def test_a_version_already_in_the_index_fails(index_files: list[str]) -> None:
    assert stopped(publish, FAIL, lambda: publish.judge_unpublished(index_files, NAME, VERSION, has_receipt=False))


def test_a_version_with_a_receipt_fails_even_when_the_index_was_emptied() -> None:
    assert stopped(publish, FAIL, lambda: publish.judge_unpublished([], NAME, VERSION, has_receipt=True))


# --- the suite ---------------------------------------------------------------------------------


def test_a_passing_suite_is_counted() -> None:
    counts = publish.judge_tests(report(tests=7, skipped=2))
    assert counts == {"tests": 7, "failures": 0, "errors": 0, "skipped": 2, "passed": 5}


@pytest.mark.parametrize(
    ("xml", "verdict"),
    [
        (report(tests=0), REFUSE),  # an empty run proves nothing
        (report(tests=3, skipped=3), REFUSE),  # nothing was checked
        (report(tests=5, failures=1), FAIL),
        (report(tests=5, errors=2), FAIL),
        ("<testsuites></testsuites>", REFUSE),
        ("not xml at all", REFUSE),
        ('<testsuites><testsuite tests="many"/></testsuites>', REFUSE),
    ],
)
def test_a_suite_that_did_not_pass_stops_the_release(xml: str, verdict: int) -> None:
    assert stopped(publish, verdict, lambda: publish.judge_tests(xml))


# --- the built files ---------------------------------------------------------------------------


def test_one_wheel_and_one_source_archive_are_accepted() -> None:
    assert publish.judge_artifacts([SDIST, WHEEL], NAME, VERSION) == (WHEEL, SDIST)


@pytest.mark.parametrize(
    "built",
    [
        [],
        [WHEEL],
        [SDIST],
        [WHEEL, SDIST, "themis_guardrails-0.0.1-py2-none-any.whl"],
        [WHEEL, SDIST, "notes.txt"],
        ["themis_guardrails-0.0.2-py3-none-any.whl", SDIST],
        [WHEEL, "themis_guardrails-0.0.2.tar.gz"],
        ["other-0.0.1-py3-none-any.whl", "other-0.0.1.tar.gz"],
    ],
)
def test_any_other_set_of_built_files_fails(built: list[str]) -> None:
    assert stopped(publish, FAIL, lambda: publish.judge_artifacts(built, NAME, VERSION))


def test_the_installed_wheel_must_answer_with_this_version() -> None:
    publish.judge_version_output("themis 0.0.1\n", VERSION)
    assert stopped(publish, FAIL, lambda: publish.judge_version_output("themis 0.0.2\n", VERSION))
    assert stopped(publish, FAIL, lambda: publish.judge_version_output("", VERSION))


# --- the copy into the index -------------------------------------------------------------------


def built_files(folder: Path) -> list[Path]:
    folder.mkdir()
    (folder / WHEEL).write_bytes(b"wheel bytes")
    (folder / SDIST).write_bytes(b"source bytes")
    return [folder / WHEEL, folder / SDIST]


def test_publishing_copies_both_files_and_records_their_hashes(tmp_path: Path) -> None:
    artifacts, index, copied = built_files(tmp_path / "dist"), tmp_path / "index", []
    records = publish.stage_publish(index, artifacts, copied)
    assert sorted(path.name for path in index.iterdir()) == sorted([WHEEL, SDIST])
    assert copied == [index / WHEEL, index / SDIST]
    assert [record["sha256"] for record in records] == [publish.sha256(path) for path in artifacts]


def test_publishing_never_overwrites_and_copies_nothing_when_one_file_exists(tmp_path: Path) -> None:
    artifacts, index, copied = built_files(tmp_path / "dist"), tmp_path / "index", []
    index.mkdir()
    (index / SDIST).write_bytes(b"the release already there")
    assert stopped(publish, FAIL, lambda: publish.stage_publish(index, artifacts, copied))
    assert copied == []
    assert [path.name for path in index.iterdir()] == [SDIST]
    assert (index / SDIST).read_bytes() == b"the release already there"


# --- the receipt and the releases page ---------------------------------------------------------


def a_receipt(version: str, commit: str = "c" * 40) -> dict:
    return {
        "package": NAME,
        "version": version,
        "commit": commit,
        "published_at_utc": "2026-01-02T03:04:05+00:00",
        "tests": {"passed": 7},
        "artifacts": [
            {"file": f"themis_guardrails-{version}.tar.gz", "sha256": "b" * 64},
            {"file": f"themis_guardrails-{version}-py3-none-any.whl", "sha256": "a" * 64},
        ],
    }


def test_a_receipt_names_the_index_relative_to_the_repository(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    assert publish.index_label(root, root / "wheelhouse") == "wheelhouse"
    assert publish.index_label(root, root / "build" / "index") == "build/index"


def test_an_index_outside_the_repository_is_named_without_its_path(tmp_path: Path) -> None:
    label = publish.index_label(tmp_path / "repo", tmp_path / "elsewhere" / "shared-index")
    assert label == "outside the repository (shared-index)"
    assert str(tmp_path) not in label


def test_versions_are_ordered_as_releases_not_as_text() -> None:
    order = ["0.9.9", "1.0.0a3", "1.0.0b1", "1.0.0rc2", "1.0.0", "1.0.9", "1.0.10"]
    assert sorted(reversed(order), key=publish.version_key) == order
    assert stopped(publish, REFUSE, lambda: publish.version_key("1.0"))


def test_the_releases_page_lists_the_newest_first_and_installs_the_newest() -> None:
    page = publish.render_releases([a_receipt("0.0.9"), a_receipt("0.0.10"), a_receipt("0.0.2")], None)
    rows = [line.split("|")[1].strip() for line in page.splitlines() if line.startswith("| 0.")]
    assert rows == ["0.0.10", "0.0.9", "0.0.2"]
    assert "The latest release is **0.0.10**" in page
    assert "[0.0.9.json](receipts/publish/0.0.9.json)" in page
    assert f"`{'a' * 12}…`" in page  # the wheel's hash, not the source archive's
    assert page.endswith("\n") and not page.endswith("\n\n")


def test_the_releases_page_names_the_repository_only_when_it_is_known() -> None:
    known = publish.render_releases([a_receipt("0.0.1")], "https://example.invalid/group/themis")
    assert f'"{NAME} @ git+https://example.invalid/group/themis@{"c" * 40}"' in known
    assert "git+" not in publish.render_releases([a_receipt("0.0.1")], None)


# --- a stop always says why --------------------------------------------------------------------


@pytest.mark.parametrize(("reason", "fix"), [("", "do this"), ("it broke", ""), ("  ", "  ")])
def test_a_stop_without_a_reason_or_a_fix_cannot_be_made(reason: str, fix: str) -> None:
    with pytest.raises(ValueError):
        Stop(FAIL, reason, fix)


def test_a_stop_is_never_a_pass() -> None:
    with pytest.raises(ValueError):
        Stop(publish.PASS, "all good", "nothing to do")


# --- planted bugs ------------------------------------------------------------------------------

#: (name, the line as it stands, the line broken, the case that must flip)
PLANTS: list[tuple[str, str, str, Callable[[types.ModuleType], bool]]] = [
    (
        "a failing test is published",
        'if counts["failures"] or counts["errors"]:',
        'if counts["errors"]:',
        lambda m: stopped(m, FAIL, lambda: m.judge_tests(report(tests=5, failures=1))),
    ),
    (
        "a suite of skips is published",
        'if counts["passed"] <= 0:',
        "if False:",
        lambda m: stopped(m, REFUSE, lambda: m.judge_tests(report(tests=3, skipped=3))),
    ),
    (
        "a published version is replaced",
        "if taken:",
        "if False:",
        lambda m: stopped(m, FAIL, lambda: m.judge_unpublished([WHEEL], NAME, VERSION, has_receipt=False)),
    ),
    (
        "a receipt no longer blocks a second publish",
        "if has_receipt:",
        "if False:",
        lambda m: stopped(m, FAIL, lambda: m.judge_unpublished([], NAME, VERSION, has_receipt=True)),
    ),
    (
        "a dirty tree is published",
        "elif dirty:",
        "elif False:",
        lambda m: stopped(
            m, REFUSE, lambda: m.judge_tree(own_repo=True, has_commit=True, dirty=["x.py"], dry_run=False)
        ),
    ),
    (
        "a folder with no repository is published",
        "if not own_repo:\n        problem",
        "if False:\n        problem",
        lambda m: stopped(
            m, REFUSE, lambda: m.judge_tree(own_repo=False, has_commit=True, dirty=[], dry_run=False)
        ),
    ),
    (
        "a wheel of another version is published",
        "if not all(is_release_file(name, dist_name, version) for name in (wheels[0], sdists[0])):",
        "if False:",
        lambda m: stopped(
            m, FAIL, lambda: m.judge_artifacts(["themis_guardrails-0.0.2-py3-none-any.whl", SDIST], NAME, VERSION)
        ),
    ),
    (
        "version 0.0.10 blocks version 0.0.1",
        'filename.startswith(f"{stem}-") and filename.endswith(".whl")',
        'filename.startswith(stem) and filename.endswith(".whl")',
        lambda m: not m.is_release_file("themis_guardrails-0.0.10-py3-none-any.whl", NAME, VERSION),
    ),
    (
        "a stop with no reason is allowed",
        "if not reason.strip() or not fix.strip():",
        "if False:",
        lambda m: _raises_value_error(lambda: m.Stop(FAIL, "", "")),
    ),
    (
        "a receipt publishes a local folder's path",
        "return index.resolve().relative_to(root.resolve()).as_posix()",
        "return str(index)",
        lambda m: m.index_label(Path("/srv/repo"), Path("/srv/repo/wheelhouse")) == "wheelhouse",
    ),
    (
        "the oldest release is shown as the latest",
        'key=lambda receipt: version_key(receipt["version"]), reverse=True',
        'key=lambda receipt: version_key(receipt["version"]), reverse=False',
        lambda m: "The latest release is **0.0.10**"
        in m.render_releases([a_receipt("0.0.9"), a_receipt("0.0.10")], None),
    ),
]


def _raises_value_error(call: Callable[[], object]) -> bool:
    try:
        call()
    except ValueError:
        return True
    return False


def planted(old: str, new: str) -> types.ModuleType:
    """The pipeline with one line broken, loaded in memory. The file on disk is not touched."""
    assert SOURCE.count(old) == 1, f"the plant's target must occur exactly once: {old!r}"
    module = types.ModuleType("planted_publish")
    module.__file__ = publish.__file__
    exec(compile(SOURCE.replace(old, new), "<planted publish.py>", "exec"), module.__dict__)  # noqa: S102
    return module


@pytest.mark.parametrize(("name", "old", "new", "case"), PLANTS, ids=[plant[0] for plant in PLANTS])
def test_each_planted_bug_flips_the_case_that_names_it(
    name: str, old: str, new: str, case: Callable[[types.ModuleType], bool]
) -> None:
    assert case(publish), f"no false alarm: the real pipeline must hold on the case for {name!r}"
    assert not case(planted(old, new)), f"the planted bug {name!r} was not caught by its own case"
