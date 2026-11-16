"""A study, as the trading pack sees it: one folder, with a fixed layout inside.

    <study>/PRE-REG.md               the seal; its frontmatter says the study's kind and its plan
    <study>/results/metrics.json     named numbers: the only numbers anyone may quote
    <study>/results/provenance.json  what produced them: inputs, commit, clean-tree flag
    <study>/results/trades.csv       the standard trade table, for a study that books trades
    <study>/results/scorecard.csv    the scorecard's lines
    <study>/results/report.html      the report
    <study>/results/explainer/index.html   one short page for a newcomer, when the study has one
    <study>/AUDIT.md                 how the independent check ended
    <study>/README.md                the verdict in plain words

The study folders are named by `work` under `[trading]` in the manifest. The trial that logs a
study is a core ledger record whose `work` is the study's folder.

Every rule of this pack reads studies through these helpers, so all of them agree on what a study
is.
"""

from __future__ import annotations

import json
from typing import Any

from themis import records, work
from themis.rule import Context

SEAL = ["PRE-REG*.md"]
RESULTS = ["results/**"]
KINDS = ("strategy", "signal", "data", "tune")
METRICS = "results/metrics.json"
PROVENANCE = "results/provenance.json"
TRADES = "results/trades.csv"
SCORECARD = "results/scorecard.csv"
REPORT = "results/report.html"
EXPLAINER = "results/explainer/index.html"
AUDIT = "AUDIT.md"
README = "README.md"


def studies(ctx: Context) -> dict[str, list[str]]:
    """Each study folder with its files. Stops the rule when the project has not said where
    studies live."""
    pattern = ctx.manifest.table("trading").get("work")
    if not pattern:
        ctx.not_configured("set work under [trading], such as work = \"research/experiments/*\"")
    try:
        return work.units(ctx.all_files, pattern)
    except ValueError as error:
        ctx.refuse(str(error), where="themis.toml")
        return {}


def has_results(unit: str, files: list[str]) -> bool:
    return bool(work.inside(unit, files, RESULTS))


def seal(ctx: Context, unit: str, files: list[str]) -> tuple[str, dict[str, Any]] | None:
    """The study's seal as (path, frontmatter), or None when it has none. A seal that cannot be
    read is refused, and None is returned."""
    found = work.inside(unit, files, SEAL)
    if not found:
        return None
    path = found[0]
    text = ctx.read(path)
    try:
        data = records.frontmatter(text or "")
    except ValueError as error:
        ctx.refuse(f"the seal's frontmatter cannot be read: {error}", where=path)
        return None
    if data is None:
        ctx.refuse("the seal has no frontmatter block", where=path,
                   fix="start the file with a block between two --- lines")
        return None
    return path, data


def kind(ctx: Context, unit: str, files: list[str]) -> str | None:
    """The study's declared kind, or None when it has no readable seal or names no kind."""
    found = seal(ctx, unit, files)
    value = found[1].get("kind") if found else None
    return value if value in KINDS else None


def read_json(ctx: Context, path: str) -> dict[str, Any] | None:
    """A JSON object from the repository. None when the file is missing; a refusal, and None, when
    it cannot be read."""
    if not ctx.exists(path):
        return None
    try:
        data = json.loads(ctx.read(path) or "")
    except json.JSONDecodeError as error:
        ctx.refuse(f"the file is not valid JSON ({error})", where=path)
        return None
    if not isinstance(data, dict):
        ctx.refuse("the file is not a JSON object", where=path)
        return None
    return data


def _by_work(found: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for record in found:
        grouped.setdefault(str(record.get("work", "")).strip("/"), []).append(record)
    return grouped


def decisions(ctx: Context) -> dict[str, list[Any]]:
    """The decision records, grouped by the study folder they name."""
    return _by_work(ctx.records("decision"))


def trials(ctx: Context) -> dict[str, list[Any]]:
    """The ledger records, grouped by the study folder they name."""
    return _by_work(ctx.records("ledger"))


def windows(ctx: Context) -> dict[str, dict[str, Any]]:
    return ctx.manifest.table("trading").get("windows", {})
