# KAVACH Milestone Tracker

Status as of 31 October 2026, from the read-only audit of that date, the M0 documentation work and the owner's decisions of the same day. All verification entries are **point-in-time historical results**; re-run the commands before relying on them. Update this file when a milestone's exit criteria are verified, not when work merely starts. Details and acceptance criteria are in [MASTER_DEVELOPMENT_PLAN.md](MASTER_DEVELOPMENT_PLAN.md). Dated execution results go in task reports.

Status values: `not started`, `in progress`, `blocked`, `complete (verified)`, `complete (unverified)`.

## Milestones

| ID | Milestone | Branch | Status | Blocked by / notes |
| --- | --- | --- | --- | --- |
| M0 | Repository, architecture alignment, workflow, reproducibility planning | `dev` | complete (documentation committed to `dev`; see the M0 task report for the hash) | C-07 deferred; PRD/API/ARCHITECTURE follow-ups noted under C-06 |
| M1 | FastAPI foundation | `main` (history) | complete (verified historically: 88 passed, Ruff clean on 31 Oct 2026; HTTP startup last verified 28 Oct 2026) | Debt TD-01, TD-02, TD-03 carried forward; M1 routes preserved (C-07 deferred) |
| M1.1 | Reproducible environment and minimal pytest + Ruff CI (pre-M2 planning milestone; approved as planned) | `feature/m1-1-ci` → `dev` | not started; implementation not yet authorized | Separate go-ahead; network/package actions; TD-01, TD-02, TD-03; D02 (tools, action versions) |
| M2 | PostgreSQL, migrations, identity, scoped auth, audit | `backend` | not started | M1.1; D02 packages, D03, D07 unapproved; shared login throttling decided (C-06), store/client pending D02 |
| M3 | Authenticated ingestion, PG idempotency, Redis state, scenario catalog + submission script | `backend` | not started | M2; D08 |
| M4 | SMS detection and evaluation | `backend` | not started | M3; D04 data/licensing |
| M5 | Voice transcription, intent, synthesis indication | `backend` | not started | M3; D04 data/licensing/hardware |
| M6 | Correlation and continuous fusion | `backend` | not started | M4, M5; D05, D06; paired labeled data |
| M7 | Analyst dashboard (M7a backend incident/review API, M7b frontend UI) | `backend`, `frontend` | not started | M3 (M6 for pairs); D09; browser login depends on shared login throttling (C-06) |
| M8 | End-to-end integration and workflows (includes simulator UI) | `dev` | not started | M6, M7; health-path compatibility plan (C-07) |
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

## Conflict decisions (owner, 31 October 2026)

C-01 to C-05 approved; C-06 decided (M2 implements shared login throttling; login fails closed if the shared throttle is unavailable; no in-process fallback for authentication; the API.md/ARCHITECTURE.md fallback wording still conflicts and needs a contract update); C-07 deferred (M1 health routes and tests preserved); C-10 resolved by the CONTRIBUTING.md update. Details are in MASTER_DEVELOPMENT_PLAN.md.

## Decisions

The owner's conflict and Git decisions do not approve any item below marked pending.

| ID | Topic | Status |
| --- | --- | --- |
| D01 | Scope | Approved for the backend foundation only; remaining use needs a recorded decision |
| D02 | Stack and **package choices** | Approved for the backend foundation only. **Pending explicit approval:** SQLAlchemy, Alembic, psycopg, Argon2 library, Redis client (if used in M2), PostgreSQL/Redis container images, CI tooling and action versions, frontend packages |
| D03 | Authentication | **Pending explicit approval**; proposal in PRD/ARCHITECTURE; see MASTER_DEVELOPMENT_PLAN |
| D04 | Dataset and model provenance | **Pending explicit approval**; no datasets or artifacts approved |
| D05–D06, D08–D09 | Correlation window, tiers, limits, UI | Proposed, unapproved; each gates the milestone listed in the master plan |
| D07 | Retention | **Pending explicit approval**; gates the M2 schema |
| D10 | Hosting | **Pending explicit approval**; local Compose is the working assumption only |

## Technical debt

| ID | Item | Impact | Target |
| --- | --- | --- | --- |
| TD-01 | `backend/uv.lock` absent; the environment was built with pip after `uv sync` timed out against PyPI | Transitive dependencies are unpinned; a clean clone is not reproducibly installable | M1.1; diagnose the network/index issue first |
| TD-02 | Installed Ruff 0.17.3 vs `pyproject.toml` pin 0.17.2; the pinned version has never been verified | Lint results may differ from CI | M1.1; decide pin or install, record the outcome |
| TD-03 | No CI workflow (`.github/workflows/.gitkeep` only) | Gates depend on manual local evidence | M1.1 (approved in principle, before M2) |
| TD-04 | `starlette.testclient`/`httpx` deprecation warning; the warning suggests `httpx2` | May become an error in a later Starlette | Evaluate when dependencies are next touched |
| TD-05 | `docs/AGENTS.md` duplicates root `AGENTS.md` with relative paths | Rules can drift; root `AGENTS.md` is authoritative | Decide whether to keep or reduce to a pointer |
| TD-06 | Stale Git/status statements: README and ARCHITECTURE.md line 7 corrected in M0; CONTRIBUTING.md branch rules added in M0. PRD document map now lists the six new documents | Reader confusion | Separate approved docs change |
| TD-07 | Development/test PostgreSQL (approved under C-05) and, if used, Redis are not yet defined | Blocks M2 integration tests | M2 (D02 tooling approval) |
| TD-08 | Public `/health` vs API.md's authenticated `/health` (C-07) | Contract mismatch once auth exists; deferred, M1 routes and tests preserved | Separate compatibility plan, owner approval |
| TD-09 | GitHub default branch (`dev` intended) and protection for `main`/`dev` not configured | Nothing prevents force-push or direct pushes | After M1.1, on explicit owner instruction |
| TD-11 | API.md and ARCHITECTURE.md permit in-process throttling fallbacks, contradicting the C-06 decision for login | Specifications disagree | Approved contract update before M2 |
| TD-10 | `.env.example` lists only `APP_ENV` and `LOG_LEVEL`; API.md lists the full variable set | Expected until each variable's feature lands | Per milestone |

## Update protocol

1. Change a milestone to `complete (verified)` only with the commands and results of its acceptance criteria attached to the task report.
2. Record scope reductions or reordering with the owner's decision and date; do not edit the acceptance criteria to fit what was built.
3. Keep conflicts in MASTER_DEVELOPMENT_PLAN.md; reference their IDs here.
