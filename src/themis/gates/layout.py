"""Gate: layout — the repository is shaped the way the project says.

Three promises about where things live, read from the repository's files (tracked, and untracked
ones git does not ignore): each kind of folder holds the files its kind needs, a retired name is
gone, and no page sends a reader to a file a clone does not have.
"""

from __future__ import annotations

import posixpath
import re
from typing import TYPE_CHECKING

from themis import claims, markdown, paths, work
from themis.manifest import MANIFEST_FILE
from themis.rule import Context, Param, proof, rule
from themis.schema import Required

if TYPE_CHECKING:
    from themis.proofs import World

# -- layout/required-files ----------------------------------------------------------------------

KINDS = Param(
    "kinds", {"*": {"folders": Required(str), "files": Required([str])}}, {}, "larger",
    "a table for each kind of folder: folders, the pattern its folders match, and files, the patterns each "
    "must hold, inside the folder; a new kind or a new file is a tightening",
)


def _folders(files: list[str]) -> list[str]:
    """Every folder that holds a file, at any depth."""
    return sorted({name.rsplit("/", depth)[0] for name in files for depth in range(1, name.count("/") + 1)})


@rule(
    "layout/required-files",
    "Each folder of a declared kind holds the files its kind requires.",
    params=(KINDS,),
    requires=("kinds",),
    learned="Folders of one kind drifted apart: some had lost the page or the profile the rest kept.",
)
def required_files(ctx: Context) -> None:
    folders = _folders(ctx.all_files)
    for kind, spec in sorted(ctx.param("kinds").items()):
        pattern = spec["folders"]
        matched = [folder for folder in folders if paths.matches(folder, pattern)]
        if not matched:
            ctx.refuse(f"no folder matches {pattern}, so the kind {kind} has nothing to check", where=MANIFEST_FILE,
                       fix="correct the pattern, or remove the kind")
        for folder in matched:
            ctx.inspect()
            inside = [name for name in ctx.all_files if name.startswith(f"{folder}/")]
            for wanted in spec["files"]:
                if not work.inside(folder, inside, [wanted]):
                    ctx.breach(f"this {kind} folder holds no {wanted}", where=folder,
                               fix=f"add {wanted}, or move the folder out of {pattern}")


KIND_SETUP = """
    [rules."layout/required-files".kinds.tool]
    folders = "tools/*"
    files = ["README.md", "*.py"]

    [rules."layout/required-files".kinds.guide]
    folders = "docs/guides/**"
    files = ["index.md"]
"""
TOOL = {"tools/{0}/README.md": "# {0}\n", "tools/{0}/{0}.py": "print('{0}')\n"}


def _tools(world: World, *names: str, setup: str = KIND_SETUP) -> None:
    world.manifest(setup)
    world.write("README.md", "# A small project\n")
    world.write("docs/guides/index.md", "# Guides\n")
    world.write("docs/guides/setup/index.md", "# Set-up\n")
    for name in names:
        for path, text in TOOL.items():
            world.write(path.format(name), text.format(name))


@proof("layout/required-files", "every folder of each kind holds what its kind needs", expect="pass")
def _(world: World) -> None:
    _tools(world, "lint", "pack")


@proof("layout/required-files", "a tool folder without its page",
       expect="fail", contains="this tool folder holds no README.md")
def _(world: World) -> None:
    _tools(world, "lint", "pack")
    world.remove("tools/pack/README.md")


@proof("layout/required-files", "a tool folder with no script that matches", expect="fail", contains="holds no *.py")
def _(world: World) -> None:
    _tools(world, "lint")
    world.move("tools/lint/lint.py", "tools/lint/lint.sh")


@proof("layout/required-files", "a nested guide without its index",
       expect="fail", contains="this guide folder holds no index.md")
def _(world: World) -> None:
    _tools(world, "lint")
    world.write("docs/guides/setup/deep/notes.md", "# Notes\n")


@proof("layout/required-files", "a kind whose pattern matches no folder",
       expect="refuse", contains="the kind tool has nothing")
def _(world: World) -> None:
    _tools(world, setup=KIND_SETUP)


# -- layout/retired-names -----------------------------------------------------------------------

NAMES = Param("names", [str], [], "larger", "the retired names: none may appear in a file's text or path, in any case")
ALLOW = Param(
    "allow", [{"file": Required(str), "line": Required(str)}], [], "smaller",
    "exact allowances: a file, and the whole text of the one line there that may still hold a name",
)
FILES = Param("files", [str], ["**"], "larger", "the files it reads, as path patterns")


