# KAVACH Definition of Done

A milestone, or any change inside one, is done only when every applicable item below holds. Milestone-specific criteria in [MASTER_DEVELOPMENT_PLAN.md](MASTER_DEVELOPMENT_PLAN.md) are added to these, never traded off against them. [AGENTS.md](../AGENTS.md) governs when a rule here is unclear.

## 1. Scope

- The task was authorized by the owner and stays inside the milestone; no excluded feature (public signup, tenant management, live call capture, external LLM, billing, intervention automation, arbitrary uploads) was added.
- Relevant pending decisions (D01–D10) were resolved or the dependent work was not done.
- Source-of-truth documents read before planning: PRD, DESIGN, ARCHITECTURE, DATABASE, API, IMPLEMENTATION_PLAN.
- The work is on the correct branch ([GIT_WORKFLOW.md](GIT_WORKFLOW.md)).

## 2. Code quality

- Reuses existing patterns; no unrelated formatting, rewrites or generated clutter.
- Routes thin, business rules in services/domain modules, SQL in repositories, ORM in `db/`, inference adapters in `models/`.
- Python: snake_case modules/functions, PascalCase classes, type annotations and validated DTOs at service boundaries and model results. TypeScript: strict mode, no unexplained `any`, unsafe cast or ignored type error.
- Missing results are explicit (`null` plus reason); null is never coerced to zero. Before a model exists its outputs are `null` with `analysis_status = unavailable` and tier `unknown`, never safe.
- A new dependency has a concrete need, an approved version, and a recorded reason; lockfile updated.

## 3. Behavior and invariants

- PostgreSQL authoritative; Redis never the sole record of anything.
- 201/200/409 idempotency semantics intact; success returned only after commit.
- SMS and voice-intent risk independent; synthesis alone never raises base risk; expiry never lowers independent risk; missing evidence never means safe.
- Historical assessments and reviews are never mutated; new versions are appended.
- Error handling distinguishes bad input, unauthorized, forbidden, not found, conflict, saturation, missing model stage and dependency failure. No blanket catch-and-success.

## 4. Security and privacy

- Authentication, role, source scope, ownership and active-account checks are enforced server-side on every new route and WebSocket.
- State-changing browser requests have CSRF and exact Origin checks.
- Login throttling is shared across processes and login fails closed when the shared throttle is unavailable; a process-local throttle is never accepted for authentication.
- No secret, token, raw message, transcript or audio is hardcoded, logged, returned, stored in Redis, URLs or browser storage, or committed. Debug logging included.
- All text, audio, path, URL and artifact inputs treated as untrusted: bounded, validated, parameterized SQL, manifest-approved sample IDs only.
- Validation and permissions were not weakened to make a test or demo pass.

## 5. Tests and verification

- Behavior and security boundaries are tested, not implementation trivia. New validation, permission and failure paths have tests.
- Persistence, constraint, race and rollback behavior uses real PostgreSQL; cache behavior uses real Redis. Model doubles exist only in tests.
- Distinguish historical results (earlier runs, reported elsewhere) from the current run; only the current run counts for this milestone.
- Run, and report with exact commands and actual output:

```sh
backend/.venv/bin/python -m pytest backend/tests
backend/.venv/bin/python -m ruff check backend
backend/.venv/bin/python -m ruff format --check backend
```

  plus integration, frontend type-check/test/build, and migration checks when those exist. Use the `uv run --project backend --locked` forms once a committed `uv.lock` exists.
- Failures are reported, not hidden. Tests are never deleted or weakened to pass. Checks that could not run are listed as "not run" with the reason.
- ML claims: any reported rate has numerator, denominator, split description and provenance; train/test leakage is checked; UI fixtures are separate from evaluation data. No claim of accuracy, latency or compliance comes from a screenshot, hardcoded score or the historical V4 figures.

## 6. Documentation and contracts

- Source-of-truth documents updated in the same change when an approved contract or behavior changes (API, schema, policy, environment variables).
- `.env.example` contains placeholder names only, matching API.md.
- README/tracker statements describe what exists and what was verified, not aspirations.
- [MILESTONE_TRACKER.md](MILESTONE_TRACKER.md) updated only for verified status.

## 7. Review and merge

- `git diff` reviewed for secrets, private data, binaries, lockfiles and accidental changes.
- Migrations reviewed separately; no destructive migration without explicit authorization and a recovery plan; forward repair preferred.
- Reviewer other than the author, or a recorded owner waiver; no unresolved critical or high finding.
- Branch current with `dev`, checks re-run after merging `dev` in.
- Enters `dev` through a pull request; no direct push to `main` or `dev`.
- CI status checks green once CI exists (M1.1); until then local results are pasted into the PR.
- No commit, push, merge or deploy without explicit approval.

## 8. Required PR/task report content

1. Summary of the change and milestone.
2. Changed files and why.
3. Commands run and actual results (including failures and "not run").
4. Contract or schema changes and the documents updated.
5. Security and privacy considerations checked.
6. Remaining limitations, open risks and the next milestone.

## 9. Exit criteria for a milestone

All items above hold, every acceptance criterion of the milestone is evidenced, the owner has reviewed the report, and the tracker is updated. Anything unevidenced is stated as unverified.
