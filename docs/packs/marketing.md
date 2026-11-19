# The marketing content pack

> 2026-11-16. Status: **built**: twenty-seven rules in six gates. Standard id:
> `themis-marketing/1`. This page says what the code does today. What was designed and is not
> built is listed in section 12.

**In one line:** this pack teaches Themis what evidence means in marketing content. A fact has a
dated source. A spend has a tool's receipt. A publish has the owner's grant. Which series leads,
is kept or is retired is decided by the numbers, not by the agent.

It serves any pipeline in which agents research, write, make and measure content, and an owner
says yes before an item goes out. It names no platform, language, product category, tool or
project. Those are parameters, rulebooks and the project's own code. The pack itself posts
nothing, opens no page and calls no tool. It reads the files and the receipts a project keeps.

## 1. The same laws, for content

The core's laws are about claims, evidence, order and approval. None of them is about a market.
Each has a plain meaning in content work.

| Law | In content work |
| --- | --- |
| 1. A rule is code | A content rule is a checker, not a sentence in an agent's instructions |
| 2. No number without a receipt | A fact cites a dated source. A cost is the sum of the receipts its tools wrote. |
| 3. The numbers issue the decision | Results decide which series leads, is kept or is retired |
| 4. Three verdicts | "Too few items to judge" is an answer, and it is not "no" |
| 5. Order is evidence | The brief reaches the main line before any asset, render or post; the grant comes before the post |
| 6. Every guard can say no | Each rule is shown a planted violation and must catch it |
| 7. One home per fact | One product table, one file for each rulebook; a checklist repeats its rulebook |
| 8. Written for a newcomer | The report page says how to read it |

## 2. What the pack adds to the core

The core supplies the primitives ([DESIGN.md](../../DESIGN.md), section 5). This pack gives some
of them a content meaning.

| Core primitive | In this pack |
| --- | --- |
| Ledger | Nothing of its own. `themis new` logs an item in the core's ledger. |
| Order | The **brief** is the seal; assets, renders and the post are results |
| Decision | The **results gate**: lead, keep, retire, standout, or too few |
| Grant | The owner's yes to **publish** one item |
| Attestation | A check that needs eyes: the owner on what was made; a second reader on the quoted passages; the judge of each ticked checklist row |
| Scope | Nothing of its own. A project declares its agent roles in the core's `[roles]` table. |
| Receipt | Each paid job's **spend**; each agent **run**; a **link check**, when the project keeps one |
| Report | The **loop report**: each item's estimate against its spend, the measured overrun, the agent runs that produced nothing |

## 3. Kinds of work

A brief names its kind. There are three.

| Kind | What it is | What the rules ask of it |
| --- | --- | --- |
| `content` | One item to publish | A checklist, and a brief that says how the item is made. Once posted: the owner's grant, a closed checklist and a result. |
| `research` | Topic or product research. It publishes nothing. | No checklist. The rules that read a brief, its evidence and its asset notes still apply. |
| `asset` | A reusable design, such as a character sheet or a visual style | The same as `research` |

**Purposes are configured.** A project declares its purposes, and for each one the goal number it
is judged on. An item is sealed with one purpose and judged on that purpose's number.

## 4. Records

One item is one folder. `work` under `[marketing]` says where the item folders are. An item's
files are TOML, each with a fixed schema. A file that does not match its schema is a REFUSE: a
required field left out, a wrong type, or a key the schema does not know.

| Record | File | Holds |
| --- | --- | --- |
| Brief | `<item>/brief.toml` | The sealed plan: `kind` and `title`, which are required; the purpose, series, audience, format and length; the parts, each with its times, on-screen text and spoken line; the claims, each with its text, its evidence id and its kind; the product; how the item is made; the disclosure flags; the caption |
| Evidence | `<item>/evidence.toml` | Rows. Each holds its id, the finding, its tier, its source and the date it was retrieved. It may hold the page's own date, the quoted passage and a topic. |
| Checklist | `<item>/checklist.toml` | The rulebook's name, and rows: id, check, judge, what the row is judged from, and whether it is ticked |
| Plan | `<item>/plan.toml` | The parts, as in the brief; the length; the estimate and its unit; the speaking rate |
| Asset note | `<item>/assets/*.toml` | One picture, clip or voice track: the tool, which is required; the kit item it was made from; the prompt's hash, the seed, the take, the file. Any other key is allowed. |
| Post | `<item>/post.toml` | Where and when the item was published, the grant it went out on, its disclosure settings, its address |
| Result | `<item>/result.toml` | The date the numbers were read, the item's age in days on that date, where they came from, and the metrics |
| Rulebook | A file the manifest names | Entries: one platform or legal rule each (section 7) |
| Series | `series/<name>.toml` | The audience, the format, the purpose, its status, its kit, the series it is compared with and what it changed |
| Spend receipt | `receipts/spend/<name>.json` | The item, the amount and the tool, which are required; the unit, the job, the time |
| Agent-run receipt | `receipts/agent-run/<name>.json` | One agent run: the role, the time, the cost, what it produced, and a flag with its reason |
| Decision | `decisions/<series>.json` | What the results gate said about a series, beside the inputs it read (section 8) |

