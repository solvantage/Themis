# Themis — guardrails as code for work done by AI agents

> Design 0.2 — 2026-11-16. Status: **proposed**. Built so far: an installable skeleton (it
> answers `themis --version` and nothing else) and the local publish pipeline
> ([docs/publishing.md](docs/publishing.md)). The skeleton is released; see
> [RELEASES.md](RELEASES.md). No rule exists yet.

**In one line:** Themis makes a repository checkable by a machine. Every number has a receipt,
every piece of work follows one sealed path, and every guard is proven able to say no.

Themis is a generic core. A field, such as trading research or marketing content, plugs in as a
**pack**. A project plugs in as a **manifest**: configuration, never code inside Themis.

Themis is the Greek Titaness of law and good order. She holds the scales: the evidence decides,
not the speaker.

| Document | Holds |
| --- | --- |
| This file | The core: laws, primitives, core rules, proofs, interfaces, adoption |
| [docs/extending.md](docs/extending.md) | How to write a pack, wrap an existing check, and set parameters |
| [docs/packs/trading.md](docs/packs/trading.md) | The trading pack |
| [docs/packs/marketing.md](docs/packs/marketing.md) | The marketing content pack |
| [docs/publishing.md](docs/publishing.md) | How a release is made and installed |
| [RELEASES.md](RELEASES.md) | The releases so far. Written by the pipeline from its receipts |

## 1. Why this exists

Two lessons, learned in different projects, are the whole reason.

**A rule written only in a prompt gets broken.** Each row is a real incident from a project that
used AI agents. Each was fixed the same way: the rule became code.

| Field | What went wrong | The fix that worked |
| --- | --- | --- |
| Trading research | A gate reported a strong pass. Nearly half its simulated fills were at prices that never traded. | A check on every fill |
| Trading research | Three agents looked at sealed data. Their prompts never mentioned the seal. | The seal moved from prose into code |
| Trading research | A study stopped reproducing its own numbers. A day was lost and the cause is still unproven. | A fingerprint beside every result |
| Strategy tuning | Two settings passed both test windows, then lost on unseen data. | A replay on every untouched year |
| Marketing content | An approval button pressed by mistake started a paid job. | A confirm step before any spend |
| Marketing content | A generated clip showed a result the advertising rules forbid. | A frame check on every shot |

Every one of those projects built its fix alone. The next project starts from zero, and its
agents start with no guard at all.

**A green check and a blind check look the same.** A check that has only ever passed has not
shown it can fail. The answer is to plant a controlled violation, run the same check, and require
the *named* rule to catch it. The vocabulary for this is small: a Gate groups Rules, a Check
evaluates them, a Proof plants the violation, and there are three verdicts: PASS, FAIL and
REFUSE.

Themis packages both lessons. The method becomes a set of rules. The proof model makes the rules
trustworthy. Any project installs it and is held to the same standard as every other project in
its field.

### Goal

- One standard for each field, enforced by code, identical in every project of that field.
- An agent cannot state a number, a decision or a "tests pass" that a machine cannot check.
- A project adopts by writing a manifest. No project needs a change to Themis.

### Not a goal

- Themis is not a backtest engine, a data pipeline, a content tool or an agent framework.
- Themis does not say the work is good. Section 18 states this limit in full.

## 2. Decisions to confirm

| Decision | Proposal | Why | Fallback |
| --- | --- | --- | --- |
| Name | **Themis** | Law, order and the scales. Fits "one standard" and "evidence decides". | Horkos (oath), Aletheia (truth), Ananke (necessity) |
| Language | **Python core**; thin wrappers for other languages later | The first packs need numpy and pandas. The rules that read files and git work on a repository in any language. | npm-first would shell out to Python for every statistic |
| Format of truth | **Small structured record files; markdown pages are generated views** | Hand-numbered tables collide and drift | Keep hand-written tables, parse them strictly |
| Distribution | **`themis-guardrails`, published to a local index** | `themis` is taken on PyPI and npm; `themis-guardrails` was free on both on 2026-11-16. A local package that shares a public name can be installed from the public index by mistake. The import and the command stay `themis`. | A private git URL; a public release later |
| Shape | **Core, packs, manifest** (section 4) | The laws are about claims and evidence, not about any field | One package per field |

## 3. The eight laws

Every rule in Themis, in the core or in a pack, is an instance of one of these.

