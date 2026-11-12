# M4.2 Data-Quality Review (before M4.3)

Dated review, 5 November 2026, of the frozen split `sms_split.v1` and of the label-audit workflow, at commit `ce63aca` (CI run 41900502306, both jobs passed). It changes **no split**: the frozen assignment file (`ef452e8c…`), its metadata, the review items and the blank sheets are byte-identical before and after. It trains no model and contains no human annotation.

## Summary

| Question | Answer |
| --- | --- |
| Are the 870 cross-split pairs at similarity 0.6 real duplicates? | **Yes, almost all.** About 87% at minimum and probably 98% are templated campaign variants of the same message; the rest are short conversational messages that share an everyday phrase. |
| Does it stop at 0.6? | **No.** All 30 hand-checked pairs in the 0.5–0.6 band and all 24 in the 0.4–0.5 band were templated too. |
| How much of the held-out test set is affected? | In v1, **5.3% of test texts have a training neighbour at similarity ≥ 0.6, 10.8% at ≥ 0.5 and 17.2% at ≥ 0.4**. For banking, the dominant class, it is **10.7%, 18.0% and 26.9%**. |
| Retain v1 or create v2? | **Create `sms_split.v2` (campaign-level grouping at Jaccard 0.4) before any model reads data**, if the owner approves. It is free now and becomes impossible once a model has seen the test set. |
| Is the review workflow sound? | It had **eight real gaps, now fixed and tested** (adjudicator independence, duplicate rows, mixed reviewer IDs, unverified answer key, spreadsheet files, malformed sheets, unused controls, no record-weighted sensitivity). The Wilson gate arithmetic verified correct. The rubric was ambiguous in places and is now version 2. |
| What blocks M4.3? | Unchanged: **0 of 2,970 human reviews are done.** |

Sections 1–6 record the review as delivered. The owner's decisions and the follow-up work (split v2 created as *proposed*, cluster-weighted gate, calibration pilot) are in [section 7](#7-follow-up-owner-decisions-applied-5-november-2026).

## 1. The cross-split pairs at 0.6

**Method.** The frozen split groups texts at character-5-gram Jaccard 0.7. I listed every pair at ≥ 0.6 whose texts sit in different splits, computed aggregate statistics only, and hand-checked masked samples drawn **only from train and validation pairs** (digits masked, text truncated, similarity metrics hidden until after judging). Test text was never displayed, and the 453 test-involved pairs are covered by the aggregate statistics and by extension from the same generating process. The judgments are mine, are not human annotations, are not part of the label audit, and are recorded in `experiments/reports/m4_2_pair_spot_check.json`.

**Criteria.** *Templated*: the same message frame, with differences limited to slot values (brand or organisation names, amounts, codes, URLs, dates), spelling variation, fragments of the same message, or a short prefix or suffix. *Generic*: different sentences sharing only boilerplate or an everyday phrase. *Unclear*: too short to tell.

**What the 870 pairs are.**

| Property | Value |
| --- | --- |
| Pairs by splits | test/train 420, train/validation 417, test/validation 33 |
| Within one stratum / across strata | 813 / 57 |
| Between datasets | IMC–IMC 844, UCI–UCI 25, IMC–UCI 1 |
| Largest stratum pair | imc:banking–imc:banking 533 |
| Char-Jaccard quartiles (min, q1, median, q3, max) | 0.600, 0.613, 0.630, 0.657, 0.699 (by construction) |
| Sequence-ratio quartiles | 0.425, 0.826, 0.862, 0.887, 0.973 |

**Hand-check results** (train–validation pairs only):

| Sample | Pairs | Templated | Generic | Unclear |
| --- | --- | --- | --- | --- |
| 0.6–0.7 band (4 sequence-ratio strata × 9) | 36 | 33 | 2 | 1 |
| of which IMC-involved | 33 | **33** (Wilson 95% lower bound 0.896) | 0 | 0 |
| every UCI–UCI train–validation pair | 11 | 4 | 6 | 1 |
| 0.5–0.6 band | 30 | **30** (lower bound 0.886) | 0 | 0 |
| 0.4–0.5 band | 24 | **24** (lower bound 0.862) | 0 | 0 |

