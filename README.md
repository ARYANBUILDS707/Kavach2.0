# KAVACH

KAVACH is a proposed fraud-analysis platform that connects authorized SMS and voice-call signals to present explainable risk evidence for human review.

Backend foundation source and tests are present and committed (`754a22a` on `main`, pushed to `origin`; `dev`, `backend` and `frontend` branches also exist). Factory startup and both health routes over HTTP were last verified on 28 October 2026; pytest and Ruff were last re-run on 31 October 2026. See "Verification status" below, which separates historical results from current status. The MVP targets a controlled demonstration; live telecom integration and reported historical benchmarks are not verified capabilities.

## Start here

Read [Product requirements](docs/PRD.md) for scope, assumptions and decisions requiring approval, then follow the [Implementation plan](docs/IMPLEMENTATION_PLAN.md).

Before implementing changes, read the root [Coding agent rules](AGENTS.md) and the relevant specifications. Product specifications and workflow documentation are in `docs/`; document-to-document links there are relative to that folder. Backend modules now live in the installable `backend/src/kavach/` package. See [CONTRIBUTING.md](CONTRIBUTING.md) for development rules.

## Specifications

| Document | Purpose |
| --- | --- |
| [PRD](docs/PRD.md) | Users, journeys, requirements, MVP scope and pending decisions |
| [Design](docs/DESIGN.md) | Visual system, components, accessibility and page layouts |
| [Architecture](docs/ARCHITECTURE.md) | Proposed stack, boundaries, data flow and deployment approach |
| [Database](docs/DATABASE.md) | Schema, constraints, retention and recovery |
| [API](docs/API.md) | Endpoints, authentication, validation and integration contracts |
| [Agent rules](docs/AGENTS.md) | Coding, security, testing and change discipline |

## Development workflows

1. [Implementation planning](docs/IMPLEMENTATION_PLAN.md)
2. [Project setup](docs/PROJECT_SETUP.md)
3. [Feature development](docs/FEATURE_DEVELOPMENT.md)
4. [Backend and database connection](docs/BACKEND_DATABASE_CONNECTION.md)
5. [Authentication and authorization](docs/AUTHENTICATION_AUTHORIZATION.md)
6. [MCP connection](docs/MCP_CONNECTION.md)
7. [External service integration](docs/EXTERNAL_SERVICE_INTEGRATION.md)
8. [Testing and QA](docs/TESTING_QA.md)
9. [Debugging](docs/DEBUGGING.md)
10. [Security audit](docs/SECURITY_AUDIT.md)
11. [Code review](docs/CODE_REVIEW.md)
12. [Deployment](docs/DEPLOYMENT.md)
13. [Monitoring and maintenance](docs/MONITORING_MAINTENANCE.md)
14. [Final production audit](docs/FINAL_PRODUCTION_AUDIT.md)

These workflows describe future execution; they do not report completed implementation, testing or deployment.

## Project connection record

The original [connection test](docs/CONNECTION_TEST.md) is preserved in the documentation folder.

## Backend foundation

Python 3.12.13 is selected in `backend/.python-version`. The package uses FastAPI, Pydantic v2, environment-based settings, pytest and Ruff. Direct dependencies are pinned in `backend/pyproject.toml`; a resolved transitive lockfile remains pending the first successful dependency installation.

Implemented source:

- `GET /health` and `GET /api/v1/health`: public process liveness only, with `analysis_ready: false`, a generated request ID and no internal dependency details.
- SMS and call Pydantic schemas with bounded identifiers/content, explicit timezone validation, UTC normalization, a seven-day maximum event age and 60-second future skew.
- Optional `kind` defaults to `sms` or `call` for the selected schema; conflicting kinds and unknown fields are rejected. Voice events use the canonical type `call`.
- Optional SMS `sender_id` and call `audio_reference`; metadata-only calls are permitted. Reference syntax excludes paths and URLs. Manifest membership, source authorization and pseudonymization are later service responsibilities.
- Safe HTTP error envelopes without raw validation inputs, and explicit environment settings.

No production POST ingestion routes exist yet. Schema API tests mount validation-only routes in a separate test harness. No model predictions, database persistence, authentication, correlation or frontend are implemented.

### Setup

Prerequisites: `uv` (0.11.16 is the version used to generate the lockfile and pinned in CI) and Python 3.12.13 (uv can install Python when network access is available). Run from the project root:

```sh
uv python install 3.12.13
uv sync --project backend --locked --python 3.12.13
```

`backend/uv.lock` pins the complete dependency graph (33 entries including the project itself; M2.1 added SQLAlchemy 2.0.55, psycopg 3.3.6 with its binary wheel, and redis 8.1.0). `--locked` fails instead of silently re-resolving if `backend/pyproject.toml` and the lockfile disagree; check this with `uv lock --check --project backend`. After an intentional dependency change, run `uv lock --project backend` and commit the updated lockfile with the manifest. Do not use `--frozen` to conceal an out-of-date lockfile.