| # | Law | In practice |
| --- | --- | --- |
| 1 | A rule is code, or it is not a rule. | Each rule has an id, a check and a proof. Prose is a generated view of the rules. |
| 2 | No number without a receipt. | A quoted number resolves to a record written by a tool, or it is flagged. |
| 3 | The numbers issue the decision, never the agent. | A decision record is written by a gate function. A hand-written one fails. |
| 4 | Three verdicts. Unknown is never a pass. | PASS, FAIL, REFUSE. Too little evidence returns "defer", not "no". |
| 5 | Order is evidence. | Log before doing. Seal before results. Grant before the action. Checked from git history. |
| 6 | Every guard is proven able to say no. | Each rule ships a planted violation. The named rule must be the one that fails. |
| 7 | One home per fact. | One record per fact. Every other mention is a pointer or a generated view. |
| 8 | Written for a newcomer. | Reports explain themselves. Terms are expanded where they first appear. |

## 4. Three layers

```text
 project    themis.toml          paths, parameters, rule levels, existing checks
            ─────────────────────────────────────────────────────────────────────
 pack       trading, marketing   kinds of work, records, field rules, gates, adapters, reports
            ─────────────────────────────────────────────────────────────────────
 core       themis               primitives, rule engine, proofs, reporters, agent hooks
```

Two rules keep the layers honest:

- **The core names no field and no project.**
- **A pack names no project.**

The second half of each rule is enforced. `tests/test_neutral.py` fails when any file in this
repository names an outside project. It holds those names only as hashes, so the test does not
name them either.

Where does a thing belong? One table decides.

| If it is… | It lives in | Example |
| --- | --- | --- |
| True in every field | The core | A quoted number must cite a receipt |
| True in one field | A pack | A simulated fill must be a price that traded |
| True in one project | That project's manifest | The test command; a freshness window; a budget; a path |
| A check the project already has | The manifest, as an **external check** | A validator script; a test file; a linter |
| New logic only one project needs | A **local pack** inside that project | A rule about that project's own data |

Nothing in the last three rows ever requires a change to Themis. Section 14 and
[docs/extending.md](docs/extending.md) describe how each is done.

Themis keeps two kinds of verdict apart:

| Kind | Question | Who answers |
| --- | --- | --- |
| **Check verdict** | Did this repository follow the standard? | Themis rules |
| **Work verdict** | Does the evidence support this claim about the work? | A gate function supplied by the pack, from the work's own records |

## 5. The primitives

The core is thirteen ideas. A pack gives them a vocabulary; a project gives them parameters.

| Primitive | What the core does | What a pack or project supplies |
| --- | --- | --- |
| Record | Validates small structured files against a schema; gives each a collision-free id | The schemas and where the files live |
| View | Regenerates a markdown page from records and fails on a difference | Which pages are views |
| Order | Checks from git history that one thing reached the main line before another | Which thing is the seal and which is the result |
| Ledger | Checks every unit of work has a record made before its result | What counts as a unit of work |
| Receipt | Stores a tool's proof that something ran, on which exact tree, with what outcome | Which commands write receipts |
| Claim | Checks a quoted number or fact against the record it cites | Which documents are governed |
| Decision | Calls a gate function on the work's records; checks the stored decision equals its answer | The gate function and its thresholds |
| Grant | Holds the owner's yes to one irreversible action as a single-use file | Which actions are irreversible |
| Attestation | Records who judged a thing that needs eyes, and the hash of what they judged | Which checks need eyes, and who the judge is |
| Scope | Checks each role changed only what it may | The roles, their paths and their denied tools |
| Proof | Plants a fault in a copy and requires the named rule to fail | The plants |
| External check | Runs any command as a rule and maps its exit code to a verdict | The command |
| Config | Validates the manifest, locks its hash, and refuses a change that weakens it without the owner's grant | The values |

## 6. Records — one home per fact

A record is a small file with a fixed schema. Its id comes from the date and a slug, never from a
hand-typed running number, so two parallel branches cannot take the same id.

The core defines six record kinds. Packs add their own on the same engine.

| Core record | Holds |
| --- | --- |
| Receipt | Proof that a command ran on an exact tree, with its counts and outcome |
| Grant | The owner's yes to one named action, used once; for money, a ceiling |
| Attestation | Who judged a thing, when, and the hash of what they judged |
| Decision | A gate's answer, its level, the gate's id and version, and the date |
| Issue | A known trap, and the test that now enforces it |
| Finding | An audit finding, its status, the decision taken and what would reopen it |

