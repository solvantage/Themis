# Releases

This page is written by `scripts/publish.py` from the receipts in `receipts/publish/`. Do not
edit it by hand: a test fails when it differs from the receipts.

| Version | Published (UTC) | Commit | Tests | Wheel SHA-256 | Receipt |
| --- | --- | --- | --- | --- | --- |
| 0.0.1 | 2026-11-16 04:14 | `6240b4cb0206` | 68 passed | `763a0a661085…` | [0.0.1.json](receipts/publish/0.0.1.json) |

## Install the latest release

The latest release is **0.0.1**, built from commit `6240b4cb02069664e92fbbd66d49c2f41fd44fdf`.

From the repository, pinned to that commit:

```bash
uv add --dev "themis-guardrails @ git+https://github.com/solvantage/Themis@6240b4cb02069664e92fbbd66d49c2f41fd44fdf"
```

From the local index, on the machine that published it: see
[docs/publishing.md](docs/publishing.md#using-themis-in-a-project).