A receipt is JSON. It may sit in `receipts/`, which is committed, or in `.themis/receipts/`,
which is not. A committed copy of a local receipt is counted once. An asset note may state a
cost, and no rule reads it: spend is counted from the receipts.

## 5. The lifecycle

```text
 evidence ─► brief ─► plan ─► assets ─►[look]─► checklist ─►[publish]─► post
                                                                         │
 next item ◄─ decision ◄─ result ◄───────────────────────────────────────┘

 [look]    = an attestation that what was made shows nothing forbidden
 [publish] = the owner's grant for this one item
```

| Step | What it leaves | A rule fails when |
| --- | --- | --- |
| Evidence | `evidence.toml` | A claim cites a row the item does not hold, or a row names no source. A source is not an address. The newest link check says a source no longer opens. |
| Brief | `brief.toml`, the seal | Evidence is stale, or of the wrong tier. A cited row has no quote, or no second reader attested. A forbidden term, or text of a forbidden kind. A price or a link that is not the product record's. Generated work with its disclosure flag unset. No checklist. A spoken line too long for its part. |
| Plan | `plan.toml`, with its estimate | The plan differs from the brief. The estimate is above the run ceiling. Past work overran, and the estimate is shown without the measured overrun. |
| Assets | Asset notes, files under `assets/` and `render/`, spend receipts | There is spend and no priced plan, or spend above the ceiling. An asset is not from the series' kit. Nobody attested what was made. An asset, a render or the post reached the main line with the brief or before it. |
| Post | `post.toml` | No grant for this item, or a grant made after the post. A checklist row that is judged before the post is still open. The post's disclosure flag differs from the brief's. |
| Result | `result.toml` | The result was read before the agreed age, or names no source. A posted item still has no result at twice the agreed age. The purpose's goal number is missing. |
| Decision | `decisions/<series>.json` | The stored decision is not the gate's, or its inputs are not the records. Too few items with results is a REFUSE, not a failure. |
| Report | `<item>/report.md`, `reports/<series>.md` | A cost on the page differs from the spend receipts |

The rules read order from history in one place only. The brief reaches the main line in an
earlier merge than any asset, render or post, and after that it changes only through an
amendment record. Beyond that, `publish/granted` compares two times: the grant's and the post's.

### The loop report

`themis report <item>` writes `<item>/report.md`. When the item's brief names a series, it also
writes `reports/<series>.md`, with one row for every item of that series.

| The page shows | Read from |
| --- | --- |
| One row for each item: title, purpose, estimate, spend, difference | The brief, the plan, the spend receipts |
| A total row | The same |
| The measured overrun: spend divided by estimate, over the items that have both | The same |
| How many agent runs are recorded, and each one that produced nothing | Every receipt under `receipts/agent-run/` |
| Each record that could not be read, which is then not counted | — |

Nothing on the page is typed, so building it again from the same records gives the same page.
Each spend is written with its cost tag, and the pack points `spend/figures-from-tools` at these
pages. A receipt added later makes the page fail that rule until the report is built again.

## 6. The pack's rules

Twenty-seven rules in six gates, beside the core's. Every rule starts at `warn`; a project raises
it to `enforce`. A rule that lacks a setting it needs says `not configured` and does not run.
Most rules need `work` under `[marketing]`. Section 9 lists every parameter with its default.

### Gate: evidence — content says only what a source says

| Rule | The promise | Parameters |
| --- | --- | --- |
| `evidence/sourced` | Every factual line cites an evidence row, and every evidence row has a source. | — |
| `evidence/fresh` | Evidence is inside its window, by the date it was retrieved and by the page's own date. | `max_age_days` and `page_max_age_days` under `[marketing.evidence]`; `today` |
| `evidence/tier` | A claim of a guarded kind rests on a source of a required tier. | `tiers` and `require` under `[marketing.evidence]` |
| `evidence/quoted` | Each evidence row holds the passage it rests on, and a second reader has agreed the line says no more. | `judge` |
| `evidence/reachable` | A source is a real address, and one that no longer opens is recorded as such. | — |

A factual line is an entry under `[[claims]]` in the brief. It names its evidence row by id.

- `evidence/sourced` also fails when the brief has claims and the item has no `evidence.toml`.
- `evidence/fresh` holds the date a row was retrieved to `max_age_days`. A topic listed in
  `page_max_age_days` has a second window, for the page's own date. A row on such a topic must
  hold a page date, and the date must be inside the window. A date more than one day ahead fails
  too.
- `evidence/tier` reads each claim's `kind`. A kind listed in `require` must cite a row of one of
  the tiers listed for it. When `tiers` is set, every row's tier must be one of them. A claim
  with no kind is not guarded.
