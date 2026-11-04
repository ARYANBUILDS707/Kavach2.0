# M4.2 Data Preparation Report

Dated execution report, 5 November 2026. It records what M4.2 did to the approved SMS data and what it could not do. Nothing here is a model result: no model was trained, and no label-audit result exists because no human review has been done. Procedures and policy are in [DATASET_GOVERNANCE.md](DATASET_GOVERNANCE.md) and [M4_EVALUATION_PLAN.md](M4_EVALUATION_PLAN.md); the machine-readable outputs are `experiments/manifests/sms_datasets.v2.json`, `experiments/manifests/sms_split.v1.meta.json` and `experiments/reports/`.

## Verdict

**CONDITIONAL.** Acquisition, cleaning, deduplication, the synthetic hard negatives, the leakage-safe split and the engineering are complete and verified. **Label approval is BLOCKED**: the blinded review bundle exists, but 0 of 2,970 required human reviews have been done, so no IMC class is promoted to phishing and M4.3 cannot start.

## Baseline

| Item | Evidence |
| --- | --- |
| Commit | `0845ed2` (`backend` = `origin/backend`) |
| GitHub Actions | run 41891028870: both jobs succeeded (read from the public GitHub API after polling the in-progress run to completion) |
| Working tree at start | One untracked file: `backend/tests/test_dataset_manifest.py`, the M4.1 governance test, which the M4.1 commit omitted, so CI never ran it. This milestone moved it to `experiments/tests/test_manifest.py`, where it runs in CI. |

## Owner decisions applied

Recorded in `sms_datasets.v2.json` with the manifest validator enforcing them: (1) IMC positives are provisional until audited; (2) UCI is the primary benign source and spam stays separate; (3) Mishra is audit reference only and Munoz is excluded (rejected); (4) explicitly synthetic benign hard negatives, reported separately; (5) wrong-number and relative-impersonation scams never count as phishing automatically; (6) an IMC class is promoted only when its independently reviewed precision has a 95% Wilson lower bound of at least 0.95; (7) a separately locked training environment.

## 1. Acquisition and checksums

| Dataset | Source | Result |
| --- | --- | --- |
| IMC25 smishing reports | GitHub raw, **pinned to commit** `a617556…` | 1 file, SHA-256 and size match |
| UCI SMS Spam Collection | UCI static download | 2 files match |
| Mishra & Soni (audit reference) | Mendeley, via a redirect to a signed S3 host | All 8 archive members, including the nested archive, match; **0 unknown members**; only the CSV is written to disk, and the scripts and PDFs are checksummed in memory and never written or run |
| Munoz & Islam | not acquired (excluded) | n/a |

The acquisition code refuses a changed, missing or unknown file, any host or redirect outside the manifest allow-list, non-https URLs, archive path traversal, oversized or over-numerous archive members, and overwriting a different local file. It never prints or stores a URL, because the Mendeley redirect carries a signed token. Mendeley rejected the default Python User-Agent with 403, so the downloader identifies itself as `kavach-dataset-acquisition/1.0`. Raw files live in the ignored `data/m4/raw/`; a second `build` and an offline `verify` both reproduce the same checks.

## 2. Two normalizations, and a finding that M4.1 missed

- **Matching normalization** (duplicates, overlap, fixtures): NFKC, lower case, URLs and placeholders to one token, digit runs to `0`, punctuation removed.
- **Feature normalization** (what a model will see; version 2): keeps case, punctuation and digits; maps URL forms, emails, phone numbers and dates/times to one token each; deletes other entity placeholders and redaction markers; idempotent.

