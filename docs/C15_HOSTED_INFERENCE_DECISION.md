# Decision C-15: Hosted anonymous SMS inference — owner decision record

**Status: AWAITING THE OWNER'S DECISION. Nothing in this document approves anything.** It was
prepared on 16 November 2026 so that the owner can decide with the facts in one place. The code
that would run hosted inference exists (branch `feature/hosted-inference-gate`), is disabled by
default, and refuses to start unless the owner sets the approval value described in §6 after
recording a decision here. The authors of this document cannot and do not set that value.

Related: [PUBLIC_ANALYZER_PROPOSAL.md](PUBLIC_ANALYZER_PROPOSAL.md) (the proposal and launch gates),
[PUBLIC_ANALYZER_RUNBOOK.md](PUBLIC_ANALYZER_RUNBOOK.md) (how to operate it),
[MASTER_DEVELOPMENT_PLAN.md](MASTER_DEVELOPMENT_PLAN.md) (C-12, C-13, C-14, C-15).

## 1. What hosted anonymous inference enables

A visitor opens `https://<the public domain>/analyze` with no account, pastes a message of up to
500 characters, and the pinned model (`Horizon-Labs/phishing-scam-detector-base`, revision
`fa686fc0…`, manifest `sms_classifier.horizon.v1`) classifies it on the KAVACH server as
**fraud**, **spam** or **legitimate**. The response carries the class, whether the model truncated
the input, and two timings. It carries no score, probability, tier, or stored identifier, because
none of those is validated. The site already shows the page; today the server answers that
analysis is disabled.

What it does **not** enable: accounts, incidents, the operator console (absent on the public
service), real-time intervention, voice, or any claim of accuracy.

## 2. Fictional demonstration messages, or visitors' real messages? (decision required)

The page is written for **fictional messages only**: the privacy notice says not to paste personal
information, real messages, passwords or OTPs. The two scopes differ in what the owner takes on:

| | A. Fictional demonstration only (recommended first step) | B. Visitors' real messages |
| --- | --- | --- |
| Page wording | As now: "fictional messages only", "do not paste real messages" | Must change: invite real messages and say exactly what happens to them |
| Privacy posture | The server must still treat every input as personal data (people ignore instructions) | Same, plus a completed privacy review, a named contact, and a stated retention for edge logs |
| M4-Q | Restricted release under a recorded waiver (§4) | A GO or approved CONDITIONAL verdict, or a stronger waiver that accepts unknown error rates on real decisions |
| Harm if the model is wrong | A wrong answer about an invented message misleads nobody about a real threat | A real scam predicted "legitimate" can lull a person; a real message predicted "fraud" can wrongly accuse a sender |
| Law | Lower exposure, not none | Data-protection review (DPDP Act 2023 or the hosting jurisdiction) before launch; out of engineering scope |

The engineering in this branch is the same for both; only wording, review and the waiver differ.
**Recommendation:** approve **A** first. Treat **B** as a separate later decision with its own
wording change and privacy review.

## 3. Sensitive data: what the service does with the text

- The text is read into memory, sent over a pipe to a worker process on the same container,
  classified, and discarded. No event, incident, audit row, analytics record or cache holds it.
- Nothing is logged about the content: operational logs carry event names, reason codes, counts
  and request IDs only; the access log is off; the worker reports numbers only.
- Redis holds, for at most 60 seconds, an HMAC of the visitor's address, random request IDs and
  timestamps for the rate limits, plus the pause switch. It never holds text.
- No third party receives the text or the visitor's address: no external model, analytics,
  fonts, captcha or scripts. The model runs offline inside the container.
- **What cannot be promised:** that the text never leaves the visitor's device (it is sent to the
  server), that memory is scrubbed, or that the hosting provider's own edge logs (which record
  client addresses, paths and timings, not request bodies) are retained for a specific period.
  The owner must state the provider's retention in the privacy notice.

## 4. Validation limitations and the restricted-release decision (M4-Q)

- M4-Q, the independent evaluation on KAVACH's own labelled data, is **NOT READY** (12 November
  2026: collected spam 19 of minimum 25; synthetic benign 1 of minimum 16). No GO, CONDITIONAL
  or NO-GO verdict exists. Error rates on messages like the ones visitors may paste are unknown
  in size and direction.
