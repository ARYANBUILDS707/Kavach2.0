# KAVACH SMS Dataset Governance (M4.1)

Dated research record, 4 November 2026, for D04 (SMS data). It states what was verified about four candidate datasets, what KAVACH may do with each, how labels map to the task, and what the owner still has to decide. **D04 is not approved by this document.** It proposes a scoped approval and lists the conditions. The machine-checkable counterpart is [experiments/manifests/sms_datasets.v1.json](../experiments/manifests/sms_datasets.v1.json); the training and evaluation procedure is in [M4_EVALUATION_PLAN.md](M4_EVALUATION_PLAN.md).

## How this was verified

| Step | What was done |
| --- | --- |
| Source pages | Each landing page (Mendeley ×2, UCI, GitHub) was fetched and read for title, authors, version, DOI, license, size and labels. |
| Files | All four datasets were downloaded on 4 November 2026 into a scratch directory outside the repository. SHA-256, byte size and row counts were measured on the actual files. |
| Statistics | Duplicate, overlap, near-duplicate and label-consistency counts were computed with `experiments/audit/dataset_audit.py`. It reproduces every value recorded in the manifest (and fails on a wrong file). |
| Papers | The IMC 2025 paper (UCL Discovery PDF) was read for labeling method, scale and ethics. The Mishra & Soni and Munoz & Islam records have no associated paper in the pages read. |
| Not verified | The Mendeley pages list their files empty to the page fetcher (the archives were obtained from the public download endpoint instead). The IMC repository's `LICENSE.txt` and `time_day.csv` were not read. The IMC paper's inter-annotator figures and GPT-4o validation were not independently checked. Message text was inspected only as a few masked, truncated samples to understand label meaning; none is quoted here or stored. |

## Candidate comparison

| | IMC 2025 smishing reports | UCI SMS Spam Collection | Mishra & Soni 2022 | Munoz & Islam 2025 |
| --- | --- | --- | --- | --- |
| Source | GitHub `reportsmishing/Smishing-Dataset-IMC25` @ `a617556` (12 Sep 2025) | UCI repository, dataset 228 | Mendeley Data `f45bkkt8pr` v1 | Mendeley Data `vmg875v4xs` v1 |
| Citable work / DOI | IMC '25 paper, 10.1145/3730567.3764431 (dataset has no DOI of its own) | 10.24432/C5CC84 | 10.17632/f45bkkt8pr.1 | 10.17632/vmg875v4xs.1 |
| License (as stated) | CC BY 4.0 (README) | CC BY 4.0 (UCI page); the bundled readme states older terms: free use, authors' copyright, please cite and notify, no warranty | CC BY 4.0 | CC BY 4.0 |
| Intended use (as stated) | Smishing infrastructure and tactics research | SMS spam research and filtering | ML and pattern recognition for SMS phishing | Training and testing spam and smishing detection, LLM tuning |
| Records (measured) | 33,869 (22,078 English) | 5,574 | 5,971 | 10,191 |
| Classes (measured) | Scam types only; no benign class: banking 15,277, others 6,922, delivery 3,810, government 3,248, telecom 2,226, spam 1,710, wrong number 332, hey mum/dad 263, empty 81 | ham 4,827 / spam 747 | ham 4,844 / spam 489 / smishing 638 | ham 3,397 / spam 3,397 / smishing 3,397 |
| Origin | User-posted screenshots from five public forums (2017-2024), text read from images by an LLM | Human-collected: UK spam forum, Singapore university volunteers, a thesis, an earlier corpus (2003-2011) | Largely the UCI messages plus "images obtained from the Internet" converted to text | Described as LLM-created, trained on the Mishra & Soni data; real/generated mix and model unstated |
| Label provenance | `scam_type` assigned by GPT-4o, validated by two humans on 150 English texts (paper: kappa 0.94 human-human, 0.93 GPT-4o vs consensus for scam type) | Defined by the compilers (ham/spam) | Undocumented ("label by extraction source") | Derived from the Mishra & Soni labels |
| Unique texts after normalization | 23,567 (English 14,875); 8,540 exact-duplicate rows | 5,099; 403 exact-duplicate rows | 5,704; 22 exact-duplicate rows | 7,274; 2,200 exact-duplicate rows |
| Overlap with others (unique texts) | UCI 0, Munoz 0, Mishra 1 | Mishra 4,924 (86% of Mishra, 97% of UCI), Munoz 3,469 | UCI 4,924, Munoz 4,030 | Mishra 4,030, UCI 3,469; 1,402 near-duplicates of Mishra, 1,071 of UCI |
| Language | 66 languages reported; English 65% of rows | English (8.7% of rows with non-ASCII characters) | English | Not stated |
| PII | Sender IDs withheld; text may hold names or fragments (427 phone-like, 6 email-like) | Real personal messages from volunteers; 440 phone-like (nearly all spam) | Same as UCI plus unknown additions | 4,310 phone-like texts |
| Genuine phishing evidence | **Yes**: real reported messages, wide scam coverage | Spam only; no phishing label | **Weak** (see finding 1) | **No** (generated and duplicated) |

