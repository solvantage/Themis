"""Gate: scope — each role stays in its lane.

A project declares its roles in the manifest: the paths a role may change, and the branches it
works on. These rules check that an agent's role changed only its own paths, that no agent merged
into the main line, that each run read the rules as they are now, and that the tools taken away
from agents are still taken away in the host's settings.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from themis import paths, receipts, roles
from themis.rule import Context, Param, proof, rule

AGENTS = Param("agents", [str], None, "larger", "the committer emails that belong to agents")
RULE_FILES = Param("rule_files", [str], None, "larger", "the files that are the rules an agent reads")
DENIED = Param("denied", [str], None, "larger", "the tools no agent may use, as the host's settings name them")
SETTINGS = Param("settings", str, ".claude/settings.json", None, "the host's settings file")
NO_MAIN = "commit to main, or set project.main"


def _main(ctx: Context) -> str | None:
    return ctx.git.main_ref(ctx.manifest.project.get("main"))


def rules_hash(root: Path, files: Iterable[str]) -> str:
    """One hash over the rule files: each file's name and its bytes, in sorted order.

    A harness calls this when a run starts, and writes the answer into the run's receipt as
    `rules_hash`. A file that cannot be read is hashed as missing, so the answer still changes.
    """
    digest = hashlib.sha256()
    for name in sorted(set(files)):
        try:
            data = (Path(root) / name).read_bytes()
            digest.update(f"{name}\0{len(data)}\0".encode() + data)
        except OSError:
            digest.update(f"{name}\0missing\0".encode())
    return digest.hexdigest()


# -- scope/paths --------------------------------------------------------------------------------


@rule(
    "scope/paths",
    "A role's pull request changes only the paths that role may change.",
    learned="An agent asked to write one script also rewrote the code that checked it.",
)
def role_paths(ctx: Context) -> None:
    if not ctx.manifest.roles:
        ctx.not_configured("declare the roles and their paths under [roles]")
    main = _main(ctx)
    if main is None:
        ctx.refuse("there is no main line to compare this work with", fix=NO_MAIN)
        return
    ctx.inspect()
    role = roles.current(ctx.manifest, ctx.git)
    if not roles.is_agent(role):
        return  # the owner's work, or work no role claims, is not limited to a lane
    allowed = role[1].get("paths", [])
    lane = f"only {', '.join(allowed)}" if allowed else "no path at all"
    for name in ctx.git.changed_against(main):
        if not paths.matches_any(name, allowed):
            ctx.breach(f"the role {role[0]} changed a path it may not change", where=name,
                       fix=f"take the change out of this branch; the role {role[0]} may change {lane}")


ROLES = """
    [project]
    name = "world"

    [roles.writer]
    branches = ["writer/*"]
    paths = ["content/**"]

    [roles.reader]
    branches = ["reader/*"]

    [roles.owner]
    branches = ["owner/*"]
    owner = true
