"""The library that writes grants, action receipts and attestations.

The gates `grant` and `attest` have their own proofs. These tests hold the writer to its word:
what it writes is TOML the standard library reads back, a record never replaces an older one, and
the gates accept what the library wrote.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path

import pytest

from themis import gates, grants, proofs, receipts, records, schema
from themis import manifest as manifests
from themis.proofs import World
from themis.verdict import Verdict

gates.load_all()  # the attest gate adds `author` and `shown` to the attestation record

NOON = dt.datetime(2026, 3, 4, 12, 0, 0, tzinfo=dt.timezone.utc)


def read(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def problems(kind: str, data: dict) -> list[str]:
    return schema.problems(data, records.KINDS[kind][0], kind)


# -- to_toml ------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [
    "plain", "", 'a "quoted" word', "back\\slash", "two\nlines\tand a tab", "ภาษาไทย", "a face 😀",
    "control \x00 \x1f and delete \x7f", "# not a comment", "'single'", 7, -3, 0, 2.5, 1e16, 1e-7, True, False,
    ["a", "b"], [], ['with "quotes"', "and, a comma"],
])
def test_a_value_written_as_toml_is_read_back_unchanged(value) -> None:
    assert tomllib.loads(grants.to_toml({"key": value})) == {"key": value}


def test_a_table_keeps_every_key_and_a_key_that_needs_quotes_gets_them() -> None:
    table = {"action": "publish", "ceiling": 50, "spent": False, "a key with spaces": "x", "dotted.key": ["y"]}
    text = grants.to_toml(table)
    assert tomllib.loads(text) == table
    assert text.splitlines()[0] == 'action = "publish"'
    assert grants.to_toml({}) == ""


def test_true_is_written_as_true_and_never_as_a_number() -> None:
    assert grants.to_toml({"done": True, "count": 1}) == "done = true\ncount = 1\n"


@pytest.mark.parametrize("value", [None, {"nested": 1}, [1, 2], [["a"]], b"bytes"])
def test_a_value_toml_cannot_hold_flat_is_refused(value) -> None:
    with pytest.raises(TypeError):
        grants.to_toml({"key": value})


def test_text_that_is_not_valid_unicode_is_refused() -> None:
    with pytest.raises(ValueError):
        grants.to_toml({"key": "half a pair \ud83d"})


# -- new_grant ----------------------------------------------------------------------------------


def test_a_grant_is_a_valid_record_named_by_its_date_action_and_target(tmp_path: Path) -> None:
    path = grants.new_grant(tmp_path, "publish", "Episode 12 / final", granted_by="owner",
                            reason="the cut was reviewed", now=NOON)
    assert path.relative_to(tmp_path).as_posix() == "grants/2026-03-04-publish-episode-12-final.toml"
    data = read(path)
    assert data == {"action": "publish", "target": "Episode 12 / final", "granted_by": "owner",
                    "granted_at": "2026-03-04T12:00:00+00:00", "reason": "the cut was reviewed"}
    assert problems("grant", data) == []


def test_a_grant_that_spends_holds_its_ceiling_and_unit(tmp_path: Path) -> None:
    data = read(grants.new_grant(tmp_path, "spend", "ads", granted_by="owner", reason="one test run",
                                 ceiling=50, unit="credits", now=NOON))
    assert (data["ceiling"], data["unit"]) == (50, "credits")
    assert problems("grant", data) == []


def test_a_second_grant_never_replaces_the_first(tmp_path: Path) -> None:
    made = [grants.new_grant(tmp_path, "publish", "episode-12", granted_by="owner", reason=reason, now=NOON)
            for reason in ("first", "second", "third")]
    assert [path.name for path in made] == [
        "2026-03-04-publish-episode-12.toml", "2026-03-04-publish-episode-12-2.toml",
        "2026-03-04-publish-episode-12-3.toml",
    ]
    assert [read(path)["reason"] for path in made] == ["first", "second", "third"]


def test_a_name_held_by_a_link_that_leads_nowhere_is_not_taken_again(tmp_path: Path) -> None:
    (tmp_path / "grants").mkdir()
    (tmp_path / "grants" / "2026-03-04-publish-x.toml").symlink_to(tmp_path / "nowhere.toml")
    path = grants.new_grant(tmp_path, "publish", "x", granted_by="owner", reason="r", now=NOON)
    assert path.name == "2026-03-04-publish-x-2.toml" and not (tmp_path / "nowhere.toml").exists()


def test_the_date_in_a_grants_name_is_the_utc_date(tmp_path: Path) -> None:
    late = dt.datetime(2026, 3, 4, 23, 30, tzinfo=dt.timezone(dt.timedelta(hours=-7)))
    path = grants.new_grant(tmp_path, "publish", "x", granted_by="owner", reason="r", now=late)
    assert path.name == "2026-03-05-publish-x.toml"
    assert read(path)["granted_at"] == "2026-03-05T06:30:00+00:00"


@pytest.mark.parametrize("fields", [
    {"reason": ""}, {"reason": "   "}, {"granted_by": ""},
    {"ceiling": -1}, {"ceiling": float("inf")}, {"ceiling": True},
])
def test_a_grant_with_no_reason_or_no_usable_ceiling_is_not_written(tmp_path: Path, fields: dict) -> None:
    wanted = {"granted_by": "owner", "reason": "a reason", **fields}
    with pytest.raises(ValueError):
        grants.new_grant(tmp_path, "publish", "episode-12", **wanted)
    assert not (tmp_path / "grants").exists()


# -- find_grant ---------------------------------------------------------------------------------


def test_a_grant_is_found_by_its_action_and_target_and_by_nothing_looser() -> None:
    held = [
        {"action": "publish", "target": "episode-12", "granted_at": "2026-01-01T00:00:00+00:00", "reason": "old"},
        {"action": "publish", "target": "episode-12", "granted_at": "2026-02-01T00:00:00+00:00", "reason": "new"},
        {"action": "publish", "target": "episode-13", "granted_at": "2026-03-01T00:00:00+00:00"},
    ]
    assert grants.find_grant(held, "publish", "episode-12")["reason"] == "new"
    assert grants.find_grant(held, "publish", "episode-1") is None
    assert grants.find_grant(held, "spend", "episode-12") is None
    assert grants.find_grant([], "publish", "episode-12") is None


def test_a_grant_marked_spent_is_not_found_again() -> None:
    spent = {"action": "publish", "target": "x", "granted_at": "2026-02-01", "spent_at": "2026-02-02"}
    fresh = {"action": "publish", "target": "x", "granted_at": "2026-01-01"}
    assert grants.find_grant([spent], "publish", "x") is None
    assert grants.find_grant([spent, fresh], "publish", "x") is fresh


def test_a_written_grant_is_found_among_the_projects_records(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.manifest('[project]\nname = "demo"\n')
    path = grants.new_grant(tmp_path, "publish", "episode-12", granted_by="owner", reason="reviewed", now=NOON)
    manifest = manifests.load(tmp_path)
    held = records.load_kind(tmp_path, manifest, "grant", ["themis.toml", path.relative_to(tmp_path).as_posix()])
    found = grants.find_grant(held, "publish", "episode-12")
    assert found is not None and found.id == path.stem and not found.problems
    assert grants.grant_id(found) == grants.grant_id(path) == grants.grant_id(path.stem) == path.stem


# -- record_action ------------------------------------------------------------------------------


def test_an_action_receipt_names_the_grant_by_its_id_and_holds_only_what_was_given(tmp_path: Path) -> None:
    grant = grants.new_grant(tmp_path, "spend", "ads", granted_by="owner", reason="r", ceiling=50, unit="credits",
                             now=NOON)
    path = grants.record_action(tmp_path, "spend", "ads", grant=grant, amount=12.5, unit="credits", by="writer",
                                now=NOON)
    assert path.relative_to(tmp_path).as_posix() == "receipts/action/2026-03-04-120000-spend-ads.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "kind": "action", "action": "spend", "target": "ads", "at": "2026-03-04T12:00:00+00:00",
        "grant": "2026-03-04-spend-ads", "amount": 12.5, "unit": "credits", "by": "writer",
    }
    bare = grants.record_action(tmp_path, "render", "episode-12", now=NOON)
    assert set(json.loads(bare.read_text(encoding="utf-8"))) == {"kind", "action", "target", "at"}
    assert {receipt["action"] for receipt in receipts.read_all(tmp_path, "action")} == {"spend", "render"}


def test_a_second_action_in_the_same_second_keeps_both_receipts(tmp_path: Path) -> None:
    first = grants.record_action(tmp_path, "publish", "x", now=NOON)
    second = grants.record_action(tmp_path, "publish", "x", now=NOON)
    assert first != second and first.is_file() and second.is_file()
    assert len(receipts.read_all(tmp_path, "action")) == 2


def test_an_action_with_no_name_or_an_amount_that_is_no_number_is_not_recorded(tmp_path: Path) -> None:
    for call in (lambda: grants.record_action(tmp_path, "", "x"), lambda: grants.record_action(tmp_path, "spend", " "),
                 lambda: grants.record_action(tmp_path, "spend", "x", amount=float("nan"))):
        with pytest.raises(ValueError):
            call()
    assert not (tmp_path / "receipts").exists()


# -- new_attestation ----------------------------------------------------------------------------


def test_an_attestation_holds_the_hash_of_the_file_as_it_is_now(tmp_path: Path) -> None:
    subject = tmp_path / "work" / "plan.md"
    subject.parent.mkdir()
    subject.write_bytes(b"the plan\n")
    path = grants.new_attestation(tmp_path, "work/plan.md", "plan-signed", "owner", "owner", now=NOON)
    assert path.relative_to(tmp_path).as_posix() == "attestations/2026-03-04-work-plan-md-plan-signed.toml"
    data = read(path)
    assert data == {"subject": "work/plan.md", "row": "plan-signed", "judge": "owner", "by": "owner",
                    "at": "2026-03-04T12:00:00+00:00", "sha256": hashlib.sha256(b"the plan\n").hexdigest()}
    assert problems("attestation", data) == []


def test_an_attestation_keeps_its_note_its_author_and_what_was_shown(tmp_path: Path) -> None:
    (tmp_path / "result.md").write_text("42\n", encoding="utf-8")
    data = read(grants.new_attestation(tmp_path, "./result.md", "second-read", "reader", "editor", note="agrees",
                                       author="writer", shown=["question.md", "data/input.csv"], now=NOON))
    assert (data["subject"], data["note"], data["author"]) == ("result.md", "agrees", "writer")
    assert data["shown"] == ["question.md", "data/input.csv"]
    assert problems("attestation", data) == []


def test_a_subject_is_recorded_under_the_name_it_was_given(tmp_path: Path) -> None:
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "plan.md").write_bytes(b"the plan\n")
    (tmp_path / "latest.md").symlink_to(tmp_path / "work" / "plan.md")
    for given, kept in (("latest.md", "latest.md"), ("work/../work/./plan.md", "work/plan.md"),
                        (str(tmp_path / "work" / "plan.md"), "work/plan.md")):
        data = read(grants.new_attestation(tmp_path, given, "plan-signed", "owner", "owner", now=NOON))
        assert (data["subject"], data["sha256"]) == (kept, hashlib.sha256(b"the plan\n").hexdigest())


def test_a_file_judged_twice_has_two_attestations(tmp_path: Path) -> None:
    (tmp_path / "plan.md").write_text("one\n", encoding="utf-8")
    first = grants.new_attestation(tmp_path, "plan.md", "plan-signed", "owner", "owner", now=NOON)
    (tmp_path / "plan.md").write_text("two\n", encoding="utf-8")
    second = grants.new_attestation(tmp_path, "plan.md", "plan-signed", "owner", "owner", now=NOON)
    assert first != second and read(first)["sha256"] != read(second)["sha256"]


@pytest.mark.parametrize("subject", ["missing.md", "work", "../outside.md"])
def test_a_subject_that_is_not_a_file_in_the_repository_cannot_be_attested(tmp_path: Path, subject: str) -> None:
    root = tmp_path / "repo"
    (root / "work").mkdir(parents=True)
    (tmp_path / "outside.md").write_text("x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="is not a file in this repository"):
        grants.new_attestation(root, subject, "plan-signed", "owner", "owner")
    assert not (root / "attestations").exists()


# -- the gates accept what the library writes ---------------------------------------------------


def test_the_grant_gate_passes_a_grant_and_a_receipt_the_library_wrote(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.manifest("""
        [rules."grant/required"]
        guarded = ["spend"]

        [rules."grant/ceiling"]
        spending = ["spend"]
    """)
    grant = grants.new_grant(tmp_path, "spend", "ads", granted_by="owner", reason="one test run", ceiling=50,
                             unit="credits", now=NOON)
    grants.record_action(tmp_path, "spend", "ads", grant=grant, amount=40, unit="credits", now=NOON)
    for rule_id in ("grant/required", "grant/single-use", "grant/ceiling"):
        assert proofs.judge(tmp_path, rule_id).verdict is Verdict.PASS, rule_id
    grants.record_action(tmp_path, "spend", "ads", grant=grant, amount=60, unit="credits", now=NOON)
    assert proofs.judge(tmp_path, "grant/single-use").verdict is Verdict.FAIL
    assert proofs.judge(tmp_path, "grant/ceiling").verdict is Verdict.FAIL


def test_the_attest_gate_passes_an_attestation_the_library_wrote_until_the_file_changes(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.manifest('[project]\nname = "demo"\n')
    world.write("work/plan.md", "the plan\n")
    grants.new_attestation(tmp_path, "work/plan.md", "plan-signed", "owner", "owner", now=NOON)
    assert proofs.judge(tmp_path, "attest/bound").verdict is Verdict.PASS
    world.write("work/plan.md", "the plan, edited\n")
    assert proofs.judge(tmp_path, "attest/bound").verdict is Verdict.REFUSE
