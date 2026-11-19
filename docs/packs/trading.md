# The trading pack

> 2026-11-20. Status: **built**: twenty-seven rules in seven gates. Standard id: `themis-trading/1`.
> `themis describe` lists each rule below and whether its proofs hold.

**In one line:** this pack teaches Themis what evidence means in trading research. A trial is
counted before it runs, the plan is sealed before the answer is known, unseen data is looked at
once, and a gate function, not a person, says whether an edge is there.

It serves any project that tests trading ideas: research on historical data, strategy backtests,
and the tuning of a strategy's settings in an outside tester. It names no instrument, venue,
engine or project. Those are a project's parameters and its own code.

Turn it on in the manifest:

```toml
[project]
packs = ["trading"]

[trading]
work = "research/experiments/*"     # or a list: ["research/experiments/*", "systems/*/tune"]
```

## 1. What the pack adds to the core

The core supplies the primitives ([DESIGN.md](../../DESIGN.md), section 5). This pack gives them
their trading meaning.

| Core primitive | In this pack |
| --- | --- |
| Ledger | A **trial**: a ledger record that names the study and how many variants it covers |
| Order | The **pre-registration** is the seal; everything under `results/` is a result |
| Decision | A **verdict**, issued by a gate function: `entry`, `signal` or `tune` |
| Grant | One look at a **sealed window** of data |
| Receipt | The action receipt each look leaves; the calibration receipt of each gate |
| Report | The **scorecard** and its report page |

The independent audit is a file in the study, `AUDIT.md`, and not an attestation record.

## 2. Kinds of work

A pre-registration declares its kind in its frontmatter.

| Kind | What it does | What its seal must state | What it must ship |
| --- | --- | --- | --- |
| `strategy` | Books trades | `binding`, `gate`, `nulls`, `windows`, `mde` | The trade table, the scorecard, the report, an audit before any decision |
| `signal` | Predicts | The same five: `binding`, `gate`, `nulls`, `windows`, `mde` | The scorecard, the report, an audit before any decision |
| `data` | Describes; selects nothing | Only its kind | No scorecard and no audit |
| `tune` | Searches a strategy's settings | `windows`, `gate`, `iterations`, `risk_rules` | Every settings version counted as a trial; a confirming run on the model the project named |
| `forward` | Trades live under sealed settings, beside a replay of the same dates | `gate`, `settings`, `min_trades`, `stop_rule`, `lines` with a `line-<id>` for each, `risk` with the same, `ranges` with a `range-<day>` for each, `gap_parts`, `reasons` | A record each week, and that week's decision; no scorecard and no audit |

`mde` is the smallest effect worth seeing. It is set in the seal, never after the run.

A `forward` seal names its gate, `forward`; the fingerprint of the `settings` the live run and every
replay use; how many trades come before any pass (`min_trades`); in words, who stops trading and
what must happen before a restart (`stop_rule`); its lines, its risk lines and its ranges, each an
inline table; the parts the money gap is split into (`gap_parts`); and the known `reasons` for an
entry missed or extra. `changes_allowed` and `changes_stop` are optional lists of a change's `what`.

```markdown
---
kind: forward
gate: forward
settings: 3f9a0c1d
min_trades: 220
stop_rule: the owner stops it; a restart is a new run, sealed anew
lines: [match, unexplained, entry-cost]
line-match: {worse = "lower", pass = 0.90, stop = 0.80, running = 2}
line-unexplained: {worse = "higher", pass = 50, stop = 200}
line-entry-cost: {worse = "higher", pass = 0.43, stop = 0.86, min = 30}
risk: [day-loss]
line-day-loss: {worse = "higher", stop = 0.52}
ranges: [30, 61]
range-30: {low = 9500, high = 12500}
range-61: {low = 9000, high = 15000}
gap_parts: [spread, commission, swap]
reasons: [news pause, server restart]
changes_allowed: [spread]
changes_stop: [leverage]
---
```

`match` and `unexplained` are drawn by every forward seal and computed by Themis; the other lines
are the project's own. A line's `worse` says which way it goes bad, `pass` is its bar, and `stop`,
when it has one, lies past the bar; between the two is "look closer". `running` is how many weeks
in a row a line must be past its stop before it stops the run, 1 when unset, and `min` the least
sample it is read on, 0 when unset. A risk line has only `worse` and `stop`. A range is the live
money on a day since the start, from `low` to `high`.