"""


def _on_branch(world, branch: str, *changed: str) -> None:
    world.manifest(ROLES)
    world.write("src/app.py", "print('one')\n")
    world.commit("main")
    world.branch(branch)
    for name in changed:
        world.write(name, "changed\n")


@proof("scope/paths", "an agent role that changes only its own paths", expect="pass")
def _(world):
    _on_branch(world, "writer/topic", "content/script.md", "content/notes/sources.md")
    world.commit("a script")


@proof("scope/paths", "an agent role that changes code outside its lane", expect="fail",
       contains="the role writer changed a path it may not change")
def _(world):
    _on_branch(world, "writer/topic", "content/script.md", "src/app.py")
    world.commit("a script, and a change to the code")


@proof("scope/paths", "a file outside the lane counts before it is committed", expect="fail", contains="may not")
def _(world):
    _on_branch(world, "writer/topic", "tools/helper.py")


@proof("scope/paths", "a role that was given no paths may change nothing", expect="fail",
       contains="the role reader changed a path it may not change")
def _(world):
    _on_branch(world, "reader/check", "content/script.md")


@proof("scope/paths", "the owner may change any path", expect="pass")
def _(world):
    _on_branch(world, "owner/cleanup", "src/app.py", "content/script.md")
    world.commit("the owner's change")


@proof("scope/paths", "work on a branch no role claims is not limited", expect="pass")
def _(world):
    _on_branch(world, "fix/typo", "src/app.py")
    world.commit("a fix")


@proof("scope/paths", "with no main line the rule cannot decide", expect="refuse", contains="no main line")
def _(world):
    world.manifest(ROLES)


# -- scope/no-self-approval ---------------------------------------------------------------------


@rule(
    "scope/no-self-approval",
    "No agent merges into the main line.",
    params=(AGENTS,),
    requires=("agents",),
    learned="An agent merged its own pull request before anyone had read it.",
)
def no_self_approval(ctx: Context) -> None:
    main = _main(ctx)
    log = ctx.git.run("log", "--first-parent", "--merges", "--format=%H%x09%ce%x09%cs", main) if main else None
    if log is None:
        ctx.refuse("there is no main line, or its merges cannot be read", fix=NO_MAIN)
        return
    ctx.inspect()  # the main line itself: with no merge on it yet, no agent has merged
    agents = {email.strip().casefold() for email in ctx.param("agents")}
    start = ctx.since.isoformat() if ctx.since else ""
    for line in log.splitlines():
        commit, email, date = (line.split("\t") + ["", ""])[:3]
        if date < start:
            continue  # history is never rewritten: a merge from before the rule's start date stays
        ctx.inspect()
        if email.strip().casefold() in agents:
            ctx.breach(f"the merge {commit[:12]} into the main line was made by an agent, {email}",
                       fix="the owner reads and merges each pull request; take the right to merge away from the agent")


APPROVAL = """
    [rules."scope/no-self-approval"]
    agents = ["writer@agents.invalid"]
"""


def _git_as(world, email: str, *args: str) -> None:
    """Run git in the world as another committer: `World.git` always commits as the same one."""
    stamp = "2026-01-01T01:00:00+00:00"
    env = {**os.environ, "GIT_AUTHOR_NAME": "someone", "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": stamp,
           "GIT_COMMITTER_NAME": "someone", "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": stamp,
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    subprocess.run(["git", *args], cwd=world.root, env=env, check=True, capture_output=True)


def _agent_branch(world, setup: str = APPROVAL) -> None:
    """A main line, and beside it a branch that holds one commit made by the agent."""
    world.manifest(setup)
    world.commit("start")
    world.branch("writer/topic")
    world.write("content/script.md", "a script\n")
    _git_as(world, "writer@agents.invalid", "add", "-A")
    _git_as(world, "writer@agents.invalid", "commit", "-q", "-m", "a script")
    world.checkout("main")


@proof("scope/no-self-approval", "the owner merges a branch of an agent's commits", expect="pass")
def _(world):
    _agent_branch(world)
    world.merge("writer/topic")


@proof("scope/no-self-approval", "an agent may merge main into its own branch", expect="pass")
def _(world):
    _agent_branch(world)
    world.write("README.md", "news on the main line\n")
    world.commit("the main line moves on")
    world.checkout("writer/topic")
    _git_as(world, "writer@agents.invalid", "merge", "-q", "--no-ff", "-m", "catch up with main", "main")
    world.checkout("main")
    world.merge("writer/topic")


@proof("scope/no-self-approval", "a main line with no merge yet", expect="pass")
def _(world):
    world.manifest(APPROVAL)
    world.commit("start")


@proof("scope/no-self-approval", "an agent merges its own branch into the main line", expect="fail",
       contains="was made by an agent, writer@agents.invalid")
def _(world):
    _agent_branch(world)
    _git_as(world, "writer@agents.invalid", "merge", "-q", "--no-ff", "-m", "merge writer/topic", "writer/topic")


@proof("scope/no-self-approval", "an email is matched whatever its capitals", expect="fail", contains="by an agent")
def _(world):
    _agent_branch(world)
    _git_as(world, "Writer@Agents.invalid", "merge", "-q", "--no-ff", "-m", "merge writer/topic", "writer/topic")


@proof("scope/no-self-approval", "a merge from before the rule's start date is left in history", expect="pass")
def _(world):
    _agent_branch(world, APPROVAL + '    since = "2026-06-01"\n')
    _git_as(world, "writer@agents.invalid", "merge", "-q", "--no-ff", "-m", "merge writer/topic", "writer/topic")


@proof("scope/no-self-approval", "with no main line the rule cannot decide", expect="refuse", contains="no main")
def _(world):
    world.manifest(APPROVAL)


# -- scope/rules-current ------------------------------------------------------------------------


def _runs(ctx: Context) -> list[dict[str, Any]]:
    """Every run receipt that names its role. One that cannot be read is a refusal, never a skip."""
    found = receipts.read_all(ctx.root, "run")
    fix = "restore the receipt from git; a receipt is written by a tool, never by hand"
    kept = {path.relative_to(ctx.root).as_posix() for base in (receipts.LOCAL, receipts.COMMITTED)
            for path in (ctx.root / base / "run").glob("*.json")}
    for name in sorted(kept - {receipt["_path"] for receipt in found}):
        ctx.refuse("this run receipt cannot be read", where=name, fix=fix)
    named = [receipt for receipt in found if isinstance(receipt.get("role"), str) and receipt["role"].strip()]
    for receipt in found:
        if receipt not in named:
            ctx.refuse("this run receipt does not name the role that ran", where=receipt["_path"], fix=fix)
    return named


@rule(
    "scope/rules-current",
    "A run records the hash of the rules it read, and a run on a stale copy is refused.",
    params=(RULE_FILES,),
    requires=("rule_files",),
    learned="An agent kept working from an old copy of the rules after they had been tightened.",
)
def rules_current(ctx: Context) -> None:
    files = sorted({name for pattern in ctx.param("rule_files") for name in ctx.files(pattern)})
    if not files:
        ctx.refuse("no file matches `rule_files`, so there are no rules to hash", where="themis.toml",
                   fix="correct `rule_files` for this rule, or restore the rule files")
        return
    current = rules_hash(ctx.root, files)
    newest: dict[str, dict[str, Any]] = {}
    for receipt in sorted(_runs(ctx), key=lambda receipt: (str(receipt.get("at", "")), receipt["_path"])):
        newest[receipt["role"]] = receipt  # sorted by time, so the last one kept is the newest
    for role, receipt in sorted(newest.items()):
        ctx.inspect()
        recorded = receipt.get("rules_hash")
        if not isinstance(recorded, str) or not recorded.strip():
            ctx.breach(f"the newest run of the role {role} did not record the hash of the rules it read",
                       where=receipt["_path"], fix="the harness records `rules_hash` when a run starts; run again")
        elif recorded.strip().lower() != current:
            ctx.refuse(f"the newest run of the role {role} read a stale copy of the rules", where=receipt["_path"],
                       fix="repeat the run on the current rules: read the rule files again, then run")


CURRENT = """
    [rules."scope/rules-current"]
    rule_files = ["AGENTS.md", "docs/rules/*.md"]