@rule(
    "layout/retired-names",
    "No file holds a retired name, in its text or its path, but on a line allowed exactly.",
    params=(NAMES, ALLOW, FILES),
    requires=("names",),
    learned="A renamed folder lived on in links and notes, and readers went looking for it.",
)
def retired_names(ctx: Context) -> None:
    names = [(name, name.casefold()) for name in ctx.param("names")]
    if any(not name.strip() for name, _ in names):
        ctx.refuse("a retired name is empty, so it would match every line", where=MANIFEST_FILE,
                   fix="remove the empty name")
        return
    allowed = {(entry["file"], entry["line"].strip()) for entry in ctx.param("allow")}
    used: set[tuple[str, str]] = set()
    # The manifest is never read: it is where the names are written.
    for path in sorted({name for pattern in ctx.param("files") for name in ctx.files(pattern)} - {MANIFEST_FILE}):
        ctx.inspect()
        for name, folded in names:
            if folded in path.casefold():
                ctx.breach(f"the path holds the retired name {name!r}", where=path, fix="rename it")
        text = ctx.read(path)
        for number, line in enumerate((text or "").split("\n"), 1):
            held = [name for name, folded in names if folded in line.casefold()]
            if not held:
                continue
            if (path, line.strip()) in allowed - used:
                used.add((path, line.strip()))  # an allowance covers one line, once
                continue
            ctx.breach(f"this line holds the retired name {held[0]!r}", where=path, line=number,
                       fix="write the name in use now; an origin note is allowed exactly, under allow")
    for path, _ in sorted(allowed - used):
        ctx.refuse("an allowance matches no line here that holds a retired name", where=path,
                   fix="remove it from allow, or correct its text")


NAMES_SETUP = """
    [rules."layout/retired-names"]
    names = ["old-tools"]
    allow = [{ file = "docs/history.md", line = "This project was called old-tools until 2026." }]
"""
HISTORY = "# History\n\nThis project was called old-tools until 2026.\n"


def _renamed(world: World, history: str = HISTORY, setup: str = NAMES_SETUP) -> None:
    world.manifest(setup)
    world.write("README.md", "# new-tools\n\nRun `scripts/build.sh`.\n")
    world.write("scripts/build.sh", "echo building new-tools\n")
    world.write("docs/history.md", history)


@proof("layout/retired-names", "the old name only on the allowed line, and in the manifest", expect="pass")
def _(world: World) -> None:
    _renamed(world)


@proof("layout/retired-names", "the old name in a script, in capitals",
       expect="fail", contains="holds the retired name")
def _(world: World) -> None:
    _renamed(world)
    world.write("scripts/build.sh", "echo building OLD-TOOLS\n")


@proof("layout/retired-names", "a second mention in the allowed file", expect="fail", contains="holds the retired name")
def _(world: World) -> None:
    _renamed(world, HISTORY + "\nSee the old-tools wiki.\n")


@proof("layout/retired-names", "the allowed line written twice", expect="fail", contains="holds the retired name")
def _(world: World) -> None:
    _renamed(world, HISTORY + "\nThis project was called old-tools until 2026.\n")


@proof("layout/retired-names", "the allowed line, in another file", expect="fail", contains="holds the retired name")
def _(world: World) -> None:
    _renamed(world)
    world.write("docs/about.md", "This project was called old-tools until 2026.\n")


@proof("layout/retired-names", "a folder still named the old way",
       expect="fail", contains="the path holds the retired name")
def _(world: World) -> None:
    _renamed(world)
    world.write("docs/old-tools/notes.md", "# Notes\n")


@proof("layout/retired-names", "an allowance that matches nothing", expect="refuse", contains="matches no line")
def _(world: World) -> None:
    _renamed(world, "# History\n")


@proof("layout/retired-names", "an empty name", expect="refuse", contains="a retired name is empty")
def _(world: World) -> None:
    _renamed(world, setup='[rules."layout/retired-names"]\nnames = [" "]\n')


# -- layout/no-ignored-citations ----------------------------------------------------------------

PAGES = Param("pages", [str], None, "larger", "the pages it reads, as path patterns, such as **/*.md")
INDEX = Param(
    "index", [str], [], "smaller",
    "tracked files that list git-ignored paths a page may still cite, such as an archive's index",
)
#: A path with at least one folder in it, as written in a code span.
_PATH = re.compile(r"[\w.@+~-]+(?:/[\w.@+~-]*)+")
#: What follows a path and is not part of it: a line number, or an anchor.
_SUFFIX = re.compile(r"(?::\d+)+$|#.*$")


def citations(page: str, text: str) -> list[tuple[int, str]]:
    """(line, repository path) for each file a page cites: a link target, resolved from the page's folder,
    or a code span in prose that holds a path with a folder in it, read from the repository root."""
    found = []
    for line, target in claims.find_links(text):
        name = claims.link_path(page, target)
        if name and not name.startswith(".."):
            found.append((line, name))
    for line, prose in markdown.prose_lines(text):
        for span in markdown.code_spans(prose):
            span = _SUFFIX.sub("", span)
            if _PATH.fullmatch(span) and not span.startswith("~"):
                name = posixpath.normpath(span.removeprefix("./"))
                if not name.startswith(".."):
                    found.append((line, name))
    return found