Extrapolating the IMC result to the 845 IMC-involved pairs gives **at least ~757 (87%) templated**, probably ~98%. The 25 UCI pairs are mostly generic short chat. What the templated ones are: the same scam campaigns reworded and re-branded — "your account will be blocked, update your PAN card" under SBI, HDFC, Paytm and other names, electricity-disconnection notices, KYC suspensions, SIM verification, credit-card points, USPS package delays.

**The similarity scores are poor discriminators.** Templated pairs span sequence ratios 0.60–0.94, and the three generic pairs scored 0.78–0.85. I therefore did **not** build a "templated" classifier; the judgment is a hand check, and the measures are descriptive only.

**Why it matters.** IMC is dominated by a few prolific campaign families. Clustering at 0.4, **one family holds 50.8% of all banking records and 26.2% of all IMC records**. A model can score well on a random test split by recognizing a campaign it saw in training, so the v1 headline numbers would be optimistic mainly for banking.

## 2. Retain v1 or create v2?

All figures are dry runs from `python -m sms_prep pairs`; nothing was written. "Texts" are unique normalized texts.

| | v1 (frozen, 0.7) | v2 @ 0.6 | v2 @ 0.5 | v2 @ 0.4 |
| --- | --- | --- | --- | --- |
| Clusters | 15,891 | 14,816 | 13,843 | 12,884 |
| Largest cluster (records) | 1,345 | 3,687 | 4,017 | 5,822 |
| Records assigned | 28,032 | 27,877 | 27,706 | 27,554 |
| Test texts with a train neighbour ≥ 0.4 / 0.5 / 0.6 | 17.2% / 10.8% / 5.3% | 12.0% / 6.2% / 0 | 6.4% / 0 / 0 | **0 / 0 / 0** |
| Test banking texts with a train neighbour ≥ 0.4 | 26.9% | 16.7% | 9.6% | **0** |
| Cross-split pairs ≥ 0.4 | 19,181 | 5,982 | 1,169 | **0** |
| Records that change split | n/a | 26.1% | 28.3% | 29.9% |
| Largest stratum deviation from 70/15/15 | 0.37 pp | 0.37 pp | 0.37 pp | 0.19 pp |

**Recommendation: create `sms_split.v2` at 0.4.** The evidence says campaign variants stay templated at least down to 0.4, the cost grows slowly (30% of records move instead of 26%, 1.7% fewer records survive the label-conflict filter), and the benefit is the only option with no measured training neighbour at ≥ 0.4. Retaining v1 would leave a quarter of the banking test set recognizable from training.

**Why now.** `data/m4` holds no test-access log, so the v1 test set has never been read, and a v2 replaces it without breaking the freeze rule (a test set that has influenced a model must not change). Once M4.3 evaluates anything, this window closes. v1 stays on disk as the immutable record; v2 is a new file, never an edit.

**What v2 would change, and what it would not.**
- *Evaluation becomes campaign-level.* The dominant family (about half of banking) lands in one split — most likely train — so the banking test set contains *other* campaigns. That is the harder, more honest question ("does it catch campaigns it has not seen?"), and the one deployment poses. Metrics will look worse than on v1, and that is the point.
- *Residual risk remains.* Nothing below 0.4 was examined, and templated reuse can sit below any threshold. M4.3 must therefore report an overall result **and** the leakage profile (the share of the test set with a training neighbour at each level), plus per-campaign-family results, and must not call the split leak-free.
- *The review bundle needs no regeneration.* The audit samples one representative per 0.7-level cluster, independently of the split, so the human review can start now.
- *A few classes shrink.* Clusters that mix incompatible provisional labels at the looser threshold are excluded (478 fewer records than v1, 1.7%).

