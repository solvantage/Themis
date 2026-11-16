"""Gate: config — the configuration cannot be quietly weakened."""

from __future__ import annotations

from themis import configguard, paths, roles, standards
from themis import manifest as manifests
from themis.rule import Context, proof, rule

MANIFEST = """
    [project]
    name = "world"
"""
LOCKED_ROLE = """
    [project]
    name = "world"

    [roles.writer]
    branches = ["writer/*"]
    paths = ["content/**"]
"""


def _main(ctx: Context) -> str | None:
    return ctx.git.main_ref(ctx.manifest.project.get("main"))


# -- config/valid -------------------------------------------------------------------------------


@rule(
    "config/valid",
    "The manifest matches its schema. An unknown key, a wrong type or an unknown rule id is refused, never defaulted.",
    learned="A mistyped setting silently became a weaker default.",
)
def valid(ctx: Context) -> None:
    if not ctx.manifest.present:
        ctx.refuse("there is no themis.toml in this folder", fix="run `themis init`")
        return
    ctx.inspect()


@proof("config/valid", "a plain manifest is accepted", expect="pass")
def _(world):
    world.manifest(MANIFEST)


@proof("config/valid", "a mistyped key is refused", expect="refuse", contains="is not a known key")
def _(world):
    world.manifest('[project]\nname = "world"\nstrikt = true\n')


@proof("config/valid", "an unknown rule id is refused", expect="refuse", contains="is not a rule Themis knows")
def _(world):
    world.manifest('[rules]\n"order/sealed-frist" = "enforce"\n')


@proof("config/valid", "a level that does not exist is refused", expect="refuse", contains="must be")
def _(world):
    world.manifest('[rules]\n"config/valid" = "strict"\n')


@proof("config/valid", "a folder with no manifest is refused", expect="refuse", contains="no themis.toml")
def _(world):
    world.write("README.md", "nothing here\n")


# -- config/locked ------------------------------------------------------------------------------


@rule(
    "config/locked",
    "A lock file holds the hash of the effective configuration. A manifest that differs from its lock fails.",
    learned="A check script was edited to pass everything, and nothing noticed.",
)
def locked(ctx: Context) -> None:
    ctx.inspect()
    lock = configguard.read_lock(ctx.root)
    if lock is None:
        ctx.breach("there is no themis.lock, or it cannot be read", where=configguard.LOCK_FILE,
                   fix="run `themis config lock` and commit the lock")
    elif lock.get("hash") != configguard.effective_hash(ctx.manifest):
        ctx.breach("the configuration differs from its lock", where=configguard.LOCK_FILE,
                   fix="run `themis config diff` to see what moved, then `themis config lock`")


def _lock(world) -> None:
    configguard.write_lock(manifests.load(world.root))


@proof("config/locked", "a manifest that matches its lock passes", expect="pass")
def _(world):
    world.manifest(MANIFEST)
    _lock(world)


@proof("config/locked", "a manifest changed after its lock fails", expect="fail", contains="differs from its lock")
def _(world):
    world.manifest(MANIFEST)
    _lock(world)
    world.manifest(MANIFEST + '\n[rules]\n"config/locked" = "off"\n')


@proof("config/locked", "a wrapped script edited after the lock fails", expect="fail", contains="differs from its lock")
def _(world):
    world.write("tools/check.py", "raise SystemExit(1)\n")
    world.manifest(MANIFEST + """
        [[checks.external]]
        id = "ext/check"
        description = "The check passes"
        command = ["python3", "tools/check.py"]
    """)
    _lock(world)
    world.write("tools/check.py", "raise SystemExit(0)\n")


@proof("config/locked", "a missing lock fails", expect="fail", contains="no themis.lock")
def _(world):
    world.manifest(MANIFEST)


# -- config/no-silent-weakening -----------------------------------------------------------------