**Existing pip-built environment:** a `backend/.venv` created with the earlier pip workaround is not identical to the lockfile (it has Ruff 0.17.3, `opentelemetry-api` 1.45.1 and `pip`). Running `uv sync --project backend --locked`, or any `uv run --project backend --locked …` command, makes that environment match the lockfile: Ruff becomes 0.17.2, `opentelemetry-api` 1.45.2, and packages not in the lock (such as `pip`) are removed. Do this deliberately; the `backend/.venv/bin/python -m …` commands below keep using the environment as it is. For M2.1 the four new packages (`sqlalchemy==2.0.55`, `psycopg==3.3.6`, `psycopg-binary==3.3.6`, `redis==8.1.0`) were added to that environment additively with `uv pip install --python backend/.venv/bin/python --no-deps …`; nothing else in it changed.

Environment settings default to development/INFO. Optionally copy `.env.example` to root `.env` without overwriting an existing file. `APP_ENV` accepts `development`, `test`, or `pilot`; `LOG_LEVEL` accepts `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. No credentials are needed for this phase. Invalid settings fail startup. Setting `APP_ENV=pilot` disables interactive API docs; it does not make this foundation pilot-ready.

Run from the project root using the installed backend virtual environment and process environment (verified command):

```sh
backend/.venv/bin/python -m uvicorn kavach.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

`backend/src/kavach/main.py` exposes the `create_app` factory, not a module-level `app`. Use `kavach.main:create_app --factory`; `kavach.main:app` fails with `Attribute "app" not found`. The existing factory structure is preserved. After generating a lockfile with the setup commands, the equivalent uv invocation is `uv run --project backend --locked uvicorn kavach.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log`.

To load an optional root `.env`, add `--env-file .env` to the Uvicorn command. Dotenv loading is explicit, so tests do not accidentally load local secrets. Uvicorn server logging can be selected with `--log-level`; `LOG_LEVEL` controls the application's logger. Keep access logs disabled to avoid recording sensitive URL/query values.

Check both routes while the server runs:

```sh
curl --noproxy '*' --fail-with-body --max-time 5 -sS -i http://127.0.0.1:8000/health
curl --noproxy '*' --fail-with-body --max-time 5 -sS -i http://127.0.0.1:8000/api/v1/health
```

Development OpenAPI is available at `/docs`. Neither health response certifies fraud-analysis readiness or a telecom connection.

### Verification commands

Run from the project root with the installed backend virtual environment:

```sh
backend/.venv/bin/python -m pytest backend/tests
backend/.venv/bin/python -m ruff check backend
backend/.venv/bin/python -m ruff format --check backend
```

Locked equivalents (the commands CI runs; they sync `backend/.venv` to the lockfile first, see Setup):

```sh
uv lock --check --project backend
uv sync --project backend --locked
uv run --project backend --locked pytest backend/tests
uv run --project backend --locked ruff check backend
uv run --project backend --locked ruff format --check backend
```

### Development services (PostgreSQL and Redis)

`deployment/compose.dev.yml` runs PostgreSQL 17.11 and Redis 7.4.12 for **local development and tests only**; it is not a deployment artifact. Images are pinned by digest, ports bind to `127.0.0.1` only, every password comes from the environment (there are no defaults), and Redis runs without persistence. On first start, `deployment/postgres/initdb/10-kavach-roles.sql` creates the least-privilege roles `kavach_migrator` (owns the databases and schema), `kavach_app` (runtime: connect and schema usage only) and `kavach_retention`, plus the databases `kavach_dev` and `kavach_test`. Table grants are applied by the schema migration (M2.2).

```sh
cp deployment/compose.dev.env.example deployment/.env.dev   # ignored by Git
# edit deployment/.env.dev: replace every password with `openssl rand -hex 24` output
docker compose --env-file deployment/.env.dev -f deployment/compose.dev.yml up --detach --wait
docker compose --env-file deployment/.env.dev -f deployment/compose.dev.yml down            # keep dev data
docker compose --env-file deployment/.env.dev -f deployment/compose.dev.yml down --volumes  # discard it
```

The role bootstrap only runs on an empty data volume; after changing role passwords, recreate the volume with `down --volumes`.

#### Schema migrations

The schema (`docs/DATABASE.md`) is created by Alembic revision `0001_initial_schema`, run as the migration owner. The URL is read from `MIGRATION_DATABASE_URL`, never from `backend/alembic.ini`:

```sh
export MIGRATION_DATABASE_URL="postgresql+psycopg://kavach_migrator:<migrator-password>@127.0.0.1:55432/kavach_dev"
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head   # safe to repeat
backend/.venv/bin/alembic -c backend/alembic.ini check          # models and database must agree
```

