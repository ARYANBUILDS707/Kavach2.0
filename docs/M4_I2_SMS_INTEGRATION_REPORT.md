# M4-I.2 SMS Worker Integration: Implementation Report

Dated 7 November 2026.
- **Baseline:** `7e4fbcc`, GitHub Actions run 42274378378. Both jobs passed, and the worker lockfile check, worker tests and worker Ruff steps executed and passed (public GitHub API).
- **Contract:** [M4_SMS_INFERENCE_ARCHITECTURE.md](M4_SMS_INFERENCE_ARCHITECTURE.md).
- **Worker:** [M4_I1_SMS_WORKER_REPORT.md](M4_I1_SMS_WORKER_REPORT.md).

**What this is:** the verified pretrained SMS worker now classifies SMS in authenticated ingestion, when explicitly enabled.

**What it is not:**
- The model is **not validated on KAVACH data**.
- Its scores are **uncalibrated** model evidence; no phishing probability, risk score or tier is derived from them.
- None of the demonstration outputs below is an accuracy measurement.

## Request flow (SMS, worker enabled)

1. Bearer ingestion key, then the 30/minute/key quota (Redis; fails closed with 503 before the body is read), then the 32 KiB body bound, DTO validation and source scope. All unchanged.
2. PostgreSQL lookup of `(source, event_id)`.
   - Replay (200) and conflict (409) return here, with no inference.
3. Subscriber digest, then **inference outside any transaction**:
   - The text goes to the supervisor, which takes a non-blocking admission slot (max 2: one executing, one waiting).
   - The text crosses one pipe to the worker as a random-ID frame. It is never stored, logged or put in arguments.
   - No free slot returns 429 `CAPACITY_EXCEEDED` with `Retry-After: 1`. A starting or restarting worker returns 503 `DEPENDENCY_UNAVAILABLE` with `Retry-After: 10`. Both are **before anything is stored**.
4. One transaction: subscriber advisory lock, event, standalone incident and assessment (tier `unknown`), audit record. Unchanged except for the signals content.
5. After commit, the best-effort Redis candidate index. A Redis failure still returns 201 with the committed result.

Outcomes of an attempted inference are stored:
- **Completed:** signals version 2 with the native outputs, event `complete`, assessment `partial`.
- **Failed or unavailable:** the SMS stage is `unavailable` with a fixed reason code. Scores are null and nothing is ever marked legitimate.
- **Replays** return exactly what was stored and never re-run the model.

## Stored contract

| Item | Value |
| --- | --- |
| `events.signals` | `schema_version: 2`; stage `sms_classifier` with `status`, `reason`, `duration_ms`, and for `complete` a `model_output` of `labels` (legitimate/spam/fraud, 4 decimals), `top_label`, `score_semantics: "uncalibrated_softmax"`, `truncated`; `reason_codes: ["sms_model_uncalibrated"]` |
| `events.sms_score` | **always null** |
| `events.model_versions` | `sms_classifier`: `horizon-phishing-scam-base@fa686fc0d6a3+m1:<manifest sha256[:12]>` |
| Assessment | tier `unknown`, null base and final score, `analysis_status` `partial` (model ran) or `unavailable`, policy `kavach-m4-uncalibrated-sms-evidence` |
| Receipt | `analysis_status` `complete` plus warning `SMS_SCORE_UNCALIBRATED`, or `unavailable` plus `SMS_CLASSIFIER_UNAVAILABLE`; **no scores or labels** |
| Compatibility | Version 1 rows and every existing consumer are unchanged. No migration and no new column. The service rejects any extra key before a write |

## Files

**Added**
- `backend/src/kavach/api/routes/system.py`: authenticated model readiness.
- `backend/tests/test_sms_ingestion_unit.py` (31 tests).
- `backend/tests/integration/test_sms_inference.py` (22 tests).
- `backend/tests/fakes/support.py` (test-only).
- This report.

