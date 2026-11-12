# Proposal C-15: A Public Real-Time SMS Analyzer

**Status: PROPOSED. Not approved, not implemented, not enabled anywhere.** This document is the separate design and authorization proposal that [PUBLIC_SITE_DESIGN.md](PUBLIC_SITE_DESIGN.md) and the owner's 13 Nov 2026 instruction call for. It is not legal advice.

## Why this needs its own decision

| Existing decision | What it allows | Why it does not cover a public analyzer |
| --- | --- | --- |
| C-12 D | The worker stays disabled until the M4-Q evaluation gives GO (or an approved CONDITIONAL) | M4-Q is **NOT READY** (collected spam 19 of minimum 25; synthetic benign 1 of minimum 16) |
| C-13 | Local-only experimental inference on **fictional** messages | A public analyzer processes strangers' messages, which may be real and personal, on a hosted service |
| C-14 | A login-free site that shows **recorded** examples | It deliberately has no input box and no live analysis |

Until C-15 is approved, the public site shows only recorded examples, and the hosted configuration cannot run the worker (the C-13 gate refuses it outside `APP_ENV=development` on a loopback origin).

## What would be offered

A page where a visitor pastes one SMS (the existing limit is 4,096 characters) and receives the model's prediction (legitimate, spam or fraud) with the same honesty rules as today: a prediction, not a fact; scores uncalibrated; no risk tier; no "safe" verdict; clear unavailable states. Nothing is stored. No accounts.

## Decisions needed from the owner

1. Is processing visitors' messages, which may contain personal data, acceptable for this project?
2. Is a model that is not validated on KAVACH data acceptable for public use, under what wording, and is M4-Q GO (or an approved CONDITIONAL) required first? Recommendation: **yes, require it.**
3. Where would it be hosted, who operates it, and who answers abuse or privacy reports (PRD decision D10)?
4. Is a privacy notice and a completed privacy review required before launch? Recommendation: yes.

## Privacy

- **Treat every input as real personal data**, whatever the page says. Do not rely on a "fictional messages only" instruction.
- **No persistence.** Analyse in memory and discard. Do not create incidents, events or audit rows for public requests; do not log text, URLs, sender-like strings or scores. Operational events only (counts, durations, error codes).
- **No third parties.** No external model, no hosted LLM, no analytics, no third-party scripts, fonts or captchas that receive the visitor's IP or text. (Fonts are already self-hosted.)
- **Privacy notice** in plain language: what is processed, that nothing is kept, the limits of the model, and a contact. Retention for network-level logs (IP addresses at the edge) must be decided and stated.
- **Data-protection law review** (for example India's DPDP Act 2023, or the law where the service is hosted) before launch. Out of engineering scope.

## Model limitations that must be shown to users

- Not validated on KAVACH data; error rates unknown in size and direction; M4-Q NOT READY.
- Scores are uncalibrated softmax values, not probabilities. Consider showing only the predicted class to reduce misreading.
- Harm in both directions: a scam predicted "legitimate" can lull a user, and a legitimate message predicted "fraud" can wrongly accuse a sender. The page must say a person decides, and must never say a message is safe.
- Long messages are truncated by the model; the UI already says so. Language and script coverage beyond the examples tested is unverified.
- Adversarial text can change the output; no robustness claim is made.

## Abuse prevention (proposed values; none has been load-tested)

| Control | Proposal |
| --- | --- |
| Per-IP limit | Sliding window in Redis, for example 20 analyses per minute and 200 per day per IP; fails closed (503) if the limiter is unavailable, like login today |
| Global limit and concurrency | Cap total analyses per minute and in flight; the worker already allows at most 2 in flight and returns 429 `CAPACITY_EXCEEDED` when full |
| Request size | Keep the 4,096-character limit; reject over-length input with 422, never truncate silently; bound the JSON body |
| Bot and cost abuse | A self-hosted proof-of-work challenge or an edge WAF rule set; avoid third-party captchas because they receive visitor data |
| Model probing | Return the class only (not full scores) and limit rates, to make extracting the model by repeated queries harder |
| CSRF and cross-origin | No cookies and no session, so no CSRF state to steal; still require a custom header and an exact Origin check, and send no CORS headers |
| Kill switch | A configuration flag that turns the endpoint off immediately without a deploy |
| Monitoring | Alerts on saturation, timeouts, error rates and limiter rejections, using counts only |

## Resource limits

What exists today, measured on an Apple M1 CPU in M4-I.2 (see `docs/M4_I2_SMS_INTEGRATION_REPORT.md`): about 54 ms median per analysis over HTTP, the worker using roughly 0.5 to 1.1 GB of memory, one worker process, at most 2 analyses in flight, a 2 s inference budget inside a 30 s request deadline, and the worker killed and restarted on a timeout.

Required before launch: a load test on the real hosting hardware to set limits from measurement, not from the numbers above; a memory ceiling for the worker enforced by the host (cgroup or container limit); and a plan for what happens at saturation (reject with a clear message, never queue unboundedly).

## Deployment security

- **Isolation:** the worker stays a separate, offline, unprivileged process with read-only model files; the public endpoint must not be able to reach PostgreSQL, Redis state about accounts, or the admin API. Prefer a separate service or host for public inference.
- **Transport and headers:** HTTPS only, HSTS, a strict CSP, no third-party origins.
- **Configuration:** a new, separately named authorization setting (not reuse of the C-13 value), refused unless explicitly approved; secrets only through environment storage; `APP_ENV=pilot` semantics for the rest of the service.
- **Code changes this implies (none done):** a new public route with its own anonymous dependency and rate limiter; relaxing the C-13 "development and loopback only" gate for this one purpose, behind the new setting; a no-persistence code path; classifying the route in `test_anonymous_access.py`; a frontend analyzer page with honest loading, error, unavailable and saturated states; tests for privacy (no text in database, Redis or logs), limits and failure behavior; a refreshed security audit.
- **Supply chain:** keep pinned model revision, checksums and locked dependencies; re-run the advisory scans before launch.

## Options considered

| Option | For | Against |
| --- | --- | --- |
| A. Run the model in the visitor's browser | No message leaves the device; no server inference cost | Needs a browser-runnable model format and a licence and size review; not built; the current artifacts and worker are server-side |
| B. Server inference on a public endpoint | Reuses the existing worker and honesty rules | Highest privacy and abuse exposure; needs everything above |
| C. Invite-only or access-code analyzer | Smaller blast radius | Conflicts with the "no login" decision unless kept separate from the public site |

**Recommendation:** do not launch B until M4-Q is GO (or an approved CONDITIONAL), the privacy review is done and a host is chosen. If the owner wants a lower-risk step first, evaluate A.

## Launch gates (all required)

1. C-15 approved by the owner in the master plan.
2. M4-Q GO or approved CONDITIONAL, or an explicit recorded owner waiver stating the risk.
3. Privacy notice and privacy review completed.
4. Load test completed and limits set from measurements.
5. Abuse controls and kill switch tested, with the privacy and failure-behavior tests passing in CI.
6. Security audit refreshed with no open critical or high findings.
7. Hosting decided (D10), with monitoring, an operator, and a rollback procedure.

## Owner decision record (to be completed by the owner)

- [ ] Approve a public analyzer in principle
- [ ] Approve conditional on the launch gates above
- [ ] Not approved; keep the public site to recorded examples
- Notes and conditions:
