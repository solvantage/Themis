"""A content item, as the marketing pack sees it: one folder, with a fixed layout inside.

    <item>/brief.toml        the sealed plan: kind, purpose, series, parts, claims, how it is made
    <item>/evidence.toml     the evidence rows the brief rests on
    <item>/checklist.toml    the checklist rows, each with its judge
    <item>/plan.toml         the plan derived from the brief, which the making follows
    <item>/assets/*.toml     one note for each picture, clip or voice track that was made
    <item>/post.toml         where and when the item was published, and its disclosure settings
    <item>/result.toml       the item's numbers, read at the agreed age

The item folders are named by `work` under `[marketing]` in the manifest. Beside the items, a
project keeps a few shared files, all named in its manifest: the banned-terms list, the product
table, and one rulebook file for each checklist.

Every rule of this pack reads items through these helpers, so all of them agree on what an item
is. Each loader validates the file against its schema: a file that does not match is refused.
"""

from __future__ import annotations

import tomllib
from typing import Any

from themis import schema, work
from themis.rule import Context
from themis.schema import ANY, Choice, Required

KINDS = ("content", "research", "asset")
RESULTS = ["assets/**", "render/**", "post.toml", "result.toml"]

PART = {"id": Required(str), "start_s": Required(float), "end_s": Required(float), "text": str, "line": str}
BRIEF = {
    "kind": Required(Choice(*KINDS)),
    "title": Required(str),
    "purpose": str,
    "series": str,
    "audience": str,
    "format": str,
    "length_s": float,
    "parts": [PART],
    "claims": [{"text": Required(str), "evidence": Required(str), "kind": str}],
    "product": str,
    "made_with": {"voice": Choice("generated", "human"), "footage": Choice("generated", "filmed", "mixed")},
    "disclosure": {"*": bool},
    "caption": str,
}
EVIDENCE = {"rows": Required([{
    "id": Required(str), "finding": Required(str), "tier": Required(str), "source": Required(str),
    "retrieved": Required(str), "page_date": str, "quote": str, "topic": str,
}])}
CHECKLIST = {"rulebook": Required(str), "rows": Required([{
    "id": Required(str), "check": Required(str), "judge": Required(str), "judged_from": str, "done": bool,
}])}
PLAN = {"parts": Required([PART]), "length_s": float, "estimate": float, "unit": str, "speaking_rate": float}
ASSET = {
    "kit_item": str, "tool": Required(str), "prompt_sha256": str, "seed": int, "cost": float, "unit": str,
    "take": int, "file": str, "kind": str, "*": ANY,
}
POST = {"platform": Required(str), "at": Required(str), "grant": str, "disclosure": {"*": bool}, "url": str}
RESULT = {"read_at": Required(str), "age_days": Required(int), "source": Required(str), "metrics": Required({"*": float})}
RULEBOOK = {"entries": Required([{
    "id": Required(str), "check": Required(str), "pass_when": str, "judge": Required(str), "judged_from": str,
    "source": Required(str), "read_on": Required(str),
}])}
SERIES = {
    "audience": str, "format": str, "purpose": str, "status": Choice("active", "retired", "parked"),
    "compared_with": str, "changed": str, "kit": [str],
}

FILES = {
    "brief": ("brief.toml", BRIEF), "evidence": ("evidence.toml", EVIDENCE), "checklist": ("checklist.toml", CHECKLIST),
    "plan": ("plan.toml", PLAN), "post": ("post.toml", POST), "result": ("result.toml", RESULT),
}


def table(ctx: Context) -> dict[str, Any]:
    return ctx.manifest.table("marketing")


def items(ctx: Context) -> dict[str, list[str]]:
    """Each item folder with its files. Stops the rule when the project has not said where items
    live."""
    pattern = table(ctx).get("work")
    if not pattern:
        ctx.not_configured("set work under [marketing], such as work = \"content/items/*\"")
    try:
        return work.units(ctx.all_files, pattern)
    except ValueError as error:
        ctx.refuse(str(error), where="themis.toml")
        return {}


def read_toml(ctx: Context, path: str, spec: Any, what: str) -> dict[str, Any] | None:
    """A TOML file checked against its schema. None when it is missing; a refusal, and None, when
    it cannot be read or does not match."""
    if not ctx.exists(path):
        return None
    try:
        data = tomllib.loads(ctx.read(path) or "")
    except tomllib.TOMLDecodeError as error:
        ctx.refuse(f"the {what} is not valid TOML ({error})", where=path)
        return None
    found = schema.problems(data, spec, what)
    for problem in found:
        ctx.refuse(problem, where=path, fix=f"correct the {what}")
    return None if found else data


def load(ctx: Context, unit: str, name: str) -> dict[str, Any] | None:
    """One of an item's own files, by name: brief, evidence, checklist, plan, post or result."""
    filename, spec = FILES[name]
    return read_toml(ctx, f"{unit}/{filename}", spec, name)


def assets(ctx: Context, unit: str, files: list[str]) -> dict[str, dict[str, Any]]:
    """The item's asset notes, by path."""
    found = {}
    for path in work.inside(unit, files, ["assets/*.toml"]):
        data = read_toml(ctx, path, ASSET, "asset note")
        if data is not None:
            found[path] = data
    return found


def rulebook(ctx: Context, name: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """A rulebook as (its table in the manifest, its entries by id), or None when it is not
    declared or cannot be read."""
    declared = table(ctx).get("rulebooks", {}).get(name)
    if declared is None:
        return None
    data = read_toml(ctx, declared["file"], RULEBOOK, "rulebook")
    if data is None:
        if not ctx.exists(declared["file"]):
            ctx.refuse(f"the rulebook {name} names a file that does not exist", where=declared["file"])
        return None
    return declared, {entry["id"]: entry for entry in data["entries"]}


def series(ctx: Context, name: str, folder: str = "series") -> dict[str, Any] | None:
    """A series file, `series/<name>.toml`, or None when there is none."""
    return read_toml(ctx, f"{folder}/{name}.toml", SERIES, "series file")


def words(ctx: Context, path: str) -> list[str] | None:
    """A list file: one entry a line, blank lines and lines starting with # left out. None when
    the file is missing."""
    text = ctx.read(path)
    if text is None:
        return None
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