- `evidence/quoted` asks for a quote only in the rows a claim cites. The second reader's word is
  an attestation on the item's `evidence.toml`, made as the judge that `judge` names. The rule
  does not compare a line with its quote. The reader does.
- `evidence/reachable` opens no page. A source must be a full web address, or the path of a file
  kept in the repository. When the project keeps link-check receipts, the rule reads the newest
  one. A source that it marks as not opening is a breach: a FAIL, not a REFUSE. A link-check
  receipt that cannot be read is a REFUSE. With no link-check receipt, a dead page is not
  noticed.

### Gate: compliance — the content breaks no platform or legal rule

| Rule | The promise | Parameters |
| --- | --- | --- |
| `compliance/banned-terms` | No forbidden term appears in any text or spoken line. | `file` under `[marketing.banned_terms]` |
| `compliance/source-facts` | Product wording, price and link come only from the product record. | `file` under `[marketing.products]`; `price_words` |
| `compliance/forbidden-content` | Nothing shown or said is of a kind the rulebook forbids, and what only eyes can judge is attested. | `patterns`; `visual_judge` |
| `compliance/disclosure` | The disclosure flags follow the way the item was made, and the post shows them set. | `generated_flag` |
| `compliance/checklist` | Every item carries the full checklist for its kind and purpose, and a row is ticked only by its judge. | `[marketing.rulebooks]` |
| `compliance/rulebook-dated` | Each rule cites its page and the date it was read, and a rulebook past its window blocks publishing. | `max_age_days` of each rulebook; `today` |

These rules read all of an item's text: the title, the caption, each part's on-screen text and
spoken line, and each claim.

- `compliance/banned-terms` reads a list with one term a line. A line that starts with `re:` is a
  regular expression. Case and spacing are ignored.
- `compliance/source-facts` runs for an item whose brief names a `product`. The product must be a
  row of the product table: a CSV file with the columns `id`, `name`, `price`, `link` and
  `benefit`. Each number written as a price must equal the row's price. A number counts as a
  price when a currency sign or one of `price_words` stands beside it. Each link in the caption
  must equal the row's link. The product's wording is not compared with the table.
- `compliance/forbidden-content` takes its forbidden kinds from its own `patterns`: one regular
  expression for each kind. They are not read from a rulebook. Text that matches is a breach.
  Once an item has an asset note, the rule also asks for an attestation on the item's
  `plan.toml`, for the row `visual`, made as `visual_judge`.
- `compliance/disclosure` reads how the brief says the item is made: `voice` is `generated` or
  `human`; `footage` is `generated`, `filmed` or `mixed`. When the voice is generated, or the
  footage is generated or mixed, the brief must set the flag that `generated_flag` names, under
  `[disclosure]`. Once there is a post record, its flag must agree with the brief. No other flag
  is checked. A `content` item whose brief does not say how it is made is a REFUSE.
- `compliance/checklist` asks every `content` item for a checklist. The checklist names a
  declared rulebook, and that rulebook must apply to the item's kind and purpose. The rows repeat
  the rulebook's entries in order: `id`, `check` and `judge`. A ticked row needs an attestation
  made as the row's judge (section 7). When two rulebooks apply to one item, the item may carry
  either.
- `compliance/rulebook-dated` fails an entry with no source, and an entry read longer ago than
  its rulebook's `max_age_days`. A rulebook with no `max_age_days` never goes stale. The rule
  does not look at posts: a stale entry fails it at any time.

### Gate: consistency — what is made matches what was approved

| Rule | The promise | Parameters |
| --- | --- | --- |
| `consistency/derived-matches` | Each plan derived from the brief equals the brief. | — |
| `consistency/assets-from-kit` | Every asset used is an approved asset of the item's series. | — |
| `consistency/timing-fits` | Each spoken line fits its part's time. | `words_per_second` |
| `consistency/rulebook-pinned` | Rule data held inside a checker equals its reference file. | `pins` |

- `consistency/derived-matches` compares `plan.toml` with `brief.toml`: the number of parts; each
  part's id, times, on-screen text and spoken line; and the length, when both state it. In the
  plan, no part may end before it starts, and no two parts may overlap.
- `consistency/assets-from-kit` reads the `kit_item` each asset note names. It must be in the
  `kit` list of the series the brief names. "Approved" means listed there.
- `consistency/timing-fits` allows a spoken line as many words as its part's seconds times the
  speaking rate. The rate is `words_per_second`. A plan may set a slower `speaking_rate`, never a
  faster one. A line with no spaces is counted at four characters to a word. The rule runs
  whenever the brief is checked; it is not tied to pricing.
- `consistency/rulebook-pinned` runs only when the project lists `pins`. Each pin names a checker
  file, a reference file and a marker. The lines between `# <marker> begin` and `# <marker> end`
  in the checker must equal the reference file's entries, in the same order.

### Gate: spend — every cost is a tool's figure, inside a budget

