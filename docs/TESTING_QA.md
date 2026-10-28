# KAVACH Testing and QA Workflow

## Status and test strategy

No application tests have been executed by this documentation task. Before testing, read PRD.md, API.md, ARCHITECTURE.md, DATABASE.md, DESIGN.md and AGENTS.md and inspect the actual implementation. Prioritize user journeys, security boundaries, correlation correctness and data loss over superficial coverage percentages.

Use pytest for pure domain and backend integration tests, real disposable PostgreSQL/Redis for persistence/cache behavior, Vitest/Testing Library for interactive components, and Playwright for critical browser journeys. Tests may use clearly isolated deterministic model doubles; at least one separate real-artifact smoke test and offline evaluation are required before claiming inference works.

## Critical test matrix

| Area | Cases | Expected invariant |
| --- | --- | --- |
| Authentication | Login, disabled user, bad password, idle/absolute expiry, logout | No protected access after expiry/revocation |
| Authorization | Every role/endpoint, source-scoped key, missing CSRF, wrong Origin | Server denies unauthorized operation |
| SMS | Benign OTP, phishing, obfuscation, unknown language | Versioned result or explicit uncertainty; keyword alone is not proof |
| Voice | Human scam, benign synthetic IVR, noise, silent/corrupt audio | Synthesis and intent remain separate; failed stage is not zero |
| Input | Unknown fields, invalid dates/IDs, oversize JSON/audio, path/URL samples | Bounded validation before unsafe processing |
| Correlation | Same/different subscriber, same brand only, unrelated close events | Identity/time/context all respected |
| Event time | Both arrival orders, exact window/lateness boundaries, expired cache | Event-time correctness; late independent risk preserved |
| Fusion | Both signals borderline, missing signal, high standalone risk | No both-positive gate; no suppression by elapsed time |
| Idempotency | Retry, changed payload, concurrent same ID, lost response | One durable event or explicit conflict |
| Persistence | Concurrent SMS/call, audit failure, commit failure | Unique pairs and atomic rollback |
| Review | All decisions, repeated save, stale revision/version, concurrent analysts | Append-only history; safe retry; no silent overwrite |
| Feed | Filters, cursor bounds, new arrivals, expiring records | Stable ordering, safe pagination, correctly labeled record counts |
| Live updates | Disconnect, dropped invalidation, slow client, expired session | REST reconciliation; bounded resources; no unauthorized stream |
| UI states | Loading, empty/filter-empty, partial, stale, conflict, 401/403/404/429/503 | Clear truthful state with relevant recovery |
| Privacy | Database/log/error/browser storage inspection | No raw messages/audio/transcripts/secrets or forbidden identifiers |
| Operations | Redis/DB/model outage, overload, kill deadline, restart | No false success; bounded processing and explicit degradation |
| Retention | Expired incident graph, audit expiry, restore cleanup | No dangling records; policy survives restore |

## End-to-end journeys

1. Admin logs in, runs each fixed synthetic scenario, observes actual receipts, opens linked incidents, and verifies independent and pair evidence.
2. Analyst filters incidents, opens detail, saves a review, reloads and sees persisted attribution/history.
3. Viewer can inspect but cannot submit reviews, run the simulator or obtain machine credentials.
4. Two analysts review the same version; one commits and the other receives a recoverable conflict with draft preserved.
5. Expire a session during investigation; protected data is removed and no further socket evidence arrives.
6. Disconnect updates and then reconnect; new incidents appear through refetch without duplicate rows or focus jumps.

## ML validation

Maintain dataset provenance, permitted-use records, hashes, preprocessing and split manifests. Split by campaign/speaker/source where needed to avoid leakage. Compare SMS-only, voice-only, rule-based fusion and learned fusion on the same labeled incident sequences. Report TP/FP/TN/FN, precision, recall, FPR, exact denominators, confidence intervals and calibration. Document null/missing-signal treatment and selected operating points. Do not tune on the held-out test set.

Evaluate unseen speakers, campaigns, languages and codecs where data supports it; mark untested groups rather than generalizing English results. Test base-floor policy separately from raw fusion calibration. Do not count standalone/pair dashboard records as independent labeled attacks. Keep historical V4 claims separate from reproduced results.

## Performance and accessibility

Measure named hardware, model versions, workload, warm/cold state, concurrency, throughput, failure rate, per-stage timings and p50/p95 total delay. Include audio collection time and any admission wait. Sustain the workload long enough to reveal resource growth. Verify configured overload behavior without hiding semantic detection loss.

Test 320, 768, 1024 and 1440 CSS-pixel widths, 200% zoom, keyboard-only navigation, visible focus, accessible names/live regions, non-color statuses, contrast and reduced motion. Use automated accessibility checks plus manual screen-reader investigation/review.

## Reporting and fixes

Report test commands, environment, passed/failed/not-run cases, reproducible bugs with severity and recommended fixes. Critical: unauthorized sensitive access/data loss; high: false-success persistence, broken risk invariants or key journeys; medium: recoverable functional/accessibility defects; low: minor presentation issues. Do not alter behavior solely to make tests pass or weaken a test without evidence it was wrong. Retest fixes and affected regressions. A model-quality failure remains a finding even if application tests pass.
