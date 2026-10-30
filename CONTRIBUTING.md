# Contributing to KAVACH

Read [AGENTS.md](AGENTS.md), the [product requirements](docs/PRD.md), and the relevant specifications before changing code. Work only on an approved milestone and preserve existing documentation and user changes.

## Current scope

The foundation contains a Python 3.12 FastAPI application factory, public liveness routes, validated event DTOs, configuration, and backend tests. Authentication, durable ingestion, ML, Redis correlation and frontend implementation remain future work. Do not represent schema validation as event processing or liveness as model readiness.

The installable package is `backend/src/kavach/`. Keep routes in `api/routes/`, DTOs in `api/schemas/`, and shared configuration/errors in `core/`. Add services and repositories only with their corresponding implementation tasks. Put backend tests in `backend/tests/`; root `tests/` is reserved for cross-application tests.

## Environment and checks

Follow [README.md](README.md) for Python/uv setup and recovery commands. Direct dependencies and build tooling are pinned in `backend/pyproject.toml`; Python is pinned in `backend/.python-version`. `backend/uv.lock` (generated with uv 0.11.16) pins the full dependency graph; commit it together with any `pyproject.toml` dependency change, regenerated with `uv lock --project backend`. Never handcraft a lockfile or claim a dependency resolution succeeded when it did not. Ruff is pinned at 0.17.2 in both the manifest and the lockfile.

Run from the project root (these are the commands CI runs; note that they sync `backend/.venv` to the lockfile, see the README Setup section):

```sh
uv lock --check --project backend
uv sync --project backend --locked
uv run --project backend --locked pytest backend/tests
uv run --project backend --locked ruff check backend
uv run --project backend --locked ruff format --check backend
```

CI (`.github/workflows/backend-ci.yml`) runs the same commands on pushes to `backend`, `dev` and `main` and on pull requests into `dev` and `main`. Include local results in the milestone report, and do not describe CI as passing without a green GitHub Actions run.

Use `uv run --project backend --locked ruff format backend` to format intentional code changes, then inspect the diff. Add behavioral tests for new validation, permissions and failures. Use synthetic data only; do not commit communications, secrets or model binaries. HTTP tests of ingestion DTOs use routes registered only in the test harness, never fake production ingestion endpoints.

## Branches and pull requests

Full procedure: [docs/GIT_WORKFLOW.md](docs/GIT_WORKFLOW.md). Milestones: [docs/MASTER_DEVELOPMENT_PLAN.md](docs/MASTER_DEVELOPMENT_PLAN.md). Done criteria: [docs/DEFINITION_OF_DONE.md](docs/DEFINITION_OF_DONE.md).

- `main` is the stable release branch. `dev` is the integration branch (the intended GitHub default; that setting has not been changed). `backend` carries all backend milestones M1.1 through M7a; `frontend` carries frontend work (M7b) independently. `feature/*` branches are not used for backend milestones.
- Backend milestones are committed directly to `backend`; there is **no** pull request into `dev` per milestone. Each milestone needs its report, its acceptance evidence and a green CI run on the pushed `backend` commit.
- Backend work reaches `dev` through a **single** `backend` → `dev` integration pull request, opened only after the complete backend (M1.1–M7a) passes acceptance testing. When the frontend integrates into `dev` is still an open decision. Releases go from `dev` to `main` through a release PR ([docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)). Do not push directly to `main` or `dev`.
- Milestone reports and the integration/release PR descriptions state the milestone(s), changed files, exact verification commands and their actual results (or "not run" with the reason), contract or schema changes with the updated documents, and open risks. Schema changes include a migration.
- If `dev` moves, merge it into `backend` (or `frontend`) and re-run the checks; use merge commits, never rebase or force-push shared branches.
- **The user performs all Git operations** (staging, commits, pushes, merges, branch switches, pull requests) and deployments; agents use read-only Git commands only.
- Required review and status checks apply once CI exists. Until then the pasted local `pytest` and `ruff` results are the gate. Branch protection is proposed for `main` and `dev` after CI is configured and has not been applied.

## Change discipline

- Keep changes small and tied to a requirement. Reuse existing patterns and avoid unrelated dependencies or rewrites.
- Keep all source-of-truth documents consistent with approved contract changes.
- Do not log raw inputs or serialize Pydantic error input/context into API responses.
- Never weaken a test, validator or permission boundary solely to obtain a passing check.
- Report exact commands and actual outcomes. A syntax check is not a passing test suite.
- Inspect staged changes and secret exclusions before any authorized commit. Do not commit or push without task authorization.

## Dependency references

Version choices were checked against the official package records for [FastAPI](https://pypi.org/project/fastapi/), [Pydantic](https://pypi.org/project/pydantic/), [pydantic-settings](https://pypi.org/project/pydantic-settings/), [Uvicorn](https://pypi.org/project/uvicorn/0.52.0/), [HTTPX](https://pypi.org/project/httpx/), [pytest](https://pypi.org/project/pytest/9.1.1/), and [Ruff](https://pypi.org/project/ruff/0.16.7/). Package existence does not establish compatibility; installation and the test suite must verify that. See [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/) for the lockfile workflow.