**Views.** A page people read, such as a ledger table or a verdict matrix, is written by
`themis render`. A rule regenerates it and fails on any difference. People read markdown;
machines read records; the two cannot drift.

**A decision is dated.** A decision travels with its number, the version of the method that
produced it, and its date. When the method later changes in a way that could flip it, every
citation of the old decision must be marked provisional.

**History is never rewritten.** A rule can bind from a date. Records older than that date sit in
a closed list that may shrink and never grow.

## 7. The lifecycle — one shape, named by the pack

Every piece of work follows the same seven steps. The pack gives the steps their names and says
what each must produce.

```text
 1 log ─► 2 seal ─► 3 do ─► 4 check ─► 5 decide ─► 6 report ─► 7 hand off
```

| Step | Core command | The core refuses when | Trading calls it | Marketing calls it |
| --- | --- | --- | --- | --- |
| 1 Log | `themis new` | — | A trial | A topic |
| 2 Seal | `themis seal` | The plan lacks a field its kind requires | Pre-registration | An approved brief |
| 3 Do | `themis run` | The seal is not on the main line; the tree is dirty; a guarded action has no grant | A study run | Making pictures and clips |
| 4 Check | `themis attest`, `themis check` | A row is ticked by someone who is not its judge | An independent audit | A frame check; a second reader |
| 5 Decide | `themis decide` | The evidence is too little to decide | A verdict | Lead, keep or retire |
| 6 Report | `themis report` | A required part of the report was not produced | A scorecard | A loop report |
| 7 Hand off | `themis checkpoint` | A stated fact has no receipt | The checkpoint | The checkpoint |

The commands are a convenience. **The rules are the law.** `themis check` reads git history and
the files, so work that skipped the commands is still caught.

Inside the work, the library does the same in code:

```python
from themis import work

with work.open("2026-11-20_open-drive") as w:   # refuses: no seal on the main line, dirty tree
    data = w.read("train")                      # a guarded source raises without a grant
    outcome = do_the_work(data)
    w.metric("net_ev", outcome.net_ev)          # the only numbers anyone may quote
    w.decide()                                  # the pack's gate decides; the agent cannot
```

## 8. The core rule catalogue

Forty-four rules in fourteen gates. Every rule returns PASS, FAIL or REFUSE. **REFUSE is the
answer whenever the evidence is missing, unreadable or empty.** A gate that inspected nothing
never passes.

Each rule can be `off`, `warn` or `enforce`, and can bind from a date. A rule that is off or
weakened is listed by `themis describe` as **unproven**, so silence is never mistaken for a pass.

A pack adds its own gates beside these. Packs never weaken a core rule.

### Gate: order — things happen in the declared order

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `order/logged-first` | A unit of work has its ledger record before its first result. | What a unit of work is |
| `order/sealed-first` | A seal reaches the main line in an earlier merge than any result that rests on it. | Which file is the seal, which files are results |
| `order/unchanged` | A sealed file changes only through an amendment record. | Which changes loosen the plan |

### Gate: ledger — every attempt is counted

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `ledger/complete` | No result exists without a ledger record. Every record ends with a result or a stated reason. | Where results live |
| `ledger/count-used` | A decision that depends on how many attempts were made uses the ledger's own count. | Which decisions depend on the count |

### Gate: decision — the numbers decide

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `decision/issued-by-gate` | The stored decision equals what the gate returns on the work's records. | The gate function |
| `decision/enough-evidence` | A negative decision states that the evidence was enough. Otherwise the decision is REFUSE: "defer". | What "enough" means |
| `decision/calibrated` | The gate holds a receipt showing it says no to noise and yes to a planted effect. | The noise and the planted case |

### Gate: claims — no number without a receipt

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `claims/receipt` | Each number in a governed document cites a record, and matches it. | Which documents and sections are governed |
| `claims/fresh` | The cited record still verifies against its fingerprint. | — |
| `claims/dated` | A cited decision carries its number, method version and date; a stale one is marked provisional. | Which method changes can flip which decisions |
| `claims/links` | Every link and every cited record id resolves. | — |