Downgrading drops every table, so it is refused unless the database name ends in `_test` and is named explicitly (`-x allow-destructive-downgrade=kavach_test`). Never downgrade `kavach_dev` or any deployed database; use a forward-repair migration instead.

#### Integration tests

Integration tests are excluded from the default `pytest` run and selected with `-m integration`. They read four variables and **fail (not skip)** if any is missing. They rebuild the schema in the disposable `kavach_test` database from empty at the start of each session, so never point them at `kavach_dev`:

```sh
export TEST_DATABASE_URL="postgresql+psycopg://kavach_app:<app-password>@127.0.0.1:55432/kavach_test"
export TEST_MIGRATION_DATABASE_URL="postgresql+psycopg://kavach_migrator:<migrator-password>@127.0.0.1:55432/kavach_test"
export TEST_RETENTION_DATABASE_URL="postgresql+psycopg://kavach_retention:<retention-password>@127.0.0.1:55432/kavach_test"
export TEST_REDIS_URL="redis://:<redis-password>@127.0.0.1:56379/15"
backend/.venv/bin/python -m pytest backend/tests -m integration
```

### Continuous integration

`.github/workflows/backend-ci.yml` runs on pushes to `backend`, `dev` or `main` and on pull requests targeting `dev` or `main`. Job "Backend tests and lint" is described here; job "Backend integration (PostgreSQL and Redis)" (M2.1) generates fresh masked passwords for each run, starts `deployment/compose.dev.yml` on the runner, applies the migrations twice and runs `alembic check` (M2.2), runs `pytest -m integration` against it, prints service logs on failure and always removes the containers and volumes. Every backend milestone pushed to `backend` is checked; `frontend` and `feature/*` pushes are not. On `ubuntu-24.04` with Python 3.12.13 and uv 0.11.16, it verifies the lockfile is current, installs from it with `--locked`, then runs pytest, Ruff lint and Ruff format check. The workflow has read-only `contents` permission, does not persist checkout credentials, uses no secrets, pins actions to commit SHAs (`actions/checkout` v7.0.1, `astral-sh/setup-uv` v10.3.0), cancels superseded runs on the same ref, and times out after 15 minutes. Any failed step fails the job; the three checks each still run after a successful install so all failures are reported together. The "Backend tests and lint" job passed on GitHub Actions for `backend` commit `c36e903` (reported by the owner). **The M2.1 integration job has not run on GitHub yet**; it is verified only by replaying its commands locally.

### Verification status

**Current status (M2.2 local verification, 31 October 2026; point-in-time, re-run before relying on it):**

- `uv lock` added exactly `alembic` 1.20.0, `mako` 1.4.3 and `markupsafe` 3.0.4 (36 entries); no existing version changed; `uv lock --check` passed.
- On a fresh `kavach_test` database: `alembic upgrade head` succeeded, a second `upgrade head` was a no-op, `alembic current` reported `0001_initial_schema (head)` and `alembic check` reported "No new upgrade operations detected". A downgrade was refused without permission and for `kavach_dev`.
- Default suite: 103 passed, 141 deselected, 1 warning. Integration suite: 141 passed (70 constraint, 48 privilege, 12 migration, 11 service tests), in both the existing `backend/.venv` (Ruff 0.17.3) and a fresh locked environment (Ruff 0.17.2). Ruff check passed; 31 files already formatted.
- The CI integration job's commands were replayed locally with fresh passwords: migrations, `alembic check` and 141 integration tests passed; containers and volumes were removed.
- A mutation probe (dropping the incident triggers inside a rolled-back transaction) turned a rejected invalid incident into an accepted one, so the trigger tests depend on the triggers.
- GitHub Actions has **not** run M2.2 yet. M2.1 passed on GitHub (run 41119537962, commit `0cebb3b`, both jobs).

**Historical record — M2.1 local verification, 31 October 2026:**

- `uv lock --project backend` added exactly six entries (`sqlalchemy` 2.0.55, `psycopg` 3.3.6, `psycopg-binary` 3.3.6, `redis` 8.1.0, and the platform-conditional `greenlet` 3.5.6 and Windows-only `tzdata` 2026.6); no existing version changed. `uv lock --check` passed.
- Default suite (service-free): 103 passed, 11 deselected, 1 warning, in both the existing `backend/.venv` (Ruff 0.17.3) and a fresh environment built from the lockfile (Ruff 0.17.2). Ruff check passed and 24 files were already formatted in both.
- Integration suite against `deployment/compose.dev.yml` on Docker 29.8.0 (linux/aarch64): 11 passed in both environments. The CI integration job's commands were replayed locally with fresh passwords (11 passed; containers and volumes removed afterwards).
- Without the `TEST_*` variables, `pytest -m integration` fails (4 failed, 7 errors) rather than skipping.
- The warning is the existing Starlette/httpx deprecation (TD-04). Uvicorn startup over HTTP was not repeated.

