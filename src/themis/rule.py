"""Rules, their parameters and their proofs, and the context a rule reads a repository through.

A rule is a function that looks at a repository and reports what it finds. It never changes what
it checks. It is registered with an id, a one-line promise and its parameters, and it must come
with proofs: at least one planted violation it fails on, and one honest case it passes.
"""

from __future__ import annotations

import datetime as dt
import functools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from themis import paths
from themis.gitlog import Git
from themis.verdict import Finding, Verdict

if TYPE_CHECKING:
    from themis.manifest import Manifest

#: Which way a parameter tightens a rule. None means neither way: the value is neutral.
DIRECTIONS = {"lower", "higher", "smaller", "larger", "earlier", None}


@dataclass(frozen=True)
class Param:
    name: str
    spec: Any  # a spec of themis.schema
    default: Any = None
    stricter: str | None = None
    help: str = ""

    def __post_init__(self) -> None:
        if self.stricter not in DIRECTIONS:
            raise ValueError(f"{self.name}: stricter must be one of {sorted(d for d in DIRECTIONS if d)} or None")


@dataclass(frozen=True)
class Rule:
    id: str
    promise: str
    func: Callable[[Context], None]
    params: tuple[Param, ...] = ()
    requires: tuple[str, ...] = ()  # parameters that must be set before the rule can run
    pack: str = "core"
    learned: str = ""  # the incident behind the rule, in one line

    @property
    def gate(self) -> str:
        return self.id.split("/", 1)[0]

    def param(self, name: str) -> Param | None:
        return next((param for param in self.params if param.name == name), None)


@dataclass(frozen=True)
class Proof:
    """A small world built for one rule, and the verdict the rule must reach in it."""

    rule: str
    name: str
    expect: Verdict
    build: Callable[[Any], None]
    contains: str | None = None  # text the finding must hold, so the rule fails for the planted reason


RULES: dict[str, Rule] = {}
PROOFS: dict[str, list[Proof]] = {}


def rule(
    id: str, promise: str, *, params: tuple[Param, ...] = (), requires: tuple[str, ...] = (),
    pack: str = "core", learned: str = "",
) -> Callable[[Callable[[Context], None]], Callable[[Context], None]]:
    """Register a rule. Its id is `gate/name`."""

    def register(func: Callable[[Context], None]) -> Callable[[Context], None]:
        if id.count("/") != 1 or not all(id.split("/")):
            raise ValueError(f"a rule id is gate/name, not {id!r}")
        if id in RULES:
            raise ValueError(f"the rule id {id} is already taken")
        if not promise.strip():
            raise ValueError(f"{id} needs a one-line promise")
        unknown = [name for name in requires if all(param.name != name for param in params)]
        if unknown:
            raise ValueError(f"{id} requires parameters it does not declare: {unknown}")
        RULES[id] = Rule(id=id, promise=promise, func=func, params=tuple(params), requires=tuple(requires),
                         pack=pack, learned=learned)
        return func

    return register


def proof(
    rule_id: str, name: str, *, expect: str, contains: str | None = None
) -> Callable[[Callable[[Any], None]], Callable[[Any], None]]:
    """Register a proof for a rule: `expect` is "pass", "fail" or "refuse"."""

    def register(build: Callable[[Any], None]) -> Callable[[Any], None]:
        PROOFS.setdefault(rule_id, []).append(
            Proof(rule=rule_id, name=name, expect=Verdict(expect), build=build, contains=contains)
        )
        return build

    return register


class NotConfigured(Exception):
    """Raised by a rule when the project has not told it what to look at. The rule does not run."""


class Context:
    """What a rule may see and say. Reading goes through here; so do breaches and refusals."""

    def __init__(self, root: Path, manifest: Manifest, rule: Rule, params: dict[str, Any]) -> None:
        self.root = Path(root)
        self.manifest = manifest
        self.rule = rule
        self.params = params
        self.findings: list[Finding] = []
        self.inspected = 0

    # -- what the rule says ---------------------------------------------------------------------

    def breach(self, message: str, *, where: str | None = None, line: int | None = None, fix: str | None = None) -> None:
        self.findings.append(Finding("breach", message, where, line, fix))

    def refuse(self, message: str, *, where: str | None = None, fix: str | None = None) -> None:
        self.findings.append(Finding("refusal", message, where, None, fix))

    def inspect(self, count: int = 1) -> None:
        """Count what was looked at. A rule that looked at nothing does not pass."""
        self.inspected += count

    def not_configured(self, what: str) -> None:
        """Stop: the project has not set what this rule needs. Say what is missing."""
        raise NotConfigured(what)

    # -- what the rule sees ---------------------------------------------------------------------

    def param(self, name: str) -> Any:
        return self.params.get(name)

    @property
    def since(self) -> dt.date | None:
        """The date the rule binds from, when the project set one."""
        value = self.params.get("since")
        return dt.date.fromisoformat(value) if isinstance(value, str) else None

    @functools.cached_property
    def git(self) -> Git:
        return Git(self.root)

    @functools.cached_property
    def all_files(self) -> list[str]:
        return self.git.all_files()

    def files(self, pattern: str) -> list[str]:
        return paths.select(self.all_files, pattern)

    def exists(self, path: str) -> bool:
        return (self.root / path).is_file()

    def read(self, path: str) -> str | None:
        """The file's text, or None when it is missing or is not text."""
        try:
            return (self.root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def records(self, kind: str) -> list[Any]:
        """The project's records of one kind. An unreadable record becomes a refusal."""
        from themis import records

        found = records.load_kind(self.root, self.manifest, kind, self.all_files)
        for record in found:
            for problem in record.problems:
                self.refuse(problem, where=record.path, fix="correct the record, or restore it from git")
        return [record for record in found if not record.problems]
