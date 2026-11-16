"""External checks: any command a project already has, run as a rule.

The command's exit code is mapped to a verdict. Everything that is not a clear pass or a clear
fail is a REFUSE: the program cannot start, runs past its time, is stopped by a signal, returns a
code the mapping does not name, prints more than the limit, or prints what its parser cannot read.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from themis.verdict import Finding, Verdict

OUTPUT_LIMIT = 2 * 1024 * 1024
SHOWN_LINES = 12


@dataclass(frozen=True)
class Check:
    id: str
    description: str
    command: tuple[str, ...]
    cwd: str = "."
    when: tuple[str, ...] = ()
    passes: tuple[int, ...] = (0,)
    fails: tuple[int, ...] = (1,)
    output: str | None = None
    timeout_s: int = 300
    level: str = "enforce"
    proofs: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_table(cls, table: dict[str, Any]) -> Check:
        verdicts = table.get("verdicts", {})
        return cls(
            id=table["id"], description=table["description"], command=tuple(table["command"]),
            cwd=table.get("cwd", "."), when=tuple(table.get("when", ())),
            passes=tuple(verdicts.get("pass", (0,))), fails=tuple(verdicts.get("fail", (1,))),
            output=table.get("output"), timeout_s=table.get("timeout_s", 300),
            level=table.get("level", "enforce"), proofs=tuple(table.get("proofs", ())),
        )

    def scripts(self, root: Path) -> list[str]:
        """The files of this repository that the command names: the scripts that do the judging."""
        found = []
        for word in self.command:
            candidate = (root / self.cwd / word).resolve()
            try:
                relative = candidate.relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            if candidate.is_file():
                found.append(relative)
        return found


@dataclass(frozen=True)
class Outcome:
    verdict: Verdict
    findings: tuple[Finding, ...]
    output: str


_PATH_LINE = re.compile(r"^(?P<path>[^\s:][^:]*):(?P<line>\d+):(?:\d+:)?\s*(?P<message>.+)$")


def parse_path_line_message(output: str) -> list[Finding]:
    """Lines of `path:line: message`. Lines in any other shape are left out."""
    return [
        Finding("breach", found["message"].strip(), where=found["path"], line=int(found["line"]))
        for found in (_PATH_LINE.match(line.strip()) for line in output.splitlines())
        if found
    ]


def parse_json_lines(output: str) -> list[Finding]:
    """One JSON object a line, each with `message` and optionally `path`, `line` and `fix`."""
    found = []
    for line in output.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict) or not isinstance(item.get("message"), str):
            raise ValueError("a line is not an object with a message")
        found.append(Finding("breach", item["message"], where=item.get("path"), line=item.get("line"), fix=item.get("fix")))
    return found


PARSERS = {"path-line-message": parse_path_line_message, "json-lines": parse_json_lines}


def _tail(output: str) -> str:
    lines = [line for line in output.strip().splitlines() if line.strip()]
    return "\n".join(lines[-SHOWN_LINES:])


def _refuse(message: str, output: str = "") -> Outcome:
    return Outcome(Verdict.REFUSE, (Finding("refusal", message),), output)


def run(check: Check, root: Path) -> Outcome:
    """Run the command and turn what happened into a verdict."""
    cwd = (root / check.cwd).resolve()
    if not cwd.is_dir() or root.resolve() not in (cwd, *cwd.parents):
        return _refuse(f"the folder {check.cwd} is not inside the repository")
    try:
        process = subprocess.Popen(  # noqa: S603 - the command is a list from the project's own manifest
            list(check.command), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    except (FileNotFoundError, PermissionError) as error:
        return _refuse(f"`{check.command[0]}` cannot be started ({error.__class__.__name__})")
    try:
        raw, _ = process.communicate(timeout=check.timeout_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        process.communicate()
        return _refuse(f"the command did not finish in {check.timeout_s} seconds")
    if len(raw) > OUTPUT_LIMIT:
        return _refuse(f"the command printed more than {OUTPUT_LIMIT // (1024 * 1024)} MiB")
    output = raw.decode("utf-8", errors="replace")
    code = process.returncode
    if code < 0:
        return _refuse(f"the command was stopped by signal {-code}", output)
    if code in check.passes:
        return Outcome(Verdict.PASS, (), output)
    if code not in check.fails:
        return _refuse(f"the command exited {code}, which the check's mapping does not name:\n{_tail(output)}", output)
    findings: list[Finding] = []
    if check.output:
        try:
            findings = PARSERS[check.output](output)
        except (ValueError, KeyError, TypeError) as error:
            return _refuse(f"the output is not in the {check.output} form the check declared ({error})", output)
    if not findings:
        findings = [Finding("breach", _tail(output) or f"the command exited {code} and printed nothing")]
    return Outcome(Verdict.FAIL, tuple(findings), output)