**Implementation if approved.** Parametrize the clustering threshold and split version in `build` (the code and tests already take both), write `sms_split.v2.meta.json` beside v1, re-run the quality report, and record the owner's approval in the split metadata. About one hour of work; no data re-acquisition.

**Alternatives considered.** *Retain v1 and document*: possible, but it knowingly keeps the leak. *Prune the v1 test set* of items with a close training neighbour: keeps the freeze literally but leaves a test set biased toward rare, atypical messages and discards 17% of it (27% of banking). *v2 at 0.6 or 0.5*: leaves 12% or 6.4% of test texts with a ≥ 0.4 neighbour in train.

## 3. The review workflow, verified

### The Wilson acceptance gate — correct

The implementation matches an independent derivation to 1e-8 (95/100 → 0.88825–0.97846; 5/10 → 0.23659–0.76341). At n = 200, 197 correct passes (lower bound 0.9568) and 196 fails (0.9497); at n = 100 only 100 of 100 passes; the smallest sample that can ever pass is 73. `hey mum/dad` has 45 clusters and cannot pass; `wrong number` (202) can pass only if reviewers actually label it phishing, which the rubric makes unlikely, consistent with owner decision 5. Regressions are covered by tests and by a mutation probe that lowered the gate.

### Defects found and fixed (each reproduced by a failing test first)

| # | Gap | Effect before | Fix |
| --- | --- | --- | --- |
| 1 | Adjudicator could be one of the two reviewers | A disagreement could be settled by one of the people who disagreed | Adjudicator must differ from both reviewers, else BLOCKED |
| 2 | Duplicate rows for one item: the last silently won | Conflicting labels could flip a result | Duplicates make the item ambiguous and BLOCK the audit |
| 3 | A sheet could mix several reviewer IDs | "Two independent reviewers" was not guaranteed per sheet | Exactly one ID per sheet, distinct between sheets |
| 4 | Answer key never checked against its recorded hash | An edited key could change class results | Hash must match the bundle metadata, else BLOCKED |
| 5 | Spreadsheet exports with a byte-order mark crashed the reader | A real-world Excel save would break the audit | `utf-8-sig` read |
| 6 | Missing columns or file crashed with a traceback | Same | BLOCKED with the reason in the report |
| 7 | Controls and composition items were never evaluated | No sign of careless review | Per-reviewer control accuracy, with a warning below 90% (informational; the gate is unchanged) |
| 8 | Only cluster-weighted precision | Large campaigns count once | Record-weighted precision is reported as a **sensitivity**, never the gate |

Unknown item rows now also block (a mistyped ID cannot silently vanish), and kappa is reported for gated items as well as all items.

### The rubric — ambiguous in places, now version 2

Version 1 required "posing as a trusted party" but did not say what to do with prize offers, one-time-code messages, or messages that state a problem and demand action without naming anyone, so reviewers would have disagreed on exactly the borderline cases. Version 2 is a three-step decision order (asks for action? poses as someone trusted? fraud anyway?), explicit edge-case rules, seven fictional worked examples, and the working rules (work alone, no tools or models, one reviewer ID per sheet, leave blank rather than guess). It was applied to the private bundle through the normal `build`, which refuses to change a rubric once any annotation exists.

### Remaining limits (not fixable in software)

- **Independence is by ID.** The software cannot tell that two IDs are one person. The owner must assign two people and an adjudicator who is a third person.
- **Blinding is partial.** Reviewers never see the class or source, but 84% of items come from IMC scam classes, so a reviewer may infer a high base rate; 60 controls only partly counter that.
- **Unit of the estimate.** Precision is per duplicate cluster (0.7 level): each campaign variant counts once. Record-weighted precision may differ, and is now printed beside it; whether the *gate* should use it is an owner decision, to be made before reviews begin because it would change the sample (probability-proportional sampling).
- **Seven classes are tested at 95% each.** The family-wise error rate is higher; the owner's rule is per class and is applied as written.
- **A pilot is advisable.** The sheets list the same items in different orders, so a calibration round on a separate small set (excluded from the audit) is the way to check agreement before the full run. The software does not generate one yet.

