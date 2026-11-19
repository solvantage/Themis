# Themis — guardrails as code for work done by AI agents

> Design 0.2 — 2026-11-19. Status: **built**: the engine, the core, both packs and the Node
> wrapper. What was designed and is not built is listed in section 18. `themis describe` lists
> every rule that exists, and whether it is proven. What is released is in [RELEASES.md](RELEASES.md); how a
> release is made is in [docs/publishing.md](docs/publishing.md).

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

## 2. Decisions

| Decision | Chosen | Why | The road not taken |
| --- | --- | --- | --- |
| Name | **Themis** | Law, order and the scales. Fits "one standard" and "evidence decides". | Horkos (oath), Aletheia (truth), Ananke (necessity) |
| Language | **Python, standard library only**; a thin Node wrapper | The rules read files and git, so they work on a repository in any language. The packs' statistics are written out by hand, so installing Themis pulls in nothing else. | npm-first would shell out to Python for every statistic |
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

**History is never rewritten.** A rule can bind from a date, set with `since`. Work older than
that date is left as it was written. Every rule that inspects units of work reads the date the
same way (`Context.predates`, `Context.bound`): a unit, a seal or a record that reached the main
line in a commit dated before `since` is not held to the rule; one begun on or after it is.

## 7. The lifecycle — one shape, named by the pack

Every piece of work follows the same seven steps. The pack gives the steps their names and says
what each must produce.

```text
 1 log ─► 2 seal ─► 3 do ─► 4 check ─► 5 decide ─► 6 report ─► 7 hand off
```

| Step | Core command | The core refuses when | Trading calls it | Marketing calls it |
| --- | --- | --- | --- | --- |
| 1 Log | `themis new` | A ledger record of that name already exists | A trial | An item |
| 2 Seal | None: the plan is merged on its own | The plan lacks a field its kind requires (a pack rule) | Pre-registration | The brief |
| 3 Do | `themis run <unit> -- <command>` | The seal is not on the main line; the tree is dirty | A study run | Making pictures and clips |
| 4 Check | `themis attest`, `themis check` | A row is ticked by someone who is not its judge | An independent audit | A frame check; a second reader |
| 5 Decide | `themis decide` | The evidence is too little to decide | A verdict | Lead, keep or retire |
| 6 Report | `themis report` | A required part of the report was not produced | A scorecard | A loop report |
| 7 Hand off | `themis checkpoint` | A stated fact has no receipt | The checkpoint | The checkpoint |

The commands are a convenience. **The rules are the law.** `themis check` reads git history and
the files, so work that skipped the commands is still caught.

Inside the work, a pack's own library guards what the commands cannot. The trading pack's
`data.window` hands over a sealed window's dates only with an unused grant, and writes the look
down first. There is no general library for the inside of a run: what a run writes is held by the
rules afterwards.

## 8. The core rule catalogue

Fifty rules in seventeen gates. Every rule returns PASS, FAIL or REFUSE. **REFUSE is the
answer whenever the evidence is missing, unreadable or empty.** A gate that inspected nothing
never passes.

Each rule can be `off`, `warn` or `enforce`, and can bind from a date. Every rule starts at
`warn`: it runs and is shown, and cannot fail the run. A rule that lacks a setting it needs says
**not configured** and does not run. `themis describe` counts every rule that is off, not
configured or unproven, so silence is never mistaken for a pass. It runs each rule to learn that,
since a rule may need a table only its run reads, so `describe` and `describe --status` count
the same.

A pack adds its own gates beside these. Packs never weaken a core rule. The full catalogue, the
core's rules and every pack's in one place, with each rule's gate, promise, level and proof
count, is written from the rules themselves by `themis describe --markdown`, so it is never out
of date. The pages written by hand are held to the code by `tests/test_docs.py`: each rule's row
and promise here and on its pack's page, the counts here, in the README and at the top of each
pack page, each pack's kinds, gate functions and parameters, and every command `themis --help`
lists in section 15.

