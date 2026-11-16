"""The packs shipped with Themis. Each sub-package is one field; importing it registers the pack."""

from __future__ import annotations

import importlib
import pkgutil

#: module name -> why it failed to import. A broken module must not hide the rest of its pack.
BROKEN: dict[str, str] = {}


def load_modules(package: str, path: list[str]) -> None:
    """Import every module of a pack, so each registers its rules, records and gate functions."""
    for module in sorted(pkgutil.iter_modules(path), key=lambda found: found.name):
        name = f"{package}.{module.name}"
        if module.name.startswith("_") or module.name == "pack":
            continue
        try:
            importlib.import_module(name)
        except Exception as error:  # noqa: BLE001 - kept for `themis doctor` and the tests to report
            BROKEN[name] = f"{error.__class__.__name__}: {error}"