"""
RULE_FILES_HELD = ("AGENTS.md", "docs/rules/style.md")


def _rules(world) -> None:
    world.manifest(CURRENT)
    world.write("AGENTS.md", "log before doing\n")
    world.write("docs/rules/style.md", "write for a newcomer\n")


def _run(world, name: str, role: str = "writer", at: str = "2026-01-01T10:00:00+00:00", **fields: Any) -> None:
    """A run receipt that holds the hash of the rule files as they are when this is called."""
    data = {"kind": "run", "role": role, "at": at, "rules_hash": rules_hash(world.root, RULE_FILES_HELD), **fields}
    held = {key: value for key, value in data.items() if value is not None}
    world.write(f"receipts/run/{name}.json", json.dumps(held))


@proof("scope/rules-current", "a run on the rules as they are now", expect="pass")
def _(world):
    _rules(world)
    _run(world, "r1")


@proof("scope/rules-current", "an old run on old rules, then a newer run on the current ones", expect="pass")
def _(world):
    _rules(world)
    _run(world, "r1")
    world.write("AGENTS.md", "log before doing; seal before results\n")
    _run(world, "r2", at="2026-01-02T10:00:00+00:00")


@proof("scope/rules-current", "the rules were tightened after the newest run", expect="refuse",
       contains="the newest run of the role writer read a stale copy of the rules")
def _(world):
    _rules(world)
    _run(world, "r1")
    world.write("AGENTS.md", "log before doing; seal before results\n")


@proof("scope/rules-current", "a rule file was renamed after the newest run", expect="refuse", contains="a stale copy")
def _(world):
    _rules(world)
    _run(world, "r1")
    world.move("docs/rules/style.md", "docs/rules/tone.md")


@proof("scope/rules-current", "one role is current and another is not", expect="refuse",
       contains="the newest run of the role editor read a stale copy")
def _(world):
    _rules(world)
    _run(world, "r1", role="editor")
    world.write("AGENTS.md", "log before doing; seal before results\n")
    _run(world, "r2", role="writer", at="2026-01-02T10:00:00+00:00")


@proof("scope/rules-current", "a run that recorded no hash", expect="fail", contains="did not record the hash")
def _(world):
    _rules(world)
    _run(world, "r1", rules_hash=None)


@proof("scope/rules-current", "no file matches the rule files", expect="refuse", contains="no file matches")
def _(world):
    world.manifest(CURRENT)
    world.write("receipts/run/r1.json", json.dumps({"kind": "run", "role": "writer", "rules_hash": "0" * 64}))


@proof("scope/rules-current", "a run receipt that cannot be read", expect="refuse", contains="cannot be read")
def _(world):
    _rules(world)
    _run(world, "r1")
    world.write("receipts/run/r2.json", '{"role": "writer", ')


# -- scope/capabilities -------------------------------------------------------------------------


@rule(
    "scope/capabilities",
    "Tools denied to agents stay denied in the host's settings.",
    params=(DENIED, SETTINGS),
    requires=("denied",),
    learned="A tool that had been taken away from the agents was quietly allowed again in a settings file.",
)
def capabilities(ctx: Context) -> None:
    settings = ctx.param("settings")
    if not ctx.exists(settings):
        ctx.refuse("the host's settings file is missing, so nothing shows what is denied", where=settings,
                   fix="run `themis hooks install`, or restore the file from git")
        return
    try:
        held = json.loads(ctx.read(settings) or "")
    except json.JSONDecodeError:
        held = None
    permissions = held.get("permissions", {}) if isinstance(held, dict) else None
    deny = permissions.get("deny", []) if isinstance(permissions, dict) else None
    if not isinstance(deny, list):
        ctx.refuse("the host's settings file is not readable JSON with a permissions.deny list", where=settings,
                   fix="correct the file, or restore it from git")
        return
    for tool in ctx.param("denied"):
        ctx.inspect()
        if tool not in deny:
            ctx.breach(f"the tool {tool} is not denied in the host's settings", where=settings,
                       fix=f"the owner adds {json.dumps(tool)} to permissions.deny in {settings}")


CAPABILITIES = """
    [rules."scope/capabilities"]
    denied = ["Publish", "Shell(git push:*)"]