**Historical record — M1.1 local verification, 31 October 2026:**

- `uv lock --project backend` (uv 0.11.16, Python 3.12.13) resolved 27 packages from `https://pypi.org/simple` in under a second; `uv lock --check --project backend` passed.
- Existing `backend/.venv` (Ruff 0.17.3, left unchanged): pytest 88 passed with 1 warning; Ruff check passed; Ruff format check reported 17 files already formatted.
- Fresh isolated environment created from the lockfile outside the repository (`UV_PROJECT_ENVIRONMENT` set to a temporary directory; `backend/.venv` untouched), Ruff 0.17.2: the five locked commands above all passed, with the same 88 passed, 1 warning and 17 files formatted.
- Remaining warning: `StarletteDeprecationWarning` — using `httpx` with `starlette.testclient` is deprecated in favour of `httpx2` (tracked as TD-04; not changed).
- Uvicorn startup and HTTP requests were not repeated. The GitHub Actions workflow has not run yet.

**Historical record — results reported on 28 October 2026 (not re-run as a whole since):**

- The startup command above launched Uvicorn 0.54.0 with Python 3.12.13. Both curl commands above returned HTTP 200 with `data: {"status":"ok","scope":"liveness","analysis_ready":false}`, distinct request IDs matching the response headers, and `Cache-Control: no-store`.
- pytest 9.1.1: **88 passed**, one dependency warning about Starlette TestClient's deprecated HTTPX integration. The new `backend/tests/test_entrypoint.py` loads `kavach.main:create_app` through Uvicorn with factory mode and checks both health routes.
- Ruff lint: **All checks passed**. Formatting: **17 files already formatted**.
- Checks used the existing installed environment. Installed Ruff is **0.17.3**, while `pyproject.toml` pins **0.17.2**; the pinned Ruff version was not verified. No dependencies or pins were changed. `backend/uv.lock` is still absent, so locked dependency reproducibility remains unverified.
- Local server binding and curl required execution outside the sandbox; sandbox attempts were blocked. No application behavior was changed to accommodate that restriction.

The earlier dependency-installation failures no longer describe the installed environment, although the environment was built with pip rather than a reproducible `uv sync`. The foundation is committed as `754a22a` on `main` and pushed to `origin`; the `dev`, `backend` and `frontend` branches were created from it on 31 October 2026. M2 started with M2.1 (database and Redis infrastructure); see "Next milestone".

## Repository layout

```text
Kavach2.0/
├── AGENTS.md
├── CONTRIBUTING.md
├── README.md
├── .env.example
├── .gitignore
├── .github/workflows/backend-ci.yml
├── deployment/                   # Development/test-only services (not a deployment)
│   ├── compose.dev.yml
│   ├── compose.dev.env.example
│   └── postgres/initdb/10-kavach-roles.sql
├── backend/
│   ├── .python-version
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── alembic.ini
│   ├── src/kavach/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── routes/health.py
│   │   │   └── schemas/{events,health}.py
│   │   ├── core/{config,errors,redis_client}.py
│   │   └── db/{engine,models}.py, db/migrations/{env.py,script.py.mako,versions/0001_initial_schema.py}
│   └── tests/
│       ├── {conftest,test_config,test_entrypoint,test_errors,test_events,test_health,test_infrastructure}.py
│       └── integration/{conftest,schema_rows,test_services,test_migrations,test_constraints,test_privileges}.py
├── docs/                         # Specifications and workflow documents
├── frontend/.gitkeep             # Reserved; no frontend implementation
├── tests/.gitkeep                # Reserved for cross-application tests
├── scripts/.gitkeep
└── data/.gitkeep                 # Data contents excluded from Git
```

Package `__init__.py` files are omitted from the condensed tree below the top package. Local ignored environments/caches are not shown. `backend/uv.lock` sits beside `backend/pyproject.toml`.

## Next milestone

M1.1 and M2.1 are complete (GitHub Actions green on `c36e903` and `0cebb3b`). M2.2 (schema, migrations, grants) is implemented and verified locally, uncommitted, and has not yet run on GitHub. M2.3/M2.4 (login, sessions, CSRF, throttling, ingestion keys, provisioning, audit) follow (see `docs/MILESTONE_TRACKER.md`). Backend milestones M1.1–M7a stay on `backend` and reach `dev` through a single integration pull request after full backend acceptance (`docs/GIT_WORKFLOW.md`). D02 packages, D03, D07 and C-06 were approved on 31 October 2026. Ingestion, ML, Redis correlation and frontend are not started. Branch workflow and milestone status: `docs/GIT_WORKFLOW.md`, `docs/MILESTONE_TRACKER.md`.
