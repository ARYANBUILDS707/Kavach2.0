# KAVACH Product Requirements

## Current implementation authorization

The user has authorized repository setup and a Python 3.12 FastAPI backend foundation: liveness routes, event input schemas, environment settings, pytest and Ruff. This resolves only the D01/D02 portions needed for that bounded task; remaining product, authentication, persistence, model and deployment decisions retain their original status. No frontend, inference or telecom capabilities are implied. See the root README for actual implementation and verification status.

## Status and authority

Status: proposed implementation specification, awaiting the decisions below. No application, dataset, model, integration, benchmark, or production readiness has been verified.

Source: `KAVACH_Complete_Project_Documentation.docx`, prepared 27 October 2026, supplied from the user's Downloads directory. Section references below refer to that handbook. The underlying V1–V4 PDFs were not provided or independently inspected for this task.

This document defines product scope. [DESIGN.md](DESIGN.md), [ARCHITECTURE.md](ARCHITECTURE.md), [DATABASE.md](DATABASE.md), and [API.md](API.md) define implementation contracts. [AGENTS.md](AGENTS.md) governs changes. [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) orders development. The remaining workflow documents are instructions for future execution, not reports of completed work.

## Problem and value proposition

Fraud can span a deceptive SMS followed by a persuasive call. Independent detectors may miss a sequence whose individual signals are borderline. KAVACH assembles authorized SMS and voice evidence into an explainable risk assessment for human review. Its differentiating hypothesis is that continuous cross-channel evidence improves detection on unseen incidents without excessive false positives. This hypothesis must be tested, not presented as established fact. [Source §§1–3, 15]

Synthetic speech is not synonymous with fraud. A human scam caller may have a low synthesis score; a legitimate IVR may have a high one. An OTP mention alone is not sufficient evidence of fraud.

## Users and roles

The MVP is a single-organization, controlled research/demo deployment. It does not provide customer-facing mobile monitoring.

| Role | Purpose | Allowed operations |
| --- | --- | --- |
| Viewer | Security reviewer or judge | Read incident evidence and system health |
| Analyst | Fraud operations investigator | Viewer access; append incident reviews |
| Admin | Deployment operator | Analyst access; run controlled simulator; provision/deactivate accounts through an operator command |
| Ingestor | Machine identity for authorized simulator | Submit events and read own submission receipts; no dashboard or incident access |
| Unauthenticated | No established identity | Login and minimal liveness only |

Roles are proposed under D03. No role can alter model scores, erase review history through the UI, block calls, freeze accounts, or silently retrain models. All authorized dashboard users share the organization's incident scope. Multiple organizations are outside MVP scope.

## Core journeys and user stories

1. **Controlled demonstration:** As an admin, I select a documented synthetic scenario and send its SMS/call events. I see real processing results or explicit failure; repeated submission does not create duplicate events.
2. **Triage:** As an analyst, I open the incident feed, filter by tier, review status, kind, and event time, and distinguish complete, partial, and unavailable analysis.
3. **Investigation:** As a viewer, I open a timeline showing event times, arrival times, independent scores, subscriber-match evidence, time difference, context reasons, and model/policy versions. I can understand why a link was accepted or rejected.
4. **Review:** As an analyst, I submit `true_fraud`, `false_alarm`, or `needs_investigation` with an optional bounded note. The saved decision includes my identity, time, and assessment revision. A concurrent update does not silently overwrite another review.
5. **Degraded operation:** As an analyst, I see when transcription, models, Redis, or connectivity are unavailable. Missing evidence is never represented as zero risk or a successful analysis.
6. **Evaluation:** As a researcher, I run reproducible offline comparisons on the same held-out incident population and record confusion matrices, calibration, timings, dataset provenance, and limitations.

## Functional requirements

| ID | Requirement | Acceptance condition |
| --- | --- | --- |
| FR01 | Accept authenticated SMS JSON and call metadata with an allowlisted sample reference | Validate identity, size, event ID, timestamp, source, and permissions; reject arbitrary paths/URLs |
| FR02 | Deduplicate events | Same source/event ID and canonical payload returns original receipt; changed payload returns conflict |
| FR03 | Score SMS with a versioned TF-IDF classifier | Return score, structured reason codes, model version, duration, and availability; raw text is not stored |
| FR04 | Analyze call audio locally | Separate synthesis likelihood from semantic fraud intent; expose missing STT/acoustic analysis explicitly |
| FR05 | Correlate eligible evidence | Require authorized shared subscriber identity, event-time eligibility, and contextual evidence; never link on brand/time alone |
| FR06 | Use continuous fusion inputs | Do not require both independent scores to cross alert thresholds before considering a pair |
| FR07 | Preserve independent evidence | Expired, absent, or unrelated correlations cannot reduce independently established risk |
| FR08 | Generate explainable incidents | Store standalone and qualifying pair assessments with versioned structured evidence; distinguish these incident kinds |
| FR09 | Support triage and investigation | Feed and detail reflect backend records; stable pagination and durable review history |
| FR10 | Record reviews transactionally | Append-only review, optimistic revision check, idempotent retry, attributable audit entry |
| FR11 | Refresh dashboard | WebSocket invalidations plus REST refetch and polling fallback; reconnect reconciles state |
| FR12 | Report health | Authenticated dependency/model status, degraded reasons, last successful refresh; no credentials or internals in public health |
| FR13 | Evaluate reproducibly | Same population for SMS-only, voice-only, rule fusion, learned fusion; no train/test campaign or speaker leakage |
| FR14 | Enforce privacy and security | Server-side RBAC, bounded inputs, restricted logs, explicit retention, synthetic-only demo seeds |

