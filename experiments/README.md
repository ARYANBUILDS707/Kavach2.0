# experiments/

Offline research and governance for KAVACH models. Nothing here is imported by the running API, and **no raw dataset, message text, trained model or credential is stored in this directory or in Git.**

| Path | Purpose |
| --- | --- |
| `manifests/sms_datasets.v1.json` | The versioned SMS dataset manifest (sources, licenses, checksums, label policy, permitted uses, decisions). Change it only by adding a new version. |
| `dataset_governance/manifest.py` | Schema and validator for the manifest. `backend/.venv/bin/python experiments/dataset_governance/manifest.py` validates the shipped file. |
| `dataset_governance/fingerprints.py` | Text normalization, fingerprints, near-duplicate measure and the simulator-fixture exclusion check. |
| `audit/dataset_audit.py` | Recomputes the manifest's measured values from local copies of the datasets and verifies their SHA-256. Prints counts only. |

Read [docs/DATASET_GOVERNANCE.md](../docs/DATASET_GOVERNANCE.md) first, then [docs/M4_EVALUATION_PLAN.md](../docs/M4_EVALUATION_PLAN.md).

## Rules

- Raw data lives in an operator-controlled directory outside the repository (the ignored `data/` directory or another path) and is verified against the manifest's SHA-256 before use. Never commit it, log it, or paste it into reports or issues.
- Reports show counts, record identifiers and fingerprints, not message text.
- The simulator scenarios (S01-S12) never enter training, validation or evaluation data.
- D04 is **pending**. The manifest keeps every dataset `pending`; the validator refuses to mark anything approved without the owner's decision reference.
- Tests: `backend/tests/test_dataset_manifest.py` (runs with the backend suite; `pytest` adds this directory to its path). CI does not lint this directory yet.
- Lint and format with the backend configuration from the `backend/` directory so import grouping matches CI: `cd backend && .venv/bin/ruff check --config pyproject.toml . ../experiments`.
