"""Gate: agents — the agent's own guards are in place.

Also the gate for views: a page written from records must equal what the records produce.
"""

from __future__ import annotations

from themis import hooks, render
from themis.rule import Context, proof, rule

AGENTS = """
    [agents]
    host = "claude"
    instructions = "AGENTS.md"
"""


@rule(
    "agents/hooks-installed",
    "The shipped hooks are present in the host's settings, and the git hooks run Themis when the project declares them.",
    learned="A hook was removed from the settings, and nothing said the guard was gone.",
)
def hooks_installed(ctx: Context) -> None:
    table = ctx.manifest.table("agents")
    if not table.get("host") and not table.get("git_hooks"):
        ctx.not_configured("name the agent host, or the git hooks folder as git_hooks, under [agents]")
    if table.get("host"):
        ctx.inspect()
        absent = hooks.missing(ctx.root)
        if absent is None:
            ctx.refuse("the host's settings file cannot be read", where=hooks.SETTINGS, fix="correct the JSON")
        for event in absent or []:
            ctx.breach(f"the {event} hook is not installed", where=hooks.SETTINGS, fix="run `themis hooks install`")
    if table.get("git_hooks"):
        ctx.inspect()
        for what, where in hooks.git_missing(ctx.root, table["git_hooks"]):
            ctx.breach(what, where=where, fix="run `themis hooks install --git`, and commit the hooks")


@proof("agents/hooks-installed", "all three hooks installed", expect="pass")
def _(world):
    world.manifest(AGENTS)
    hooks.install(world.root, "themis")


@proof("agents/hooks-installed", "no settings file at all", expect="fail", contains="the Stop hook is not installed")
def _(world):
    world.manifest(AGENTS)


@proof("agents/hooks-installed", "one hook taken out afterwards", expect="fail", contains="the Stop hook is not installed")
def _(world):
    world.manifest(AGENTS)
    path = hooks.install(world.root, "themis")
    path.write_text(path.read_text().replace("themis hook stop", "true"), encoding="utf-8")


@proof("agents/hooks-installed", "settings that are not JSON", expect="refuse", contains="cannot be read")
def _(world):
    world.manifest(AGENTS)
    world.write(hooks.SETTINGS, "{not json")


@proof("agents/hooks-installed", "hooks installed beside the project's own settings", expect="pass")
def _(world):
    world.manifest(AGENTS)
    world.write(hooks.SETTINGS, '{"permissions": {"deny": ["Tool"]}, "hooks": {"Stop": [{"hooks": []}]}}')
    hooks.install(world.root, "themis")


GIT_HOOKS = """
    [agents]
    git_hooks = ".githooks"
"""


def _git_hooks(world, setup: str = GIT_HOOKS) -> None:
    world.manifest(setup)
    world.commit("start")
    hooks.install_git(world.root, ".githooks", "themis")


@proof("agents/hooks-installed", "git hooks declared, installed and switched on", expect="pass")
def _(world):
    _git_hooks(world)


@proof("agents/hooks-installed", "the agent hooks and the git hooks, both in place", expect="pass")
def _(world):
    _git_hooks(world, AGENTS + '    git_hooks = ".githooks"\n')
    hooks.install(world.root, "themis")


@proof("agents/hooks-installed", "git hooks declared and never installed", expect="fail",
       contains="the pre-commit git hook is not installed")
def _(world):
    world.manifest(GIT_HOOKS)
    world.commit("start")


@proof("agents/hooks-installed", "git hooks written, but git not pointed at them", expect="fail",
       contains="git does not run the hooks in .githooks")
def _(world):
    _git_hooks(world)
    world.git("config", "--unset", "core.hooksPath")


@proof("agents/hooks-installed", "a git hook that no longer runs Themis", expect="fail",
       contains="the pre-push git hook does not run `themis check`")
def _(world):
    _git_hooks(world)
    world.write(".githooks/pre-push", "#!/bin/sh\nexit 0\n")
    (world.root / ".githooks/pre-push").chmod(0o755)


@proof("agents/hooks-installed", "a pre-push hook that runs only the check of changed paths", expect="fail",
       contains="the pre-push git hook does not run `themis check`")
def _(world):
    _git_hooks(world)
    world.write(".githooks/pre-push", '#!/bin/sh\nexec themis check --changed\n')
    (world.root / ".githooks/pre-push").chmod(0o755)


@proof("agents/hooks-installed", "a hook that names the check only in a comment", expect="fail",
       contains="the pre-commit git hook does not run `themis check --changed`")
def _(world):
    _git_hooks(world)
    world.write(".githooks/pre-commit", "#!/bin/sh\n# exec themis check --changed\nexit 0\n")
    (world.root / ".githooks/pre-commit").chmod(0o755)


