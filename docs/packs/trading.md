# The trading pack

> Design 0.2 — 2026-11-16. Status: **proposed**. Standard id: `themis-trading/1`. Nothing in
> this pack is built.

**In one line:** this pack teaches Themis what evidence means in trading research. A trial is
counted before it runs, the plan is sealed before the answer is known, unseen data is looked at
once, and a gate function, not a person, says whether an edge is there.

It serves any project that tests trading ideas: research on historical data, strategy backtests,
and the tuning of a strategy's settings in an outside tester. It names no instrument, venue,
engine or project. Those are parameters and adapters.

## 1. What the pack adds to the core

The core supplies the primitives ([DESIGN.md](../../DESIGN.md), section 5). This pack gives them
their trading meaning.

| Core primitive | In this pack |
| --- | --- |
| Ledger | A **trial**: any variant, event definition, parameter sweep or peek at a subset |
| Order | The **pre-registration** is the seal; everything under `results/` is a result |
| Decision | A **verdict**, issued by a gate function matched to the idea's role |
| Grant | One look at a **sealed window** of data |
| Attestation | The independent **audit**; the owner's sign-off on a seal |
| Receipt | The **provenance** fingerprint; the **calibration** of each gate |
| Report | The **scorecard** |

## 2. Kinds of work

A pre-registration declares its kind. Each kind has its own required outputs.

| Kind | What it does | Must ship |
| --- | --- | --- |
| `strategy` | Books trades | The strategy scorecard, the report, an audit |
| `signal` | Predicts, and books no trades | The signal scorecard, the report, an audit |
| `data` | Describes; selects nothing | Charts with "how to read" boxes. It costs no trial. |
| `tune` | Searches a strategy's settings | The search is sealed: windows, ranges, risk rules, iteration budget. Every setting tried is a trial. One look at unseen data at the end. |

A `data` study that scans a subset or picks a "best" value in order to trade it has become a
trial, and must be logged as one.

## 3. Records

| Record | Holds |
| --- | --- |
| Trial | The question, the role, the number of variants, the data window, its state |
| Pre-registration | Kind, the binding clause, the gate, the nulls, the windows, the smallest effect worth seeing |
| Provenance | Hashes of every input and of the code, the commit, the clean-tree flag, the versions, the seed |
| Metrics | Named numbers with units: the only numbers anyone may quote |
| Audit | Its status, its script, who wrote it, what that writer was shown |
| Verdict | The decision, its level, the gate's id and version, the date |
| Look | The window, its kind (signal or pipeline), its scope and purpose, its grant |
| Method | A check adopted, the trap it closes, and which roles' verdicts it could flip |

**A verdict names its level.** A killed standalone strategy is not a dead idea. The record says
which was tested: the idea on its own, the idea as one ingredient of a larger strategy, or the
idea under different handling. Claiming "it is only an ingredient" needs that ingredient's own
sealed test.

## 4. The lifecycle

| Step | Here it is | It refuses when |
| --- | --- | --- |
| Log | A trial record, before anything runs | Similar killed trials were not looked up |
| Seal | The pre-registration, merged on its own | A field its kind requires is missing |
| Do | The run, with its provenance | The seal is not on the main line; the tree is dirty; the gate is not calibrated; a sealed window has no grant |
| Check | A second script reproduces the headline numbers | The audit shares code with the study |
| Decide | The verdict, from the sealed gate | A kill has no power statement |
| Report | The scorecard and its report | A required check on the scorecard was not run and the seal does not say why |
| Hand off | The checkpoint | — |

## 5. The pack's rules

Seventeen rules in five gates, beside the core's.

### Gate: trials — attempts are counted honestly

| Rule | The promise | Parameters |
| --- | --- | --- |
| `trials/settings-counted` | Each new settings version in the run history is a counted trial. | — |
| `trials/count-feeds-adjustment` | The luck-adjusted Sharpe ratio uses the ledger's own cumulative count. | A penalty for unlogged researcher choices |

### Gate: prereg — the plan is complete

| Rule | The promise | Parameters |
| --- | --- | --- |
| `prereg/declared` | The seal names its kind, binding clause, gate, nulls, windows and smallest effect worth seeing. | Required fields for each kind |
| `prereg/provenance` | Every result carries a fingerprint taken on a clean tree. | — |

### Gate: holdout — unseen data is looked at once

| Rule | The promise | Parameters |
| --- | --- | --- |
| `holdout/guarded` | A window marked sealed cannot be read without a grant. | The windows and which are sealed |
| `holdout/one-signal-look` | Each sealed window has at most one signal look. | Looks allowed for each window |
| `holdout/pipeline-look-declared` | A look that only proves the code works states its scope, its purpose and what it was compared against, and computes no forward return. | — |

### Gate: validity — the statistics can be trusted

| Rule | The promise | Parameters |
| --- | --- | --- |
| `validity/fills-on-tape` | Every simulated fill sits between its bar's low and high. | — |
| `validity/baselines` | The scorecard carries the always-long and always-short baselines. | Extra baselines |
| `validity/net-of-cost` | The binding number is net of a cost that cites how it was derived. | The cost model of each instrument |
| `validity/power-stated` | A kill states the smallest effect the test could have seen. An underpowered fail is recorded as "defer". | The power required |
| `validity/audit-reproduced` | A number is quoted only after a separate script reproduces it. | Which numbers, by the size of the decision |
| `validity/confirm-on-real-ticks` | For `tune`, the confirming run uses the tester's most faithful model. | The tester model |

### Gate: scorecard — a result a newcomer can read