### Gate: suite — "tests pass" is a receipt, not a sentence

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `suite/receipt-for-tree` | A push or a "done" claim holds a full-suite receipt for the exact tree. | The suite command |
| `suite/declared-skips` | Every skipped test is declared with a reason and an end condition. | The declared skips |
| `suite/attack-files` | Each guarded module has an attack file. Each planted bug names the check that must catch it. | Which modules are guarded |

### Gate: grant — the owner's yes is a file

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `grant/required` | An action declared irreversible runs only with a grant that names it and its target. | Which actions are irreversible |
| `grant/single-use` | A grant is spent by one action and cannot be used again. | — |
| `grant/ceiling` | An action that spends stays under the ceiling its grant names. | The unit: money, credits, looks |

### Gate: attest — a check that needs eyes names who looked

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `attest/by-judge` | A row is ticked only by the judge it names. An agent never ticks the owner's row. | The judge of each row |
| `attest/bound` | An attestation names the hash of what was judged. A changed file makes it REFUSE. | — |
| `attest/independent` | A second reader is not the author and did not use the author's code. | What independence means |

### Gate: scope — each role stays in its lane

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `scope/paths` | A role's pull request changes only the paths that role may change. | The roles and their paths |
| `scope/no-self-approval` | No role merges or approves its own pull request. | — |
| `scope/rules-current` | A run records the hash of the rules it read. A stale copy is a REFUSE. | Which files are the rules |
| `scope/capabilities` | Tools denied to agents stay denied in the host's settings. | The denied tools |

### Gate: report — a result a newcomer can read

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `report/exists` | Finished work has the report its kind requires. | What the report contains |
| `report/generated` | The report is rebuilt from the work's records and matches. | The report builder |
| `report/readable` | Each chart has a "how to read this" box. Each abbreviation is expanded where it first appears. | The glossary |

### Gate: handoff — the checkpoint is true and short

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `checkpoint/shape` | The headline and each dated entry stay within their caps. | The caps |
| `checkpoint/git-true` | The commit named in the headline exists and is on the main line. | — |
| `checkpoint/suite-receipt` | The suite count cites a receipt for that commit, or is labelled unverified. | — |
| `checkpoint/pointers` | Each standing trap and each "do not re-propose" line links to its home record. | — |

### Gate: registry — past lessons stay findable

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `registry/indexed` | Every unit of work appears in the index. | Where work lives |
| `registry/closed-says-why` | A closed finding states its decision. A "won't fix" names what would reopen it. | — |
| `registry/graduated` | An issue marked "enforced" names a test that exists. | — |

### Gate: agents — the agent's own guards are in place

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `agents/hooks-installed` | The shipped hooks are present and unmodified in the host settings. | The host |
| `agents/instructions-generated` | The rules section of the agent instructions equals what `themis render` writes. | The instructions file |

### Gate: external — the project's own checks, held to the same laws

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `external/declared` | Each declared command runs and its exit code maps to a verdict. An unmapped code is a REFUSE. | The command and the mapping |
| `external/proven` | Each external check has a plant that makes it fail, or is listed as unproven. | The plant |

### Gate: config — the configuration cannot be quietly weakened

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `config/valid` | The manifest matches its schema. An unknown key, a wrong type or an unknown rule id is a REFUSE, never a silent default. | — |
| `config/locked` | A lock file holds the hash of the effective configuration. A manifest that differs from its lock fails. | — |
| `config/no-silent-weakening` | A change that weakens the configuration reaches the main line only with the owner's grant and a written reason. | Each parameter's stricter direction |
| `config/protected` | The manifest, the lock, the local pack, the hook settings, the grants and the receipts are changed by no agent role. | Extra protected paths |
| `config/standard-floor` | A value below the declared standard's floor is listed, and fails when the project sets `strict`. | The standard |

## 9. Receipts and claims — how hallucination is closed off

An agent hallucinates when it can type a number or a status that nothing checks. Themis removes
the typing.

**Receipts.** A receipt is a small JSON file written by a tool, never by hand. It says what ran,
on which exact tree, and what came out.

| Receipt | Written by | Makes this sentence checkable |
| --- | --- | --- |
| Suite | The pytest plugin, at the end of every run | "The suite passes on this commit" |
| Lint | A `themis lint` wrapper | "The linter is clean" |
| Run | `themis run` | "This work ran after its seal, on these inputs" |
| Calibration | `themis calibrate` | "This gate says no to noise and yes to a planted effect" |
| Spend | A pack's adapter for a paid tool | "This job cost this much" |
| Delivery | A host hook on the file-send tool | "The chart was sent to the owner" |

