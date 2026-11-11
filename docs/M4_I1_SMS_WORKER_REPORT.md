# M4-I.1 Isolated SMS Inference Worker: Implementation Report

Dated 6–7 November 2026.
- **Baseline:** `73b43fd`, GitHub Actions run 42268142297; both jobs passed (public GitHub API).
- **Contract:** [M4_SMS_INFERENCE_ARCHITECTURE.md](M4_SMS_INFERENCE_ARCHITECTURE.md).

**Scope:**
- Built: the worker and its supervisor.
- **Not connected to ingestion.** No change to event storage, schema, API responses or settings.
- No training.
- The model is not validated on KAVACH data, and its scores are uncalibrated.

## What exists

| Part | Path | Environment |
| --- | --- | --- |
| Worker | `workers/sms/` (package `kavach_sms_worker`; `uv.lock`, 59 packages, `exclude-newer` 2026-10-23) | Default: stdlib only. `model` group: torch 2.14.1, transformers 5.20.2, tokenizers 0.23.3, safetensors 0.8.0, huggingface-hub 2.2.0, numpy 2.5.4 |
| Manifest v1 | `deployment/models/sms_classifier.horizon.v1.json` | Git-versioned trust root |
| Supervisor | `backend/src/kavach/models/{sms_worker,manifest,protocol}.py` | API environment (stdlib + pydantic); imports no ML library |
| Fake worker (test-only) | `backend/tests/fakes/fake_sms_worker.py` | Never packaged |
| CI | `.github/workflows/backend-ci.yml`: worker lockfile check, default install, tests, Ruff | No torch in CI |

## Implementation choices within the design

- **Artifact layout.**
  - The manifest's `artifact_dir` (`horizon-phishing-scam-base/<revision>`) is relative to `MODEL_DIR`. This reuses the verified download in `data/models/` instead of copying 1.2 GB.
  - The lock file path is configured by the caller (proposed `MODEL_DIR/.kavach-sms-worker.lock`), outside the artifact directory, so it never counts as a stray file.
- **No idle ping.**
  - An idle crash is detected immediately by end-of-stream on the worker's stdout.
  - An idle *hang* is caught by the next request's timeout.
  - The `ping`/`pong` frame in §5 is therefore not implemented.
- **Added codes.**
  - Rejected `worker_busy`: the waiting request's budget ran out while the worker was healthy but busy.
  - Failure `invalid_startup_output`.
  - Fatal codes `runtime_mismatch`, `model_load_failed`, `self_test_failed`, `manifest_mismatch`.
- **Hardening.**
  - Frames go to a private duplicate of stdout, and fd 1 is redirected to stderr, so a stray library `print` cannot corrupt the protocol (tested).
  - The worker blocks outbound sockets in-process (`getaddrinfo`, `connect`, `create_connection`, `sendto`).
  - Core dumps are 0, and the umask is 077.
- **Supply chain.**
  - Every resolved package, transitive included, is at least two weeks old (`exclude-newer`).
  - OSV reports no advisories for the 59 locked packages (6 Nov 2026).

## Manifest and hash verification

- **All seven files** were verified against the manifest by the worker:
  - config, special tokens, tokenizer config, tokenizer, weights (`1f056ed6…25af`), LICENSE, NOTICE;
  - the same values as the audited record (cross-checked by `experiments/tests/test_pretrained.py`).
- **Approved runtime** matches the installed versions.
- **Canary self-test:**
  - the canary's SHA-256 is pinned (`4f5515cd…edda`);
  - expected outputs measured three times, identical: `[0.000705, 0.000828, 0.998467]`, tolerance 0.001.
- **Real refusal:**
  - a manifest recording a different weights hash makes the real worker refuse after hashing the real 1.2 GB file;
  - the supervisor goes terminal `unverified` after one start.
- `model_version` format: `horizon-phishing-scam-base@fa686fc0d6a3+m1:<manifest sha256[:12]>`.

## Measurements

Measured on an Apple M1 with 8 GB RAM, running the real worker through the real supervisor. The whole test process ran under `sandbox-exec` denying outbound network, so the measurements are offline. Every message was fictional.

| Measure | Value |
| --- | --- |
| Startup to ready (hash 1.26 GB + load + self-test) | 5.91 s |
| Restart to ready after a kill | 5.89 s |
| Worker peak RSS (self-reported) | 1,090 MB at ready; 1,097 MB after 200 messages and the concurrency run |
| Sequential, 200 short messages, 2 threads | total median 34.0 ms, p95 39.1 ms, max 56.5 ms; model median 33 ms |
| 4,096-character message (truncated at 256 tokens) | 117 ms |
| Threads 1 / 2 / 4, model ms median (p95) | 32 (35) / 33 (39) / 34 (41) |
| 3 simultaneous max-length requests | 2 complete (the second waited 114 ms), 1 rejected `inference_saturated` |
| Real kill of an in-flight inference (10 ms budget) | process gone 48 ms after the call; fresh worker passed its self-test |
| Swap during the run | 7,409 MB → 7,361 MB used, out of 8,192 MB (no growth) |

