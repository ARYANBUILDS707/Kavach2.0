# M4-Q Solo Human Evaluation of the Pretrained SMS Model

Dated 7 November 2026 at commit `79ff21c` (CI run 42369713267: both jobs passed, including the worker tests); **revised 8 November 2026 (revision 2)** before any label existed.

**Status: the review workflow is prepared. No label exists, the model has not been run on this sample, and no result is claimed.**

## Revision 2 (8 November 2026): ten more legitimate messages, thresholds unchanged

A pre-label audit found that revision 1 could never reach GO. With zero false fraud flags in n legitimate messages the 95% Wilson upper bound is z²/(n+z²), z = 1.959964 (the zero-flag case; the next section covers one flag):

| Messages | Zero-error upper bound | Against the limit |
| --- | --- | --- |
| 30 legitimate (revision 1) | 0.1135 | above 0.10: GO unreachable |
| 34 | 0.1015 | above 0.10 |
| **35** | **0.0989** | passes 0.10 (smallest count that can) |
| 15 synthetic benign | 0.2039 | above 0.20 |
| **16 synthetic benign** | **0.1936** | passes 0.20 (smallest count that can) |

The owner chose to keep the strict 0.10 limit and enlarge the sample instead. Revision 2 adds exactly 10 UCI ham campaigns (3,215 more were eligible), for 40 ham, 173 first-time items and 183 rows. Every threshold is unchanged; only two minimum label counts changed (collected legitimate 25 → 35; new synthetic benign minimum 16). Revision 1 (`data/m4/review_solo/`, criteria v1) is kept untouched and is superseded. **Label only revision 2.**

**How many false fraud flags are tolerable depends on n.** The decision always uses the Wilson upper bound against the unchanged limit; it is never a fixed count of flags. With k false flags among n labels the bound is the Wilson interval's upper end, so more labels tolerate more flags. Verified examples (collected legitimate, limit 0.10):

| n | False flags | Upper bound | Result |
| --- | --- | --- | --- |
| 35 | 0 | 0.0989 | passes |
| 35 | 1 | 0.1453 | fails |
| 40 | 0 | 0.0876 | passes |
| 40 | 1 | 0.1288 | fails |
| 53 | 1 | 0.0994 | passes (52 gives 0.1012, which fails) |

So with the 40 ham rows the limit leaves no room for even one false flag; one flag only becomes tolerable from n = 53, which the sample reaches only if at least 13 of the 21 ambiguous rows are also labeled `benign` (not expected). The same Wilson rule applies to the synthetic benign limit (0.20):

| n | False flags | Upper bound | Result |
| --- | --- | --- | --- |
| 16 | 0 | 0.1936 | passes |
| 16 | 1 | 0.2833 | fails |
| 24 | 0 | 0.1380 | passes |
| 24 | 1 | 0.2024 | fails |

With 24 synthetic rows, one false flag (0.2024) therefore just misses the 0.20 limit even when every row is labeled `benign`. Consequence: a single false fraud flag among the collected legitimate labels (while n < 53) or among the 24 synthetic benign rows makes the corresponding GO check fail, so GO is no longer possible. The verdict is then CONDITIONAL unless a NO-GO rule fires (NO-GO needs, for example, a legitimate false-positive Wilson **lower** bound above 0.20, or fraud recall or precision with a Wilson upper bound below 0.60). One false flag alone never produces NO-GO, and a CONDITIONAL verdict can also come from any other failed check or cap. Labeling a ham message `unclear` or `spam` shrinks the legitimate count (40 ham allow at most 5 such rows before the 35 minimum is lost, unless ambiguous rows are labeled `benign`).

## What this is, and is not

**It is** a practical, three-day check. One reviewer labels a small blinded sample with the existing rubric (version 2). The frozen, pinned Horizon model is then scored offline on the same texts, and the comparison is judged against criteria registered **before** any label exists.

**It is not validation.**
- The independent two-reviewer plus adjudicator label-approval gate (95% Wilson lower bound, cluster-weighted) is unchanged and still BLOCKED (0 of 2,970 reviews). Solo labels never feed it.
- One reviewer, about 170 messages, one message per campaign: the rates are neither prevalence estimates nor production accuracy.
- The model's scores are uncalibrated. The mapping below is a comparison convenience, not a calibration.