A hook or a pre-push check then asks for the receipt. It does not re-run a long suite.

**Claims.** In a governed document a number is followed by an invisible tag that names its
record:

```markdown
The half-size stop gave an uplift of **+3.7 pp**<!--t:open-drive#uplift_half_stop-->.
```

`claims/receipt` reads the number, looks up the metric in that work's records, and compares at
the precision shown. A number with no tag fails. A tag whose record is missing is a REFUSE.

The agent does not type the number at all. `themis cite open-drive uplift_half_stop` prints the
formatted number with its tag, ready to paste. Whole tables are generated blocks between
`<!-- themis:begin -->` and `<!-- themis:end -->` markers.

**Scope.** Governed text starts narrow: the checkpoint headline and each work's decision
section. Dates, times, record ids and pull-request numbers are exempt.

**Risk.** This is the rule most likely to raise false alarms. It ships at `warn`. It moves to
`enforce` in a project only after its false-alarm rate has been measured on that project's own
documents. Themis must be calibrated before it is trusted, like any other gate.

## 10. Grants and attestations

Some actions happen once and cannot be taken back: a look at sealed data, money spent, something
published. For these, three common ways of asking permission have each failed.

| How permission is usually given | Why it fails |
| --- | --- |
| A flag typed in code | Any value that counts as true opens it, and nothing asks the owner |
| An environment variable in the shell | An agent can type it |
| A button in a chat tool | It can be pressed by mistake |

A **grant** replaces all three.

| Step | What happens |
| --- | --- |
| 1 | The owner runs `themis grant <action> <target>`, with a ceiling when the action spends. |
| 2 | The shipped hook stops every command that starts with `themis grant` for the owner's click. An exact command name is easy to match and easy to attack-test. |
| 3 | The command writes a single-use grant file. It is committed, so it is visible in review. |
| 4 | The guarded code checks the file, marks it spent, and writes a record of the action. |
| 5 | `grant/required` compares receipts with grants. A guarded action with no grant fails. |

There is no value an agent can type to open a guarded action. It needs a file that only an
approved command creates. Which actions are guarded is a pack's or a project's choice.

An **attestation** is the grant's quieter sibling. Some checks need eyes: does the footage look
right, did a separate reader agree, did the owner sign the plan. Each such row names its judge.
The attestation records who judged it and the hash of what they judged. An agent can never tick
a row whose judge is the owner, and an attestation whose file has since changed is a REFUSE.

## 11. The checkpoint

`themis checkpoint` writes the parts that are facts. The agent writes only the two parts that
are judgment.

```markdown
**Last updated:** 2026-11-16 15:20 local (08:20 UTC). `main` at `a1b2c3d4` (#42).   ← generated
**Suite:** 1,204 pass / 3 skip<!--r:suite/a1b2c3d4-->, linter clean.               ← from receipts
**Changed:** <one line, written by the agent>
**Next:** <one line, written by the agent>
```

Below the headline, Themis lists what moved since the last checkpoint: new ledger records, new
decisions, open seals and grants spent. It offers them as bullets. It also proposes which entries
to roll to the archive, so the file cannot regrow.

An end-of-turn hook can warn when a session added records and the checkpoint does not mention
them. The handoff then depends on a check, not on memory.

## 12. Proofs — every rule can fail

`themis prove` plants a fault for every rule, in a way that is aware of git.

| Proof | How it works | What it shows |
| --- | --- | --- |
| **Worlds** | Each rule ships small git repositories built from scratch in a temporary folder, with the answer worked out by hand. Honest histories must pass. Broken ones must breach the named rule. | The rule's logic can say no, with no false alarm |
| **In your repository** | Themis clones the repository to a temporary folder, plants one fault, runs `themis check`, and discards the clone. | The rule is wired to *your* paths and config |
| **External checks** | The project's own plant is applied in a clone, and the wrapped command must fail with the expected message. | The project's existing check can say no |
| **Hooks** | Each shipped hook has a table of commands that must be stopped and commands that must pass, plus planted bugs in the hook's own pattern. | The agent's guards work |
| **Closed lists** | A closed list's proof adds a new offender and expects a breach. | An exemption does not hide new debt |
| **Configuration** | In a clone, a rule is switched off with no grant, and `config/no-silent-weakening` must fail. | The guard cannot be turned off quietly |

