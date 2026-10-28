# KAVACH Deployment and Production Setup Workflow

## Deployment scope

Default target is a local controlled demo. Hosting provider, region, hardware, domain and live-data authority remain pending PRD D10. No deployment has been performed by this documentation task. Read ARCHITECTURE.md, API.md, DATABASE.md and AGENTS.md. Do not describe a working local Compose environment as telecom-ready or production-certified.

## Preconditions

Confirm target environment and authorization for external resources/costs. Resolve environment-specific retention, model licensing, data access, capacity and operating responsibilities. Verify the implementation has passed critical QA/security checks. For a live pilot, obtain specialist review and documented authority to process the specific communications; this procedure is not legal certification.

## Preparation and deployment

1. Inspect existing deployment tooling and preserve persistent volumes. Build pinned frontend/backend images from a clean revision; record artifact/model/policy versions.
2. Run production frontend build, backend tests/type/lint checks and integration smoke tests. Do not start deployment with a known failing critical build/test.
3. Provision the approved environment only. Keep database/Redis private, mount model/sample assets read-only, configure resource limits and a single API process per approved MVP capacity plan.
4. Set API.md secret/config variables through environment secret storage. Use separate migration/runtime/retention credentials and fresh non-development keys/accounts. Never bake secrets into images or browser bundles.
5. Configure same-origin routing, domain and HTTPS for a shared deployment. Proxy `/api/v1` and `/api/v1/stream`; restrict trusted proxy headers. HTTP-only local development must remain loopback-bound.
6. Back up existing data before migration. Run reviewed migrations once with the migration role, validate schema, then start runtime services. Do not erase volumes or downgrade destructively to resolve a failure.
7. Verify liveness and authenticated readiness. Missing model assets must prevent a claim of full analysis readiness even when the UI starts.
8. Run synthetic login/ingestion/detail/review/logout smoke tests with least-privilege accounts. Confirm no raw communications or secrets in logs/responses.
9. Activate retention jobs, encrypted backups and monitoring from MONITORING_MAINTENANCE.md. Perform a restore drill before a pilot release.
10. Document rollback: retain previous application/model artifacts; use only schema-compatible application rollback; restore data only through an approved recovery procedure with known data-loss implications.

## Runtime commands

Derive exact build/start/migrate commands from implemented manifests and record them in the execution report. Required capabilities: frontend production build, Uvicorn server startup with the approved process count, Compose service orchestration, Alembic upgrade, retention job and health smoke check. This specification does not assert scripts already exist.

## Verification checklist

Verify configured origin/cookies/CSRF, TLS, private dependency ports, key privileges, migration status, image/model versions, health, browser routing/deep links, WebSocket reconnection, overload rejection, backup success and restore results. Confirm demo-only samples and no automatic external transmissions. Check operational metrics against measured capacity, not V4 benchmark claims.

## Required report

State deployment target and URL if one exists; otherwise “not deployed” or “prepared only.” Include revision/artifacts, commands/results, variable names without values, migrations applied, tests, backup/restore status, rollback procedure and manual blockers. Separate a successful local demo from an approved research host or live pilot launch.
