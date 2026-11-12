# Experimental SMS Analysis (local only)

This mode lets a signed-in admin type a **fictional** SMS and see the pinned pretrained model's actual prediction (fraud, spam or legitimate) in the KAVACH UI. It is an owner-authorized, local-only experiment. **It is not a validated capability, and it does not mean M4-Q passed.**

| | Standard configuration | Experimental local mode |
| --- | --- | --- |
| Worker | Disabled (default) | Enabled |
| Required settings | none | `SMS_WORKER_ENABLED=true` **and** `SMS_MODEL_AUTHORIZATION=experimental-local-unvalidated`, plus the worker paths |
| Allowed where | anywhere | `APP_ENV=development` with a loopback `APP_ORIGIN` only. Startup is refused otherwise, including any pilot. |
| What users see | "Analysis unavailable" | "Model prediction (experimental): The model predicts: Fraud/Spam/Legitimate", the native uncalibrated scores, the model version and the limitations |
| Risk tier, `sms_score` | unknown, null | **still** unknown, null |

## Decision record

- **Conflict.** Decision C-12 D ([MASTER_DEVELOPMENT_PLAN.md](MASTER_DEVELOPMENT_PLAN.md)) keeps the worker disabled until the M4-Q evaluation completes with GO, or CONDITIONAL with owner approval.
- **M4-Q status.** NOT READY. The owner labelled all 183 revision-2 rows. Preflight gave 20 PASS and two coverage failures: collected spam 19 (minimum 25) and synthetic benign 1 (minimum 16). That result is preserved unchanged. No label, criterion, threshold or sample was touched, and no evaluation was run.
- **Decision C-13**, approved by the owner on 12 Nov 2026, is recorded in the master plan as *Resolved (limited)*. It covers **only** a local-only, fictional-data, experimental and unvalidated inference mode. It does not authorize production inference, real or customer messages, bypassing M4-Q, or any claim of validated accuracy. The mode sits outside the C-12 D verdict path, and it is not a GO, CONDITIONAL or validation. Every C-12 D "always" rule still holds:
  - `sms_score` stays null and the tier stays `unknown`;
  - native outputs are labelled uncalibrated;
  - no accuracy claim and no fine-tuning;
  - fictional messages only, no automatic action.
- **Normal and production operation.** C-12 governs them unchanged. The default configuration and the local demo procedure keep the worker disabled, and any pilot or production enablement still needs an M4-Q verdict.

## Start the application in experimental mode

**Shortest path:** run `scripts/kavach-demo.sh start --experimental` from the repository root. It prepares the worker environment, sets the five settings below in its own process only, waits for `sms_worker.ready`, and prints the C-13 banner. Ctrl-C stops everything. If the worker cannot start, the launcher says so, and the UI shows "analysis unavailable" rather than a prediction. The manual steps follow.

The prerequisites are the same as in [LOCAL_DEMO.md](LOCAL_DEMO.md), plus the model environment and the verified artifacts (`data/models/horizon-phishing-scam-base`, never in Git; see [M4_I1_SMS_WORKER_REPORT.md](M4_I1_SMS_WORKER_REPORT.md)).

1. **Services, migrations and accounts:** follow [LOCAL_DEMO.md](LOCAL_DEMO.md) steps 1–4 exactly.
2. **Model environment, once:**

   ```sh
   uv sync --project workers/sms --locked --group model --python 3.12.13
   ```

3. **Add the experimental settings** to `~/.kavach-demo/runtime.env`, replacing the `SMS_WORKER_ENABLED=false` line. Run this from the repository root:

   ```sh
   R="$(pwd)"
   sed -i '' '/SMS_WORKER_ENABLED=false/d' ~/.kavach-demo/runtime.env   # GNU sed: sed -i '...'
   cat >> ~/.kavach-demo/runtime.env <<EOF
   export SMS_WORKER_ENABLED=true
   export SMS_MODEL_AUTHORIZATION=experimental-local-unvalidated
   export SMS_WORKER_PYTHON='$R/workers/sms/.venv/bin/python'
   export MODEL_DIR='$R/data/models'
   export MODEL_MANIFEST_PATH='$R/deployment/models/sms_classifier.horizon.v1.json'
   EOF
   ```