### Incident and score semantics

Proposed under D05: each analyzed event has one standalone incident. Each eligible SMS/call pair has one separate pair incident. The pair links its constituent events; it does not delete, merge, or relabel standalone incidents. Detail views link related incidents. Feed filters expose `standalone` and `pair`; counts are labeled **incident records**, never unique attacks or subscribers. Evaluation operates on a separately labeled sequence population, not dashboard row counts.

Maintain separate `sms_score`, `voice_intent_score`, and `synthesis_score`. Unavailable scores are null with reasons. Base risk is the maximum available SMS/voice-intent score, never synthesis alone. The proposed safety policy uses the maximum of base risk and available pair-fusion score; it is a policy score, not a calibrated probability. Evaluate and version this proposal before approval. If neither base signal is available, tier is `unknown`. Missing fusion yields base-only, partial analysis.

## Pages and states

| Route | Screen | Required content and actions |
| --- | --- | --- |
| `/login` | Sign in | Credentials, generic rejection, pending submission, session expiry explanation |
| `/incidents` | Incident feed | Tier/status/kind/time filters, last update, pagination, degraded banner |
| `/incidents/:id` | Evidence and review | Timeline, signal availability, linkage reasons, versions, related incidents, review history/form |
| `/simulator` | Admin demo controls | Fixed scenarios and allowlisted samples; explicit synthetic-data label; event receipts |
| `/system` | System health | Database/Redis/model availability and operational limitations |

No separate marketing site, customer portal, billing page, account signup, settings console, or model-training UI is required.

All screens need first-load, empty, failed, and stale states. Feed empty copy distinguishes “No incidents received” from “No incidents match these filters.” Missing audio says “Audio analysis unavailable,” not “Safe.” Failed review keeps the draft in memory and provides retry; navigating away warns about an unsaved draft. Forbidden/not-found/session-expired states provide appropriate navigation without exposing protected evidence.

## Data and integrations

Store pseudonymous event metadata, bounded structured signal results, model versions, incident assessments, review history, sessions, and integrity-protected audit records. Raw SMS, transcripts, audio, telephone numbers, OTPs, URLs, and unredacted sender identifiers are not persisted by default. Allowlisted synthetic audio fixtures are a separate development asset, not uploaded communications. Features and pseudonymous identifiers remain sensitive. [Source §§10, 16]

Required internal dependencies: FastAPI, local ML models, Redis, a durable database, and React. No external fraud provider, telecom API, hosted LLM, SMS delivery service, webhook receiver, or MCP server is required by the source. Any future live feed requires a separate authorization and integration decision.

## Non-functional requirements

- Security: all evidence and write APIs require identity and server-side permission checks; TLS for shared environments; secrets remain server-side.
- Privacy: minimize persisted evidence; apply expiry and verify deletion; do not equate redaction/HMAC with anonymity or deletion-proof storage.
- Reliability: durable writes are transactional; a database failure cannot produce a successful receipt. Redis failure uses documented durable fallback with degraded status.
- Responsiveness: proposed UI target is p95 read response under 500 ms for 10,000 incident records at 5 concurrent users on documented hardware; validate, do not advertise before measurement.
- Processing: proposed bounded ingestion timeout is 30 seconds, with saturation rejection and explicit partial results. Report collection, queue/admission, inference, and total alert delay separately.
- Accessibility: target WCAG 2.2 AA; keyboard workflows, visible focus, non-color status labels, screen-reader announcements, reduced motion.
- Maintainability: versioned API/schema/model/policy contracts; repeatable local Compose startup and documented test commands.
- Recoverability: proposed daily encrypted backups, 24-hour recovery-point target and 4-hour recovery-time target for a future pilot; validate restore before pilot launch.

The 810 ms p95 buffer processing, approximately 120 streams/GPU, 91% recall, and cost figures in the handbook are reported historical claims. They are not acceptance evidence or guaranteed targets for this implementation.

## MVP and exclusions

MVP includes authorized synthetic ingestion, SMS and voice baselines, temporal/contextual correlation, continuous learned fusion, explainable incidents, analyst reviews, RBAC, health, local simulator, and offline evaluation. English is the proposed first evaluated language; Hindi/Hinglish results must be labeled experimental until separately tested.

