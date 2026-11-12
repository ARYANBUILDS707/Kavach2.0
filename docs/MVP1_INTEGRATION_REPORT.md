# SMS MVP-1 Integration Report

This report records the joint acceptance run for the first integration into `dev`, the approved SMS MVP-1 (decision C-12). The gate and the checklist are defined in [INTEGRATION_PLAN.md](INTEGRATION_PLAN.md). Results are point-in-time: re-run the commands before relying on them.

- **Dates:** 11–12 November 2026.
- **Scope:** local controlled demo only. Not deployed, not a pilot, no live telecom data.
- **SMS worker:** disabled throughout (`SMS_WORKER_ENABLED=false`). The M4-Q decision (MVP-B1/B2) has not been made, so no model output appears in the product.

## Candidates

| Part | Commit | CI on GitHub |
| --- | --- | --- |
| Backend | `50431e994a7436fda69e96810568645aee0682d2` (`backend`) | Backend CI green: push run 42517472445 and PR run 43094400802 |
| Backend in `dev` | `5bcd68a` (merge of PR #1, 11 Nov 2026 20:16 UTC) | Backend CI run 43094934847 completed successfully. It stayed "in progress" for a while during GitHub's Actions incident of 11 Nov 2026. |
| Frontend | `988cb1e` (`frontend`) | Frontend CI green: push run 43093871566 |
| PR #2 head (`frontend` with `dev` merged) | `39b77219917a669f78ead8000e6a6a2c8a39807e` | Green after the GitHub Actions outage of 11 Nov: runs 43153039726 (frontend) and 43153039779 (backend) |
| **Integrated `dev`** | **`61cbffa01e4f4b24ec64fdca6e390295d4b735b0`** (merge of PR #2) | Backend CI on the `dev` push: run 43153516772 success. Frontend CI has no `dev` push trigger (security finding M1); the tree is identical to `39b7721`, whose PR run passed. |

In `39b7721`, the backend paths are identical to `50431e9` and the frontend paths are identical to `988cb1e` (`git diff --stat` is empty for each). `61cbffa` has the same tree hash as `39b7721`.

## Final acceptance on the integrated `dev` commit (12 Nov 2026)

Every check below was repeated on `61cbffa`, extracted with `git archive`, with the same results as on `39b7721`:
- lockfiles in sync; backend 387 passed (1 skipped); Ruff clean; experiments 275; worker 40;
- migrations twice plus `alembic check` clean; integration 424 passed (1 skipped) against fresh disposable services;
- frontend `npm ci`, audit gate and `npm run verify` 136/136; contract byte-identical.

Playwright ran from the `dev` extraction against its backend, one spec per read-quota window: **17/17 passed**, with idle expiry run against `SESSION_IDLE_MINUTES=1`.

**API truth check:**
- `GET /system/models` returned `disabled`, `validated_on_kavach_data: false`.
- All 6 incidents were `unavailable`, `unknown`, with a null `final_score`.
- 5 sampled details had null `sms_score` and null assessment scores, no model output, and stage reason `model_not_deployed`.

**Direct probes:**
- Missing token, wrong token, and foreign Origin with a valid token all returned 403 `CSRF_REJECTED`; the foreign-Origin login was refused.
- A request with no cookie returned 401.
- Redis stopped gave 503 (liveness 200); PostgreSQL stopped gave 503; both recovered.
- Privacy scan of the database, Redis, logs and test output: 0 submitted text, 0 credentials.

The security procedure was executed in [SECURITY_AUDIT_REPORT_MVP1.md](SECURITY_AUDIT_REPORT_MVP1.md).

## Checks on the exact PR #2 head (`39b7721`, extracted with `git archive`)

| Check | Command | Result |
| --- | --- | --- |
| Lockfiles | `uv lock --check --project backend` (and for `experiments`, `workers/sms`) | all three in sync |
| Backend default suite | `uv run --project backend --locked pytest backend/tests` | 387 passed, 1 skipped (needs the real model), 424 deselected |
| Ruff | `ruff check backend`, `ruff format --check backend` | clean; 99 files formatted |
| Migrations | `alembic upgrade head` (twice), `current`, `check` | head `0002_retention_procedure`; second upgrade is a no-op; no drift |
| Backend integration | `pytest backend/tests -m integration`, fresh disposable PostgreSQL 17.11 and Redis 7.4.12 with random passwords | 424 passed, 1 skipped |
| Experiments | `pytest experiments/tests`, Ruff | 275 passed; clean |
| SMS worker (default environment) | `pytest workers/sms/tests`, Ruff | 40 passed; clean |
| Frontend install | Node 24.16.0 (`.nvmrc`), `npm ci` | succeeded |
| Advisory gate | `npm audit --audit-level=high` | passes: 0 high, 0 critical. 10 moderate, all ESLint/minimatch development tooling, not in the bundle. |
| Frontend verify | `npm run verify` (contract checksum, type freshness, lint, strict types, Vitest, build, bundle scan) | 136/136 tests; contract SHA-256 `fb9b8344…4188` matches backend `50431e9` |

**Real-model smoke test** (on `50431e9`, the same backend code): `pytest backend/tests/test_sms_worker_model.py -m model`, run under a macOS `sandbox-exec` network denial, gave 5 passed. It runs the pinned Horizon model on fictional messages only, and was run only to confirm the artifacts work. The product keeps the worker disabled.

## Real full-stack browser acceptance

- **Stack:** the frontend served by Vite on `127.0.0.1:5173`, its proxy to the backend (`50431e9`) on `127.0.0.1:8000` with `APP_ORIGIN=http://127.0.0.1:5173`, and disposable PostgreSQL and Redis.
- **Accounts:** a synthetic admin and a synthetic viewer, created with `python -m kavach.cli` in the disposable database.
- **Tests:** Playwright 1.64.1 (Chromium), with no request mocking.

| Journey or check | Result |
| --- | --- |
| Landing page, sign-in, session restored after reload, sign-out revokes the session | passed |
| Overview and System show the real `GET /system/models` state (Disabled, not validated on KAVACH data) | passed |
| Admin submits a synthetic SMS; receipt, incident history and the real incident detail match the API (analysis unavailable, tier unknown, scores null) | passed |
| Viewer has no Analyze page; server refuses the viewer's submission (403 `FORBIDDEN`) | passed |
| Missing CSRF token and a foreign `Origin` refused (403 `CSRF_REJECTED`) | passed |
| Malformed and unknown incident IDs show the same unavailable page | passed |
| Idle session expiry (backend with `SESSION_IDLE_MINUTES=1`): warning, end at the deadline, server agrees | passed |
| Tables at 390 px and 768 px, landing and sign-in at six widths, both themes, axe accessibility checks | passed |
| Motion control: one keyboard control pauses and resumes the decorative animation; reduced motion honoured | passed |
| Every browser API response carries a server request ID; no unexpected failed request or console error | passed |

Totals: 17 tests in 6 spec files. On the first full run, three tests hit the documented read limit (120 GETs per minute per user, 429 with a countdown), because every test signs in as the same account. Each passed when re-run in its own minute.

Two defects were found and fixed before `988cb1e`:
- the incident table overflowed its card at 768–899 px;
- a test read the overview tiles before they rendered.

**Degraded paths, run against the real services:**
- Redis stopped: login and session reads returned 503 `DEPENDENCY_UNAVAILABLE`; liveness stayed 200.
- PostgreSQL stopped: reads returned 503 `DEPENDENCY_UNAVAILABLE`.
- Both recovered fully when restarted.
- The read limit returned 429 and the UI showed its countdown.

**Privacy:** 12 events were stored from fictional texts. No submitted text was found in a full PostgreSQL data dump, in Redis keys or values, in the backend logs, or in browser storage. No credential appeared in any test output.

## Joint acceptance checklist ([INTEGRATION_PLAN.md](INTEGRATION_PLAN.md))

| # | Item | Status |
| --- | --- | --- |
| 1 | Backend checks; CI green on pushed commits | pass locally on `61cbffa`; CI green on `50431e9`, the PR #2 run and the `dev` push of `61cbffa` |
| 2 | Frontend checks; bundle clean | pass locally on `61cbffa`; CI green on `988cb1e` and on the PR #2 run |
| 3 | Contract matches the backend snapshot | pass (byte-identical OpenAPI) |
| 4 | Authentication: login, idle expiry, logout revocation, CSRF, Origin, fails closed without Redis | pass. Absolute expiry, inactive accounts and mixed credentials are covered by the backend integration suite only. |
| 5 | Authorization | pass for admin and viewer. **Analyst not run in the browser** (no analyst account); covered by backend tests. |
| 6 | Model state is the real state, worker disabled | pass |
| 7 | Degraded paths | pass: disabled, Redis down, PostgreSQL down, read limit. **Starting (503), saturation (429), timeout and crash not run in the browser**: they need the worker, which stays disabled. Covered by the backend integration suite. |
| 8 | Idempotency (replay 200, changed payload 409) | backend integration suite only; not exercised in the browser |
| 9 | Privacy | pass |
| 10 | Accessibility (keyboard, visible focus, text not colour) | pass (axe, keyboard tests); no screen-reader session was recorded |
| 11 | Preserved behaviour | pass (full backend suites unchanged) |

## Release checklist status for `dev` → `main` ([RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md))

Release scope: **local demo**. Open blockers before a `dev` → `main` release PR:

Done since the first draft: CI is green on the integrated commit, and the security audit report exists ([SECURITY_AUDIT_REPORT_MVP1.md](SECURITY_AUDIT_REPORT_MVP1.md)).

Still open:
1. **Documentation commit.** This report, the security audit report and the updated README, tracker, API notes, demo procedure and demo script must be on `dev` (owner commit and PR), and CI must be green on that `dev` commit before the release PR.
2. **Evaluation honesty.** No evaluation report exists, because M4-Q is unlabelled. The release notes must state that the SMS model is disabled and unvalidated, with no accuracy claim (README, UI and demo script comply).
3. **Branch protection** for `main` and `dev` is not applied (security finding M2); apply it or record a waiver in the release PR.
4. **Restore drill, monitoring and Compose release build** apply to research-host or pilot scope only. Mark them "not applicable" for a local-demo release.
5. **Release notes, the `dev` → `main` PR and an annotated tag** need owner approval. The `dev` → `main` PR triggers both CI workflows.

No critical or high finding is open. Open medium findings: M1 (no Frontend CI push trigger on `dev`) and M2 (no branch protection). Open low findings: L1 (no operator audit-HMAC verification) and L2 (10 moderate development-tool advisories).

## Not integrated or not claimed

- Voice and call analysis, correlation and fusion (M5, M6).
- Review workflow, live updates and the simulator UI (M7 advanced, M8).
- Deployment (M11); no URL exists.
- Any model accuracy. Outputs from the model, if it is ever enabled, are uncalibrated and not validated on KAVACH data.