**IMC was anonymized with an entity recognizer: 27,902 of 33,869 rows (82%) carry placeholders** such as `<NAMED_ENTITY>` (10,878), `<DATE_TIME>` (10,573), `<LOCATION>` (3,059), `<PHONE_NUMBER>` (2,898), `<US_DRIVER_LICENSE>` (1,774), `<US_BANK_NUMBER>` (944), `<NRP>`, `<EMAIL_ADDRESS>` and others, besides `<URL>`. UCI, Mishra and the synthetic data have none. Left alone, "contains a placeholder" separates IMC (all positives) from UCI (all benign). Feature normalization removes the marker from every source. **What remains**: IMC lost its names and places while UCI and the synthetic data keep theirs, and the share of date-time tokens still differs by source (UCI ham 9%, IMC classes 18–61%). M4.3 must test for it, not assume it is gone.

## 3. Deduplication and overlap (counts match the M4.1 audit)

| Dataset | Rows | Unique normalized texts | Exact-duplicate rows | Normalized-duplicate rows |
| --- | --- | --- | --- | --- |
| IMC25 | 33,869 | 23,567 | 8,540 | 10,302 |
| UCI | 5,574 | 5,099 | 403 | 475 |
| Mishra (reference) | 5,971 | 5,704 | 22 | 267 |
| Synthetic | 720 | 709 | 0 | 11 |

Shared unique texts: Mishra & UCI 4,924; IMC & Mishra 1; IMC & UCI 0; synthetic & any collected set 0.

**Clusters.** Records are grouped by exact and near-duplicate similarity (character 5-gram Jaccard) with an exact prefix-filter join, deterministic IDs and, for synthetic data, template families. Of 15,891 clusters, 8,399 are singletons, the largest holds 1,345 records and 4,896 span sources or the Mishra reference. 67 clusters whose members carry incompatible labels (for example one text labeled both ham and spam) and 434 reference-only clusters are excluded from the splits; 217 clusters mix IMC scam types and take the majority type.

**The clustering threshold is 0.7, not the 0.8 proposed in the plan.** At 0.8, the first build left 819 near-duplicate pairs (Jaccard 0.7–0.8) across splits, so I tightened it. Cluster counts: 14,816 at 0.6, 15,891 at 0.7, 17,126 at 0.8. At 0.7 no pair at 0.7 or 0.8 crosses a split; **870 of 49,381 pairs at 0.6 still do**, which is reported rather than hidden.

## 4. Manual label audit: BLOCKED

**What exists.** A reproducible (seeded), stratified, blinded review bundle in the ignored `data/m4/review/`: 1,485 items, one random representative per duplicate cluster, English only.

| Class | Clusters available | Sampled | Correct needed to pass (of sampled) |
| --- | --- | --- | --- |
| banking | 3,517 | 200 | 197 |
| delivery | 937 | 200 | 197 |
| government | 828 | 200 | 197 |
| telecom | 1,020 | 200 | 197 |
| others | 2,864 | 200 | 197 |
| wrong number | 202 | 200 | 197 |
| hey mum/dad | 45 | 45 | **cannot pass** (73 correct of 73 is the smallest passable sample) |

Besides the 1,245 gated items, the bundle holds 180 composition items (100 IMC spam and 80 UCI spam with links, which is all that exist) and 60 controls (40 UCI ham, 20 UCI spam) that are never counted in precision. The sheets show masked, neutralized text and no class; the class lives only in `answer_key.json`. Two reviewer sheets list the same items in different random orders, plus a rubric (`phishing`, `other_scam`, `spam`, `benign`, `unclear`) and an empty adjudication sheet.

**What does not exist.** Any human review. **Completed: 0 of 2,970 required reviews** (2 reviewers × 1,485 items), 0 disagreements adjudicated. The sheets' label and reviewer columns are empty (checked). The software never writes a label, calls a model or an LLM, or treats an automatic judgment as a review; its audit module imports no network, model or ML package (tested). With the gate at 0.95, a class needs about 98.5% observed precision at 200 items (197 correct), so the reviewers' care matters.