Out of scope: live SMSC/SIP/SIP-REC integration, passive phone access, real-time carrier streaming, autonomous intervention, multi-tenancy, public signup, arbitrary audio upload, external notification delivery, online retraining, large-scale GPU orchestration, payment systems, and any claim of legal compliance certification.

## Success and release criteria

1. Demonstrate legitimate OTP plus family call, phishing plus human scam caller, benign synthetic IVR, unrelated close-timed events, out-of-order delivery, and missing signals with saved evidence.
2. Prove idempotency, permissions, same-subscriber matching, expiry, concurrency, and partial-failure behavior through automated tests.
3. Run a held-out matched-population ablation. Record TP/FP/TN/FN, precision, recall, FPR, confidence intervals, calibration, language/speaker coverage, and sample sizes. A demonstration is not proof of generalization.
4. Claim fusion improvement only if measured against independent baselines at a comparable operating point. If not demonstrated, ship only as an experimental prototype with that limitation visible.
5. Pass critical end-to-end workflows, accessibility checks, privacy leakage tests, and restore verification for the chosen deployment tier.
6. No open critical/high security findings; all release-blocking decisions resolved for the intended environment.

## Assumptions and decisions requiring owner approval

All proposed values below are design assumptions, not instructions found in the handbook. Recording them here does not approve them. Documentation can proceed; dependent implementation must resolve the relevant decision first.

| ID | Proposed decision | Approval needed before |
| --- | --- | --- |
| D01 | Single-organization local research MVP; synthetic or explicitly permitted datasets only | Application setup and data acquisition |
| D02 | React/TypeScript/Vite, Python/FastAPI, PostgreSQL/SQLAlchemy/Alembic, Redis, Compose; bounded synchronous ingestion | Dependency installation and schema implementation |
| D03 | Provisioned local accounts, Argon2id passwords, opaque server sessions; viewer/analyst/admin plus machine API keys | Authentication implementation |
| D04 | TF-IDF logistic SMS baseline; local Whisper-tiny; versioned acoustic/intent baselines; exact datasets, licensing and artifact provenance still required | Training, downloading artifacts, or claiming model readiness |
| D05 | 30-minute event window, 10-minute allowed lateness; standalone and pair incidents; base-risk floor policy described above | Correlation and policy implementation |
| D06 | Demo tier bands: low <0.40, medium 0.40–<0.70, high 0.70–<0.90, critical ≥0.90; unknown for no base evidence | Alert policy implementation; recalibrate before any pilot |
| D07 | Seven-day synthetic event/incident/review retention; 30-day security-audit retention with no evidence bodies; no raw communication retention | Persistence and deletion implementation; real-data policy needs separate review |
| D08 | Login 5 failures/15 minutes/account+IP; reads 120/minute/user; ingestion 30/minute/key; 2 concurrent analyses and 30-second deadline | Capacity/rate-limit implementation; load-test and revise |
| D09 | Light operational UI and tokens in DESIGN.md; English-first evaluation | UI implementation and public quality claims |
| D10 | Local Compose first; pilot hosting/provider, hardware, data region, operating authority and backup budget undecided | External provisioning or live pilot |

## Document map

1. [PRD.md](PRD.md)
2. [DESIGN.md](DESIGN.md)
3. [ARCHITECTURE.md](ARCHITECTURE.md)
4. [DATABASE.md](DATABASE.md)
5. [API.md](API.md)
6. [AGENTS.md](AGENTS.md)
7. [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
8. [PROJECT_SETUP.md](PROJECT_SETUP.md)
9. [FEATURE_DEVELOPMENT.md](FEATURE_DEVELOPMENT.md)
10. [BACKEND_DATABASE_CONNECTION.md](BACKEND_DATABASE_CONNECTION.md)
11. [AUTHENTICATION_AUTHORIZATION.md](AUTHENTICATION_AUTHORIZATION.md)
12. [MCP_CONNECTION.md](MCP_CONNECTION.md)
13. [EXTERNAL_SERVICE_INTEGRATION.md](EXTERNAL_SERVICE_INTEGRATION.md)
14. [TESTING_QA.md](TESTING_QA.md)
15. [DEBUGGING.md](DEBUGGING.md)
16. [SECURITY_AUDIT.md](SECURITY_AUDIT.md)
17. [CODE_REVIEW.md](CODE_REVIEW.md)
18. [DEPLOYMENT.md](DEPLOYMENT.md)
19. [MONITORING_MAINTENANCE.md](MONITORING_MAINTENANCE.md)
20. [FINAL_PRODUCTION_AUDIT.md](FINAL_PRODUCTION_AUDIT.md)
21. [MASTER_DEVELOPMENT_PLAN.md](MASTER_DEVELOPMENT_PLAN.md)
22. [GIT_WORKFLOW.md](GIT_WORKFLOW.md)
23. [MILESTONE_TRACKER.md](MILESTONE_TRACKER.md)
24. [DEFINITION_OF_DONE.md](DEFINITION_OF_DONE.md)
25. [INTEGRATION_PLAN.md](INTEGRATION_PLAN.md)
26. [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)
