"""Gate: order — things happen in the declared order.

Order is read from git history, on the main line: the first-parent chain of the main branch, one
commit for each merge. A file "arrives" at the main-line commit that first brought it.
"""

from __future__ import annotations

from themis import records, work
from themis.rule import Context, Param, proof, rule
from themis.schema import ANY, Either, Required

records.register("ledger", {"work": Required(str), "*": ANY}, "ledger/*.toml")
records.register("amendment", {
    "seal": Required(str), "sha256": Required(str), "reason": Required(str), "loosens": bool, "*": ANY,
}, "**/amendments/*.toml")

WORK = Param("work", Either(str, [str]), None, "larger",
             "the folders that each hold one unit of work: one pattern, such as work/*, or a list of them")
SEAL = Param("seal", [str], None, None, "the sealed plan's file, inside a unit")
RESULTS = Param("results", [str], None, None, "the result files, inside a unit")
MAIN = Param("main", str, None, None, "the main line's name, when it is not main")


def _main(ctx: Context) -> str | None:
    return ctx.git.main_ref(ctx.param("main") or ctx.manifest.project.get("main"))


def _units(ctx: Context) -> dict[str, list[str]]:
    try:
        return work.units(ctx.all_files, ctx.param("work"))
    except ValueError as error:
        ctx.refuse(str(error), where="themis.toml")
        return {}


# -- order/sealed-first -------------------------------------------------------------------------


@rule(
    "order/sealed-first",
    "A seal reaches the main line in an earlier merge than any result that rests on it.",
    params=(WORK, SEAL, RESULTS, MAIN),
    requires=("work", "seal", "results"),
    learned="A merge joined a plan to its results, so nobody could show which came first.",
)
def sealed_first(ctx: Context) -> None:
    main = _main(ctx)
    if main is None:
        ctx.refuse("there is no main line, so no order can be read", fix="commit to main, or set project.main")
        return
    arrivals, line = ctx.git.arrivals(main), ctx.git.main_line(main)
    for unit, files in sorted(_units(ctx).items()):
        results = work.inside(unit, files, ctx.param("results"))
        seals = work.inside(unit, files, ctx.param("seal"))
        if not results or not seals:
            continue  # nothing to order: no result yet, or a unit that was never sealed
        if ctx.predates(seals):
            continue  # sealed before the rule's start date
        sealed_at = min((arrivals[name] for name in seals if name in arrivals), default=None)
        ctx.inspect()
        if sealed_at is None:
            ctx.breach("this unit holds results, but its seal is not on the main line yet", where=unit,
                       fix="merge the seal in a pull request of its own, then run again on a fresh branch")
            continue
        early = [name for name in results if name in arrivals and arrivals[name] <= sealed_at]
        if early:
            ctx.breach("a result reached the main line in the same merge as its seal, or before it", where=early[0],
                       fix="a seal and its results are two merges, seal first; run again on a fresh branch")
            continue
        merge = line[sealed_at]
        for name in results:
            added = ctx.git.added_by(name)
            if added and not ctx.git.is_ancestor(merge, added):
                ctx.breach("this result was made on a branch that did not hold the merge of its seal", where=name,
                           fix="cut the results branch from main after the seal merges, and run again")
                break


SETUP = """
    [rules."order/sealed-first"]
    work = "work/*"
    seal = ["PLAN.md"]
    results = ["results/**"]
"""
PLAN = {"work/a/PLAN.md": "the plan\n"}
RESULT = {"work/a/results/out.csv": "1\n"}


def _start(world, setup: str = SETUP) -> None:
    world.manifest(setup)
    world.commit("start")


@proof("order/sealed-first", "two merges, the seal first", expect="pass")
def _(world):
    _start(world)
    world.pull_request("seal", PLAN)
    world.pull_request("results", RESULT)


@proof("order/sealed-first", "results on a branch, the seal already merged", expect="pass")
def _(world):
    _start(world)
    world.pull_request("seal", PLAN)
    world.branch("results")
    world.write("work/a/results/out.csv")
    world.commit("results")


@proof("order/sealed-first", "one merge brings the seal and its results", expect="fail",
       contains="in the same merge as its seal")
def _(world):
    _start(world)
    world.pull_request("both", PLAN, RESULT)


@proof("order/sealed-first", "results merged before the seal", expect="fail", contains="in the same merge as its seal")
def _(world):
    _start(world)
    world.pull_request("results", RESULT)
    world.pull_request("seal", PLAN)


@proof("order/sealed-first", "a seal and its results on one unmerged branch", expect="fail",
       contains="its seal is not on the main line yet")
def _(world):
    _start(world)
    world.branch("both")
    world.write("work/a/PLAN.md")
    world.commit("seal")
    world.write("work/a/results/out.csv")
    world.commit("results")


@proof("order/sealed-first", "results stacked on the open seal branch", expect="fail",
       contains="did not hold the merge of its seal")
def _(world):
    _start(world)
    world.branch("seal")
    world.write("work/a/PLAN.md")
    world.commit("seal")
    world.branch("results")
    world.write("work/a/results/out.csv")
    world.commit("results")
    world.checkout("main")
    world.merge("seal")
    world.merge("results")