## 4. Minimal remediation

| Item | State |
| --- | --- |
| Review-evaluator defects 1–8 | **Done**, 17 new tests, mutation-checked |
| Rubric v2 | **Done** (private bundle updated; no annotations existed) |
| Pair-review tooling (`python -m sms_prep pairs`) and spot-check record | **Done**, reproducible |
| Split v2 at 0.4 | **Needs the owner's decision**; not created |
| Gate unit (cluster vs record weighting), pilot calibration set | **Owner decisions**, before review starts |

## 5. Exact outstanding human-review actions

All files are in the ignored `data/m4/review/` (they contain message text; do not copy them into Git, chat or tickets).

1. **Decide first**: (a) whether to create split v2 (does not block the review); (b) whether precision should be cluster-weighted (current) or record-weighted (changes the sample); (c) whether to run a pilot.
2. **Assign three different people**: Reviewer A, Reviewer B, and an adjudicator who is neither.
3. **Each reviewer works alone** on their own sheet, following `RUBRIC.md` (version 2): label every one of the **1,485 rows** of `review_A.csv` / `review_B.csv` (A and B each fill one), entering the same personal ID in the `reviewer` column of every row they complete. Rows must stay in place; no rows may be added, duplicated or deleted; leave a row blank rather than guess. An estimate of 10–20 seconds per message is about 4–8 hours per reviewer (my estimate, not a measurement).
4. **Adjudicator**: after both sheets are complete, run `python -m sms_prep audit`. It writes `adjudication_queue.csv` listing only the items the reviewers disagree on, with the masked text and the two labels (not who gave them). The adjudicator, who is neither reviewer, enters one row per disagreement in `adjudication.csv` (`item_id`, `final_label`, `adjudicator`). The queue decides nothing.
5. **Run `python -m sms_prep audit`** (from `experiments/`). While anything is missing or invalid it exits 3 with BLOCKED and the reason. When complete it writes `reports/label_audit_status.json` with per-class precision, Wilson intervals, kappa, control accuracy and the promoted classes.
6. **Report the outcome**; the owner decides what follows. If a class passes, M4.3 can use it. If none passes, an owner decision is needed (a different positive source or a changed gate).

## 6. Verification

| Check | Result |
| --- | --- |
| Frozen split before/after this review | assignment file, split metadata, answer key, both blank sheets and the empty adjudication sheet byte-identical; only `RUBRIC.md` changed (v1 → v2) |
| Experiments suite | **161 passed** (17 new) |
| Hand-check samples reproducible | all three reproduce exactly from committed code (36/36, 30/30, 24/24) |
| Privacy | pair reports and the spot-check record contain no message text; readable samples exclude the test split by construction (tested) |
| Test access log | none exists: the v1 test split has never been read |

## 7. Follow-up: owner decisions applied (5 November 2026)

### Decisions

1. **Create a proposed `sms_split.v2` at Jaccard 0.4**, subject to final distribution and leakage checks. v1 and its metadata are preserved for reproducibility.
2. **The label-approval gate is cluster-weighted**: one review item per cluster, 95% Wilson lower bound ≥ 0.95, unchanged. Record-weighted precision is reported separately and never gates (`label_audit_status.json` → `gate.precision_basis = "cluster_weighted"`; a regression test shows record weights cannot lift a failing class).
3. **A calibration pilot** runs before the main review.

No model was trained, no annotation was made, and no test text was displayed. The threshold came from label-free similarity statistics and hand checks of train/validation pairs only.

### How v2 is built and kept apart from v1

`python -m sms_prep split --version 2` (`sms_prep/split_versions.py`, `sms_prep/split_report.py`):

