# The marketing content pack

> Design 0.2 — 2026-11-16. Status: **proposed**. Standard id: `themis-marketing/1`. Nothing in
> this pack is built.

**In one line:** this pack teaches Themis what evidence means in marketing content. A fact has a
dated source. A spend has a tool's receipt. A publish has the owner's grant. What to make next is
decided by the numbers, not by the agent.

It serves any pipeline in which agents research, write, make and measure content, and an owner
approves at fixed points. It names no platform, language, product category, tool or project.
Those are parameters, rulebooks and adapters.

## 1. The same laws, for content

The core's laws are about claims, evidence, order and approval. None of them is about a market.
Each has a plain meaning in content work.

| Law | In content work |
| --- | --- |
| 1. A rule is code | A content rule is a checker, not a sentence in an agent's instructions |
| 2. No number without a receipt | A fact cites a dated page. A cost cites the tool that reported it. |
| 3. The numbers issue the decision | Results decide which series leads, is kept or is retired |
| 4. Three verdicts | "Too few items to judge" is an answer, and it is not "no" |
| 5. Order is evidence | The brief is approved before pictures are made; the grant comes before the post |
| 6. Every guard can say no | Each rule is shown a planted violation and must catch it |
| 7. One home per fact | One product table, one rulebook; everything else points there |
| 8. Written for a newcomer | The owner's pages stay short and explain themselves |

## 2. What the pack adds to the core

The core supplies the primitives ([DESIGN.md](../../DESIGN.md), section 5). This pack gives them
their content meaning.

| Core primitive | In this pack |
| --- | --- |
| Ledger | Every content **item**, from the moment its topic is taken up |
| Order | The **brief** is the seal; assets, renders and posts are results |
| Decision | The **results gate**: lead, keep, retire, or too few |
| Grant | The owner's choice of **plan**; a **spend** up to a ceiling; a **publish** |
| Attestation | A check that needs eyes: the owner on footage; a second reader on a quoted source |
| Scope | Each agent **role** and the paths it may change |
| Receipt | Each paid job's **spend**; each agent **run** |
| Report | The **loop report**: what was made, estimate against spend, lessons |

## 3. Kinds of work

| Kind | What it is | Must ship |
| --- | --- | --- |
| `content` | One item to publish, with a declared purpose | A brief, its evidence, its checklist, its assets, a result once published |
| `research` | Topic or product research. It scores and ranks; it publishes nothing. | Evidence rows only |
| `asset` | A reusable design, such as a character sheet or a visual style | The asset, its provenance, the owner's attestation |

**Purposes are configured.** A project declares its purposes, and for each one the goal number it
is judged on. An item is sealed with one purpose and judged on that purpose's number.

## 4. Records

| Record | Holds |
| --- | --- |
| Evidence | The finding, its tier, the page's own date, the date it was retrieved, the link, the quoted passage |
| Rulebook entry | One platform or legal rule, its source page, the date it was read, the checks that rest on it |
| Series | The audience, the format, the purpose, its status, and what it changed from the series it is compared with |
| Brief | The sealed plan of one item: purpose, goal number, structure, lines, evidence ids, checklist |
| Asset | One picture, clip or voice track: the tool, the prompt's hash, the seed, the references, the cost, the take |
| Spend | An amount, its unit, the tool that reported it, the job, the time |
| Agent run | The role, the model, the cost, what it produced, the hash of the rules it read |
| Post | The item, where and when it was published, and its disclosure settings |
| Result | An item's numbers at the agreed age, and where they came from |

## 5. The lifecycle

```text
 topic ─► evidence ─► options ─►[plan]─► brief ─►[review]─► assets ─►[review]─► render
                                                                                  │
 next topic ◄─ decision ◄─ results ◄─ post ◄─[publish]◄─[review]◄─────────────────┘

 [ ] = the owner's yes, held as a grant or an attestation
```

| Step | What it produces | It refuses when |
| --- | --- | --- |
| Topic | A ledger record for the item, with its purpose | — |
| Evidence | Evidence rows | A row has no source, or its page was not opened in this run |
| Options | Plans to choose from, each with its evidence ids and its cost | An option cites no evidence; a cost is not a tool's figure |
| Brief | The sealed plan | Evidence is stale; a forbidden term; an audience or format the project has not declared |
| Assets and render | Pictures, clips, voice, the finished item, a check of each part | The plan differs from the brief; the priced plan passes its ceiling |
| Post | A post record | No publish grant; an open checklist row; a stale rulebook |
| Results | A result for every published item | An item is younger than the agreed age; a published item is missing |
| Decision | The gate's answer for each series | Too few items with results |

## 6. The pack's rules

Twenty-three rules in five gates, beside the core's.

### Gate: evidence — content says only what a source says

