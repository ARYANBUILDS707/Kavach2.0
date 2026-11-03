# M2 Security Acceptance Report (M2.5)

Dated execution report, 3–4 November 2026, for the backend identity, database and security foundation (M2.1–M2.4) on branch `backend`. It applies the procedures in [SECURITY_AUDIT.md](SECURITY_AUDIT.md) and [TESTING_QA.md](TESTING_QA.md) to what is implemented; it is not a certification and makes no claim about production or legal compliance. Results are point-in-time; re-run the commands before relying on them.

## Baseline

| Item | Evidence |
| --- | --- |
| Commit audited | `0db68fb` (`backend` = `origin/backend`, clean tree) |
| GitHub Actions on `0db68fb` | run 41693476877: "Backend tests and lint" and "Backend integration (PostgreSQL and Redis)" both success (read from the public GitHub API) |
| Local re-run before any change | `uv lock --check` passed; default 162 passed; integration 207 passed; Ruff clean; `alembic upgrade head` + `alembic check` clean |
| Environment | macOS arm64, Docker 29.8.0, `deployment/compose.dev.yml` (PostgreSQL 17.11, Redis 7.4.12, digest-pinned), Python 3.12.13; both the existing `backend/.venv` (Ruff 0.17.3) and a fresh environment from `backend/uv.lock` (Ruff 0.17.2) |
| Dependency advisories | OSV.dev batch query of all 39 locked third-party packages (4 Nov 2026): **no known advisories** |

## Findings

Each finding was reproduced against real PostgreSQL before fixing and re-tested after. "Fixed" means fixed in the working tree and covered by tests; it has not yet run in GitHub Actions.

| ID | Severity | Finding | Evidence (before) | Status |
| --- | --- | --- | --- | --- |
| M-1 | Medium | The retention role held table-level DELETE on sessions, incidents, events and audit_records, so it could delete **unexpired** rows, including every audit record. DATABASE.md calls for narrowly scoped expiry procedures. | As `kavach_retention`: `DELETE FROM audit_records WHERE id = <unexpired>` deleted 1 row; unconditional `DELETE FROM audit_records` deleted 36 rows (rolled back). | **Fixed** by revision `0002_retention_procedure`: table privileges revoked; EXECUTE on `kavach_retention_purge` only, which deletes expired rows only. After: both statements fail with InsufficientPrivilege. |
| M-2 | Medium | Retention audit gap: a destructive run was audited only after its deletions committed; a crash in between left deletions with no audit record. | Code review of M2.4 `retention_run`. | **Fixed**: `run_audited_retention` commits `retention.start` before the first deletion (nothing is deleted if it cannot be written) and `retention.complete` after, sharing the run ID. Tested: start recorded while rows still exist; failed start → no deletion; interrupted run → start without completion. |
| M-3 | Medium | Revocation was reversible: the runtime role's column grant on `revoked_at` allowed setting it back to NULL for sessions and ingestion keys. | As `kavach_app`: `UPDATE sessions SET revoked_at = NULL` and the same on `ingest_keys` each updated 1 row (rolled back). | **Fixed** by a `revocation_is_final` trigger (0002) for every role. After: CheckViolation. |
| L-1 | Low | A destructive retention run accepted a future cutoff, so unexpired rows (including audit evidence) could be purged early on a test database. | Dry run with cutoff now + 10 years would have deleted 41 unexpired audit rows. | **Fixed** in the database (procedure refuses cutoffs later than its clock) and in the application (refused before any work; default cutoff is the database clock). |
| L-2 | Low | A concurrent duplicate username surfaced as an unmapped `IntegrityError`, which the CLI reported as "Database unavailable". | 6 concurrent provisions of one username: 1 created, 2 refused, 3 unmapped `UniqueViolation`. | **Fixed**: insert in a savepoint, unique violation → "That username is already provisioned"; CLI reports other constraint rejections as refusals (exit 1). |
| L-3 | Low | Every database error on request paths was reported as 503 "dependency unavailable", including privilege or programming errors. | Code review (`except DBAPIError`). | **Fixed**: only connection-level errors (`OperationalError`, `InterfaceError`) map to 503; anything else is a 500. |
| L-4 | Low | `X-Forwarded-For` is ignored, so behind a proxy every client shares one IP throttle bucket and its 30-failure ceiling. | Design (TD-14). | Open; must be resolved before any proxied deployment. |
| L-5 | Low | A 401 `SESSION_EXPIRED` does not clear the stale session cookie (logout does). | Code review. | Open; cosmetic, no access is granted. |
| L-6 | Low | Failed Bearer-key attempts are not throttled. | Design. | Accepted for M2: keys carry 256 random bits; revisit with ingestion rate limits (D08) in M3. |
| L-7 | Low | The CLI's operator password check provides attribution and policy, not a security boundary: anyone holding the runtime database credentials can bypass it. | Design (documented in `kavach.auth.accounts`). | Accepted; credential custody is the boundary. |
| I-1 | Info | Audit HMAC detects modification but not deletion; the runtime role holds the signing key and can insert audit rows, so a compromised application could also forge valid records. | Tests: modified row fails verification; deleted row leaves no trace; remaining rows verify. | Residual; stronger assurance needs independently controlled storage (DATABASE.md). |
| I-2 | Info | `GET /health` is public liveness, while API.md's target contract makes `/health` authenticated. | C-07 (deferred by the owner). | Deferred; M1 routes and tests preserved. |
| I-3 | Info | A dry run executes the real batched deletes and rolls back, so it briefly locks the rows it would delete. | Design. | Accepted for operator-triggered local runs; revisit before scheduling. |