- Refuses to run unless the record store and the v1 assignment file match the hashes in `sms_split.v1.meta.json`, and re-checks v1 after writing. It refuses to rebuild v1.
- Clusters the same records at 0.4 (plus synthetic template families), splits clusters by stratum 70/15/15 by unique texts, seed 20261105, and writes only `data/m4/work/split_v2/` (ignored), `manifests/sms_split.v2.meta.json`, `reports/m4_2_split_v2_report.json` and the index `manifests/sms_splits.json`.
- Applies nine acceptance checks fixed in code before any result was seen. Status is `proposed` only if all pass, otherwise `proposed_failed_checks` and exit 4.
- Deterministic: a second run is byte-identical. v1's assignment file (`ef452e8c…`), clusters, records, metadata, review bundle and rubric were hash-checked before and after: unchanged. `HeldOutGuard` protects the v2 test split the same way; no test-access log exists.

v2 assignment SHA-256: `b5b5d9e958aee7589b3dadf731b826e3f7109a58567b8555285975b50ec4966b`. Status **proposed**; adoption for M4.3 is the owner's call after this review.

### Acceptance checks (all passed)

| Check | Result |
| --- | --- |
| No cluster or text in more than one split | 0 clusters, 0 texts |
| No cross-split pair at Jaccard ≥ 0.4 | 0 pairs |
| Synthetic template families stay whole | 0 split |
| No simulator fixture text | 0 matches |
| Every stratum in every split | all present |
| Test cells ≥ 30 unique texts (except hey mum/dad) | all large enough |
| Largest stratum deviation from 70/15/15 ≤ 0.02 | 0.0019 |
| Records lost to label conflicts ≤ 3% of v1 | 478 (1.71%) |
| No cluster above 70% of its stratum | largest 38.6% |

### Clusters and distribution

12,884 clusters: 12,604 assigned, 104 excluded for label conflict, 176 reference-only. Records: **train 20,641 / validation 3,464 / test 3,449**.

| Records per cluster | Clusters | Share of records |
| --- | --- | --- |
| 1 | 10,150 | 35.8% |
| 2–4 | 2,042 | 17.1% |
| 5–19 | 455 | 13.5% |
| 20–99 | 56 | 7.9% |
| 100–999 | 4 | 5.2% |
| 1,000+ | 1 | 20.4% |

Unique texts per stratum (train / validation / test): banking 4,548/975/975; others 2,280/489/488; government 914/196/196; delivery 790/170/169; telecom 666/143/143; IMC spam 674/144/144; wrong number 139/30/30; hey mum/dad 37/8/8; UCI ham 3,141/673/673; UCI spam 417/89/89; synthetic 496/107/106.

By records, provisional labels are benign 18.7% / needs_review 75.0% / spam 6.3% in train and 23.9% / 67.9% / 8.2% in test. Sources are IMC 73–79%, UCI 19–24%, synthetic 2.4–3.2% across splits.

29.86% of records (8,227) change split relative to v1, in all six directions.

### Giant-cluster effects

- **One banking campaign cluster holds 5,792 records**: 52.5% of banking records and 38.6% of banking unique texts. It mixes label keys and sits in train. Consequence: banking is split 70/15/15 by unique texts but only **about 10% of banking test records** (8,710 / 1,183 / 1,140). The test set contains no text from that campaign, so banking test results measure other campaigns. A per-record banking metric must say so.
- A second giant holds 11 of 53 hey mum/dad unique texts (train).
- Grouping at 0.4 also files more IMC records under a stratum other than their own class: **5.6% (1,199) in v2 against 1.9% (410) in v1** (for example 424 telecom records inside banking-led clusters). M4.3 must report per-class results by each record's own audited class, not by the cluster's stratum.

### Remaining leakage (v2 is not leak-free)

| Similarity to the nearest train text | ≥ 0.3 | ≥ 0.35 | ≥ 0.4 |
| --- | --- | --- | --- |
| Cross-split pairs | 2,435 | 501 | 0 |
| Test texts with a train neighbour (of 3,021) | 10.76% | 4.44% | 0 |
| Banking test texts | 16.41% | 6.56% | 0 |
| Validation texts (of 3,024) | 11.28% | 4.00% | 0 |

