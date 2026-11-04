# M3 Ingestion, Simulator and Security Acceptance Report (M3.4)

This is a dated execution report from 4 November 2026. It covers the M3 backend on branch `backend`: authenticated ingestion and PostgreSQL idempotency (M3.1), Redis candidate state, limits and resilience (M3.2), and the controlled simulator (M3.3). It applies [SECURITY_AUDIT.md](SECURITY_AUDIT.md), [TESTING_QA.md](TESTING_QA.md) and [DEFINITION_OF_DONE.md](DEFINITION_OF_DONE.md) to the code itself, not to earlier reports. Every result below comes from runs made during this audit. "Fixed" means fixed in the working tree and covered by tests; GitHub Actions has not run these changes yet.

## Baseline

| Item | Evidence |
| --- | --- |
| Commit audited | `bf403a8` "feat: add controlled synthetic simulator and scenario catalog" (`backend` = `origin/backend`, clean tree) |
| GitHub Actions on `bf403a8` | run 41879325247: "Backend tests and lint" success (17:40:04Z), "Backend integration (PostgreSQL and Redis)" success (17:41:23Z), read from the public GitHub API |
| Local re-run before any change | integration 297 passed on a fresh disposable stack |
| Environment | macOS arm64, Docker, `deployment/compose.dev.yml` (PostgreSQL 17.11, Redis 7.4.12, digest-pinned), Python 3.12.13, Uvicorn 0.54.0; existing `backend/.venv` (Ruff 0.17.3) and fresh environments from `backend/uv.lock` (Ruff 0.17.2) |
| Dependencies | unchanged (40 lock entries); no package added |

## Findings

Each finding was reproduced against the real stack before it was handled.