### Gate: order — things happen in the declared order

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `order/logged-first` | A unit of work has its ledger record before its first result. | What a unit of work is |
| `order/sealed-first` | A seal reaches the main line in an earlier merge than any result that rests on it. | Which file is the seal, which files are results |
| `order/unchanged` | A sealed file changes only through an amendment record. | Which changes loosen the plan |

### Gate: ledger — every attempt is counted

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `ledger/complete` | No result exists without a ledger record, and every ledger record ends with a result or a stated reason. | Where results live |
| `ledger/count-used` | A decision that depends on how many attempts were made uses the ledger's own count. | Which decisions depend on the count |

### Gate: decision — the numbers decide

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `decision/issued-by-gate` | The stored decision equals what the gate returns on the work's records. | The gate function |
| `decision/enough-evidence` | A negative decision states that the evidence was enough, and is otherwise recorded as a refusal. | What "enough" means |
| `decision/calibrated` | The gate holds a receipt showing it says no to noise and yes to a planted effect. | The noise and the planted case |

### Gate: claims — no number without a receipt

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `claims/receipt` | Each number in a governed document cites a record, and matches it. | Which documents and sections are governed |
| `claims/fresh` | The cited record still verifies against its fingerprint. | — |
| `claims/dated` | A cited decision carries its date and method version, and one that a later method change could flip is marked provisional. | Which method changes can flip which decisions |
| `claims/links` | Every link and every cited record resolves. | — |

### Gate: suite — "tests pass" is a receipt, not a sentence

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `suite/receipt-for-tree` | The exact tree holds a receipt of a full, passing test run. | The suite command |
| `suite/declared-skips` | Every skipped test is declared with a reason and an end condition. | The declared skips |
| `suite/attack-files` | Each guarded module has an attack file that plants faults in it. | Which modules are guarded |

### Gate: grant — the owner's yes is a file

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `grant/required` | An action declared irreversible runs only with a grant that names it and its target. | Which actions are irreversible |
| `grant/single-use` | A grant is spent by one action and cannot be used again. | — |
| `grant/ceiling` | An action that spends stays under the ceiling its grant names. | The unit: money, credits, looks |

### Gate: attest — a check that needs eyes names who looked

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `attest/by-judge` | A row is ticked only by the judge it names. | The judge of each row |
| `attest/bound` | An attestation names the hash of what was judged, and a file that changed since then is refused. | — |
| `attest/independent` | A second reader is not the author and was not given the author's own work. | What independence means |

### Gate: scope — each role stays in its lane

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `scope/paths` | A role's pull request changes only the paths that role may change. | The roles and their paths |
| `scope/no-self-approval` | No agent merges into the main line. | — |
| `scope/rules-current` | A run records the hash of the rules it read, and a run on a stale copy is refused. | Which files are the rules |
| `scope/capabilities` | Tools denied to agents stay denied in the host's settings. | The denied tools |

### Gate: report — a result a newcomer can read

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `report/exists` | Finished work has the report its kind requires. | What the report contains |
| `report/generated` | The report is rebuilt from the work's records and matches. | The report builder |
| `report/readable` | Each chart has a box that says how to read it, and each abbreviation is expanded where it first appears. | The glossary |

### Gate: handoff — the checkpoint is true and short

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `checkpoint/shape` | The headline and each dated entry stay within their caps. | The caps |
| `checkpoint/git-true` | The commit named in the headline exists and is on the main line. | — |
| `checkpoint/suite-receipt` | The suite count cites a receipt for that commit, or is labelled unverified. | — |
| `checkpoint/pointers` | Each standing trap and each closed decision points at its home record. | — |

### Gate: registry — past lessons stay findable

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `registry/indexed` | Every unit of work appears in the index. | Where work lives |
| `registry/closed-says-why` | A closed finding states its decision, and a finding left unfixed names what would reopen it. | — |
| `registry/graduated` | An issue marked enforced names a test that exists. | — |

