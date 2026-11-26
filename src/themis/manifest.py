"""The manifest: a project's `themis.toml`, read strictly.

Everything specific to a project lives here as declarative values: paths, parameters, rule levels,
the checks it already has. An unknown key, a wrong type or an unknown rule id is a problem, never a
silent default, because a typing mistake must not weaken the guard unnoticed.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from themis import gates, pack, schema
from themis.rule import RULES, Rule
from themis.schema import ANY, Choice, Either, Required

MANIFEST_FILE = "themis.toml"
LEVELS = ("off", "warn", "enforce")
LEVEL_RANK = {name: rank for rank, name in enumerate(LEVELS)}
PARSERS = ("path-line-message", "json-lines")
#: How the agent hook answers before a tool call: ask for danger and leave the rest to the host, or
#: also allow what it reads in full and knows is safe.
PRETOOL_MODES = ("ask", "allow-safe")
#: Where scratch work lives, when [agents] sets no `temp`: inside a folder of /tmp (not a folder of
#: /tmp itself, which other sessions may own), and the session's own `$TMPDIR`, read when the hook runs.
TEMP_FOLDERS = ("/tmp/*/**", "/private/tmp/*/**", "$TMPDIR/**")
#: Keys any rule's table may hold, beside the rule's own parameters.
COMMON_RULE_KEYS = {
    "level": Choice(*LEVELS),
    "since": str,
    "empty": Choice("refuse", "allow"),
    "shadow": str,
}

PLANT = {"file": Required(str), "append": str, "find": str, "replace": str, "content": str, "delete": bool,
         "stage": bool}
#: The timeline gate's table: the page and heading its table sits under, and the project's states.
#: `cites` lists what a state's row must cite: "pr" for a bare #N, or path patterns.
TIMELINE = {
    "page": Required(str),
    "heading": Required(str),
    "states": Required({"*": {"started": bool, "finished": bool, "names": Choice("rows", "until"), "cites": [str]}}),
}
EXTERNAL = {
    "id": Required(str),
    "description": Required(str),
    "command": Required([str]),
    "cwd": str,
    "when": [str],
    "verdicts": {"pass": [int], "fail": [int]},
    "output": Choice(*PARSERS),
    "timeout_s": int,
    "needs": [str],
    "level": Choice(*LEVELS),
    "proofs": [{
        "name": Required(str),
        "plant": PLANT,
        "expect": Required(Choice("pass", "fail", "refuse")),
        "expect_output": str,
    }],
}
CORE = {
    "project": {"name": str, "packs": [str], "local_pack": str, "standard": str, "strict": bool, "main": str},
    "homes": {"*": str},
    "views": {"*": str},
    "suite": {"command": str, "skips": [{"test": Required(str), "reason": Required(str), "until": Required(str)}]},
    "rules": {"*": Either(Choice(*LEVELS), {"*": ANY})},
    "roles": {"*": {"paths": [str], "branches": [str], "denied_tools": [str], "owner": bool}},
    "config": {"protected": [str]},
    "checks": {"external": [EXTERNAL]},
    "adapters": {"*": {"*": ANY}},
    "agents": {"host": Choice("claude"), "instructions": str, "git_hooks": str, "pretool": Choice(*PRETOOL_MODES),
               "temp": [str], "keep": [str], "ask": [str], "deny": [str], "allow": [str]},
    "timeline": TIMELINE,
}


@dataclass(frozen=True)
class Setting:
    """How a project has set one rule."""

    level: str = "warn"
    since: str | None = None
    empty: str = "refuse"
    shadow: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    stated: bool = False  # True when the project wrote this rule into its manifest


@dataclass
class Manifest:
    root: Path
    raw: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    present: bool = False
    packs: list[pack.Pack] = field(default_factory=list)

    # -- the shared tables ----------------------------------------------------------------------

    @property
    def project(self) -> dict[str, Any]:
        return self.raw.get("project", {})

    @property
    def name(self) -> str:
        return self.project.get("name") or self.root.name

    @property
    def homes(self) -> dict[str, str]:
        return self.raw.get("homes", {})

    @property
    def views(self) -> dict[str, str]:
        return self.raw.get("views", {})

    @property
    def suite(self) -> dict[str, Any]:
        return self.raw.get("suite", {})

    @property
    def roles(self) -> dict[str, dict[str, Any]]:
        return self.raw.get("roles", {})

    @property
    def standard(self) -> str | None:
        return self.project.get("standard")

    @property
    def strict(self) -> bool:
        return bool(self.project.get("strict", False))

    @property
    def external(self) -> list[dict[str, Any]]:
        return self.raw.get("checks", {}).get("external", [])

    def table(self, name: str) -> dict[str, Any]:
        """A pack's own table, or any other top-level table, empty when the project wrote none."""
        return self.raw.get(name, {})

    # -- rules ----------------------------------------------------------------------------------

    def active_rules(self) -> list[Rule]:
        """The core's rules and those of the packs this project turned on."""
        names = {"core", *(loaded.name for loaded in self.packs)}
        return [rule for rule in RULES.values() if rule.pack in names]

    def setting(self, rule: Rule) -> Setting:
        params = {param.name: param.default for param in rule.params}
        for loaded in self.packs:
            params.update(loaded.defaults(self).get(rule.id, {}))
        stated = self.raw.get("rules", {}).get(rule.id)
        if stated is None:
            return Setting(params=params)
        if isinstance(stated, str):
            return Setting(level=stated, params=params, stated=True)
        params.update({key: value for key, value in stated.items() if key not in COMMON_RULE_KEYS})
        return Setting(
            level=stated.get("level", "warn"), since=stated.get("since"), empty=stated.get("empty", "refuse"),
            shadow=stated.get("shadow"), params=params, stated=True,
        )


