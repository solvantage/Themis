"""The three verdicts, and what a rule reports.

PASS means the rule holds. FAIL means the evidence shows it is broken. REFUSE means the rule could
not decide: the evidence was missing, unreadable or empty. REFUSE is never a pass.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    REFUSE = "refuse"


EXIT_CODE = {Verdict.PASS: 0, Verdict.FAIL: 1, Verdict.REFUSE: 2}
_RANK = {Verdict.PASS: 0, Verdict.FAIL: 1, Verdict.REFUSE: 2}


def worst(verdicts: Iterable[Verdict]) -> Verdict | None:
    """The verdict that decides a group: REFUSE over FAIL over PASS. None for an empty group."""
    found = list(verdicts)
    return max(found, key=_RANK.__getitem__) if found else None


@dataclass(frozen=True)
class Finding:
    """One thing a rule found: a breach of the rule, or a reason it could not decide."""

    kind: str  # "breach" or "refusal"
    message: str
    where: str | None = None
    line: int | None = None
    fix: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("breach", "refusal"):
            raise ValueError("a finding is a breach or a refusal")
        if not self.message.strip():
            raise ValueError("a finding always says what was found")
