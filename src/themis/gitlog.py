"""What git knows, asked the same way by every rule.

Order is evidence, so several rules read history: which commit of the main line first brought a
file, what a file held on the main line, what a branch changed. The main line is the first-parent
chain of the main branch: one commit for each merge.
"""

from __future__ import annotations

import functools
import subprocess
from pathlib import Path

MAIN_CANDIDATES = ("origin/main", "main", "origin/master", "master")


class Git:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def run(self, *args: str) -> str | None:
        """The command's output, or None when git refuses or is not installed."""
        try:
            done = subprocess.run(
                ["git", *args], cwd=self.root, capture_output=True, text=True, timeout=120, check=False
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        return done.stdout if done.returncode == 0 else None

    @functools.cached_property
    def is_repo(self) -> bool:
        top = self.run("rev-parse", "--show-toplevel")
        return top is not None and Path(top.strip()).resolve() == self.root.resolve()

    def head(self) -> str | None:
        out = self.run("rev-parse", "--verify", "--quiet", "HEAD")
        return out.strip() if out else None

    def branch(self) -> str | None:
        out = self.run("rev-parse", "--abbrev-ref", "HEAD")
        return out.strip() if out and out.strip() != "HEAD" else None

    def resolve(self, ref: str) -> str | None:
        out = self.run("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        return out.strip() if out else None

    def main_ref(self, preferred: str | None = None) -> str | None:
        """The main line's name: the one asked for, else the first usual name that exists."""
        if not self.is_repo:
            return None
        for name in ((preferred,) if preferred else MAIN_CANDIDATES):
            if name and self.resolve(name):
                return name
        return None

    def is_ancestor(self, older: str, newer: str) -> bool:
        return self.run("merge-base", "--is-ancestor", older, newer) is not None

    def all_files(self) -> list[str]:
        """Tracked files and untracked ones that are not ignored, as repository paths."""
        if self.is_repo:
            out = self.run("ls-files", "-z", "--cached", "--others", "--exclude-standard")
            names = [name for name in (out or "").split("\0") if name]
            return sorted(name for name in set(names) if (self.root / name).is_file())
        skipped = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache"}
        return sorted(
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file() and not skipped.intersection(path.relative_to(self.root).parts)
        )

    def dirty(self) -> list[str]:
        out = self.run("status", "--porcelain")
        return [line[3:] for line in (out or "").splitlines() if line.strip()]

    def show(self, ref: str, path: str) -> str | None:
        """The file's text at that commit, or None when it is not there."""
        return self.run("show", f"{ref}:{path}")

    @functools.lru_cache(maxsize=None)
    def arrivals(self, ref: str) -> dict[str, int]:
        """For each file, the position on the main line of the commit that first brought it.

        Position 0 is the oldest commit. A merge is read against its first parent, so every file a
        pull request added arrives at that pull request's merge.
        """
        out = self.run("log", "--first-parent", "-m", "-M", "--diff-filter=AR", "--name-status", "--format=@%H", ref)
        if out is None:
            return {}
        commits: list[list[str]] = []
        for line in out.splitlines():
            if line.startswith("@"):
                commits.append([])
            elif line.strip() and commits:
                commits[-1].append(line.split("\t")[-1])
        found: dict[str, int] = {}
        for position, names in enumerate(reversed(commits)):
            for name in names:
                found.setdefault(name, position)
        return found

    @functools.lru_cache(maxsize=None)
    def main_line(self, ref: str) -> list[str]:
        """The commits of the main line, oldest first: positions match `arrivals`."""
        out = self.run("rev-list", "--first-parent", "--reverse", ref)
        return (out or "").split()

    @functools.lru_cache(maxsize=None)
    def added_by(self, path: str) -> str | None:
        """The commit that first added this path, on any branch that reaches HEAD."""
        out = self.run("log", "--diff-filter=A", "--format=%H", "--", path)
        found = (out or "").split()
        return found[-1] if found else None

    def commit_date(self, commit: str) -> str | None:
        out = self.run("show", "-s", "--format=%cs", commit)
        return out.strip() if out else None

    def changed_against(self, ref: str) -> list[str]:
        """Every path that differs from that commit: committed since, staged, unstaged or untracked."""
        committed = self.run("diff", "--name-only", "-z", ref, "--") or ""
        untracked = self.run("ls-files", "-z", "--others", "--exclude-standard") or ""
        return sorted({name for name in (committed + untracked).split("\0") if name})

    def tree_id(self) -> str | None:
        out = self.run("rev-parse", "--verify", "--quiet", "HEAD^{tree}")
        return out.strip() if out else None

    def ignored(self, names: list[str]) -> set[str] | None:
        """The paths among these that git ignores, as they were given, or None when git cannot say.

        A path need not exist. A tracked file is never ignored, whatever the ignore files say, and
        a path under an ignored folder is. Give a folder with a trailing slash.
        """
        if not names:
            return set()
        if not self.is_repo:
            return None
        try:
            done = subprocess.run(
                ["git", "check-ignore", "--stdin", "-z"], cwd=self.root, input="\0".join(names) + "\0",
                capture_output=True, text=True, timeout=120, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if done.returncode not in (0, 1):  # 1: nothing among them is ignored
            return None
        return {name for name in done.stdout.split("\0") if name}