- Decision C-12 D says the worker stays disabled for the MVP until an M4-Q verdict. C-13 was a
  narrow, local-only exception for fictional data. Hosting is a further exception and needs its
  own explicit record.
- The outputs stay what they are everywhere else: uncalibrated softmax, `sms_score` null, tier
  `unknown`, no accuracy claim, no fine-tuning, and the page says "a prediction, not a fact" and
  "Legitimate does not mean safe".

**The owner must choose one** (write it in §8):

- **Waiver (restricted release):** "I release the unvalidated pinned model for hosted analysis of
  fictional demonstration messages, knowing M4-Q is NOT READY and error rates are unknown; the
  page states this; this is not a validation and does not change C-12 D for any other use."
- **Wait:** keep hosted inference off until M4-Q reaches a verdict (requires the owner to finish
  the labelling that is currently paused).

An independent review (someone other than the implementer and the owner reading the privacy
notice, the limits and the kill switch) is listed in the proposal's launch gates. If nobody is
available, the owner should record that the review was waived rather than skip it silently.

## 5. Risks the owner accepts by approving

1. **Wrong predictions shown to the public**, in both directions, with no measured error rate.
2. **Abuse and cost:** anyone can spend the per-IP budget (5/minute) and the global budget
   (60/minute); above that the service answers 429. A distributed abuser can keep the global
   budget exhausted, which denies the analyzer (not the site) to everyone. Compute is bounded, so
   the cost ceiling is the plan's usage limit (§7), not the abuser's choice.
3. **Model extraction:** repeated queries reveal the model's behaviour; only the class is
   returned, and the model is a public third-party checkpoint, so the loss is small.
4. **Adversarial text:** inputs crafted to flip the output will work; no robustness is claimed.
5. **Provider dependence:** Railway's edge terminates TLS and sets the client-address header the
   limits depend on; a change on their side would make the analyzer fail closed (503), not open.
6. **Memory pressure:** the worker needs about 1.7–2 GB; the supervisor restarts it if it grows
   past `SMS_WORKER_MAX_RSS_MB`, and the host kills the container if it exceeds the replica
   limit. Either shows as "unavailable", never as a wrong answer.

## 6. Mandatory protections (all implemented in code; the configuration names are exact)

| Protection | How |
| --- | --- |
| Off by default | Image and example configuration ship `PUBLIC_ANALYZER_MODE=disabled`, `SMS_WORKER_ENABLED=false` |
| Separate hosted gate | `PUBLIC_ANALYZER_MODE=hosted` refuses to start unless **all** of: `PUBLIC_ANALYZER_HOSTED_APPROVAL=c15-owner-approved`, `PUBLIC_ANALYZER_ONLY=true`, `APP_ENV=pilot`, an `https://` `APP_ORIGIN`, `SMS_WORKER_ENABLED=true`, `PUBLIC_ANALYZER_CLIENT_IP_HEADER` set, `REDIS_URL` and `RATE_LIMIT_HMAC_KEY` set, and the local-only `SMS_MODEL_AUTHORIZATION` **not** set. The C-13 local mode is unchanged. Thirteen refusal cases are tested. |
| No fake approval | The approval value appears in no committed file, image default, example or fixture; tests set it only inside a test process against a loopback test client |
| Verified model | Weights are fetched at image build time from the pinned revision, checked file by file (size, SHA-256, label map, no stray or forbidden files) and installed read-only; the worker verifies again at every start and runs a canary self-test; a mismatch means "unavailable" |
| No private data reachable | The public-only service has no database URL, no admin keys, no session routes; `/admin`, `/api/v1/incidents` and the rest are 404 there (tested) |
| Rate limits | Redis sliding windows, atomic per-IP and global, fail closed when Redis is unreachable |
| Trusted client address | In hosted mode the address comes only from the edge's single-valued header (`X-Real-IP` on Railway); a missing or malformed value fails closed; `X-Forwarded-For` and `Forwarded` are ignored |
| Bounded resources | At most 2 analyses in flight, 32 KiB bodies read within 5 s, 2 s model budget inside a 30 s deadline, worker killed and restarted on timeout, worker RSS ceiling, one API process |
| Instant kill switch | `SET kavach:pilot:public:paused 1` in the service's Redis: every analysis answers 503 `ANALYZER_PAUSED` immediately, no redeploy; `DEL` resumes. Second switch: `PUBLIC_ANALYZER_MODE=disabled` plus redeploy. Third: Railway rollback to the previous deployment |
| Transport and headers | HTTPS with HSTS, strict CSP, `no-store`, `nosniff`, `no-referrer`, no CORS grant, no cookies |
| Honest UI | "Experimental", "not validated", "not a safety verdict", disabled and unavailable states; no scores shown |

