# KAVACH Security Audit and Hardening Workflow

## Scope and status

This is an audit procedure, not a completed assessment. Read PRD.md, ARCHITECTURE.md, DATABASE.md, API.md and AGENTS.md; inspect implementation and configuration without exposing secrets. Apply safe, justified fixes within the authorized task. Destructive data changes, new data collection or live telecom access require a separate approved change.

## Checks

| Boundary | Required checks |
| --- | --- |
| Accounts | Argon2id configuration, no default passwords, account disable/reset revokes sessions, generic login errors |
| Sessions | Random tokens, digests at rest, cookie flags, rotation/expiry, no browser-storage credentials |
| Authorization | All routes and sockets enforce active role/source; viewer cannot mutate; key cannot read incidents or another source's receipt |
| Browser mutations | CSRF and exact Origin, same-origin proxy, safe redirects, no permissive credentialed CORS |
| Inputs | JSON bounds, timezone/skew checks, finite scores, unknown fields rejected, notes safely rendered |
| Media | Manifest-only IDs, no traversal/SSRF/arbitrary upload, decoder byte/duration bounds, worker deadline |
| Model artifacts | Trusted source, license/provenance/checksum, read-only files, no user-supplied executable serialization |
| Database | Parameterized queries, least privileges, transaction/constraint integrity, immutable history, private network |
| Secrets | No committed values, build leakage, tokens in URLs or logs; versioned key rotation/recovery |
| Privacy | No raw SMS/audio/transcript or sensitive entities in evidence/logs/traces; redaction treated as imperfect |
| Abuse | Login/ingestion/read limits, bounded inference and socket buffers, conservative cache-outage behavior |
| Audit | Mutation rollback on audit failure, HMAC verification, protected key access, no deletion-proof overclaim |
| Operations | TLS, non-root runtime where practical, limited mounts, backups/retention, restore checks |
| Dependencies | Lockfiles, known advisories, supported versions, no unnecessary cloud/telecom SDKs |

## KAVACH-specific abuse cases

Attempt cross-subscriber linkage, forged source identity, changed-payload duplicate IDs, concurrent pair creation, review replay with altered note, stale review overwrite, synthetic-only risk escalation, missing-signal zero filling and malicious audio references. Test session expiry during a live stream. Verify real-data prohibition in seeds/simulator and no hosted inference calls.

## Remediation and verification

Prioritize exploitable critical/high findings. Reproduce safely on development/staging, implement a minimal compatible fix, add a regression test, and rerun affected checks. Do not hide errors, bypass validation, disable monitoring, or replace authentication simply to clear findings. Document medium/low items with impact and a concrete follow-up.

## Report

For each finding provide severity, affected boundary/files, evidence without secrets, impact, fix/status and verification. Include tests actually run, residual risks, manual checks and deployment scope. A clean dependency scan alone is not a security approval; legal authorization/privacy review for a pilot is a separate gate.
