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
backend/.venv/bin/python -m uvicorn kavach.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

**Always pass `--no-proxy-headers`** (M3.4 finding). By default Uvicorn trusts `X-Forwarded-For` from `127.0.0.1`/`::1` and rewrites the client address before the application sees it. Any local process could then rotate its apparent IP past the per-IP login and invalid-key ceilings. Behind a reverse proxy, replace the flag with `--proxy-headers --forwarded-allow-ips <the proxy's own address>`. The proxy must overwrite or append the client address (never pass a client-supplied header through unchanged). Trusted-proxy configuration is part of deployment (TD-14).

`backend/src/kavach/main.py` exposes the `create_app` factory, not a module-level `app`. Use `kavach.main:create_app --factory`; `kavach.main:app` fails with `Attribute "app" not found`. The existing factory structure is preserved. After generating a lockfile with the setup commands, the equivalent uv invocation is `uv run --project backend --locked uvicorn kavach.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers`.

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

#### Authentication (M2.3)

`POST /api/v1/auth/login`, `GET /api/v1/auth/session` and `POST /api/v1/auth/logout` need the authentication settings described in `.env.example` (all-or-nothing; without them the routes return 503). Accounts are provisioned by an operator, never by signup.

#### Operator commands (M2.4)

`python -m kavach.cli` manages accounts, ingestion API keys and retention. It needs the authentication settings (with `DATABASE_URL` for the runtime role) and, for retention, `RETENTION_DATABASE_URL`.

```sh
C="backend/.venv/bin/python -m kavach.cli"
$C user create --username root --display-name "First Admin" --bootstrap   # only while no active admin exists
$C user create --username alice --display-name "Alice" --role analyst --actor root
$C user set-role --username alice --role admin --actor root
$C user reset-password --username alice --actor root      # revokes alice's sessions
$C user deactivate --username alice --actor root          # revokes alice's sessions
$C key create --name "simulator feed" --source simulator --actor root   # prints the key once
$C key rotate --key-id <id> --actor root                  # new key, old key revoked atomically
$C key revoke --key-id <id> --actor root
$C key list --actor root                                  # never shows key material
$C retention run --database kavach_test --dry-run --actor root
$C candidates rebuild --actor root                       # restore the Redis candidate index
```

