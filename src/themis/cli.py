"""The ``themis`` command.

Skeleton: only ``--version`` exists. Every other call exits REFUSE, because a command that
checked nothing must never look like a pass (DESIGN.md, law 4).
"""

from __future__ import annotations

import argparse
import sys

from themis import __version__

EXIT_PASS, EXIT_FAIL, EXIT_REFUSE = 0, 1, 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="themis",
        description="Guardrails as code for work done by AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"themis {__version__}")
    parser.parse_args(argv)
    print(
        "themis: no commands exist yet. This is the skeleton release; nothing was checked. "
        "See DESIGN.md.",
        file=sys.stderr,
    )
    return EXIT_REFUSE


if __name__ == "__main__":
    raise SystemExit(main())
