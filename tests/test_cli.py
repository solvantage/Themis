"""The skeleton command: it states its version, and a call that checked nothing is never a pass."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import publish
import themis
from themis.cli import EXIT_REFUSE, main

ROOT = Path(__file__).resolve().parents[1]


def test_version_flag_prints_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["--version"])
    assert stopped.value.code == 0
    assert capsys.readouterr().out.strip() == f"themis {themis.__version__}"


def test_a_bare_call_refuses(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_REFUSE
    assert "nothing was checked" in capsys.readouterr().err


def test_the_version_has_one_home() -> None:
    """pyproject.toml must not restate the version; the pipeline and the package read one line."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert "version" not in project
    assert "version" in project["dynamic"]
    init_text = (ROOT / publish.VERSION_FILE).read_text(encoding="utf-8")
    assert publish.read_version(init_text) == themis.__version__
