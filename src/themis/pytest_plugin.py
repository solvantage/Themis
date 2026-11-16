"""The pytest plugin: a receipt after every test run.

In a project with a `themis.toml`, each pytest run ends by writing what ran, on which exact tree,
and how it ended. "The suite passes" then cites a receipt. In any other folder the plugin does
nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from themis import receipts
from themis.manifest import MANIFEST_FILE


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    root = Path(str(config.rootpath))
    if hasattr(config, "workerinput") or not (root / MANIFEST_FILE).is_file():
        return  # a worker of a parallel run, or a folder Themis does not guard
    tree = receipts.tree_fingerprint(root)
    if tree is None:
        return  # nothing to pin a receipt to
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    stats = reporter.stats if reporter else {}

    def count(key: str) -> int:
        return len(stats.get(key, []))

    receipts.write(root, "suite", tree, {
        "tree": tree,
        "at": receipts.now(),
        "command": ["pytest", *config.invocation_params.args],
        "exit_status": int(exitstatus),
        "passed": count("passed"),
        "failed": count("failed"),
        "errors": count("error"),
        "skipped": count("skipped"),
        "skipped_tests": sorted(report.nodeid for report in stats.get("skipped", [])),
        "python": sys.version.split()[0],
    })