Whatever its kind, a study that holds anything under `results/` also needs its provenance file,
five answers in its README about how far it can be believed, and a short explainer page or a
stated reason for having none.

## 3. Records

A study is one folder. The pack reads these files in it, and these records beside it.

| Record | Where | Holds |
| --- | --- | --- |
| Trial | `ledger/*.toml` | `work`: the study's path, or its folder name when no other study shares it. `variants`: how many variants it covers; 1 when unset |
| Pre-registration | `<study>/PRE-REG*.md` | Frontmatter: `kind`, the fields its kind needs, and where they apply `cost_model`, `title` and `not_run_reason`; the study's own windows as `window-<id>` (section 7) |
| Provenance | `<study>/results/provenance.json` | `commit`, `clean` (must be true), and `inputs`: each input's path with its sha256 |
| Metrics | `<study>/results/metrics.json` | The numbers the gate reads; `net_of_cost` and `costs_paid`; the `scorecard` table (section 9) |
| Trade table | `<study>/results/trades.csv` | One row for each closed trade (section 8) |
| Audit | `<study>/AUDIT.md` | Frontmatter: `status`, `script`, `study_code` |
| Verdict | `decisions/*.json` | The core's decision record: the decision, the verdict, the gate and its version, the date, the numbers |
| Look | `looks/*.toml` | `window`, `study`, `kind` (signal or pipeline), `at`, `grant`, and for a pipeline look its `scope`, `purpose` and `compared_against` |
| Comparison | `comparisons/**/*.json` | `what` is compared, and `runs`: two or more runs side by side, each with `run` (its id) and the fingerprint fields the project names. Tracked, since a rule cannot see an ignored file |

## 4. The lifecycle

| Step | Command | What stops it |
| --- | --- | --- |
| Log | `themis new` writes the trial record | `order/logged-first`: a result with no trial logged before it |
| Seal | The pre-registration, merged on its own | `prereg/declared`: a field its kind needs is missing. `order/sealed-first`: the seal and a result arrive in one merge |
| Do | `themis run <study> --input FILE -- COMMAND` | The command refuses on a dirty tree, or when the seal is not on the main line. It writes the provenance file. Sealed data opens only through `data.window` with a grant |
| Check | A second script reproduces the numbers; `AUDIT.md` says how it ended | `validity/audit-reproduced` |
| Decide | `themis decide <study> --gate entry` | `decision/issued-by-gate`: the stored verdict is not what the gate returns. `validity/power-stated`: a kill with no power behind it |
| Report | `themis report <study>` | `scorecard/complete`; `report/generated`: the page is older than its inputs |
| Hand off | `themis checkpoint` | The core's handoff rules |

## 5. The pack's rules

Twenty-seven rules in seven gates, beside the core's.

### Gate: trials — attempts are counted honestly

| Rule | The promise | Parameters |
| --- | --- | --- |
| `trials/settings-counted` | Each new settings version in the run history is a counted trial. | `history`, `settings_column` |
| `trials/count-feeds-adjustment` | The luck-adjusted figure uses the ledger's own count of trials. | `penalty`: extra trials, for choices nobody logged |

### Gate: prereg — the plan is complete

| Rule | The promise | Parameters |
| --- | --- | --- |
| `prereg/declared` | The seal names its kind, its binding clause, its gate, its nulls, its windows and the smallest effect worth seeing. | — |
| `prereg/provenance` | Every result carries a fingerprint taken on a clean tree. | — |

### Gate: holdout — unseen data is looked at once

| Rule | The promise | Parameters |
| --- | --- | --- |
| `holdout/guarded` | A window marked sealed is read only with a grant. | Which windows are `sealed` |
| `holdout/one-signal-look` | Each sealed window has at most its allowed number of signal looks. | `looks` on the window; 1 when unset |
| `holdout/pipeline-look-declared` | A look that only proves the code works states its scope, its purpose and what it was compared against, and computes no forward return. | — |

### Gate: validity — the statistics can be trusted

