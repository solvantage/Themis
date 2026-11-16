"""Gate: suite — "tests pass" is a receipt, not a sentence.

After every test run the test plugin writes a receipt: which exact files the run was on, the
command it was given, and how it ended. The rules here read that receipt. A run on other files, a
run of a few chosen tests and a run with a failure all leave a receipt, and none of them says
"the suite passes here".

`is_selection` tells a full run from a selection by the arguments the runner was given.
"""

from __future__ import annotations

import datetime as dt
import re
import shlex
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from themis import paths, receipts
from themis.rule import Context, Param, proof, rule

if TYPE_CHECKING:
    from themis.proofs import World

GUARDED = Param("guarded", [str], None, "larger",
                "the source files that each need an attack file, as patterns such as src/guards/*.py")
ATTACK = Param("attack", str, "tests/test_{name}_negative.py", None,
               "where a module's attack file lives; {name} is the module file's name without its extension")
MARKER = Param("marker", str, "PLANTS", None, "text an attack file must hold to show that it plants faults")

#: Arguments that narrow a test run by themselves.
SELECTING_FLAGS = frozenset(
    "--lf --last-failed --ff --failed-first --collect-only --co --sw --stepwise --sw-skip --stepwise-skip".split()
)
#: Options that narrow a test run and take a value.
SELECTING_OPTIONS = frozenset({"--deselect", "--ignore", "--ignore-glob"})
#: Options that take a value and narrow nothing. Their value must not be read as a test path.
VALUE_OPTIONS = frozenset("""
    --assert --basetemp --capture --color --confcutdir --cov --cov-config --cov-fail-under --cov-report
    --dist --durations --durations-min --import-mode --junit-prefix --junit-xml --junitxml --log-cli-level
    --log-file --log-file-level --log-level --maxfail --maxprocesses --numprocesses --override-ini
    --pythonwarnings --rootdir --show-capture --tb --timeout --tx --verbosity
""".split())
#: Short options that take a value. Of these, only -k and -m narrow a run.
SHORT_VALUE_OPTIONS = "kmcnoprW"

NO_RUN = "no test run is recorded for this exact tree"
COUNTS = ("exit_status", "passed", "failed", "errors")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def narrowing(args: Sequence[str]) -> list[str]:
    """The arguments that make a test run less than the full suite: each filter, test path and node id."""
    found: list[str] = []
    rest = list(args)

    def value() -> str:
        """The next argument, when it is an option's value and not another option."""
        return rest.pop(0) if rest and not rest[0].startswith("-") else ""

    while rest:
        arg = rest.pop(0)
        if arg == "--":  # everything after this is a test path
            found += [_path(name) for name in rest]
            break
        if arg.startswith("--"):
            name, joined, given = arg.partition("=")
            if not joined and name in SELECTING_OPTIONS | VALUE_OPTIONS:
                given = value()
            if name in SELECTING_FLAGS | SELECTING_OPTIONS:
                found.append(f"{name} {given}".strip())
        elif arg.startswith("-") and len(arg) > 1:  # short options, which may be written joined: -qk fast
            for index, letter in enumerate(arg[1:], start=1):
                if letter in SHORT_VALUE_OPTIONS:
                    given = arg[index + 1:].lstrip("=") or value()
                    if letter in "km":
                        found.append(f"-{letter} {given}".strip())
                    break
        else:
            found.append(_path(arg))
    return found


def is_selection(args: Sequence[str]) -> bool:
    """True when these arguments make the test runner run only some of the tests."""
    return bool(narrowing(args))


def suite_arguments(command: str) -> list[str]:
    """The arguments a suite command gives the test runner. Empty when the command names no runner."""
    try:
        words = shlex.split(command)
    except ValueError:
        return []
    for index, word in enumerate(words):
        if PurePosixPath(word).name in ("pytest", "py.test"):
            return words[index + 1:]
    return []


def _path(arg: str) -> str:
    return arg.removeprefix("./").rstrip("/") or arg