A hand check of 24 v2 train/validation pairs in the 0.3–0.4 band (seed 20261109, judged by the assistant, not by a human reviewer) found 10 templated, 12 generic and 2 unclear: templated share Wilson 95% 0.245–0.612, against 54 of 54 in the 0.4–0.6 bands. 0.4 is a reasonable stopping point; the residual near-campaign overlap below it is documented, not removed. Character similarity also cannot detect a campaign that is fully reworded.

### Calibration pilot

`python -m sms_prep pilot` writes `data/m4/review_pilot/` (ignored). It contains:

- Blank sheets `pilot_A.csv` and `pilot_B.csv`: the same 42 items in different orders.
- `RUBRIC.md` (v2, identical to the main bundle) and `INSTRUCTIONS.md`.
- A private answer key that records only provenance, never a label, with its hash in `bundle_meta.json`.

**Items (42):** banking 6, others 6, delivery 4, government 4, telecom 4, wrong number 2, IMC spam 4, UCI ham controls 4, UCI spam controls 4, synthetic benign 4.

**Coverage gaps:**
- Wrong number has only 2 items because only 2 of its clusters are outside the main audit sample.
- Hey mum/dad and UCI spam-with-links have none, because all of their clusters are already in the audit.

**Separation from the audit:** the pilot shares no record and no cluster with the audit sample, so discussing a pilot item cannot reveal an audit answer. It is never used by the gate. The software refuses to regenerate it with different items or a changed rubric once anyone has written in it.

**Reviewer instructions** (from `INSTRUCTIONS.md`):

1. Read `RUBRIC.md` fully.
2. Reviewer A labels every row of `pilot_A.csv`; Reviewer B labels every row of `pilot_B.csv`.
   - Work alone, with no discussion, lookups, links, classifiers or language models.
   - Write one rubric label and your personal reviewer ID on every row.
   - Leave a row blank rather than guess, and put rubric questions in `notes`.
3. Run `python -m sms_prep pilot-audit`.
   - It reports Cohen's kappa and per-reviewer control accuracy.
   - It writes `pilot_disagreements.csv` (text and both labels, not who gave them) and `reports/pilot_status.json`.
   - It exits 3 while INCOMPLETE.
4. Reviewer A, Reviewer B and the independent adjudicator discuss the disagreements against the rubric. Rubric clarifications are proposals; main-review sheets are not touched.
5. The owner decides whether to start the main review. The suggested bar is kappa ≥ 0.60 and control accuracy ≥ 90% per reviewer (status READY, otherwise CALIBRATE).

### Workflow re-verified

These properties are unchanged and covered by tests:

- Reviewer independence: one ID per sheet and different IDs across sheets.
- The adjudicator must differ from both reviewers.
- Every disagreement must be adjudicated.
- Answer-key integrity is checked.
- Controls are scored against provenance.
- The gate needs n ≥ 73 per class (197 of 200 at n = 200).

New regression tests:

| Test file | Tests | What they cover |
| --- | --- | --- |
| `test_split_v2.py` | 19 | Registry, v1 preservation, determinism, refusals, one failing check per violation |
| `test_pilot.py` | 13 | Disjointness, blinding, statuses, controls, tampering, no effect on the main audit |
| `test_review.py` | 1 new | Cluster-weighted gate |

Mutation probes caught three faults: a non-disjoint pilot, a record-weighted gate and a disabled leakage check.

### Outstanding actions

1. **Owner:** review and adopt (or reject) split v2 for M4.3. Until adopted, v1 stays the frozen split of record.
2. **Reviewers:** complete the pilot (42 items each), then meet; the owner decides whether to proceed.
3. **Reviewers + adjudicator:** complete the main review (1,485 items each, unchanged); run `python -m sms_prep audit`.
4. Known limits:
   - Hey mum/dad cannot pass the gate (too few clusters).
   - Wrong number has only 2 pilot items.
   - Seven per-class tests at 95% each.