| Rule | The promise | Parameters |
| --- | --- | --- |
| `validity/fills-on-tape` | Every simulated fill sits between its bar's low and high. | — |
| `validity/baselines` | The scorecard carries the always-long and always-short baselines. | `extra`: further baseline lines |
| `validity/net-of-cost` | The binding number is net of a cost that cites how it was derived. | The cost models under `[trading.costs]` |
| `validity/power-stated` | A kill states the power it had, and a fail with too little power is recorded as a deferral. | `min_power`; 0.8 when unset |
| `validity/audit-reproduced` | A study's numbers are decided on only after a separate script reproduces them. | `forbidden`: modules no audit may import |
| `validity/confirm-on-real-ticks` | A tuning study's confirming run uses the most faithful model the project named. | `confirm_model` under `[trading.tune]` |
| `validity/same-basis` | A comparison sets side by side only runs that share every fingerprint field the project names. | `fields` |

### Gate: scorecard — a result a newcomer can read

| Rule | The promise | Parameters |
| --- | --- | --- |
| `scorecard/complete` | A study that books trades or predicts ships its scorecard, with no line left unexplained. | — |
| `scorecard/believable` | A published result answers five questions about how far it can be believed. | `kinds` |
| `scorecard/explainer` | A published result has one short page for a newcomer, or says why it has none. | `max_bytes`, `max_controls`, `kinds` |
| `scorecard/rendering` | No page puts two bare dollar signs in one line, and no chart file is oversized. | `max_chart_bytes` |

### Gate: live — nothing trades live by default

| Rule | The promise | Parameters |
| --- | --- | --- |
| `live/off-by-default` | Every live-trading switch holds its safe value in the source, unless the owner granted that file its flip. | `switches`, `absent` |

### Gate: forward — a live run is held to a replay of the same dates

| Rule | The promise | Parameters |
| --- | --- | --- |
| `forward/sealed-before-start` | A forward run's seal reaches the main line before its first live trade. | `margin_hours` |
| `forward/same-dates-control` | Each week of a forward run has a replay on the same dates, from the same start state, with the same settings. | `fields` |
| `forward/match` | Each week's share of replay entries that also appear live is counted from the entries and read against the sealed lines. | `floor` |
| `forward/gap-explained` | The gap between live and replay money is split into its sealed parts, and the remainder is read against its sealed line. | `tolerance` |
| `forward/conditions-stable` | Every change in trading conditions recorded during a forward run is listed in that week's verdict. | — |
| `forward/no-retune` | The settings fingerprint stays the same for the whole forward run. | — |
| `forward/enough-trades` | A forward run gets no pass before its sealed number of trades. | `min_trades` |
| `forward/risk-line` | A risk number past its sealed line stops a forward run, whatever else passes. | `required` |

### Core rules the pack configures

Once `work` is set, the pack gives these core rules what they need, so a project does not have to.

| Core rule | What the pack sets |
| --- | --- |
| `order/sealed-first`, `order/unchanged` | The seal is `PRE-REG*.md` |
| `order/logged-first`, `ledger/complete` | A result is anything under `results/` |
| `report/generated`, `report/readable` | The report is `results/report.html`, built from the trade table, the metrics and the audit |
| `grant/required` | The action `holdout` is guarded, when a window is sealed: in the manifest, a study table or a seal. A project that states its own `guarded` list replaces this one, so it keeps `holdout` in it |

What the rules read, in more detail:

- **`trials/settings-counted`.** With `since`, a study whose seal reached the main line before
  that date is left alone, as the order rules leave it.
- **`trials/count-feeds-adjustment`.** Metrics that hold `luck_adjusted_sharpe` must hold
  `trials_counted` beside it, and it must be at least the ledger's count plus the penalty. The
  count is of the trials the ledger held at the commit that last wrote the metrics file, so a
  trial logged later does not make an old figure wrong. A metrics file that is new or changed
  answers to the whole ledger.
- **`validity/fills-on-tape`.** It reads `bar_low` and `bar_high` in the trade table. A trade
  with no bar cannot be checked, and that is a REFUSE.