## The sample (183 rows, already built, blank)

| Part | Rows | Source and rule |
| --- | --- | --- |
| Reported scams (IMC) | 56 | banking 20, delivery 12, government 12, telecom 12 |
| Ambiguous (IMC) | 21 | "others" 16 (composition unknown) and "wrong number" 5 |
| Spam | 32 | IMC spam 16, UCI spam 16 |
| Legitimate chat (UCI ham) | 40 | genuine personal messages (30 from revision 1 plus 10) |
| Synthetic transactional (OTP, bank alerts, delivery, appointments, utilities) | 24 | explicitly synthetic benign hard negatives, 12 template categories |
| Repeats | 10 | the same text again under a new ID, to measure your own consistency (the same 10 texts as revision 1) |

**Shortfalls, stated plainly:**
- **No collected transactional or OTP messages.** None of the permitted sources contains genuine ones, so legitimate transactional wording is tested **only** with synthetic text.
- **Hey mum/dad has no eligible campaigns left.** The audit and the pilot used them all.
- **Wrong number has only 5.**
- **No Mishra data**: it is a reference-only source.

**Protections** (verified independently from the split files):
- Every message is in train or validation under **both** the frozen split v1 and the proposed v2. Neither test set is read. The held-out guard's test-access log does not exist.
- No record or campaign overlaps the main audit sample or the calibration pilot.
- 173 distinct campaigns in 173 first-time items; the 163 revision-1 items are all kept and the 10 additions are all UCI ham.
- Collected and synthetic messages come from separate pools, are never pooled in a metric, and are reported in separate tables. Synthetic results can only lower the verdict.
- Selection is by hash; no model output, and no label, was used.
- The sheet shows only the masked text (the same as the main review), with no source, class or model information.

## Pre-registered decision rules

File: `experiments/manifests/sms_solo_eval_criteria.v2.json` (committable; `…v1.json` is preserved unchanged for reproducibility). Its SHA-256 is recorded in the bundle, and the evaluation refuses to run if the file or the bundle's copy differs. **Change a number only before your first label.**

Comparison mapping: `phishing` and `other_scam` → model `fraud`; `spam` → `spam`; `benign` → `legitimate`. `unclear` and blank rows are excluded and counted.

| Verdict | Rule |
| --- | --- |
| **INCOMPLETE** | Fewer than 95% of rows labeled, or a damaged sheet: nothing is scored, no verdict |
| **NO-GO** | Any one of:<br>• fraud recall Wilson **upper** bound < 0.60<br>• fraud precision upper bound < 0.60<br>• legitimate messages flagged fraud: Wilson **lower** bound > 0.20<br>• synthetic benign flagged fraud: lower bound > 0.30 |
| **GO** | All of:<br>• fraud recall Wilson **lower** ≥ 0.70<br>• fraud precision lower ≥ 0.70<br>• legitimate flagged fraud: Wilson **upper** ≤ 0.10<br>• synthetic benign flagged fraud: upper ≤ 0.20<br>• fraud labeled spam ≤ 0.30<br>• spam labeled fraud ≤ 0.50<br>• your repeat agreement ≥ 0.80 (at least 5 usable pairs)<br><br>**and** no cap: ≥ 40 human-fraud, ≥ 25 human-spam and ≥ 35 human-legitimate collected labels, ≥ 16 synthetic benign labels, and no more than 10% `unclear` |
| **CONDITIONAL** | Neither, with the shortfalls listed |

What each verdict means:
- **GO:** keep the model as clearly labelled **experimental** evidence and carry it into the M4.3 comparison. Not validated, not production.
- **CONDITIONAL:** use it only with the shortfalls stated beside it, and gather more labels.
- **NO-GO:** do not present the model's output as a fraud indicator in the MVP.

An empty denominator never passes a GO check and never fires a NO-GO rule. The 0.70/0.60/0.10/0.20 numbers are the registered thresholds (a proposal the owner accepted unchanged for revision 2): they are small-sample, interval-based and deliberately far below the 0.95 gate. Adjust them now if you disagree.

## Reviewer instructions

Work alone, in one sitting if you can (about 45 minutes at 15 seconds a message).