**The machine was already heavily swapped by other applications** before the run. A clean-machine figure was not taken.

Values adopted (design U2):
- **Threads: 2.** Thread count makes no material difference for SMS-length input.
- **`SMS_INFERENCE_TIMEOUT_MS`: 2000.** That is 17× the slowest measured input and 51× the p95.
- **`SMS_WORKER_MAX_RSS_MB`: 1536.** The measured peak was 1,097 MB.

## Fault, timeout and recovery results

All of these run with the fake worker in CI. They passed 5 sequential runs and 3 concurrent runs.

| Case | Result |
| --- | --- |
| Invalid output (wrong id, NaN, sum ≠ 1, wrong count, extra key, error status, garbage, oversize) | `invalid_model_output`, worker replaced, next request completes |
| Crash mid-request | `worker_crashed`, restart, next request completes |
| Per-inference timeout | `inference_timeout` within 0.3–1.5 s, PID gone (own process group, SIGKILL), no late result |
| Request deadline shorter than the timeout | budget clamps to the deadline minus the reserve |
| Deadline exhausted | `deadline_exhausted`, nothing sent |
| Startup hang | killed after the start timeout, `start_timeout` failure |
| Repeated failures | `circuit_open` after 3; exactly one probe start, then open again |
| Idle crash (external SIGKILL) | detected, restarted |
| Fatal, wrong manifest or no self-test | terminal `unverified`, one start only |
| Memory ceiling | answer kept, planned restart, not counted as a failure |
| Concurrency | 2 admitted (one waits), third `inference_saturated`; waiting request gets `worker_restarting` when the executing one is killed |
| Slots | free count back to 2 after every path, including an injected exception |
| Model-copy lock | second supervisor `lock_held`, never spawns; after release a new one starts |
| Teardown | idempotent; worker gone, lock released, temp home removed, threads joined; close during a hung startup returns under 3 s |

Mutation probes: 13 of 13 deliberate defects were caught by the tests:
- no SIGKILL;
- blocking admission;
- unreleased slot;
- inherited environment;
- no lock;
- no request-id check;
- no sum check;
- no circuit breaker;
- fatal retried;
- worker skips hashing;
- stray pickle allowed;
- no network guard;
- invalid input echoed.

## Privacy and security verification

- **Worker environment** is built from an allowlist. With `DATABASE_URL`, `REDIS_URL`, all HMAC keys, `PYTHONPATH`, `DYLD_INSERT_LIBRARIES` and `LD_PRELOAD` set in the parent, none reached the worker (tested). The worker argv never contains text.
- **What crosses the pipe:** only `{v, type, id, text}` frames. IDs are random 128-bit, distinct per call and unrelated to events.
- **Leaky libraries:** a fake that writes the text to stderr and to stdout leaked nothing into logs, results or status, with the logger at DEBUG level.
- **Errors** carry fixed codes. Invalid requests are answered without echo, and library failures as `internal_error` only.
- **Isolation:** `import kavach.main` loads no torch, transformers, tokenizers, safetensors or numpy, and `backend/uv.lock` contains none of them (tested).
- **Limits:**
  - Freed memory is not erased (TD-26).
  - Network denial is in-process plus configuration; OS enforcement is TD-27. The offline claim above rests on the macOS sandbox run, not on the code alone.

## Tests and checks

CI replay on 7 November 2026, local, on a fresh disposable PostgreSQL/Redis stack:

| Suite | Result |
| --- | --- |
| Backend default (`pytest backend/tests`) | **317 passed** (267 before + 50 new supervisor tests) |
| Backend integration (`-m integration`, real PostgreSQL/Redis) | **319 passed** (unchanged) |
| Migrations | upgrade twice, `current` = `0002_retention_procedure`, `alembic check`: no differences |
| Experiments | **222 passed** (+1 manifest parity) |
| Worker (`workers/sms/tests`, fresh environment, torch absent) | **40 passed** |
| Backend real model (`-m model`, local, offline sandbox) | **5 passed** (not in CI) |
| Ruff lint + format | clean in all three projects |
| `uv lock --check` | clean in all three projects |

GitHub Actions has not run these changes.

## Remaining before M4-I.2 (connection to ingestion)

1. Settings: `SMS_WORKER_*`, `MODEL_DIR` and `MODEL_MANIFEST_PATH` in `kavach.core.config` with startup validation. Not added here, because nothing reads them yet.
2. Wire into `IngestionService` per §6.4:
   - 429 and 503 rejection before storing;
   - committed unavailable stages;
   - `signals` schema v2;
   - `SMS_SCORE_UNCALIBRATED`;
   - `sms_score` null and tier `unknown`;
   - authenticated health status.
3. Integration tests C1–C4, P1–P2 and S1 against real PostgreSQL and Redis.
4. Worker packaging for containers (U3) and OS-level network denial (TD-27).
5. Calibration and the fraud/spam mapping remain blocked on the M4.2 label gate (0 of 2,970 reviews).