- **`validity/net-of-cost`.** The seal names a `cost_model` declared under `[trading.costs]`,
  which must cite its `derivation`. The metrics must say `net_of_cost = true` and give
  `costs_paid`.
- **`validity/power-stated`.** A decision that fails must carry `numbers.mde` and
  `numbers.power`, and the power must reach `min_power`. A gate in this pack records a weak "no"
  as a deferral by itself; this rule catches a kill written any other way. A `tune` study's kill is
  not read: a budget spent or a stage failed is a stage outcome, not a test too weak to see.
- **`validity/audit-reproduced`.** A `strategy` or `signal` study with a decision needs
  `AUDIT.md` with `status: reproduced` or `differences-explained`, and a `script` in the study
  folder. The script may not be the study's own code and may not import it.
- **`validity/confirm-on-real-ticks`.** It binds a `tune` study whose decision is a pass: the
  decision's `numbers.confirm_model` must be the model named under `[trading.tune]`. The `tune`
  gate copies `confirm_model` from the study's metrics into its numbers, so the metrics name it.
- **`validity/same-basis`.** Each comparison record must list two or more distinct runs, and
  every run must state each field in `fields` with the same value as the others. One run cut into
  pieces, such as a by-year table, is not a comparison and writes no record; a record that holds
  only one run's pieces fails.
- **`scorecard/believable`.** The study's README has a heading that holds "How believable is
  this?" with five numbered answers under it: the independent unit, how many were checked, what
  could be missed, whether the sources are independent, and what is unexplained.
- **`scorecard/explainer`.** The page is `results/explainer/index.html`, with one how-to-read
  box. A study with no page says `explainer: none` in its README, and why.
- **`live/off-by-default`.** Each switch names `files` (a path pattern), `pattern` (a regular
  expression read line by line, whose one capture group is the value) and `safe`. Every match in
  every selected file must hold the safe value. A file that holds another value fails, and says
  whether it was flipped from the main line or written that way, until the owner runs `themis grant
  live <file>` for that file. A selected file with no switch is refused, or skipped with `absent =
  "skip"`. A pattern that matches no file, or has other than one capture group, is refused.
- **`scorecard/rendering`.** It reads every Markdown page in a study with the core's reader, the
  one `docs/no-bare-dollar-pairs` uses: a sign in a code span, a fence, an HTML block or a link
  target is not prose, and a fence closes only as CommonMark says. A project that turns on the
  core rule for every page still keeps this one for its studies' chart sizes.
- **`scorecard/believable` and `scorecard/explainer`** bind every kind of study unless `kinds`
  names fewer, and a study whose kind cannot be read is always bound. Both honour `since`: a study
  whose seal reached the main line before that date is left alone.

## 6. The gate functions

A verdict is issued by a function. Three are built. Each reads the study's metrics and returns a
decision, a verdict, whether the evidence was enough, a reason in words, and every number it
computed.

| Gate | The question | What it must beat | A pass needs |
| --- | --- | --- | --- |
| `signal` | Do higher values of the signal come before higher values of what follows? | The same two lists with the signal rotated against the forward values, which keeps each list's own stickiness | A rank correlation above zero and above that noise floor, on samples that do not overlap, with the same sign in all but one block. A drift both lists share is taken out first |
| `entry` | Is an entry or exit better than a dumb entry? | Draws of a dumb entry on the same days, in the same window, on the same side | The trades pay on average after costs; each side pays when two sides are claimed; the mean sits in the top `alpha` of the dumb draws |
| `tune` | Did a tuned setting earn its confirmation? | Its own stages, in order | The search stayed inside its sealed budget; in-sample, out-of-sample and the walk back over untouched periods all passed; then the sealed window, once |
| `forward` | Is a live run holding up against its replay, week by week? | Its own sealed lines, read on a replay of the same dates | No risk line passed and no line past its stop, this week's lines inside their pass, every missed or extra entry for a known reason, and the sealed number of trades |

The decisions are `promote`, `kill` and `defer`. The tuning gate says `full-pass`, `kill` and
`not-confirmed`. Every gate follows the same order:

1. Missing or malformed inputs are a REFUSE. A gate never guesses.
2. Too small a sample is a REFUSE, whatever its numbers look like.
3. Economics first. A result that does not pay is a no before any significance is read.
4. A "no" from a test too weak to have seen the effect is a REFUSE, "defer", and not a kill.