| Rule | The promise | Parameters |
| --- | --- | --- |
| `spend/priced-first` | No paid job is sent before its plan is priced and under its ceiling. | `run_ceiling` and `unit` under `[marketing.spend]` |
| `spend/figures-from-tools` | Every cost in a document equals a spend record. | `documents` |
| `spend/estimate-calibrated` | An estimate shown to the owner carries the measured overrun of past work. | `min_loops` |
| `spend/agent-runs` | Each agent run records its cost and what it produced, and a run that produced nothing is flagged. | — |

- `spend/priced-first` reads the spend receipts after the fact. It fails when an item has spend
  and its plan holds no `estimate`, when the estimate is above `run_ceiling`, and when the item's
  receipts add up to more than `run_ceiling`. The ceiling is for one item, retakes included. The
  rule does not compare times, so it cannot show that the plan was priced before the job was
  sent. A receipt in another unit than `unit` is a REFUSE.
- `spend/figures-from-tools` reads only a cost that carries a cost tag: the number, then the tag,
  as in `1,100<!--s:content/items/a-->`. The tag names the item's folder, or `total` for every
  item. The number must equal the receipts added up, to the decimals written. A cost with no tag
  is not seen.
- `spend/estimate-calibrated` measures the overrun of finished work: the spend of every posted
  item that has an estimate, divided by those estimates. When it is above 1.05, each item that
  has an estimate and no post must state it in its `README.md` or `options.md`, as in
  `expected overrun: 1.25`, within 0.05 of the measured figure. `min_loops` is how many finished
  items are needed before the rule asks.
- `spend/agent-runs` reads every receipt under `receipts/agent-run/`. Each must hold its `cost` as a
  number and `produced` as a list of paths. An empty list needs `flagged = true` and a `reason`.

### Gate: results — the numbers are complete and fairly compared

| Rule | The promise | Parameters |
| --- | --- | --- |
| `results/recorded` | Each published item has a result with its source, read at the agreed age or later. | `min_age_days` under `[marketing.results]`; `today` |
| `results/purpose-sealed` | An item is judged on the goal number of the purpose it was sealed with. | `[marketing.purposes]` |
| `results/own-baseline` | Results are compared only with the baseline the project declared. | `baseline` under `[marketing.results]` |
| `results/one-change` | A new series changes one thing from the series it is compared with. | — |
| `results/noise-band` | A difference between two series is called real only when it is larger than the spread among their own items. | — |
| `results/inputs-rebuilt` | The numbers a results decision rests on are the result records and the project's own thresholds. | `[marketing.results]` |

- `results/recorded` asks a result for an `age_days` of at least `min_age_days`, and for a
  source. A posted item with no result fails once the post is more than twice `min_age_days` old.
- `results/purpose-sealed` asks an item that has a result for a declared purpose, and asks the
  result's metrics for that purpose's goal number.
- `results/one-change` knows three things a series can change: the audience, the format or the
  purpose. This is fixed, not a parameter. A series that names `compared_with` must name what it
  `changed`, and that field alone must differ between the two series files.
- `results/own-baseline`, `results/noise-band` and `results/inputs-rebuilt` read the decisions
  the results gate issued (section 8). The owner's own decision is left alone.

### Gate: publish — an item goes out only on the owner's yes, with its checklist closed

| Rule | The promise | Parameters |
| --- | --- | --- |
| `publish/granted` | A post names the owner's grant to publish that one item, and the grant was made before the post. | — |
| `publish/checklist-closed` | An item goes out only when every row of its checklist that is judged before the post is ticked. | — |

- `publish/granted` reads the grant a post record names in `grant`. The grant must be on file,
  be for the action `publish`, name the item's folder as its target, and be made no later than
  the post. The owner makes it with `themis grant publish <item> --reason "..."`.
- `publish/checklist-closed` asks a posted `content` item for a checklist with every row ticked,
  except a row whose `judged_from` is `post`. It reads the checklist as it is now.

### Core rules the pack sets up

Once `work` is set, the pack gives two core rules their parameters.

| Core rule | What the pack sets |
| --- | --- |
| `order/sealed-first` | The seal is `brief.toml`. The results are `assets/**`, `render/**` and `post.toml`. |
| `order/unchanged` | The seal is `brief.toml` |

It also points its own `spend/figures-from-tools` at the pages `themis report` writes:
`report.md` in each item, and `reports/*.md`.

### Core rules that read the pack's records as they are

These run with no setting from the pack or the project.

| Core rule | What it holds here |
| --- | --- |
| `decision/issued-by-gate` | The stored decision equals what the results gate says on the stored inputs |
| `decision/enough-evidence` | A retire states that its evidence was enough |
| `decision/calibrated` | The results gate holds a calibration receipt inside the limits |
| `attest/bound` | Each attestation holds the hash of the file that was judged; a file changed since is refused |
| `config/no-silent-weakening` | A change under `[marketing]` that loosens a threshold past its default, or whose direction the pack does not state, counts as a weakening |

### Core rules the pack does not set up