| ID | Severity | Finding | Evidence | Status |
| --- | --- | --- | --- | --- |
| M34-M1 | Medium | **Forwarded headers decided the throttle identity.** The documented launch command left Uvicorn's `proxy_headers` on, and by default Uvicorn trusts `X-Forwarded-For` from `127.0.0.1`/`::1` and rewrites the client address before the app runs. Any process on the host could therefore rotate its apparent IP past the per-IP invalid-key ceiling, the login IP ceiling and the per-account+IP login limit. TD-14 and M2 L-4 said the header was ignored. That holds only for the application in isolation (TestClient), not for the server as launched. | Real Uvicorn with default flags: 31 invalid keys with rotating `X-Forwarded-For` → 31 × 401, never 429, 31 separate counters, and a valid key from the same host was not blocked. | **Mitigated**: README launch now requires `--no-proxy-headers` (or `--forwarded-allow-ips` set to the real proxy only). Real-server tests pin both behaviors. Same probe with the flag → 30 × 401 then 429. *Not enforced in code*: the app cannot see the original peer once Uvicorn rewrites it, so the deployment (M11) must keep the flag. |
| M34-M2 | Medium | **A late identical replay re-indexed an expired candidate.** Re-indexing on replay used the event's *original* arrival time for the 40-minute horizon. A replay 45 minutes later re-added a candidate that can no longer match and refreshed the key's TTL, breaking the documented invariant. | `test_a_late_identical_replay_does_not_resurrect_an_expired_candidate` failed on `bf403a8` (stale member present). | **Fixed**: indexing uses the current time (`IngestionService._index(..., now)`). A replay inside the horizon still repairs a missing candidate (`test_a_prompt_identical_replay_still_repairs_a_missing_candidate`). |
| M34-M3 | Medium | **The 1,200-member cap can evict candidates that are still inside the horizon.** The cap equals one key's D08 rate × 40 minutes. The 60-second future-skew allowance already permits about 1,230 in-horizon events from one key, and several sources or keys for one subscriber multiply that. Eviction drops the oldest event-time members, emits `operational_event candidate.index_capped`, and `rebuild` cannot restore them (it re-applies the cap). | Code review plus `test_the_per_subscriber_cap_evicts_the_oldest` (M3.2). | **Open (TD-21)**: harmless today (no matching exists). M6 must treat Redis only as an accelerator and confirm or complete candidates from PostgreSQL (`ix_events_candidates`), or the owner must set a different cap. |
| M34-M4 | Medium | **Shared-IP lockout (TD-19).** After 30 invalid Bearer credentials from one IP in 15 minutes, every Bearer request from that IP got 429, including valid keys. One misbehaving client behind a NAT or shared egress, or anyone sharing a proxy address when trusted-proxy handling is absent, locked out all ingestors there for 15 minutes. | Real Uvicorn (`--no-proxy-headers`): 30 × 401, then a valid key → 429 `Retry-After: 900`. | **Fixed** (see "TD-19 fix"): the 30/IP/15-minute ceiling still counts and blocks rejected credentials, but a well-formed key from a blocked IP is still checked against PostgreSQL. It is admitted for that check if it authenticated within the last 24 hours (keyed marker), or else within a per-IP budget of 10 lookups per minute. Real Uvicorn: valid key → authenticated from the blocked IP. **Residual:** a key never used in the last 24 hours, presented while an attacker keeps spending the budget, waits up to 60 s per window. |
| M34-L1 | Low | Deeply nested JSON (for example 16,000 `[`, well under 32 KiB) raised `RecursionError` in `json.loads` and returned 500 instead of 422. Only an authenticated key holder could reach it. | Reproduced in-process (exception) and reasoned from the generic 500 handler. | **Fixed**: mapped to 422 `VALIDATION_ERROR`. Real server: 422. |
| M34-L2 | Low | If a retired `PAYLOAD_HMAC_KEYS` version is removed while events signed with it exist, a resubmission of such an event returns an unexplained 500. | `test_a_retired_payload_key_that_is_removed_fails_safely_and_is_reported` failed (no signal). | **Fixed (observability)**: logs `operational_event ingest.payload_key_missing`. It still returns 500 with nothing changed, because neither replay nor conflict can be decided. Operators must keep retired versions for the retention window (documented). |
| M34-L3 | Low | `CandidateIndex.near` can return members past the 40-minute horizon until the next write to that subscriber, because pruning happens only on writes. | Code review. | **Open (M6)**: DATABASE.md already requires candidate validation against event time and durable records; M6 must re-check eligibility. |
| M34-L4 | Low | Subscriber-key rotation starts a new candidate set: pseudonyms differ per key version, so events before and after a rotation are never candidates of each other. | `test_subscriber_key_rotation_starts_a_separate_candidate_set` pins the behavior. | **Open (TD-22)**: M6 design or a rotation procedure outside correlation windows. |
| M34-L5 | Low | No read limits: `GET /events/{id}` (keys) and `GET /simulator/scenarios` (admin) are not rate-limited; the D08 read limit (120/min/user) is not implemented anywhere. Receipt reads still pass the invalid-key throttle. | Code review. | Open; with the D08 read-limit work. |
| M34-L6 | Low | A Redis restart resets every counter (login failures, invalid keys, submission windows), because persistence is off by design. | Real restart probe. | Accepted for the MVP; documented. |
| M34-I1 | Info | Exactly-once processing is not guaranteed. A lost commit acknowledgement returns 503 although the event was stored, and a same-ID retry returns 200 with the original receipt. Storage is idempotent per `(source, event_id)`; delivery is the client's at-least-once retry. | `test_an_ambiguous_commit_is_resolved_by_retrying_the_same_event_id`. | As documented in API.md. |
| M34-I2 | Info | `python -m kavach.simulator run --key ...` is refused, but argparse echoes the stray value to the operator's stderr. | Probe. | Accepted: the value never reaches the server; the operator typed it into their own shell. |
| M34-I3 | Info | `candidates rebuild` selects by `event_time` without a leading index (sequential scan). | Code review. | Accepted at MVP size; operator-only command. |

Carried from M2 (unchanged): L-5 (a 401 does not clear a stale cookie); L-7 (the CLI operator check is attribution, not a boundary); I-1 (audit HMAC detects modification, not deletion; the runtime role holds the signing key and could forge records; audit logs are not immutable). M2 L-4 is superseded by M34-M1.

**No critical or high findings were identified.**

## Acceptance matrix

Results are from the final working tree. Tests named "M3.x" already existed and were re-run; "M3.4" tests are new.

### A. Ingestion and PostgreSQL — PASS

