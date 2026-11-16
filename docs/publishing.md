# Publishing Themis locally

There is no hosted CI (continuous integration). One script on the owner's machine is the release
gate. It tests, builds, checks the built wheel, and copies it into a local package index that
every project on the machine installs from.

```bash
uv run python scripts/publish.py            # publish the current version
uv run python scripts/publish.py --dry-run  # every stage, into a throwaway index; nothing is kept
```

## The verdict

The pipeline ends with one word, and the exit code repeats it. A blocking exit always prints a
reason and a fix.

| Verdict | Exit code | Meaning |
| --- | --- | --- |
| PASS | 0 | The release is in the index and its receipt is written. |
| FAIL | 1 | A rule was broken: a test failed, or the version is already published. |
| REFUSE | 2 | The pipeline could not establish what it would publish: a dirty tree, no tests, a missing tool. |

## The stages

| Stage | What it does | It stops when |
| --- | --- | --- |
| preflight | Reads the version. Checks the folder is a clean git repository of its own. Checks the version is not published. | Not a repository, no commit, a dirty tree (REFUSE). The version is in the index or has a receipt (FAIL). |
| test | Runs the suite on the locked dependencies and reads its report. | A test fails (FAIL). Zero tests, only skips, or no report (REFUSE). |
| build | Builds one wheel and one source archive into an empty folder. | The build fails, or the files do not carry this name and version (FAIL). |
| verify | Installs the built wheel into a fresh environment, away from the source, and runs `themis --version`. | It does not install, or it answers with another version (FAIL). |
| publish | Copies both files into the index and compares their hashes. | A file with that name is already there (FAIL). |
| receipt | Writes `receipts/publish/<version>.json`. | — |

When a stage stops after files were copied, the copies are removed. The index never holds half a
release.

## Where things go

| Path | What it is | In git? |
| --- | --- | --- |
| `wheelhouse/` | The local package index: wheels and source archives, one pair per version | No. Built files, never source. |
| `receipts/publish/<version>.json` | The commit, the hashes of both files, the test counts, the tool versions, the time | **Yes. Commit it after each publish.** |

Choose another index folder with `--index <folder>` or the `THEMIS_INDEX` environment variable.

## Three rules

1. **A published version is never replaced.** To publish again, raise `__version__` in
   `src/themis/__init__.py`. That line is the version's only home; `pyproject.toml` reads it.
2. **A release is tied to one commit.** The tree must be clean. A release from a dirty tree pins
   nothing, so it is refused.
3. **The receipt is committed.** The next publish is refused until it is, because the tree is
   dirty.

## The first release

The folder is not a git repository yet, so a real publish is refused. Once you are ready:

```bash
git init
git add -A
git commit -m "Themis skeleton and local publish pipeline"
uv run python scripts/publish.py
git add receipts && git commit -m "receipt: 0.0.1"
```

## Using Themis in a project

Add the index and pin the package to it in that project's `pyproject.toml`. The path is relative
to that file.

```toml
[[tool.uv.index]]
name = "themis-local"
url = "../Themis/wheelhouse"
format = "flat"
explicit = true

[tool.uv.sources]
themis-guardrails = { index = "themis-local" }
```

Then:

```bash
uv add --dev themis-guardrails
uv run themis --version
```

`explicit = true` and the `sources` line mean this package can only come from the local index. A
package of the same name on a public index is never picked up in its place.

To move a project to a new release: publish it, then run `uv lock --upgrade-package
themis-guardrails` in that project.

One thing to know: the project's `uv.lock` records the index as an absolute path. On another
machine, or after moving the folders, run `uv lock` again.

## While developing Themis itself

Do not publish to try a change. Point one project at the source instead:

```bash
uv add --dev --editable ../Themis
```

Switch that project back to the index before its own next release.

## How the pipeline is tested

`tests/test_publish.py` attacks the pipeline's decisions: every refusal, the near misses that must
pass, and nine one-line bugs planted in the pipeline's own source and run in memory. Each planted
bug names the one case it must flip.

Checked end to end on 2026-11-16 with uv 0.11.21, on a scratch copy with its own repository: a
publish, a refusal on a dirty tree, a failure on a repeated version, a second version, and an
install into a separate project from the index.

## Going public later

The name `themis-guardrails` was free on PyPI and npm on 2026-11-16. A public release would add
one stage after `receipt` that uploads the same two verified files. Nothing else changes.
