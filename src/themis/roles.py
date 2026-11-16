"""Roles: who is working, so a rule can say what they may change.

A project declares roles in its manifest. A role is recognised by the branch it works on, or by
the `THEMIS_ROLE` environment variable, which an agent harness sets. A role marked `owner = true`
is the owner's. When no role is recognised, the work is taken to be the owner's.
"""

from __future__ import annotations

import os
from typing import Any

from themis import paths
from themis.gitlog import Git
from themis.manifest import Manifest


def current(manifest: Manifest, git: Git, environ: dict[str, str] | None = None) -> tuple[str, dict[str, Any]] | None:
    """The role at work, as (name, its table), or None when none is recognised."""
    environ = os.environ if environ is None else environ
    named = environ.get("THEMIS_ROLE")
    if named and named in manifest.roles:
        return named, manifest.roles[named]
    branch = git.branch()
    if branch:
        for name, table in manifest.roles.items():
            if paths.matches_any(branch, table.get("branches", [])):
                return name, table
    return None


def is_agent(role: tuple[str, dict[str, Any]] | None) -> bool:
    return role is not None and not role[1].get("owner", False)