| Requirement | Evidence | Result |
| --- | --- | --- |
| Authenticated SMS and call ingestion | M3.1 creation tests; simulator S01–S07 against real Uvicorn | Pass |
| Request size and schema validation | 413 above 32 KiB (real server); unknown fields, bad timestamps and phone-like tokens → 422 without echo (M3.1); deep JSON → 422 (M3.4) | Pass |
| Source scope | own-source only (M3.1); forged source S11 → 403, nothing stored; partner key against the catalog → run aborted after 1 request | Pass |
| Subscriber privacy | only HMAC digests stored; privacy scans of DB, Redis, logs and runner output (M3.1–M3.3); real server log: no key, text, token or event ID | Pass |
| Receipts and recovery | `GET /events/{id}` own-source only, same 404 otherwise; runner verifies every stored receipt | Pass |
| 201 / 200 / 409 | M3.1 tests; S08, S09 real server | Pass |
| Concurrent identical and conflicting submissions | 8-thread tests: exactly one row (M3.1) | Pass |
| HMAC across key versions | rotation keeps replay (200), conflict (409) and new events on v2 (M3.4); missing version → 500 + operational event | Pass (with M34-L2) |
| Audit atomicity | failed audit write → 500, nothing stored, retry 201 (M3.1); one `event.ingest` audit per stored event (M3.3) | Pass |
| Database failure and ambiguous commit | DB down → 503 nothing stored (M3.1, real stop); lost commit acknowledgement → 503, retry → 200 replay, one row (M3.4) | Pass |
| No raw content persisted | M3.1 privacy test; M3.3 full-catalog scan | Pass |

### B. Redis and rate limiting

| Requirement | Evidence | Verdict |
| --- | --- | --- |
| 30 submissions/min/key, atomic and shared | two OS processes capped at exactly 30 (M3.2); real server 30 accepted then 429 `Retry-After: 59` | **PASS** |
| Invalid-key throttle 30/IP/15 min with refunds | M3.2 tests; 11 TD-19 tests (`test_bearer_lockout.py`); real server: 30 × 401, then 10 bounded lookups, then 429; a recently valid key still authenticates from the blocked IP | **CONDITIONAL**: correct only with `--no-proxy-headers` (M34-M1); the 30-attempt ceiling value is still the owner's to confirm; cold-key residual (M34-M4) |
| Candidate window (30 min) and lateness (10 min) | inclusive 30-minute boundary, 40-minute horizon, out-of-order, duplicates, two processes (M3.2); S05–S07, S10 on real server: 0 mismatches | **Candidate correctness: CONDITIONAL**: correct for current use; M34-M2 fixed; M34-M3, M34-L3 and M34-L4 must be handled by M6; D05 provisional |
| TTL, rebuild, replay repair, restart, hung, unavailable | TTL 40 min; real Redis restart emptied the index and `candidates rebuild` restored 17 in-horizon events (0 mismatches); prompt replay repairs; paused Redis → 503 in 0.51 s; refused → 503; failure after commit → success + deferred index | **TTL/recovery: PASS** |
| PostgreSQL authoritative, no conclusions | candidate proximity creates no pair incident (M3.2, M3.3); 16 events → 16 standalone incidents, tier `unknown`, no scores | Pass |

### C. Simulator and catalog — PASS

| Requirement | Evidence | Result |
| --- | --- | --- |
| S01–S12 | Real Uvicorn on a disposable stack: **12/12 passed, 20 submissions**; 16 events stored; forged source and unapproved audio stored nothing; 0 candidate mismatches | Pass |
| Determinism | two dry runs with the same seed and run ID were byte-identical; a same-seed same-ID rerun replays (M3.3 integration) | Pass |
| Loopback only | external target refused before sending (exit 2); 11 refused URL forms (unit) | Pass |
| Key handling | environment or stdin only; `--key` rejected; key never printed (unit and integration scans) | Pass |
| Pacing and 429 | client pacing ≤ 30/min; real-server 429 retried after `Retry-After` (M3.3) | Pass |
| No score fabrication | every receipt `unavailable` with stage warnings; DB scores null; tier `unknown` | Pass |
| Admin-only catalog | real server: admin 200 (`no-store`, 12 scenarios, `samples: []`), anonymous 401, cookie + Bearer 401; viewer/analyst 403 and deactivated admin 401 (M3.3) | Pass |
| No sensitive leakage | runner output, logs, Redis and DB scans (M3.3); real server log clean | Pass |
| Audio manifest inactive | any `audio_reference` → 422 (S12); `samples` empty | Pass |

### D. Security and privacy — CONDITIONAL

