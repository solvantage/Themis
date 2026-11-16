# Themis

Guardrails as code for work done by AI agents.

Themis makes a repository checkable by a machine. Every number has a receipt, every piece of work
follows one sealed path, and every guard is proven able to say no.

It is a generic core. A field plugs in as a **pack**; a project plugs in as a **manifest**. The
core names no field and no project, and a test keeps it that way.

**Status:** the engine works. `themis init`, `describe`, `check`, `prove`, `explain` and
`config` run; a project can declare the checks it already has and get one report, with proof that
each can fail. The rules are being built gate by gate: [DESIGN.md](DESIGN.md) says which exist.
Every release, with its commit, its test count and the line that installs it, is listed in
**[RELEASES.md](RELEASES.md)**.

| Read | For |
| --- | --- |
| [RELEASES.md](RELEASES.md) | The releases, and how to install the newest |
| [DESIGN.md](DESIGN.md) | The core: laws, primitives, core rules, proofs, adoption |
| [docs/extending.md](docs/extending.md) | Parameters, external checks, local packs, writing a pack |
| [docs/packs/trading.md](docs/packs/trading.md) | The trading pack |
| [docs/packs/marketing.md](docs/packs/marketing.md) | The marketing content pack |
| [docs/publishing.md](docs/publishing.md) | How a release is made and how a project installs it |

## Try it

```bash
uv run pytest -q                            # the tests, among them the attacks on the pipeline
uv run python scripts/publish.py --dry-run  # every release stage; nothing is published
```

## The name

Themis is the Greek Titaness of law and good order. She holds the scales: the evidence decides,
not the speaker.
