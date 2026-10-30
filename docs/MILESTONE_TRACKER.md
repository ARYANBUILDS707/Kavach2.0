# KAVACH Milestone Tracker

Status as of 31 October 2026, from the read-only audit of that date, the M0 documentation work and the owner's decisions of the same day. All verification entries are **point-in-time historical results**; re-run the commands before relying on them. Update this file when a milestone's exit criteria are verified, not when work merely starts. Details and acceptance criteria are in [MASTER_DEVELOPMENT_PLAN.md](MASTER_DEVELOPMENT_PLAN.md). Dated execution results go in task reports.

Status values: `not started`, `in progress`, `blocked`, `complete (verified)`, `complete (unverified)`.

## Milestones

| ID | Milestone | Branch | Status | Blocked by / notes |
| --- | --- | --- | --- | --- |
| M0 | Repository, architecture alignment, workflow, reproducibility planning | `dev` | complete (documentation committed to `dev`; see the M0 task report for the hash) | C-07 deferred; PRD/API/ARCHITECTURE follow-ups noted under C-06 |
| M1 | FastAPI foundation | `main` (history) | complete (verified historically: 88 passed, Ruff clean on 31 Oct 2026; HTTP startup last verified 28 Oct 2026) | Debt TD-01, TD-02, TD-03 carried forward; M1 routes preserved (C-07 deferred) |
| M1.1 | Reproducible environment and minimal pytest + Ruff CI | `backend` (stays there until full backend acceptance) | complete (verified): GitHub Actions passed on `backend` commit `c36e903` (owner-reported, 31 Oct 2026) | — |
| M2 | PostgreSQL, migrations, identity, scoped auth, audit (owner-defined steps below) | `backend` | in progress | D02 packages, D03, D07, C-06 approved 31 Oct 2026 |
| M2.1 | Database and development infrastructure: dependencies, dev/test Compose, engine/session and Redis client lifecycle, config validation, real-service tests, CI integration job | `backend` | complete (verified): GitHub Actions run 41119537962 on `0cebb3b`, both jobs passed (checked via the public GitHub API, 31 Oct 2026) | — |
| M2.2 | Full DATABASE.md schema, Alembic migration `0001_initial_schema`, integrity triggers, role grants | `backend` | in progress: implemented and verified locally on 31 Oct 2026; uncommitted; **not yet run on GitHub** | Owner review; user commit/push; exit requires both CI jobs (including the new migration gate) green on the pushed `backend` commit |
| M2.3 / M2.4 | Login, sessions, CSRF, shared throttling; ingestion keys, provisioning, audit | `backend` | not started | M2.2; argon2-cffi 25.1.0 approved but not yet added; `RATE_LIMIT_HMAC_KEY` becomes required |
| M3 | Authenticated ingestion, PG idempotency, Redis state, scenario catalog + submission script | `backend` | not started | M2; D08 |
| M4 | SMS detection and evaluation | `backend` | not started | M3; D04 data/licensing |
| M5 | Voice transcription, intent, synthesis indication | `backend` | not started | M3; D04 data/licensing/hardware |
| M6 | Correlation and continuous fusion | `backend` | not started | M4, M5; D05, D06; paired labeled data |
| M7 | Analyst dashboard (M7a backend incident/review API, M7b frontend UI); M7a completion triggers the single `backend` → `dev` integration PR | `backend`, `frontend` | not started | M3 (M6 for pairs); D09; browser login depends on shared login throttling (C-06) |
| M8 | End-to-end integration and workflows (includes simulator UI) | `dev` | not started | Backend integration PR merged; M7b integrated (decision open); health-path compatibility plan (C-07) |
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
| D04 | Dataset and model provenance | **Pending explicit approval**; no datasets or artifacts approved |
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
| TD-13 | Retention runs as column-limited DELETE grants; DATABASE.md's narrowly scoped expiry procedures (and the cleanup job) are not written yet | Cleanup must be implemented before retention is claimed | With the retention job (M2.4 or M9) |
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
