# KAVACH Milestone Tracker

Status as of 31 October 2026, from the read-only audit of that date, the M0 documentation work and the owner's decisions of the same day; rows added since carry their own dates. **Current priority (9 Nov 2026): SMS MVP-1** (rows MVP-1 to MVP-J; MASTER_DEVELOPMENT_PLAN.md C-12). All verification entries are **point-in-time historical results**; re-run the commands before relying on them. Update this file when a milestone's exit criteria are verified, not when work merely starts. Details and acceptance criteria are in [MASTER_DEVELOPMENT_PLAN.md](MASTER_DEVELOPMENT_PLAN.md). Dated execution results go in task reports.

Status values: `not started`, `in progress`, `blocked`, `complete (verified)`, `complete (unverified)`.

## Milestones

| ID | Milestone | Branch | Status | Blocked by / notes |
| --- | --- | --- | --- | --- |
| M0 | Repository, architecture alignment, workflow, reproducibility planning | `dev` | complete (documentation committed to `dev`; see the M0 task report for the hash) | C-07 deferred; PRD/API/ARCHITECTURE follow-ups noted under C-06 |
| M1 | FastAPI foundation | `main` (history) | complete (verified historically: 88 passed, Ruff clean on 31 Oct 2026; HTTP startup last verified 28 Oct 2026) | Debt TD-01, TD-02, TD-03 carried forward; M1 routes preserved (C-07 deferred) |
| M1.1 | Reproducible environment and minimal pytest + Ruff CI | `backend` (stays there until full backend acceptance) | complete (verified): GitHub Actions passed on `backend` commit `c36e903` (owner-reported, 31 Oct 2026) | — |
| M2 | PostgreSQL, migrations, identity, scoped auth, audit (owner-defined steps below) | `backend` | in progress | D02 packages, D03, D07, C-06 approved 31 Oct 2026 |
| M2.1 | Database and development infrastructure: dependencies, dev/test Compose, engine/session and Redis client lifecycle, config validation, real-service tests, CI integration job | `backend` | complete (verified): GitHub Actions run 41119537962 on `0cebb3b`, both jobs passed (checked via the public GitHub API, 31 Oct 2026) | — |
| M2.2 | Full DATABASE.md schema, Alembic migration `0001_initial_schema`, integrity triggers, role grants | `backend` | complete (verified): GitHub Actions run 41121829796 on `e7c0873`, both jobs passed (public GitHub API, 31 Oct 2026) | — |
| M2.3 | Login/session/logout, Argon2id, opaque DB sessions, CSRF, Origin, shared Redis throttling (fail closed), audited minimal provisioning | `backend` | complete (verified): GitHub Actions run 41186469837 on `24e6538`, both jobs passed (public GitHub API, 3 Nov 2026) | — |
| M2.4 | Source-scoped ingestion keys and `require_ingest_key`/`require_source`; operator CLI (bootstrap, provision, deactivate, reset, role change, key create/rotate/revoke/list, retention); admin-actor authorization; operator-triggered retention | `backend` | complete (verified): GitHub Actions run 41693476877 on `0db68fb`, both jobs passed (public GitHub API, 4 Nov 2026) | — |
| M2.5 | Full M2 security acceptance: findings M-1–M-3 and L-1–L-3 fixed (migration `0002_retention_procedure`, write-ahead retention audit, final revocation), report in `M2_SECURITY_ACCEPTANCE.md` | `backend` | complete (verified): GitHub Actions run 41695959367 on `a4a5578`, both jobs passed (public GitHub API, 4 Nov 2026). **M2 acceptance: PASS** | — |
| M3 | Authenticated ingestion, PG idempotency, Redis state, scenario catalog + submission script | `backend` | complete with conditions (verified): M3.1–M3.4 all passed both CI jobs on GitHub (M3.4: run 41885380731 on `90c32b4`). Acceptance verdict **CONDITIONAL PASS** (`M3_INGESTION_ACCEPTANCE.md`); the conditions (D05/D08/TD-19 values confirmed, `--no-proxy-headers` launch, M6 treats Redis as an accelerator only) remain open | M2; D05/D08/TD-19 owner decisions |
| M3.1 | Key-authenticated SMS/call ingestion, transactional PostgreSQL idempotency (201/200/409), receipt recovery, standalone incident with unavailable analysis, ingestion audit | `backend` | complete (verified): GitHub Actions run 41698348162 on `4647f52`, both jobs passed (public GitHub API, 4 Nov 2026) | — |
| M3.2 | Redis candidate index (D05 window/lateness), shared per-key submission limit (D08), invalid-Bearer throttle, ingestion deadline, fail-closed Redis handling, post-commit index recovery | `backend` | complete (verified): GitHub Actions run 41867501351 on `14e23d9`, both jobs passed (public GitHub API, 4 Nov 2026) | — |
| M3.3 | Controlled synthetic simulator: versioned scenario catalog S01–S12 with validated expectations and simulation-only labels, admin-only `GET /simulator/scenarios`, loopback-only paced runner (`python -m kavach.simulator`) through the ordinary endpoints, audio manifest contract documented (not active) | `backend` | complete (verified): GitHub Actions run 41879325247 on `bf403a8`, both jobs passed (public GitHub API, 4 Nov 2026) | — |
| M3.4 | Full M3 acceptance audit: findings M34-M1–M4 and L1–L6 (`M3_INGESTION_ACCEPTANCE.md`); fixed: stale candidate on late replay, deep-JSON 500, missing payload-key signal, TD-19 valid-key lockout; mitigated: proxy-header throttle evasion via the documented launch flag; 22 new integration tests | `backend` | complete (verified): GitHub Actions run 41885380731 on `90c32b4`, both jobs passed (public GitHub API, 4 Nov 2026). Verdict CONDITIONAL PASS | — |
| M4.1 | SMS dataset research and governance: four candidates verified on real files (IMC25, UCI, Mishra & Soni, Munoz & Islam), versioned manifest with validator and tests, reproducible audit script, label and privacy policy, M4.2–M4.4 plan (`DATASET_GOVERNANCE.md`, `M4_EVALUATION_PLAN.md`, `experiments/`). No model trained, no dependency added | `backend` | complete (verified): GitHub Actions run 41891028870 on `0845ed2`, both jobs passed (public GitHub API, 5 Nov 2026). The governance test file was left out of that commit (moved into `experiments/tests/` in M4.2). D04 was then decided by the owner | — |
| M4.2 | SMS data preparation: verified acquisition (IMC25, UCI, Mishra), feature vs matching normalization, exact + near-duplicate clustering, blinded double-review bundle, synthetic hard negatives, frozen leakage-safe split, quality report, separately locked experiments environment, CI for `experiments/` (`M4_2_DATA_PREPARATION_REPORT.md`) | `backend` | complete with conditions (verified): GitHub Actions run 41900502306 on `ce63aca`, both jobs passed (public GitHub API, 5 Nov 2026). Verdict CONDITIONAL: **label approval BLOCKED**, 0 of 2,970 human reviews done | Human review (2 reviewers + adjudicator); owner decision if no class passes |
| M4.2-R | Focused data-quality review of the frozen split and the review workflow: 870 cross-split pairs examined (87–98% templated campaign variants; the pattern continues below 0.6), recommendation to create `sms_split.v2` at Jaccard 0.4 before any model reads the data, eight review-evaluator gaps fixed, rubric v2, adjudication queue (`M4_2_DATA_QUALITY_REVIEW.md`). No split changed, no annotation made. **Follow-up (owner decisions, 5 Nov 2026):** proposed `sms_split.v2` at Jaccard 0.4 created beside the preserved v1 (all nine acceptance checks pass; 0 cross-split pairs at ≥ 0.4; 4.4% of test texts still have a train neighbour at ≥ 0.35); gate fixed as cluster-weighted with record-weighted precision reported only; 42-item blinded calibration pilot disjoint from the audit (section 7) | `backend` | in progress: verified locally on 5 Nov 2026; uncommitted; **not yet run on GitHub** | Owner adoption of split v2 after manual review; pilot then main human review; user commit/push; both CI jobs green |
| M4-P | Pretrained SMS classifier track (owner strategy change, 5 Nov 2026): three Hugging Face candidates audited (license, provenance, training-data overlap, labels, hashes); Horizon-Labs/phishing-scam-detector-base selected and pinned; verified, resumable fetch; offline safetensors-only CPU inference on 14 fictional messages (`M4_PRETRAINED_EVALUATION.md`). No training, no integration, no KAVACH metric | `backend` | complete (verified): GitHub Actions run 42000377582 on `42da12e`, both jobs passed (public GitHub API, 6 Nov 2026) | — |
| M4-A | Integration architecture and PRD amendment: D04-A1 and FR03 v2 approved by the owner (pretrained-first research track, TF-IDF kept as baseline); C-11 resolved; supervised SMS worker contract (manifest, pipes protocol, TD-18 admission/timeout/kill/restart, outcome table, score semantics, privacy path, schema-v2 signals, test plan) (`M4_SMS_INFERENCE_ARCHITECTURE.md`). Documentation only | `backend` | complete (verified): GitHub Actions run 42268142297 on `73b43fd`, both jobs passed (public GitHub API, 6 Nov 2026) | — |
| M4-I.1 | Isolated SMS worker (`workers/sms/`, own lockfile, stdlib default + `model` group), Git-versioned manifest v1, supervisor in `kavach.models` (pipes protocol, TD-18 admission/timeouts/SIGKILL/backoff/circuit, model-copy lock, env allowlist), fake-worker fault tests, real-model offline smoke test (`M4_I1_SMS_WORKER_REPORT.md`). **Not connected to ingestion** | `backend` | complete (verified): GitHub Actions run 42274378378 on `7e4fbcc`, both jobs passed including the worker lockfile, tests and Ruff steps (public GitHub API, 7 Nov 2026) | — |
| M4-I.2 | The worker connected to authenticated SMS ingestion (off by default): settings and lifespan, inference after the replay lookup and outside transactions, 429/503 rejection before storing, signals version 2 (native uncalibrated evidence; `sms_score` null; tier `unknown`), authenticated `/api/v1/system/models`, simulator accepts the documented outcomes. Real end-to-end run with the real model offline (`M4_I2_SMS_INTEGRATION_REPORT.md`) | `backend` | complete (verified): GitHub Actions run 42369713267 on `79ff21c`, both jobs passed including the worker tests (public GitHub API, 7 Nov 2026) | — |
| M4-Q | Solo human evaluation workflow for the pretrained SMS model: blinded 183-row sheet (revision 2, 8 Nov 2026: 10 more UCI ham campaigns so the unchanged 0.10 legitimate Wilson limit is reachable; criteria v2 beside the preserved v1) (non-held-out in both split versions, disjoint from the audit and pilot, one message per campaign, collected and synthetic reported separately), criteria registered before any label, offline scoring only after the sheet is complete (`M4_Q_SOLO_EVALUATION.md`). **No label exists and no result is claimed** | `backend` | in progress: workflow prepared and verified locally on 7 Nov 2026; uncommitted; **not yet run on GitHub** | The owner labels the sheet (about 45 min); `solo-preflight` must report READY; then `solo-evaluate` runs once, only on the owner's explicit authorization; a solo result never replaces the independent label gate |
| M4-Q.1 | Read-only `solo-preflight` (no model, no text, IDs or names): PASS / FAIL / NOT EVALUATED per check, zero-denominator unclear share is NOT EVALUATED, only all-PASS is READY; summary line derived from the printed checks (on the blank sheet: 22 checks, 12 PASS, 8 FAIL, 2 NOT EVALUATED → "10 checks not passing"), so the count cannot drift from the output | `backend` | in progress: verified locally on 9 Nov 2026 (experiments 275 passed, Ruff clean); uncommitted; **not yet run on GitHub** | Part of the M4-Q commit |
| MVP-1 | **SMS MVP-1 (current priority, owner decision C-12, 9 Nov 2026):** items MVP-B1–B7, MVP-F1–F3 and MVP-J in [MASTER_DEVELOPMENT_PLAN.md](MASTER_DEVELOPMENT_PLAN.md) "SMS MVP-1"; contract in [API.md](API.md) "SMS MVP-1 contract"; first integration into `dev` after joint acceptance ([INTEGRATION_PLAN.md](INTEGRATION_PLAN.md)) | `backend`, `frontend` | in progress (12 Nov 2026): backend and frontend integrated in `dev` at `61cbffa` (PRs #1 and #2); joint acceptance and security audit passed on `61cbffa`; model decision (MVP-B1/B2) outstanding; release to `main` not done | MVP-B1/B2; `dev` → `main` release checklist |
| MVP-B1 | M4-Q completion (labeling, preflight READY, owner-authorized single evaluation, report) | `backend` | blocked: owner labelled all 183 revision-2 rows; preflight **NOT READY** (owner record, 12 Nov 2026: 20 PASS, 2 coverage failures: collected spam 19 of minimum 25, synthetic benign 1 of minimum 16). Result preserved; no evaluation run; no further labelling planned for now | Coverage shortfall; owner decision on next step |
| MVP-B2 | MVP model decision under C-12 D (worker disabled until then) | `backend` | not started (no M4-Q verdict). Separately, decision C-13 (approved 12 Nov 2026) allows only an *experimental local* mode on fictional data; it is not a C-12 D verdict and does not change normal operation | MVP-B1 |
| MVP-B3 | Incident read APIs with `channel` filter | `backend` | complete (verified): committed in `50431e9`; Backend CI green (runs 42517472445, 43094400802); exercised in real browser journeys on 11–12 Nov 2026 | — |
| MVP-B4 | Admin browser SMS submission | `backend` | complete (verified): committed in `50431e9`; Backend CI green; real browser submission, viewer 403, CSRF and Origin rejection verified on 11–12 Nov 2026 | — |
| MVP-B5 | D08 read limit (120/min/user, fail closed) | `backend` | complete (verified): committed in `50431e9`; Backend CI green; 429 countdown observed in the browser and 503 with Redis stopped on 11–12 Nov 2026 | — |
| MVP-B6 | OpenAPI snapshot and contract tests | `backend` | complete (verified): committed in `50431e9`; Backend CI green; `frontend/contract/openapi.json` byte-identical (SHA-256 `fb9b8344…4188`) | — |
| MVP-B7 | Local integration launch | `backend` | in progress: local launch with the worker **disabled** verified on 11–12 Nov 2026 ([LOCAL_DEMO.md](LOCAL_DEMO.md)); launch with a model decision not possible until MVP-B2 | MVP-B2 |
| MVP-F1–F3 | Frontend MVP (scaffold and shared components; overview, history, detail, system; `/analyze` only after MVP-B4) | `frontend` | complete (verified): F1–F3 Frontend CI green on `c052536` (run 42569028071); redesign, landing page, motion control and real-backend tests in `988cb1e` with Frontend CI green (run 43093871566); 136 unit tests and 17 real-backend browser journeys passed | — |
| MVP-J | Joint acceptance, integration report, owner PRs into `dev` | `backend`, `frontend` → `dev` | complete (verified): PR #1 (`5bcd68a`) and PR #2 (`61cbffa`) merged; PR CI green (runs 43153039779, 43153039726) and Backend CI green on the `dev` push (run 43153516772); joint acceptance re-run on `61cbffa` ([MVP1_INTEGRATION_REPORT.md](MVP1_INTEGRATION_REPORT.md), [SECURITY_AUDIT_REPORT_MVP1.md](SECURITY_AUDIT_REPORT_MVP1.md)) | — |
| PUB-1 | Login-free public site (decision C-14): static home and recorded-examples pages with no API calls; operator console moved under `/admin`; anonymous-access route inventory test; proposal for a public analyzer (C-15, not approved) | `frontend`, `backend` (tests) | implemented on branch `feature/public-login-free-site`; pull request into `dev` pending; not deployed | Owner review and merge; C-15 decision |
| M4 | SMS detection and evaluation | `backend` | in progress: M4.1 verified on GitHub; M4.2 verified on GitHub (run 41900502306, `ce63aca`) with label approval BLOCKED; M4.2 data-quality review done locally; M4.3–M4.4 not started and blocked on the label audit and the split decision | M3; D04 (approved 5 Nov 2026) |
| M5 | Voice transcription, intent, synthesis indication | `backend` | not started; **postponed until after MVP-1** (C-12) | M3; D04 data/licensing/hardware |
| M6 | Correlation and continuous fusion | `backend` | not started; **postponed until after MVP-1** (C-12). `ui-sub-` subscriber tokens from browser submissions are synthetic and must never count as identity evidence (B4-1) | M4, M5; D05, D06; paired labeled data |
| M7 | Analyst dashboard (M7a backend incident/review API, M7b frontend UI). The MVP-1 subset (incident reads, SMS UI) is tracked under MVP-1; review APIs and the review form are postponed (C-12 B) | `backend`, `frontend` | not started (outside MVP-1) | MVP-1; M6 for pairs; D09 |
| M8 | End-to-end integration and workflows (includes simulator UI) | `dev` | not started | MVP-1 integrated; remaining M7 review work; health-path compatibility plan (C-07) |
| M9 | Security, privacy, resilience | `dev` | not started | M8 |
| M10 | Adversarial evaluation, ablation, calibration, benchmarks | `dev` | not started | M9; representative data |
| M11 | CI/CD, Docker, release, demo readiness | `dev` → `main` | not started | M10; D10 for anything beyond local |

## Verified baseline (historical, 31 October 2026 audit)

These are results of past runs, not a statement about the current tree. Re-run before any milestone relies on them.

| Item | Value |
| --- | --- |
| Commit at the time | `754a22a` ("feat: initialize KAVACH backend foundation"), the same on `main`, `dev`, `backend`, `frontend` and their `origin/` counterparts. `dev` now additionally carries uncommitted M0 documentation changes. |
| Backend tests | `backend/.venv/bin/python -m pytest backend/tests`: 88 passed, 1 Starlette/httpx deprecation warning |
| Lint / format | `ruff check backend`: passed; `ruff format --check backend`: 17 files formatted |
| Implemented routes | `GET /health`, `GET /api/v1/health` (liveness only, `analysis_ready: false`) |
| Not implemented | event endpoints, auth, PostgreSQL, Redis, models, correlation, frontend, CI, Compose |

## M1.1 local verification (31 October 2026, historical once recorded)

Generated with uv 0.11.16 for Python `==3.12.*` from `https://pypi.org/simple`. `backend/uv.lock` lists 27 packages (26 third-party plus the editable project). The GitHub Actions workflow has **not** run; nothing here claims CI is passing.

| Check | Existing `backend/.venv` (pip-built, Ruff 0.17.3, unchanged) | Fresh environment from `uv sync --locked` (Ruff 0.17.2) |
| --- | --- | --- |
| `uv lock --check --project backend` | n/a | passed |
| pytest `backend/tests` | 88 passed, 1 warning | 88 passed, 1 warning |
| `ruff check backend` | passed | passed |
| `ruff format --check backend` | 17 files already formatted | 17 files already formatted |

The fresh environment was created in a temporary directory outside the repository via `UV_PROJECT_ENVIRONMENT`; `backend/.venv` was confirmed unmodified afterward. The workflow YAML was parsed and checked structurally (triggers, `contents: read`, SHA-pinned actions); `actionlint` was not available and was not run.

### Locked versions

| Package | Version | Kind |
| --- | --- | --- |
| annotated-doc | 0.0.5 | transitive |
| annotated-types | 0.8.0 | transitive |
| anyio | 4.15.1 | transitive |
| certifi | 2026.10.23 | transitive |
| click | 8.5.0 | transitive |
| colorama | 0.4.6 | transitive (Windows-only marker) |
| fastapi | 0.162.0 | direct |
| h11 | 0.16.0 | transitive |
| httpcore | 1.0.9 | transitive |
| httpx | 0.28.1 | dev group |
| idna | 3.20 | transitive |
| iniconfig | 2.3.1 | transitive |
| kavach-backend | 0.1.0 | project (editable) |
| opentelemetry-api | 1.45.2 | transitive |
| packaging | 26.3 | transitive |
| pluggy | 1.7.0 | transitive |
| pydantic | 2.14.1 | direct |
| pydantic-core | 2.50.1 | transitive |
| pydantic-settings | 2.16.1 | direct |
| pygments | 2.21.0 | transitive |
| pytest | 9.1.1 | dev group |
| python-dotenv | 1.2.4 | transitive |
| ruff | 0.17.2 | dev group |
| starlette | 1.10.0 | transitive |
| typing-extensions | 4.16.0 | transitive |
| typing-inspection | 0.4.4 | transitive |
| uvicorn | 0.54.0 | direct |

## M4.2 data preparation verification (5 November 2026, historical once recorded)

GitHub Actions has **not** run the M4.2 changes; everything below is local. Baseline: `0845ed2`, run 41891028870, both jobs passed. Full report: [M4_2_DATA_PREPARATION_REPORT.md](M4_2_DATA_PREPARATION_REPORT.md).

| Item | Value |
| --- | --- |
| Dependencies / migrations | backend: none / none; `experiments/` has its own lockfile (20 packages; training group scikit-learn 1.9.1, numpy 2.5.4, scipy 1.18.1 not installed by default; OSV: no advisories) |
| Acquisition | IMC25 (commit-pinned), UCI and Mishra verified against manifest v2 checksums; 0 unknown archive members; Munoz not fetched |
| Data | 46,134 records; 15,891 clusters (Jaccard 0.7); 28,032 records assigned to splits; 0 clusters, 0 texts and 0 near-duplicate pairs (0.7/0.8) cross splits; 0 simulator matches |
| Label audit | **BLOCKED**: 1,485 items in a blinded bundle, 0 of 2,970 reviews done |
| Backend default suite | 267 passed (unchanged) |
| Backend integration suite | 319 passed (unchanged) |
| Experiments suite | 144 passed; four mutation probes each failed the suite |
| Ruff / lock | backend 78 files and experiments 27 files formatted and clean; both `uv lock --check` passed; `alembic check` clean |
| Verdict | **CONDITIONAL** |

## M4.1 dataset governance verification (4–5 November 2026, historical once recorded)

GitHub Actions has **not** run the M4.1 changes; everything below is local. Baseline: `90c32b4`, run 41885380731, both jobs passed.

| Item | Value |
| --- | --- |
| Dependencies / migrations | none / none; `backend/pyproject.toml` gains only pytest `pythonpath` and Ruff `src` entries for `experiments/` |
| Datasets | Four downloaded and measured (SHA-256, rows, classes, duplicates, overlap, near-duplicates); `experiments/audit/dataset_audit.py` reproduces all 51 recorded values and fails on a wrong file |
| Default suite | 304 passed (37 new in `test_dataset_manifest.py`: shipped manifest valid and pending, no automatic phishing labels, spam stays spam, generated data never evaluates, 26 rejected policy breaks, fixture fingerprints) |
| Integration suite | see the final report; unchanged by M4.1 |
| Ruff / lock | `ruff check backend` and format check passed; `experiments/` linted with the backend config; `uv lock --check` unchanged |
| Verdict | **CONDITIONAL**: D04 is not approved and no hard-negative source exists |

## M3.4 acceptance verification (4 November 2026, historical once recorded)

Recorded before the push; GitHub Actions later passed both jobs on `90c32b4` (run 41885380731). Full report: [M3_INGESTION_ACCEPTANCE.md](M3_INGESTION_ACCEPTANCE.md).

| Item | Value |
| --- | --- |
| Baseline | `bf403a8`, GitHub Actions run 41879325247, both jobs passed |
| Dependencies / migrations | none / none (`alembic check` clean) |
| Default suite | 267 passed |
| Integration suite | 319 passed after the TD-19 fix (11 TD-19 tests: valid keys on a blocked IP, bounded lookups, revoked/expired keys, scope and quota, Redis outages, two processes, privacy; earlier 308 with 11 acceptance tests: late replay keeps expired candidates out, prompt replay repairs, ambiguous commit retried, forwarded headers vs the throttle (in-process and real Uvicorn with and without `--no-proxy-headers`), payload-key rotation, removed payload key, subscriber-key rotation, deep JSON ×2) |
| Real stack | simulator 12/12, 20 submissions, 0 candidate mismatches; Redis restart → rebuild restored 17 events; Redis paused → 503 in 0.51 s; PostgreSQL stop/start → 503 then 201/200; 413, 422, 429 `Retry-After: 59`; shared-IP lockout 429 `Retry-After: 900` before the TD-19 fix; after it a recently valid key authenticates from the blocked IP, 10 bounded lookups, then 429 |
| Ruff / lock | check passed, 78 files formatted / `uv lock --check` passed; fresh locked environment passed after the TD-19 fix |
| Verdict | **CONDITIONAL PASS** |

## M3.3 local verification (4 November 2026, historical once recorded)

Recorded before the push; GitHub Actions later passed on `bf403a8` (run 41879325247).

| Item | Value |
| --- | --- |
| Dependencies / migrations | none / none (`alembic check` clean) |
| Default suite | 267 passed (70 new: catalog validity and 17 invalid-catalog cases, D05 boundary margins, deterministic planning, payloads valid without labels, run-ID and loopback-target restrictions, pacing under the per-key limit, 429 Retry-After with identical resend and capped retries, stop on 401/403/5xx/unreachable, submission cap, local key checks, key only from environment or stdin, redacted text and JSON output, dry run sends nothing, catalog endpoint fails closed) |
| Integration suite | 297 passed (14 new: whole catalog against real services with stored rows, standalone incidents, tier `unknown`, null scores, no pair incidents, unchanged conflict original and Redis candidate expectations; privacy scan of runner output, logs, Redis and database; same seed and run ID replays identically; wrong-source key and revoked key stop after one submission; real 429 handling; PostgreSQL and Redis outages; CLI over real loopback HTTP; admin-only catalog with viewer/analyst/anonymous/API-key/mixed/deactivated denials) |
| Demonstration | Uvicorn on a disposable Compose stack: 12/12 scenarios, 20 submissions, 16 events (all standalone, tier `unknown`, no scores), 0 candidate-expectation mismatches; rerun of the same run ID reported as 409; external target refused (exit 2); Redis paused and PostgreSQL stopped each aborted after one 503 with nothing stored; recovery run passed |
| Ruff / lock | check passed, 76 files formatted / `uv lock --check` passed |

## M3.2 local verification (4 November 2026, historical once recorded)

Recorded before the push; GitHub Actions later passed on `14e23d9` (run 41867501351).

| Item | Value |
| --- | --- |
| Dependencies / migrations | none / none |
| Default suite | 197 passed (10 new: D05 boundaries, Redis key privacy, Retry-After, closed and hung Redis fail closed), 283 deselected |
| Integration suite | 283 passed (17 new: index contents/TTL, replay without duplicates, out-of-order arrival, inclusive 30-minute window, 40-minute horizon and pruning, per-subscriber cap, no pair incidents, two processes sharing one index, 30/minute limit with replays counted, per-key limits, sliding recovery, two processes capped at exactly 30, invalid-Bearer ceiling with refunds, deadline abort and retry, Redis outage before storage, Redis failure after commit and both recovery paths, CLI rebuild, Redis privacy scan) |
| Real outages | Redis paused → 503 in 0.51 s; stopped → 503; nothing stored either time; restart emptied the index, `rebuild` restored it; PostgreSQL stopped → 503, restored → 201 |
| Ruff / lock | check passed, 67 files formatted / `uv lock --check` passed |

## M3.1 local verification (4 November 2026, historical once recorded)

GitHub Actions has **not** run the M3.1 changes; everything below is local.

| Item | Value |
| --- | --- |
| Endpoints | `POST /api/v1/events/sms`, `POST /api/v1/events/call`, `GET /api/v1/events/{id}` (ingestion keys only) |
| Dependencies / migrations | none added / none (existing `events` schema) |
| Default suite | 187 passed (25 new: canonicalization, keyed digests, stage reporting, configuration, unauthenticated bodies never read), 266 deselected |
| Integration suite | 266 passed (29 new: create/replay/conflict, per-source IDs, concurrency, key scope and validity, validation bounds, audio references, receipt recovery, audit rollback, database outage, privacy scan of every stored row and log) |
| Concurrency evidence | 8 identical concurrent submissions → one 201 and seven 200, one row; 8 conflicting → one 201 and seven 409. Instrumented runs: 7–14 of 14 losing requests took the `ON CONFLICT DO NOTHING` path |
| Real outage | PostgreSQL container stopped → 503, nothing stored; restored → replay 200, failed event created on retry 201 |
| Ruff / lock | check passed, 63 files formatted / `uv lock --check` passed |

## M2.5 security acceptance (4 November 2026, historical once recorded)

Full report with evidence: [M2_SECURITY_ACCEPTANCE.md](M2_SECURITY_ACCEPTANCE.md). GitHub Actions has **not** run the M2.5 changes.

| Item | Value |
| --- | --- |
| Findings | 0 critical, 0 high; 3 medium (M-1 retention role could delete unexpired rows, M-2 retention audited only after commit, M-3 revocation reversible) **fixed**; 7 low (3 fixed, 4 open/accepted); 3 informational |
| Schema change | revision `0002_retention_procedure`: `kavach_retention_purge` (SECURITY DEFINER, expired rows only, no future cutoff), retention role table grants revoked, `revocation_is_final` triggers; no table or column changes |
| Default suite | 162 passed, 237 deselected |
| Integration suite | 237 passed (30 new acceptance tests), both environments |
| Ruff / lock | check passed, 56 files formatted / `uv lock --check` passed, no dependency changes |
| Advisories | OSV.dev: no known advisories for the 39 locked third-party packages |
| Real outages | Redis and PostgreSQL containers stopped and restarted: login 503 with 0 password verifications, recovery to 200 |

## M2.4 local verification (3 November 2026, historical once recorded)

GitHub Actions has **not** run the M2.4 changes; everything below is local.

| Item | Value |
| --- | --- |
| Dependencies | none added; 40 lock entries; `uv lock --check` passed |
| Default suite | 162 passed (18 new: key format and scope, CLI argument safety, retention guards), 207 deselected |
| Integration suite | 207 passed (39 new: key enforcement/expiry/rotation/revocation, operator authorization and last-admin protection, audit rollback/tamper/deletion limits, CLI lifecycles, retention boundaries/dry run/permissions) |
| Ruff | check passed; 54 files formatted (0.17.3 and 0.17.2) |
| Real-service probes | PostgreSQL container stopped → key auth 503, CLI exit 3; restored → 200; destructive retention on `kavach_dev` and a mismatched `--database` refused |
| Removed | `kavach.auth.provision` (it created accounts with no operator authentication); replaced by `kavach.cli user create` (admin actor, or explicit bootstrap) |
| Changed existing tests | auth fixtures moved to `integration/conftest.py` and now provision through a bootstrap operator; provisioning audit now attributes the admin actor instead of `system` |

## M2.3 local verification (31 October 2026, historical once recorded)

GitHub Actions has **not** run the M2.3 changes; everything below is local.

| Item | Value |
| --- | --- |
| New dependencies | `argon2-cffi==25.1.0` (direct); `argon2-cffi-bindings` 26.1.0, `cffi` 2.1.1, `pycparser` 3.12 (transitive); 40 lock entries; no existing version changed |
| Endpoints | `POST /api/v1/auth/login`, `GET /api/v1/auth/session`, `POST /api/v1/auth/logout` |
| Default suite | 144 passed (40 new service-free auth tests, including real closed-port and hung-socket Redis outages), 168 deselected |
| Integration suite | 168 passed (27 new auth tests against real PostgreSQL and Redis, including a two-process throttle test: 12 concurrent wrong-password attempts → exactly 5 × 401 and 7 × 429) |
| Ruff | check passed; 50 files formatted (0.17.3 and 0.17.2) |
| Real outage probe | Redis container stopped mid-run → login 503 in 0.00 s with only sanitized telemetry; restarted → 200 |
| Provisioning CLI probe | provisioned an account from stdin; rejected a short password and a duplicate (case-insensitive) username |
| Changed existing tests | OpenAPI path set (adds auth routes); pilot docs test now supplies the complete test-only configuration pilot requires |

## M2.2 local verification (31 October 2026, historical once recorded)

GitHub Actions has **not** run the M2.2 changes; everything below is local (Docker 29.8.0, linux/aarch64, the digest-pinned PostgreSQL 17.11 image).

| Item | Value |
| --- | --- |
| New dependencies | `alembic==1.20.0` (direct); `mako` 1.4.3 and `markupsafe` 3.0.4 (transitive); 36 lock entries; no existing version changed |
| Schema | 9 tables, 35 CHECK constraints, 8 unique constraints, 12 foreign keys (3 composite, of which the 2 circular ones are deferred), 9 secondary indexes, 4 deferred constraint triggers, `users.updated_at` trigger (counted from the SQLAlchemy metadata, which `alembic check` matched to the database) |
| Migration | fresh `upgrade head` succeeded; repeated `upgrade head` was a no-op; `alembic check`: no differences; downgrade refused without explicit permission and for `kavach_dev`; downgrade + upgrade round trip on `kavach_test` passed |
| Integration tests | 141 passed: 70 constraint, 48 privilege, 12 migration, 11 service (both environments) |
| Default tests / Ruff | 103 passed, 141 deselected, 1 warning; Ruff check passed; 31 files formatted |
| CI replay | the integration job's commands, including the new migration gate, passed locally with fresh passwords; cleanup left no containers or volumes |
| Mutation probe | dropping the incident integrity triggers (rolled back) let an invalid incident through, confirming the tests detect their absence |

## M2.1 local verification (31 October 2026, historical once recorded)

GitHub Actions has **not** run the M2.1 changes; everything below is local.

| Item | Value |
| --- | --- |
| New direct dependencies | `sqlalchemy==2.0.55`, `psycopg[binary]==3.3.6`, `redis==8.1.0` |
| New lock entries | sqlalchemy 2.0.55, psycopg 3.3.6, psycopg-binary 3.3.6, redis 8.1.0, greenlet 3.5.6 (x86_64/aarch64 Linux and Windows only), tzdata 2026.6 (Windows only); no existing version changed; 33 entries total |
| Approved but deferred | `alembic==1.20.0` (M2.2), `argon2-cffi==25.1.0` (M2.3); added only when first used |
| PostgreSQL image | `postgres:17.11-bookworm@sha256:839fbb5a4942a7758dd93e18b42ea5649807491a0545b5eeeb8f0b8bb11857a5` (index; linux/amd64 and linux/arm64/v8) |
| Redis image | `redis:7.4.12-alpine@sha256:8da19c7399dca900c6822a1cf30f9d2285585e2c4b457ff4095b0f4500054d3f` (index; linux/amd64 and linux/arm64/v8) |
| Default suite | 103 passed, 11 deselected, 1 warning (existing `backend/.venv` and fresh locked environment) |
| Integration suite | 11 passed against the Compose services (both environments); CI job commands replayed locally: 11 passed, cleanup left no containers or volumes |
| Missing service variables | `pytest -m integration` fails (4 failed, 7 errors), it does not skip |
| Ruff | check passed; 24 files already formatted (0.17.3 and 0.17.2) |
| Manual probes | wrong PostgreSQL password rejected; Redis password absent from the container process list; `kavach_*` roles not superuser; only the three roles have database access |

## Conflict decisions (owner, 31 October 2026)

C-01 to C-05 approved; C-06 approved (shared Redis login throttling; login fails closed with 503 if Redis cannot validate throttle state; no in-process fallback; API.md and ARCHITECTURE.md updated in M2.1; `RATE_LIMIT_HMAC_KEY` added to the API.md inventory); C-07 deferred (M1 health routes and tests preserved); C-10 resolved by the CONTRIBUTING.md update. Details are in MASTER_DEVELOPMENT_PLAN.md.

## Decisions

The owner's conflict and Git decisions do not approve any item below marked pending.

| ID | Topic | Status |
| --- | --- | --- |
| D01 | Scope | Approved for the backend foundation only; remaining use needs a recorded decision |
| D02 | Stack and **package choices** | **Approved 31 Oct 2026** for M2: SQLAlchemy 2.0.55, Alembic 1.20.0, psycopg[binary] 3.3.6, argon2-cffi 25.1.0, redis 8.1.0, the digest-pinned PostgreSQL 17.11 and Redis 7.4.12 dev images. Frontend packages still pending |
| D03 | Authentication | **Approved direction 31 Oct 2026**: provisioned accounts (viewer/analyst/admin), Argon2id with versioned parameters and rehash, database-backed opaque sessions (30 min idle, 8 h absolute), HttpOnly + SameSite=Lax cookies (Secure outside explicit local development), session-bound CSRF and exact Origin, source-scoped Bearer ingestion keys (90-day default, expiry, revocation), no public registration. Denied logins → sanitized security telemetry, not permanent audit rows; successful authentication and account/key lifecycle changes are audited |
| D04 | Dataset and model provenance | **SMS data approved by the owner on 5 Nov 2026** (decisions 1–7, scoped to SMS): IMC25 provisional positives subject to audit, UCI primary benign, Mishra audit reference, Munoz excluded, synthetic hard negatives reported separately, class-promotion gate at a 95% Wilson lower bound of 0.95, separate training environment. Recorded in `sms_datasets.v2.json`. Voice data and models remain unresearched and unapproved |
| D05–D06, D08–D09 | Correlation window, tiers, limits, UI | Proposed, unapproved; each gates the milestone listed in the master plan |
| D07 | Retention | **Approved 31 Oct 2026 for the synthetic-data local MVP only**: synthetic events/incidents 7 days; metadata-only audit 30 days; metadata-only application logs 14 days; deactivated users and referenced keys follow referential integrity and explicit cleanup rules; all configurable. Not authorization to ingest real user data |
| D10 | Hosting | **Pending explicit approval**; local Compose is the working assumption only |

## Technical debt

| ID | Item | Impact | Target |
| --- | --- | --- | --- |
| TD-01 | ~~`backend/uv.lock` absent~~ Addressed in M1.1 (uncommitted): lock generated with uv 0.11.16, 27 packages, `uv lock --check` passes, fresh isolated install verified. The earlier timeouts did not reproduce: the PyPI index answered in 0.13 s and resolution took 0.4 s, so the cause is attributed to the earlier execution environment's network sandbox, not the index or manifest (not proven). | — | Close when committed and CI is green |
| TD-02 | Ruff pin: **kept at the documented 0.17.2** (manifest and lockfile); 0.17.2 verified clean in the fresh environment. The existing `backend/.venv` still has 0.17.3 until the user syncs it (see README Setup). | Local pip venv differs from lock until synced | Close when committed and CI is green |
| TD-03 | ~~CI not yet run~~ The lint/test job passed on `c36e903`. The new M2.1 integration job has not run on GitHub yet | Integration job unproven on GitHub | Close after both jobs are green on the M2.1 push |
| TD-04 | `starlette.testclient`/`httpx` deprecation warning; the warning suggests `httpx2` (still present in the M1.1 runs: 88 passed, 1 warning) | May become an error in a later Starlette | Evaluate when dependencies are next touched |
| TD-12 | Lockfile resolved `opentelemetry-api` 1.45.2 (transitive via FastAPI 0.162.0; released 29 Oct 2026), while the pip venv has 1.45.1. Tests pass with both | Minor drift between local venv and lock | Disappears when the user syncs `backend/.venv` |
| TD-13 | Retention runs are operator-triggered and destructive only on `*_test` databases; no schedule exists. Since M2.5 the retention role is limited to the expiry procedure and runs are audited before deleting | Synthetic dev data is not yet cleaned automatically | Scheduling and the dev/pilot policy with the deployment milestone (M11) |
| TD-14 | Login and invalid-key throttles key on the client address Uvicorn reports. **Corrected in M3.4 (M34-M1):** the application ignores `X-Forwarded-For`, but Uvicorn by default trusts it from `127.0.0.1`/`::1` and rewrites the address first, so the README launch now requires `--no-proxy-headers`. Behind a proxy without trusted-proxy configuration every client shares the proxy's address and ceilings | Launch flags are not enforced by code; proxied deployments need `--forwarded-allow-ips` set to the proxy only | Encode in the deployment artifact with a startup check (M11) |
| TD-15 | ~~No operator commands for deactivation, reset or role change~~ Implemented in M2.4 (`python -m kavach.cli`) | — | Closes with M2.4 |
| TD-16 | The documented admin session path for event submission (`simulator` source + CSRF) and admin receipt reads is not implemented; M3.1–M3.3 are key-only, and the M3.3 runner uses an ingestion key scoped to `simulator`, the same source name the admin path would use (shared idempotency namespace) | Browser simulator cannot submit yet | With the simulator UI (M8) or on approval |
| TD-17 | No approved audio sample manifest (`AUDIO_SAMPLE_MANIFEST_PATH`): every non-null `audio_reference` is rejected; the manifest contract is documented in API.md (M3.3) but not read | Calls are metadata-only; the PRD's "benign synthetic IVR" journey cannot run; catalog `samples` is empty | Approve the sample list (D04 provenance) before voice analysis (M5) |
| TD-18 | D08: the 30/minute/key submission limit and the 30-second deadline are enforced (M3.2); `MAX_INFLIGHT_ANALYSES` (2 concurrent analyses) is not, because it bounds model inference and no models exist | Admission control arrives with the first model. **Designed 6 Nov 2026** (M4_SMS_INFERENCE_ARCHITECTURE.md §6): 2 slots, 1 executing and 1 waiting; per-request timeout with SIGKILL; backoff restart; circuit breaker. **Implemented in the supervisor (M4-I.1) and enforced on SMS ingestion (M4-I.2, 7 Nov 2026)** when the worker is enabled; load testing not done | M5/M11 |
| TD-19 | Invalid-Bearer ceiling: 30 rejected credentials per IP per 15 min. **Lockout of valid keys fixed in M3.4 (owner request):** a well-formed key from a blocked IP is still checked if it authenticated in the last 24 h or within a 10-lookups-per-minute IP budget; everything else gets 429 without a database lookup | Values (30/15 min, 10/min, 24 h) await owner confirmation; a key unused for 24 h can wait up to a minute during an active attack; shares the proxy limitation of TD-14 | Confirm the values; revisit with trusted-proxy handling (M11) |
| TD-20 | D05 window (30 min) and lateness (10 min) are adopted from the proposal for the candidate index; formal approval is still pending | M6 matching depends on them | Approve before M6 |
| TD-21 | The 1,200-member per-subscriber candidate cap can evict in-horizon candidates (one key at full rate with future skew, or several sources for one subscriber); `near()` can return members past the horizon until the next write (M34-M3, M34-L3) | No impact until matching exists | M6: confirm candidates from PostgreSQL (`ix_events_candidates`) and re-check eligibility, or set a different cap |
| TD-22 | Subscriber-key rotation gives the same token a new pseudonym and candidate set, so pairs spanning a rotation are not candidates (M34-L4) | Cross-rotation pairs missed | M6 design or a rotation procedure |
| TD-23 | The IMC label audit needs 2 independent human reviewers plus an adjudicator for 1,485 items (2,970 reviews). Until it is done, no class is promoted and M4.3 cannot start | Blocks all SMS model work | Owner arranges the review; `python -m sms_prep audit` then decides |
| TD-24 | IMC was anonymized (82% of rows carry entity placeholders). Feature normalization removes the markers, but IMC lost names and places that UCI and the synthetic data keep, and date-time token shares still differ by source | Possible residual source shortcut | M4.3 source-probe on spam; per-source reporting |
| TD-25 | Near-duplicate pairs cross the frozen split below the 0.7 clustering threshold: 870 at ≥ 0.6, 4,702 at ≥ 0.5, 19,181 at ≥ 0.4. The review found them to be templated campaign variants (all 54 hand-checked pairs in the 0.4–0.6 bands). In v1, 17.2% of test texts (26.9% of banking) have a training neighbour at ≥ 0.4 | Optimistic test results on recurring campaigns | **Mitigated by proposed `sms_split.v2` (5 Nov 2026), pending owner adoption:** 0 cross-split pairs at ≥ 0.4; residual 501 pairs at ≥ 0.35 and 2,435 at ≥ 0.3 (4.4% / 10.8% of test texts; banking 6.6% / 16.4%). Not leak-free. v2 also puts one banking campaign (52.5% of banking records) wholly in train and files 5.6% of IMC records under another class's stratum, so M4.3 must report per-class results by each record's own class |
| TD-26 | SMS text reaches the worker process memory (M4-I design). Python cannot zero freed memory, so text can stay resident in the API and worker processes until it is overwritten | Text residency on a compromised or swapped host; core dumps are disabled in the worker and encrypted swap is the operator's control; revisit for any real-data pilot (D07) | M11 |
| TD-27 | The SMS worker's offline guarantee is library configuration (`HF_HUB_OFFLINE`, an environment allowlist) plus a socket-guard test, not OS enforcement | A library bug or future dependency could open a connection; add a Linux network namespace or seccomp for the worker in the container deployment | M11 |
| TD-05 | `docs/AGENTS.md` duplicates root `AGENTS.md` with relative paths | Rules can drift; root `AGENTS.md` is authoritative | Decide whether to keep or reduce to a pointer |
| TD-06 | Stale Git/status statements: README and ARCHITECTURE.md line 7 corrected in M0; CONTRIBUTING.md branch rules added in M0. PRD document map now lists the six new documents | Reader confusion | Separate approved docs change |
| TD-07 | ~~Development/test PostgreSQL and Redis not defined~~ Defined in M2.1: `deployment/compose.dev.yml` | — | Closes with M2.1 |
| TD-08 | Public `/health` vs API.md's authenticated `/health` (C-07) | Contract mismatch once auth exists; deferred, M1 routes and tests preserved | Separate compatibility plan, owner approval |
| TD-09 | GitHub default branch (`dev` intended) and protection for `main`/`dev` not configured; protection for `backend` undecided | Nothing prevents force-push or direct pushes | After the first green CI run, on explicit owner instruction (user applies) |
| TD-11 | ~~API.md/ARCHITECTURE.md in-process throttling wording~~ Updated in M2.1 to the approved C-06 behavior | — | Closes with M2.1 |
| TD-10 | `.env.example` lists only `APP_ENV` and `LOG_LEVEL`; API.md lists the full variable set | Expected until each variable's feature lands | Per milestone |

## Update protocol

1. Change a milestone to `complete (verified)` only with the commands and results of its acceptance criteria attached to the task report.
2. Record scope reductions or reordering with the owner's decision and date; do not edit the acceptance criteria to fit what was built.
3. Keep conflicts in MASTER_DEVELOPMENT_PLAN.md; reference their IDs here.
