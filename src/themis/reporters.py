"""Reports: one run, shown four ways.

    terminal   for a person: grouped by gate, findings under the rule that raised them
    compact    one line a finding, in the shape editors read into a problems list
    json       for an agent or another tool: every rule, with why it exists and how to fix it
    sarif      the format code-analysis tools exchange; a refusal is a notification, never a result
"""

from __future__ import annotations

import json
from typing import Any

from themis.engine import Report, Result
from themis.verdict import Verdict

MARK = {Verdict.PASS: "✓", Verdict.FAIL: "✗", Verdict.REFUSE: "?"}
SHOWN_FINDINGS = 10


def _place(finding: Any) -> str:
    if not finding.where:
        return ""
    return f"{finding.where}:{finding.line}" if finding.line else finding.where


def terminal(report: Report) -> str:
    lines = [f"themis check · {report.project}", ""]
    gate = None
    for result in sorted(report.results, key=lambda result: (result.gate, result.id)):
        if result.gate != gate:
            gate = result.gate
            lines.append(f" {gate}")
        if result.status != "ran":
            lines.append(f"   - {result.id:<34} {result.status}")
            continue
        note = f"{result.inspected} inspected" if result.verdict is Verdict.PASS else result.verdict.value.upper()
        lines.append(f"   {MARK[result.verdict]} {result.id:<34} {result.level:<8} {note}")
        for finding in result.findings[:SHOWN_FINDINGS]:
            place = _place(finding)
            first, *rest = finding.message.splitlines() or [""]
            lines.append(f"       {place + '  ' if place else ''}{first}")
            lines += [f"         {line}" for line in rest]
            if finding.fix:
                lines.append(f"         fix: {finding.fix}")
        if len(result.findings) > SHOWN_FINDINGS:
            lines.append(f"       … and {len(result.findings) - SHOWN_FINDINGS} more")
    ran = [result for result in report.results if result.status == "ran"]
    enforced = [result for result in ran if result.level == "enforce"]
    quiet = len(report.results) - len(ran)
    tally = ", ".join(
        f"{sum(result.verdict is verdict for result in enforced)} {verdict.value}"
        for verdict in (Verdict.PASS, Verdict.FAIL, Verdict.REFUSE)
    )
    lines += ["", f" {len(enforced)} enforced ({tally}) · {len(ran) - len(enforced)} at warn · {quiet} not run"]
    if not enforced and ran:
        lines.append(" no rule is enforced yet, so nothing here can fail the run")
    lines.append(report.verdict.value.upper())
    return "\n".join(lines) + "\n"


def compact(report: Report) -> str:
    lines = []
    for result in report.results:
        severity = "error" if result.level == "enforce" else "warning"
        for finding in result.findings:
            place = _place(finding)
            kind = "" if finding.kind == "breach" else "could not decide: "
            message = " ".join(finding.message.split())
            lines.append(f"{place + ': ' if place else ''}{severity} themis[{result.id}]: {kind}{message}")
    return "\n".join(lines) + ("\n" if lines else "")


def _result(result: Result) -> dict[str, Any]:
    return {
        "rule": result.id,
        "gate": result.gate,
        "pack": result.pack,
        "promise": result.promise,
        "level": result.level,
        "status": result.status,
        "verdict": result.verdict.value if result.verdict else None,
        "inspected": result.inspected,
        "learned": result.learned or None,
        "findings": [
            {"kind": finding.kind, "message": finding.message, "where": finding.where, "line": finding.line,
             "fix": finding.fix}
            for finding in result.findings
        ],
    }


def as_json(report: Report) -> str:
    document = {
        "themis_report": 1,
        "project": report.project,
        "verdict": report.verdict.value,
        "exit_code": report.exit_code,
        "results": [_result(result) for result in report.results],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def sarif(report: Report) -> str:
    rules = [{"id": result.id, "shortDescription": {"text": result.promise}} for result in report.results]
    results, notices = [], []
    for result in report.results:
        for finding in result.findings:
            if finding.kind == "refusal":
                notices.append({"level": "error", "message": {"text": finding.message},
                                "associatedRule": {"id": result.id}})
                continue
            entry: dict[str, Any] = {
                "ruleId": result.id,
                "level": "error" if result.level == "enforce" else "warning",
                "message": {"text": finding.message},
            }
            if finding.where:
                region = {"startLine": finding.line} if finding.line else {}
                entry["locations"] = [{"physicalLocation": {"artifactLocation": {"uri": finding.where}, **({"region": region} if region else {})}}]
            results.append(entry)
    document = {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [{
            "tool": {"driver": {"name": "themis", "rules": rules}},
            "results": results,
            "invocations": [{"executionSuccessful": not notices, "toolExecutionNotifications": notices}],
        }],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


REPORTERS = {"terminal": terminal, "compact": compact, "json": as_json, "sarif": sarif}