- **Actor.** Every command except `--bootstrap` authenticates `--actor` (password prompt) as an *active admin*, re-checked in the same transaction as the change. Operators cannot deactivate themselves, and the last active admin cannot be deactivated or demoted. The password check gives attribution and policy; the real boundary is custody of the database credentials the CLI runs with.
- **Secrets** are never arguments. They are prompted for (new passwords twice), or with `--stdin` read one per line: the actor's password first, then any new password.
- **Audit.** Bootstrap, provisioning, role change, password reset, deactivation, key create/rotate/revoke are audited in the same transaction as the change (an audit failure rolls the change back). A destructive retention run writes `retention.start` before deleting anything and `retention.complete` afterwards (same run ID); the retention role itself cannot write audit rows.
- **API keys** are `kvk_` + 256 random bits, stored only as SHA-256 digests, bound to one source, and always expire (default 90 days, maximum 365). For an overlap window, `key create` a replacement and `key revoke` the old key later instead of `key rotate`.
- **Retention** deletes rows whose `expires_at` (or a session's `revoked_at`) is at or before the cutoff (`--as-of`, default now): expired incidents with their links, assessments and reviews, then events no longer linked to any incident, then audit records, then sessions. Users and keys are never deleted. `--database` must name the connected database; destructive runs are refused unless it is a `*_test` database (dry runs are allowed anywhere). A dry run executes the batches in one transaction and rolls back, so its counts are exact. Scheduling is a later milestone.

#### Event ingestion (M3.1)

With the ingestion settings in `.env.example` (they require the authentication settings), an ingestion key for source `simulator` can submit synthetic events:

```sh
curl -sS -X POST http://127.0.0.1:8000/api/v1/events/sms \
  -H "Authorization: Bearer $KAVACH_KEY" -H "Content-Type: application/json" \
  -d '{"event_id":"demo-1","subscriber_token":"sub_demo_a","timestamp":"<now, RFC 3339>","source":"simulator","text":"Synthetic test message"}'
```

The first submission returns 201, an identical retry 200 (`replayed: true`), and a changed payload with the same `event_id` 409. `GET /api/v1/events/<receipt event_id>` recovers the receipt for the same source. No models are deployed, so every receipt reports `analysis_status: unavailable` with a warning per unavailable stage. Only synthetic data may be submitted.

#### Controlled simulator (M3.3)

`python -m kavach.simulator` runs the fixed synthetic scenario catalog (`backend/src/kavach/simulator/scenarios_v1.json`, version 1) against a **local** backend through the ordinary event endpoints. It is a test and demonstration tool for synthetic data only. Admins can read the same catalog from `GET /api/v1/simulator/scenarios` (browser session).

| ID | Scenario | Expected result |
| --- | --- | --- |
| S01 | Legitimate SMS | 201, analysis unavailable, indexed |
| S02 | Phishing SMS | 201; "phishing" is simulation-only ground truth |
| S03 | Legitimate call (metadata only) | 201, all voice stages unavailable |
| S04 | Scam-intent call (metadata only) | Same handling as S03: nothing tells them apart without audio and models |
| S05 | Phishing SMS then scam call, same subscriber, 5 min apart | Two standalone incidents; candidate pair within the window; no pair incident, no conclusion (provisional D05) |
| S06 | Unrelated events, different subscribers | Separate candidate sets; never linked (provisional D05) |
| S07 | Out-of-order delivery (call first, SMS 8 min late) | Pair found by event time; within the 10-min lateness allowance (provisional D05) |
| S08 | Identical duplicate replay | 201 then 200 `replayed: true` with the original receipt |
| S09 | Conflicting replay with the same event ID | 201 then 409 `EVENT_ID_CONFLICT`; original unchanged |
| S10 | Delayed events and window boundaries | 45-min-old SMS not indexed; 36-min-old SMS late but indexed; linked to a call 28 min later, not 32 min later (provisional D05) |
| S11 | Forged source | 403 `FORBIDDEN`, nothing stored |
| S12 | Unapproved audio reference | 422 `UNKNOWN_AUDIO_REFERENCE`, nothing stored |

Provision a test-only key and run it (the key is read from the environment or stdin, never from an argument, and is never printed):

```sh
C="backend/.venv/bin/python -m kavach.cli"
S="backend/.venv/bin/python -m kavach.simulator"
$C key create --name "local simulator" --source simulator --expires-in-days 7 --actor root
$S list
$S run --all --dry-run --run-id demo1                          # the plan only; sends nothing
read -rs KAVACH_SIMULATOR_API_KEY && export KAVACH_SIMULATOR_API_KEY   # paste the key; not echoed
$S run --all --run-id demo1 --seed 7 --base-url http://127.0.0.1:8000
$S run --scenario S05 --scenario S07 --json                    # machine-readable report
unset KAVACH_SIMULATOR_API_KEY && $C key revoke --key-id <id> --actor root
```

A successful run ends with `Summary: 12/12 scenarios passed, 20 submissions`. Each step shows the external event ID, the HTTP status, the receipt ID, `replayed` and the warning codes. Exit codes: 0 all passed, 1 a scenario failed or the run aborted, 2 refused before sending.

- **What it checks.** Status and error code per step; that a replay returns the original receipt; that every receipt says `analysis_status: unavailable` with a warning per stage (no model is deployed); and, via `GET /events/{id}`, that the stored receipt matches. It cannot see PostgreSQL or Redis. The integration tests (`backend/tests/integration/test_simulator.py`) check the stored rows, the standalone incidents (tier `unknown`, null scores), the absence of pair incidents, and the Redis candidate expectations for every scenario.
- **Determinism.** Event IDs are `sim-<run_id>-<scenario>-<step>`, and subscriber tokens are derived from `--seed`, `--run-id`, scenario and alias. Event times are fresh: each scenario's offsets are applied when it starts. Reusing a run ID therefore conflicts (409), so use a new `--run-id` for each run. `--run-id` defaults to a random value.
- **Safety limits.**
  - Only `http(s)` on `127.0.0.1`, `::1` or `localhost`, with no credentials, path or query. There is no override.
  - Redirects are never followed.
  - Pacing: at most `--max-per-minute` submissions (default 20, maximum 30, the server's per-key limit). Room for a whole scenario is reserved before it starts. A 429 is retried at most twice, after `Retry-After`, with the identical payload.
  - At most 60 submissions per run.
  - The run stops at the first 401, unexpected 403, 5xx or lost connection, so a bad key costs one invalid-key attempt.
  - Output has no key, subscriber token, SMS text or ground-truth label in any payload.
- **Labels.** `truth` labels describe what the scenario author wrote. They are never sent to the API and are not model outputs. Scenario expectations marked *provisional: D05* depend on the unapproved 30-minute window and 10-minute lateness (TD-20).
- **Audio.** No audio sample manifest is approved (TD-17), so calls are metadata-only and any `audio_reference` is rejected (S12). The intended manifest contract is in `docs/API.md`.

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

**Current status (M4 integration design gate, 6 November 2026; point-in-time):** the owner approved D04-A1. The pinned Horizon-Labs pretrained transformer may produce experimental, uncalibrated SMS evidence in a separate supervised worker, and TF-IDF stays the comparison baseline. The worker, TD-18 controls and ingestion contract are designed in `docs/M4_SMS_INFERENCE_ARCHITECTURE.md` but **not implemented**: ingestion still records every model stage as unavailable. The offline proof of concept (`experiments/pretrained/`) passed CI on `42da12e`. No model is validated on KAVACH data; label approval is still BLOCKED.

**Historical record — M4.2 follow-up, 5 November 2026:** following the owner's decisions, a *proposed* campaign-level `sms_split.v2` (Jaccard 0.4) now sits beside the preserved, frozen v1 and passes all nine fixed acceptance checks, but it is not leak-free below 0.4 and awaits the owner's adoption. The label-approval gate is cluster-weighted (record-weighted precision is reported only), and a 42-item blinded calibration pilot, disjoint from the audit, is ready for the reviewers. No model is trained and no annotation exists; label approval is still BLOCKED. See section 7 of `docs/M4_2_DATA_QUALITY_REVIEW.md`. Experiments suite 195 passed.

**Historical record — M4.2 data-quality review, 5 November 2026:** the 870 cross-split pairs at similarity 0.6 are mostly templated campaign variants and the pattern continues below 0.6; the review recommended a stricter `sms_split.v2` (Jaccard 0.4) and fixed eight gaps in the human-review evaluator plus a clearer rubric. Experiments suite 162 passed.

**Historical record — M4.2 data preparation, 5 November 2026:** the approved SMS data is acquired and checksum-verified, deduplicated, clustered and split without leakage across duplicate groups, with explicitly synthetic hard negatives and a blinded double-review bundle. **Label approval is BLOCKED: no human review has been done, so no IMC class is promoted and no model can be trained yet.** Details in `docs/M4_2_DATA_PREPARATION_REPORT.md`. Backend default 267 passed, integration 319 passed, experiments 144 passed (its own locked environment); Ruff and lockfiles clean. GitHub Actions has **not** run M4.2; M4.1 passed on GitHub (run 41891028870, commit `0845ed2`).

**Historical record — M4.1 dataset governance, 4–5 November 2026:** research and governance only: four SMS datasets verified on real files, a versioned manifest with a validator (`experiments/`), a reproducible audit, and the M4.2–M4.4 plan; see `docs/DATASET_GOVERNANCE.md` and `docs/M4_EVALUATION_PLAN.md`. No model is trained and no dependency was added; D04 awaits the owner's decision. Default suite 304 passed. GitHub Actions has **not** run M4.1; M3.4 passed on GitHub (run 41885380731, commit `90c32b4`).

**Historical record — M3.4 acceptance, 4 November 2026:** M3 acceptance **CONDITIONAL PASS**, see `docs/M3_INGESTION_ACCEPTANCE.md`. Default suite 267 passed; integration suite 319 passed (11 acceptance regressions and 11 TD-19 tests); both environments; Ruff clean (78 files); `uv lock --check` passed with no dependency changes; no migrations. Fixed: a late replay re-indexing an expired candidate, deep JSON returning 500, an unexplained 500 when a payload key version is removed, and other clients' invalid keys locking out valid keys on a shared IP (TD-19). Mitigated: forwarded-header evasion of the per-IP throttles, through the `--no-proxy-headers` launch flag above. GitHub Actions has **not** run M3.4; M3.3 passed on GitHub (run 41879325247, commit `bf403a8`).

**Historical record — M3.3 local verification, 4 November 2026:** default suite 267 passed (70 new); integration suite 297 passed (14 new simulator tests); both environments; Ruff clean (76 files); `uv lock --check` passed with no dependency changes; no migrations (`alembic check` clean). A real Uvicorn server on a disposable Compose stack ran all 12 scenarios over loopback HTTP: 12/12 passed, 20 submissions, 16 events stored, all standalone with tier `unknown`, and every Redis candidate expectation held. With Redis paused or PostgreSQL stopped, the run aborted after one 503 with nothing stored. GitHub Actions has **not** run M3.3; M3.2 passed on GitHub (run 41867501351, commit `14e23d9`).

**Historical record — M3.2 local verification, 4 November 2026:** default suite 197 passed; integration suite 283 passed (17 new resilience tests); both environments; Ruff clean (67 files); `uv lock --check` passed with no dependency changes; no migrations. Real containers: Redis paused (hung) → 503 in 0.51 s and stopped → 503, nothing stored in either case; after a Redis restart the candidate index was empty and `rebuild` restored it from PostgreSQL; PostgreSQL stopped → 503, restored → 201. GitHub Actions has **not** run M3.2 yet; M3.1 passed on GitHub (run 41698348162, commit `4647f52`).

**Historical record — M3.1 local verification, 4 November 2026:** default suite 187 passed; integration suite 266 passed (29 new ingestion tests); both environments; Ruff clean (63 files); `uv lock --check` passed with no dependency changes. A real PostgreSQL container stop returned 503 for new events with nothing stored; after restart the stored event replayed (200) and the failed one was created on retry (201). GitHub Actions has **not** run M3.1 yet; M2.5 passed on GitHub (run 41695959367, commit `a4a5578`).

**Historical record — M2.5 security acceptance, 3–4 November 2026:** see `docs/M2_SECURITY_ACCEPTANCE.md` for findings and evidence. Default suite 162 passed; integration suite 237 passed (both environments); Ruff clean (56 files); `uv lock --check` passed; migrations `0001` → `0002` verified from empty and on existing data, `alembic check` clean. GitHub Actions has **not** run the M2.5 changes yet; M2.4 passed on GitHub (run 41693476877, commit `0db68fb`).

**Historical record — M2.4 local verification, 3 November 2026:**

- No dependency changes; `uv lock --check` passed (40 entries).
- Default suite: 162 passed, 207 deselected, 1 warning. Integration suite: 207 passed (39 new M2.4 tests). Both in the existing `backend/.venv` (Ruff 0.17.3) and a fresh locked environment (Ruff 0.17.2). Ruff check passed; 54 files already formatted.
- Real-service probes with `python -m kavach.cli` subprocesses: a key created over stdin authenticated (200); with the PostgreSQL container stopped, key authentication returned 503 and `key list`/`retention run` exited 3 ("Database unavailable"); after restart, both worked again. A destructive retention run against `kavach_dev` and a run naming the wrong database were refused.
- GitHub Actions has **not** run M2.4 yet. M2.3 passed on GitHub (run 41186469837, commit `24e6538`, both jobs).

**Historical record — M2.3 local verification, 31 October 2026:**

- `uv lock` added exactly `argon2-cffi` 25.1.0, `argon2-cffi-bindings` 26.1.0, `cffi` 2.1.1 and `pycparser` 3.12 (40 entries); no existing version changed; `uv lock --check` passed.
- Default suite: 144 passed, 168 deselected, 1 warning. Integration suite: 168 passed (27 of them new authentication tests). Both in the existing `backend/.venv` (Ruff 0.17.3) and a fresh locked environment (Ruff 0.17.2). Ruff check passed; 50 files already formatted.
- Two existing tests were updated for the new contract: the OpenAPI path set now includes the three auth routes, and the pilot docs test now supplies the complete (test-only, never connected) configuration that pilot requires.
- Real outage probes: with the Redis container stopped mid-run, login returned 503 immediately, then 200 after Redis was restarted; with Redis refusing connections or never replying, login returned 503 within 1.5 s and verified no password.
- The CI integration job's commands were replayed locally with fresh passwords: migrations, `alembic check` and 168 integration tests passed; cleanup left no containers or volumes.
- GitHub Actions has **not** run M2.3 yet. M2.2 passed on GitHub (run 41121829796, commit `e7c0873`, both jobs).

**Historical record — M2.2 local verification, 31 October 2026:**

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

M1.1 and M2.1–M2.3 are complete (GitHub Actions green on `c36e903`, `0cebb3b`, `e7c0873` and `24e6538`). M2.4 (source-scoped API keys, operator CLI, audit, retention) is implemented and verified locally, uncommitted, and has not yet run on GitHub (see `docs/MILESTONE_TRACKER.md`). Backend milestones M1.1–M7a stay on `backend` and reach `dev` through a single integration pull request after full backend acceptance (`docs/GIT_WORKFLOW.md`). D02 packages, D03, D07 and C-06 were approved on 31 October 2026. Ingestion, ML, Redis correlation and frontend are not started. Branch workflow and milestone status: `docs/GIT_WORKFLOW.md`, `docs/MILESTONE_TRACKER.md`.