"""


def _settings(world, deny: list[str] | None, path: str = ".claude/settings.json", setup: str = CAPABILITIES) -> None:
    world.manifest(setup)
    permissions = {"allow": ["Read"]} if deny is None else {"allow": ["Read"], "deny": deny}
    world.write(path, json.dumps({"permissions": permissions}))


@proof("scope/capabilities", "every denied tool is in the deny list", expect="pass")
def _(world):
    _settings(world, ["Shell(git push:*)", "Publish", "Delete"])


@proof("scope/capabilities", "a settings file the project keeps elsewhere", expect="pass")
def _(world):
    _settings(world, ["Publish", "Shell(git push:*)"], path="host/settings.json",
              setup=CAPABILITIES + '    settings = "host/settings.json"\n')


@proof("scope/capabilities", "a denied tool was taken out of the deny list", expect="fail",
       contains="the tool Publish is not denied")
def _(world):
    _settings(world, ["Shell(git push:*)"])


@proof("scope/capabilities", "a looser entry is not the denied one", expect="fail",
       contains="the tool Shell(git push:*) is not denied")
def _(world):
    _settings(world, ["Publish", "Shell(git push --force:*)"])


@proof("scope/capabilities", "settings with no deny list at all", expect="fail", contains="is not denied")
def _(world):
    _settings(world, None)


@proof("scope/capabilities", "the settings file is missing", expect="refuse", contains="settings file is missing")
def _(world):
    world.manifest(CAPABILITIES)


@proof("scope/capabilities", "settings that are not JSON", expect="refuse", contains="is not readable JSON")
def _(world):
    world.manifest(CAPABILITIES)
    world.write(".claude/settings.json", "{ permissions: deny everything }\n")