Each gate is calibrated: it is fed data with nothing in it and data with a known effect, many
times, and the rates are measured. `themis calibrate` writes the receipt that
`decision/calibrated` asks for. Measured at this release:

| Gate | Says yes to noise (worst case) | Finds the planted effect |
| --- | --- | --- |
| `signal` | 6.2% | 98.3% |
| `entry` | 5.2% | 97.8% |
| `tune` | 0% | 100% |

The `tune` gate reads outcomes that are true or false, so its cases are a list of every way a run
can fall short, not random draws.

A study cannot loosen a gate through its own metrics. An `alpha` above 0.10 is refused. `entry`
needs 30 trades and 20 draws of the dumb entry; a study may ask for more trades, never for fewer.
`signal` needs samples worth 30 independent ones, so two sticky lists count for less than their
length.

## 7. Parameters

Everything here belongs to the project.

| Where | Parameter | Meaning |
| --- | --- | --- |
| `[trading]` | `work` | The folders that each hold one study: one glob, or a list of them. A study is named by its whole path, so two studies may share a folder name |
| `[trading.windows.<name>]` | `from`, `to` | The window's dates |
| | `sealed` | True for a window that opens only with a grant |
| | `looks` | How many signal looks the window allows; 1 when unset |
| `[trading.studies."<study>".windows.<name>]` | `from`, `to`, `sealed`, `looks` | A window of one study's own, keyed by the study's folder |
| A study's seal | `window-<name>` | A window of the study's own, as an inline table: `{from = "2025-01-01", to = "2025-12-31", sealed = true}` |
| `[trading.costs.<name>]` | `derivation` | Where the cost was measured. Any other key is the project's own |
| `[trading.tune]` | `confirm_model` | The most faithful model a confirming run can use |
| | `risk_rules`, `iterations` | Accepted, and read by no rule yet. Each `tune` study states its own in its seal, and `prereg/declared` checks them there |
| `trials/settings-counted` | `history`, `settings_column` | The run-history file in a study, and its column that names each run's settings |
| `trials/count-feeds-adjustment` | `penalty` | Extra trials added to the ledger's count |
| `validity/baselines` | `extra` | Further baseline lines the scorecard must carry |
| `validity/power-stated` | `min_power` | The least power a test must have had for its fail to stand |
| `validity/audit-reproduced` | `forbidden` | Modules no audit script may import |
| `validity/same-basis` | `fields` | The fingerprint fields every run in a comparison must share, such as `window`, `settings`, `cost_model` or `session` |
| `forward/sealed-before-start` | `margin_hours` | How many hours before the first live trade the seal must reach the main line; 0 when unset |
| `forward/same-dates-control` | `fields` | Further fingerprint fields the live week and its replay must both state, with one value |
| `forward/match` | `floor` | The lowest `pass` a seal may set for `match`; 0 when unset |
| `forward/gap-explained` | `tolerance` | How far, in money, the parts and the remainder may add up from live less replay; 0.01 when unset |
| `forward/enough-trades` | `min_trades` | The fewest trades a seal may ask for before any pass; 30 when unset |
| `forward/risk-line` | `required` | The risk ids every forward seal must draw a line for |
| `scorecard/explainer` | `max_bytes`, `max_controls` | The caps on the explainer page |
| `scorecard/believable`, `scorecard/explainer` | `kinds` | The kinds of study the rule binds; every kind when unset |
| `scorecard/rendering` | `max_chart_bytes` | The cap on one page or picture under `results/` |
| `live/off-by-default` | `switches` | Each live-trading switch: `files`, `pattern` with one capture group, and its `safe` value |
| | `absent` | `refuse` (the default: a selected file must hold the switch) or `skip` |

