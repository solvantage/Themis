# Getting started with Themis

> 2026-11-20, for release 0.3.0. Every command and every message quoted here was run against a
> release: T1–T3 and M1–M3 against 0.1.0, G1 and T4 against 0.2.0, T5 against 0.3.0. The messages
> of G1, T4 and T5 are held to what this release prints by `tests/test_onboarding.py`.

Themis checks a repository the way a careful reviewer would, every time, from the files and the
git history. An AI agent working in the repository cannot quote a number nothing recorded,
decide a result by typing it, spend past a budget, publish without your yes, or look at sealed
data unasked. This page sets it up for trading research or for marketing content, and walks
cases through the whole workflow: a guarded command in any project, five trading cases and three
content cases.

## Key features

| Feature | What it means for you |
| --- | --- |
| Three verdicts | Every rule answers PASS, FAIL or REFUSE. REFUSE means "could not tell", and it is never counted as a pass. Exit codes 0, 1 and 2. |
| The plan comes first | A plan (a trading `PRE-REG.md`, a content `brief.toml`) must reach `main` in an earlier merge than anything made from it. Checked from git history. |
| Your yes is a file | Opening sealed data and publishing an item each need your grant, made with `themis grant`. A grant opens one thing, once. |
| Guarded commands | A command that deletes, spends or looks at sealed data runs through `themis act`: once, on your unspent grant, with a receipt. Its script can refuse to run any other way. |
| The gate decides | A decision is issued by a gate function from the records. A decision typed by hand fails, and so do inputs typed kinder. Too little evidence is "defer" or "too few", never "no". |
| No number without a record | A number in a governed page carries a tag naming its record, and must match it. A cost must equal the tools' receipts. |
| Built, never typed | Reports are built from the records. A page left behind by a later change fails. |
| Checks that need eyes | A checklist row is ticked only by an attestation from its judge, tied to the hash of the file judged. |
| Agent hooks | Before a command, the hook stops deletes, force-pushes, grants, the owner's own decisions and attestations, and edits to protected files, and asks you; in `allow-safe` mode it also allows what it knows is safe, and leaves the rest to your host. At the end of each turn, a new failure keeps the turn open. |
| Git hooks | Before each commit `themis check --changed` runs, and before each push `themis check`, from your own terminal too. |
| Guarded configuration | Loosening a threshold or switching a rule off fails until you grant it. Tightening is free. |
| Every guard is proven | Each rule ships cases it must fail on. `themis prove` shows they still fail in your repository. |

## Set up