| Rule | The promise | Parameters |
| --- | --- | --- |
| `evidence/sourced` | Every factual line cites an evidence id. Every evidence row has a source. | Which lines count as factual |
| `evidence/fresh` | Evidence is inside its window, by the date it was retrieved and by the page's own date. | The windows, by tier and by topic |
| `evidence/tier` | A claim of a guarded kind rests on a source of a required tier. A search snippet never carries a claim alone. | The tiers; which kinds of claim need which |
| `evidence/quoted` | The row holds the passage it rests on. The line says no more than the passage, and a second reader attests it. | — |
| `evidence/reachable` | The source still opens. A page that does not load is a REFUSE, never a guess. | How often links are re-checked |

### Gate: compliance — the content breaks no platform or legal rule

| Rule | The promise | Parameters |
| --- | --- | --- |
| `compliance/banned-terms` | No forbidden term or pattern, in any text or spoken line. | The term list |
| `compliance/source-facts` | Product wording, price and link come only from the product record. | The product table |
| `compliance/forbidden-content` | Nothing shown or said is of a kind the rulebook forbids. Text is checked by pattern; pictures by an attested check. | The rulebook |
| `compliance/disclosure` | The disclosure flags follow the way the item was made, and the post record shows them set. | The disclosure rules |
| `compliance/checklist` | Every item carries the full checklist for its kind and purpose. A row is ticked only by its judge. | The checklists |
| `compliance/rulebook-dated` | Each rule cites its page and the date it was read. A rulebook past its window blocks publishing. | The rulebook's window |

### Gate: consistency — what is made matches what was approved

| Rule | The promise | Parameters |
| --- | --- | --- |
| `consistency/derived-matches` | Each plan derived from the brief equals the brief: parts, times, text, length. | — |
| `consistency/assets-from-kit` | Every asset used is an approved asset of the item's series. | The kits |
| `consistency/timing-fits` | Each spoken line fits its part's time before any paid job is priced. | The speaking rate |
| `consistency/rulebook-pinned` | Rule data held inside a checker equals its reference page. | — |

### Gate: spend — every cost is a tool's figure, inside a budget

| Rule | The promise | Parameters |
| --- | --- | --- |
| `spend/priced-first` | No paid job is sent before its plan is priced and under its ceiling. | The ceilings, by run and by period |
| `spend/figures-from-tools` | Every cost in a document equals a spend record. | The unit |
| `spend/estimate-calibrated` | An estimate shown to the owner carries the measured overrun of past work. | How many past loops to average |
| `spend/agent-runs` | Each agent run records its cost and what it produced. A run that produced nothing is flagged. | — |

### Gate: results — the numbers are complete and fairly compared

| Rule | The promise | Parameters |
| --- | --- | --- |
| `results/recorded` | Each result is a record with its source, read at the agreed age or later. | The age; the metrics |
| `results/purpose-sealed` | An item is judged on the goal number of the purpose it was sealed with. | The purposes and their goal numbers |
| `results/own-baseline` | An item is compared only with the baseline the project declared. | The baseline |
| `results/one-change` | A new series changes one thing from the series it is compared with. | What counts as one thing |

One more rule ships at `warn` only: `results/noise-band`. It calls a difference between two
series real only when it is larger than the spread among each series' own items.

### Core rules this pack relies on

| Core rule | What this pack configures |
| --- | --- |
| `grant/required`, `grant/ceiling` | Guarded actions: choosing a plan, spending, publishing |
| `attest/by-judge`, `attest/bound` | Each checklist row's judge; each visual check tied to the file's hash |
| `scope/paths`, `scope/rules-current` | Each agent role's paths; the rule files a run must have read |
| `ledger/complete` | Every published item has a result or a stated reason |
| `decision/issued-by-gate`, `decision/enough-evidence` | The results gate and its minimum number of items |

## 7. Rulebooks and checklists are data

Platform and legal rules change, and they differ by platform and by country. So the pack ships
none. A project supplies them as files, and the pack checks they are used.

| A rulebook entry has | Why |
| --- | --- |
| An id and a one-line check | So a checklist row can point at it |
| A pass condition | So the judge knows what "done" means |
| A judge: the agent, the owner, or a tool | So `attest/by-judge` can hold |
| What it is judged from: the script, the footage, the published post | So a row is ticked at the right moment |
| A source link and the date it was read | So `compliance/rulebook-dated` can hold |

A checklist is a list of rulebook entries that applies to a kind and a purpose. An item's own
checklist must repeat those entries exactly. A project can therefore hold several checklists, for
example one for items that sell and one for items that do not.

## 8. The results gate

The gate turns Result records into a decision. Its decision types are fixed; its numbers are the
project's.