| Rule | The promise | Parameters |
| --- | --- | --- |
| `scorecard/complete` | A `strategy` or `signal` study ships its scorecard with no unexplained "not run" line. | — |
| `scorecard/believable` | Five questions are answered: the independent unit, how many were checked, what could be missed, whether the sources are independent, what is unexplained. | — |
| `scorecard/explainer` | One short interactive page, within fixed caps, or a stated reason for none. | The caps |
| `scorecard/rendering` | No text element holds two bare dollar signs. No chart file passes its size cap. | The size cap |

## 6. The gate functions

A verdict is issued by a function chosen for the idea's **role**.

| Role | What it must beat | The bar for a pass |
| --- | --- | --- |
| Direction | A null that keeps the signal's own stickiness; always-long and always-short | Above its own noise floor on non-overlapping samples, stable by period, both sides pay, net of cost |
| Regime or volatility tag | A stack of simple estimators that spans the rival explanation; a placebo | Adds information beyond the stack, across neighbouring horizons |
| Entry or exit timing | A dumb entry on the same day, in the same window, on the same side | Both sides pay alone; barriers scored by which is touched first; every fill on tape |
| Sizing | Constant exposure of the same average size; random vetoes | Every binding clause holds in both windows |
| Tuning | In-sample, out-of-sample, a replay on every untouched period, then the sealed window once | A full pass under the project's risk rules |

Every gate obeys the core's three decision rules:

- **Calibrated.** It holds a receipt showing its false-alarm rate on noise and its power on a
  planted effect, as measured rates, not single draws.
- **Enough evidence.** A fail with too little power is a REFUSE: "underpowered — defer".
- **Issued, not typed.** The stored verdict must equal what the gate returns on the metrics.

## 7. Parameters

Everything in this table belongs to the project. Nothing here is a default built into the pack
unless the standard sets a floor for it.

| Parameter | Example |
| --- | --- |
| Data windows, and which are sealed | `train`, `test`, a sealed `holdout` with one look |
| The cost model of each instrument, with its derivation | A per-side toll and a carry rate, citing the study that measured them |
| Horizons and the stop grid | Fixed horizons; three stop sizes |
| The smallest effect worth seeing, for each role | Set in the seal, never after the run |
| The minimum number of independent blocks | For a bootstrap to mean anything |
| Risk rules for a `tune` | A daily loss limit, a total loss limit, a minimum number of trades |
| The iteration budget for a `tune` | How many settings may be tried |
| Which numbers an audit must reproduce | The headline table for a kill; every number for a promotion |

```toml
[trading.windows.train]
from = "2015-01-01"
to = "2021-12-31"

[trading.windows.holdout]
from = "2022-01-01"
to = "2024-12-31"
sealed = true
looks = 1

[trading.costs.example]
toll_per_side = 0.10
unit = "USD per unit"
derivation = "research/experiments/2026-01-10_cost-study"

[trading.tune]
risk_rules = "rules/prop.json"
iterations = 50
confirm_model = "real ticks"
```

## 8. Adapters

| Adapter | Reads | Into |
| --- | --- | --- |
| Frames | Bar and trade tables in memory | The standard trade table |
| Trade list | A CSV or JSON list of closed trades from any engine | The standard trade table |
| MetaTrader 5 tester | The tester's report and its deals | The standard trade table and the run's settings |
| Run history | A log of settings tried | Trial records |

The standard trade table has one row for each closed trade: entry and exit time and price, side,
size, costs, net result, and the low and high of the bar it was filled in. One table means one
scorecard, so a strategy from any engine can be laid beside any other.

## 9. The report

| Output | Content |
| --- | --- |
| `report.html` | Warnings, the charts with their "how to read" boxes, the scorecard table, the run history |
| `scorecard.csv` | 26 fixed lines for a strategy; the five measurements for a signal |
| `headline.png` | A static picture of the main chart, read back before the verdict |
| `explainer/index.html` | One idea, one box, one question, at most two controls |

The strategy scorecard's six groups: did it make money after costs; does each trade pay; how
bumpy was the ride; was it a few lucky trades; is it real skill; what exactly was tested.

The five measurements of a signal: forward return at fixed horizons; the average path; a grid of
stop sizes; the best and worst moves inside each trade; and how well the signal ranks what
follows.

Every money figure is framed as a stake: starting capital, ending equity, drawdown and costs
paid. Every tooltip carries a `$100` example. The scorecard measures; it issues no verdict.

## 10. Proofs

| Rule | The plant | Must fail |
| --- | --- | --- |
| `validity/fills-on-tape` | Book one fill above its bar's high | That rule |
| `holdout/guarded` | Read a sealed window with no grant | That rule |
| `trials/settings-counted` | Add a run with new settings and no trial | That rule |
| `validity/power-stated` | Record a kill with no power statement | REFUSE, "defer" |
| A gate function | Feed it noise; feed it a planted edge | It says no; it says yes |

## 11. What this pack cannot do

- **It does not say a strategy makes money.** It says the claim followed the standard.
- **It cannot see a belief.** What someone learned during a look at sealed data is invisible.
- **It cannot make data independent.** It reports the independent unit; it cannot enlarge it.
- **The cost model is the project's.** A wrong cost gives a wrong net number, faithfully.

## 12. Where the rules come from

Each rule exists because of an incident in a real project: fills at prices that never traded, a
parameter grid that ran unlogged, sealed data read by agents whose prompts never mentioned the
seal, a merge that joined a seal to its results, a study that stopped reproducing itself, a kill
issued by a test with too little power, and tuned settings that passed both test windows and then
lost on unseen years.
