"""Guarding the configuration: its hash, its lock, and telling a tightening from a weakening.

A configurable guard is easy to defeat by editing its configuration. So the effective
configuration is hashed and locked, and a change that weakens it is named as one.

A change is a weakening when it lowers a rule's level, moves a parameter in its looser direction,
moves a start date later (or sets one for the first time), removes or alters an external check,
widens what a role may change, skips a test, moves where records are read, or drops a pack, a
standard, a table or a list entry. The opposite is a tightening. An addition is a tightening: a
new table, a rule's required parameter first set, a new list entry that adds a check, a new
external check. A value is compared with what was in force before it: a rule's parameter with the
value its pack set for it, and a pack's key with the default the pack states for it. A key added
to a table that was already there is a weakening unless its pack states which way it tightens. A
change that cannot be classified is treated as a weakening.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from themis import external, pack
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


EMPTY = (None, "", [], {})


def _as_set(value: Any) -> Any:
    """A set-like value as a list: nothing is an empty list, and one pattern is a list of one."""
    if value is None:
        return []
    return [value] if isinstance(value, str) else value


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
    old, new = _as_set(old), _as_set(new)
    if isinstance(old, dict) and isinstance(new, dict):
        # A table of sets is compared key by key, so a set inside it moves the way a set does: a
        # new kind, or a new file in a kind, is a tightening when the stricter direction is larger.
        added, removed = ("tightening", "weakening") if stricter == "larger" else ("weakening", "tightening")
        moves = {added if key not in old else removed if key not in new else _direction(old[key], new[key], stricter)
                 for key in set(old) | set(new)}
        return "weakening" if "weakening" in moves else "tightening" if "tightening" in moves else "neutral"
    if not isinstance(old, (list, tuple)) or not isinstance(new, (list, tuple)):
        return "weakening"
    added = [item for item in new if item not in old]
    removed = [item for item in old if item not in new]
    loosened = added if stricter == "smaller" else removed
    tightened = removed if stricter == "smaller" else added
    if loosened:
        return "weakening"
    return "tightening" if tightened else "neutral"


def _rule_changes(old: dict[str, Any], new: dict[str, Any], old_set: dict[str, dict[str, Any]] | None = None,
                  new_set: dict[str, dict[str, Any]] | None = None) -> list[Change]:
    """The changes to the rules. `old_set` and `new_set` are what the packs set for each rule on
    either side: a parameter a project leaves unstated holds that value, not the rule's own default."""
    old_set, new_set = old_set or {}, new_set or {}
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
            was = before.get(name, old_set.get(rule_id, {}).get(name, default))
            now = after.get(name, new_set.get(rule_id, {}).get(name, default))
            if was == now:
                continue
            if param is None:
                kind = "weakening"
            elif was in EMPTY and name in rule.requires:
                # A required parameter first set turns the rule on, whichever way it leans. `was` is
                # what was in force, so a value a pack had set is not "first set" when replaced.
                kind = "tightening"
            elif param.stricter is None:
                # A path or a name has no stricter direction. Setting one turns the rule on. Changing
                # one can point the rule away from what it guarded, and nothing says which way it went.
                kind = "tightening" if was in EMPTY else "weakening"
            else:
                kind = _direction(was, now, param.stricter)
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


def _packs(raw: dict[str, Any], root: Path | None) -> list[pack.Pack]:
    """The packs a manifest turns on, as far as they can be loaded. A local pack needs the root."""
    project = raw.get("project") if isinstance(raw.get("project"), dict) else {}
    names = project.get("packs") if isinstance(project.get("packs"), list) else []
    found = []
    for name in names:
        try:
            found.append(pack.load(str(name)))
        except pack.PackError:
            continue  # a pack that cannot load sets nothing; config/valid names it
    local = project.get("local_pack")
    if root is not None and isinstance(local, str):
        try:
            found.append(pack.load_local(Path(root) / local))
        except pack.PackError:
            pass
    return found


def _pack_settings(raw: dict[str, Any], root: Path | None, packs: list[pack.Pack]) -> dict[str, dict[str, Any]]:
    """What the packs set for each rule under this manifest: {rule id: {param: value}}. A pack's
    defaults may read the project's files, so none are read without the root."""
    if root is None:
        return {}
    held = Manifest(root=Path(root), raw=raw, packs=packs)
    found: dict[str, dict[str, Any]] = {}
    for loaded in packs:
        try:
            given = loaded.defaults(held)
        except Exception:  # a pack's defaults that fail on an old manifest set nothing there
            continue
        for rule_id, params in given.items():
            found.setdefault(rule_id, {}).update(params)
    return found


def classify(old: dict[str, Any], new: dict[str, Any], root: Path | None = None) -> list[Change]:
    """Every difference between two manifests, each named a weakening, a tightening or neutral.

    `root` is the project's folder. With it, a rule's parameter is compared with the value the
    packs set for it on each side, as the engine runs it; without it, with the rule's own default.
    """
    old_packs, new_packs = _packs(old, root), _packs(new, root)
    found = _rule_changes(old.get("rules", {}), new.get("rules", {}),
                          _pack_settings(old, root, old_packs), _pack_settings(new, root, new_packs))
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
    keys = {loaded.name: loaded.keys for loaded in old_packs + new_packs}
    for table in sorted((set(old) | set(new)) - classified):
        found += _table_changes(f"[{table}]", old.get(table), new.get(table), keys.get(table, {}))
    return found


