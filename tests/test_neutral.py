"""The codebase names no outside project.

DESIGN.md, section 4: the core names no field and no project, and a pack names no project. This
test keeps the second half true for every file in the repository: source, tests, scripts and
documents. A name in a comment or a document is a reference too.

The names it looks for are held only as SHA-256 hashes, so this file does not name them either.
To forbid another name: lower-case it, drop any hyphen or underscore, and add
``(len(name), sha256(name).hexdigest())`` to FORBIDDEN. A name so short that it turns up inside
longer words or encoded data goes in WHOLE_WORDS instead: it counts only as a word of its own, cut
at anything that is not a letter or a digit.
"""

from __future__ import annotations

import functools
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIPPED_FOLDERS = {".git", ".venv", "__pycache__", ".pytest_cache", "wheelhouse", "dist", "node_modules"}

#: (length of the name, SHA-256 of the name) for each outside project that must not be named here.
FORBIDDEN: frozenset[tuple[int, str]] = frozenset({
    (8, "74395936be675d5bfa62270311928d5b5670a7de6da484dcbf8535e470b75e4d"),
    (6, "752115f45427e30c230603d78fa1bf560bfea9cc378e954dfd1f571540ddc184"),
    (7, "90dfd1573ce4692f8da7f5ea8e63400399f507aef17e9fd6c6901891c5e2509b"),
    (5, "2015a1e4aebfcf6990e93533ddcb98a883cbcb111207bbdf15681495fb331459"),
    (6, "bde9289c0ed77fd308497f766f8c2afda2b119c41be2ae64e477b9a94880a31b"),
    (10, "365107e5b93c95398655f77f81f4bc3350ec04335422d2505c28a7423f6390a1"),
    (4, "00c9f2514148f9c05077cfef1129ce294a706e7db8169bba18abbc0a5c313c3d"),
})

#: The same, for names that count only as a whole word: `x-name_y` holds it, `xnamey` does not.
WHOLE_WORDS: frozenset[tuple[int, str]] = frozenset({
    (3, "7cc50a21f4fb69729aeeddfd6bb19fd9b9346ee5fcde5adf5e68c37930ee1267"),
})

WORD = re.compile(r"[a-z0-9_-]+")
PART = re.compile(r"[a-z0-9]+")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@functools.lru_cache(maxsize=None)
def names_a_project(word: str, forbidden: frozenset[tuple[int, str]]) -> bool:
    """True when the word holds a forbidden name anywhere inside it, whatever the hyphens."""
    joined = word.replace("-", "").replace("_", "")
    return any(
        digest(joined[start:start + length]) == wanted
        for length, wanted in forbidden
        for start in range(len(joined) - length + 1)
    )


@functools.lru_cache(maxsize=None)
def is_a_whole_name(part: str, whole: frozenset[tuple[int, str]]) -> bool:
    """True when the word, cut at anything that is not a letter or a digit, is a forbidden name."""
    return any(len(part) == length and digest(part) == wanted for length, wanted in whole)


def offences(text: str, forbidden: frozenset[tuple[int, str]] = FORBIDDEN,
             whole: frozenset[tuple[int, str]] = WHOLE_WORDS) -> list[int]:
    """The numbers of the lines that name a forbidden project."""
    return [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if any(names_a_project(word, forbidden) for word in WORD.findall(line.lower()))
        or any(is_a_whole_name(part, whole) for part in PART.findall(line.lower()))
    ]


def repository_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not SKIPPED_FOLDERS.intersection(path.relative_to(ROOT).parts)
    )


def test_no_file_names_an_outside_project() -> None:
    found = []
    for path in repository_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # not a text file
        found += [f"{path.relative_to(ROOT)}:{number}" for number in offences(text)]
    assert not found, "these lines name an outside project; describe the idea without the name:\n" + "\n".join(found)


def test_the_scan_covers_the_source_the_tests_and_the_documents() -> None:
    """An empty scan would pass for the wrong reason, so the scan must reach each kind of file."""
    scanned = {str(path.relative_to(ROOT)) for path in repository_files()}
    for expected in ("DESIGN.md", "README.md", "src/themis/cli.py", "scripts/publish.py", "tests/test_neutral.py"):
        assert expected in scanned


def test_the_list_of_names_was_not_emptied() -> None:
    assert len(FORBIDDEN) >= 7
    assert len(WHOLE_WORDS) >= 1


# --- the scanner can say no, shown with a made-up name -----------------------------------------

MADE_UP = frozenset({(7, digest("zorblax"))})
MADE_UP_WORD = frozenset({(3, digest("zq9"))})


def test_a_named_line_is_found_in_every_spelling() -> None:
    text = "\n".join([
        "nothing to see",              # 1
        "Lifted from Zorblax.",        # 2  a capital letter
        "see docs/zorblax.md",         # 3  inside a path
        "the zorblax-drafts folder",   # 4  joined to another word
        "import zor_blax",             # 5  split by an underscore
        "ZOR-BLAX is the donor",       # 6  split by a hyphen, in capitals
        "myzorblaxdata = 1",           # 7  inside an identifier
        "still nothing",               # 8
    ])
    assert offences(text, MADE_UP) == [2, 3, 4, 5, 6, 7]


def test_clean_text_raises_no_alarm() -> None:
    text = "A rule is code.\nzorbla and x are two words.\nThe area each rule covers.\n"
    assert offences(text, MADE_UP) == []
    assert offences(text) == []


def test_a_whole_word_name_is_found_only_as_a_word_of_its_own() -> None:
    text = "\n".join([
        "the zq9 tester",              # 1
        "see scripts/zq9-run.sh",      # 2  cut by a hyphen
        "zq9_card.py and ZQ9's",       # 3  cut by an underscore, in capitals
        "a zq9s or azq9 or zq90",      # 4  inside a longer word
        "sha 0e1fzq9a7c",              # 5  inside encoded data
    ])
    assert offences(text, frozenset(), MADE_UP_WORD) == [1, 2, 3]