4. **Start the backend (terminal 1)** and wait about 10 s for the model to load:

   ```sh
   . ~/.kavach-demo/runtime.env
   backend/.venv/bin/python -m uvicorn kavach.main:create_app --factory \
     --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
   ```

   The log shows `sms_worker.ready reason=self_test_passed`.

5. **Start the frontend (terminal 2):** `cd frontend && npm ci && npm run dev`. Open `http://127.0.0.1:5173`, sign in as the admin, and check that the header pill reads **SMS model: Ready**.
6. **Analyze SMS:** the page shows "Experimental analysis is on". Submit a fictional message; the receipt reads the stored prediction back from the server.

**Switching back to the standard mode:** remove the five lines from step 3, restore `export SMS_WORKER_ENABLED=false`, and restart the backend.

## Verified behaviour (12 Nov 2026, branch `feature/experimental-sms-analysis`)

The full stack ran locally on disposable PostgreSQL and Redis, with the real worker and the pinned model `horizon-phishing-scam-base@fa686fc0d6a3+m1:1cf123b806f7`.

**Predictions in the browser.** The expected class is not hardcoded; each result shown on the page was checked against the stored API result.

| Fictional message (intent) | Prediction | Native scores, uncalibrated: legitimate / spam / fraud |
| --- | --- | --- |
| Account frozen, confirm PIN at a link (fraud-like) | Fraud | 0.0024 / 0.0023 / 0.9953 |
| Festival sale, 60% off, reply STOP (spam-like) | Spam | 0.0138 / 0.9843 / 0.0019 |
| Running late for a meeting (normal) | Legitimate | 0.9939 / 0.0039 / 0.0022 |

**Honest failure states (browser):**
- Model directory missing: the event is stored *unavailable* (`model_unverified`) and no prediction is shown.
- Inference budget of 100 ms on a long message: the worker timed out and was killed and restarted (`inference_timeout`); the event was stored *unavailable* and no prediction was shown.

**Boundaries with the model on:**
- a viewer's submission gets 403;
- a missing CSRF token or a foreign Origin gets 403;
- an injected `label` field or over-length text gets 422;
- the receipt never echoes the text;
- no text in the database or logs; empty browser storage.

**Model regression on fictional fixtures** (`backend/tests/test_sms_model_fixtures.py`, offline). Nine new fictional messages give valid, deterministic native outputs. The predictions agree with the author's intent on 9 of 9; that is a **smoke signal on nine hand-written messages, not an accuracy evaluation**.

## Why there is no dataset accuracy figure

- The held-out test split is reserved for one logged final evaluation ([M4_PRETRAINED_EVALUATION.md](M4_PRETRAINED_EVALUATION.md)), so scoring it now would spend it.
- The blinded M4-Q sample was drawn from the train and validation splits, so scoring those would expose the blind sample.
- UCI is the model publisher's own evaluation set, so its scores could be contaminated.

A fair public-data figure needs a newly governed dataset that is disjoint from all KAVACH splits: licence review, manifest and overlap check, as in [DATASET_GOVERNANCE.md](DATASET_GOVERNANCE.md). Until then, KAVACH claims no detection accuracy.

## Limitations

- The model is not validated on KAVACH data. Scores are uncalibrated softmax values, not probabilities. Its errors are unknown in size and direction.
- Messages longer than the model reads are truncated (the UI says so).
- One local worker, at most two concurrent analyses. Overload returns 429 and a starting worker 503, before anything is stored.
- Local and fictional only: no deployment, no real or customer messages, no telecom access, no automatic blocking or alerts. A person decides.
