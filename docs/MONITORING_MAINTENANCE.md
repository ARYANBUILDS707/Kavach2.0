# KAVACH Production Monitoring and Maintenance Workflow

## Status and prerequisites

Monitoring is not configured by this document. Read ARCHITECTURE.md, API.md, DATABASE.md and AGENTS.md and inspect the actual deployment. Use simple structured logs, health checks and the chosen hosting platform's existing monitoring first. No additional monitoring vendor is required for a local demo.

## Signals to collect

| Signal | Useful measurement | Privacy limit |
| --- | --- | --- |
| Availability | Public liveness and protected dependency/model readiness | No internal errors/credentials in public output |
| API | Request count, status class, endpoint template, latency, request ID | No bodies, query secrets or subscriber identity |
| Inference | Stage duration, failure/unavailable counts, worker capacity/timeouts, model version | No text, transcript, audio or full feature vectors |
| Correlation | Candidate/pair counts, rejection reason codes, cache fallback count | Aggregate only; no subscriber tags |
| Reviews | Save/conflict/failure counts and transaction health | No review note content |
| Database/Redis | Connection failure, pool saturation, query duration, memory/storage | No SQL parameter dumps or key contents |
| Live updates | Connection count, disconnect rate, slow-consumer drops | No session tokens or evidence payload logs |
| Retention/backups | Last run, deleted-record counts, backup age, restore drill result | Protected job metadata only |
| Host resources | CPU/RAM/disk; GPU utilization/memory if used | No process environment dumps |

Operational risk-score distributions are not accuracy measurements. Precision/recall require labeled evaluation and denominators; never derive fraud accuracy from incident counts or analyst agreement alone.

## Proposed actionable alerts

These are starting values for the approved pilot, to be tuned against measured traffic and an assigned responder. Local demo needs visible health status, not a paging system.

- Page/urgent notification: service unavailable for two consecutive one-minute probes; database write failure persists for two minutes; audit-sign/write failure blocks mutations; sustained disk free space below 10%.
- Urgent investigation: API 5xx >5% over five minutes with at least 20 requests; model stage unavailable for five minutes during active ingestion; inference saturation/rejection persists for five minutes.
- Warning: Redis fallback persists for five minutes; latency exceeds an approved measured SLO for ten minutes; failed retention run; backup older than 26 hours against a daily schedule.
- Security follow-up: abnormal sustained login denials or authorization failures, using aggregate counts and rate-limit evidence rather than storing communication content.

Group related failures, notify once per incident with cooldown, and send recovery notification. Each alert needs an owner, impact description, dashboard/log link and runbook. Do not enable external messaging without the deployment task's authorization and chosen service.

## Runbooks and maintenance

1. Database failure: stop false-success writes, preserve volumes, inspect safe connection/storage metrics, restore connectivity; do not reset data.
2. Redis failure: confirm bounded fallback behavior, maintain explicit degraded state, restore cache without losing durable records.
3. Model failure/overload: inspect artifact checksum/version and capacity; restart the bounded worker if appropriate; keep missing intent visible; do not replace it with synthesis risk.
4. Authentication incident: revoke affected sessions/keys, rotate scoped credentials and investigate sanitized audit evidence; avoid printing secrets during response.
5. Retention/backups: run scheduled deletion with the restricted role; verify actual expired-record removal and finite backup retention. Alert on repeated failures.
6. Updates: review dependency/model changes, run regression and evaluation tests, stage deployment and retain compatible rollback artifacts. Never retrain silently from analyst reviews.

## Recovery verification

Target pilot RPO 24 hours/RTO 4 hours is proposed, not achieved. Record backup encryption/access, frequency, retention and protected key recovery. Restore to an isolated environment; verify constraints, incident/review linkage, HMAC verification, cleanup of expired records and invalidation of restored sessions before service exposure. Run a drill before pilot launch and after material storage/key changes; propose quarterly repetition once operated.

## Report

List what is actually tracked, configured alert thresholds/destinations, responders, retention jobs, last successful backup/restore, observed recovery times and unmonitored gaps. Do not claim alerting works until a test failure and recovery notification are verified. Record local-only limitations explicitly.
