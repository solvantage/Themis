# Extending Themis

> Design 0.2 — 2026-11-16. Status: **proposed**. Nothing here is built.

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

A value with no stricter direction, such as a folder name, is neutral: changing it is neither a
tightening nor a weakening, but it must still pass `config/valid`.

### Standards

A pack publishes a **standard**: a named set of rules, the level each must have, and a floor for
each parameter. A project declares one.

```toml
[project]
standard = "themis-marketing/1"
strict = true
```

`themis describe` then reports conformance:

```text
Standard: themis-marketing/1
  35 rules required · 33 at or above the floor · 2 below

  below   evidence/fresh         max_age_days = 45   floor 30
  below   results/enough-items   min_items = 2       floor 3
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
- **It is proven.** A plant edits a file in a clone and the check must then fail, with the
  expected text in its output. That last part is what keeps the proof strict: the check must fail
  for the planted reason, not for any reason.
- **It is protected.** The files named in `command` join the protected paths, so no agent role
  can edit the script that judges its own work.
- **It is locked.** The command and the hash of its script are part of the configuration hash.

Parsers shipped with the core: `path-line-message` (lines of `path:line: message`), `junit`,
`sarif` and `json-lines`. A project that needs another format writes it in a local pack.

### Shadowing

A pack rule can run beside an external check that claims the same promise.

```toml
[rules."compliance/banned-terms"]
level = "warn"
shadow = "ext/content-validator"
```

Themis runs both on the same tree and reports each difference as a finding. This is how a project
decides, with evidence, whether to replace its own check with the pack's rule.

## 3. Local packs

When one project needs logic no pack has, it writes a local pack: a folder in its own repository,
named in the manifest.

```toml
[project]
local_pack = "tools/themis_pack"
```

A local pack uses the same interface as an installed pack and is held to the same contract,
proofs included. It is a protected path. If a second project comes to need the same rule, the
rule moves into a pack. It never moves into the core unless it is true in every field.

## 4. Packs

A pack teaches Themis one field. It must provide six things.

| A pack provides | What it is |
| --- | --- |
| Kinds of work | The shapes work takes in this field, and what each kind must produce |
| Records | The schemas of the field's facts |
| Rules | The field's own gates, beside the core's |
| Gate functions | What "enough evidence to decide" means, and the decisions that can be issued |
| Adapters | Readers that turn a tool's files into the pack's records |
| A report | What a finished piece of work must show a newcomer |

The interface, in outline:

```python
from themis.pack import Pack, Param

pack = Pack(name="example", standard="themis-example/1")


@pack.rule(
    "evidence/fresh",
    promise="Evidence is no older than the window.",
    params=[Param("max_age_days", int, default=30, stricter="lower", floor=30)],
)
def evidence_fresh(ctx, max_age_days):
    for row in ctx.records("evidence"):
        if row.retrieved is None:
            yield ctx.refuse(row, "the row has no retrieved date")
        elif ctx.age_days(row.retrieved) > max_age_days:
            yield ctx.breach(row, f"retrieved {row.retrieved}, more than {max_age_days} days ago")


@pack.proof("evidence/fresh")
def a_stale_row_is_caught(world):
    world.plant(record="evidence/e1", set={"retrieved": world.days_ago(31)})
    world.expect_breach("evidence/fresh")


@pack.proof("evidence/fresh")
def a_fresh_row_passes(world):
    world.expect_pass("evidence/fresh")
```

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

`themis.pack.kit` checks a pack against the contract. `themis prove` runs it and refuses a pack
that fails.

| The kit requires | Why |
| --- | --- |
| Every rule has a one-line promise | `themis describe` and the generated instructions are built from it |
| Every rule has a plant that fails it and an honest case that passes | Law 6 |
| Every parameter declares its type, default and stricter direction | So weakening can be detected |
| A rule that inspects nothing returns REFUSE | Law 4 |
| A rule only reads; it writes nothing and reaches nothing it did not declare | A check must not change what it checks |
| No rule id repeats a core rule's id | A pack adds gates; it never replaces one |
| Every gate function holds a calibration: it says no to noise and yes to a planted effect | A gate that cannot say no has not earned a yes |
| The pack's source names no project | A pack serves a field |

### Adapters

An adapter reads one tool's output into a pack's records. It is where the outside world meets the
pack, so it follows three rules: it validates before it trusts, it refuses what it cannot read,
and it never guesses a missing value.

```toml
[adapters.results]
reader = "csv"
path = "results/*.csv"
map = { id = "item", views = "views", follows = "new_followers" }
```

Common readers (`csv`, `json`, `junit`) ship with the core. A reader for one tool's own format
ships with the pack that needs it.

## 5. What an extension may not do

| Not allowed | Because |
| --- | --- |
| Lower a core rule's level from inside a pack | Only a project's manifest sets levels, and weakening needs the owner |
| Ship a rule with no proof | An unproven rule is listed as unproven and cannot be enforced |
| Put logic in the manifest | Values are declarative so that changes can be compared mechanically |
| Name a project in a pack, or a field in the core | Each layer must be usable by the next project without change |
| Change the work it checks | A check reads; only the lifecycle commands write |
