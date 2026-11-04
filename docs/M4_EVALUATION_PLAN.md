# M4 Training and Evaluation Plan (M4.2 – M4.4)

Prepared in M4.1 on 4 November 2026. This is a plan, not a result: **no model has been trained, no metric exists, and no dependency has been added.** It applies [DATASET_GOVERNANCE.md](DATASET_GOVERNANCE.md) and the manifest in `experiments/manifests/`. Steps marked *needs owner decision* wait for the D04 answers in that document. [MASTER_DEVELOPMENT_PLAN.md](MASTER_DEVELOPMENT_PLAN.md) M4 remains the contract: no accuracy target is claimed here; any target is set by the owner after seeing the report.

## Stages

| Stage | Deliverable | Gate to start |
| --- | --- | --- |
| **M4.2** Data preparation and evaluation design | Verified local copies, cleaned record store, deduplicated clusters, contamination report, manual audit sample and result, frozen labels, grouped split with a frozen held-out test set, evaluation harness (no model) | D04 answers; package decision for the experiments environment |
| **M4.3** Baselines and comparison | TF-IDF + logistic regression, the comparison models, validation-based selection, one final held-out evaluation, reports | M4.2 accepted |
| **M4.4** Runtime adapter and integration | Checksummed artifact + manifest, `backend/models/` adapter, ingestion integration, TD-18 admission control, missing-artifact behavior, privacy scan | M4.3 report reviewed by the owner |

## M4.2 – data preparation

1. **Acquire and verify.** Follow the acquisition procedure in the governance document. Run `experiments/audit/dataset_audit.py`; every checksum and recorded value must reproduce. A mismatch stops the stage.
2. **Record store.** Write one local JSONL store outside Git, one record per source row: `record_id` (SHA-256 of source id + row index), `source`, raw `text`, source label, and (IMC) scam type and language. Raw text exists only here. Logs and reports use `record_id` and counts.
3. **Two normalizations, kept separate.**
   - *Matching normalization* (`fingerprints.normalize_text`): NFKC, lower-case, URLs and `<URL>` placeholders to one token, digit runs to `0`, punctuation removed. Used for duplicate, overlap and fixture checks only.
   - *Feature normalization*: NFKC; URLs, URL placeholders, emails and phone-like runs mapped to fixed tokens; case folding decided in M4.3 by validation; homoglyph and zero-width stripping. Defined once, shipped with the artifact, and applied identically at inference.
4. **Duplicates.** Exact duplicates and near-duplicates (5-character shingles, Jaccard ≥ 0.8, with a sensitivity report at 0.7 and 0.9) are grouped into clusters with union-find. Each cluster is one unit: it is never split across train, validation and test. A cluster whose members carry different labels is excluded and listed by `record_id`.
5. **Cross-dataset contamination.** All sources are clustered together, so a UCI text and its Mishra copy land in one cluster. The report lists clusters spanning sources and their label agreement. Munoz is never loaded. **Simulator fixtures:** `simulator_overlap` runs over the final store and every split and must return 0; the check fails the pipeline otherwise.
6. **Label freeze.** Apply the mapping rules. IMC classes marked `needs_review` go through the audit below. Output `labels.v1` (record → benign / spam / phishing / excluded) with the audit evidence.
7. **Manual precision audit** *(needs owner decision D04-Q5)*. For each IMC scam type in scope, draw a stratified random sample of unique clusters (proposed 200 per class; the interval width follows from this and is reported). Two reviewers label each (phishing / spam / benign / unclear) on the operator's machine with masked digits; disagreements are resolved by discussion. Report precision with a Wilson interval and Cohen's kappa. A class becomes `phishing` only if the owner's bound is met; otherwise it stays out. Also audit a sample of UCI spam containing a URL or a request for personal data, and of IMC `others`, to measure their composition.
8. **Hard negatives** *(needs owner decision D04-Q2)*. Required for a defensible evaluation: benign messages that look like phishing on the surface (OTP and verification codes, bank debit alerts, delivery updates, appointment reminders, links to real services, urgent but legitimate notices), and spam with links. Without a source for them, results must say that benign transactional SMS was not evaluated.
9. **Source-shortcut probe.** Train a throwaway classifier to predict *source* from text within the same label (for example UCI ham vs IMC "others" after review) and report its AUC. A high AUC means source or era is separable from content; M4.3 results then carry that warning, and per-source results are mandatory. This is a diagnostic, not a gate.
10. **Imbalance.** Report class counts after deduplication per split. Compare `class_weight='balanced'` with no weighting on validation; do not oversample the held-out set. Precision depends on prevalence, so reports include precision and PPV at several assumed prevalences, with the data's own prevalence labeled as an artifact of collection.

## Splits and the frozen held-out set

- **Unit and strata.** Clusters (step 4), stratified by source × label, plus a campaign key for IMC (named entity + scam type) so one campaign does not straddle splits where the data allows.
- **Proportions and seed.** Proposed 70 / 15 / 15 train / validation / test with a recorded seed; counts per cell are reported. A cell with fewer than 30 test records is reported as "insufficient" in subgroup tables.
- **Time.** IMC `time` holds a full date for only about 354 of 33,869 rows (the rest are times of day or free text), so a temporal split is not available; the report states this limit.
- **Freeze.** The split is written once as `sms_split.v1` (record fingerprints only, with its SHA-256). The held-out set is not used for training, feature work, hyper-parameters, thresholds or model choice. It is evaluated once per final candidate, and every use is logged. Any change to the data, labels or split creates `sms_split.v2`; v1 results stay attached to v1.
- **Leave-one-source-out view.** In addition to the pooled test, report performance on IMC-only positives against held-out negatives from each source, to expose source dependence.

