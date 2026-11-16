"""Packs: how a field plugs into Themis.

A pack supplies what one field needs on the core's engine: its own table in the manifest, its
records, its rules, its gate functions, defaults for the core rules, and one or more standards.
A pack names no project.

A pack is found by name in three places, in this order: among the packs shipped with Themis
(`themis.packs.<name>`), among installed distributions (the entry point group `themis.packs`), and
as a local pack, which is a folder inside one repository.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Standard:
    """A named floor: the level each rule must have, and the weakest value each parameter may take."""

    id: str
    levels: dict[str, str] = field(default_factory=dict)
    floors: dict[str, dict[str, Any]] = field(default_factory=dict)  # rule id -> {param: floor}


@dataclass
class Pack:
    name: str
    schema: dict[str, Any] = field(default_factory=dict)  # the spec of the pack's own manifest table
    standards: dict[str, Standard] = field(default_factory=dict)
    #: Given the manifest, the parameters this pack sets for rules: {rule id: {param: value}}.
    defaults: Callable[[Any], dict[str, dict[str, Any]]] = lambda manifest: {}
    #: name -> gate function. A gate turns a piece of work's records into a decision.
    gates: dict[str, Callable[..., Any]] = field(default_factory=dict)
    #: gate name -> calibration cases, each a callable returning (expected verdict text, observed).
    calibrations: dict[str, list[Callable[[], Any]]] = field(default_factory=dict)
    #: kind of work -> what it must produce, in words, for `themis describe`.
    kinds: dict[str, str] = field(default_factory=dict)

    def standard(self, id: str) -> Standard:
        self.standards[id] = Standard(id)
        return self.standards[id]


PACKS: dict[str, Pack] = {}


class PackError(Exception):
    pass


def register(pack: Pack) -> Pack:
    PACKS[pack.name] = pack
    return pack


def load(name: str) -> Pack:
    """Find and import a pack by name. Importing it registers its rules and records."""
    if name in PACKS:
        return PACKS[name]
    try:
        shipped = importlib.util.find_spec(f"themis.packs.{name}") is not None
    except (ModuleNotFoundError, ValueError):
        shipped = False
    if shipped:
        importlib.import_module(f"themis.packs.{name}")
    else:
        found = [entry for entry in metadata.entry_points(group="themis.packs") if entry.name == name]
        if not found:
            raise PackError(f"no pack named {name!r} is installed")
        found[0].load()
    if name not in PACKS:
        raise PackError(f"the pack {name!r} was imported but did not register itself")
    return PACKS[name]


def load_local(folder: Path) -> Pack:
    """Import a pack that lives in a repository: a folder whose `__init__.py` defines `pack`."""
    init = folder / "__init__.py"
    if not init.is_file():
        raise PackError(f"the local pack folder {folder.name} has no __init__.py")
    module_name = f"themis_local_pack_{abs(hash(str(folder.resolve())))}"
    if module_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(module_name, init, submodule_search_locations=[str(folder)])
        if spec is None or spec.loader is None:
            raise PackError(f"the local pack in {folder.name} cannot be imported")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as error:
            del sys.modules[module_name]
            raise PackError(f"the local pack in {folder.name} failed to import: {error!r}") from None
    found = getattr(sys.modules[module_name], "pack", None)
    if not isinstance(found, Pack):
        raise PackError(f"the local pack in {folder.name} must define `pack`, a themis.pack.Pack")
    return register(found)
