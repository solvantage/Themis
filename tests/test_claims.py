"""The claims library: tags, the numbers that have none, precision, and citing a record."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from themis import claims, work
from themis.claims import Tag

TAGGED = "The half-size stop gave an uplift of **+3.7 pp**<!--t:open-drive#uplift_half_stop-->."
METRICS = {"uplift_half_stop": 3.6953, "trades": 23656, "net_ev": {"value": 0.125, "unit": "R"}}
INSIDE = "results/metrics.json"
KEPT = "results/provenance.json"


def numbers(text: str) -> list[str]:
    return [number for _, number in claims.untagged_numbers(text)]


def project(tmp_path: Path, metrics: object = METRICS) -> dict[str, list[str]]:
    """One unit of work on disk with its metrics; returns the units as `work.units` does."""
    path = tmp_path / "work/open-drive" / INSIDE
    path.parent.mkdir(parents=True)
    path.write_text(metrics if isinstance(metrics, str) else json.dumps(metrics), encoding="utf-8")
    return work.units([f"work/open-drive/{INSIDE}"], "work/*")


# --- tags --------------------------------------------------------------------------------------


def test_a_tag_is_read_with_its_line_its_record_and_the_number_before_it() -> None:
    assert claims.find_tags("Results\n\n" + TAGGED) == [Tag(3, "open-drive", "uplift_half_stop", None, "+3.7")]


@pytest.mark.parametrize(
    ("written", "number"),
    [
        ("3.7", "3.7"), ("**3.7**", "3.7"), ("_3.7_", "3.7"), ("`23,656`", "23,656"), ("**`3.7`**", "3.7"),
        ("-0.25", "-0.25"), ("\u22120.25", "\u22120.25"), ("+3.7 pp", "+3.7"), ("3.7pp", "3.7"), ("45%", "45"),
        ("1.8x", "1.8"), ("12 trades", "12"), ("$1,204", "1,204"), (".5", ".5"), ("1,234,567.25", "1,234,567.25"),
    ],
)
def test_the_number_before_a_tag_is_read_through_bold_code_signs_and_units(written: str, number: str) -> None:
    (tag,) = claims.find_tags(f"It gave {written}<!--t:open-drive#uplift-->.")
    assert tag.number == number
    assert numbers(f"It gave {written}<!--t:open-drive#uplift-->.") == []


@pytest.mark.parametrize("written", ["a large gain", "v2", "3.7 percentage points", "3.7 (net)", "3.7<!--t:a#b-->"])
def test_a_tag_with_no_number_right_before_it_holds_none(written: str) -> None:
    assert claims.find_tags(f"It gave {written}<!--t:open-drive#uplift-->.")[-1].number is None


def test_a_flag_word_after_the_key_is_kept() -> None:
    (tag,) = claims.find_tags("3.7<!-- t:open-drive#net-ev stale -->")
    assert (tag.work, tag.key, tag.flag) == ("open-drive", "net-ev", "stale")


def test_a_tag_shown_inside_code_is_not_a_tag() -> None:
    assert claims.find_tags("Write `3.7<!--t:open-drive#uplift-->`.\n\n```\n3.7<!--t:open-drive#uplift-->\n```\n") == []


def test_a_tag_with_no_key_is_not_a_tag_so_its_number_stays_untagged() -> None:
    assert claims.find_tags("3.7<!--t:open-drive-->") == []
    assert numbers("3.7<!--t:open-drive-->") == ["3.7"]


def test_a_decision_tag_is_found_with_its_line_outside_code() -> None:
    text = "Decision: keep<!--d:open-drive-->.\n`<!--d:in-code-->`\nAgain<!-- d:2026-11-20_close-drive -->"
    assert claims.find_decisions(text) == [(1, "open-drive"), (3, "2026-11-20_close-drive")]


# --- numbers with no tag -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("An uplift of 3.7 pp.", ["3.7"]), ("It took 12 trades.", ["12"]), ("The 2nd run, in 2026.", ["2", "2026"]),
        ("Up 45%, then -0.25 and \u22120.5.", ["45", "-0.25", "\u22120.5"]), ("1,204 pass / 3 skip", ["1,204", "3"]),
        ("A 3:1 ratio, N=1204, (3.7), about .5", ["3", "1", "1204", "3.7", ".5"]), ("| 1 | 2.5x |", ["1", "2.5"]),
        ("from 3-5 days", ["3", "5"]), ("[run 7](docs/run.md)", ["7"]), ("## Results for 40 runs", ["40"]),
    ],
)
def test_a_bare_number_in_prose_is_a_claim(text: str, found: list[str]) -> None:
    assert numbers(text) == found


def test_each_number_is_reported_with_its_line() -> None:
    assert claims.untagged_numbers("one\n\nAn uplift of 3.7 pp\nover 12 days.") == [(3, "3.7"), (4, "12")]


def test_a_tag_covers_its_own_number_and_no_other() -> None:
    assert numbers("An uplift of 3.7<!--t:open-drive#uplift--> pp in 12 days.") == ["12"]


def test_digits_joined_to_a_word_are_part_of_the_word() -> None:
    assert numbers("v2 of sha256, as utf-8, at p95 on x86_64, see EXP-12, run_3 and report.v3") == []


def test_emphasis_marks_do_not_hide_a_number() -> None:
    assert numbers("Up _3.7_ pp, then __12__, *5* and **7**.") == ["3.7", "12", "5", "7"]


#: For each entry of claims.EXEMPT, text it sets aside. With that entry taken out, each one is flagged.
EXEMPT_CASES = {
    "link definition": ["[plan]: docs/2026/plan.md", '[2]: <docs/2026/plan.md> "Plan 7"'],
    "link target": ["[the plan](docs/2026/plan.md)", '![chart](charts/2026.png "Chart 7")', "[a](<docs/run 7.md>)"],
    "link label": ["[the plan][2]", "As shown[^3]."],
    "url": ["See https://example.invalid/2026/11 today.", "<mailto:2026@example.invalid>", "www.example.invalid/7"],
    "date": ["On 2026-11-16.", "At 2026-11-16T15:20:00+00:00.", "The unit 2026-11-20_open-drive.",
             "2026-11-16 15:20"],
    "time": ["At 15:20.", "At 08:20 UTC.", "At 9:05:30, then 08:20 UTC+7."],
    "version": ["Release 1.2.3.", "From 0.2.0 to 10.15.7.1"],
    "commit id": ["`main` at 079faaf.", "See 8e7a240 and 0123456789abcdef0123456789abcdef01234567."],
    "record id": ["Merged in #42.", "See (#7) and issue #1204"],
    "heading number": ["## 3. Title", "### 3.2. Title", "# 4) Title"],
    "list number": ["1. first", "  2) second", "> 3. quoted"],
}


def test_every_exemption_has_a_case() -> None:
    assert set(EXEMPT_CASES) == set(claims.EXEMPT)


@pytest.mark.parametrize(("name", "text"), [(name, text) for name, texts in EXEMPT_CASES.items() for text in texts])
def test_an_exemption_is_why_its_case_is_no_claim(name: str, text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    assert numbers(text) == []
    monkeypatch.setattr(claims, "EXEMPT", {key: pattern for key, pattern in claims.EXEMPT.items() if key != name})
    assert numbers(text) != [], f"{text!r} passes without the {name} exemption, so it does not test it"


@pytest.mark.parametrize(
    "text",
    ["```\nuplift = 3.7\n```", "~~~text\n12 trades\n~~~", "Run `step 4` with `--runs 40`.", "<!-- 40 runs -->",
     "<!--\nan uplift of 3.7\n-->", "3.7<!--t:open-drive#uplift--> <!--r:suite/079faaf-->"],
)
def test_code_and_html_comments_hold_no_claim(text: str) -> None:
    assert numbers(text) == []


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Run 1234567 passed.", ["1234567"]),  # hex digits with no letter: a number, not a commit id
        ("It needs 3.11 or later.", ["3.11"]),  # one dot is a decimal, not a version
        ("At 25:00, a 30:70 split.", ["25", "00", "30", "70"]),  # not times of day
        ("On 2026-13-45.", ["2026", "13", "45"]),  # not a date
        ("## 5 results", ["5"]), ("### 3.2 Title", ["3.2"]),  # a heading number ends with . or )
        ("[^3]: The uplift was 3.7 pp.", ["3.7"]),  # a footnote's text is prose
        ("[Note]: the uplift was 3.7 pp.", ["3.7"]),  # so is a line that only starts like a link definition
        ("The trade count was\n23656. That is a lot.", ["23656"]),  # a wrapped line of a paragraph is not a list
        ("- The trade count was\n  23656. That is a lot.", ["23656"]), ("1. It took\n   12. Then more.", ["12"]),
        ("```\ncode\n```\nThen 3.7 pp.", ["3.7"]), ("An open <!-- comment 5", ["5"]), ("A stray ` and 5.", ["5"]),
        ("The 1st of 3 runs.", ["1", "3"]),  # ordinals and small counts are numbers
    ],
)
def test_an_exemption_is_no_wider_than_it_says(text: str, found: list[str]) -> None:
    assert numbers(text) == found


def test_list_numbers_are_exempt_wherever_a_list_item_can_start() -> None:
    nested = "1. first\n   wrapped on\n2. second\n   1. nested\n   2. nested\n3. third"
    assert numbers(f"Steps:\n\n{nested}\n\n4. fourth\n## Next\n5. fifth") == []
    assert numbers("> 1. quoted\n> 2. quoted\n\n  7) indented") == []


def test_governed_lines_are_every_line_or_only_those_under_the_named_headings() -> None:
    text = "# Report\nx\n## 2. **Decision**\ny\n### Detail\nz\n## Next\nw\n```\n## Decision\n```"
    assert claims.governed_lines(text) == set(range(1, 12))
    assert claims.governed_lines(text, ["decision"]) == {3, 4, 5, 6}
    assert claims.governed_lines(text, ["Report"]) == set(range(1, 12))
    assert claims.governed_lines(text, ["Verdict"]) == set()


# --- precision ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "value", "same"),
    [
        ("3.7", 3.6953, True), ("3.7", 3.76, False), ("23,656", 23656, True),  # the three cases of the design
        ("+3.7", 3.6953, True), ("-3.7", 3.6953, False), ("3.7", -3.6953, False), ("\u22123.7", -3.6953, True),
        ("3.70", 3.6953, True), ("3.69", 3.6953, False), ("3.695", 3.6953, True), ("3.6953", 3.6953, True),
        ("4", 3.6953, True), ("3", 3.6953, False), ("23,656.0", 23656, True), ("1,204", 1204.4, True),
        ("0.13", 0.125, True), ("0.12", 0.125, True), ("0.14", 0.125, False),  # exactly half way: either way
        ("2.68", 2.675, True), ("2.67", 2.675, True), ("2.66", 2.675, False), (".5", 0.5, True), ("0.0", -0.04, True),
        ("three", 3.0, False), ("3.7", float("nan"), False), ("1", True, False), ("3.7", "3.7", False),
    ],
)
def test_a_written_number_matches_the_metric_at_the_precision_shown(written: str, value: object, same: bool) -> None:
    assert claims.matches(written, value) is same


@pytest.mark.parametrize(
    ("value", "decimals", "text"),
    [
        (3.6953, None, "3.6953"), (3.69531234, None, "3.6953"), (3.7, None, "3.7"), (3.0, None, "3"),
        (23656, None, "23656"), (-0.25, None, "-0.25"), (0.0123456, None, "0.01235"), (0.05, None, "0.05"),
        (1e22, None, "1" + "0" * 22), (3.6953, 1, "3.7"), (3.6953, 2, "3.70"), (3, 1, "3.0"), (-0.001, 2, "0.00"),
        (2.675, 2, "2.68"), (23656.4, 0, "23656"),
    ],
)
def test_a_number_is_written_at_its_own_precision_or_as_asked(value: float, decimals: int | None, text: str) -> None:
    assert claims.format_number(value, decimals) == text


def test_a_number_that_cannot_be_written_is_refused() -> None:
    for value in (float("inf"), float("nan"), True, "3.7"):
        with pytest.raises(ValueError):
            claims.format_number(value)
    with pytest.raises(ValueError):
        claims.format_number(3.7, -1)


@pytest.mark.parametrize("value", [3.6953, -3.6953, 0.125, 2.675, 23656, 0.000012345, 1204.5, 0.0, 99.99995, 1e-9])
def test_whatever_is_written_matches_the_metric_it_came_from(value: float) -> None:
    for decimals in (None, 0, 1, 2, 4):
        assert claims.matches(claims.format_number(value, decimals), value)


# --- records and cite --------------------------------------------------------------------------


def test_a_metric_is_a_bare_number_or_a_table_with_a_value(tmp_path: Path) -> None:
    project(tmp_path, {**METRICS, "label": "half", "ok": True, "empty": {"unit": "R"}, "bad": float("nan")})
    assert claims.load_metrics(tmp_path, "work/open-drive", INSIDE) == {
        "uplift_half_stop": 3.6953, "trades": 23656, "net_ev": 0.125,
    }


@pytest.mark.parametrize(
    ("metrics", "inside", "said"),
    [("{}", "results/other.json", "is missing"), ("uplift: 3.7", INSIDE, "cannot be read as JSON"),
     ("[1, 2]", INSIDE, "is not a JSON object"), ("{}", "../../themis.toml", "points outside its unit")],
)
def test_metrics_that_cannot_be_read_say_why(tmp_path: Path, metrics: str, inside: str, said: str) -> None:
    project(tmp_path, metrics)
    with pytest.raises(ValueError, match=said):
        claims.load_metrics(tmp_path, "work/open-drive", inside)


def test_a_unit_is_named_by_its_folder_and_two_cannot_share_a_name() -> None:
    assert claims.unit_names(["work/open-drive", "work/2026-11-20_close-drive/"]) == {
        "open-drive": "work/open-drive", "2026-11-20_close-drive": "work/2026-11-20_close-drive/",
    }
    with pytest.raises(ValueError, match="share a folder name"):
        claims.unit_names(["alpha/work", "beta/work"])


def test_cite_writes_the_number_with_its_tag_and_the_pair_reads_back(tmp_path: Path) -> None:
    units = project(tmp_path)
    assert claims.cite(tmp_path, units, "open-drive", "uplift_half_stop", INSIDE) == (
        "3.6953<!--t:open-drive#uplift_half_stop-->"
    )
    cited = claims.cite(tmp_path, units, "open-drive", "uplift_half_stop", INSIDE, decimals=1)
    assert cited == "3.7<!--t:open-drive#uplift_half_stop-->"
    assert claims.cite(tmp_path, units, "open-drive", "net_ev", INSIDE, decimals=2) == "0.13<!--t:open-drive#net_ev-->"
    (tag,) = claims.find_tags(f"An uplift of {cited} pp.")
    assert tag == Tag(1, "open-drive", "uplift_half_stop", None, "3.7")
    assert claims.matches(tag.number, claims.resolve(tmp_path, claims.unit_names(units), tag.work, tag.key, INSIDE))
    assert numbers(f"An uplift of {cited} pp.") == []


@pytest.mark.parametrize(
    ("unit", "key", "said"),
    [("open-drvie", "uplift_half_stop", "no unit of work has the folder name open-drvie"),
     ("open-drive", "uplift_full_stop", "hold no number under the key uplift_full_stop"),
     ("open-drive", "win rate", "cannot be written in a tag")],
)
def test_cite_refuses_a_work_or_a_key_it_cannot_find_or_write(tmp_path: Path, unit: str, key: str, said: str) -> None:
    units = project(tmp_path, {**METRICS, "win rate": 0.5})
    with pytest.raises(ValueError, match=said):
        claims.cite(tmp_path, units, unit, key, INSIDE)


def fingerprint(tmp_path: Path, inputs: object) -> None:
    project(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data/fills.csv").write_bytes(b"day,fill\r\n1,10.5\r\n")
    (tmp_path / "work/open-drive" / KEPT).write_text(json.dumps({"inputs": inputs}), encoding="utf-8")


def test_an_input_is_compared_by_the_sha256_of_its_bytes(tmp_path: Path) -> None:
    digest = hashlib.sha256(b"day,fill\r\n1,10.5\r\n").hexdigest()
    listed = {"data/fills.csv": digest.upper(), "data/elsewhere.bin": "0" * 64, "../outside.csv": "0" * 64}
    fingerprint(tmp_path, listed)
    assert claims.load_provenance(tmp_path, "work/open-drive", KEPT) == listed
    assert claims.changed_inputs(tmp_path, "work/open-drive", KEPT) == []
    (tmp_path / "data/fills.csv").write_bytes(b"day,fill\n1,10.5\n")
    assert claims.changed_inputs(tmp_path, "work/open-drive", KEPT) == ["data/fills.csv"]


@pytest.mark.parametrize(
    ("inputs", "said"),
    [({"data/elsewhere.bin": "0" * 64}, "nothing can be compared"), ({}, "nothing can be compared"),
     (["data/fills.csv"], "has no `inputs` table"), ({"data/fills.csv": 5}, "has no `inputs` table")],
)
def test_a_fingerprint_that_compares_nothing_is_not_a_pass(tmp_path: Path, inputs: object, said: str) -> None:
    fingerprint(tmp_path, inputs)
    with pytest.raises(ValueError, match=said):
        claims.changed_inputs(tmp_path, "work/open-drive", KEPT)
    with pytest.raises(ValueError, match="is missing"):
        claims.changed_inputs(tmp_path, "work/open-drive", "results/none.json")


# --- links and citation lines ------------------------------------------------------------------


def test_links_are_found_with_their_lines_outside_code_and_comments() -> None:
    text = ('See [a](docs/a.md#top), ![chart](<my chart.png> "t") and [b](https://example.invalid).\n'
            "`[c](in-code.md)` <!-- [d](in-comment.md) -->\n[ref]: ../x.md\n[^1]: a footnote, not a link\n"
            "[Note]: prose, not a link")
    assert claims.find_links(text) == [
        (1, "docs/a.md#top"), (1, "my chart.png"), (1, "https://example.invalid"), (3, "../x.md"),
    ]


@pytest.mark.parametrize(
    ("target", "path"),
    [
        ("plan.md", "docs/notes/plan.md"), ("./plan.md#goal", "docs/notes/plan.md"), ("../plan.md", "docs/plan.md"),
        ("../../work/open-drive/", "work/open-drive"), ("/README.md", "README.md"), ("../..", ""),
        ("a%20b.md?raw=1", "docs/notes/a b.md"), ("../../../outside.md", "../outside.md"),
        ("#top", None), ("https://example.invalid/a", None), ("mailto:owner@example.invalid", None), ("//host/a", None),
    ],
)
def test_a_link_is_resolved_from_its_documents_folder(target: str, path: str | None) -> None:
    assert claims.link_path("docs/notes/status.md", target) == path


@pytest.mark.parametrize(
    ("text", "word", "held"),
    [
        ("on 2026-03-02 (edge, version 2)", "2", True), ("on 2026-03-02 (edge v2)", "2", True),
        ("on 2026-03-02 (edge)", "2", False), ("at 15:02 with 2.5 and #2 and rev2", "2", False),
        ("decided 2026-03-02T10:00Z", "2026-03-02", True), ("decided 2026-03-021", "2026-03-02", False),
        ("Provisional: keep", "provisional", True), ("not provisionally", "provisional", False),
        ("anything", " ", False),
    ],
)
def test_a_word_is_held_only_on_its_own(text: str, word: str, held: bool) -> None:
    assert claims.has_word(text, word) is held


def test_a_citation_line_is_read_without_its_comments_and_a_stamp_gives_its_date() -> None:
    assert "2026" not in claims.line_text("x\nkeep<!--d:2026-03-02_open-drive-->.", 2)
    assert claims.line_text("x", 5) == ""
    assert claims.date_of("2026-03-02T10:00:00+00:00") == "2026-03-02"
    assert claims.date_of("last spring") is None and claims.date_of("2026-13-02") is None