def _rule_problems(raw: dict[str, Any], known: dict[str, Rule]) -> list[str]:
    found = []
    for rule_id, stated in raw.get("rules", {}).items():
        where = f'rules."{rule_id}"'
        if rule_id not in known:
            found.append(f"{where} is not a rule Themis knows; check the id, or turn its pack on")
            continue
        if isinstance(stated, str):
            continue
        spec = dict(COMMON_RULE_KEYS)
        spec.update({param.name: param.spec for param in known[rule_id].params})
        found += schema.problems(stated, spec, where)
    return found


def _external_problems(raw: dict[str, Any]) -> list[str]:
    found, seen = [], set()
    for index, check in enumerate(raw.get("checks", {}).get("external", [])):
        where = f"checks.external[{index}]"
        check_id = check.get("id")
        if not isinstance(check_id, str):
            continue
        if not check_id.startswith("ext/") or len(check_id) <= 4:
            found.append(f"{where}.id must start with ext/, such as ext/docs")
        if check_id in seen:
            found.append(f"{where}.id {check_id} is used twice")
        seen.add(check_id)
        if isinstance(check.get("command"), list) and not check["command"]:
            found.append(f"{where}.command is empty")
        for number, proof in enumerate(check.get("proofs", [])):
            plant = proof.get("plant")
            if isinstance(plant, dict):
                actions = [key for key in ("append", "content", "delete", "replace") if key in plant]
                if len(actions) != 1 or ("replace" in plant) != ("find" in plant):
                    found.append(
                        f"{where}.proofs[{number}].plant needs exactly one action: append, content, "
                        "delete, or find with replace"
                    )
    return found


def load(root: Path) -> Manifest:
    """Read and check a project's manifest. Problems are collected, never raised."""
    root = Path(root)
    manifest = Manifest(root=root)
    gates.load_all()
    path = root / MANIFEST_FILE
    if not path.is_file():
        return manifest
    manifest.present = True
    try:
        manifest.raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        manifest.problems.append(f"{MANIFEST_FILE} cannot be read: {error}")
        return manifest

    spec = dict(CORE)
    project = manifest.raw.get("project", {}) if isinstance(manifest.raw.get("project", {}), dict) else {}
    for name in project.get("packs", []) if isinstance(project.get("packs", []), list) else []:
        try:
            manifest.packs.append(pack.load(name))
        except pack.PackError as error:
            manifest.problems.append(f"project.packs: {error}")
    local = project.get("local_pack")
    if isinstance(local, str):
        try:
            manifest.packs.append(pack.load_local(root / local))
        except pack.PackError as error:
            manifest.problems.append(f"project.local_pack: {error}")
    for loaded in manifest.packs:
        spec[loaded.name] = loaded.schema or {"*": ANY}

    manifest.problems += schema.problems(manifest.raw, spec, MANIFEST_FILE.removesuffix(".toml"))
    if not manifest.problems:
        known = {rule.id: rule for rule in manifest.active_rules()}
        manifest.problems += _rule_problems(manifest.raw, known)
        manifest.problems += _external_problems(manifest.raw)
        standard = manifest.standard
        if standard and not any(standard in loaded.standards for loaded in manifest.packs):
            manifest.problems.append(f"project.standard {standard!r} is published by no pack this project turned on")
    return manifest