### Gate: agents — the agent's own guards are in place

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `agents/hooks-installed` | The shipped hooks are present in the host's settings, and the git hooks run Themis when the project declares them. | The host, or the git hooks folder |
| `agents/instructions-generated` | The rules section of the agent instructions equals what the rules produce. | The instructions file |

### Gate: views — a generated page is never typed

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `views/current` | Each generated page equals what its records produce. | Which pages hold a generated block |
| `views/untouched` | A page stamped by its generator still hashes to the hash in its stamp. | Which pages may carry a stamp |

`views/untouched` is for pages a clone cannot rebuild, because their generator reads data that is
not in the repository. The generator writes a stamp on a line of its own, such as
`<!-- generated by scripts/costs.py --doc · sha256:… -->` (`themis.gates.views.stamp` writes one).
The hash is the SHA-256, in lower-case hex, of the page's UTF-8 text with each CRLF or lone CR
turned into LF and the stamp's own line taken out. A stamp inside fenced code is a quotation, not
a stamp. A page in scope with no stamp is the project's own, unless it carried one on the main
line: a stamp taken out is the hand edit the rule is for.

### Gate: layout — the repository is shaped the way the project says

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `layout/required-files` | Each folder of a declared kind holds the files its kind requires. | Each kind's folder pattern and the files it needs |
| `layout/retired-names` | No file holds a retired name, in its text or its path, but on a line allowed exactly. | The retired names, and each allowed line |
| `layout/no-ignored-citations` | No page links or cites a path git ignores, unless a tracked index the project names lists it. | The pages, and the index |

A kind is a table of `folders` (a pattern) and `files` (patterns inside each folder); a new kind,
or a new file in a kind, is a tightening. Retired names are matched in any case, and the manifest
that holds them is never read; an allowance names a file and the whole text of one line, and
covers that line once. A page cites a path through a link, or a code span in prose that holds a
path with a folder in it; a path is listed when the index cites it, or a folder that holds it.

### Gate: docs — a page renders as it was written

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `docs/no-bare-dollar-pairs` | No line of Markdown prose holds two or more bare dollar signs, which a renderer pairs into math. | Which pages it reads |

Prose is told from code and HTML as CommonMark says: a fence closes only on its own character, at
least as long; indented code starts where no paragraph or list goes on; an HTML block starts under
one of the seven start conditions. Code spans, link targets, inline tags and `\$` are not bare.
The reader is `themis.markdown`, which a pack rule can build on.

### Gate: external — the project's own checks, held to the same laws

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `external/declared` | Each declared command can be started, and no exit code is both a pass and a fail. | The command and the mapping |
| `external/proven` | Each external check has a plant that makes it fail and an honest case it passes. | The plant |

### Gate: config — the configuration cannot be quietly weakened

| Rule | The promise | Supplied by the pack or project |
| --- | --- | --- |
| `config/valid` | The manifest matches its schema. An unknown key, a wrong type or an unknown rule id is refused, never defaulted. | — |
| `config/locked` | A lock file holds the hash of the effective configuration. A manifest that differs from its lock fails. | — |
| `config/no-silent-weakening` | A change that weakens the configuration reaches the main line only with the owner's grant and a written reason. | Each parameter's stricter direction |
| `config/protected` | The manifest, the lock, the local pack, the hook settings, the grants and the receipts are changed by no agent role. | Extra protected paths |
| `config/standard-floor` | A value below the declared standard's floor is listed, and fails when the project sets strict. | The standard |

## 9. Receipts and claims — how hallucination is closed off

An agent hallucinates when it can type a number or a status that nothing checks. Themis removes
the typing.

**Receipts.** A receipt is a small JSON file written by a tool, never by hand. It says what ran,
on which exact tree, and what came out.

| Receipt | Written by | Makes this sentence checkable |
| --- | --- | --- |
| Suite | The pytest plugin, at the end of every run | "The suite passes on this commit" |
| Run | `themis run` | "This work ran after its seal, on a clean tree" |
| Calibration | `themis calibrate` | "This gate says no to noise and yes to a planted effect" |
| Action | The guarded code, through `grants.record_action` | "This action ran on the owner's grant" |
| Spend | The project's own code, for each paid job | "This job cost this much" |