## Findings that drive the decision

1. **Mishra's "smishing" label is not clean phishing ground truth.** Of its 448 unique smishing texts, 267 are texts the UCI corpus labels *spam*, relabeled; 37 texts carry both labels inside the file. Only 181 unique smishing texts are absent from UCI. The sampled relabeled texts are premium-rate and prize offers, which are spam rather than credential or payment phishing.
2. **Mishra is not an independent dataset.** 86% of its unique texts are in UCI. Using both as separate sources double-counts messages and leaks across any split.
3. **Munoz & Islam is unsuitable for evaluation.** All 3,397 ham rows repeat Mishra texts. Its smishing class has 2,237 unique texts of which 336 match Mishra smishing exactly and 1,402 of its unique texts are near-duplicates of Mishra texts, which is consistent with LLM-generated variants of a small seed set. It carries 2,200 exact-duplicate rows. Its perfect 1:1:1 balance is an artifact. The record does not name the generator.
4. **IMC25 is the only candidate with real, recent, varied phishing.** Its limits are: no benign class; labels from an LLM validated on 150 English texts; reports can be misjudged by reporters (the paper notes that forum reports are unverified); text is machine-read from screenshots; 157 English unique texts carry more than one scam type; the `others` bucket holds 6,922 rows of unknown composition.
5. **IMC replaces URLs with a `<URL>` placeholder** in 9,401 of 22,078 English rows (43%), while no other source does. A model could learn the placeholder as a phishing marker. All sources must map URLs and placeholders to one token (the normalization in `fingerprints.py` and the plan do), and the plan tests for source shortcuts.
6. **No candidate contains modern benign transactional SMS** (OTP codes, bank alerts, delivery updates). The only benign data is 2003-2011 personal conversation. Combined with positives from 2017-2024 forum reports, any classifier can separate the two by era and style. This gap (G1/G2) is the main threat to the validity of M4 results and is not solved by any listed dataset.
7. **Licensing is permissive on paper but layered.** All four state CC BY 4.0; the UCI readme carries older, different terms; derived sets inherit upstream terms. Attribution and the citations in the manifest are mandatory. This is a compliance reading of public statements, not legal advice.

## Recommendation (for the owner to approve)

| Role | Dataset | Condition |
| --- | --- | --- |
| **Primary positive source** | IMC25 (English subset first) | Only after the M4.2 manual precision audit passes per scam type; the `others`, `wrong number` and `hey mum/dad` classes need owner scope decisions. |
| **Primary negative sources** | UCI ham (benign) and UCI spam (spam) | Used as negatives only; modern transactional negatives must be added (see gaps). |
| **Audit reference only** | Mishra & Soni | Used to measure overlap and contamination; its 181 non-UCI smishing texts and 461 non-UCI ham texts may be reconsidered after manual review. |
| **Excluded** | Munoz & Islam | Never in validation or evaluation; at most a separately reported augmentation experiment if the owner later asks. |