| Core rule | Where that leaves a project |
| --- | --- |
| `grant/required`, `grant/ceiling` | Not configured. Publishing is held by `publish/granted`, and spending by `spend/priced-first` with the run ceiling. A project whose own posting code writes action receipts can turn these on itself. |
| `scope/paths` | Runs once the project declares its roles under `[roles]` |
| `scope/rules-current` | Not configured. A project can name its rule files itself. |
| `ledger/complete`, `order/logged-first` | Not configured. A project that wants every item logged sets them itself. |
| `attest/independent` | Not configured. A project can name `second-reader` as a judge that must be independent of the author. |
| `attest/by-judge` | Cannot be used on this pack's checklists. It needs a `subject` in each row, and the pack's checklist schema refuses that key. |

### The standard `themis-marketing/1`

A project declares it with `standard = "themis-marketing/1"` under `[project]`. It is a floor:
twenty-two rules that must be at `enforce`, and two limits. A project may tighten anything.

| What it keeps out | Rules that must be at `enforce` |
| --- | --- |
| A weakened configuration | `config/locked`, `config/no-silent-weakening` |
| Work made before its brief, or a brief changed afterwards | `order/sealed-first`, `order/unchanged` |
| An untrue claim | `evidence/sourced`, `evidence/fresh`, `evidence/tier`, `compliance/banned-terms`, `compliance/source-facts`, `compliance/disclosure`, `compliance/checklist`, `compliance/rulebook-dated` |
| An unapproved post | `publish/granted`, `publish/checklist-closed` |
| An unpriced spend | `spend/priced-first`, `spend/figures-from-tools` |
| A typed decision | `results/own-baseline`, `results/noise-band`, `results/inputs-rebuilt`, `decision/issued-by-gate`, `decision/enough-evidence`, `decision/calibrated` |

The two limits are on `decision/calibrated`: `max_false_alarm` may be no higher than 0.1, and
`min_power` no lower than 0.8.

Declaring the standard changes no level. The project sets each rule to `enforce` itself.
`themis describe` lists each place where it sits below the floor, and `config/standard-floor`
fails on them once the project sets `strict = true`. The other rules of the pack stay the
project's own choice.

## 7. Rulebooks and checklists are data

Platform and legal rules change, and they differ by platform and by country. So the pack ships
none. A project supplies them as TOML files, declares each under `[marketing.rulebooks]`, and the
pack checks they are used.

| A rulebook entry has | Field | Why |
| --- | --- | --- |
| An id and a one-line check | `id`, `check` | So a checklist row can repeat it |
| A judge, by any name the project uses | `judge` | So `compliance/checklist` can ask for an attestation made as that judge |
| A source and the date it was read | `source`, `read_on` | So `compliance/rulebook-dated` can hold |
| A pass condition, if wanted | `pass_when` | So the judge knows what "done" means. No rule reads it. |
| What it is judged from, if wanted | `judged_from` | For the reader. The rules read the checklist row's own `judged_from`. |

```toml
# rules/selling.toml
[[entries]]
id = "no-cure"
check = "No line promises to cure a condition"
pass_when = "No spoken line or on-screen text names a cure"
judge = "agent"
judged_from = "script"
source = "https://rules.example/health-claims"
read_on = "2026-11-02"

[[entries]]
id = "true-result"
check = "The footage shows no result the product cannot give"
judge = "owner"
judged_from = "footage"
source = "https://rules.example/advertising"
read_on = "2026-11-02"
```

A rulebook applies to a kind and to purposes, set in the manifest with `applies_to`. A rulebook
with no `applies_to` applies to every item. A project can therefore hold several, for example one
for items that sell and one for items that do not.

An item's checklist names its rulebook and repeats its entries: the same `id`, `check` and
`judge`, in the same order. Only `judged_from` and `done` are the item's own.

```toml
# content/items/soft-hands/checklist.toml
rulebook = "selling"

[[rows]]
id = "no-cure"
check = "No line promises to cure a condition"
judge = "agent"
judged_from = "script"
done = true

[[rows]]
id = "true-result"
check = "The footage shows no result the product cannot give"
judge = "owner"
judged_from = "footage"
done = false
```

A row is ticked with `done = true`. A ticked row needs an attestation for that row id, made as
the row's judge, on the file the row is judged from. The judge makes it with
`themis attest <file> <row id> --judge <judge> --by <who>`.

| `judged_from` | The file the attestation is on | Must be ticked before the post |
| --- | --- | --- |
| `script`, `brief`, or left out | `brief.toml` | Yes |
| `plan`, `footage`, `render` | `plan.toml` | Yes |
| `post` | `post.toml` | No |

`judged_from` is not compared with the rulebook's entry. Any other value is read as `script`.

## 8. The results gate

The pack has one gate function.

| Gate | The question | What it must beat | A decision needs |
| --- | --- | --- | --- |
| `results` | Should a series lead, be kept or be retired, and does one item stand out? | The project's own median views, and the two series' numbers dealt out again at random | Results read at the agreed age, enough items in each series, and a difference larger than the noise |