@proof("order/sealed-first", "a unit that was never sealed is left alone", expect="refuse",
       contains="nothing was inspected")
def _(world):
    _start(world)
    world.pull_request("results", RESULT)


@proof("order/sealed-first", "an old unit, from before the rule's start date, is exempt", expect="refuse",
       contains="nothing was inspected")
def _(world):
    _start(world, SETUP + '    since = "2027-01-01"\n')
    world.pull_request("both", PLAN, RESULT)


@proof("order/sealed-first", "a unit sealed after the start date is still held to it", expect="fail",
       contains="in the same merge as its seal")
def _(world):
    _start(world, SETUP + '    since = "2026-06-01"\n')
    world.pull_request("old", {"work/old/PLAN.md": "the plan\n", "work/old/results/out.csv": "1\n"})
    world.on("2026-07-01")
    world.pull_request("both", PLAN, RESULT)


# -- order/logged-first -------------------------------------------------------------------------


@rule(
    "order/logged-first",
    "A unit of work has its ledger record before its first result.",
    params=(WORK, RESULTS, MAIN),
    requires=("work", "results"),
    learned="A sweep ran unlogged and had to be recorded after its results were known.",
)
def logged_first(ctx: Context) -> None:
    main = _main(ctx)
    if main is None:
        ctx.refuse("there is no main line, so no order can be read", fix="commit to main, or set project.main")
        return
    arrivals = ctx.git.arrivals(main)
    units = _units(ctx)
    logged: dict[str | None, list[str]] = {}
    for record in ctx.records("ledger"):
        logged.setdefault(work.named(units, str(record.get("work"))), []).append(record.path)
    for unit, files in sorted(ctx.bound(units, ctx.param("results")).items()):  # results first made before since
        results = work.inside(unit, files, ctx.param("results"))
        if not results:
            continue
        ctx.inspect()
        rows = logged.get(unit)
        if not rows:
            ctx.breach("this unit holds results and has no ledger record", where=unit,
                       fix="a unit is logged before it runs; add its ledger record and say why it is late")
            continue
        logged_at = min((arrivals[name] for name in rows if name in arrivals), default=None)
        first_result = min((arrivals[name] for name in results if name in arrivals), default=None)
        if first_result is not None and (logged_at is None or logged_at >= first_result):
            ctx.breach("the ledger record reached the main line with the first result, or after it", where=rows[0],
                       fix="log a unit in an earlier merge than its results")


LEDGER_SETUP = """
    [rules."order/logged-first"]
    work = "work/*"
    results = ["results/**"]
"""
ROW = {"ledger/a.toml": 'work = "work/a"\nquestion = "does it hold?"\n'}


@proof("order/logged-first", "logged in an earlier merge than the result", expect="pass")
def _(world):
    _start(world, LEDGER_SETUP)
    world.pull_request("log", ROW)
    world.pull_request("results", RESULT)


@proof("order/logged-first", "a result with no ledger record", expect="fail", contains="has no ledger record")
def _(world):
    _start(world, LEDGER_SETUP)
    world.pull_request("results", RESULT)


@proof("order/logged-first", "units that share a folder name, each logged by its path", expect="pass")
def _(world):
    _start(world, LEDGER_SETUP.replace('"work/*"', '"work/*/*"'))
    world.pull_request("log", {"ledger/a.toml": 'work = "work/a/tune"\n', "ledger/b.toml": 'work = "work/b/tune"\n'})
    world.pull_request("results", {"work/a/tune/results/out.csv": "1\n", "work/b/tune/results/out.csv": "1\n"})


@proof("order/logged-first", "a folder name two units share logs neither of them", expect="fail",
       contains="has no ledger record")
def _(world):
    _start(world, LEDGER_SETUP.replace('"work/*"', '"work/*/*"'))
    world.pull_request("log", {"ledger/tune.toml": 'work = "tune"\n'})
    world.pull_request("results", {"work/a/tune/results/out.csv": "1\n", "work/b/tune/results/out.csv": "1\n"})


@proof("order/logged-first", "logged in the same merge as the result", expect="fail", contains="with the first result")
def _(world):
    _start(world, LEDGER_SETUP)
    world.pull_request("both", ROW, RESULT)


@proof("order/logged-first", "logged after the result", expect="fail", contains="with the first result")
def _(world):
    _start(world, LEDGER_SETUP)
    world.pull_request("results", RESULT)
    world.pull_request("log", ROW)


@proof("order/logged-first", "a unit begun before the start date is exempt; a later one is held", expect="pass")
def _(world):
    _start(world, LEDGER_SETUP + '    since = "2026-06-01"\n')
    world.pull_request("old", {"work/old/results/out.csv": "1\n"})  # never logged: it predates the rule
    world.on("2026-07-01")
    world.pull_request("log", ROW)
    world.pull_request("results", RESULT)


@proof("order/logged-first", "a folder begun before the start date, with results first made after it, is held",
       expect="fail", contains="has no ledger record")