Three rules for proofs:

- **Strict.** A proof passes only when the rule it names fails. An unrelated failure does not
  count.
- **Isolated.** Nothing is planted in the working tree. Themis clones, because its rules read
  history.
- **Run in every project.** `themis prove` is part of the standard, so each project shows its
  own guards work, not only that Themis's tests passed somewhere else.

**A pack is admitted only with proofs.** Every rule a pack ships must carry at least one plant
that fails it and one honest case that passes. `themis prove` refuses a pack that does not.

For a project's own code, `themis.testing` supplies an attack kit: refusal tables, real rows
corrupted one at a time, and planted bugs run in memory. Each planted bug names the check that
must catch it.

## 13. Agent integration — guardrails outside the prompt

| Piece | What it does |
| --- | --- |
| `themis hooks install` | Writes the hooks into the host settings: session start, before a tool call, and end of turn. |
| Before a tool call | Stops delete and remote commands, `themis grant`, and any edit to a protected file, for the owner's click. |
| End of turn | Runs `themis check --changed` within a 30-second budget, and asks for receipts. |
| `--reporter=json` | One object per breach: rule id, location, why the rule exists, and the command that fixes it. |
| `themis explain <rule>` | The rule's promise, the incident behind it, and a worked fix. |
| `themis render agents-md` | Writes the rules section of the agent instructions from the catalogue. |

**Deny the capability before writing the rule.** Where a tool can be taken away from an agent,
take it away; a rule is for what cannot be removed. An agent with no login to a platform cannot
post there, whatever its instructions say.

Design rules for the end-of-turn hook:

1. Silent in a folder with no `themis.toml`.
2. Checks only work changed in this session.
3. A blocking exit always carries a reason.
4. Breaches that existed before the session are warnings, not blocks.
5. At most three blocks in one turn; then it warns and lets the turn end.
6. Never installs anything. Never reports a pass it did not establish.

A breach, as an agent receives it:

```json
{
  "rule": "order/sealed-first",
  "verdict": "fail",
  "where": "work/2026-11-20_open-drive/results/metrics.json",
  "why": "A result reached the main line in the same merge as its seal.",
  "fix": "Run again on a fresh branch cut from main after the seal pull request merges."
}
```

## 14. Extending Themis

Four extension points. None of them changes Themis.

| Extension | What it is | Who writes it | Where it lives |
| --- | --- | --- | --- |
| **Pack** | A plug-in for one field: kinds, records, rules, gate functions, adapters, reports | Anyone; installed as a Python package | Its own distribution, or inside Themis for the first packs |
| **Local pack** | A pack that lives in one repository | That project | A folder named in the manifest |
| **External check** | Any command, run as a rule | That project | The manifest |
| **Parameters** | Thresholds, windows, budgets, paths, rule levels | That project | The manifest |

**External checks** are how a project keeps the checks it already has. A validator script, a
test file or a linter is declared once, and Themis runs it as a rule: one report, one hook, the
same three verdicts, and a proof that it can fail.

```toml
[[checks.external]]
id = "ext/content-validator"
description = "Scripts follow the writing rules"
command = ["python3", "tools/check_scripts.py", "content/scripts"]
when = ["content/scripts/**", "tools/check_scripts.py"]
verdicts = { pass = [0], fail = [1] }      # any other exit code is REFUSE
output = "path-line-message"               # optional: turns output lines into located breaches

[[checks.external.proofs]]
name = "a forbidden word is caught"
plant = { file = "content/scripts/example.md", append = "\nA forbidden word.\n" }
expect = "fail"
expect_output = "forbidden"
```

### Configuration is guarded too

Everything above makes Themis easy to configure. That would also make it easy to defeat: switch a
rule off, raise a budget, or edit a wrapped script so it always passes. So the configuration is
held to the same laws as the work.

| Defence | How it works |
| --- | --- |
| **Declarative, not free code** | Values live in `themis.toml`, which can be compared mechanically. A config written as free code could hide a bypass in a branch. Logic lives only in packs, which must carry proofs. |
| **Strict schema** | An unknown key or rule id is a REFUSE. A typing mistake never becomes a default that happens to be weaker. |
| **A lock** | `themis.lock` holds the hash of the effective configuration: the manifest, the pack versions, the local pack, and each external check's command and script. Every receipt carries that hash, so a receipt made under a weaker configuration does not satisfy a stricter one. |
| **Weakening needs the owner** | Themis compares the manifest on a branch with the one on the main line. Tightening is free. Weakening needs a `config` grant and a reason, kept as an amendment record. |
| **Protected paths** | No agent role may change the manifest, the lock, the local pack, the hook settings, the grants or the receipts. The hook stops such an edit for the owner's click. |
| **Proofs** | A wrapped script edited to pass everything stops failing on its plant, and `external/proven` reports it. |