A rule then asks for the receipt: `suite/receipt-for-tree` for the suite, `grant/required` for an
action. Nothing re-runs a long suite to check a sentence about it.

**Claims.** In a governed document a number is followed by an invisible tag that names its
record:

```markdown
The half-size stop gave an uplift of **+3.7 pp**<!--t:open-drive#uplift_half_stop-->.
```

`claims/receipt` reads the number, looks up the metric in that work's records, and compares at
the precision shown. A number with no tag fails. A tag whose record is missing is a REFUSE.

The agent does not type the number at all. `themis cite open-drive uplift_half_stop` prints the
formatted number with its tag, ready to paste. A tag names a unit by its folder name, or by its
whole path (`<!--t:setups/a/tune#uplift-->`) when units share that folder name; only a tag that
uses a shared name fails. Whole tables are generated blocks between
`<!-- themis:begin NAME -->` and `<!-- themis:end NAME -->` markers, written by `themis render`.

Two more tags point at records: `<!--d:WORK-->` at a decision, and `<!--r:KIND/NAME-->` at a
receipt. A pack may register a tag of its own, as the marketing pack does for a cost.

**Scope.** Which documents are governed, and which of their sections, is the project's choice:
`governed` and `sections` on the claims rules. Dates, times, record ids and pull-request numbers
are exempt.

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
| 2 | The shipped hook stops every `themis grant` command for the owner's click. An exact command name is easy to match and easy to attack-test. |
| 3 | The command writes a grant file under `grants/`. It is committed, so it is visible in review. |
| 4 | The guarded code checks that the grant is for this action and target and is unused, then writes an action receipt that names it. `themis act <action> <target> -- <command>` does this for any command: it spends the grant, writes the receipt and only then runs the command. |
| 5 | `grant/required` compares the receipts with the grants. A guarded action with no grant fails. `grant/single-use` fails a grant named by two actions. |

There is no value an agent can type to open a guarded action. It needs a file that only an
approved command creates. Which actions are guarded is a pack's or a project's choice. A project
that states its own `guarded` list replaces the pack's, so it keeps the pack's actions in it.

A delete or a spend that runs inside a script is out of a hook's sight. `themis act` gives the
command it runs a token in `THEMIS_ACT_TOKEN`; the script calls `themis act --verify <action>
<target>` first and stops on anything but exit 0. The token is good only while its act runs, for
its own action and target, and its receipt holds only its hash. A pack may write records of its
own for an action before the command starts: the trading pack writes the look a sealed window's
rules count.

An **attestation** is the grant's quieter sibling. Some checks need eyes: does the footage look
right, did a separate reader agree, did the owner sign the plan. Each such row names its judge.
The attestation, written by `themis attest`, records the judge, who judged, and the hash of
the file they judged. A row is ticked only by an attestation made as its judge, and an
attestation whose file has since changed is a REFUSE. The hook stops `themis attest --judge
owner` for the owner's click, so an agent cannot attest as the owner. Themis reads the judge an
attestation names; it cannot see who really looked.

## 11. The checkpoint

`themis checkpoint` writes the parts that are facts. The agent writes only the two parts that
are judgment.

```markdown
**Last updated:** 2026-11-16 15:20 local (08:20 UTC). `main` at `a1b2c3d4` (#42).   ← generated
**Suite:** 1,204 pass / 3 skip<!--r:suite/a1b2c3d4-->.                         ← from the receipt
**Changed:** <one line, written by the agent>
**Next:** <one line, written by the agent>
```

When the tree has no suite receipt, the second line says so: `unverified — no receipt for this
tree`. Below the headline sit dated entries, the standing traps and the closed decisions. The
handoff rules hold their length, the commit the headline names, the suite count, and that each
trap and decision points at its home record.

## 12. Proofs — every rule can fail

