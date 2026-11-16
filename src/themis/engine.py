"""The engine: runs the rules a project has, and reaches one verdict.

A rule runs at the level its project set: `off` does not run, `warn` runs and is shown, `enforce`
runs and counts towards the verdict. A rule whose required parameters are unset is "not
configured": it does not run, and `themis describe` lists it as unproven, so its silence is never
read as a pass.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from themis import external, paths
from themis.manifest import Manifest, Setting
from themis.rule import Context, NotConfigured, Rule
from themis.verdict import EXIT_CODE, Finding, Verdict, worst


@dataclass
class Result:
    id: str
    gate: str
    promise: str
    level: str
    status: str  # "ran", "off", "not configured" or "not triggered"
    verdict: Verdict | None = None
    findings: tuple[Finding, ...] = ()
    inspected: int = 0
    seconds: float = 0.0
    pack: str = "core"
    learned: str = ""
    note: str = ""  # why the rule did not run

    @property
    def counts(self) -> bool:
        """True when this result decides the run's verdict."""
        return self.status == "ran" and self.level == "enforce"


@dataclass
class Report:
    project: str
    results: list[Result] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # why the manifest could not be used

    @property
    def verdict(self) -> Verdict:
        """REFUSE over FAIL over PASS, among the enforced rules. A run that enforced nothing passes
        only if it also ran something; a run that checked nothing at all is a REFUSE."""
        if self.problems:
            return Verdict.REFUSE
        decided = worst(result.verdict for result in self.results if result.counts and result.verdict)
        if decided is not None:
            return decided
        return Verdict.PASS if any(result.status == "ran" for result in self.results) else Verdict.REFUSE

    @property
    def exit_code(self) -> int:
        return EXIT_CODE[self.verdict]


def resolve(rule: Rule, manifest: Manifest) -> tuple[Setting, dict[str, Any]]:
    setting = manifest.setting(rule)
    params = dict(setting.params)
    if setting.since:
        params["since"] = setting.since
    return setting, params


def _decide(findings: list[Finding], inspected: int, empty: str) -> tuple[Verdict, list[Finding]]:
    if any(finding.kind == "breach" for finding in findings):
        return Verdict.FAIL, findings
    if findings:
        return Verdict.REFUSE, findings
    if inspected == 0 and empty != "allow":
        return Verdict.REFUSE, [Finding("refusal", "nothing was inspected, so the rule could not be shown to hold")]
    return Verdict.PASS, findings


def run_rule(rule: Rule, manifest: Manifest, *, force: bool = False) -> Result:
    """Run one rule. `force` runs it whatever its level, which is what a proof needs."""
    setting, params = resolve(rule, manifest)
    result = Result(id=rule.id, gate=rule.gate, promise=rule.promise, level=setting.level, status="ran",
                    pack=rule.pack, learned=rule.learned)
    if setting.level == "off" and not force:
        result.status = "off"
        return result
    unset = [name for name in rule.requires if params.get(name) in (None, "", [], {})]
    if unset:
        result.status, result.note = "not configured", f"set {', '.join(unset)} for this rule"
        return result
    context = Context(manifest.root, manifest, rule, params)
    started = time.perf_counter()
    try:
        rule.func(context)
    except NotConfigured as missing:
        result.status, result.note = "not configured", str(missing)
        return result
    except Exception as error:  # noqa: BLE001 - a rule that crashes has decided nothing
        context.findings = [Finding("refusal", f"the rule itself failed: {error.__class__.__name__}: {error}")]
    result.seconds = time.perf_counter() - started
    result.inspected = context.inspected
    result.verdict, findings = _decide(context.findings, context.inspected, setting.empty)
    result.findings = tuple(findings)
    return result


def run_external(check: external.Check, root: Path, changed: list[str] | None) -> Result:
    result = Result(id=check.id, gate="ext", promise=check.description, level=check.level, status="ran", pack="project")
    if check.level == "off":
        result.status = "off"
        return result
    if changed is not None and check.when and not any(paths.matches_any(name, check.when) for name in changed):
        result.status = "not triggered"
        return result
    started = time.perf_counter()
    outcome = external.run(check, root)
    result.seconds = time.perf_counter() - started
    result.verdict, result.findings, result.inspected = outcome.verdict, outcome.findings, 1
    return result


def run(manifest: Manifest, *, changed: list[str] | None = None, only: set[str] | None = None) -> Report:
    """Run every rule the project has. `changed` limits external checks to those whose paths moved."""
    report = Report(project=manifest.name)
    if manifest.problems:
        # A manifest that cannot be trusted decides nothing else: only config/valid speaks.
        report.problems = list(manifest.problems)
        report.results.append(Result(
            id="config/valid", gate="config", promise="The manifest matches its schema.", level="enforce",
            status="ran", verdict=Verdict.REFUSE, inspected=1,
            findings=tuple(Finding("refusal", problem, where="themis.toml") for problem in manifest.problems),
        ))
        return report
    for rule in sorted(manifest.active_rules(), key=lambda rule: rule.id):
        if only is None or rule.id in only:
            report.results.append(run_rule(rule, manifest))
    for table in manifest.external:
        check = external.Check.from_table(table)
        if only is None or check.id in only:
            report.results.append(run_external(check, manifest.root, changed))
    return report