| Area | Result |
| --- | --- |
| Unauthorized access, source crossing | Pass (401 uniform for unknown/expired/revoked keys; 403 for other sources; same 404 for other-source receipts) |
| Cookie plus Bearer | Pass (401 `MIXED_CREDENTIALS` on events and catalog) |
| Key expiry and revocation | Pass (M3.1; revoked key stops a simulator run after one request, M3.3) |
| Redaction in logs, receipts, errors | Pass (scans above; telemetry carries event, reason and request ID only) |
| Audit | Pass with the I-1 limitations (not immutable) |
| Proxy headers and shared-IP DoS | Conditional: M34-M1 mitigated by the launch flag only; M34-M4 fixed for valid keys, with the cold-key residual |
| Rate-limit bypass, exhaustion, replay | Pass for per-key limits across processes and replays counted; read limits absent (M34-L5); several keys per source multiply capacity (operator-controlled) |
| Configuration failures | Pass (incomplete auth or ingestion config → 503; pilot refuses to start without it, M2/M3.1) |
| Operator and simulator privileges | Pass (admin actor for key lifecycle; simulator is an ordinary key-scoped client with no DB/Redis access) |

### E. Resilience and deadlines — PASS

30-second deadline aborts before commit and a retry succeeds (M3.2); remaining time is enforced as `statement_timeout`; Redis down before ingestion → 503, nothing stored; Redis failure after commit → 201 and `candidate.index_deferred`, repaired by replay or rebuild; PostgreSQL stopped → 503, restarted → the same event ID 201 then 200 replay (real); ambiguous commit resolved by retry (M3.4). No guaranteed delivery or exactly-once processing is claimed.

## TD-19 fix (owner-requested, 4 November 2026)

| Rule | Behavior |
| --- | --- |
| Rejected-credential ceiling | Unchanged: each presented key reserves an attempt per client IP; a valid key refunds it; 30 rejections per 15 minutes block the IP. |
| Valid key from a blocked IP | Not denied because of others' failures. A well-formed key is still checked against PostgreSQL (revocation, expiry and source scope enforced as always) if it carries a recently-valid marker or the IP's lookup budget allows. |
| Recently-valid marker | `ratelimit:bearer:valid:{HMAC(presented key)}`, written after any successful authentication, TTL 24 h. It never grants access, only a lookup. Any failed check deletes it, so a revoked or expired key gets one more lookup at most. |
| Lookup budget for a blocked IP | `ratelimit:bearer:lookup:{HMAC(IP)}`: 10 lookups per 60 s for keys without a marker; beyond it 429 with `Retry-After` ≤ 60 s and no database access. Malformed credentials get 429 without a lookup or budget. |
| Database load from a blocked IP | At most 10 lookups per minute for unknown keys, plus legitimate keys' own checks (real server: 30 + 10 lookups, then only 429s). |
| Refunds | Only a reservation that was actually taken is refunded, so a valid key cannot lower a blocked IP's counter. |
| Redis failure | Fails closed (503 `DEPENDENCY_UNAVAILABLE`, no lookup) at reservation and at blocked-IP admission. Writing or deleting the marker is best effort: a failure only makes a key "cold" or costs one extra lookup. |
| Processes | All state is in Redis, so separate backend processes share the ceiling, the budget and the markers (tested with two spawned processes). |
| Responses | Unchanged codes: 401 `INVALID_CREDENTIALS` after a lookup, 429 `RATE_LIMITED` without one, 503 when Redis cannot confirm. No key material, IP or token in Redis names, values, logs or errors (tested). |

Tests: `backend/tests/integration/test_bearer_lockout.py` (11). They cover:

- valid keys after and before an attack;
- bounded lookups and malformed tokens;
- revoked and expired keys;
- scope and the 30/min limit on a blocked IP;
- partial and full Redis outages;
- two spawned processes sharing the ceiling and budget;
- one process's success admitting the key in another;
- Redis privacy.

The M3.2 throttle test and the M3.4 forwarded-header tests were updated from "blocked means 429 for every key" to the new rule. A unit test covers the new Redis key names.

## Verification commands and results (final working tree)

| Check | Result |
| --- | --- |
| `backend/.venv/bin/python -m pytest backend/tests` | **267 passed**, 319 deselected, 1 warning (TD-04) |
| `backend/.venv/bin/python -m pytest backend/tests -m integration` | **319 passed** (11 M3.4 acceptance + 11 TD-19 tests), 267 deselected, 1 warning |
| `ruff check backend` / `ruff format --check backend` | passed / 78 files formatted (Ruff 0.17.3 and 0.17.2) |
| Fresh locked environment (after the TD-19 fix) | `uv lock --check` passed; `uv sync --locked`; pytest 267 passed; Ruff 0.17.2 clean; migrations at head, `alembic check` "No new upgrade operations detected"; integration 319 passed; TD-19 tests passed in two further runs; containers and volumes removed |
| CI replay before the TD-19 fix (fresh stack) | migrations applied twice (2 then 0 revisions), integration 308 passed |
| Migrations | none added |

