# Themis

Guardrails as code for work done by AI agents.

Themis makes a repository checkable by a machine. Every number has a receipt, every piece of work
follows one sealed path, and every guard is proven able to say no.

It is a generic core. A field plugs in as a **pack**; a project plugs in as a **manifest**. The
core names no field and no project, and a test keeps it that way.

**Status:** built. The engine, 46 core rules in 16 gates, the agent hooks, the pack interface,
the trading pack, the marketing content pack and a wrapper for Node check runners all exist,
and every rule ships proofs that it can fail. What was designed and is not built is listed at the
end of [DESIGN.md](DESIGN.md) and of each pack's document. Every release, with its commit, its
test count and the line that installs it, is listed in **[RELEASES.md](RELEASES.md)**.

| Read | For |
| --- | --- |
| [RELEASES.md](RELEASES.md) | The releases, and how to install the newest |
| [docs/onboarding.md](docs/onboarding.md) | Getting started in a trading repository: set-up, the daily loop, three scenarios |
| [DESIGN.md](DESIGN.md) | The core: laws, primitives, core rules, proofs, adoption |
| [docs/extending.md](docs/extending.md) | Parameters, external checks, local packs, writing a pack |
| [docs/packs/trading.md](docs/packs/trading.md) | The trading pack |
| [docs/packs/marketing.md](docs/packs/marketing.md) | The marketing content pack |
| [docs/publishing.md](docs/publishing.md) | How a release is made and how a project installs it |

## Try it

In a project of your own:

```bash
themis init            # a starter themis.toml; every rule starts at warn
themis describe        # every rule, and what is not in force
themis check           # run the rules: exit 0 PASS, 1 FAIL, 2 REFUSE
themis prove           # show that each rule in force can fail
themis hooks install   # the agent hooks: before a tool call, session start, end of turn
```

In this repository:

```bash
uv run pytest -q                            # the tests, every rule's proofs among them
uv run python scripts/publish.py --dry-run  # every release stage; nothing is published
```

## The name

Themis is the Greek Titaness of law and good order. She holds the scales: the evidence decides,
not the speaker.