def _(world):
    _start(world, LEDGER_SETUP + '    since = "2026-06-01"\n')
    world.pull_request("plan", {"work/a/PLAN.md": "the plan, written before the rule\n"})
    world.on("2026-07-01")
    world.pull_request("results", RESULT)


@proof("order/logged-first", "a unit begun after the start date is still held to it", expect="fail",
       contains="has no ledger record")
def _(world):
    _start(world, LEDGER_SETUP + '    since = "2026-06-01"\n')
    world.pull_request("old", {"work/old/results/out.csv": "1\n"})
    world.on("2026-07-01")
    world.pull_request("results", RESULT)


# -- order/unchanged ----------------------------------------------------------------------------


@rule(
    "order/unchanged",
    "A sealed file changes only through an amendment record.",
    params=(WORK, SEAL, MAIN),
    requires=("work", "seal"),
    learned="A sealed plan was edited after its results were in.",
)
def unchanged(ctx: Context) -> None:
    main = _main(ctx)
    if main is None:
        ctx.refuse("there is no main line, so no seal can be compared", fix="commit to main, or set project.main")
        return
    arrivals, line = ctx.git.arrivals(main), ctx.git.main_line(main)
    amended = {(str(record.get("seal")), str(record.get("sha256"))) for record in ctx.records("amendment")}
    for unit, files in sorted(_units(ctx).items()):
        seals = work.inside(unit, files, ctx.param("seal"))
        if ctx.predates(seals):
            continue  # sealed before the rule's start date
        for name in seals:
            if name not in arrivals:
                continue  # not sealed yet: a seal is the file's arrival on the main line
            ctx.inspect()
            sealed, now = ctx.git.show(line[arrivals[name]], name), ctx.read(name)
            if sealed is None or now is None:
                ctx.refuse("the sealed file cannot be read", where=name)
            elif sealed != now and (name, work.text_hash(now)) not in amended:
                ctx.breach("a sealed file changed with no amendment record for this version", where=name,
                           fix="add an amendment record that names the file, its new sha256 and the reason")


SEAL_SETUP = """
    [rules."order/unchanged"]
    work = "work/*"
    seal = ["PLAN.md"]
"""


@proof("order/unchanged", "a seal left as it was merged", expect="pass")
def _(world):
    _start(world, SEAL_SETUP)
    world.pull_request("seal", PLAN)


@proof("order/unchanged", "a seal merged among commits that add nothing is read at its own merge", expect="pass")
def _(world):
    _start(world, SEAL_SETUP)
    world.write("notes.md", "an edit\n")
    world.commit("start the notes")
    world.write("notes.md", "an edit that adds nothing\n")
    world.commit("edit the notes")
    world.pull_request("seal", PLAN)
    world.pull_request("notes", {"notes.md": "another edit\n"})


@proof("order/unchanged", "a seal from before the start date may change, beside a later one kept", expect="pass")
def _(world):
    _start(world, SEAL_SETUP + '    since = "2026-06-01"\n')
    world.pull_request("old", {"work/old/PLAN.md": "the old plan\n"})
    world.on("2026-07-01")
    world.pull_request("seal", PLAN)
    world.write("work/old/PLAN.md", "the old plan, edited\n")


@proof("order/unchanged", "a seal from after the start date is still held to it", expect="fail",
       contains="changed with no amendment record")
def _(world):
    _start(world, SEAL_SETUP + '    since = "2026-06-01"\n')
    world.pull_request("old", {"work/old/PLAN.md": "the old plan\n"})
    world.on("2026-07-01")
    world.pull_request("seal", PLAN)
    world.write("work/a/PLAN.md", "the plan, edited\n")


@proof("order/unchanged", "a seal from before the start date is exempt", expect="refuse",
       contains="nothing was inspected")
def _(world):
    _start(world, SEAL_SETUP + '    since = "2026-06-01"\n')
    world.pull_request("old", {"work/old/PLAN.md": "the old plan\n"})
    world.write("work/old/PLAN.md", "the old plan, edited\n")


@proof("order/unchanged", "a seal edited afterwards", expect="fail", contains="changed with no amendment record")
def _(world):
    _start(world, SEAL_SETUP)
    world.pull_request("seal", PLAN)
    world.write("work/a/PLAN.md", "the plan, with a looser bar\n")


@proof("order/unchanged", "a seal edited with an amendment for that exact version", expect="pass")
def _(world):
    _start(world, SEAL_SETUP)
    world.pull_request("seal", PLAN)
    world.write("work/a/PLAN.md", "the plan, with a tighter bar\n")
    digest = work.text_hash("the plan, with a tighter bar\n")
    world.write("work/a/amendments/1.toml", f'seal = "work/a/PLAN.md"\nsha256 = "{digest}"\nreason = "tightened"\n')


@proof("order/unchanged", "an amendment for another version does not cover a later edit", expect="fail",
       contains="changed with no amendment record")
def _(world):
    _start(world, SEAL_SETUP)
    world.pull_request("seal", PLAN)
    world.write("work/a/amendments/1.toml", f'seal = "work/a/PLAN.md"\nsha256 = "{"0" * 64}"\nreason = "tightened"\n')
    world.write("work/a/PLAN.md", "the plan, edited again\n")
