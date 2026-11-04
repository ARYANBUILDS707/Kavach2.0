# experiments/

Offline dataset governance, preparation and (from M4.3) training for KAVACH models. Nothing here is imported by the running API, `experiments/` has its **own locked environment** (`pyproject.toml`, `uv.lock`) that is never part of the API image, and **no raw dataset, message text, trained model or credential is stored here or in Git.**

| Path | Purpose |
| --- | --- |
| `manifests/sms_datasets.v2.json` | The current dataset manifest: sources, checksums, licenses, label policy, the owner's D04 decisions, the synthetic set, the promotion gate. `…v1.json` is the earlier, immutable record. |
| `manifests/sms_split.v1.meta.json` | Frozen split metadata: seed, algorithm, input hashes, the SHA-256 of the full assignment file, counts. |
| `reports/` | Aggregate data-quality report and label-audit status (counts and hashes only). |
| `dataset_governance/` | Manifest schema and validator; matching normalization, fingerprints and the simulator-fixture exclusion. |
| `sms_prep/` | The M4.2 pipeline: acquisition, feature normalization, clustering, records, synthetic hard negatives, label-audit bundle and evaluation, splits and the held-out guard, quality report, CLI. |
| `audit/dataset_audit.py` | Recomputes the M4.1 manifest's measured values (checksums + counts) from local copies. |
| `tests/` | 144 deterministic tests on small synthetic fixtures. |

Read [docs/DATASET_GOVERNANCE.md](../docs/DATASET_GOVERNANCE.md), [docs/M4_EVALUATION_PLAN.md](../docs/M4_EVALUATION_PLAN.md) and [docs/M4_2_DATA_PREPARATION_REPORT.md](../docs/M4_2_DATA_PREPARATION_REPORT.md) first.

## Commands

Run from `experiments/` (the locked environment is created on first use; add `--group train` for the M4.3 packages):

```sh
cd experiments
uv sync --project . --locked
uv run --project . --locked python -m dataset_governance.manifest   # validate the manifest
uv run --project . --locked python -m sms_prep acquire    # download + verify into ../data/m4/raw/ (ignored)
uv run --project . --locked python -m sms_prep verify     # offline checksum check
uv run --project . --locked python -m sms_prep build      # records, clusters, review bundle, splits, reports
uv run --project . --locked python -m sms_prep audit      # evaluate completed review sheets; exit 3 while BLOCKED
uv run --project . --locked pytest tests
uv run --project . --locked ruff check . && uv run --project . --locked ruff format --check .
```

`build` is deterministic: a second run reproduces the split metadata and report byte for byte, and it never overwrites review sheets that may hold annotations.

## Rules

- Raw data lives under the ignored `data/m4/` and is verified against the manifest's SHA-256 before use. Never commit it, log it, or paste it into reports or issues. Downloads are limited to the manifest's host allow-list and never print URLs.
- Reports show counts, record identifiers and fingerprints, not message text. Human review sheets are private (`data/m4/review/`) and the software never fills in a label.
- The simulator scenarios (S01-S12) never enter training, validation or evaluation data.
- Synthetic hard negatives are reported separately and never join the real-world test set.
- The test split is read only through `HeldOutGuard` for a logged final evaluation.
- A change to a file hash, label rule, permitted use or status is a new manifest version, never an edit in place.