**Exact pending work.**
1. Two independent reviewers each label all 1,485 rows of `review_A.csv` and `review_B.csv` per `RUBRIC.md`, entering their own ID in `reviewer`.
2. An adjudicator resolves every disagreement in `adjudication.csv`.
3. Run `python -m sms_prep audit`; it computes per-class precision, Wilson intervals and Cohen's kappa, and writes `reports/label_audit_status.json`.

If the owner wants a smaller review, a smaller sample makes the gate harder: 100 items need 100 of 100 correct. Reducing `--per-class` changes the item set, so it requires a fresh bundle and is a decision for the owner.

## 5. Label decisions and exclusions

| Group | Decision now | After the audit |
| --- | --- | --- |
| IMC banking, delivery, government, telecom, others | `needs_review` (BLOCKED) | phishing only if the gate passes; otherwise excluded |
| IMC wrong number, hey mum/dad | `needs_review`; never automatic phishing | `hey mum/dad` cannot pass (45 clusters); `wrong number` only if audited as phishing |
| IMC spam, UCI spam | `spam` (a distinct class) | unchanged |
| UCI ham | `benign` | unchanged |
| Synthetic hard negatives | `benign` (synthetic) | unchanged |
| IMC non-English (11,711 rows) | experimental pool, not split | unchanged |
| IMC with no scam type (81 rows) | excluded | unchanged |
| Mishra | reference only: clustered, never split | unchanged |
| Munoz | not loaded | unchanged |

**Consequence for M4.3:** until at least one IMC class passes, there are no approved positives, so no phishing classifier can be trained or evaluated.

## 6. Synthetic hard-negative policy

720 messages from 72 hand-authored template families in 12 categories (login and payment OTPs, debit and credit alerts, account and card notices, delivery dispatch, out-for-delivery, delivered and re-slot, appointments, utility notices). They deliberately share phishing surface cues (links, urgency, "if this was not you", "do not share this code"). All of it is fictional and nonfunctional: invented institutions, couriers, merchants and clinics; links only on `.invalid`; phone numbers only in the reserved 555-01xx range; random codes; no real brand (checked against a 40-name deny-list); no `[SIMULATED]` marker a model could learn; 0 matches with the simulator S01–S12 texts. The corpus is deterministic for its seed and its SHA-256 is in the manifest, which the build verifies. Every record carries `origin=synthetic`. **Template families are the split groups**, so held-out templates test unseen wording. Synthetic data is never part of the real-world test set, and any metric on it is labeled synthetic. It cannot show how a model treats real transactional messages.

## 7. Leakage-safe split (`sms_split.v1`)

Cluster-level, stratified by `source:label`, deterministic from the seed (20261105) and cluster IDs, independent of input order and of label approval. A class that later fails the audit drops out of every split and no remaining cluster moves, so the test set can be frozen now. The assignment file's SHA-256 is in `sms_split.v1.meta.json`; the test split is readable only through `HeldOutGuard`, which refuses it for training, tuning and threshold selection, requires a model version, and logs each final evaluation (a procedural control, not a security boundary).

| Split | Clusters | Records | of which synthetic | Unique texts |
| --- | --- | --- | --- | --- |
| train | 9,432 | 20,872 | 500 | 14,348 |
| validation | 2,981 | 3,583 | 110 | 3,077 |
| test | 2,977 | 3,577 | 110 | 3,072 |

| Stratum | Unique texts | train / validation / test | Note |
| --- | --- | --- | --- |
| imc:banking | 6,136 | 4,295 / 921 / 920 | |
| imc:others | 3,491 | 2,444 / 524 / 523 | |
| imc:telecom | 1,294 | 906 / 194 / 194 | |
| imc:government | 1,243 | 870 / 187 / 186 | |
| imc:delivery | 1,195 | 837 / 179 / 179 | |
| imc:spam | 1,066 | 746 / 160 / 160 | |
| imc:wrong number | 210 | 147 / 32 / 31 | test cell near the minimum of 30 |
| imc:hey mum/dad | 54 | 38 / 8 / 8 | **insufficient** (test below 30) |
| uci:ham | 4,501 | 3,151 / 675 / 675 | |
| uci:spam | 598 | 418 / 90 / 90 | |
| synthetic:synthetic_benign | 709 | 496 / 107 / 106 | |

