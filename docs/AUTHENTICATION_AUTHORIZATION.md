# KAVACH Authentication and Authorization Workflow

## Preconditions

Read PRD.md, ARCHITECTURE.md, DATABASE.md, API.md and AGENTS.md. Resolve D03 before choosing implementation libraries. Inspect existing identity code before changing it. The approved proposal is provisioned accounts, opaque server-side sessions and separate source-scoped ingestion keys; no public signup or email reset service.

## Tasks

1. Implement operator provisioning/deactivation/reset with audited changes and no hardcoded credentials. Hash passwords with maintained Argon2id tooling; enforce a documented provisioned-password policy and input bounds.
2. Generate cryptographically random session/key values; persist digests only. Rotate browser sessions at login, apply idle/absolute expiry and revoke on logout, account disable or password reset.
3. Configure HttpOnly, host-only, SameSite cookies and Secure in shared environments; validate Origin and CSRF on browser mutations. Keep credentials out of URLs and browser storage.
4. Implement login/session/logout and protected frontend routes. Frontend hiding is convenience; server authorization remains mandatory.
5. Enforce viewer read-only, analyst review, admin simulator/operator capabilities and ingestor own-source submission/receipts. Reject mixed credential mechanisms.
6. Revalidate active users/roles at requests and WebSocket intervals; clear evidence and close sockets on expiry. No role can overwrite model scores or delete reviews through the API.
7. Apply login throttles without exposing whether an account exists. Return safe 401/403/404 states and prevent redirect injection.

## Required tests

Exercise all endpoint-role pairs, wrong/inactive credentials, session fixation, expired/revoked cookies, idle timeout, logout, role change, CSRF/Origin denial, key expiry/source mismatch, another source's receipt, WebSocket expiry and login rate limits. Verify password/token values never reach logs or responses. Test provisioning/reset failure rollback and old-session revocation.

## Report

Describe actual login/logout/session flow, protected resources and permissions, files changed, tests/results, environment settings and unresolved security issues. Do not replace working authentication without an approved reason or infer that OIDC is required for the local MVP.