```toml
[trading.windows.train]
from = "2015-01-01"
to = "2021-12-31"

[trading.windows.holdout]
from = "2022-01-01"
to = "2024-12-31"
sealed = true
looks = 1

[trading.studies."research/experiments/2026-01-10_rsi".windows.oos-2025]
from = "2025-01-01"
to = "2025-12-31"
sealed = true

[trading.costs.example]
toll_per_side = 0.10
unit = "USD per unit"
derivation = "research/experiments/2026-01-10_cost-study"

[trading.tune]
risk_rules = "rules/prop.json"
iterations = 50
confirm_model = "real ticks"

[rules."validity/power-stated"]
level = "enforce"
min_power = 0.9

[rules."live/off-by-default"]
switches = [{files = "strategies/**/*.py", pattern = '^LIVE\s*=\s*(\w+)', safe = "False"}]

[rules."validity/same-basis"]
fields = ["window", "cost_model", "session"]
```

**Changing `[trading]`.** `config/no-silent-weakening` reads each key in its own direction. A new
window, study window, cost model or study folder adds a check, and needs no grant. A window's
`looks` raised above 1, `sealed` taken off, its dates moved, a cost model's figures changed or
added, `confirm_model` changed, or `iterations` raised is a weakening, and needs the owner's grant.

**A study's own windows.** A study reads the project's windows and its own. A window id names one
window wherever it is declared: studies that share an id give it the same dates, or
`prereg/declared` fails the second declaration, and `holdout/one-signal-look` counts their looks
together. So sibling studies on the same data share an id, and a study on other dates takes an id
of its own. A look is keyed by its study and its window, and so is the grant that opens it:
`themis grant holdout <study>/<window>`, and `themis act holdout <study>/<window>` needs a grant
for that exact target. A grant that names one of the project's windows alone opens it for one look
read through `data.window`, or through `themis act holdout <window>`, which records no study.

**The standard.** A project that sets `standard = "themis-trading/1"` under `[project]` says it
holds this floor. These are all at `enforce`: the order, prereg, trials, holdout and decision
rules, `ledger/complete`, every validity rule but `validity/confirm-on-real-ticks`,
`live/off-by-default`, `scorecard/complete`, `scorecard/believable`, `report/generated`,
`config/locked` and `config/no-silent-weakening`. A gate says yes to noise at most one time in ten and finds a
planted effect at least four times in five. `min_power` is at least 0.8, and
`live/off-by-default` refuses a file with no switch (`absent = "refuse"`).
`config/standard-floor` lists every place the project sits below it.

## 8. What a project's own code uses

The pack ships no adapter for any one engine or tester. It ships the pieces an adapter is made
of, in `themis.packs.trading`.

| Piece | What it does |
| --- | --- |
| `trades.from_rows(rows, mapping)` | Turns rows from any engine, whatever its columns are called, into standard trades |
| `trades.write_trades`, `trades.read_trades` | Write and read the standard trade table. A table that breaks the standard is refused, with the row and the reason |
| `data.window(root, manifest, name, grant=..., study=...)` | Hands over a window's dates. A sealed window needs an unused grant for it, and the look is written down first |
| `scorecard.compute`, `report.write_report` | What `themis report` calls |

The standard trade table has one row for each closed trade: `entry_time`, `exit_time`, `side`,
`size`, `entry_price`, `exit_price`, `costs` and `net`. It may also carry `bar_low` and
`bar_high`, the bar the trade was filled in, and `mfe` and `mae`, the best and worst moment of
the trade. One table means one scorecard, so a strategy from any engine can be laid beside any
other.

A look at sealed data goes like this. The owner runs `themis grant holdout <study>/<window>
--reason ...`. The study's code calls `data.window` with that grant and the study. The look record
and an action receipt are written, and only then are the dates returned. The same grant does not
open the window twice.

A look made by a program outside Python, such as an outside tester, goes through `themis act
holdout <study>/<window> -- <command>`. The pack writes the signal look before the command starts,
and the core writes the action receipt. The command can call `themis act --verify holdout
<study>/<window>` and refuse to run without it. A project that states its own `guarded` list for
`grant/required` keeps `holdout` in it.

## 9. The report

`themis report <study>` builds two files from the study's own files. Nothing on them is typed,
and the same inputs give the same files, byte for byte.

| Output | Content |
| --- | --- |
| `results/scorecard.csv` | 31 fixed lines in six groups |
| `results/report.html` | The stake in four figures, a warnings box that lists every line marked NOT RUN, four charts each with a "how to read this" box, the scorecard table, and whether a second script checked the numbers |

