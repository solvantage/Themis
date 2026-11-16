"""The releases page, the receipts, and the documents that point at them.

RELEASES.md is a view: scripts/publish.py writes it from the receipts in receipts/publish/. A view
that is edited by hand, or left behind after a release, drifts, so this file pins it to the
receipts. It also keeps a receipt from publishing a local folder name, because receipts are
committed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import publish

ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = sorted((ROOT / "receipts").rglob("*.json")) if (ROOT / "receipts").is_dir() else []


def test_the_releases_page_is_what_the_receipts_dictate() -> None:
    receipts, page = publish.load_receipts(ROOT), ROOT / publish.RELEASES_FILE
    if not receipts:
        assert not page.exists(), "RELEASES.md exists with no receipt behind it"
        return
    expected = publish.render_releases(receipts, publish.repository_url(ROOT))
    assert page.exists(), "run `uv run python scripts/publish.py --releases`"
    assert page.read_text(encoding="utf-8") == expected, "run `uv run python scripts/publish.py --releases`"


def test_the_documents_point_at_the_releases_page() -> None:
    for document in ("README.md", "DESIGN.md", "docs/publishing.md"):
        assert publish.RELEASES_FILE in (ROOT / document).read_text(encoding="utf-8"), (
            f"{document} does not point at {publish.RELEASES_FILE}"
        )


# --- a receipt never publishes a local path ----------------------------------------------------


def strings(value: object) -> list[str]:
    """Every string anywhere inside a parsed JSON value."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [found for item in value.values() for found in strings(item)]
    if isinstance(value, list):
        return [found for item in value for found in strings(item)]
    return []


def local_paths(value: object, home: str = str(Path.home())) -> list[str]:
    """The strings that are an absolute path, start at the home folder, or hold the home folder."""
    return [
        text
        for text in strings(value)
        if text.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[\\/]", text) or home in text
    ]


def test_no_committed_receipt_holds_a_local_path() -> None:
    found = {
        str(path.relative_to(ROOT)): local_paths(json.loads(path.read_text(encoding="utf-8")))
        for path in RECEIPTS
    }
    assert not {name: paths for name, paths in found.items() if paths}


def test_the_path_check_can_say_no_and_stays_quiet_on_honest_values() -> None:
    leaking = {"index": "/home/someone/project/wheelhouse", "nested": [{"where": "C:\\Users\\someone\\index"}, "~/index"]}
    assert local_paths(leaking) == ["/home/someone/project/wheelhouse", "C:\\Users\\someone\\index", "~/index"]
    assert local_paths({"note": "kept in /opt/elsewhere"}, home="/opt/elsewhere") == ["kept in /opt/elsewhere"]
    honest = {"index": "wheelhouse", "commit": "6240b4cb", "tests": {"passed": 68}, "at": "2026-11-16T04:14:56+00:00"}
    assert local_paths(honest) == []