def _entry(where: str, key: str) -> str:
    return f"{where[:-1]}.{key}]" if where.endswith("]") else f"{where}.{key}"


def _declared(keys: dict[str, pack.Key], path: tuple[str, ...]) -> pack.Key | None:
    """The pack's word on the key at this place in its table, or None when it says nothing."""
    for pattern, key in keys.items():
        parts = pattern.split(".")
        if len(parts) == len(path) and all(part in ("*", name) for part, name in zip(parts, path)):
            return key
    return None


def _declared_change(where: str, old: Any, new: Any, key: pack.Key, keys: dict[str, pack.Key],
                     path: tuple[str, ...]) -> list[Change]:
    """A change to a key whose pack states its direction and its default."""
    if key.stricter in ("larger", "smaller") and (isinstance(old, dict) or isinstance(new, dict)):
        # A table of entries, such as the windows: a new entry adds a check whatever it holds (or,
        # when smaller is stricter, lets more through), and an entry on both sides is read inside.
        old, new = old or {}, new or {}
        if not isinstance(old, dict) or not isinstance(new, dict):
            return [Change("weakening", f"{where} changed, and its direction cannot be classified")]
        added, removed = ("tightening", "weakening") if key.stricter == "larger" else ("weakening", "tightening")
        found = []
        for name in sorted(set(old) | set(new), key=str):
            place = _entry(where, str(name))
            if name not in old:
                found.append(Change(added, f"{place} added"))
            elif name not in new:
                found.append(Change(removed, f"{place} removed"))
            else:
                found += _table_changes(place, old[name], new[name], keys, (*path, str(name)))
        return found
    was = key.default if old is None else old
    now = key.default if new is None else new
    if was == now:
        return []
    if key.stricter is None:
        kind = "tightening" if was in EMPTY else "weakening"  # first set turns a check on; a change may point it away
    elif was in EMPTY and key.stricter != "smaller":
        kind = "tightening"  # a limit set where there was none
    else:
        kind = _direction(was, now, key.stricter)
    return [] if kind == "neutral" else [Change(kind, f"{where}: {was!r} to {now!r}")]


def _table_changes(where: str, old: Any, new: Any, keys: dict[str, pack.Key] | None = None,
                   path: tuple[str, ...] = (), fresh: bool = False) -> list[Change]:
    """The changes to a table the core does not classify by name: views, the suite, the agents,
    adapters and pack tables. `keys` is what the pack says about the keys of its table, and `path`
    is where in the table this value sits.

    A key the pack names is compared with its default, in its stricter direction. Otherwise, a new
    table is a tightening, and so is every key inside it (`fresh`), unless a named key in it
    loosens its default. A new list entry is a tightening. A key added to a table that was already
    there is a weakening, since nothing says which way it moves the checking; so is a removal, and
    a changed value. Two tables are read their own way: a new suite skip is a weakening (a test
    stops counting) and a removed one a tightening, and any change to [homes] is a weakening,
    because it moves where records are read from."""
    keys = keys or {}
    if old == new:
        return []
    if where == "[homes]" or where.startswith("[homes."):
        return [Change("weakening", f"{where} changed: records are read from another place")]
    if where == "[suite.skips]":
        old, new = old or [], new or []  # no list of skips is an empty one
    declared = _declared(keys, path) if path else None
    if declared is not None:
        return _declared_change(where, old, new, declared, keys, path)
    if old is None:
        if isinstance(new, dict):
            inside = _table_changes(where, {}, new, keys, path, fresh=True)
            loosened = [change for change in inside if change.kind == "weakening"]
            return loosened or [Change("tightening", f"{where} added")]
        if fresh or isinstance(new, list):
            return [Change("tightening", f"{where} added")]
        return [Change("weakening", f"{where} added to a table that was there, and nothing states which way it moves "
                                    "the checking")]
    if new is None:
        return [Change("weakening", f"{where} removed")]
    if isinstance(old, dict) and isinstance(new, dict):
        return [change for key in sorted(set(old) | set(new), key=str)
                for change in _table_changes(_entry(where, str(key)), old.get(key), new.get(key), keys,
                                             (*path, str(key)), fresh)]
    if isinstance(old, (str, list)) and isinstance(new, (str, list)) and not isinstance(old, type(new)):
        old, new = _as_set(old), _as_set(new)  # one pattern and a list of patterns are the same set
    if isinstance(old, list) and isinstance(new, list):
        added = [item for item in new if item not in old]
        removed = [item for item in old if item not in new]
        if where == "[suite.skips]":
            if added:
                return [Change("weakening", f"{where}: a test is skipped that was not")]
            return [Change("tightening", f"{where}: a skip was removed")] if removed else []
        if removed:
            return [Change("weakening", f"{where}: an entry was removed or altered")]
        return [Change("tightening", f"{where}: an entry was added")] if added else []
    return [Change("weakening", f"{where} changed, and its direction cannot be classified")]


def parse(text: str | None) -> dict[str, Any] | None:
    if text is None:
        return None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