**Modified**
- `backend/src/kavach/core/config.py`: the worker settings group.
- `backend/src/kavach/main.py`:
  - builds the supervisor;
  - starts it in the app lifespan and closes it on shutdown;
  - accepts an injected supervisor for tests.
- `backend/src/kavach/services/ingestion.py`: inference step, signals version 2, allowlist check, `AnalysisRejected`.
- `backend/src/kavach/db/event_repository.py`: the assessment's status and model versions.
- `backend/src/kavach/api/routes/events.py`: the 429/503 mapping.
- `backend/src/kavach/models/sms_worker.py`: `refused()`, the public state, peak memory in status, and a lock-file failure becoming `unverified`.
- `backend/src/kavach/simulator/runner.py`: accepts documented model outcomes and requires replay fidelity.
- Tests: `test_health.py` (the route inventory gains `/api/v1/system/models`) and `test_simulator_unit.py` (+2 tests).
- Docs: API.md, DATABASE.md, the design doc, tracker, README and `.env.example`.

Unchanged by design: schema and migrations, the SMS event DTO, existing routes, datasets, splits and review sheets.

## Configuration (all optional; the worker is off by default)

`SMS_WORKER_ENABLED`, `SMS_WORKER_PYTHON`, `MODEL_DIR`, `MODEL_MANIFEST_PATH` (absolute), `MAX_INFLIGHT_ANALYSES` (1–2), `SMS_INFERENCE_TIMEOUT_MS` (100–10000; with the 2 s commit reserve it must be shorter than `INFERENCE_TIMEOUT_SECONDS`), `SMS_WORKER_THREADS`, `SMS_WORKER_MAX_RSS_MB`, `SMS_WORKER_START_TIMEOUT_SECONDS`, `INFERENCE_DEVICE` (`cpu` only).
- Enabling requires the event ingestion configuration.
- An unusable manifest, interpreter or model directory leaves the model `unverified` (SMS stored as unavailable), and refuses startup in `APP_ENV=pilot`.
- Without the setting, behavior and stored data are exactly as before M4.

## Real end-to-end results

Real uvicorn API (7 Nov 2026) with the real worker and the real pinned model. The whole process ran under a `sandbox-exec` profile that denies all outbound network except localhost (PostgreSQL/Redis), against a fresh disposable PostgreSQL/Redis stack and migrated database. Ingestion keys and accounts were provisioned with the operator CLI. Every message is fictional and marked as such.

| Case | Result |
| --- | --- |
| Legitimate demo SMS ("running late, start dinner") | 201 `complete`; native output legitimate **0.6407**, spam 0.3151, fraud 0.0443; top label `legitimate` |
| Suspicious demo SMS (fake bank KYC link) | 201 `complete`; fraud **0.9963**, spam 0.0022, legitimate 0.0015; top label `fraud` |
| Stored | `sms_score` null; assessment tier `unknown`, `partial`; `model_versions` set; exactly one row each |
| Identical replay of both | 200 `replayed: true`, same warnings, still one row, no second inference |
| 4 simultaneous max-length requests | 2 × 201, 2 × 429 `CAPACITY_EXCEEDED` (`Retry-After: 1`) |
| Worker SIGKILLed | the next request 503 `DEPENDENCY_UNAVAILABLE`, **0 rows stored**; the worker returned to `ready`; a retry of the same event ID gave 201 `complete` |
| Inference timeout (`SMS_INFERENCE_TIMEOUT_MS=100`, 4,096-char message) | 201 `unavailable`, stored reason `inference_timeout`, no scores |
| Model directory missing | status `unavailable`/`unverified`; 201 `unavailable`, reason `model_unverified` |
| Manifest with a wrong weights hash | the same `model_unverified`; the real worker refused after hashing 1.2 GB |
| Second API process | state `lock_held`; SMS stored `worker_unavailable`; **one** worker process in total |
| API shutdown | the worker exited with it |
| Simulator, all 12 scenarios | 12/12 passed, 20 submissions; SMS receipts `complete` + `SMS_SCORE_UNCALIBRATED`, calls unavailable, replays identical |
| Readiness | `GET /api/v1/system/models` with a viewer session: `ready`, `detail: ready`, `validated_on_kavach_data: false` |

