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


@dataclass(frozen=True)
class Calibration:
    """One known-answer test of a gate function, measured as a rate over many draws.

    A `noise` case feeds the gate data with nothing in it and returns how often the gate said yes:
    its false-alarm rate. A `planted` case feeds it data with a known effect and returns how often
    the gate found it: its power. A gate that cannot say no to noise has not earned a yes.
    """

    gate: str
    kind: str  # "noise" or "planted"
    name: str
    run: Callable[[], float]


@dataclass
class Pack:
    name: str
    schema: dict[str, Any] = field(default_factory=dict)  # the spec of the pack's own manifest table
    standards: dict[str, Standard] = field(default_factory=dict)
    #: Given the manifest, the parameters this pack sets for rules: {rule id: {param: value}}.
    defaults: Callable[[Any], dict[str, dict[str, Any]]] = lambda manifest: {}
    #: name -> gate function: `gate(metrics: dict) -> {"decision": ..., "verdict": "pass"|"fail"|"refuse", ...}`.
    gates: dict[str, Callable[..., Any]] = field(default_factory=dict)
    gate_versions: dict[str, str] = field(default_factory=dict)
    calibrations: list[Calibration] = field(default_factory=list)
    #: kind of work -> what it must produce, in words, for `themis describe`.
    kinds: dict[str, str] = field(default_factory=dict)
    #: Builds the report of one unit of work: `report(root, manifest, unit) -> the files written`.
    report: Callable[[Path, Any, str], list[Path]] | None = None
    #: gate name -> a builder of what that gate reads, from the records:
    #: `inputs(root, manifest, subject, rival=None, *, as_of=None) -> dict`. A gate with a builder
    #: decides about a subject that is not one folder of work, and its numbers are never typed.
    inputs: dict[str, Callable[..., dict[str, Any]]] = field(default_factory=dict)

    def gate(self, name: str, *, version: str = "1") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register a gate function under a name and a version."""

        def register(func: Callable[..., Any]) -> Callable[..., Any]:
            self.gates[name] = func
            self.gate_versions[name] = version
            return func

        return register

    def calibration(self, gate: str, kind: str, name: str) -> Callable[[Callable[[], float]], Callable[[], float]]:
        """Register a calibration case for a gate: `kind` is "noise" or "planted"."""
        if kind not in ("noise", "planted"):
            raise ValueError("a calibration case is noise or planted")

        def register(run: Callable[[], float]) -> Callable[[], float]:
            self.calibrations.append(Calibration(gate, kind, name, run))
            return run

        return register


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