The gate turns result records into a decision about one series.
`themis decide <series> --gate results --rival <other series>` builds the gate's inputs, asks the
gate, and stores both: the inputs in `decision-inputs/<series>.json` and the decision in
`decisions/<series>.json`.

**The inputs are built from records and are never typed.**

- An item counts when its brief names a series and it has a result. Its goal number is the goal
  of the item's own purpose. Its views are the metric named `views`.
- A result counts when it was read on or before the day of the decision, at the agreed age or
  later.
- The baseline is the median views of every item that counts, in every series. Its name is
  `own-median`, and `themis decide` refuses any other.
- The thresholds are the project's, from `[marketing.results]`.

`results/inputs-rebuilt` builds the inputs again, as of the same day, and compares. A threshold
typed kinder, a result typed higher, or a result record edited afterwards all fail it.

The decisions are fixed. They are tried in this order.

| Decision | When | Verdict |
| --- | --- | --- |
| `unreadable` | An input is missing or malformed | REFUSE |
| `too-few` | The series has fewer items with results than `min_items_to_judge` | REFUSE |
| `standout` | One item has at least `views_times_baseline` times the baseline's views | PASS |
| `lead` | Both series have `min_items_to_rank` items, this one is higher on the goal number, and the difference is larger than the noise | PASS |
| `retire` | Both series have `min_items_to_rank` items. This one is lower on the goal number and on the second number. Its median views are under `views_below_share_of_baseline` of the baseline. The difference is larger than the noise. | FAIL |
| `keep` | Everything else: no rival, too few items to rank, a tie, lower on the goal number and higher on the second, or a difference inside the noise | PASS |

Two series are compared on the mean of their items' goal numbers, and on the mean of their second
numbers. With no `second_number`, no series is lower on it, so none is retired.

```toml
[marketing.results]
min_age_days = 7                 # a result read earlier than this is not counted
min_items_to_judge = 3           # below this the decision is "too-few"
min_items_to_rank = 6            # both series need this many to lead or to retire
baseline = "own-median"          # never an outside benchmark
second_number = "shares_and_saves_per_thousand_views"

[marketing.results.retire]
views_below_share_of_baseline = 0.7

[marketing.results.standout]
views_times_baseline = 5
```

**The noise band.** The two series' goal numbers are pooled and dealt out again at random, 500
times, with a fixed seed. A lead or a retire stands only when at most 5% of those deals show a
difference at least as large as the real one. Otherwise the series is kept. `themis decide`
always runs this test; the manifest has no switch for it. `results/noise-band` fails a lead or a
retire whose numbers do not say it passed.

**Calibration.** `themis calibrate` shows the gate plain noise and a planted effect: two series
of eight items, 500 draws each. Measured on 2026-11-16, version 1 of the gate said yes to noise
3.8% of the time, against a limit of 10%. It found a goal number raised by two standard
deviations 96.4% of the time, against a floor of 80%. The seeds are fixed, so the figures move
only when the gate does. The command writes `receipts/calibration/marketing-results.json`, which
`decision/calibrated` reads.

Three things follow from making this a function:

- **The thresholds are sealed.** They sit in the manifest. The core counts a change under
  `[marketing]` that lowers a minimum below its default, or that it cannot classify, as a
  weakening, which needs the owner's grant and a reason. A decision made on
  other thresholds fails `results/inputs-rebuilt`.
- **The owner can still overrule.**
  `themis decide <series> --gate results --by owner --decision keep --verdict pass --reason "..."`
  records the decision as the owner's, so nobody later mistakes it for what the numbers said. The
  results rules and `decision/calibrated` leave it alone: no gate was used, so none needs a
  calibration receipt.
- **The agent cannot round up.** It receives the decision with the numbers behind it: the
  thresholds used, the means, and the share of deals that matched the difference.

A project that needs a decision type the pack does not have writes it in a local pack.

## 9. Parameters

Everything here belongs to the project. The pack's own table is `[marketing]`.

| Key under `[marketing]` | Type | Default | What it is |
| --- | --- | --- | --- |
| `work` | Text | None | The folders that each hold one item, such as `content/items/*`. Most rules do not run without it. |
| `evidence.max_age_days` | Whole number | None | The most days since a row was retrieved. `evidence/fresh` does not run without it. |
| `evidence.page_max_age_days` | Table: topic, whole number | None | For each topic, the most days since the page's own date |
| `evidence.tiers` | List of text | None | The tiers a row may have |
| `evidence.require` | Table: kind of claim, list of tiers | None | The tiers a claim of that kind may rest on. `evidence/tier` does not run without it. |
| `banned_terms.file` | Text | None | The list of forbidden terms |
| `products.file` | Text | None | The product table, a CSV file |
| `rulebooks.<name>.file` | Text, required | — | The rulebook, a TOML file |
| `rulebooks.<name>.max_age_days` | Whole number | None: never stale | The most days since an entry was read |
| `rulebooks.<name>.applies_to` | Table: `kind` as text, `purpose` as a list of text | None: every item | The items the rulebook applies to |
| `purposes.<name>.goal` | Text, required | — | The metric that purpose is judged on |
| `spend.unit` | Text | None | The unit spend is counted in. A receipt in another unit is refused. |
| `spend.run_ceiling` | Number | None | The most one item may cost. `spend/priced-first` does not run without it. |
| `results.min_age_days` | Whole number | None | The age, in days, a result is read at. `results/recorded` does not run without it. |
| `results.min_items_to_judge` | Whole number | 3 | Below this the gate says `too-few` |
| `results.min_items_to_rank` | Whole number | 6 | What both series need to lead or to retire |
| `results.baseline` | Text | None | The baseline's name. Only `own-median` is built. |
| `results.second_number` | Text | None | The metric that is the second number |
| `results.retire.views_below_share_of_baseline` | Number | 0.7 | A retired series' median views are under this share of the baseline |
| `results.standout.views_times_baseline` | Number | 5 | A standout item has this many times the baseline's views |