## 7. Hosting facts and costs (measured and published figures; estimates are marked)

- **Trial plan cannot host the model.** Railway's Trial allows 1 GB RAM per service, a 0.5 GB
  volume and a 4 GB image. Measured on Linux (Docker, 2 vCPU): with the model loaded the worker
  process holds 1.63 GB RSS and the container 1.77 GiB; under a 1 GB cap it ran only by
  thrashing the memory-mapped weights (16,372 reclaim events, socket throttling, 1.9–2.6 s per
  analysis under two concurrent requests). The current image is 3.48 GB compressed without
  weights; with the 1.23 GB weights it exceeds the Trial's 4 GB image limit.
- **Hobby plan is sufficient:** $5/month including $5 of usage; up to 48 GB RAM and a 100 GB
  image per service. Usage rates: RAM $10 per GB-month, CPU $20 per vCPU-month, egress $0.05/GB.
- **Estimate (assumptions: steady RSS 1.8 GB, idle CPU near zero, under 20,000 analyses a month
  at ~0.3 s of 2 vCPU each, a small Redis, under 1 GB egress):** RAM ≈ $18/month, CPU < $1,
  Redis ≈ $0.50, egress < $0.10 → **about $19–22/month all-in**, of which $5 is the subscription's
  included usage. These are estimates from local measurements, not Railway's meter; the first
  month's usage page is the real number.
- **Recommended cap:** a workspace hard usage limit of **$30/month** (minimum is $10; reaching it
  takes every workload offline, including the website) with a soft alert at $20.
- **Not purchased and not provisioned:** no plan upgrade, Redis service, or billing change has
  been made. Those are the owner's actions (runbook §"Railway activation").

## 8. Owner decision (to be completed by the owner only)

- [ ] **Not approved.** Keep the public site with the analyzer disabled.
- [ ] **Approved, scope A (fictional demonstration messages only),** under the M4-Q waiver in §4.
- [ ] **Approved, scope B (visitors' real messages),** only after a separate wording change, a
      privacy review and the stronger waiver.
- M4-Q restricted-release decision (waiver text or "wait"): ______________________________
- Independent review: done by ____________ on ________ / waived (reason): ________________
- Privacy notice contact and edge-log retention statement: ______________________________
- Budget: Hobby plan approved [ ] ; hard usage limit $______ ; soft alert $______
- Operator who watches it and can pause it: ______________________
- Date and signature: ______________________

## 9. Launch approval checklist (every box before `PUBLIC_ANALYZER_HOSTED_APPROVAL` is set)

1. [ ] §8 completed and this file plus the C-15 row in MASTER_DEVELOPMENT_PLAN.md updated by the owner.
2. [ ] Pull request for `feature/hosted-inference-gate` merged into `dev`, then `main`, with all three required checks green.
3. [ ] Hobby plan active; workspace hard usage limit set; Redis service created on the private network only, with a random password; `RATE_LIMIT_HMAC_KEY` generated (≥32 random characters) and stored only in Railway variables.
4. [ ] Variables set exactly as in the runbook; `SMS_MODEL_AUTHORIZATION` absent; `APP_ORIGIN` equal to the exact public origin.
5. [ ] Deployment built with the model (build log shows `model horizon-phishing-scam-base@… verified`) and `/health` healthy.
6. [ ] `GET /api/v1/public/analyzer` reports `enabled: true`; a fictional message at `/analyze` returns a real prediction in the browser; `/admin` and `/api/v1/incidents` are 404.
7. [ ] Edge-address check passed: six quick requests from one client give 429 on the sixth; the same with varying spoofed `X-Real-IP` values still gives 429 (the edge overwrites it). If instead every request is 503, or spoofed values are **not** limited, pause and stop.
8. [ ] Kill switch rehearsed: pause key set → 503 `ANALYZER_PAUSED` within seconds; deleted → analysis resumes. Rollback rehearsed once.
9. [ ] No raw text in Railway logs after the tests (search the deploy log for a fragment of a test message).
10. [ ] Someone named in §8 is watching usage and the 429/503 counts for the first days.