@rule(
    "config/no-silent-weakening",
    "A change that weakens the configuration reaches the main line only with the owner's grant and a written reason.",
    learned="A rule was switched off in the same change that broke it.",
)
def no_silent_weakening(ctx: Context) -> None:
    main = _main(ctx)
    if main is None:
        ctx.refuse("there is no main line to compare the manifest with", fix="commit to main, or set project.main")
        return
    ctx.inspect()
    before = ctx.git.show(main, manifests.MANIFEST_FILE)
    if before is None:
        return  # the manifest is new: there was nothing to weaken
    old = configguard.parse(before)
    if old is None:
        ctx.refuse("the manifest on the main line cannot be read", where=manifests.MANIFEST_FILE)
        return
    weakened = [change for change in configguard.classify(old, ctx.manifest.raw) if change.kind == "weakening"]
    if not weakened:
        return
    wanted = configguard.effective_hash(ctx.manifest)
    if any(grant.get("action") == "config" and grant.get("target") == wanted for grant in ctx.records("grant")):
        return
    for change in weakened:
        ctx.breach(f"weakened with no grant from the owner: {change.what}", where=manifests.MANIFEST_FILE,
                   fix="the owner runs `themis grant config --reason ...` for this exact configuration")


ENFORCED = MANIFEST + '\n[rules]\n"config/locked" = "enforce"\n'
RELAXED = MANIFEST + '\n[rules]\n"config/locked" = "warn"\n'


def _grant(world, target: str) -> None:
    world.write("grants/config-1.toml", f"""
        action = "config"
        target = "{target}"
        granted_by = "owner"
        granted_at = "2026-01-01T00:00:00+00:00"
        reason = "the lock is being introduced in stages"
    """)


@proof("config/no-silent-weakening", "a tightening needs no grant", expect="pass")
def _(world):
    world.manifest(RELAXED)
    world.commit("main")
    world.branch("stricter")
    world.manifest(ENFORCED)


@proof("config/no-silent-weakening", "a rule lowered on a branch with no grant fails", expect="fail",
       contains="level enforce to warn")
def _(world):
    world.manifest(ENFORCED)
    world.commit("main")
    world.branch("looser")
    world.manifest(RELAXED)
    world.commit("lower the level")


@proof("config/no-silent-weakening", "a removed external check with no grant fails", expect="fail",
       contains="the check was removed")
def _(world):
    world.manifest(MANIFEST + """
        [[checks.external]]
        id = "ext/check"
        description = "The check passes"
        command = ["true"]
    """)
    world.commit("main")
    world.branch("drop")
    world.manifest(MANIFEST)


@proof("config/no-silent-weakening", "a weakening with the owner's grant for that configuration passes", expect="pass")
def _(world):
    world.manifest(ENFORCED)
    world.commit("main")
    world.branch("looser")
    world.manifest(RELAXED)
    _grant(world, configguard.effective_hash(manifests.load(world.root)))


@proof("config/no-silent-weakening", "a grant for another configuration does not count", expect="fail",
       contains="weakened with no grant")
def _(world):
    world.manifest(ENFORCED)
    world.commit("main")
    world.branch("looser")
    world.manifest(RELAXED)
    _grant(world, "0" * 64)


@proof("config/no-silent-weakening", "a new manifest has nothing to weaken", expect="pass")
def _(world):
    world.write("README.md")
    world.commit("main")
    world.manifest(MANIFEST)


@proof("config/no-silent-weakening", "with no main line the rule cannot decide", expect="refuse", contains="no main line")
def _(world):
    world.manifest(MANIFEST)


# -- config/protected ---------------------------------------------------------------------------