A rule's own parameters are set under `[rules."<rule id>"]`.

| Parameter | Rule | Type | Default |
| --- | --- | --- | --- |
| `today` | `evidence/fresh`, `compliance/rulebook-dated`, `results/recorded` | Text, an ISO date | Unset: the real current date |
| `judge` | `evidence/quoted` | Text | `second-reader` |
| `price_words` | `compliance/source-facts` | List of text | `["price"]` |
| `patterns` | `compliance/forbidden-content` | Table: forbidden kind, regular expression | Empty. The rule does not run until one is set. |
| `visual_judge` | `compliance/forbidden-content` | Text | `owner` |
| `generated_flag` | `compliance/disclosure` | Text | `ai_generated` |
| `words_per_second` | `consistency/timing-fits` | Number | 2.5 |
| `pins` | `consistency/rulebook-pinned` | List of tables: `checker`, `reference`, `marker` | None. The rule does not run until one is set. |
| `documents` | `spend/figures-from-tools` | List of text | The report pages, once `work` is set |
| `min_loops` | `spend/estimate-calibrated` | Whole number | 1 |

A manifest that uses all of it, and holds the standard:

```toml
[project]
packs = ["marketing"]
standard = "themis-marketing/1"

[marketing]
work = "content/items/*"

[marketing.evidence]
max_age_days = 30
page_max_age_days = { trend = 90 }
tiers = ["official", "third-party", "vendor"]
require = { health = ["official"] }

[marketing.banned_terms]
file = "rules/banned-terms.txt"

[marketing.products]
file = "products.csv"

[marketing.rulebooks.selling]
file = "rules/selling.toml"
max_age_days = 60
applies_to = { kind = "content", purpose = ["sales"] }

[marketing.purposes.growth]
goal = "new_followers_per_thousand_views"

[marketing.purposes.sales]
goal = "orders_per_thousand_views"

[marketing.spend]
unit = "credits"
run_ceiling = 10000

[marketing.results]
min_age_days = 7
baseline = "own-median"
second_number = "shares_and_saves_per_thousand_views"

[rules]
"config/locked" = "enforce"
"config/no-silent-weakening" = "enforce"
"order/sealed-first" = "enforce"
"order/unchanged" = "enforce"
"evidence/sourced" = "enforce"
"evidence/fresh" = "enforce"
"evidence/tier" = "enforce"
"compliance/banned-terms" = "enforce"
"compliance/source-facts" = "enforce"
"compliance/disclosure" = "enforce"
"compliance/checklist" = "enforce"
"compliance/rulebook-dated" = "enforce"
"publish/granted" = "enforce"
"publish/checklist-closed" = "enforce"
"spend/priced-first" = "enforce"
"spend/figures-from-tools" = "enforce"
"results/own-baseline" = "enforce"
"results/noise-band" = "enforce"
"results/inputs-rebuilt" = "enforce"
"decision/issued-by-gate" = "enforce"
"decision/enough-evidence" = "enforce"
"decision/calibrated" = "enforce"

[rules."compliance/forbidden-content"]
patterns = { before-and-after = "before and after" }

[roles.writer]                   # the core's table, not the pack's
branches = ["writer/*"]
paths = ["content/items/*/brief.toml"]
```

## 10. Adapters

The pack ships no adapter and names no platform or tool. A project's own code writes the records
below, and the rules read them. A file the code does not write leaves its rules with nothing to
inspect: they say so, and that is not a pass.

| The project's code writes | Where | What the rules read in it |
| --- | --- | --- |
| A post record, when an item goes out | `<item>/post.toml` | `platform` and `at`, which are required; `grant`; the flags under `[disclosure]`; `url` |
| A result record, at the agreed age | `<item>/result.toml` | `read_at`, `age_days`, `source` and `[metrics]`, all required. The gate needs `views`, the goal number of the item's purpose and, when one is set, the second number. |
| A spend receipt for each paid job | `receipts/spend/<name>.json` | `item`, the item's folder; `amount`; `tool`. All three are required. `unit`, when the project counts in one. |
| An agent-run receipt for each agent run | `receipts/agent-run/<name>.json` | `cost`, a number; `produced`, a list of paths; `flagged` and `reason`, for a run that produced nothing. The report also shows `role` and `at`. |
| An asset note for each thing made | `<item>/assets/<name>.toml` | `tool`, which is required; `kit_item` |
| A link-check receipt, if the project checks links | `receipts/links/<name>.json` | `at`, and `checked`: each source with true or false |

