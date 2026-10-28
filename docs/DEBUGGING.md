# KAVACH Debugging and Root Cause Workflow

## Required input

Identify a concrete error, failing journey, sanitized log/request ID, screenshot or reproduction. No bug is specified by this document. Read AGENTS.md and relevant source-of-truth documents before modifying code.

## Investigation

1. Record expected versus observed behavior, environment, model/policy versions, event/arrival times and recent relevant changes. Do not request or print real SMS/audio, OTPs, credentials or subscriber identity when synthetic reproduction is possible.
2. Reproduce with the smallest authorized synthetic case. Trace API validation, role checks, inference stage status, matching rules, database transaction and frontend response handling.
3. For unexpected risk, inspect distinct intent/synthesis scores, null handling, feature units/order, base-risk floor and manifest versions. Do not “fix” a test by changing thresholds without approval.
4. For missing/duplicate incidents, inspect source/event ID uniqueness, canonical payload digest, event-time/lateness rules, subscriber digest version, cache fallback and concurrent transaction behavior.
5. For failed reviews, check incident version/assessment revision, idempotency key reuse, transaction/audit failures and stale client state.
6. Establish the causal chain with a failing test or reproducible trace. If evidence is insufficient, state exactly which sanitized observation is missing; do not guess.
7. Implement the smallest correct fix using existing patterns. Avoid unrelated rewrites, suppressed errors, removed tests, relaxed validation or new dependencies without cause.
8. Re-run the reproduction and relevant regression/security tests; inspect the diff and update a contract only for approved behavior changes.

## Output

Report root cause and why it occurs, fix and changed files, test commands/results, remaining uncertainty and operational follow-up. If no fix can be verified, say so explicitly rather than claiming resolution.
