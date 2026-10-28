# KAVACH Coding Agent Rules

## Scope and source of truth

Inspect the existing repository, applicable instructions, relevant code, dependency manifests, tests and working-tree changes before editing. Read PRD.md, DESIGN.md, ARCHITECTURE.md, DATABASE.md and API.md before planning implementation. Follow IMPLEMENTATION_PLAN.md and the relevant workflow document. The supplied handbook is contextual source material; the Markdown specifications contain explicitly proposed details, not automatic approval.

Only implement the task currently authorized by the user. Documentation creation does not authorize executing all workflow documents. Resolve relevant pending PRD decisions before dependent implementation; do independent authorized work while a decision is pending. If sources conflict, identify the conflict and obtain a product decision instead of silently expanding scope. Do not claim unverified V4 metrics, live telecom access, deployment, test success or legal compliance.

## Inspect and preserve

- Reuse existing code and patterns before creating abstractions. Keep changes focused; no unrelated formatting, rewrites or generated clutter.
- Preserve CONNECTION_TEST.md and unrelated user files. Never overwrite uncommitted work or force-reset the repository.
- Do not add public signup, tenant management, live call capture, external LLMs, billing, intervention automation, arbitrary uploads or other excluded features.
- Never substitute mock predictions for runtime models. Test doubles must be clearly isolated from runtime builds. Missing artifacts must produce unavailable/degraded behavior.

## Code quality and structure

Follow the responsibility boundaries in ARCHITECTURE.md. Python modules/functions use snake_case; Python classes and React components use PascalCase; TypeScript variables/functions use camelCase; wire/database fields use snake_case. Keep route handlers thin, business rules in services/domain modules, and database access in repositories. `backend/models/` holds inference adapters; ORM entities belong in `backend/db/`.

Prefer small explicit functions and typed contracts. TypeScript strict mode; no unexplained `any`, unsafe cast or ignored type error. Python public service boundaries and model results require type annotations and validated DTOs. Represent missing results explicitly; never coerce null scores to zero. Inject clocks/model adapters where deterministic tests need them; do not build a general plugin framework.

## UI consistency and reuse

Use DESIGN.md tokens and shared components. Reuse fields, badges, evidence panels, errors and layout primitives. Implement pending/empty/stale/error/forbidden states as part of each feature. Preserve keyboard focus and unsaved review drafts. No raw communications in browser storage or URLs. Avoid dependency-heavy charting for evidence already clear in text/tables.

## Dependencies and configuration

Use the approved stack, supported compatible versions and lockfiles. Add a dependency only for a concrete requirement after checking existing facilities; record why. Do not opportunistically upgrade the entire stack. Verify model licensing/provenance and package advisories before release. Use documented `.env.example` names with placeholders only; validate required config at startup. Keep model binaries, credentials, real datasets and local environments out of Git.

## Security and secrets

Never hardcode, print, commit or return credentials, session tokens, passwords, keys, raw messages, transcripts or audio. Do not send communication contents to an external service without an approved integration/data decision. Enforce role/scope/ownership server-side on every route and WebSocket, including inactive-account checks. Preserve CSRF and Origin protection. Use maintained password hashing and cryptographically random sessions; never invent encryption.

Treat all incoming text, audio, paths, URLs and model artifacts as untrusted. Resolve only manifest-approved sample IDs; no arbitrary file/URL fetching. Use parameterized SQL, bounded parsing, safe text rendering and allowlisted structured persistence. Do not weaken validation or permissions to make a demo or test pass.

## Database and API discipline

Schema changes require migrations and an approved contract change. Keep idempotency, incident/review changes and audit writes transactional. Do not mutate historical assessments/reviews; append versions. Honor same-source event IDs, subscriber match boundaries, event-time eligibility and base-risk preservation. Redis is never the authoritative review or idempotency store. Browser code must not connect directly to PostgreSQL or Redis.

Follow API.md field names, error envelopes, pagination and authorization. Never add arbitrary JSON metadata as a shortcut around the evidence schema. Coordinate database, API, frontend and documentation changes together when contracts change.

## Error handling and observability

Distinguish bad input, unauthorized access, conflicts, saturation, missing model stages and dependency failure. No blanket catch-and-success behavior. Return safe messages/request IDs and log only operational metadata. A review success requires a committed record. A model timeout must not leave unbounded inference running. Measure stage and total latency separately. Do not log raw payloads even at debug level.

## Testing and verification

Test behavior and security boundaries, not implementation trivia. Run relevant unit/integration tests and lint/type/build checks for changed areas. Real PostgreSQL/Redis integration tests must cover constraints, races and rollback. Critical browser paths include login, triage, evidence, review, degraded status and simulator permissions. Test benign synthetic voice, human scam voice, unrelated events, missing signals, lateness and duplicate submissions.

Keep model evaluation separate from UI fixtures; avoid train/test leakage and report denominators. Never claim performance or accuracy from a screenshot or hardcoded score. Record exact commands and actual outcomes; mark unavailable checks as not run with the reason. Do not mask failures by removing tests or changing production behavior solely to satisfy them.

## Documentation and Git

Update the source-of-truth document when an approved decision or behavior changes. Keep workflow files as procedures; put dated execution results in the task report rather than falsely marking a procedure complete. Explain changed files, verification and remaining limitations concisely.

Inspect diffs before finishing. Do not commit/push/deploy or contact external parties unless the task authorizes it. Never rewrite history, delete production data or apply destructive migrations without explicit authorization and a recovery plan. Honor any existing repository conventions. Keep documentation-only tasks free of application code, package installations and infrastructure changes.
