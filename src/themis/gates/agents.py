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
    "The shipped hooks are present in the host's settings.",
    learned="A hook was removed from the settings, and nothing said the guard was gone.",
)
def hooks_installed(ctx: Context) -> None:
    if not ctx.manifest.table("agents").get("host"):
        ctx.not_configured("name the agent host under [agents]")
    ctx.inspect()
    absent = hooks.missing(ctx.root)
    if absent is None:
        ctx.refuse("the host's settings file cannot be read", where=hooks.SETTINGS, fix="correct the JSON")
        return
    for event in absent:
        ctx.breach(f"the {event} hook is not installed", where=hooks.SETTINGS, fix="run `themis hooks install`")


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