1. Read `data/m4/review_solo_v2/RUBRIC.md` once. It is the same rubric version 2 as the main review.
2. Open `data/m4/review_solo_v2/solo_review.csv` in a plain editor or spreadsheet (UTF-8 CSV).
3. For **every** row write one label in `label`: `phishing`, `other_scam`, `spam`, `benign`, or `unclear`.
   - `unclear` is only for text too short or garbled to judge.
   - Write the same name or initials in `reviewer` on every row you complete.
   - Put rubric doubts in `notes`.
4. Do **not**: look anything up, open links, ask a classifier or language model, or look at any model output (none exists yet). Do not discuss items.
5. Leave a row blank rather than guess; blank counts as unfinished.
6. Some texts appear twice under different IDs. Label each by its own text without trying to recall your first answer.
7. Save as CSV with the same name and columns. Do not add, delete or reorder rows or columns, or edit `item_id` or `display_text`.
8. Run the evaluation command below.

The files stay in the ignored `data/m4/`. They contain message text: do not copy them into Git, chat or tickets.

## Exact commands

From `experiments/`:

```sh
# already done once for revision 2 (the default); deterministic and safe to repeat (it refuses to overwrite labels)
uv run --project . --locked python -m sms_prep solo-prepare

# after you finish labeling: a read-only readiness check (no model, no text, no item IDs or names; exit 3 until every
# registered check passes; a rate with no denominator is NOT EVALUATED, never PASS)
uv run --project . --locked python -m sms_prep solo-preflight

# then, only when the preflight reports READY: progress while unfinished (exit 3), then scoring and the verdict
uv sync --project . --locked --group pretrained         # one time: torch + transformers (local only)
uv run --project . --locked --group pretrained python -m sms_prep solo-evaluate
```

- While anything is unfinished or damaged, `solo-evaluate` prints progress only. It does not load the model.
- When complete, it verifies the key and criteria hashes, then loads the pinned model offline and scores every first-time item twice.
  - Primary input: the same masked text you saw.
  - Secondary, reported only: the raw stored text.
- It writes the private `data/m4/review_solo_v2/model_outputs.json` (numbers only) and the committable `experiments/reports/solo_eval_status.v2.json` (aggregates; no text, no item IDs).
- If the pretrained group or model is missing it stops (exit 4) rather than produce a score.

## What the report contains

- **Per origin**, collected and synthetic, separately:
  - denominators;
  - the 3 × 3 confusion matrix (rows: your class; columns: the model's top label);
  - precision, recall and false-positive rate for fraud, spam and legitimate, each with k, n and a Wilson 95% interval;
  - per-stratum counts.
- **Fraud versus spam, explicitly:**
  - spam the model calls fraud, and fraud it calls spam;
  - how often it picks the right one when both say "unwanted";
  - fraud recall split by your `phishing` versus `other_scam` labels.
- **Unwanted versus legitimate:** the model's unwanted-versus-legitimate split.
- **Your consistency:** repeat agreement.
- **Verdict:** each registered check with its value and limit.
- **Secondary:** the raw-text table.
- Scores are shown only as native `legitimate`/`spam`/`fraud` outputs, marked uncalibrated.

## Remaining limitations

- `--revision 1` rebuilds the superseded revision-1 bundle; do not label it.
- A solo reviewer has no independent check on their own judgment; the repeats only measure self-consistency.
- Sampling is one message per campaign, so rare campaigns weigh as much as the giant banking campaign. The rates describe the model across campaigns, not across traffic.
- IMC texts are anonymized with placeholders and the display masks digits, so both reviewer and model see text unlike live SMS.
- UCI spam includes prize and premium-rate messages that the rubric can legitimately call phishing, spam or other scam; expect some fraud/spam disagreement from that alone.
- The model's training data is reported as synthetic; UCI is among its publisher's own evaluation sets. That is the publisher's claim, not independent evidence.
- With about 56–80 fraud labels, a Wilson interval is still wide: a GO is possible only for a clearly strong model.

## Next recommended action

1. The registered thresholds are fixed (criteria v2); do not change them once the first label exists.
2. Label `solo_review.csv` (about 45 minutes).
3. Run `solo-evaluate` and read the verdict as an input to the MVP demo decision, not as validation.
4. If the verdict is GO or CONDITIONAL, keep the labels as pilot-quality evidence for the M4.3 comparison. The independent review remains the only route to a validated claim.