A receipt is written by a tool, never by hand. A receipt that cannot be read is a REFUSE, never
a skip. The core command `themis run` writes a receipt of its own under `receipts/run/`: the
command and its exit status. The pack does not read it, so the two kinds never mix.

## 11. Proofs

Each rule ships its own proofs: small projects built from scratch, with at least one honest case
the rule passes and one planted fault it must fail on. `themis prove` runs them, and
`themis explain <rule id>` lists them.

| Rule | The plant | Must fail |
| --- | --- | --- |
| `compliance/banned-terms` | Add a forbidden term to one spoken line | That rule, at that line |
| `evidence/fresh` | Move one evidence row's date back past the window | That rule, at that row |
| `consistency/derived-matches` | Change one part's end time in the plan | That rule |
| `spend/priced-first` | Price a plan above its ceiling | That rule |
| `publish/granted` | Record a post with no grant | That rule |
| `results/inputs-rebuilt` | Type a kinder threshold into the gate's inputs | That rule |
| `scope/paths` | Change code outside the writer's paths, on a writer's branch | That core rule, by the core's own proof |
| The results gate | Ask it about a weak series with too few items; feed it two series shuffled together | `too-few`, a REFUSE; `keep` |

## 12. What this pack cannot do

- **It cannot judge taste.** Whether an item is good stays with the owner's reviews.
- **It cannot prove a fact is true.** It proves the line cites a row of the right tier, that the
  row holds a quote, and that someone attested as the second reader.
- **It cannot tell who made an attestation.** It reads the judge an attestation was made as, not
  who ran the command.
- **It sees only what is declared.** A fact the brief does not list as a claim, a claim with no
  kind, and a cost with no tag are not seen.
- **It cannot see inside a platform.** Whether a setting is really on is what the post record
  says.
- **It cannot see inside an agent tool.** It sees what reaches the repository or a record.
- **A model looking at a picture is evidence, not proof.** A visual check stays an attestation.
  It is tied to the hash of the item's plan, not of each picture.
- **It reads little order from time.** A plan priced after its job was sent, and a checklist row
  ticked after the item went out, look the same as honest ones.
- **Small numbers stay small.** The gate can say "too few" honestly. It cannot make a week of
  results mean more than they do.

Not built yet:

- **A grant to choose a plan, and a grant to spend.** Only publishing needs the owner's grant.
  Spending is held by the run ceiling in the manifest.
- **A ceiling for a period**, such as a week. There is one ceiling, for one item.
- **An options step.** No rule checks the plans offered to the owner for their evidence or their
  cost.
- **Fixed review points.** The owner's reviews are the checklist rows a project's rulebook gives
  the owner, and the look at what was made.
- **A ledger rule for items.** The ledger record `themis new` writes holds no purpose. No rule
  asks for every item to be logged, or takes a stated reason in place of a missing result.
- **A check that a page was opened in this run.** No rule opens a page, and no parameter says how
  often links are checked again. A link check is the project's own tool.
- **A rule about search snippets.** A claim may rest on any row of an allowed tier.
- **A parameter for which lines count as factual.** A factual line is one the brief lists as a
  claim.
- **A check of the brief's audience and format** against a list the project declares.
- **A record of the finished item, or a check of each of its parts.** Files under `render/` are
  held to the order rule only.
- **Product wording.** `compliance/source-facts` checks the price and the link.
- **Forbidden kinds read from a rulebook.** They are a parameter of the rule.
- **More than one disclosure flag.** Only the flag for generated work is checked.
- **What a research or an asset item must ship.** No rule asks a `research` item for evidence
  rows only, or an `asset` item for its provenance and the owner's attestation.
- **A run's model, and the hash of the rules it read.** The pack does not read them.
- **A brief that must cite the decision it relies on.**
- **Lessons in the report.**
- **A parameter for what counts as one change** between two series. The three things are fixed.
- **A window of past loops for the overrun.** It is measured over every finished item.
- **A list of result metrics in the manifest.** A result holds the metrics it was given.
- **A limit on the length of the owner's pages.**
- **Adapters.** None is shipped (section 10).

## 13. Where the rules come from

Each rule carries one line that says what it was learned from. `themis explain <rule id>` prints
it. Among them: an approval pressed by mistake that started a paid job nobody had priced, a
generated clip that showed a result the advertising rules forbid, an estimate that fell a quarter
short of the spend, a cost in the owner's own pages that had been typed and was wrong, an agent
run that cost money and produced nothing, and decision thresholds that lived in a file the
deciding agent could edit.
