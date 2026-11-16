"""Records: small structured files, one home per fact.

A record is a `.toml` or `.json` file, or a markdown file whose first lines are a frontmatter
block between two `---` lines. Its kind decides its schema and where it lives. The core defines a
few kinds; a pack adds its own with `register`.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from themis import paths, schema
from themis.schema import ANY, Choice, Required

if TYPE_CHECKING:
    from themis.manifest import Manifest


@dataclass
class Record:
    kind: str
    id: str
    path: str
    data: dict[str, Any]
    problems: list[str] = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


#: kind -> (spec, default home pattern). A project may move a home in its manifest.
KINDS: dict[str, tuple[Any, str]] = {}


def register(kind: str, spec: dict[str, Any], home: str) -> None:
    KINDS[kind] = (spec, home)


register("grant", {
    "action": Required(str), "target": Required(str), "granted_by": Required(str),
    "granted_at": Required(str), "reason": str, "ceiling": float, "unit": str,
    "spent_by": str, "spent_at": str,
}, "grants/*.toml")

register("attestation", {
    "subject": Required(str), "row": Required(str), "judge": Required(str), "by": Required(str),
    "at": Required(str), "sha256": Required(str), "note": str,
}, "attestations/**/*.toml")

register("decision", {
    "work": Required(str), "decision": Required(str), "verdict": Required(Choice("pass", "fail", "refuse")),
    "gate": Required(str), "gate_version": Required(str), "decided_at": Required(str),
    "level": str, "enough_evidence": bool, "numbers": {"*": ANY}, "reason": str, "by": str,
    "inputs": str,  # the file the gate read, when it is not the work's own metrics file
}, "decisions/**/*.json")

register("issue", {
    "title": Required(str), "status": Required(Choice("open", "enforced", "closed")),
    "enforced_by": str, "found": str,
}, "docs/issues/*.md")

register("finding", {
    "title": Required(str), "status": Required(Choice("open", "fixed", "wontfix", "refuted")),
    "anchor": str, "decision": str, "reopens_if": str, "found": str,
}, "docs/findings/*.toml")


_SCALAR = re.compile(r"^(?P<key>[A-Za-z0-9_-]+)\s*:\s*(?P<value>.*)$")


def _scalar(text: str) -> Any:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def frontmatter(text: str) -> dict[str, Any] | None:
    """The simple `key: value` block at the top of a markdown file, or None when there is none.

    Values are text, numbers, true or false, or a list written as `[a, b]`. Nothing deeper: a
    record that needs more than this belongs in a `.toml` file.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return None
    data: dict[str, Any] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        found = _SCALAR.match(line.strip())
        if not found:
            raise ValueError(f"frontmatter line is not `key: value`: {line.strip()!r}")
        value = found["value"].strip()
        if value.startswith("[") and value.endswith("]"):
            data[found["key"]] = [_scalar(item) for item in value[1:-1].split(",") if item.strip()]
        else:
            data[found["key"]] = _scalar(value)
    return data


def read_data(path: Path) -> dict[str, Any]:
    """A record file's contents. Raises ValueError with a plain reason when it cannot be read."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"cannot be read ({error.__class__.__name__})") from None
    try:
        if path.suffix == ".toml":
            return tomllib.loads(text)
        if path.suffix == ".json":
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("is not a JSON object")
            return data
        if path.suffix == ".md":
            data = frontmatter(text)
            if data is None:
                raise ValueError("has no frontmatter block")
            return data
    except (tomllib.TOMLDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"is not valid {path.suffix[1:].upper()} ({error})") from None
    raise ValueError(f"has an unsupported type {path.suffix!r}")


def home_of(manifest: Manifest, kind: str) -> str:
    return manifest.homes.get(kind) or KINDS[kind][1]


def load_kind(root: Path, manifest: Manifest, kind: str, all_files: list[str]) -> list[Record]:
    if kind not in KINDS:
        raise KeyError(f"no record kind named {kind!r}")
    spec = KINDS[kind][0]
    found = []
    for name in paths.select(all_files, home_of(manifest, kind)):
        record = Record(kind=kind, id=Path(name).stem, path=name, data={})
        try:
            record.data = read_data(root / name)
        except ValueError as error:
            record.problems.append(f"the {kind} record {error}")
        else:
            record.problems += [f"the {kind} record: {problem}" for problem in schema.problems(record.data, spec, kind)]
        found.append(record)
    return found