## M4.3 – models and evaluation

**Primary baseline.** TF-IDF features (word 1–2-grams plus character 3–5-grams with word boundaries, sublinear TF) with L2-regularised logistic regression. The regularisation strength, case folding and n-gram ranges are chosen on validation only. A character n-gram component is included because SMS uses obfuscation, spacing and misspellings.

**Comparison models** (same features and splits):

| Model | Why |
| --- | --- |
| Linear SVM, then calibrated on validation | Tests whether the margin loss beats the logistic loss; the standard strong linear text baseline |
| Complement Naive Bayes on word TF-IDF | The classic SMS-spam baseline; a different inductive bias, cheap, a useful sanity check |
| Keyword/URL rule baseline | A floor that shows how much the learned model adds; MASTER plan notes keyword baselines are not proof of fraud |

A transformer is out of scope for M4 (no GPU requirement, no external download, explainability and artifact size); it can be proposed later against these baselines.

**Metrics** (held-out test, once, at the threshold(s) fixed on validation):

- Confusion matrix with TP, FP, TN, FN and the denominator of each rate.
- Precision, recall, F1, false-positive rate and false-negative rate; PR-AUC and ROC-AUC.
- False-positive rate separately for `benign` negatives and for `spam` negatives.
- Calibration: reliability bins, expected calibration error and Brier score. A score is called a probability only if calibration was fit on validation data and shown on the test set; otherwise it is labeled a ranking score.
- Confidence intervals: Wilson intervals for proportions; cluster bootstrap (resample clusters, 2,000 resamples, recorded seed) for F1, PR-AUC and ROC-AUC.
- Subgroups with the n ≥ 30 rule: source, scam type, message length bucket, URL present, language (English only in the first report).

**Error analysis.** False positives and false negatives are listed by `record_id` with their cluster, source, scam type and the model's top contributing features (n-grams after feature normalization, not message text). Human reading of messages stays local and masked. The report groups errors by cause (hard negative, ambiguous label, obfuscation, source artifact) and flags label noise found.

**Stress cases** required by the MASTER plan: benign OTP, obfuscated phishing (spacing, homoglyphs, leetspeak), a message in an unseen language, very short and very long texts, and a message with only a URL.

**Reproducibility.** Fixed seeds; a locked environment; one command reproduces the split, training and metrics; rerunning on the same inputs gives the same metrics; the report records the manifest version, split version, code commit, and the SHA-256 of the data files. Artifact digest must match the model manifest.

## Dependency proposal (not installed; needs owner decision D04-Q6)

For a separate, training-only dependency group (never the runtime image), checked on PyPI and OSV on 4 November 2026:

| Package | Version | Released | Python | Advisories (OSV) |
| --- | --- | --- | --- | --- |
| scikit-learn | 1.9.1 | 2026-09-10 | ≥3.11 | none |
| numpy | 2.5.4 | 2026-10-10 | ≥3.12 | none |
| scipy | 1.18.1 | 2026-08-21 | ≥3.12 | none |
| joblib (transitive) | 1.6.0 | 2026-08-31 | ≥3.10 | none |
| threadpoolctl (transitive) | 3.7.0 | 2026-09-15 | ≥3.9 | none |

Wheels exist for CPython 3.12 on macOS arm64 and Linux x86_64 for scikit-learn, numpy and scipy. M4.2 must re-check advisories and add the lockfile entries in the same change, and CI must install the group. Rationale: scikit-learn provides the vectorizers, linear models and calibration the baseline needs; there is no smaller approved facility. Also proposed: extend CI linting to `experiments/` (today only `backend/` is linted; the validator tests run in CI).

**Runtime avoids these packages.** The proposed artifact is a plain JSON file (feature configuration, vocabulary, IDF weights, coefficients, intercept, calibration parameters) plus a manifest, scored by a small pure-Python function in `backend/models/`. That keeps scikit-learn, numpy and any pickle or joblib deserialization out of the API process (AGENTS.md forbids loading untrusted pickles; a trusted pickle is still arbitrary code on load), and a parity test must show the pure-Python score matches the training library's within a stated tolerance. This design is confirmed in M4.4, not here.

## M4.4 – artifact and integration (preview)

Checksummed `model.json` and `model_manifest.json` (model version, training manifest version and file hashes, split version, feature configuration digest, metrics-report digest, code commit, creation date) under an operator-controlled `MODEL_DIR`. A missing, unreadable or mismatched artifact leaves the SMS stage `unavailable` exactly as today (null score, tier `unknown`). The adapter returns score, structured reason codes, model version and duration. The in-flight admission control and killable worker (TD-18) land in the same change that first runs the model inside ingestion. Replays keep the original result; nothing is recomputed. Persisted `signals` carry no free text (privacy scan).

## Acceptance for M4.2

The pipeline reproduces from raw files and manifest; checksums and recorded audit values match; duplicate clusters, contamination and fixture checks report zero cross-split leakage and zero simulator matches; the audit result and label freeze are recorded; the split is frozen with its hash; the harness runs end to end on a dummy scorer without touching the test set; and no model is trained. M4.3 starts only after the owner reviews this.

## Risks

Source and era confounding (G2) can inflate results and cannot be removed with these datasets; absent hard negatives the false-positive rate on real transactional SMS is unknown; LLM-assigned labels may carry systematic bias even after the audit; forum reports may over-represent certain brands and regions; and public-data results do not predict performance on KAVACH's deployment traffic. Every report states these limits next to its numbers.