## Decisions (current implementation vs pending)

| Item | Implemented now | Status | Recommendation |
| --- | --- | --- | --- |
| D05 window/lateness | 30-minute inclusive window, 10-minute lateness, 40-minute candidate horizon (index only; no matching) | **Provisional (TD-20)** | Approve 30 min / 10 min as the *initial, versioned* policy for M6 so matching can be built and evaluated; revisit with M10 data. Record the policy version in assessments. |
| D08 limits | 30 submissions/min/key (sliding window on Redis time, replays counted); 30 s deadline | **Provisional** | Approve both for the simulator MVP. Treat 30 s as an upper bound to be tightened after M4/M5 latency is measured. Implement the read limits (120/min/user) before any multi-user pilot. |
| TD-16 admin browser submission | Not implemented; catalog read is admin-only; submissions use a `simulator`-scoped key | Deferred | Implement with the M8 simulator UI; decide whether admin submissions share the `simulator` source namespace with the key. |
| TD-17 audio samples | Contract documented; no manifest read; all references → 422 | Deferred | Approve a licensed synthetic sample list together with D04 voice data, before M5. |
| TD-18 inference admission | No inference; `MAX_INFLIGHT_ANALYSES` absent | Deferred | **Required in the same change that first wires a model into ingestion (M4 runtime)**: 2 concurrent analyses, 429 `CAPACITY_EXCEEDED`, a killable worker so a timed-out inference cannot commit. |
| TD-19 invalid-key ceiling | 30 rejected credentials per IP per 15 min; valid keys are no longer locked out (owner-requested fix, below) | Lockout **fixed**; the numeric ceiling (30/15 min), the lookup budget (10/min) and the 24 h marker are implementation choices awaiting owner confirmation | Confirm the three values; revisit with trusted-proxy handling (M11) |
| TD-14 trusted proxies | `--no-proxy-headers` required by README | Open until M11 | Make the launch flags part of the deployment artifact and add a startup check in M11; never trust forwarded headers from a broad range. |
| TD-20 | as D05 | Pending | as D05 |

## Verdict

**M3 acceptance: CONDITIONAL PASS.** Ingestion, idempotency, privacy, audit atomicity, resilience, the simulator and the admin catalog pass on the real stack. Three medium defects were found and fixed (including the TD-19 lockout), and two low ones were fixed. The conditions:

1. The owner confirms or replaces D05, D08 and the TD-19 values (30 per 15 min, 10 lookups/min, 24 h marker). They stay provisional until then.
2. Every launch keeps `--no-proxy-headers` (or a correctly scoped `--forwarded-allow-ips`) until M11 encodes it (M34-M1).
3. M6 treats the Redis index as an accelerator only: PostgreSQL confirms candidates, eligibility is re-checked, and cap eviction and key rotation are handled (M34-M3, M34-L3, M34-L4).
4. GitHub Actions passes both jobs on the commit containing these changes.

## M4 prerequisites

- **D04 approved**: SMS dataset sources, licenses and permitted use, label provenance, language coverage and personal-data handling. Only licensed or synthetic data; record hashes.
- **Package approval** for the training/runtime stack (scikit-learn and its pinned dependencies) under D02, with lockfile update and an advisory check.
- **Experiment layout** under `experiments/`: dataset manifest, leakage-resistant split (by campaign, template or sender where the data allows), held-out set frozen before training, fixed seeds.
- **Evaluation contract**: TP/FP/TN/FN, precision, recall, FPR, exact denominators and confidence intervals on the held-out split; English first, Hindi/Hinglish labeled experimental; no V4 figures as targets or results.
- **Fixture separation**: the simulator catalog texts (S01–S12) are demonstration fixtures and must not be used for training or evaluation.
- **Artifact handling**: checksummed artifact and manifest under an operator-controlled `MODEL_DIR`/`MODEL_MANIFEST_PATH`; never deserialize uploads; a missing or mismatched artifact keeps the stage `unavailable`.
- **Runtime wiring** (when the adapter joins ingestion): TD-18 admission control and a killable worker in the same change; adapter output = score, reason codes, model version, duration; replays keep the original result (no recomputation).