| Decision | Meaning | Verdict |
| --- | --- | --- |
| Too few | Not enough items with results to say anything | REFUSE |
| Lead | Of two series with enough items, the one higher on the goal number | PASS |
| Keep | Lower on the goal number, higher on a declared second number | PASS |
| Retire | Enough items, and lower on every declared number | FAIL |
| Standout | One item far above the baseline | PASS |

```toml
[marketing.results]
min_age_days = 7                 # a result is read no earlier than this
min_items_to_judge = 3           # below this the decision is "too few"
min_items_to_rank = 6            # needed to lead or retire a series
baseline = "own-median"          # never an outside benchmark
second_number = "shares_and_saves_per_thousand_views"

[marketing.results.retire]
views_below_share_of_baseline = 0.7

[marketing.results.standout]
views_times_baseline = 5
```

Three things follow from making this a function:

- **The thresholds are sealed.** They sit in the manifest. Loosening one is a weakening, and
  needs the owner's grant and a reason.
- **The owner can still overrule.** An owner's decision is recorded as the owner's, so nobody
  later mistakes it for what the numbers said.
- **The agent cannot round up.** It receives the decision with the numbers behind it. A brief
  that says a series is working must cite that decision.

A project that needs a decision type the pack does not have writes it in a local pack.

## 9. Parameters

Everything here belongs to the project.

| Parameter | Example |
| --- | --- |
| Evidence tiers, and which claims need which | `official`, `third-party`, `vendor`; a health claim needs `official` |
| Freshness windows | Thirty days since retrieval; ninety days for a trend page's own date |
| The term list, the product table, the rulebooks, the checklists | Files in the project |
| Purposes and their goal numbers | A purpose named `growth`, judged on new followers for each thousand views |
| The result metrics and the age they are read at | Views, follows, shares, saves; seven days |
| Spend units and ceilings | Credits; a ceiling for one run and for one week |
| Agent roles and their paths | A writer may change scripts and nothing else |
| The results gate's numbers | Section 8 |

```toml
[project]
packs = ["marketing"]
standard = "themis-marketing/1"

[marketing.evidence]
max_age_days = 30
page_max_age_days = { trend = 90 }
tiers = ["official", "third-party", "vendor"]
require = { health = ["official"] }

[marketing.rulebooks.selling]
file = "rules/selling-checklist.md"
max_age_days = 60
applies_to = { kind = "content", purpose = ["sales"] }

[marketing.purposes.growth]
goal = "new_followers_per_thousand_views"

[marketing.spend]
unit = "credits"
run_ceiling = 10000

[roles.writer]
paths = ["content/scripts/**"]
```

## 10. Adapters

| Adapter | Reads | Into |
| --- | --- | --- |
| Tool notes | The note a generation tool writes beside each file it makes | Asset and Spend records |
| Results | A platform export, a CSV, or lines the owner enters | Result records |
| Web evidence | A fetched page, with the passage that was quoted | Evidence records |
| Agent runs | An agent tool's run log | Agent run records |

An adapter validates before it trusts, refuses what it cannot read, and never guesses a missing
value. A reader for one tool's own format is written once, in the pack or in a local pack.

## 11. Proofs

| Rule | The plant | Must fail |
| --- | --- | --- |
| `compliance/banned-terms` | Add a forbidden term to one spoken line | That rule, at that line |
| `evidence/fresh` | Move one evidence row's date back past the window | That rule |
| `consistency/derived-matches` | Change one part's end time in a derived plan | That rule |
| `spend/priced-first` | Price a plan above its ceiling | That rule |
| `scope/paths` | Change a checker on a writer's branch | That core rule |
| `grant/required` | Record a post with no publish grant | That core rule |
| The results gate | Ask it to retire a series with too few items; feed it shuffled results | REFUSE; "no difference" |

## 12. What this pack cannot do

- **It cannot judge taste.** Whether an item is good stays with the owner's reviews.
- **It cannot prove a fact is true.** It proves the line cites a source of the right tier, quotes
  it, and that a second reader agreed it says no more.
- **It cannot see inside a platform.** Whether a setting is really on is the owner's attestation
  until an interface reports it.
- **It cannot see inside an agent tool.** It sees what reaches the repository or a record.
- **A model looking at a picture is evidence, not proof.** A visual check stays an attestation.
- **Small numbers stay small.** The gate can say "too few" honestly. It cannot make a week of
  results mean more than they do.

## 13. Where the rules come from

Each rule exists because of an incident in a real content pipeline run by agents: an approval
pressed by mistake that started a paid job, a generated clip that showed a result the advertising
rules forbid, an estimate that fell a quarter short of the spend, a cost fact that was wrong in
the owner's own pages, an agent run that cost money and produced nothing, and decision thresholds
that existed only as instructions to the agent who would be judged by them.
