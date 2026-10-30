# KAVACH Milestone Tracker

Status as of 31 October 2026, from the read-only audit of that date, the M0 documentation work and the owner's decisions of the same day. All verification entries are **point-in-time historical results**; re-run the commands before relying on them. Update this file when a milestone's exit criteria are verified, not when work merely starts. Details and acceptance criteria are in [MASTER_DEVELOPMENT_PLAN.md](MASTER_DEVELOPMENT_PLAN.md). Dated execution results go in task reports.

Status values: `not started`, `in progress`, `blocked`, `complete (verified)`, `complete (unverified)`.

## Milestones

| ID | Milestone | Branch | Status | Blocked by / notes |
| --- | --- | --- | --- | --- |
| M0 | Repository, architecture alignment, workflow, reproducibility planning | `dev` | complete (documentation committed to `dev`; see the M0 task report for the hash) | C-07 deferred; PRD/API/ARCHITECTURE follow-ups noted under C-06 |
| M1 | FastAPI foundation | `main` (history) | complete (verified historically: 88 passed, Ruff clean on 31 Oct 2026; HTTP startup last verified 28 Oct 2026) | Debt TD-01, TD-02, TD-03 carried forward; M1 routes preserved (C-07 deferred) |
| M1.1 | Reproducible environment and minimal pytest + Ruff CI | `backend` → `dev` (owner instruction of 31 Oct 2026; the plan's `feature/m1-1-ci` was not used) | in progress: implemented and verified locally on 31 Oct 2026; uncommitted; **no GitHub Actions run yet** | Owner review, commit and push (user-run); PR into `dev` triggers the first CI run; exit requires that run to be green |
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
| TD-01 | ~~`backend/uv.lock` absent~~ Addressed in M1.1 (uncommitted): lock generated with uv 0.11.16, 27 packages, `uv lock --check` passes, fresh isolated install verified. The earlier timeouts did not reproduce: the PyPI index answered in 0.13 s and resolution took 0.4 s, so the cause is attributed to the earlier execution environment's network sandbox, not the index or manifest (not proven). | — | Close when committed and CI is green |
| TD-02 | Ruff pin: **kept at the documented 0.17.2** (manifest and lockfile); 0.17.2 verified clean in the fresh environment. The existing `backend/.venv` still has 0.17.3 until the user syncs it (see README Setup). | Local pip venv differs from lock until synced | Close when committed and CI is green |
| TD-03 | CI workflow written (`.github/workflows/backend-ci.yml`) but **not yet run on GitHub** | Workflow correctness on GitHub unproven | Close after the first green run |
| TD-04 | `starlette.testclient`/`httpx` deprecation warning; the warning suggests `httpx2` (still present in the M1.1 runs: 88 passed, 1 warning) | May become an error in a later Starlette | Evaluate when dependencies are next touched |
| TD-12 | Lockfile resolved `opentelemetry-api` 1.45.2 (transitive via FastAPI 0.162.0; released 29 Oct 2026), while the pip venv has 1.45.1. Tests pass with both | Minor drift between local venv and lock | Disappears when the user syncs `backend/.venv` |
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