**D04 stance.** The evidence supports a *scoped* approval of IMC25 and UCI for SMS training and evaluation work, with the label policy below, the manual precision audit as a gate, and a hard-negative source decided (D04-Q2). It does not support approving Mishra for training, approving Munoz at all, or claiming that the combined data represents real-world traffic. The manifest therefore keeps every dataset `pending` and `d04_sms: pending`.

## Task and label policy

**Target.** *SMS phishing (smishing) risk*: the message tries to make the recipient click, call, reply, pay or reveal credentials or personal data under false pretences. It is not generic spam. The scored label is `phishing`.

**Labels.** `benign`, `spam`, `phishing`, `needs_review`, `excluded`. Source labels are never merged silently.

| Source label | Maps to | Why |
| --- | --- | --- |
| UCI ham | benign | Personal chat; not transactional |
| UCI spam | spam | Premium-rate and prize spam; a spam message with a link or a request for personal data goes to the audit sample |
| IMC banking, delivery, government, telecom | needs_review → phishing only after the audit | LLM labels, validated on 150 texts |
| IMC wrong number, hey mum/dad | needs_review (owner scope decision D04-Q3) | Social-engineering fraud, not credential phishing |
| IMC others | needs_review | Composition unknown |
| IMC spam | spam | Reported unwanted messages, not phishing |
| IMC empty | excluded | No label |
| Mishra ham / spam | benign / spam, after removing exact and near duplicates of UCI | Not independent |
| Mishra smishing | needs_review | See finding 1 |
| Munoz (all) | excluded | See finding 3 |

The validator enforces: no source label maps automatically to `phishing` (only a rule marked `human_verified`), `spam` can map only to `spam` or be excluded, and `needs_review` needs a review plan.

**Proposed use of `spam`.** Keep three labels in all data and reports. The first model scores P(phishing) with `benign` and `spam` as negatives, and reports the false-positive rate on each negative class separately, so spam-vs-phishing confusion stays visible. This is a proposal (D04-Q4).

**Exclusions beyond label mapping.** Non-English rows (11,791 in IMC) stay out of the first baseline as an experimental pool (English first, per ARCHITECTURE.md). Rows whose normalized text carries two labels are excluded until reviewed. Exact and near duplicates are collapsed to one record before any split.

## Real versus synthetic data

| Kind | Datasets | Rule |
| --- | --- | --- |
| Genuine collected data | UCI, IMC25 (user reports), the personal messages in Mishra | May supply training, validation and held-out data after approval |
| LLM-generated or mixed with unknown share | Munoz & Islam | Never validation or held-out data; excluded from the baseline |
| Simulator fixtures (S01-S12) | `scenarios_v1.json` | Demonstration data only; never in any training, validation or evaluation set |
| Any future synthetic hard negatives | Authored under D04-Q2 if approved | Labeled synthetic in the manifest; used for stress tests, reported separately, never mixed into the held-out set unless the owner decides so |

## Manifest and governance

The manifest (`experiments/manifests/sms_datasets.v1.json`, schema in `experiments/dataset_governance/manifest.py`) records for every dataset: title, creators, publication date, version, DOI, source and download URLs, citation, acquisition date, per-file name, SHA-256, size and rows, license (SPDX id, evidence URL, caveats), origin, label provenance, languages, observed source-label counts, the label-mapping rules, measured audit values, privacy assessment and required handling, status, permitted uses, limitations and approval state. It also records the task, the storage and reporting policy, the held-out rule, the simulator exclusion, the coverage gaps and the open decisions.

