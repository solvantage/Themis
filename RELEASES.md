# Releases

This page is written by `scripts/publish.py` from the receipts in `receipts/publish/`. Do not
edit it by hand: a test fails when it differs from the receipts.

| Version | Published (UTC) | Commit | Tests | Wheel SHA-256 | Receipt |
| --- | --- | --- | --- | --- | --- |
| 0.3.0 | 2026-11-20 01:36 | `14f66159665f` | 2896 passed | `2aa4a5a1532e…` | [0.3.0.json](receipts/publish/0.3.0.json) |
| 0.2.1 | 2026-11-19 18:39 | `10ab7aa56de0` | 2699 passed | `09ad093a82c8…` | [0.2.1.json](receipts/publish/0.2.1.json) |
| 0.2.0 | 2026-11-19 16:16 | `e0d324f4037b` | 2070 passed | `a3dd3694b7a0…` | [0.2.0.json](receipts/publish/0.2.0.json) |
| 0.1.0 | 2026-11-16 06:18 | `594be2ad77c8` | 1721 passed | `104b78b84ff6…` | [0.1.0.json](receipts/publish/0.1.0.json) |
| 0.0.1 | 2026-11-16 04:14 | `6240b4cb0206` | 68 passed | `763a0a661085…` | [0.0.1.json](receipts/publish/0.0.1.json) |

## Install the latest release

The latest release is **0.3.0**, built from commit `14f66159665f51aabcfa4f28097d943370abe766`.

From the repository, pinned to that commit:

```bash
uv add --dev "themis-guardrails @ git+https://github.com/solvantage/Themis@14f66159665f51aabcfa4f28097d943370abe766"
```

From the local index, on the machine that published it: see
[docs/publishing.md](docs/publishing.md#using-themis-in-a-project).
