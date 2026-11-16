"""The pack test kit: what every pack must satisfy before its rules are trusted.

`problems(pack)` returns every way a pack falls short of the contract. An empty list means the
pack may be used. `themis prove` runs the kit on each pack a project turns on, and a test runs it
on every pack shipped with Themis.

The contract:

- every rule has a one-sentence promise;
- every rule has a planted fault it fails on and an honest case it passes;
- every parameter says what it is for, and its stricter direction is one Themis knows;
- every standard names rules and parameters that exist;
- every gate function has a version, a noise case and a planted case, so it can be calibrated.
"""

from __future__ import annotations

from themis import proofs
from themis.pack import Pack
from themis.rule import DIRECTIONS, RULES


def rules_of(pack: Pack) -> list[str]:
    return sorted(rule_id for rule_id, rule in RULES.items() if rule.pack == pack.name)


def problems(pack: Pack) -> list[str]:
    found = []
    for rule_id in rules_of(pack):
        rule = RULES[rule_id]
        if not rule.promise.strip().endswith("."):
            found.append(f"{rule_id}: the promise must be one full sentence")
        standing = proofs.standing(rule_id)
        if standing != "proven":
            found.append(f"{rule_id}: {standing}")
        for param in rule.params:
            if not param.help.strip():
                found.append(f"{rule_id}: the parameter {param.name} has no line of help")
            if param.stricter not in DIRECTIONS:
                found.append(f"{rule_id}: the parameter {param.name} has an unknown stricter direction")
    for standard in pack.standards.values():
        for rule_id in standard.levels:
            if rule_id not in RULES:
                found.append(f"standard {standard.id}: there is no rule {rule_id}")
        for rule_id, floors in standard.floors.items():
            rule = RULES.get(rule_id)
            if rule is None:
                found.append(f"standard {standard.id}: there is no rule {rule_id}")
                continue
            for name in floors:
                param = rule.param(name)
                if param is None:
                    found.append(f"standard {standard.id}: {rule_id} has no parameter {name}")
                elif param.stricter is None:
                    found.append(f"standard {standard.id}: {rule_id}.{name} has no stricter direction, so it cannot have a floor")
    for gate in sorted(pack.gates):
        if gate not in pack.gate_versions:
            found.append(f"gate {gate}: it has no version")
        kinds = {case.kind for case in pack.calibrations if case.gate == gate}
        if "noise" not in kinds:
            found.append(f"gate {gate}: no noise case, so it is never shown to say no")
        if "planted" not in kinds:
            found.append(f"gate {gate}: no planted case, so it is never shown to say yes")
    for case in pack.calibrations:
        if case.gate not in pack.gates:
            found.append(f"calibration {case.name!r}: there is no gate {case.gate}")
    return found


def calibrate(pack: Pack, gate: str) -> dict[str, object]:
    """Run a gate's calibration cases. The false-alarm rate is the worst noise case; the power is
    the worst planted case."""
    cases = [case for case in pack.calibrations if case.gate == gate]
    measured = [{"name": case.name, "kind": case.kind, "rate": float(case.run())} for case in cases]
    noise = [item["rate"] for item in measured if item["kind"] == "noise"]
    planted = [item["rate"] for item in measured if item["kind"] == "planted"]
    return {
        "gate": gate,
        "gate_version": pack.gate_versions.get(gate, "1"),
        "pack": pack.name,
        "false_alarm_rate": max(noise) if noise else None,
        "power": min(planted) if planted else None,
        "cases": measured,
    }
