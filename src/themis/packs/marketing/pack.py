"""The marketing content pack's own object: its table in the manifest.

Every module of this pack imports `pack` from here and adds to it. Nothing here names a platform,
a language, a product category, a tool or a project: those are a project's parameters, rulebooks
and adapters.
"""

from __future__ import annotations

from typing import Any

from themis.pack import Pack, Standard, register
from themis.schema import Required

pack = register(Pack(
    name="marketing",
    schema={
        "work": str,  # the folders that each hold one content item, such as content/items/*
        "evidence": {
            "max_age_days": int,
            "page_max_age_days": {"*": int},
            "tiers": [str],
            "require": {"*": [str]},
        },
        "banned_terms": {"file": Required(str)},
        "products": {"file": Required(str)},
        "rulebooks": {"*": {
            "file": Required(str), "max_age_days": int, "applies_to": {"kind": str, "purpose": [str]},
        }},
        "purposes": {"*": {"goal": Required(str)}},
        "spend": {"unit": str, "run_ceiling": float},
        "results": {
            "min_age_days": int,
            "min_items_to_judge": int,
            "min_items_to_rank": int,
            "baseline": str,
            "second_number": str,
            "retire": {"views_below_share_of_baseline": float},
            "standout": {"views_times_baseline": float},
        },
    },
    kinds={
        "content": "one item to publish: a brief, its evidence, its checklist, its assets, a result once published",
        "research": "topic or product research: evidence rows only; it publishes nothing",
        "asset": "a reusable design: the asset, its provenance, the owner's attestation",
    },
))


#: The pages `themis report` writes: one inside each item, and one for each series.
ITEM_REPORT, SERIES_REPORTS = "report.md", "reports"


def _defaults(manifest: Any) -> dict[str, dict[str, Any]]:
    """What the core's rules mean in content work: the brief is the seal, and the pages the pack
    builds are held to the spend receipts."""
    work = manifest.table("marketing").get("work")
    if not work:
        return {}
    return {
        "order/sealed-first": {"work": work, "seal": ["brief.toml"], "results": ["assets/**", "render/**", "post.toml"]},
        "order/unchanged": {"work": work, "seal": ["brief.toml"]},
        "spend/figures-from-tools": {"documents": [f"{work.strip('/')}/{ITEM_REPORT}", f"{SERIES_REPORTS}/*.md"]},
    }


pack.defaults = _defaults

#: The floor a project holds when it declares this standard. It may tighten anything. The rules
#: named here are the ones that keep an untrue claim, an unapproved post, an unpriced spend and a
#: typed decision out; the rest stay the project's own choice.
pack.standards["themis-marketing/1"] = Standard(
    "themis-marketing/1",
    levels={rule_id: "enforce" for rule_id in (
        "config/locked", "config/no-silent-weakening", "order/sealed-first", "order/unchanged",
        "evidence/sourced", "evidence/fresh", "evidence/tier",
        "compliance/banned-terms", "compliance/source-facts", "compliance/disclosure", "compliance/checklist",
        "compliance/rulebook-dated", "publish/granted", "publish/checklist-closed",
        "spend/priced-first", "spend/figures-from-tools",
        "results/own-baseline", "results/noise-band", "results/inputs-rebuilt",
        "decision/issued-by-gate", "decision/enough-evidence", "decision/calibrated",
    )},
    floors={"decision/calibrated": {"max_false_alarm": 0.1, "min_power": 0.8}},
)
