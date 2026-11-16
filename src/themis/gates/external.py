"""Gate: external — the project's own checks, held to the same laws.

Each declared check runs as its own rule, under the id the project gave it. The two rules here
look at the declarations themselves.
"""

from __future__ import annotations

import shutil

from themis import external, proofs
from themis.rule import Context, proof, rule


@rule(
    "external/declared",
    "Each declared command can be started, and no exit code is both a pass and a fail.",
    learned="A check whose program was missing was read as passing.",
)
def declared(ctx: Context) -> None:
    if not ctx.manifest.external:
        ctx.not_configured("declare a check under [[checks.external]]")
    for table in ctx.manifest.external:
        check = external.Check.from_table(table)
        ctx.inspect()
        both = sorted(set(check.passes) & set(check.fails))
        if both:
            ctx.breach(f"{check.id}: exit code {both[0]} is mapped to both pass and fail", where="themis.toml",
                       fix="an exit code means one thing")
        program = check.command[0]
        if shutil.which(program) is None and not (ctx.root / check.cwd / program).is_file():
            ctx.refuse(f"{check.id}: the program `{program}` cannot be found", where="themis.toml",
                       fix="install it, or correct the command")


CHECK = """
    [[checks.external]]
    id = "ext/check"
    description = "The check passes"
    command = ["{program}"]
    {extra}
"""


@proof("external/declared", "a command that exists, with a clear mapping", expect="pass")
def _(world):
    world.manifest(CHECK.format(program="python3", extra=""))


@proof("external/declared", "one exit code mapped both ways", expect="fail", contains="both pass and fail")
def _(world):
    world.manifest(CHECK.format(program="python3", extra="verdicts = { pass = [0, 1], fail = [1] }"))


@proof("external/declared", "a program that is not installed", expect="refuse", contains="cannot be found")
def _(world):
    world.manifest(CHECK.format(program="no-such-program-anywhere", extra=""))


@rule(
    "external/proven",
    "Each external check has a plant that makes it fail and an honest case it passes.",
    learned="A check that had only ever passed turned out to check nothing.",
)
def proven(ctx: Context) -> None:
    if not ctx.manifest.external:
        ctx.not_configured("declare a check under [[checks.external]]")
    for table in ctx.manifest.external:
        ctx.inspect()
        standing = proofs.external_standing(table)
        if standing != "proven":
            ctx.breach(f"{table['id']} is {standing}", where="themis.toml",
                       fix="add a proof with a plant and expect = \"fail\", and one with expect = \"pass\"")


PROVEN = CHECK.format(program="python3", extra="") + """
    [[checks.external.proofs]]
    name = "a planted fault is caught"
    plant = { file = "notes.md", append = "bad\\n" }
    expect = "fail"

    [[checks.external.proofs]]
    name = "the honest case passes"
    expect = "pass"
"""


@proof("external/proven", "a check with a planted fault and an honest case", expect="pass")
def _(world):
    world.manifest(PROVEN)


@proof("external/proven", "a check with no proof at all", expect="fail", contains="unproven: no proof at all")
def _(world):
    world.manifest(CHECK.format(program="python3", extra=""))


@proof("external/proven", "a check that was only ever shown passing", expect="fail", contains="unproven: no planted fault")
def _(world):
    world.manifest(CHECK.format(program="python3", extra="") + """
        [[checks.external.proofs]]
        name = "the honest case passes"
        expect = "pass"
    """)
