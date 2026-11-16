"""Every rule's proofs hold, and every rule meets the contract.

A rule ships with small worlds built for it: honest ones it must pass, broken ones it must fail
for the planted reason. This file runs every one of them, so a new rule needs no test file of its
own. It also holds each rule to the contract: a promise, a planted fault, an honest case, and
parameters that say which way is stricter.
"""

from __future__ import annotations

import pytest

from themis import gates, pack, proofs
from themis.rule import DIRECTIONS, PROOFS, RULES

gates.load_all()
for _name in ("trading", "marketing"):
    try:
        pack.load(_name)
    except pack.PackError:
        pass  # a pack that is not built yet has nothing to prove

ALL_PROOFS = [proof for rule_id in sorted(PROOFS) for proof in PROOFS[rule_id]]


def test_every_gate_module_imports() -> None:
    assert not gates.BROKEN, gates.BROKEN


@pytest.mark.parametrize("proof", ALL_PROOFS, ids=[f"{proof.rule}: {proof.name}" for proof in ALL_PROOFS])
def test_the_proof_holds(proof) -> None:
    outcome = proofs.run_proof(proof)
    assert outcome.held, f"expected {outcome.expect.value}, got {outcome.actual}: {outcome.detail}"


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_the_rule_meets_the_contract(rule_id: str) -> None:
    rule = RULES[rule_id]
    assert rule.promise.strip().endswith("."), "a rule's promise is one full sentence"
    assert proofs.standing(rule_id) == "proven", f"{rule_id} is {proofs.standing(rule_id)}"
    for param in rule.params:
        assert param.stricter in DIRECTIONS
        assert param.help, f"{rule_id}: the parameter {param.name} needs a line of help"


def test_no_proof_is_registered_for_a_rule_that_does_not_exist() -> None:
    assert not sorted(set(PROOFS) - set(RULES))