The three outputs above are single demonstration messages, not an accuracy measurement. The very first request after startup took longer inside the model (about 1 s) than later ones.

### Latency, memory, startup

| Measure | Value |
| --- | --- |
| Launch to ready (API start plus worker self-test) | 8.3 s |
| 20 sequential requests, end to end over HTTP | median 54 ms, p95 81 ms, max 99 ms; stored processing time median 40 ms, max 73 ms |
| Worker memory | 475 MB current (`ps`) with the model idle; peak 1,097 MB self-reported in the M4-I.1 run |
| API process | 50 MB |
| Kill to ready again | 5.9 s (M4-I.1) |

Not measured: behavior on a clean machine. This Mac already had about 7.3 GB of its swap in use.

## Failure matrix (as implemented and tested)

| Situation | Response | Stored |
| --- | --- | --- |
| Bad key, wrong source, invalid body, rate limited | 401, 403, 422, 429 | nothing; the worker is never called |
| Redis down | 503 | nothing; no inference |
| PostgreSQL down at lookup | 503 | nothing; no inference |
| PostgreSQL fails after inference | 503 | nothing; a retry is analyzed afresh |
| No free slot | 429 | nothing |
| Worker starting or restarting | 503 | nothing |
| Waiting request when the executing one is killed | 503 | nothing |
| Timeout, crash, invalid output, deadline too short | 201 `unavailable` | the reason code; no scores |
| Circuit open, unverified model, lock held, disabled | 201 `unavailable` | the reason code |
| Redis index fails after commit | 201 | the committed result is intact; replay re-indexes |

## Privacy and security findings

- **Zero hits** for the fictional text or the subscriber token across every table of the end-to-end database (77 events), every Redis key and 465 DEBUG log lines.
- **Integration tests** (real PostgreSQL/Redis) scan all tables, all Redis values, captured logs and audit records after runs that include worker-side stderr and stdout echoes of the text, crashes and timeouts: no text and no sender ID. The worker environment contains none of the database, Redis or HMAC settings, and its arguments hold no text.
- **Authentication, source scope, quota and idempotency** run before inference. Tests confirm the worker is never called for a rejected request, a replay or a conflict.
- **Readiness** requires a dashboard session; an ingestion key gets 401.
- **Mutation checks:** 5 deliberate defects were all caught (saturation stored instead of rejected, wrong status for saturation, allowlist disabled, inference before the replay lookup, raw text added to the stage).
- **Limits that remain:**
  - Freed memory is not erased (TD-26).
  - Network denial in the worker is in-process plus the macOS sandbox run, not OS enforcement in deployment (TD-27).
  - The 1 s first-request latency and single-worker throughput (about 25 requests per second) bound capacity.

## Tests

CI replay on 7 November 2026, on a fresh disposable PostgreSQL/Redis stack:

| Suite | Result |
| --- | --- |
| Backend default | **350 passed** (317 before + 33 new) |
| Backend integration (real PostgreSQL/Redis) | **341 passed** (319 + 22 new) |
| Real model, offline sandbox (`-m model`, local, not in CI) | **5 passed** |
| Worker (no torch installed) | **40 passed** |
| Experiments | **222 passed** |
| Ruff lint and format | clean in all three projects |
| `uv lock --check` | clean for backend, experiments and workers/sms |
| Migrations | upgrade, `current` = `0002_retention_procedure`, `alembic check`: no differences |

GitHub Actions has not run these changes.

## Remaining before this is relied on

1. **Calibration and mapping:** unchanged blocker; needs the M4.2 label audit (0 of 2,970 reviews), an adopted split and validation-only fitting.
2. **Container packaging** of the worker environment and OS-level network denial (TD-27).
3. **Capacity:** one worker, 25 requests per second at best, and a first-request warm-up. Load testing is not done.
4. **Public `/health`** is unchanged (C-07): it still reports liveness only, so model readiness lives on the new authenticated route.
