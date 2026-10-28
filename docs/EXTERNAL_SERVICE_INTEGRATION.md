# KAVACH External Service Integration Workflow

## Current scope

The MVP has no required telecom API, hosted speech/LLM API, notification provider or webhook. PostgreSQL, Redis and local model artifacts are covered by ARCHITECTURE.md. This file defines future execution steps; no provider has been integrated.

## Required inputs

Before execution, identify the approved service/purpose, official API documentation/version, permitted data, environment, operations, credentials, budget and data-retention boundary. A live SMSC/SIP/recording feed also requires explicit authorized access and an approved product-scope change; an API key alone does not establish permission to process communications.

## Implementation procedure

1. Read API.md, ARCHITECTURE.md, DATABASE.md and AGENTS.md. Inspect existing adapters and dependencies.
2. Update approved contracts with required operations, credentials, source identity mapping, persistence/retention changes, timeout budget and failure semantics before coding.
3. Implement a narrow server-side adapter with schema validation for requests/responses and bounded payloads/timeouts. Keep secrets out of frontend builds and logs.
4. Retry only safe reads or operations protected by provider-supported idempotency. Honor rate limits/Retry-After; cap retries and use backoff with jitter.
5. If webhooks are required, verify provider signatures on original bytes, enforce timestamp/replay checks, deduplicate event IDs, and acknowledge only after the defined durable boundary. Do not invent an HMAC format for a provider.
6. Prevent duplicate side effects, SSRF, arbitrary URL fetching and cross-source subscriber association. Never treat provider failure as a low-risk result.
7. Add operational status and sanitized logs; provide a disable/revoke procedure.

## Verification and report

Test successful calls, malformed output, denied credentials, timeout, rate limit, retry exhaustion, duplicate requests and invalid/replayed webhooks where applicable. Use sandbox/test accounts and synthetic data. Report actual provider/environment, changed files, variable names, tests/results, manual setup and limits. No production transmissions or external provisioning occur merely because this workflow exists.