No critical or high findings were identified.

## Acceptance results (after fixes)

| Area | Result |
| --- | --- |
| Migrations | Fresh `upgrade head` (0001 → 0002) succeeds; repeated upgrade is a no-op; `alembic check` clean; `0002` → `0001` → `0002` round trip on a database holding data succeeds; both downgrades refuse anything but an explicitly named `*_test` database |
| Schema | 9 tables, 35 CHECK constraints, deferred circular FKs, 4 deferred integrity triggers, revocation triggers on `sessions` and `ingest_keys`; tested by violating inserts and catalog inspection |
| Privileges | Runtime: SELECT/INSERT everywhere, UPDATE only on named mutable columns, no UPDATE/DELETE on append-only tables, no DDL. Retention: no table privileges, EXECUTE on the purge procedure only. Verified by catalog checks for every table and column and by attempted statements |
| Authentication | Login/session/logout, idle (30 min) and absolute (8 h) expiry, rotation, revocation on logout/deactivation/password reset, Argon2id RFC 9106 low-memory profile with rehash, CSRF, exact Origin, cookie flags for HTTPS and local HTTP, mixed credentials, role re-check per request, last-admin protection |
| API keys and CLI | Create/rotate/revoke/list, expiry, cross-source 403, uniform 401 for malformed/unknown/expired/revoked keys, digest-only storage, secrets never accepted as arguments, single-winner concurrent bootstrap (8 threads), bootstrap allowed only while no admin is active |
| Failure safety (real containers) | Redis stopped → login 503 in 0.03 s with **0 password verifications**, existing sessions unaffected; restarted → 200. PostgreSQL stopped → login 503 with 0 verifications, session check 503; restarted → 200 (pool pre-ping reconnects). Hung Redis socket → 503 within the 0.5 s timeout budget (test). Two-process throttle: exactly 5 × 401 then 429 |
| Audit and retention | All security-sensitive mutations audited transactionally; audit failure rolls back the change; tampering detected; deletion not detectable (documented). Retention cutoff boundary (at or before deleted, 1 µs after kept), dry-run exactness, foreign-key order, users and keys preserved, destructive-target protection |
| Leakage | No password, username, session token, CSRF token or API key in logs (captured at DEBUG) or error bodies; SQL parameters hidden in engine errors |

## Commands and results

Run from the repository root against `deployment/compose.dev.yml` with the `TEST_*` variables from the README:

| Command | Existing `backend/.venv` | Fresh locked environment |
| --- | --- | --- |
| `uv lock --check --project backend` | passed (40 entries) | — |
| `pytest backend/tests` | 162 passed, 237 deselected | 162 passed, 237 deselected |
| `pytest backend/tests -m integration` | 237 passed, 162 deselected | 237 passed, 162 deselected |
| `ruff check backend` / `ruff format --check backend` | passed / 56 files formatted | passed / 56 files formatted |
| `alembic upgrade head` (twice), `alembic check` | applied; no-op; no differences | — |

The single warning in every pytest run is the known Starlette/httpx deprecation (TD-04).

## Not verified

- GitHub Actions on the M2.5 changes (requires the owner's push).
- Behavior behind a reverse proxy, TLS termination, and multi-replica deployments (no deployment exists).
- Load, latency percentiles and long-running resource use (M10).