- **Versioning.** A change to a file hash, label rule, permitted use or status is a new manifest version (`sms_datasets.v2.json`), never an edit in place. Splits and results cite the manifest version they used.
- **Acquisition procedure.** Download from `download_url` into an operator-controlled directory outside the repository (`data/` is ignored), verify SHA-256 against the manifest, then run `experiments/audit/dataset_audit.py`. A hash mismatch stops the work; the dataset's publisher may have changed it.
- **Checks.** `backend/tests/test_dataset_manifest.py` validates the shipped manifest and proves the validator rejects 20+ ways of breaking the policy. CI runs it with the backend tests. CI does not lint `experiments/` yet (proposed for M4.2).

## Privacy policy

- Raw data never enters Git (`.gitignore` already excludes `data/**`, `datasets/`, `raw_data/`, `artifacts/`, `*.pkl`, `*.joblib`), and never appears in application logs, test output, reports, issue text or the manifest.
- Reports and error analyses cite record identifiers and fingerprints and show counts. Manual review happens locally with digit runs, emails and URLs masked.
- Only the `text` field is used. Sender IDs, phone numbers, network names and other metadata are not loaded into features, logs or artifacts.
- Data is public, third-party and may contain personal fragments. It is used only for the research purpose in the manifest. It is not combined with KAVACH subscriber data, not re-published and not sent to any external or hosted service (including LLMs). The IMC labels came from a hosted LLM at the dataset authors' side; KAVACH does not repeat that step.
- Removal: if a publisher withdraws a dataset or a data subject asks for removal, the dataset is marked excluded in a new manifest version and any split or model derived from it is retrained or retired.

## Coverage gaps and options (no choice is made here)

| Gap | Options for the owner |
| --- | --- |
| G1 No benign transactional SMS | (a) Author a small synthetic set of OTP, bank-alert, delivery and appointment messages with clear synthetic labeling, used for stress tests and reported separately. (b) Verify and approve a further public dataset. A search found candidates that this work did **not** verify: the Mendeley "Financial scams detection dataset" (English/Bangla, license not confirmed), MOZ-Smishing (AfricaNLP 2025, mobile-money fraud, license not confirmed) and Smishtank (smishing only, CC BY-NC-SA 4.0, which restricts non-commercial use). MIMICS-3500 is smishing-only and available on request. |
| G2 Source and era confounding | Mitigate in evaluation (source-balanced reporting, source-shortcut test, hard negatives); it cannot be removed with this data. |
| G3 URL placeholders | One URL token for all sources; no URL-domain features from IMC. |
| G4 English only | Hindi/Hinglish stay experimental with no candidate. |
| G5 No deployment-like sample | State the limitation in every report; any later real data needs its own decision. |

## Open decisions

| ID | Question | Recommendation |
| --- | --- | --- |
| D04-Q1 | Approve IMC25 and UCI as primary, Mishra as audit reference, Munoz excluded? | Yes, as a scoped approval with the precision audit as a gate |
| D04-Q2 | Which source of benign transactional hard negatives? | (a) an authored synthetic set, labeled synthetic and reported separately |
| D04-Q3 | Are wrong-number and relative-impersonation scams "phishing"? | Keep them a distinct sub-label; include in the scored class only if the owner wants fraud-intent coverage |
| D04-Q4 | Spam kept as its own class and scored as a non-phishing negative? | Yes |
| D04-Q5 | Minimum audited precision for promoting a `needs_review` class | The owner sets it after seeing the audit; this work proposes a lower confidence bound reported with a Wilson interval and does not pick a number |
| D04-Q6 | ML dependency set | See [M4_EVALUATION_PLAN.md](M4_EVALUATION_PLAN.md) |

## Limits of this record

Findings 1 to 3 rest on normalized text matching and Jaccard similarity at a 0.8 threshold; other thresholds give other counts. The sampled-text judgments about what the relabeled messages are come from a handful of masked samples, not a systematic review (the M4.2 audit is the systematic one). A published systematic review states 4,753 shared instances between Mishra and UCI using its own matching; this audit's 4,924 unique shared texts uses a looser normalization, and the difference is expected. No claim here concerns model performance: no model has been trained.