def _words(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _over(until: str) -> bool:
    """True when an end condition is a date and that date has passed. A condition in words never is."""
    try:
        return bool(_DATE.fullmatch(until)) and dt.date.fromisoformat(until) < dt.date.today()
    except ValueError:
        return False


def _selected(receipt: dict[str, Any], command: str | None) -> list[str] | None:
    """What made this run narrower than the suite command. None when the receipt does not say what ran."""
    ran = receipt.get("command")
    if not _words(ran) or not ran:
        return None
    declared = narrowing(suite_arguments(command or ""))
    return [arg for arg in narrowing(ran[1:]) if arg not in declared]


def _tree(ctx: Context) -> str | None:
    """The fingerprint of the files as they are now. Refuses when there is nothing to tie a run to."""
    tree = receipts.tree_fingerprint(ctx.root)
    if tree is None:
        ctx.refuse("this folder is not a git repository with a commit, so no test run can be tied to it",
                   fix="commit the work, then run the suite")
    return tree


# -- suite/receipt-for-tree ---------------------------------------------------------------------


@rule(
    "suite/receipt-for-tree",
    "The exact tree holds a receipt of a full, passing test run.",
    learned="Work was called tested after a few chosen tests had run, on files that changed afterwards.",
)
def receipt_for_tree(ctx: Context) -> None:
    command = ctx.manifest.suite.get("command")
    if not command:
        ctx.not_configured("set the command that runs the full suite: command under [suite]")
    tree = _tree(ctx)
    if tree is None:
        return
    ctx.inspect()
    receipt = receipts.suite_for_tree(ctx.root, tree)
    if receipt is None:
        ctx.breach(NO_RUN, fix=f"run the full suite, `{command}`; a change to any file needs a new run")
        return
    where, extra = receipt["_path"], _selected(receipt, command)
    if extra is None or not all(type(receipt.get(key)) is int for key in COUNTS):
        ctx.refuse("the suite receipt is incomplete, so it does not show how the run ended", where=where,
                   fix="run the full suite again; a receipt is written by the test run, never by hand")
        return
    exit_status, passed, failed, errors = (receipt[key] for key in COUNTS)
    if failed or errors or exit_status:
        ctx.breach(f"the test run on this tree did not pass: failed {failed}, errors {errors}, "
                   f"exit status {exit_status}", where=where, fix="fix what failed, then run the full suite again")
    elif not passed:
        ctx.breach("the test run on this tree passed no test, so it shows nothing", where=where,
                   fix="run the full suite; a run where every test is skipped or left out proves nothing")
    if extra:
        hint = "" if all(arg.startswith("-") for arg in extra) else "; write an option's value as --option=value"
        ctx.breach(f"the test run on this tree was a selection, not the full suite: {', '.join(extra)}",
                   where=where, fix=f"run the full suite, `{command}`{hint}")
    elif receipt.get("deselected"):
        # A selection set in the config file or the environment leaves no trace on the command line.
        ctx.breach(f"the test run on this tree left {receipt['deselected']} test(s) out", where=where,
                   fix=f"run the full suite, `{command}`, with nothing deselected")


SUITE = """
    [suite]
    command = "pytest -q"
"""
GREEN = {
    "at": "2026-01-01T00:00:00+00:00", "command": ["pytest", "-q"], "exit_status": 0,
    "passed": 12, "failed": 0, "errors": 0, "skipped": 0, "skipped_tests": [],
}
A_TEST = "def test_one():\n    assert True\n"


def _run(world: World, setup: str = SUITE, **outcome: Any) -> None:
    """A committed project, and the receipt of one test run on exactly those files."""
    world.manifest(setup)
    world.write("tests/test_one.py", A_TEST)
    world.commit("start")
    tree = receipts.tree_fingerprint(world.root)
    receipts.write(world.root, "suite", str(tree), {**GREEN, "tree": tree, **outcome})


@proof("suite/receipt-for-tree", "a full, passing run on these exact files", expect="pass")
def _(world: World) -> None:
    _run(world)


@proof("suite/receipt-for-tree", "tests left out through the config file, not the command line", expect="fail",
       contains="left 3 test(s) out")
def _(world: World) -> None:
    _run(world, deselected=3)


@proof("suite/receipt-for-tree", "a quick run of one test after the full run does not replace it", expect="pass")
def _(world: World) -> None:
    _run(world)
    tree = receipts.tree_fingerprint(world.root)
    later = {**GREEN, "tree": tree, "at": "2026-01-02T00:00:00+00:00", "passed": 1,
             "command": ["pytest", "-q", "tests/test_one.py"], "narrowed": ["tests/test_one.py"]}
    receipts.write(world.root, "suite", f"{tree}-later", later)


@proof("suite/receipt-for-tree", "options that take a value are not read as test paths", expect="pass")
def _(world: World) -> None:
    _run(world, command=["pytest", "-q", "-n", "8", "--dist", "worksteal", "-p", "no:cacheprovider", "-o",
                         "key=value", "--tb", "short", "-W", "error", "-rA", "--junitxml=out.xml"])


@proof("suite/receipt-for-tree", "a suite command that names its test folder is still the full suite",
       expect="pass")
def _(world: World) -> None:
    _run(world, SUITE.replace("pytest -q", "python -m pytest tests -q"), command=["pytest", "tests/", "-q"])


@proof("suite/receipt-for-tree", "no test run at all", expect="fail", contains=NO_RUN)
def _(world: World) -> None:
    world.manifest(SUITE)
    world.commit("start")


@proof("suite/receipt-for-tree", "a file edited after the run", expect="fail", contains=NO_RUN)
def _(world: World) -> None:
    _run(world)
    world.write("tests/test_one.py", "def test_one():\n    assert False\n")


def _ran(*args: str) -> dict[str, Any]:
    return {"command": ["pytest", *args]}


#: Runs that left a receipt on this exact tree and still do not count: what the receipt holds, and why.
RUNS_THAT_DO_NOT_COUNT = (
    ("a run with a failing test", {"passed": 11, "failed": 1, "exit_status": 1}, "did not pass: failed 1"),
    ("a run with an error and no failure", {"errors": 1, "exit_status": 1}, "errors 1"),
    ("a run that was cut short", {"exit_status": 2}, "exit status 2"),
    ("a run in which every test was skipped", {"passed": 0, "skipped": 12}, "passed no test"),
    ("a run filtered by keyword", _ran("-q", "-k", "fast"), "not the full suite: -k fast"),
    ("a keyword filter joined to other short options", _ran("-qkfast"), "not the full suite: -k fast"),
    ("a run filtered by marker", _ran("-m", "not slow"), "not the full suite: -m not slow"),
    ("a run of only the tests that failed last time", _ran("--lf"), "not the full suite: --lf"),
    ("the same, spelled out", _ran("--last-failed"), "not the full suite: --last-failed"),
    ("a run that puts the failed tests first", _ran("--ff"), "not the full suite: --ff"),
    ("a run with one test left out", _ran("--deselect", "tests/test_one.py::test_one"), "--deselect tests/test_one.py"),
    ("one test left out, with an equals sign", _ran("--deselect=tests/test_one.py::test_one"), "--deselect tests"),
    ("a run that only lists the tests", _ran("--collect-only"), "not the full suite: --collect-only"),
    ("a run of one test file", _ran("-q", "tests/test_one.py"), "not the full suite: tests/test_one.py"),
    ("a run of one test by its id, among options with values",
     _ran("-n", "8", "tests/test_one.py::test_one", "--tb", "short"),
     "not the full suite: tests/test_one.py::test_one"),
)

for _name, _outcome, _shown in RUNS_THAT_DO_NOT_COUNT:
    @proof("suite/receipt-for-tree", _name, expect="fail", contains=_shown)
    def _(world: World, outcome: dict[str, Any] = _outcome) -> None:
        _run(world, **outcome)


@proof("suite/receipt-for-tree", "a narrower run than the suite command names", expect="fail",
       contains="not the full suite: tests/test_one.py")
def _(world: World) -> None:
    _run(world, SUITE.replace("pytest -q", "pytest tests -q"), command=["pytest", "tests/test_one.py", "-q"])


@proof("suite/receipt-for-tree", "a folder that is not a repository", expect="refuse", contains="not a git repository")
def _(world: World) -> None:
    world.manifest(SUITE)


@proof("suite/receipt-for-tree", "a receipt that does not say how the run ended", expect="refuse",
       contains="receipt is incomplete")
def _(world: World) -> None:
    _run(world, exit_status=None)


# -- suite/declared-skips -----------------------------------------------------------------------


@rule(
    "suite/declared-skips",
    "Every skipped test is declared with a reason and an end condition.",
    learned="A test was skipped to get a green run, and stayed skipped long after anyone knew why.",
)
def declared_skips(ctx: Context) -> None:
    tree = _tree(ctx)
    if tree is None:
        return
    receipt = receipts.suite_for_tree(ctx.root, tree)
    if receipt is None:
        ctx.refuse(f"{NO_RUN}, so its skipped tests are not known", fix="run the suite, then check again")
        return
    skipped, extra = receipt.get("skipped_tests"), _selected(receipt, ctx.manifest.suite.get("command"))
    if extra is None or not _words(skipped) or receipt.get("skipped") != len(skipped):
        ctx.refuse("the suite receipt does not list the tests it skipped", where=receipt["_path"],
                   fix="run the suite again; a receipt is written by the test run, never by hand")
        return
    ctx.inspect()
    declared = ctx.manifest.suite.get("skips", [])
    for skip in declared:
        ctx.inspect()
        test, until = skip["test"], skip["until"].strip()
        if not skip["reason"].strip() or not until:
            ctx.breach(f"the declared skip of {test} has no reason or no end condition", where="themis.toml",
                       fix="say why the test is skipped, and the date or the event that ends the skip")
        elif _over(until):
            ctx.breach(f"the end condition of the declared skip of {test} has passed: {until}",
                       where="themis.toml", fix="make the test run again, or set a new end date and say why")
    for test in skipped:
        ctx.inspect()
        if not any(test == skip["test"] or paths.matches(test, skip["test"]) for skip in declared):
            ctx.breach(f"the test {test} is skipped but not declared", where=test.split("::")[0],
                       fix="make the test run, or declare it under [[suite.skips]] with test, reason and until")
    if extra:
        ctx.refuse(f"the test run on this tree was a selection, so the tests the suite skips are not all known: "
                   f"{', '.join(extra)}", where=receipt["_path"],
                   fix="run the full suite, then check again; if this was the full suite, set command under [suite]")


SLOW = "tests/test_one.py::test_slow"


def _skips(until: str, test: str = SLOW, reason: str = "it needs a data feed with no test account") -> str:
    return SUITE + f"""
    [[suite.skips]]
    test = "{test}"
    reason = "{reason}"
    until = "{until}"
"""


@proof("suite/declared-skips", "a run that skipped nothing", expect="pass")
def _(world: World) -> None:
    _run(world)


@proof("suite/declared-skips", "a skipped test, declared with an end condition in words", expect="pass")
def _(world: World) -> None:
    _run(world, _skips("the data feed has a test account"), skipped=1, skipped_tests=[SLOW])


@proof("suite/declared-skips", "a skipped test, declared by a pattern, its end date still ahead", expect="pass")
def _(world: World) -> None:
    _run(world, _skips("2999-01-01", test="tests/test_one.py::*"), skipped=1, skipped_tests=[SLOW])


@proof("suite/declared-skips", "a skipped test nobody declared", expect="fail", contains="is skipped but not declared")
def _(world: World) -> None:
    _run(world, skipped=1, skipped_tests=[SLOW])


@proof("suite/declared-skips", "a declared skip of another test does not cover this one", expect="fail",
       contains="test_slow is skipped but not declared")
def _(world: World) -> None:
    _run(world, _skips("2999-01-01", test="tests/test_one.py::test_other"), skipped=1, skipped_tests=[SLOW])


@proof("suite/declared-skips", "a declared skip whose end date has passed", expect="fail",
       contains="has passed: 2020-01-01")
def _(world: World) -> None:
    _run(world, _skips("2020-01-01"), skipped=1, skipped_tests=[SLOW])


@proof("suite/declared-skips", "a declared skip with a blank reason", expect="fail", contains="has no reason")
def _(world: World) -> None:
    _run(world, _skips("2999-01-01", reason=" "), skipped=1, skipped_tests=[SLOW])


@proof("suite/declared-skips", "a run of chosen tests does not show what the suite skips", expect="refuse",
       contains="was a selection, so the tests the suite skips are not all known")
def _(world: World) -> None:
    _run(world, command=["pytest", "-q", "-k", "fast"])


@proof("suite/declared-skips", "no test run on this tree", expect="refuse", contains=NO_RUN)
def _(world: World) -> None:
    world.manifest(SUITE)
    world.commit("start")


@proof("suite/declared-skips", "a receipt that counts more skipped tests than it lists", expect="refuse",
       contains="does not list the tests it skipped")
def _(world: World) -> None:
    _run(world, skipped=2, skipped_tests=[SLOW])


# -- suite/attack-files -------------------------------------------------------------------------


@rule(
    "suite/attack-files",
    "Each guarded module has an attack file that plants faults in it.",
    params=(GUARDED, ATTACK, MARKER),
    requires=("guarded",),
    learned="A guard was tested only with honest input, so nothing showed that it could say no.",
)
def attack_files(ctx: Context) -> None:
    marker, attack = ctx.param("marker"), ctx.param("attack")
    if not marker.strip() or not attack.strip():
        ctx.not_configured("set attack and marker to text that is not empty")
    for pattern in ctx.param("guarded"):
        if not ctx.files(pattern):
            ctx.refuse(f"the guarded pattern {pattern} matches no file", where="themis.toml",
                       fix="correct the pattern; a module that moved must stay guarded")
    for module in sorted({name for pattern in ctx.param("guarded") for name in ctx.files(pattern)}):
        ctx.inspect()
        wanted = attack.replace("{name}", PurePosixPath(module).stem)
        found = ctx.files(wanted)
        if not found:
            ctx.breach(f"this guarded module has no attack file: {wanted} is missing", where=module,
                       fix="add it, with tests that plant a fault in the module and expect the fault to be caught")
        for name in found:
            text = ctx.read(name)
            if text is None:
                ctx.refuse("this attack file cannot be read as text", where=name, fix="save it as UTF-8 text")
            elif marker not in text:
                ctx.breach(f"this attack file does not hold the marker {marker}, so it shows no planted fault",
                           where=name, fix=f"list each planted fault under {marker}, with the check that catches it")


ATTACKS = """
    [rules."suite/attack-files"]
    guarded = ["src/guards/*.py"]
"""
MODULE = "def allowed(amount):\n    return amount <= 100\n"
PLANTED = 'PLANTS = {"the limit is removed": "test_limit_holds"}\n\n\ndef test_limit_holds():\n    assert True\n'


@proof("suite/attack-files", "a guarded module with its attack file, beside a module nobody guards", expect="pass")
def _(world: World) -> None:
    world.manifest(ATTACKS)
    world.write("src/guards/limit.py", MODULE)
    world.write("src/helpers/text.py", "def shout(text):\n    return text.upper()\n")
    world.write("tests/test_limit_negative.py", PLANTED)


@proof("suite/attack-files", "a project's own place and marker for attack files", expect="pass")
def _(world: World) -> None:
    world.manifest(ATTACKS + '    attack = "attacks/{name}.py"\n    marker = "FAULTS"\n')
    world.write("src/guards/limit.py", MODULE)
    world.write("attacks/limit.py", PLANTED.replace("PLANTS", "FAULTS"))


@proof("suite/attack-files", "an ordinary test file, or the attack file of the module beside it, does not count",
       expect="fail", contains="has no attack file: tests/test_rate_negative.py is missing")
def _(world: World) -> None:
    world.manifest(ATTACKS)
    world.write("src/guards/limit.py", MODULE)
    world.write("src/guards/rate.py", MODULE)
    world.write("tests/test_limit_negative.py", PLANTED)
    world.write("tests/test_rate.py", "def test_rate():\n    assert True\n")


@proof("suite/attack-files", "an attack file that plants nothing", expect="fail",
       contains="does not hold the marker PLANTS")
def _(world: World) -> None:
    world.manifest(ATTACKS)
    world.write("src/guards/limit.py", MODULE)
    world.write("tests/test_limit_negative.py", "def test_limit_holds():\n    assert True\n")


@proof("suite/attack-files", "a guarded pattern that matches no file", expect="refuse", contains="matches no file")
def _(world: World) -> None:
    world.manifest(ATTACKS)
    world.write("src/checks/limit.py", MODULE)
    world.write("tests/test_limit_negative.py", PLANTED)