`themis prove` plants a fault for every rule, in a way that is aware of git.

| Proof | How it works | What it shows |
| --- | --- | --- |
| **Worlds** | Each rule ships small git repositories built from scratch in a temporary folder, with the answer worked out by hand. Honest histories must pass. Broken ones must breach the named rule. | The rule's logic can say no, with no false alarm |
| **External checks** | The project's own plant is applied in a clone (the tracked files and the untracked ones git does not ignore; staged, when the plant says `stage = true`), and the wrapped command must fail with the expected message. | The project's existing check can say no |
| **Hooks** | Each shipped hook has a table of commands that must be stopped and commands that must pass, plus planted bugs in the hook's own pattern. | The agent's guards work |
| **Configuration** | In a world, a rule is switched off with no grant, and `config/no-silent-weakening` must fail. | The guard cannot be turned off quietly |

Three rules for proofs:

- **Strict.** A proof passes only when the rule it names fails. An unrelated failure does not
  count.
- **Isolated.** Nothing is planted in the working tree. A world is built in a temporary folder;
  an external check's plant is applied to a copy of the repository.
- **Run in every project.** `themis prove` runs the proofs of every rule the project turns on,
  and of its external checks, so each project shows its own guards work.

**A pack is admitted only with proofs.** Every rule a pack ships must carry at least one plant
that fails it and one honest case that passes. The pack kit checks this, and `themis prove`
fails a project whose pack falls short.

## 13. Agent integration — guardrails outside the prompt

| Piece | What it does |
| --- | --- |
| `themis hooks install` | Writes three hooks into the host's settings, `.claude/settings.json`: before a tool call, session start, and end of turn. In a uv project they run `uv run --frozen --quiet themis`, held to the lock file. |
| Which project | A hook judges the project named by `--root`, else the host's project folder (`$CLAUDE_PROJECT_DIR`), else the nearest folder holding a `themis.toml` at or above the shell's folder. The shell's folder only places a command's relative paths, so a shell outside the project cannot slip a protected edit past it. |
| `themis hooks install --git [--path .githooks]` | Writes two git hooks, pre-commit (`themis check --changed`) and pre-push (`themis check`), and sets `core.hooksPath` to their folder. It keeps a different hook already there unless given `--force`. Declared as `git_hooks` under `[agents]`, they are checked by `agents/hooks-installed`. |
| Before a tool call | Stops deletes, remote commands, a forced push, `themis grant`, the owner's own `themis decide` and `themis attest`, and any write to a protected file, for the owner's click. |
| Session start | Remembers which breaches already exist, so old ones do not block new work. |
| End of turn | Runs `themis check` against the main line. A new breach keeps the turn open. The host gives it 300 seconds. |
| `--reporter=json` | One object per breach: rule id, location, why the rule exists, and the command that fixes it. |
| `themis explain <rule>` | The rule's promise, the incident behind it, and a worked fix. |
| `themis act` | Runs a guarded command only with the owner's unspent grant. A script that deletes or spends checks `themis act --verify` first, so it refuses to run where no hook can see it. |
| `themis render` | Writes the pages listed under `[views]`, and the rules section of the instructions file named under `[agents]`. |

**Deny the capability before writing the rule.** Where a tool can be taken away from an agent,
take it away; a rule is for what cannot be removed. An agent with no login to a platform cannot
post there, whatever its instructions say.

Design rules for the end-of-turn hook:

1. Silent in a folder with no `themis.toml`.
2. Runs every rule; an external check runs only when its paths changed against the main line.
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
| A rule's start date moved later, or set for the first time; a closed list grown | Yes |
| An external check removed; its command, its trigger paths or its verdict mapping changed; its plant removed | Yes |
| A role's paths widened; a denied tool allowed; a governed document dropped | Yes |
| A pack removed; the declared standard lowered or removed | Yes |
| A table, a key or a list entry removed; a value changed whose direction nothing states; a test skip added; a home moved | Yes |
| A key added to a table that was already there, whose direction its pack does not state; a stated parameter that replaces the value a pack had set, in its looser direction | Yes |
| A pack's key moved past its default in the looser direction, such as a window's `looks` raised above 1 | Yes |
| The opposite of any of these; a new external check added | No |
| An addition: a new table (a pack's, `[views]`, `[suite]`, `[agents]`), a new entry in a pack's table of entries (a window), a new list entry, a rule's required parameter first set, another `work` pattern | No |
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
| `themis init` | Write a starter `themis.toml` and the local `.themis/` folder |
| `themis describe [--status] [--markdown]` | Print every gate, rule and proof; count what is off, not configured or unproven. `--status` adds what each rule finds now; `--markdown` prints the full catalogue of core and pack rules |
| `themis check [RULE ...] [--changed] [--reporter ...]` | Run the rules on the repository |
| `themis prove [RULE ...]` | Run the proofs, and hold each turned-on pack to the pack contract |
| `themis explain RULE` | A rule's promise, the incident behind it, its parameters and its proofs |
| `themis doctor` | Say what is wrong with the project's setup |
| `themis new NAME --question ... [--under PATTERN]` | Log a unit of work before it runs: a ledger record, and the folder it will live in. `work` is one pattern or a list; with several places that can hold a unit, `--under` names one |
| `themis run UNIT -- COMMAND` | Run a unit's work on a clean tree, after its seal; write the run receipt and, with `--input`, the provenance |
| `themis decide UNIT --gate GATE` | Ask a gate for the decision and store it; `--by owner` records the owner's own call |
| `themis report UNIT` | Build a unit's report with its pack's builder |
| `themis grant ACTION [TARGET]`, `themis attest FILE ROW` | The owner's yes; a judge's statement |
| `themis act ACTION TARGET -- COMMAND` | Run a guarded command with an unspent grant: spend it, write the action receipt, then run; `--verify` from inside the command exits 0 only under `act` |
| `themis cite WORK KEY` | Print a number with its tag, ready to paste |
| `themis checkpoint` | Rewrite the facts in the checkpoint's headline |
| `themis render [--check]` | Write the generated pages, or fail when one is stale |
| `themis calibrate` | Measure each gate on noise and on a planted effect; write the receipts |
| `themis config diff`, `themis config lock` | Show what a change tightens and weakens; refresh the lock |
| `themis hooks install [--git] [--path DIR] [--force]` | Install the agent hooks; with `--git`, the git hooks (pre-commit, pre-push) and `core.hooksPath` |
| `themis hook EVENT` | Answer one hook event from the agent host, read from standard input. The installed hooks call it; people do not |

**pytest plugin.** It ships in the same distribution. In a project with a `themis.toml`, every
pytest run ends by writing the suite receipt: what ran, on which exact tree, how it ended, and
whether the run was narrowed. `suite/receipt-for-tree` and `suite/declared-skips` read it.

**Reporters.** Terminal, compact (one line per breach, for editor problem lists), JSON, and
SARIF (the standard format code-analysis tools exchange).

**Other check runners.** The exit codes and the JSON and SARIF reports are a contract. Any runner
that can run a command, in any language, can hold Themis as one of its checks and keep REFUSE
distinct from FAIL. `bridge/node` is that wrapper for a JavaScript project: `themisCheck()`
runs `themis check --reporter json` and turns anything it cannot read, such as a missing program,
a crash or a timeout, into REFUSE.

## 16. Package layout and manifest

```text
Themis/
├── pyproject.toml
├── src/themis/
│   ├── cli.py            the commands
│   ├── engine.py         runs the rules; rule.py, verdict.py and schema.py beside it
│   ├── manifest.py       reads themis.toml strictly; configguard.py locks and classifies it
│   ├── standards.py      a declared standard and where a project sits below it; roles.py, work.py
│   ├── records.py        record kinds and their homes; grants.py, receipts.py, claims.py
│   ├── proofs.py         worlds and plants; external.py runs external checks
│   ├── hooks.py          the agent and git hooks; render.py writes the generated pages
│   ├── act.py            a guarded command, run once on an unspent grant
│   ├── checkpoint.py     the handoff; reporters.py, pytest_plugin.py, gitlog.py, paths.py
│   ├── markdown.py       which lines of a page are prose, as CommonMark reads them
│   ├── gates/            the core's seventeen gates
│   ├── pack/             the pack interface and the pack test kit
│   └── packs/
│       ├── trading/      the trading pack
│       └── marketing/    the marketing content pack
├── bridge/node/          the wrapper for a JavaScript check runner
├── scripts/publish.py    the local publish pipeline
├── receipts/             committed receipts; the publish receipts so far
├── wheelhouse/           the local package index; built files, not committed
├── docs/
└── tests/
```

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
ledger = "research/trials/*.toml"
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
description = "The documents pass the markdown linter"
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

**Agreement before replacement.** Before a project swaps a wrapped check for a pack rule, it
runs both for a while and compares them by hand. A `shadow` setting that would compare them
automatically is accepted in the manifest and not built yet (section 18).

**Past records stay as written.** A rule binds from a date. Nothing older is converted, because
counts, seals and decisions are tied to the commits they were made in.

**When a project needs more.** If no pack has the logic, the project writes a local pack. If a
second project needs the same logic, it moves into a pack. It never moves into the core unless it
is true in every field.

| Phase | Delivers | Exit test | State |
| --- | --- | --- | --- |
| 0 | Engine, `check`, `describe`, `prove`, exit codes, JSON, pytest plugin, external checks | A wrapped external check and a sample native rule each fail on their plant and name themselves | Built; met |
| 1 | The core primitives and their gates; the agent hooks | Each rule fails on a planted fault and passes an honest case | Built; met. Each rule's `learned` line names its incident; not every proof rebuilds that exact incident |
| 2 | The pack interface, the pack test kit, standards and conformance | A pack with a rule that has no proof is refused | Built; met |
| 3 | The trading pack | Each gate says no to noise and yes to a planted effect, as measured rates | Built; met (see the pack's document for the rates and a known limit) |
| 4 | The marketing content pack | The same, for its results gate | Built; met |
| 5 | A wrapper for another check runner | That runner holds Themis as one check and keeps REFUSE distinct from FAIL | Built; met, for Node |

**The genericity test** applies from phase 1 on. Two projects of different shape must adopt with
a manifest alone. If either needs a change to the core, the core is wrong. It has not been run on
a real project yet.

**Incident replay** is the aim for every rule: each rule names the incident it exists for, and
its proof rebuilds that incident as a small world.

## 18. What Themis does not prove

- **It does not prove the work is good.** It proves the claim was made under the standard, and
  that the standard's checks can fail.
- **It cannot see who typed the code.** A false "written by a separate reader" is a breach of
  trust, not a pass. Themis checks the declaration, not the author.
- **It cannot stop a memory leak.** A belief formed while looking at guarded data is invisible to
  code. The grant makes the look visible; honesty covers the rest.
- **It cannot confirm a person read something.** An attestation says who judged a file, not
  that they read it.
- **It sees only what reaches the repository.** What happens inside another tool is invisible
  unless that tool writes a record.
- **The rules are still a judgment.** Wrong rules will be proven to work, faithfully. Choosing
  what to protect stays with the owner.

### Not built yet

- A `lint` receipt, and a delivery receipt for a file sent to the owner.
- Proofs planted in a copy of the project's own repository. Native proofs run in worlds built
  from scratch; only external checks are planted in a copy.
- Closed lists: a list of old offenders that may shrink and never grow.
- The `shadow` setting, which would run a pack rule beside an external check and report where
  they differ. The manifest accepts it, and nothing reads it.
- An attack kit for a project's own code (`themis.testing`).
- A checkpoint that lists what moved since the last one, and a hook that warns when a session
  added records the checkpoint does not mention.
- A general library for the inside of a run, with a seal check on entry and metrics written
  through it.
