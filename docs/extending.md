# Extending Themis

> 2026-11-16. Status: **built**, apart from what section 6 lists. Every example here runs.

Themis's core names no field and no project. Everything specific is added from outside, through
four extension points. None of them changes Themis.

| Extension | Use it when | Written as | Lives in |
| --- | --- | --- | --- |
| [Parameters](#1-parameters) | A value differs between projects: a window, a budget, a path, a level | Declarative values | The project's `themis.toml` |
| [External check](#2-external-checks) | The project already has a check, in any language | A command | The project's `themis.toml` |
| [Local pack](#3-local-packs) | One project needs a rule no pack has | Python, with proofs | A folder in that project |
| [Pack](#4-packs) | A whole field needs its vocabulary and rules | Python, with proofs | An installable package |

Start at the top of that table. Most projects need only the first two.

## 1. Parameters

Every rule declares its parameters. Each has a type, a default, and its **stricter direction**,
so Themis can tell a tightening from a weakening without a person reading the change.

```toml
[rules]
"claims/receipt" = "warn"                                    # a level alone
"checkpoint/shape" = { headline_lines = 5, entry_bullets = 10 }
"order/sealed-first" = { level = "enforce", since = "2026-09-21" }

[marketing.evidence]                                         # a pack's own table
max_age_days = 30
```

| Kind of value | Examples | Stricter direction |
| --- | --- | --- |
| Level | `off`, `warn`, `enforce` | Towards `enforce` |
| Start date | `since` | Earlier |
| Maximum | A window in days, a budget, a line cap | Lower |
| Minimum | Items needed to decide, a required score | Higher |
| Set that allows | A role's paths, allowed tiers, a closed list | Smaller |
| Set that requires | Governed documents, protected paths, required fields | Larger |
| Table of sets | `layout/required-files`'s kinds: a folder pattern and the files it needs | Key by key: a new kind or a new file is a tightening |

A value with no stricter direction, such as a folder name, cannot be classified. Setting it for
the first time turns a rule on, which is a tightening. Changing it afterwards is treated as a
weakening, because a path pointed somewhere else can hide what the rule was guarding. `work` is a
set that requires: one pattern or a list, and another pattern added is a tightening.

A rule's parameter is compared with what was in force before it: the value its pack set for it,
when the project had not stated one. So a stated `work` that replaces the folders a pack set is a
weakening, not a first setting.

A pack states the direction of each key of its own table with `Pack(keys=...)`: a dotted key,
`*` for any one name, and a `Key(stricter, default)`. A key it names is compared with its default
in that direction: a window's `looks` raised above 1 is a weakening. A table of entries whose
direction is `larger`, such as the windows, gains a check with each new entry, whatever it holds.
The rest is read by shape. A new table is a tightening, and so is every key inside it, unless a
named key in it loosens its default. A new list entry is a tightening, and one pattern and a list
of patterns are the same set. A key added to a table that was already there is a weakening, since
nothing says which way it moves the checking; so is a removal, and a changed value. Two core
tables are read their own way: a new `[[suite.skips]]` entry is a weakening and a removed one a
tightening; any change to `[homes]` is a weakening, since it moves where records are read. The
agent hook's keys under `[agents]` carry directions as a pack's would: `pretool = "allow-safe"`, a
new `temp` folder and a new `allow` pattern are weakenings, a new `keep` path or `ask` or `deny`
pattern a tightening (DESIGN.md, section 13). A rule's `since` set for the first time stays a weakening.

The rules that read a project's pages and folders take path patterns:

```toml
[rules."layout/required-files"]
kinds.tool = { folders = "tools/*", files = ["README.md", "*.py"] }    # each tools/ folder holds both

[rules."layout/retired-names"]
names = ["old-name"]                                                   # in any case, in text or a path
allow = [{ file = "docs/history.md", line = "Formerly old-name." }]   # the whole line, once

[rules."layout/no-ignored-citations"]
pages = ["**/*.md"]
index = ["docs/kept-elsewhere.md"]          # git-ignored paths this tracked page lists may be cited

[rules."views/untouched"]
pages = ["docs/**/*.md"]                    # pages a generator stamped with a hash

[rules."docs/no-bare-dollar-pairs"]
pages = ["**/*.md"]
```

### Standards

A pack publishes a **standard**: a named set of rules, the level each must have, and a floor for
each parameter. A project declares one.

```toml
[project]
standard = "themis-marketing/1"
strict = true
```

`themis describe` then reports conformance, in its header:

```text
 standard: themis-marketing/1 — deviating in 2 place(s)
   below   evidence/fresh                   level is warn; the standard requires enforce
   below   decision/calibrated              min_power = 0.7; the floor is 0.8
```

With `strict = true` a value below the floor fails `config/standard-floor`. Without it, the value
is listed and the project is described as "deviating", never as conforming. Two projects that
declare the same standard are held to the same floor.

## 2. External checks

An external check is any command, run as a rule. It is how a project keeps what it already has.

```toml
[[checks.external]]
id = "ext/content-validator"
description = "Scripts follow the writing rules"
command = ["python3", "tools/check_scripts.py", "content/scripts"]
when = ["content/scripts/**"]
verdicts = { pass = [0], fail = [1] }
output = "path-line-message"
timeout_s = 120

[[checks.external.proofs]]
name = "a forbidden word is caught"
plant = { file = "content/scripts/example.md", append = "\nA forbidden word.\n" }
expect = "fail"
expect_output = "forbidden"

[[checks.external.proofs]]
name = "the finished example passes"
expect = "pass"
```

| Key | Meaning | Default |
| --- | --- | --- |
| `id` | The rule id, always under `ext/` | Required |
| `description` | What the check promises, in one line | Required |
| `command` | The program and its arguments, as a list. Never a shell line. | Required |
| `cwd` | Where it runs, inside the repository | The root |
| `when` | Paths that trigger it under `themis check --changed` | Always runs |
| `verdicts` | Which exit codes are a pass and which are a fail | `pass = [0]`, `fail = [1]` |
| `output` | A parser that turns output into located breaches | None: the output is shown as it is |
| `timeout_s` | Seconds before the check is stopped | 300 |
| `needs` | What it reaches beyond the repository, such as `network` | Nothing |
| `proofs` | Plants that must fail it, and honest cases that must pass | None: listed as unproven |

An external check is held to the same laws as a native rule.

- **REFUSE is never a pass.** The check is REFUSE when the program cannot start, runs past its
  timeout, is stopped by a signal, returns an exit code the mapping does not name, or prints
  output its declared parser cannot read.
- **It is proven.** A plant edits a file in a copy of the repository, and the check must then
  fail, with the expected text in its output. That last part is what keeps the proof strict: the check must fail
  for the planted reason, not for any reason. A plant does one thing to one file: `append`,
  `content`, `delete`, or `find` with `replace`. With `stage = true` it also stages that file in
  the copy, so a check that reads only what is staged (a pre-commit guard) is proven on it.
- **Its copy holds what git carries.** The copy has the tracked files and the untracked ones that
  are not ignored, as the working tree holds them, and a git folder of its own. Ignored data, such
  as a results cache, stays behind, so a large one never slows a proof.
- **It is protected.** The files named in `command` join the protected paths, so no agent role
  can edit the script that judges its own work.
- **It is locked.** The command and the hash of its script are part of the configuration hash.

Two parsers ship with the core: `path-line-message` (lines of `path:line: message`) and
`json-lines` (one JSON object a line). A check whose output is in another format can leave
`output` unset; its output is then shown as it is.

### Shadowing

Not built yet. The manifest accepts `shadow = "ext/<id>"` on a rule, so that a pack rule could
one day run beside an external check that claims the same promise and report where they differ.
Nothing reads the setting today. Until then a project compares the two by hand before it
replaces its own check.

## 3. Local packs

When one project needs logic no pack has, it writes a local pack: a folder in its own repository,
named in the manifest.

```toml
[project]
local_pack = "tools/themis_pack"
```

The folder holds an `__init__.py` that defines a module attribute named `pack`, a `Pack`. A
local pack uses the same interface as an installed pack and is held to the same contract, proofs
included: `themis prove` runs its proofs and the pack kit. Its folder is a protected path. If a second project comes to need the same rule, the
rule moves into a pack. It never moves into the core unless it is true in every field.

## 4. Packs

A pack teaches Themis one field. It can provide these, and a field rarely needs them all.

| A pack provides | Where it goes |
| --- | --- |
| Its own table in the manifest | `Pack(schema=...)`: unknown keys are refused, as in the core |
| Which way each key of that table tightens | `Pack(keys=...)`: a dotted key with `*` for any name, and `Key(stricter, default)` |
| Kinds of work | `Pack(kinds=...)`: each kind, and what it must produce, for `themis describe` |
| Records | `records.register(kind, schema, home)` |
| Rules, with their proofs | `@rule(...)` and `@proof(...)`, with `pack=` set to the pack's name |
| Gate functions | `@pack.gate(name, version=...)`, each with `@pack.calibration(...)` cases |
| Defaults for core rules | `pack.defaults`: a function of the manifest |
| A report | `pack.report`: what `themis report` calls |
| The inputs of a gate | `pack.inputs[gate]`: builds what the gate reads from the records, so it is never typed |
| Records for a guarded action | `pack.actions[action]`: what `themis act` writes before the command starts, such as a look record; it raises ValueError to refuse, and then nothing runs |
| Standards | `pack.standards[id] = Standard(...)` |

A whole pack, small enough to read at once. It runs as a local pack as it is.

```python
from themis.pack import Pack, Standard
from themis.rule import Param, proof, rule

pack = Pack(name="notes", schema={"file": str})
pack.standards["notes/1"] = Standard("notes/1", levels={"notes/short": "enforce"},
                                     floors={"notes/short": {"max_lines": 50}})


@rule("notes/short", "The notes file stays short.", pack="notes",
      params=(Param("max_lines", int, 50, "lower", "the most lines the notes may hold"),),
      learned="A notes file grew until nobody read it.")
def short(ctx):
    name = ctx.manifest.table("notes").get("file") or "NOTES.md"
    text = ctx.read(name)
    if text is None:
        ctx.refuse(f"there is no {name}", fix=f"write {name}")
        return
    ctx.inspect()
    if len(text.splitlines()) > ctx.param("max_lines"):
        ctx.breach("the notes are too long", where=name, fix="move old entries to an archive")


@proof("notes/short", "a short file", expect="pass")
def _(world):
    world.write("NOTES.md", "one line\n")


@proof("notes/short", "a file past the limit", expect="fail", contains="too long")
def _(world):
    world.write("NOTES.md", "a line\n" * 51)


@pack.gate("keep", version="1")
def keep(metrics):
    if not isinstance(metrics.get("score"), (int, float)):
        return {"decision": "defer", "verdict": "refuse", "enough_evidence": False,
                "reason": "no score", "numbers": {}}
    yes = metrics["score"] > 1
    return {"decision": "keep" if yes else "drop", "verdict": "pass" if yes else "fail",
            "enough_evidence": True, "reason": f"the score is {metrics['score']}", "numbers": metrics}


@pack.calibration("keep", "noise", "a score of zero")
def _():
    return float(keep({"score": 0})["verdict"] == "pass")


@pack.calibration("keep", "planted", "a score of two")
def _():
    return float(keep({"score": 2})["verdict"] == "pass")
```

What a rule may do with `ctx`: read files (`ctx.read`, `ctx.exists`, `ctx.files`), records
(`ctx.records`), git history (`ctx.git`), the manifest and its own parameters (`ctx.param`). It
says what it found with `ctx.inspect()`, `ctx.breach(...)`, `ctx.refuse(...)` and
`ctx.not_configured(...)`. A rule that inspected nothing is a REFUSE, whatever else it said.
A rule that binds from a date asks `ctx.predates(files)` (did the first of these files reach the
main line before its `since`?) or keeps `ctx.bound(units)`, the units that do not predate it; it
never reads the main line's dates itself.

A pack's own `work` setting, such as `[trading] work`, is one glob or a list of them, as the
core's is: `Either(str, [str])` in its schema, read with `themis.work.patterns`, with each unit and
its files found by `themis.work.units`. A record that names a unit by folder name alone is matched
with `themis.work.named`, which matches only when no other unit shares that folder name.

```toml
[trading]
work = ["research/*", "systems/*/setups/*/tune"]    # a study is a folder under either
```

A proof builds a small repository from scratch in `world`: `write`, `remove`, `move`,
`manifest`, and git with `commit`, `branch`, `checkout`, `merge` and `pull_request`; `on(day,
hour)` dates the commits that follow, to the hour, for a proof of `since` or of what reached the
main line before a moment of the day. `ctx.git.commit_time(commit)` reads a commit's time to the
second, with its UTC offset; `ctx.git.last_changes(main)` gives each file's last main-line change,
where `arrivals` gives its first, and `ctx.git.versions(main, path)` every text a file held on the
main line, a removed file's too. The proof holds only when the rule
reaches the expected verdict, and, with `contains`, for that reason.

An installed pack is found through a Python entry point named `themis.packs`.

### Adding a new field

A new category of work needs a new pack, and nothing else. The core does not change.

| Step | What to do |
| --- | --- |
| 1 | Check it is a field and not one project. If only one project needs it, write a local pack instead. |
| 2 | Name the kinds of work, and what each kind must produce. |
| 3 | Define the records: the facts of the field, each with one home. |
| 4 | Say what the core primitives mean here: what is sealed, what is counted, which actions need a grant, which checks need eyes. |
| 5 | Write the field's own rules, each with a plant that fails it and an honest case that passes. |
| 6 | Write the gate function, and calibrate it on noise and on a planted effect. |
| 7 | Write adapters for the tools the field uses, and the report a newcomer should see. |
| 8 | Publish a standard: the rules, their levels and the floor of each parameter. |
| 9 | Run the pack test kit. A pack that fails it is refused. |

A pack can ship inside Themis or as its own distribution, named `themis-pack-` followed by the
field. Either way it is found through the same entry point, and a project turns it on with one
line: `packs = ["the-field"]`.

If writing the pack seems to need a change to the core, stop. Either the new thing is true in
every field, and belongs in the core for all packs, or the core has let a field leak into it.

### The pack test kit

`themis.pack.kit` checks a pack against the contract, and `themis prove` fails a project whose
pack falls short.

| The kit requires | Why |
| --- | --- |
| Every rule's promise is one full sentence | `themis describe` and the generated instructions are built from it |
| Every rule has a planted fault that fails it and an honest case that passes | Law 6 |
| Every parameter has a line of help, and a stricter direction Themis knows | So a weakening can be detected |
| Every standard names rules and parameters that exist, and a floor only where a direction is known | A floor must mean something |
| Every gate function has a version, a noise case and a planted case | A gate that cannot say no has not earned a yes |

Two more hold without the kit. The engine turns a rule that inspected nothing into a REFUSE, and
a rule id can be registered only once, so a pack cannot replace a core rule. A test in this
repository keeps project names out of every file, the packs included.

### Adapters

An adapter reads one tool's output into a pack's records. Themis ships none for any one tool:
that code belongs to the project, or to a pack for that tool's field. A pack ships the pieces an
adapter is built from, such as the trading pack's `trades.from_rows`, which maps any engine's
column names onto the standard trade table. An adapter follows three rules: it validates before
it trusts, it refuses what it cannot read, and it never guesses a missing value.

The manifest has an `[adapters]` table, which a pack may read for its adapters' settings. No
shipped pack reads it yet.

**A forward run's weekly record.** The trading pack's forward kind reads one record each ISO week,
`<study>/results/week-YYYY-WW.json`, and the project's own script writes it: `themis run <study>
--input <live log> --input <replay> -- <the script>`, where the script reads the live log and the
replay of the same dates and writes the record. Themis ships no such script; it checks what the
script writes. Every key is required (a list or a table may be empty), and every time carries its
UTC offset: a tool that keeps the server's own time converts it first. Key by key:

| Key | What the script writes |
| --- | --- |
| `week` | The ISO week, `YYYY-WW`, as the file is named |
| `period` | `from` and `to`: the moment the week starts, and the moment the next one starts. Its middle, in UTC, falls in the ISO week the file names, and it runs for 8 days at most |
| `live` | The live week: `run` (its id), `settings` (the fingerprint the seal names), `start` (`at`, `balance`, `open_positions`, `peak`), `trades` (the matched and extra entries together), `net`, `first_trade_at` (empty only with no trade) |
| `replay` | The same settings replayed over the same `period`, from the same `start`: `run`, `settings`, `period`, `start`, `trades`, `net`; `null` when no replay was made |
| `entries` | The two runs' entries of this week only, paired: `matched` (`id`, `live_at`, `replay_at`), `missed` by the live run and `extra` to it, each with `id`, `at` and its `reason`; each `live_at` and `at` in the period. With no replay, every live trade is extra |
| `fill_costs` | For each kind of fill: `n`, and the cost `live` and in the `replay` |
| `gap` | `parts`: live less replay `net`, split into the seal's `gap_parts`; `unexplained`: what they leave. Themis works the remainder out again from the money and the sealed parts, and reads its own |
| `lines` | Each of the project's own sealed lines: its `value`, and the `n` it is read on; `value` is `null` when the line has no sample this week (`n` 0). Not `match` or `unexplained`: Themis computes those |
| `conditions` | `changes`: each change in trading conditions during the week, with `at` (in the period), `what`, `from` and `to` |
| `risk` | Each sealed risk line's number for the week |
| `range` | The live money on each sealed range day that falls in the week |

Further fingerprint fields may sit beside the others in `live` and `replay`, for
`forward/same-dates-control`'s `fields`. A record that leaves out a trade or a change hides it from
every rule: the script is the project's, and so is its honesty.

## 5. What an extension may not do

| Not allowed | Because |
| --- | --- |
| Lower a core rule's level from inside a pack | Only a project's manifest sets levels, and weakening needs the owner |
| Ship a rule with no proof | The pack kit refuses it, and `themis describe` lists the rule as unproven |
| Put logic in the manifest | Values are declarative so that changes can be compared mechanically |
| Name a project in a pack, or a field in the core | Each layer must be usable by the next project without change |
| Change the work it checks | A check reads; only the lifecycle commands write |

## 6. Not built yet

- The `shadow` setting (section 2).
- Readers for `[adapters]`, and any adapter for one tool's format.
- A parser for test-runner or code-analysis output beyond the two in section 2.
