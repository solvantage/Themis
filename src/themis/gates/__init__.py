"""The core gates. Each module in this folder registers the rules of one gate, with their proofs.

A gate module that fails to import must not hide the others, so each is loaded on its own and a
failure is kept for `themis doctor` and for the tests to report.
"""

from __future__ import annotations

import importlib
import pkgutil

LOADED: list[str] = []
BROKEN: dict[str, str] = {}


def load_all() -> None:
    """Import every gate module once. Safe to call again."""
    for module in pkgutil.iter_modules(__path__):
        name = f"{__name__}.{module.name}"
        if module.name.startswith("_") or name in LOADED or name in BROKEN:
            continue
        try:
            importlib.import_module(name)
        except Exception as error:  # noqa: BLE001 - one broken gate must not hide the rest
            BROKEN[name] = f"{error.__class__.__name__}: {error}"
        else:
            LOADED.append(name)
