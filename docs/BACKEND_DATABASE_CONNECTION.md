# KAVACH Backend and Database Connection Workflow

## Prerequisites

Future execution instructions. Read DATABASE.md, ARCHITECTURE.md, API.md, PRD.md and AGENTS.md. Confirm D02/D03/D05/D07 and the assigned phase. Inspect existing migrations/services before adding anything. Use development/test credentials from secret configuration; never connect to production by assumption.

## Execution

1. Validate DATABASE_URL/REDIS_URL without printing credentials. Create reviewed migrations for exactly the approved schema, including deferred assessment/review references, channel membership checks and query-driven indexes.
2. Establish separate migration/runtime/retention privileges. Test runtime cannot alter audit/review/assessment history or schema.
3. Implement repositories and transaction boundaries; keep route handlers independent from raw SQL details.
4. Implement event source scoping, canonical retry HMAC, subscriber HMAC, input bounds and sanitized fields. Never persist raw SMS/transcript/audio as a shortcut for retries.
5. Enforce bounded inference outside locks; serialize same-subscriber commit work, recheck duplicate IDs, persist event/incident/assessment/audit atomically.
6. Implement Redis candidate caching with event-time validation and PostgreSQL fallback. Redis restart must not lose committed incidents or duplicate protection.
7. Implement review version/idempotency checks and append-only history transactionally. Audit failure must fail the associated mutation.
8. Implement approved expiry cleanup and synthetic-only development seed commands. Do not add default credentials or automatically seed shared deployments.

## Verification

Run fresh-database migrations and supported upgrade path; inspect constraints and actual query plans. Test duplicate/simultaneous ingestion, mixed-source IDs, pair uniqueness, rollback, review conflict, unauthorized reads/writes, Redis outage, database outage, expiry deletion and restore. Verify no raw communications appear in tables, errors or logs.

Report applied migrations and target environment, services/endpoints implemented, tests actually run, observed connection status and any missing credentials/approval. Never report a production connection from a successful local container test.
