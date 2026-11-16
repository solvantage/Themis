"""Guarding the configuration: its hash, its lock, and telling a tightening from a weakening.

A configurable guard is easy to defeat by editing its configuration. So the effective
configuration is hashed and locked, and a change that weakens it is named as one.

A change is a weakening when it lowers a rule's level, moves a parameter in its looser direction,
moves a start date later, removes or alters an external check, widens what a role may change, or
drops a pack or a standard. The opposite is a tightening. A change that cannot be classified is
treated as a weakening.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from themis import external
from themis.manifest import COMMON_RULE_KEYS, LEVEL_RANK, Manifest
from themis.rule import RULES

LOCK_FILE = "themis.lock"
#: Paths no agent role may change, in every project. A project adds its own under [config].
ALWAYS_PROTECTED = ("themis.toml", LOCK_FILE, "grants/**", "receipts/**", ".claude/settings.json")


@dataclass(frozen=True)
class Change:
    kind: str  # "weakening", "tightening" or "neutral"
    what: str


def protected_paths(manifest: Manifest) -> list[str]:
    """Every pattern an agent role may not touch: the fixed ones, the project's, the local pack,
    and the scripts its external checks run."""
    found = list(ALWAYS_PROTECTED) + list(manifest.table("config").get("protected", []))
    local = manifest.project.get("local_pack")
    if local:
        found.append(f"{local.strip('/')}/**")
    for table in manifest.external:
        found += external.Check.from_table(table).scripts(manifest.root)
    return sorted(set(found))


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "missing"


def effective_hash(manifest: Manifest) -> str:
    """One hash over what decides the checking: the manifest, the scripts its external checks run,
    and the local pack's files."""
    parts: dict[str, Any] = {"manifest": manifest.raw, "scripts": {}, "local_pack": {}}
    for table in manifest.external:
        for script in external.Check.from_table(table).scripts(manifest.root):
            parts["scripts"][script] = _file_hash(manifest.root / script)
    local = manifest.project.get("local_pack")
    if local and (manifest.root / local).is_dir():
        for path in sorted((manifest.root / local).rglob("*.py")):
            parts["local_pack"][path.relative_to(manifest.root).as_posix()] = _file_hash(path)
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_lock(root: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((root / LOCK_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_lock(manifest: Manifest) -> Path:
    path = manifest.root / LOCK_FILE
    path.write_text(json.dumps({"themis_lock": 1, "hash": effective_hash(manifest)}, indent=2) + "\n", encoding="utf-8")
    return path


# -- classifying a change -----------------------------------------------------------------------


def _level(stated: Any) -> str:
    if isinstance(stated, str):
        return stated
    return stated.get("level", "warn") if isinstance(stated, dict) else "warn"


def _direction(old: Any, new: Any, stricter: str | None) -> str:
    """Which way a value moved, given the direction that tightens it."""
    if old == new or stricter is None:
        return "neutral"
    if stricter in ("lower", "higher", "earlier"):
        try:
            tighter = new < old if stricter in ("lower", "earlier") else new > old
        except TypeError:
            return "weakening"
        return "tightening" if tighter else "weakening"
    if isinstance(old, dict) and isinstance(new, dict):
        old, new = sorted(old.items(), key=str), sorted(new.items(), key=str)
    if not isinstance(old, (list, tuple)) or not isinstance(new, (list, tuple)):
        return "weakening"
    added = [item for item in new if item not in old]
    removed = [item for item in old if item not in new]
    loosened = added if stricter == "smaller" else removed
    tightened = removed if stricter == "smaller" else added
    if loosened:
        return "weakening"
    return "tightening" if tightened else "neutral"


def _rule_changes(old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    found = []
    for rule_id in sorted(set(old) | set(new)):
        before, after = old.get(rule_id), new.get(rule_id)
        if before == after:
            continue
        old_level, new_level = _level(before), _level(after)
        if old_level != new_level:
            kind = "tightening" if LEVEL_RANK[new_level] > LEVEL_RANK[old_level] else "weakening"
            found.append(Change(kind, f"{rule_id}: level {old_level} to {new_level}"))
        before = before if isinstance(before, dict) else {}
        after = after if isinstance(after, dict) else {}
        if before.get("since") != after.get("since"):
            was, now = before.get("since"), after.get("since")
            later = was is None or (now is not None and now > was)
            found.append(Change("weakening" if later else "tightening", f"{rule_id}: binds from {was} to {now}"))
        if before.get("empty", "refuse") != after.get("empty", "refuse"):
            kind = "weakening" if after.get("empty") == "allow" else "tightening"
            found.append(Change(kind, f"{rule_id}: an empty inspection is now {after.get('empty', 'refuse')}"))
        rule = RULES.get(rule_id)
        for name in sorted((set(before) | set(after)) - set(COMMON_RULE_KEYS)):
            param = rule.param(name) if rule else None
            default = param.default if param else None
            was, now = before.get(name, default), after.get(name, default)
            if was == now:
                continue
            kind = "weakening" if param is None else _direction(was, now, param.stricter)
            found.append(Change(kind, f"{rule_id}: {name} {was!r} to {now!r}"))
    return found


def _external_changes(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[Change]:
    found = []
    before = {check.get("id"): check for check in old}
    after = {check.get("id"): check for check in new}
    for check_id in sorted(set(before) | set(after), key=str):
        if check_id not in after:
            found.append(Change("weakening", f"{check_id}: the check was removed"))
        elif check_id not in before:
            found.append(Change("tightening", f"{check_id}: the check was added"))
        elif before[check_id] != after[check_id]:
            was, now = dict(before[check_id]), dict(after[check_id])
            old_proofs, new_proofs = was.pop("proofs", []), now.pop("proofs", [])
            old_level, new_level = was.pop("level", "enforce"), now.pop("level", "enforce")
            if was != now:
                moved = sorted(key for key in set(was) | set(now) if was.get(key) != now.get(key))
                found.append(Change("weakening", f"{check_id}: {', '.join(moved)} changed"))
            if old_level != new_level:
                kind = "tightening" if LEVEL_RANK[new_level] > LEVEL_RANK[old_level] else "weakening"
                found.append(Change(kind, f"{check_id}: level {old_level} to {new_level}"))
            if any(proof not in new_proofs for proof in old_proofs):
                found.append(Change("weakening", f"{check_id}: a proof was removed or altered"))
            elif old_proofs != new_proofs:
                found.append(Change("tightening", f"{check_id}: a proof was added"))
    return found


def _role_changes(old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    found = []
    for name in sorted(set(old) | set(new)):
        before, after = old.get(name), new.get(name)
        if before == after:
            continue
        if after is None:
            found.append(Change("weakening", f"role {name}: removed, so its changes are no longer limited"))
            continue
        if before is None:
            found.append(Change("tightening", f"role {name}: added"))
            continue
        for key, stricter in (("paths", "smaller"), ("branches", None), ("denied_tools", "larger")):
            if before.get(key, []) != after.get(key, []):
                kind = _direction(before.get(key, []), after.get(key, []), stricter)
                found.append(Change("weakening" if stricter is None else kind, f"role {name}: {key} changed"))
        if before.get("owner", False) != after.get("owner", False):
            found.append(Change("weakening" if after.get("owner") else "tightening", f"role {name}: owner flag changed"))
    return found


def classify(old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    """Every difference between two manifests, each named a weakening, a tightening or neutral."""
    found = _rule_changes(old.get("rules", {}), new.get("rules", {}))
    found += _external_changes(old.get("checks", {}).get("external", []), new.get("checks", {}).get("external", []))
    found += _role_changes(old.get("roles", {}), new.get("roles", {}))

    before, after = old.get("project", {}), new.get("project", {})
    packs = _direction(before.get("packs", []), after.get("packs", []), "larger")
    if packs != "neutral":
        found.append(Change(packs, f"packs: {before.get('packs', [])} to {after.get('packs', [])}"))
    if before.get("standard") != after.get("standard"):
        kind = "tightening" if before.get("standard") is None else "weakening"
        found.append(Change(kind, f"standard: {before.get('standard')} to {after.get('standard')}"))
    if before.get("strict", False) != after.get("strict", False):
        found.append(Change("tightening" if after.get("strict") else "weakening", "strict changed"))
    for key in ("local_pack", "main"):
        if before.get(key) != after.get(key):
            found.append(Change("weakening", f"project.{key}: {before.get(key)!r} to {after.get(key)!r}"))
    if before.get("name") != after.get("name"):
        found.append(Change("neutral", "the project's name changed"))

    protected = _direction(old.get("config", {}).get("protected", []), new.get("config", {}).get("protected", []), "larger")
    if protected != "neutral":
        found.append(Change(protected, "config.protected changed"))

    classified = {"rules", "checks", "roles", "project", "config"}
    for table in sorted((set(old) | set(new)) - classified):
        if old.get(table) != new.get(table):
            # Homes, views, the suite command, adapters and pack tables: a change here can hide
            # records or soften a threshold, and nothing says which way it went.
            found.append(Change("weakening", f"[{table}] changed, and its direction cannot be classified"))
    return found


def parse(text: str | None) -> dict[str, Any] | None:
    if text is None:
        return None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
