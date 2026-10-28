# KAVACH Code Review and Refactoring Workflow

## Review basis

Read PRD.md, DESIGN.md, ARCHITECTURE.md, DATABASE.md, API.md and AGENTS.md. Inspect current code, tests, dependencies and user changes. This file is a future review procedure; no implementation was reviewed during document creation.

## Review priorities

1. Verify required behavior before style: real inference, correct missing-signal semantics, authorized event matching, independent-risk preservation, idempotency and review history.
2. Check architecture: thin API handlers, service transactions, separate inference/ORM models, no database or secrets in frontend, no model training in request handlers.
3. Check concurrency and failure: duplicate event races, same-subscriber matching, cache loss, deadline cancellation, atomic audit/review writes and lost responses.
4. Check API/schema consistency: endpoint-role matrix, fields and constraints, cursor ordering, retention graph, immutable assessment references and migrations.
5. Check UI: reusable design tokens/components, truthful states, focus handling, responsive evidence and role-aware controls backed by server checks.
6. Identify duplicated/dead code, unnecessary dependencies, excessive abstraction, misleading naming, hidden global state and swallowed exceptions.
7. Check performance with evidence: model loading count, blocked event loop, unbounded buffers, repeated inference, N+1 queries and unexplained indexes.
8. Check test quality: critical boundaries covered, mocks isolated, no tests proving only their own implementation, no metrics copied from V4 as actual results.

## Refactoring rules

Fix clearly justified bugs and safe maintainability problems in small changes. Preserve working behavior unless correcting a documented bug. Reuse existing patterns; do not rewrite modules merely for style or add frameworks to simplify a minor function. Explain contract changes and update approved docs. Run relevant tests/build/type checks after changes; do not broaden testing repeatedly without a new reason.

## Report

List critical findings first, with file references, impact and evidence. Report refactoring performed, changed files, commands/results, remaining technical debt and any behavior change needing approval. State unreviewed areas and unknowns instead of presenting absence of discovered bugs as proof of correctness.