What counts as weakening:

| Change | Weakening? |
| --- | --- |
| A rule's level lowered: `enforce` to `warn`, or to `off` | Yes |
| A parameter moved in its looser direction: a longer window, a higher budget, a lower minimum | Yes |
| A rule's start date moved later; a closed list grown | Yes |
| An external check removed; its command, its trigger paths or its verdict mapping changed; its plant removed | Yes |
| A role's paths widened; a denied tool allowed; a governed document dropped | Yes |
| A pack removed; the declared standard lowered or removed | Yes |
| The opposite of any of these; a new external check added | No |
| A change Themis cannot classify | Treated as weakening |

`themis config diff` shows a branch's changes sorted into these two groups before the owner is
asked.

**Standards keep configuration honest.** A pack publishes a standard, such as
`themis-trading/1`: its rules, their required levels, and a floor for each parameter. A project
may tighten anything. Where it sits below a floor, `themis describe` says so. Two projects that
declare the same standard are held to the same floor, and the difference between them is printed,
not hidden.

The full contract, with the pack interface and the pack test kit, is in
[docs/extending.md](docs/extending.md).

## 15. Interfaces

**Command line.** Exit code 0 is PASS, 1 is FAIL, 2 is REFUSE.

| Command | Purpose |
| --- | --- |
| `themis init` | Write `themis.toml`, the folders, the hooks and the generated instructions section |
| `themis describe` | Print every gate, rule and proof; mark the unproven; report conformance to the declared standard |
| `themis check [--changed]` | Run the rules on the repository |
| `themis prove` | Run the proofs |
| `themis new`, `seal`, `run`, `decide`, `report` | The lifecycle (section 7) |
| `themis grant`, `attest` | The owner's yes; a judge's statement |
| `themis config diff`, `config lock` | Show what a change tightens and weakens; refresh the lock |
| `themis checkpoint` | Refresh the handoff |
| `themis cite`, `render` | Paste a receipted number; regenerate the views |
| `themis calibrate` | Measure a gate on noise and on a planted effect; write the receipt |
| `themis explain`, `doctor` | Explain a rule; diagnose a broken setup |

A pack may add its own names for the same commands.

**pytest plugin.** It ships in the same distribution. It writes the suite receipt, runs the rules
as test items so they join the project's existing suite, and fails an undeclared skip.

**Reporters.** Terminal, compact (one line per breach, for editor problem lists), JSON, and
SARIF (the standard format code-analysis tools exchange).

**Other check runners.** The exit codes and the JSON and SARIF reports are a contract. Any runner
that can run a command, in any language, can hold Themis as one of its checks and keep REFUSE
distinct from FAIL. A thin wrapper for a JavaScript project can come later.

## 16. Package layout and manifest

```text
Themis/
├── pyproject.toml
├── src/themis/
│   ├── records/        schemas, readers, the id scheme
│   ├── rules/          the engine and the core gates
│   ├── proofs/         worlds, clones, strict proofs
│   ├── receipts/       suite, lint, run, calibration
│   ├── claims/         tags, cite, generated blocks
│   ├── grants/         grants and attestations
│   ├── checkpoint/     the handoff
│   ├── external/       external checks and output parsers
│   ├── hooks/          host hooks and their attack tables
│   ├── reporters/      terminal, compact, json, sarif
│   ├── pack/           the pack interface and the pack test kit
│   ├── testing/        the attack kit for a project's own code
│   ├── pytest_plugin.py
│   ├── cli.py
│   └── packs/
│       ├── trading/    the trading pack
│       └── marketing/  the marketing content pack
├── worlds/             proof fixtures
├── bridge/             thin wrappers for other check runners
├── scripts/publish.py  the local publish pipeline
├── receipts/           committed receipts; publish receipts come first
├── wheelhouse/         the local package index; built files, not committed
├── docs/
└── tests/
```