@rule(
    "config/protected",
    "The manifest, the lock, the local pack, the hook settings, the grants and the receipts are changed by no agent role.",
    learned="An agent edited the checker that judged its own work.",
)
def protected(ctx: Context) -> None:
    if not ctx.manifest.roles:
        ctx.not_configured("declare the agent roles under [roles]")
    main = _main(ctx)
    if main is None:
        ctx.refuse("there is no main line to compare this work with", fix="commit to main, or set project.main")
        return
    ctx.inspect()
    role = roles.current(ctx.manifest, ctx.git)
    if not roles.is_agent(role):
        return
    guarded = configguard.protected_paths(ctx.manifest)
    for name in ctx.git.changed_against(main):
        if paths.matches_any(name, guarded):
            ctx.breach(f"the role {role[0]} changed a protected file", where=name,
                       fix="take the change out of this branch; only the owner changes this file")


@proof("config/protected", "an agent role that changes its own work passes", expect="pass")
def _(world):
    world.manifest(LOCKED_ROLE)
    world.commit("main")
    world.branch("writer/topic")
    world.write("content/script.md")
    world.commit("a script")


@proof("config/protected", "an agent role that edits the manifest fails", expect="fail", contains="changed a protected file")
def _(world):
    world.manifest(LOCKED_ROLE)
    world.commit("main")
    world.branch("writer/topic")
    world.manifest(LOCKED_ROLE + '\n[rules]\n"config/protected" = "off"\n')
    world.commit("switch the guard off")


@proof("config/protected", "an agent role that edits a wrapped script fails", expect="fail", contains="changed a protected file")
def _(world):
    world.write("tools/check.py", "raise SystemExit(1)\n")
    world.manifest(LOCKED_ROLE + """
        [[checks.external]]
        id = "ext/check"
        description = "The check passes"
        command = ["python3", "tools/check.py"]
    """)
    world.commit("main")
    world.branch("writer/topic")
    world.write("tools/check.py", "raise SystemExit(0)\n")


@proof("config/protected", "the owner may change the manifest", expect="pass")
def _(world):
    world.manifest(LOCKED_ROLE)
    world.commit("main")
    world.branch("owner/settings")
    world.manifest(LOCKED_ROLE + '\n[config]\nprotected = ["tools/**"]\n')
    world.commit("protect the tools")


# -- config/standard-floor ----------------------------------------------------------------------


@rule(
    "config/standard-floor",
    "A value below the declared standard's floor is listed, and fails when the project sets strict.",
    learned="Two projects claimed one standard while one of them had loosened it.",
)
def standard_floor(ctx: Context) -> None:
    standard = standards.declared(ctx.manifest)
    if standard is None:
        ctx.not_configured("declare a standard under [project]")
    ctx.inspect(len(standard.levels) + sum(len(floors) for floors in standard.floors.values()) or 1)
    if not ctx.manifest.strict:
        return
    for deviation in standards.deviations(ctx.manifest, standard):
        ctx.breach(f"below the standard {standard.id}: {deviation.what}", where=manifests.MANIFEST_FILE,
                   fix=f"raise {deviation.rule} to the standard's floor, or stop declaring the standard")


LOCAL_PACK = """
    from themis.pack import Pack, Standard

    pack = Pack(name="demo", standards={"demo/1": Standard("demo/1", levels={"config/locked": "enforce"})})
"""


def _with_standard(world, rules: str, strict: str = "true") -> None:
    world.write("pack/__init__.py", LOCAL_PACK)
    world.manifest(f"""
        [project]
        name = "world"
        local_pack = "pack"
        standard = "demo/1"
        strict = {strict}

        [rules]
        {rules}
    """)


@proof("config/standard-floor", "a project at the floor passes", expect="pass")
def _(world):
    _with_standard(world, '"config/locked" = "enforce"')


@proof("config/standard-floor", "a strict project below the floor fails", expect="fail", contains="below the standard demo/1")
def _(world):
    _with_standard(world, '"config/locked" = "warn"')


@proof("config/standard-floor", "a project that is not strict is listed, not failed", expect="pass")
def _(world):
    _with_standard(world, '"config/locked" = "warn"', strict="false")