**1. Install.** In your project, from the repository pinned to a release (see
[RELEASES.md](../RELEASES.md) for the commit), or from a local index (see
[publishing.md](publishing.md#using-themis-in-a-project)):

```bash
uv add --dev "themis-guardrails @ git+https://github.com/solvantage/Themis@<release commit>"
uv run themis --version
```

**2. Write the manifest.** `uv run themis init` writes a starter `themis.toml`. Replace it with
the one for your field, and change the paths, dates and numbers to yours.

For trading research:

```toml
[project]
name = "my-research"
packs = ["trading"]

[trading]
work = "research/experiments/*"     # one folder per study

[trading.windows.train]
from = "2019-01-01"
to = "2024-12-31"

[trading.windows.holdout]
from = "2025-01-01"
to = "2026-12-31"
sealed = true                       # opens only with your grant

[rules]
"config/valid" = "enforce"
```

For marketing content:

```toml
[project]
name = "my-content"
packs = ["marketing"]

[marketing]
work = "content/items/*"            # one folder per item

[marketing.evidence]
max_age_days = 30

[marketing.banned_terms]
file = "rules/banned-terms.txt"     # one forbidden term a line

[marketing.products]
file = "products.csv"               # id, name, price, link, benefit

[marketing.rulebooks.selling]
file = "rules/selling.toml"         # the checklist rows, each with its judge
max_age_days = 60

[marketing.purposes.sales]
goal = "orders_per_thousand_views"  # the number a sales item is judged on

[marketing.spend]
unit = "credits"
run_ceiling = 2000                  # the most one item may cost

[marketing.results]
min_age_days = 7
baseline = "own-median"

[rules]
"config/valid" = "enforce"
```

**3. Lock it and install the hooks.**

```bash
uv run themis config lock       # writes themis.lock
uv run themis hooks install     # writes the hooks into .claude/settings.json
uv run themis hooks install --git   # writes .githooks/pre-commit and pre-push, sets core.hooksPath
git add themis.toml themis.lock .claude/settings.json .githooks
git commit -m "Themis: manifest, lock and hooks"
```

The git hooks run `themis check --changed` before each commit and `themis check` before each
push. Name their folder under `[agents]` as `git_hooks = ".githooks"`, and `agents/hooks-installed`
fails when one goes missing or no longer runs Themis. A different hook already in that folder is
kept unless you add `--force`.

To stop being asked about everyday work, add `pretool = "allow-safe"` under `[agents]`, run
`themis config lock` again, and commit; `themis config diff` lists the switch as a weakening, which
needs your grant. The hook then gives three answers. It allows a call only when it reads every
command in it and each is on its safe list: tools that only read, `git status`, `log`, `diff`,
`add`, `commit -m`, `push -u origin BRANCH` for a branch other than main, writes inside the project
away from protected files, and deletes inside a folder of `/tmp` or in `$TMPDIR` (`temp = [...]`
names other folders). It is a best-effort list, not a sandbox: what it does not fully understand
it leaves to your host. It asks,
as before, for a delete elsewhere, work thrown away, a remote command or an upload, `themis grant`
and your own decisions and attestations, and a write to a protected file or to one under
`keep = [...]`; your `deny` patterns and the host's deny list are answered deny. Everything else,
such as `python`, `npm test` or `make`, gets no answer, so your host's own permission mode decides
as it did. To let your test or lint command through, name it exactly under `allow`, such as
`allow = ["uv run --frozen pytest*"]`; the agent can then run whatever it writes into the tests.
`themis doctor` prints the mode in force, and says when a host settings file cannot be read.

**4. Look before you enforce.** Every rule starts at `warn`: it runs and reports, and blocks
nothing.

```bash
uv run themis describe   # every rule, and which are not in force
uv run themis check      # where the repository stands today
```

**5. Turn on the first rules.** These catch the costliest mistakes and need nothing beyond the
manifest above. Add them under `[rules]`, run `themis config lock` again, and commit.

For trading research:

```toml
"order/sealed-first" = { level = "enforce", empty = "allow" }
"holdout/guarded" = { level = "enforce", empty = "allow" }
"grant/required" = { level = "enforce", empty = "allow" }
"config/locked" = "enforce"
"config/no-silent-weakening" = "enforce"
```

For marketing content:

```toml
"order/sealed-first" = { level = "enforce", empty = "allow" }
"publish/granted" = { level = "enforce", empty = "allow" }
"spend/priced-first" = { level = "enforce", empty = "allow" }
"config/locked" = "enforce"
"config/no-silent-weakening" = "enforce"
```

A rule with nothing to inspect answers REFUSE. In a new repository, with no result, no look, no
post and no spend yet, these rules have nothing to look at. `empty = "allow"` lets that pass.
Leave it out in a repository that already has work in it, so a rule pointed at the wrong folder
still says so. Taking it out later is a tightening, and needs no grant.

Raise the other rules one at a time, as the repository is ready for them. `themis check` says
what each one is missing.

## The workflow

| Step | Trading research | Marketing content |
| --- | --- | --- |
| Log | `themis new <name> --question "..."` | The same |
| Seal the plan | Merge `PRE-REG.md` in its own pull request | Merge `brief.toml`, with `evidence.toml` and `checklist.toml`, in its own pull request |
| Do | `themis run <study> --input <data file> -- <your command>` | Write `plan.toml` with its estimate; make the assets; the tools write spend receipts |
| Check | A second script reproduces the numbers | Each checklist row's judge runs `themis attest <file> <row> --judge <judge> --by <who>` |
| Approve | `themis grant holdout <study>/<window>`, by you, to look at sealed data | `themis grant publish <item>`, by you; `post.toml` names the grant |
| Run what the grant opens | `themis act holdout <study>/<window> -- <command>`, when the look is made by a program outside Python | `themis act <action> <target> -- <command>` for any guarded command of your own |
| Decide | `themis decide <study> --gate entry`; each week of a forward run, `themis decide <study>/week-YYYY-WW --gate forward` | `themis decide <series> --gate results --rival <other series>` |
| Report | `themis report <study>` | `themis report <item>` |
| Hand off | `themis checkpoint` | The same |

Skipping a command does not skip the check. A decision written by hand, a number typed into a
page, or a report edited after the fact all fail `themis check`.

## What runs by itself

| When | What runs |
| --- | --- |
| Before every command or file write by the agent | The hook: stops deletes, force-pushes, `themis grant`, the owner's own `themis decide` and `themis attest`, and edits to protected files, and asks you |
| At the end of every agent turn | `themis check`: a new failure of an enforced rule keeps the turn open, at most three times |
| Every pytest run | A receipt of what ran, on which exact tree |
| Every commit and push, from any terminal | The git hooks: `themis check --changed` before a commit, `themis check` before a push |

What does not run by itself: a guarded script started by hand. Themis cannot see a delete or a
spend inside a script, so the script asks `themis act --verify` first and stops when it is not
running under `themis act` (G1).

## Any project: a guarded command

A command that cannot be taken back, such as a publish, a delete or a spend, is named in
`grant/required`'s `guarded` list. It then runs only through `themis act`, on your unspent
grant. The command's own script asks `themis act --verify <action> <target>` first, so running
it by hand does nothing.

```toml
[rules."grant/required"]
level = "enforce"
guarded = ["publish"]      # a trading project keeps "holdout" in its list too
```

### G1. A command that runs once, on your grant

A docs site whose `scripts/publish.py` begins by asking `themis act --verify publish <target>`.

| Step | What happens | What Themis says |
| --- | --- | --- |
| Run it by hand | The agent runs `python scripts/publish.py site` | `there is no THEMIS_ACT_TOKEN, so this is not running inside` act, and the script stops |
| Run it, no grant | `themis act publish site -- python scripts/publish.py site` | `there is no unspent grant for publish on site, so the command did not run` (REFUSE) |
| Self-approve | The agent runs `themis grant publish site` | `Only the owner gives a grant. The owner's approval is needed.` |
| Approve | You run `themis grant publish site --reason "..."` | `Commit it: a grant is visible in review, and is used once.` |
| Run | The agent runs the same `themis act` | `the command exited 0. The grant is spent` |
| Run again | And again | `there is no unspent grant for publish on site` |
| Check | `grant/required` and `grant/single-use` | Both pass |
| A receipt by hand | The agent writes an action receipt itself | `the guarded action publish ran on site with no grant` |

The hook does not stop `themis act`: the agent runs it, and your click stays on `themis grant`.
The action receipt in `receipts/action/` names the grant, the command, the hash of the token the
command was given, and how it exited.

## Trading: five cases, start to finish

### T1. An honest study

| Step | What happens | What Themis says |
| --- | --- | --- |
| Log | `themis new open-drive --question "..."` | A ledger record, and the study's folder |
| Seal | `PRE-REG.md` merged on its own | — |
| Run, too early | The agent runs with an uncommitted file in the tree | `a result made on it pins nothing` (REFUSE) |
| Run | The tree is clean and the seal is on `main` | `the command exited 0`, with a run receipt and the provenance file |
| Decide | `themis decide <study> --gate entry` | `kill. the signal is not better than a dumb entry: 19 of 100 dumb draws did at least as well (p = 0.198, and 0.05 is the bar)` |
| Report | `themis report <study>` | Writes `results/scorecard.csv` and `results/report.html` |
| Write-up | The README number is pasted from `themis cite <study> net_ev` | The number carries its tag, and `claims/receipt` passes |
| Hand off | pytest runs, then `themis checkpoint` | `**Suite:** 1 pass / 0 skip`, with the receipt's tag |

A kill is a FAIL verdict, so `themis decide` exits 1. That is the gate's answer, not an error.

### T2. The holdout, looked at once

The study's code asks for the sealed dates through Themis:

```python
from pathlib import Path

from themis import manifest
from themis.packs.trading import data

start, end = data.window(Path("."), manifest.load(Path(".")), "holdout",
                         grant=GRANT_ID, study="research/experiments/2026-11-20_open-drive")
```

| Step | What happens | What Themis says |
| --- | --- | --- |
| Ask, no grant | The code asks for `holdout` | `the window holdout is sealed and was not opened: no grant is named` |
| Self-approve | The agent runs `themis grant holdout holdout` | `Only the owner gives a grant. The owner's approval is needed.` |
| Approve | You run `themis grant holdout holdout --reason "..."` | Writes the grant under `grants/`; its file name is the `GRANT_ID` |
| Look | The code asks with the grant | The dates are handed over, after a look record and an action receipt are written |
| Look again | The code asks with the same grant | `was already used by the look` |
| Check | `holdout/guarded`, `grant/required`, `holdout/one-signal-look` | All three pass |
| A second grant | You grant again, and the code takes a second signal look | `this is signal look number 2 at the sealed window holdout, which allows 1` |

### T3. Corners cut

| Step | What the agent does | What Themis says |
| --- | --- | --- |
| Seal | Merges the plan and the results in one pull request | `a result reached the main line in the same merge as its seal, or before it` |
| Decide | Types "promote" over the gate's "kill" | `the stored decision is 'promote' with the verdict 'pass', but the gate entry returns 'kill' with the verdict 'fail'` |
| Decide | Overrules the gate as the owner | `Only the owner overrules a gate. The owner's approval is needed.` |
| Decide | Writes a "kill" by hand with no power figure | `this fail does not show enough power to stand, so it is a deferral and not a kill` |
| Write-up | Writes "0.62" from memory | `the number 0.62 cites no record` |
| Report | Runs again and keeps the old report page | `the report was not rebuilt after its inputs changed` |
| Config | Switches a rule off in `themis.toml` | `the configuration differs from its lock` |
| Config | ...or does it with `sed` | `This command writes to themis.toml, which only the owner changes.` |
| Hand off | Says the suite passes without running it | `**Suite:** unverified — no receipt for this tree.` |

The trading gates say yes to pure noise about one time in twenty, which is the false-alarm rate
they are built to. Themis makes sure the decision is the gate's; it cannot make a gate stronger
than its own error rate.

### T4. A strategy tuned in an outside tester

The strategy runs in a tester Themis knows nothing about. Each run the tester makes is a row of
the study's `results/run-history.csv`, with the id of the settings it used; a script of the
project's turns the tester's own output into that file, the metrics and the trade table. The
study is a `tune` study, and the project names the most faithful model a confirming run can use:

```toml
[trading]
work = "tuning/*"

[trading.windows.in-sample]
from = "2018-01-01"
to = "2022-12-31"

[trading.windows.out-of-sample]
from = "2023-01-01"
to = "2024-06-30"

[trading.tune]
confirm_model = "every tick"

[rules]
"prereg/declared" = "enforce"
"trials/settings-counted" = "enforce"
"holdout/guarded" = "enforce"
"holdout/one-signal-look" = "enforce"
"grant/required" = "enforce"
"grant/single-use" = "enforce"
"validity/confirm-on-real-ticks" = "enforce"
"decision/issued-by-gate" = "enforce"

[rules."scorecard/believable"]
kinds = ["strategy", "signal"]      # a tune study ships no README of its own

[rules."scorecard/explainer"]
kinds = ["strategy", "signal"]
```

The seal names the study's kind and gate, the windows it reads (one of them its own, sealed),
how many settings the search may try, and the risk rules each stage is judged under:

```markdown
---
kind: tune
windows: [in-sample, out-of-sample, unseen]
window-unseen: {from = "2024-07-01", to = "2025-12-31", sealed = true}
gate: tune
iterations: 40
risk_rules: rules/risk.json
---
```

| Step | What happens | What Themis says |
| --- | --- | --- |
| Log | `themis new breakout --question "..."` | `Seal its plan before anything runs.` |
| Seal | `PRE-REG.md`, as above, merged in a pull request of its own | `prereg/declared` passes |
| Map | The trial's `variants` is raised to 8, then `themis run <study> --input <data> -- <tester>` maps 8 settings in-sample | `the command exited 0`, with a run receipt and the provenance file |
| Screen and tune | `variants` raised to 12 before 4 more settings run inside the region that held; the tester writes what in-sample, out-of-sample and the walk back found | `trials/settings-counted` passes: 12 settings versions, 12 counted |
| Look, too early | `themis act holdout <study>/unseen -- <tester> confirm` | `there is no unspent grant for holdout on <study>/unseen, so the command did not run` (REFUSE); the tester never starts |
| Self-approve | The agent runs `themis grant holdout <study>/unseen` | `Only the owner gives a grant. The owner's approval is needed.` |
| Approve | You run `themis grant holdout <study>/unseen --reason "..."` | `Commit it: a grant is visible in review, and is used once.` |
| Holdout, once | The agent runs the same `themis act`. The confirming run uses the model named under `[trading.tune]` and writes `confirm_model` into the metrics | `Wrote looks/`, then `The grant is spent` |
| Decide | `themis decide <study> --gate tune` | `full-pass. the setting passed every stage, the holdout included` |
| Report | The confirming run's deals, turned into the standard trade table with `trades.from_rows`; then `themis report <study>` | Writes `results/scorecard.csv` and `results/report.html` |
| Hand off | `themis check` | PASS: the study's grant, look, count, confirming model and decision all hold |

The `tune` gate reads outcomes, not prices: whether each stage paid under the risk rules is
decided inside that stage. So the rules around it carry the weight, and the corners an agent cuts
are each caught by one of them:

| Corner cut | What the agent does | What Themis says |
| --- | --- | --- |
| A setting left uncounted | Runs a thirteenth settings version before raising `variants` | `the run history holds 13 settings versions, but the ledger counts 12 for this study` |
| The holdout read by hand | Starts the confirming run itself, outside `themis act` | `there is no THEMIS_ACT_TOKEN, so this is not running inside`, and the script stops |
| A cheaper confirm | Confirms on a coarser model; the gate still says full-pass | `the confirming run did not use the model this project named, "every tick": numbers.confirm_model is "open prices"` |
| A second look, same grant | Runs the confirming `themis act` again | `there is no unspent grant for holdout on <study>/unseen` |
| A second look, new grant | You grant once more, and it looks again | `this is signal look number 2 at the sealed window unseen, which allows 1` |

`<study>` is the folder `themis new` made, such as `tuning/2026-11-19_breakout`. Sibling studies
that tune the same strategy on the same unseen dates declare the same window id, and their looks
count together.

### T5. A forward run, week by week

The tuned settings now trade live. Each week the project's own script reads the week's live log
and a replay of the same dates, from the week's own start, on the same settings, pairs their
entries, and writes the week's record, `results/week-YYYY-WW.json` (its keys are in
[extending.md](extending.md#adapters)). The gate `forward` reads every week up to the one it
decides. The manifest turns the forward rules on:

```toml
[trading]
work = "forward/*"

[rules]
"prereg/declared" = "enforce"
"decision/issued-by-gate" = "enforce"
"decision/calibrated" = "enforce"
"forward/sealed-before-start" = "enforce"
"forward/same-dates-control" = "enforce"
"forward/match" = "enforce"
"forward/gap-explained" = "enforce"
"forward/conditions-stable" = "enforce"
"forward/no-retune" = "enforce"
"forward/enough-trades" = "enforce"
"forward/risk-line" = "enforce"

[rules."scorecard/believable"]
kinds = ["strategy", "signal"]      # a forward run ships no README of its own

[rules."scorecard/explainer"]
kinds = ["strategy", "signal"]
```

The seal names the settings' fingerprint, the trades before any pass, who stops the run, its
lines, its risk line, the parts of the money gap and the known reasons for a missed entry. It is
merged on its own before the first live trade:

```markdown
---
kind: forward
gate: forward
settings: 3f9a0c1d
min_trades: 60
stop_rule: the owner stops the run; a restart is a new run, sealed anew
lines: [match, unexplained, entry-cost]
line-match: {worse = "lower", pass = 0.90, stop = 0.80, running = 2}
line-unexplained: {worse = "higher", pass = 20, stop = 100}
line-entry-cost: {worse = "higher", pass = 0.43, stop = 0.86}
risk: [day-loss]
line-day-loss: {worse = "higher", stop = 0.52}
ranges: []
gap_parts: [costs, missed, extra]
reasons: [news pause]
changes_allowed: [spread]
changes_stop: [leverage]
---
```

| Step | What happens | What Themis says |
| --- | --- | --- |
| Log | `themis new breakout-live --question "..."` | `Seal its plan before anything runs.` |
| Seal | `PRE-REG.md`, as above, merged in a pull request of its own before day 1 | `prereg/declared` passes |
| Calibrate | `themis calibrate forward`, and the receipt it writes committed | `says yes to noise 0.0% of the time` |
| Week 1 | The week's two logs committed; `themis run <study> --input <live log> --input <replay> -- python journal.py <study> 2026-48 <live log> <replay>`; then `themis decide <study>/week-2026-48 --gate forward` | `defer. 20 trades so far, and the seal asks for 60 before any pass` (REFUSE) |
| Week 2 | The same; 3 of the replay's 20 entries are missed live, each for a sealed reason | `look-closer. match is 0.85 this week, worse than its pass of 0.9` (REFUSE) |
| Week 3 | 25 entries, all matched: 62 trades so far | `pass. every line is inside its pass and every entry's reason is known, on 62 trades so far, where the seal asks for 60` |
| Week 4 | The day's loss reaches 0.61 | `stop. the risk line day-loss was passed in week 2026-51: 0.61, past its stop of 0.52` (FAIL) |
| Hand off | `themis check` | PASS: the seal came first, and each week's replay, matches, gap, changes, settings, count and risk line hold |

A bad week is the gate's verdict, not a breach. `look-closer` is a REFUSE: you read the week, and it
is never read as a pass. A `stop` stays: every later week of the run is `stop` too, and new
settings are a new run, sealed in a folder of its own. Only you pass a week ahead of its count, or
overrule a stop, with `themis grant forward <study>/week-YYYY-WW --reason "..."` and then `themis
decide <study>/week-YYYY-WW --gate forward --by owner`, with your decision, verdict and reason.

| Corner cut | What the agent does | What Themis says |
| --- | --- | --- |
| A retune | Trades week 2 on new settings | `week 2026-49 traded the settings 77c0aa11, and the seal's are 3f9a0c1d: a settings change ends the run` (REFUSE: nothing is stored), and `forward/no-retune` fails |
| No replay | Runs the week's script on the live log alone | `week 2026-48 has no replay` (REFUSE), and `forward/same-dates-control` fails |
| A verdict by hand | Types "pass" over the gate's "defer" | `the stored decision is 'pass' with the verdict 'pass', but the gate forward returns 'defer' with the verdict 'refuse'`, and `week 2026-48 is stored as a pass at 20 of the 60 trades the seal asks for` |

## Marketing content: three cases, start to finish

An item is one folder: `brief.toml` (the plan, with its claims), `evidence.toml`,
`checklist.toml`, `plan.toml`, notes under `assets/`, then `post.toml` and `result.toml`. Spend
receipts live in `receipts/spend/`, and agent-run receipts in `receipts/agent-run/`.

### M1. An item done right

| Step | What happens | What Themis says |
| --- | --- | --- |
| Log | `themis new soft-hands --question "..."` | A ledger record, and the item's folder |
| Brief | The brief, its evidence and its checklist merged on their own | The evidence, tier, banned-term, product and checklist rules pass |
| Second reader | Before anyone checks the quotes | `no second-reader has attested that the item's lines say no more than the quoted passages` |
| Second reader | `themis attest <item>/evidence.toml quotes --judge second-reader --by reader` | `It names the file's hash: judge the file again if it changes.` |
| Make | Plan priced at 1,200; a clip from the series' kit; receipts of 650 and 480 | The plan, timing, kit, spend and order rules pass |
| Review | The agent tries to tick your row by attesting as you | `Only the owner attests as the owner. The owner's approval is needed.` |
| Review | You attest your row; the agent attests its own | `compliance/checklist` passes |
| Approve | The agent tries to grant the publish | `Only the owner gives a grant.` |
| Approve | You run `themis grant publish <item> --reason "..."` | Writes the grant; `post.toml` names it |
| Publish | The post goes out with the disclosure flag set | `publish/granted`, `publish/checklist-closed` and `compliance/disclosure` pass |
| Result | `result.toml`, read at 8 days, with its source | `results/recorded` passes |
| Report | `themis report <item>` | Writes `<item>/report.md` and `reports/<series>.md`, every cost tagged; `spend/figures-from-tools` passes |

### M2. Corners cut on an item

| Step | What the agent does | What Themis says |
| --- | --- | --- |
| Brief | Makes the assets in the same pull request as the brief | `a result reached the main line in the same merge as its seal, or before it` |
| Evidence | A claim cites a row the item does not hold | `cites the evidence row e9, which the item does not hold` |
| Script | A spoken line says "miracle cure" | `the forbidden term 'miracle cure' appears in the spoken line of part p1` |
| Caption | Writes the price as 15 | `the caption gives the price 15, and the product record of balm says 19.00` |
| Disclosure | Generated voice, flag left off | `its voice is generated, and the brief does not set the disclosure flag ai_generated` |
| Review | Ticks your checklist row itself | `the row true-result is ticked, and no attestation made as its judge, owner, exists for it` |
| Publish | Posts with no grant and the rows still open | `this item was posted with no grant from the owner` and `this item was posted with 2 checklist row(s) still open: no-cure, true-result` |

### M3. Money and results

| Step | What happens | What Themis says |
| --- | --- | --- |
| Price | A plan priced at 2,400 | `the plan's estimate of 2,400 is above the run ceiling of 2,000` |
| Make | Retakes carry the item to 2,150 | `this item has spent 2,150, which is above the run ceiling of 2,000` |
| Report | A cost on the report typed lower | `and its spend receipts add up to 1,550` |
| Runs | An agent run cost 55 and produced nothing | `this agent run produced nothing, and it is not flagged with a reason` |
| Decide | A series with 2 results | `too-few. alpha has 2 item(s) with results, and 3 are needed to say anything` (REFUSE) |
| Decide | 6 items against 6, clearly ahead | `lead. alpha is higher than beta on the goal number, and the difference is larger than the noise` |
| Decide | The agent types a kinder threshold into the gate's inputs | `the numbers this decision was made from differ from the records in: min_items_to_rank` |
| Decide | The agent types "retire" over the gate's "lead" | `the stored decision is 'retire' with the verdict 'fail', but the gate results returns 'lead' with the verdict 'pass'` |
| Decide | Two series that differ only by noise | `keep. the difference between gamma and delta on the goal number is within the noise` |

## When something is blocked

Each finding names the rule, the file, the reason and a fix. Read the fix line first.

- **Never edit `themis.toml` to get past a rule.** The hook asks you, `config/locked` fails, and
  a loosened value fails `config/no-silent-weakening` until you grant it.
- **A REFUSE is not a pass.** It means the evidence is missing or unreadable. Supply it.
- **To see why a rule exists:** `uv run themis explain <rule id>`.

## Where next

| Read | For |
| --- | --- |
| [packs/trading.md](packs/trading.md) | Every trading rule, the gates, the report, and what the pack cannot do |
| [packs/marketing.md](packs/marketing.md) | Every content rule, rulebooks and checklists, the results gate |
| [extending.md](extending.md) | Parameters, wrapping your existing checks, a pack of your own |
| [../DESIGN.md](../DESIGN.md) | How Themis works, and what is not built yet |