@proof("agents/hooks-installed", "hooks written by hand that run the checks through another command", expect="pass")
def _(world):
    _git_hooks(world)
    world.write(".githooks/pre-commit", "#!/bin/sh\n# runs the rules\nset -e\nuv run --frozen themis check --changed\n")
    world.write(".githooks/pre-push",
                '#!/bin/sh\ncd "$(git rev-parse --show-toplevel)"\nexec python -m themis.cli check\n')
    for event in ("pre-commit", "pre-push"):
        (world.root / ".githooks" / event).chmod(0o755)


@proof("agents/hooks-installed", "a git hook git cannot run", expect="fail", contains="is not executable")
def _(world):
    _git_hooks(world)
    (world.root / ".githooks/pre-commit").chmod(0o644)


@proof("agents/hooks-installed", "the agent hooks in place, the declared git hooks missing", expect="fail",
       contains="the pre-push git hook is not installed")
def _(world):
    world.manifest(AGENTS + '    git_hooks = ".githooks"\n')
    world.commit("start")
    hooks.install(world.root, "themis")


@rule(
    "agents/instructions-generated",
    "The rules section of the agent instructions equals what the rules produce.",
    learned="The instructions said one thing while the checks enforced another.",
)
def instructions_generated(ctx: Context) -> None:
    path = ctx.manifest.table("agents").get("instructions")
    if not path:
        ctx.not_configured("name the instructions file under [agents]")
    ctx.inspect()
    text = ctx.read(path)
    if text is None:
        ctx.refuse("the instructions file cannot be read", where=path, fix="run `themis render`")
        return
    current = render.block(text, "rules")
    if current is None:
        ctx.breach("the instructions hold no generated rules section", where=path, fix="run `themis render`")
    elif current.strip() != render.VIEWS["rules"](ctx.root, ctx.manifest).strip():
        ctx.breach("the rules section differs from the rules in force", where=path, fix="run `themis render`")


@proof("agents/instructions-generated", "a section written by the tool", expect="pass")
def _(world):
    from themis import manifest as manifests

    world.manifest(AGENTS)
    world.write("AGENTS.md", "# Instructions\n\nWritten by hand above the block.\n")
    render.write(world.root, manifests.load(world.root), "AGENTS.md", "rules")


@proof("agents/instructions-generated", "a rule enforced after the section was written", expect="fail",
       contains="differs from the rules in force")
def _(world):
    from themis import manifest as manifests

    world.manifest(AGENTS)
    render.write(world.root, manifests.load(world.root), "AGENTS.md", "rules")
    world.manifest(AGENTS + '\n[rules]\n"config/locked" = "enforce"\n')


@proof("agents/instructions-generated", "instructions with no generated section", expect="fail",
       contains="no generated rules section")
def _(world):
    world.manifest(AGENTS)
    world.write("AGENTS.md", "# Instructions\n\nAll written by hand.\n")


@proof("agents/instructions-generated", "no instructions file", expect="refuse", contains="cannot be read")
def _(world):
    world.manifest(AGENTS)


@rule(
    "views/current",
    "Each generated page equals what its records produce.",
    learned="A hand-kept table drifted from the records it was meant to show.",
)
def views_current(ctx: Context) -> None:
    if not ctx.manifest.views:
        ctx.not_configured("list the generated pages under [views]")
    for path, name in sorted(ctx.manifest.views.items()):
        ctx.inspect()
        wanted = render.expected(ctx.root, ctx.manifest, path, name)
        if wanted is None:
            ctx.refuse(f"there is no view named {name!r}", where="themis.toml",
                       fix=f"choose one of: {', '.join(sorted(render.VIEWS))}")
        elif ctx.read(path) != wanted:
            ctx.breach(f"the page differs from its {name} view", where=path, fix="run `themis render`")


VIEWS = """
    [views]
    "LEDGER.md" = "ledger"
"""
ROW = 'work = "work/a"\nstate = "promised"\nquestion = "does it hold?"\n'


@proof("views/current", "a page written by the tool", expect="pass")
def _(world):
    from themis import manifest as manifests

    world.manifest(VIEWS)
    world.write("ledger/a.toml", ROW)
    render.write(world.root, manifests.load(world.root), "LEDGER.md", "ledger")


@proof("views/current", "a record added after the page was written", expect="fail", contains="differs from its ledger view")
def _(world):
    from themis import manifest as manifests

    world.manifest(VIEWS)
    world.write("ledger/a.toml", ROW)
    render.write(world.root, manifests.load(world.root), "LEDGER.md", "ledger")
    world.write("ledger/b.toml", ROW.replace("work/a", "work/b"))


@proof("views/current", "a page edited by hand", expect="fail", contains="differs from its ledger view")
def _(world):
    from themis import manifest as manifests

    world.manifest(VIEWS)
    world.write("ledger/a.toml", ROW)
    path = render.write(world.root, manifests.load(world.root), "LEDGER.md", "ledger")
    path.write_text(path.read_text().replace("promised", "done"), encoding="utf-8")


@proof("views/current", "a view name that does not exist", expect="refuse", contains="no view named")
def _(world):
    world.manifest('[views]\n"LEDGER.md" = "leger"\n')