def _listed(name: str, entries: set[str]) -> bool:
    return any(name == entry or name.startswith(f"{entry}/") for entry in entries)


@rule(
    "layout/no-ignored-citations",
    "No page links or cites a path git ignores, unless a tracked index the project names lists it.",
    params=(PAGES, INDEX),
    requires=("pages",),
    learned="A page linked a file kept only on one machine, and the link was broken in every clone.",
)
def no_ignored_citations(ctx: Context) -> None:
    entries: set[str] = set()
    for index in ctx.param("index"):
        text = ctx.read(index) if index in ctx.all_files else None
        if text is None:
            ctx.refuse("the index is not a tracked text file, so what it lists cannot be read", where=index,
                       fix="track the index, or correct its path")
            return
        entries |= {name for _, name in citations(index, text)}
    cited: list[tuple[str, int, str]] = []
    for page in sorted({name for pattern in ctx.param("pages") for name in ctx.files(pattern)}):
        text = ctx.read(page)
        if text is None:
            continue  # not text, so not a page
        ctx.inspect()
        cited += [(page, line, name) for line, name in sorted(set(citations(page, text)))]
    asked = {name: name + "/" if (ctx.root / name).is_dir() else name for _, _, name in cited}
    ignored = ctx.git.ignored(sorted(set(asked.values())))
    if ignored is None:
        ctx.refuse("git cannot say which paths it ignores here", fix="run the check inside the git repository")
        return
    for page, line, name in cited:
        if asked[name] in ignored and not _listed(name, entries):
            where_else = f", or list it in {' or '.join(ctx.param('index'))}" if ctx.param("index") else ""
            ctx.breach(f"this page cites {name}, which git ignores, so a clone does not have it", where=page,
                       line=line, fix=f"cite a tracked file, or track this one{where_else}")


CITE_SETUP = """
    [rules."layout/no-ignored-citations"]
    pages = ["**/*.md"]
    index = ["docs/archive.md"]
"""
IGNORES = "/output/\n*.pdf\n"
ARCHIVE = "# What is kept outside git\n\n- `output/2026/`: the runs of 2026, in the bucket\n"


def _cited(world: World, page: str, setup: str = CITE_SETUP, archive: str | None = ARCHIVE) -> None:
    world.manifest(setup)
    world.write(".gitignore", IGNORES)
    world.write("scripts/run.sh", "echo run > output/2026/run.txt\n")
    world.write("docs/manual.md", "# The manual\n")
    if archive is not None:
        world.write("docs/archive.md", archive)
    world.write("README.md", page)
    world.commit("start")


@proof("layout/no-ignored-citations", "tracked links, a listed run, an example in code, a force-tracked file",
       expect="pass")
def _(world: World) -> None:
    _cited(world, "# Tools\n\nSee [the manual](docs/manual.md) and `scripts/run.sh`.\n"
                  "The run is in `output/2026/run.txt:3`.\n\n```\nls output/2027/\n```\n"
                  "The [signed form](docs/form.pdf) is tracked.\n")
    world.write("docs/form.pdf", "a form\n")
    world.git("add", "-f", "docs/form.pdf")
    world.commit("the form")


@proof("layout/no-ignored-citations", "a link to an ignored file", expect="fail",
       contains="cites docs/vendor.pdf, which git ignores")
def _(world: World) -> None:
    _cited(world, "# Tools\n\nRead [the vendor's guide](docs/vendor.pdf).\n")


@proof("layout/no-ignored-citations", "a code span that cites an ignored folder no index lists", expect="fail",
       contains="cites output/2027/summary.csv")
def _(world: World) -> None:
    _cited(world, "# Tools\n\nThe summary is in `output/2027/summary.csv`.\n")


@proof("layout/no-ignored-citations", "an ignored path cited with no index named", expect="fail",
       contains="which git ignores")
def _(world: World) -> None:
    _cited(world, "The run is in `output/2026/run.txt`.\n", setup='[rules."layout/no-ignored-citations"]\n'
                                                                   'pages = ["**/*.md"]\n')


@proof("layout/no-ignored-citations", "an index that is itself ignored", expect="refuse",
       contains="not a tracked text file")
def _(world: World) -> None:
    _cited(world, "The run is in `output/2026/run.txt`.\n",
           setup=CITE_SETUP.replace("docs/archive.md", "output/archive.md"), archive=None)
    world.write("output/archive.md", ARCHIVE)


@proof("layout/no-ignored-citations", "outside a git repository", expect="refuse", contains="git cannot say")
def _(world: World) -> None:
    world.manifest(CITE_SETUP)
    world.write("docs/archive.md", ARCHIVE)
    world.write("README.md", "See [the manual](docs/manual.md).\n")