The six groups: did it make money after costs; does each trade pay; how bumpy was the ride; was
it a few lucky trades; is it real skill; what exactly was tested.

The trades come from the trade table. What the trades cannot show is read from the `scorecard`
table of the metrics file:

| Key | Meaning | When it is left out |
| --- | --- | --- |
| `start_capital` | The money the test began with | The report is refused, when trades were booked |
| `baselines` | The ending money of `always_long` and `always_short` | Those lines are NOT RUN |
| `oos_start` | The first moment of data the idea had never seen | That line is NOT RUN |
| `trial_sharpes` | The per-trade Sharpe ratio of every idea tried | That line is NOT RUN |
| `sensitivity` | The ending money of neighbouring settings | That line is NOT RUN |

A key that is not in this table is refused, so a spelling mistake never becomes a blank line. A
line of real skill left NOT RUN fails `scorecard/complete` unless the seal gives a
`not_run_reason`.

The page holds no script and no outside file; every chart is drawn into the page. It carries a
digest of the trade table, the metrics and the audit, and `report/generated` compares that digest
with the files. A page left behind by a later run is caught.

Every money figure is framed as a stake: starting money, ending money, the deepest drop and the
costs paid. Each label's tip gives an example on a stake of 100. The scorecard measures; it
issues no verdict.

## 10. Proofs

Every rule has cases that pass, fail and refuse, and `themis prove` runs them. A few:

| Rule | The plant | Must give |
| --- | --- | --- |
| `validity/fills-on-tape` | Book one fill above its bar's high | FAIL |
| `holdout/guarded` | Read a sealed window with no grant | FAIL |
| `trials/settings-counted` | Add a run with new settings and no trial | FAIL |
| `validity/power-stated` | Record a kill with no power statement | FAIL |
| `validity/audit-reproduced` | Name the study's own run script as its audit | FAIL |
| `validity/same-basis` | Rank two runs from two different sessions side by side | FAIL |
| `live/off-by-default` | Flip a live-trading switch on a branch with no grant | FAIL |
| `scorecard/rendering` | Two prices on one line, after a shorter fence inside a long one | FAIL |
| A gate function | Feed it noise; feed it a planted edge | It says no; it says yes |

## 11. What this pack cannot do

- **It does not say a strategy makes money.** It says the claim followed the standard.
- **It cannot see a belief.** What someone learned during a look at sealed data is invisible.
- **It cannot make data independent.** It reports the independent unit; it cannot enlarge it.
- **The cost model is the project's.** A wrong cost gives a wrong net number, faithfully.
- **It does not rebuild a gate's inputs.** The numbers a gate reads are written by the study's
  own run. They are held by the provenance file and by the separate audit, not recomputed by
  Themis.
- **The `signal` gate cannot tell a real link from a shape both lists share.** It takes out a
  steady drift, and no more. In a check at this release, two lists that shared a V shape and
  nothing else passed 36 times in 100. A cycle both lists share can pass too. The seal's own
  `nulls` are where a project guards against that.
- **The `signal` gate has no cost input.** For it, "economics first" means only that the
  correlation is above zero.
- **It cannot stop code that reads sealed data another way.** `data.window` guards the dates it
  hands over. Code that opens the files itself leaves no look.

Not built yet:

- A gate for a regime or volatility tag, and a gate for sizing.
- A scorecard of its own for a `signal` study. Today a signal study with no trade table gets the
  same scorecard, and its trade lines say that no trade was booked.
- An adapter for any one tester's report, and one that turns a run history into trial records.
- A builder for the explainer page, and a static picture of the main chart.
- A record of which level a verdict was tested at: the idea alone, or as one part of a larger
  strategy.
- A lookup of similar killed trials when a new one is logged.

## 12. Where the rules come from

Each rule exists because of an incident in a real project: fills at prices that never traded, a
parameter grid that ran unlogged, sealed data read by agents whose prompts never mentioned the
seal, a merge that joined a seal to its results, a study that stopped reproducing itself, a kill
issued by a test with too little power, tuned settings that passed both test windows and then
lost on unseen years, two runs ranked against each other on costs from different days, and a
strategy whose source turned live trading on by default.