Built today: `pyproject.toml`, `src/themis/__init__.py`, `src/themis/cli.py`,
`scripts/publish.py`, the documents and `tests/`. Everything else in the tree is the plan.

A project's manifest. Every value here is the project's own; none is built into Themis.

```toml
[project]
name = "my-project"
packs = ["trading"]                  # installed packs, by name
local_pack = "tools/themis_pack"     # optional: rules only this project needs
standard = "themis-trading/1"
strict = true                        # fail, not just list, a value below the standard's floor

[config]
protected = ["tools/check_*.py"]     # added to the paths no agent role may change

[homes]                              # where this project keeps each kind of record
work = "research/experiments"
ledger = "research/trials"
checkpoint = "CHECKPOINT.md"

[views]
"research/TRIAL-LEDGER.md" = "ledger"

[suite]
command = "uv run pytest -q"

[rules]                              # levels and parameters, rule by rule
"claims/receipt" = "warn"
"order/sealed-first" = { level = "enforce", since = "2026-09-21" }
"checkpoint/shape" = { headline_lines = 5, entry_bullets = 10 }

[roles.writer]                       # for scope/paths
paths = ["content/scripts/**"]

[[checks.external]]                  # a check this project already has
id = "ext/docs"
command = ["npx", "markdownlint-cli2", "**/*.md"]
verdicts = { pass = [0], fail = [1] }
```

## 17. Adoption and roadmap

Adoption is the same path for every project, and it never needs a change to Themis.

| Level | Name | What the project does | What it gains |
| --- | --- | --- | --- |
| 0 | Observe | Runs `themis init`. Every rule reports at `warn`. | A first report of where it stands |
| 1 | Wrap | Declares the checks it already has as external checks. | One command, one report, one end-of-turn hook |
| 2 | Fill | Turns on core and pack rules where it has only prose today. | Instructions become checks |
| 3 | Prove | Adds a plant for each wrapped check, moves rules to `enforce`, declares a standard. | Its guards are shown able to fail |
| 4 | Replace | Optional. Swaps a wrapped check for the pack's own rule, once the two have agreed. | Less code of its own to keep |

**Agreement before replacement.** A pack rule can be set to shadow an external check. Themis runs
both on the same tree and reports any difference. A difference is a finding in one of the two. A
project replaces a check only after the two have agreed for a period it chooses.

**Past records stay as written.** A rule binds from a date. Nothing older is converted, because
counts, seals and decisions are tied to the commits they were made in.

**When a project needs more.** If no pack has the logic, the project writes a local pack. If a
second project needs the same logic, it moves into a pack. It never moves into the core unless it
is true in every field.

| Phase | Delivers | Exit test |
| --- | --- | --- |
| 0 | Engine, `check`, `describe`, `prove`, exit codes, JSON, pytest plugin, external checks | A wrapped external check and a sample native rule each fail on their plant and name themselves |
| 1 | The core primitives and their gates; the agent hooks | **Incident replay:** each rule catches its own incident, rebuilt as a world |
| 2 | The pack interface, the pack test kit, standards and conformance | A pack with a rule that has no proof is refused |
| 3 | The trading pack | Each gate says no to noise and yes to a planted effect, as measured rates |
| 4 | The marketing content pack | The same, for its results gate; each rule catches its incident |
| 5 | A wrapper for another check runner | That runner holds Themis as one check and keeps REFUSE distinct from FAIL |

**The genericity test** applies from phase 1 on. Two projects of different shape must adopt with
a manifest alone. If either needs a change to the core, the core is wrong.

**Incident replay** is the acceptance test for every rule. Each rule names the incident it exists
for. Its proof rebuilds that incident as a small world. A rule that cannot catch its own incident
is not shipped.

## 18. What Themis does not prove

- **It does not prove the work is good.** It proves the claim was made under the standard, and
  that the standard's checks can fail.
- **It cannot see who typed the code.** A false "written by a separate reader" is a breach of
  trust, not a pass. Themis checks the declaration, not the author.
- **It cannot stop a memory leak.** A belief formed while looking at guarded data is invisible to
  code. The grant makes the look visible; honesty covers the rest.
- **It cannot confirm a person read something.** A delivery receipt shows a file was sent.
- **It sees only what reaches the repository.** What happens inside another tool is invisible
  unless that tool writes a record.
- **The rules are still a judgment.** Wrong rules will be proven to work, faithfully. Choosing
  what to protect stays with the owner.
