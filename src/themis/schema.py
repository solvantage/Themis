"""A small, strict checker for declarative values.

A spec is one of:

    str, int, float, bool     a value of that type (a bool is never an int)
    ANY                       anything
    Choice("a", "b")          one of these strings
    [spec]                    a list whose items match spec
    {"key": spec, ...}        a table with exactly these keys; wrap a spec in Required to demand it
    {"*": spec}               a table with any keys, each value matching spec; beside named keys,
                              "*" is the spec for every key that is not named
    Either(spec, spec)        the first spec that matches

An unknown key is always a problem. A typing mistake must never become a default that happens to
be weaker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ANY = object()


@dataclass(frozen=True)
class Required:
    spec: Any


@dataclass(frozen=True)
class Choice:
    options: tuple[str, ...]

    def __init__(self, *options: str) -> None:
        object.__setattr__(self, "options", tuple(options))


@dataclass(frozen=True)
class Either:
    specs: tuple[Any, ...]

    def __init__(self, *specs: Any) -> None:
        object.__setattr__(self, "specs", tuple(specs))


def _name(spec: Any) -> str:
    if spec is ANY:
        return "any value"
    if isinstance(spec, type):
        return {"str": "text", "int": "a whole number", "float": "a number", "bool": "true or false"}[spec.__name__]
    if isinstance(spec, Choice):
        return "one of " + ", ".join(spec.options)
    if isinstance(spec, list):
        return f"a list of {_name(spec[0])}"
    if isinstance(spec, dict):
        return "a table"
    if isinstance(spec, Either):
        return " or ".join(_name(option) for option in spec.specs)
    if isinstance(spec, Required):
        return _name(spec.spec)
    return "a value"


def problems(value: Any, spec: Any, where: str) -> list[str]:
    """Every way `value` fails `spec`, each named by its place in the document."""
    if isinstance(spec, Required):
        return problems(value, spec.spec, where)
    if spec is ANY:
        return []
    if isinstance(spec, Either):
        tried = [problems(value, option, where) for option in spec.specs]
        return [] if any(not found for found in tried) else [f"{where} must be {_name(spec)}"]
    if isinstance(spec, Choice):
        return [] if isinstance(value, str) and value in spec.options else [f"{where} must be {_name(spec)}"]
    if isinstance(spec, type):
        if spec is float and isinstance(value, int) and not isinstance(value, bool):
            return []
        if isinstance(value, bool) and spec is not bool:
            return [f"{where} must be {_name(spec)}"]
        return [] if isinstance(value, spec) else [f"{where} must be {_name(spec)}"]
    if isinstance(spec, list):
        if not isinstance(value, list):
            return [f"{where} must be {_name(spec)}"]
        return [found for index, item in enumerate(value) for found in problems(item, spec[0], f"{where}[{index}]")]
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            return [f"{where} must be a table"]
        # "*" is the spec for keys that are not named. Without it, an unnamed key is a problem.
        named = {key: sub for key, sub in spec.items() if key != "*"}
        found = [f"{where}.{key} is not a known key" for key in value if key not in named and "*" not in spec]
        found += [f"{where}.{key} is required" for key, sub in named.items() if isinstance(sub, Required) and key not in value]
        for key, item in value.items():
            found += problems(item, named[key] if key in named else spec["*"], f"{where}.{key}") if key in named or "*" in spec else []
        return found
    raise TypeError(f"not a spec: {spec!r}")
