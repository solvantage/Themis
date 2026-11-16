"""Standards: the floor a project says it holds, and where it sits below it.

A pack publishes a standard: the level each rule must have, and the weakest value each parameter
may take. A project may tighten anything. Where it sits below the floor, that is a deviation: it
is listed, and it fails when the project set `strict`.
"""

from __future__ import annotations

from dataclasses import dataclass

from themis import configguard
from themis.manifest import LEVEL_RANK, Manifest
from themis.pack import Standard
from themis.rule import RULES


@dataclass(frozen=True)
class Deviation:
    rule: str
    what: str


def declared(manifest: Manifest) -> Standard | None:
    name = manifest.standard
    if not name:
        return None
    return next((loaded.standards[name] for loaded in manifest.packs if name in loaded.standards), None)


def deviations(manifest: Manifest, standard: Standard) -> list[Deviation]:
    found = []
    for rule_id, required in sorted(standard.levels.items()):
        rule = RULES.get(rule_id)
        if rule is None:
            found.append(Deviation(rule_id, "the standard names a rule that is not available"))
            continue
        level = manifest.setting(rule).level
        if LEVEL_RANK[level] < LEVEL_RANK[required]:
            found.append(Deviation(rule_id, f"level is {level}; the standard requires {required}"))
    for rule_id, floors in sorted(standard.floors.items()):
        rule = RULES.get(rule_id)
        if rule is None:
            continue
        params = manifest.setting(rule).params
        for name, floor in sorted(floors.items()):
            param = rule.param(name)
            value = params.get(name)
            if param and configguard._direction(floor, value, param.stricter) == "weakening":
                found.append(Deviation(rule_id, f"{name} = {value!r}; the floor is {floor!r}"))
    return found