The largest deviation of any stratum from the 70/15/15 target is 0.37 percentage points; every stratum appears in every split.

**Contamination checks** (all on the final build): 0 clusters in more than one split; 0 normalized texts in more than one split; 0 near-duplicate pairs across splits at Jaccard 0.7 or 0.8 (870 of 49,381 at 0.6); 0 simulator fixture matches in the data; 0 collected messages reproduced in any committable file (a 30-character-prefix scan of 43,049 messages found three coincidental generic phrases: one everyday OTP sentence in a template and one test string, neither a collected message).

**Source concentration.** IMC is 73–79% of every split, UCI 19–24%, synthetic 2–3%. Because IMC provides all positives and UCI all collected benign text, source and label are the same variable for the main decision.

**Era.** UCI is 2003–2011; IMC is 2017–2024 (a full date is present for only ~354 IMC rows, so no temporal split is possible). Era is perfectly confounded with source, and so with label.

**Descriptive artifacts that show the confound** (shares of records; not model output): median length is 52 characters for UCI ham against 123–156 for the large IMC classes; a URL is present in 0.3% of UCI ham against 32–58% of the main IMC classes; 55% of UCI spam contains a phone-like number against 5–23% of IMC classes.

## 8. Is a source-shortcut test feasible?

**Only partly.** A test needs the same label from two collected sources with enough held-out data (at least 30 unique texts in both validation and test). In this data that holds for **spam** (UCI vs IMC: 90 and 160 test texts). It does not hold for **benign** (UCI alone; synthetic is not collected) or for the **phishing candidates** (IMC alone), so the decisive boundary cannot be probed. The spam probe would show whether text alone reveals the source or era within one label, and M4.3 should run it as a diagnostic. **Grouped splitting does not solve source confounding**, and nothing in this milestone claims it does.

## 9. Engineering

Added: `experiments/sms_prep/` (acquisition, feature normalization, clustering, records, synthetic generator, review, splits, quality, CLI), a separately locked `experiments/pyproject.toml` and `experiments/uv.lock` (20 packages; the `train` group scikit-learn 1.9.1, numpy 2.5.4 and scipy 1.18.1 is not installed by default and OSV reports no advisories for any of the 19 third-party packages), manifest v2, split metadata, the quality report, 144 tests, and CI steps for the experiments lockfile, tests and Ruff. The fixture-exclusion code now reads the simulator catalog as JSON, so `experiments/` has no dependency on the backend package. `backend/pyproject.toml` returned to its pre-M4.1 content.

Four mutation probes (relax reviewer independence, allow unknown archive members, let `test` be read for training, lower the gate to 0.80) each made the suite fail.

## 10. What M4.3 needs first

1. **Completed human review** (section 4), the audit run, and at least one IMC class passing the gate. Otherwise there are no approved positives.
2. An owner decision on how to proceed if every class fails or most do (for example a different positive source, or a smaller gated class set).
3. The training environment installed on demand: `uv sync --project experiments --locked --group train`.
4. A decision on whether to re-cluster at 0.6 to close the remaining 870 pairs (this would create `sms_split.v2` before any model sees the data).
5. The M4.3 source-probe on spam, per-source reporting for every metric, and the placeholder asymmetry (section 2) examined before any result is believed.

## Reproduce

From `experiments/` with the locked environment (`uv sync --project experiments --locked`): `python -m sms_prep acquire`, `python -m sms_prep build`, `python -m sms_prep audit` (exit 3 while BLOCKED), then `uv run --project experiments --locked pytest experiments/tests`. A rebuild produces byte-identical split metadata and report.
