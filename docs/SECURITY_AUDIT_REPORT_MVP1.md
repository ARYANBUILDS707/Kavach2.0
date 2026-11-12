# Security Audit Report: SMS MVP-1 on `dev`

This report executes the procedure in [SECURITY_AUDIT.md](SECURITY_AUDIT.md) for the SMS MVP-1 release candidate. It is point-in-time evidence, not a certification. Legal authorization and privacy review for any pilot remain separate gates.

| Item | Value |
| --- | --- |
| Commit audited | `61cbffa01e4f4b24ec64fdca6e390295d4b735b0` (`dev`, merge of PR #2; tree identical to PR head `39b7721`) |
| Date | 12 November 2026 |
| Scope | Local controlled demo. Loopback only, synthetic accounts, fictional messages, SMS worker disabled. No deployment exists. |
| Method | Static review of the extracted commit (`git archive`, no checkout); automated suites; real-service probes against disposable PostgreSQL 17.11 and Redis 7.4.12 started with fresh random credentials and removed afterwards; real-browser Playwright journeys. No secret values were printed or recorded. |

## Tests actually run on `61cbffa`

| Suite | Result |
| --- | --- |
| Lockfile checks (backend, experiments, worker) | in sync |
| Backend default suite | 387 passed, 1 skipped (real-model test) |
| Backend integration (real PostgreSQL and Redis) | 424 passed, 1 skipped |
| Alembic upgrade (twice), `current`, `check` | clean, no drift |
| Ruff lint and format (backend, experiments, worker) | clean |
| Experiments / SMS worker suites | 275 passed / 40 passed |
| Frontend `npm ci`, `npm audit --audit-level=high`, `npm run verify` | passed; 136/136 tests; contract SHA-256 matches backend |
| Playwright against the real stack | 17/17 passed, including idle expiry against a backend with `SESSION_IDLE_MINUTES=1` |
| Python advisories (`pip-audit` 2.9.0 against OSV, locked pins) | backend 39 pins: none known; SMS worker model group 59 pins: none known |
| npm advisories | 0 critical, 0 high, 10 moderate (development tooling only) |
| GitHub Actions | Backend CI on `61cbffa` push: run 43153516772 success; PR #2 runs 43153039779 (backend) and 43153039726 (frontend) success |

## Boundary review

| Boundary | Result | Evidence |
| --- | --- | --- |
| Accounts | Pass | Argon2id, RFC 9106 low-memory profile, rehash on login, dummy hash for unknown usernames (`auth/passwords.py`); generic login error (browser test); operator-only provisioning, no default passwords; deactivate and reset revoke sessions (integration tests) |
| Sessions | Pass | 256-bit `secrets.token_urlsafe` tokens stored as SHA-256 digests; session-bound HMAC CSRF token (`auth/tokens.py`); `HttpOnly`, `SameSite=Lax` cookie, and `Secure` with the `__Host-` prefix on HTTPS origins (`auth/cookies.py`); idle expiry proven in the browser; empty browser storage asserted |
| Authorization | Pass | Viewer sees no Analyze page, and the API returns 403 `FORBIDDEN` to a viewer submission (browser). Incident reads refuse API keys and mixed credentials (`test_reads_need_a_dashboard_session_and_refuse_keys_and_mixed_credentials`). The analyst role is covered by backend tests only, not in the browser. |
| Browser mutations | Pass | Probes: missing token, wrong token, and foreign Origin with a valid token all returned 403 `CSRF_REJECTED`; foreign-Origin login refused; no CORS middleware; same-origin proxy only |
| Inputs | Pass | Strict DTOs (`extra="forbid"` on 8 models), bounded text and identifiers, timezone and skew checks, repeated-parameter 422 (tests); no SQL built with string formatting found |
| Media | Not applicable | Calls and audio are not in MVP-1; `audio_reference` syntax excludes paths and URLs |
| Model artifacts | Pass, disabled | Pinned manifest with checksums (`deployment/models/`); no model binaries in Git; artifacts verified by the offline real-model smoke test on `50431e9`; worker off (`GET /system/models` → `disabled`, `validated_on_kavach_data: false`) |
| Database | Pass | Least-privilege roles (`kavach_app` has no DDL; separate migrator and retention roles); constraint, privilege and rollback integration tests; ports bound to 127.0.0.1 |
| Secrets | Pass | No `.env`, key or certificate files tracked in `61cbffa`; examples hold placeholders only; bundle scan passed (no ingestion key or test double in the build); no credential string in any log or test output |
| Privacy | Pass | After 6 stored events: 0 occurrences of submitted text in a full `pg_dump`, in Redis keys or values, or in backend logs; 0 log lines with tracebacks or passwords; `Cache-Control: no-store` on authenticated responses |
| Abuse | Pass | Read limit of 120 per minute per user: 429 with countdown observed in the browser. Redis stopped: login and reads 503 `DEPENDENCY_UNAVAILABLE`, liveness 200. PostgreSQL stopped: reads 503. Both recovered. |
| Audit | Partial | Audit rows are written in the same transaction as the change, with a keyed HMAC. **No operator command verifies those HMACs** (finding L1). |
| Operations | Not applicable to local scope | No TLS, packaging or monitoring exist (M11). The per-IP throttles rely on the `--no-proxy-headers` launch flag; a proxied deployment needs trusted-proxy configuration. |
| Dependencies | Pass | Lockfiles enforced in CI; advisories above; no cloud or telecom SDKs |

**KAVACH-specific abuse cases:**
- **Changed payload under the same event ID:** returns 409; covered by integration tests.
- **Forged source:** the browser path is fixed to `simulator`.
- **Cross-subscriber linkage:** `ui-sub-` tokens are synthetic and never identity evidence (decision B4-1).
- **Missing-signal zero filling:** verified absent; every score is null, never 0.
- **Real-data prohibition:** fictional messages only.
- **Not applicable in MVP-1:** review replay or overwrite, and live-stream expiry (reviews and WebSocket are postponed).

## Findings

| ID | Severity | Boundary / files | Evidence | Impact | Status and follow-up |
| --- | --- | --- | --- | --- | --- |
| M1 | Medium (process) | CI, `.github/workflows/frontend-ci.yml` | Push triggers only on `frontend`; no Frontend CI run exists on `61cbffa` (tree identical to the passing PR run) | A future change landing on `dev` could skip frontend checks | Open. Add `dev` and `main` to the push branches with owner approval. |
| M2 | Medium (process) | Repository settings | `dev` and `main` have no branch protection or required checks (GitHub API: "Branch not protected") | A PR can merge without green CI | Open. Apply protection with both CI workflows required, or record an explicit waiver. |
| L1 | Low | Audit, `backend/src/kavach/cli.py` | CLI groups are `user`, `key`, `candidates`, `retention`; no audit verification command | The audit integrity claim is limited to "HMAC computed at write"; tampering is not detectable by an operator today | Open. Add an operator `audit verify` command later (hardening milestone). The release notes must not claim verified audit integrity. |
| L2 | Low | Frontend dev dependencies | `npm audit`: 10 moderate (ESLint, typescript-eslint, minimatch ReDoS) | Development tooling only; not in the production bundle | Accepted for this release; upgrade within the dependency policy when convenient |
| I1 | Info | Operations | No packaging, TLS or reverse proxy; throttle depends on `--no-proxy-headers` | Hosted use is not supported | Release scope is local demo only |

No critical or high findings. No fixes were required in application code.

## Residual risks and manual checks not performed

- No screen-reader session was recorded (axe and keyboard tests only).
- No analyst-role browser journey (backend tests cover the role).
- Worker-enabled degraded states (starting, saturation, timeout, crash) were not exercised end to end, because the worker stays disabled. They are covered by backend integration tests.
- No penetration test or third-party review; reviewer and author were the same team.
