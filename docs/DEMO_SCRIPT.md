# KAVACH 3-Minute Demo Script (SMS MVP-1)

This script is for a live or recorded demonstration of the local stack described in [LOCAL_DEMO.md](LOCAL_DEMO.md). Run the pre-demo check in that document first.

Every claim in this script is backed by [MVP1_INTEGRATION_REPORT.md](MVP1_INTEGRATION_REPORT.md). **Do not claim accuracy or detection performance:** the SMS model is disabled and has not been validated on KAVACH data.

Before starting, open one browser window at `http://127.0.0.1:5173` (the public site; no login), light theme, about 1280 px wide, with nothing else showing. The operator console is at `/admin` and is not linked from the public site. Have two fictional messages ready to paste:

- `FICTIONAL DEMO: Your Examplebank KYC expires today. Update now at the link to avoid suspension.`
- `FICTIONAL DEMO: Running 10 minutes late, start dinner without me.`

## Script (about 3:00)

| Time | On screen | Say (roughly) |
| --- | --- | --- |
| 0:00–0:20 | `/` hero; click **Pause motion** | "SMS fraud moves fast, but analysts need evidence they can trust, not a black-box score. KAVACH is an evidence-first research project: it records analysis evidence, never keeps message text, and leaves the decision to a person. There is no login on this site, and motion can be paused for accessibility." |
| 0:20–0:45 | Click **Examples**; scroll the nine cards | "These are recorded examples, not live analysis: nine invented messages and what the pinned model recorded for each, with the date and model version. The scores are uncalibrated and the model is not validated, so we claim no accuracy. There is deliberately no box to type into." |
| 0:45–1:00 | Type `/admin` in the address bar; sign in as `demo-admin` | "The operator console is a separate area that nothing public links to. Accounts are provisioned by an operator; there is no sign-up. Sessions are server-side, and every write needs a CSRF token and the right Origin." |
| 1:00–1:20 | **Overview**, then the **SMS model** pill on **System** | "This is the live state from the backend. The model is *Disabled*, and the page says so: not validated on KAVACH data, scores uncalibrated. We never invent a number." |
| 1:20–1:55 | **Analyze SMS**: paste the first message, **Submit** | "Only admins can submit, and only fictional test messages. The browser creates the event ID once, so a retry can never create a duplicate. The text is sent once and is not kept." Point at the receipt: "Stored. Analysis is *unavailable* because the model is off. That's the honest state, not a fake score." |
| 1:55–2:20 | Open the incident from the receipt or **Incidents** | "The incident record shows the event timeline, the analysis stage and its reason, tier *unknown*, and no message text, only evidence." Optionally show the filters on **Incidents**. |
| 2:20–2:45 | **Sign out**; sign in as `demo-viewer`; open `/admin/analyze` | "Roles are enforced on the server. A viewer has no submission page, and the API itself refuses a viewer's submission with 403. Hiding a button isn't the security." |
| 2:45–3:00 | Back on the public site `/`, or a summary slide | "Tested end to end against real PostgreSQL and Redis: about 800 backend tests, 136 frontend tests and 17 browser journeys, including outages that fail closed. Next steps: the human-labelled evaluation that decides whether the model can be switched on, then voice and correlation." |

## If something goes wrong live

| Problem | What to do and say |
| --- | --- |
| "Too many requests · Resuming in N s" | "That's our per-user read limit, 120 a minute, doing its job." Wait for the countdown or click **Try again** after it. |
| Sign-in fails with 503 | Redis or PostgreSQL stopped. Switch to the recording (below). |
| Page blank or wrong origin | Confirm the URL is `127.0.0.1:5173`, not `localhost`. |
| Anything else for more than 15 s | Switch to the recording. Don't debug on stage. |

## Fallback: prerecorded demonstration checklist

Record the day before, on the local stack, following the script above.

- [ ] Fresh demo stack ([LOCAL_DEMO.md](LOCAL_DEMO.md) steps 1–6) and the pre-demo check passed.
- [ ] Screen recorder set to 1920×1080 (or the window at 1280 px), with system notifications off.
- [ ] Browser: a clean profile, no extensions, bookmarks bar hidden, zoom 100%, light theme.
- [ ] Passwords typed only into password fields (masked). Never visible in the address bar, on a slide or in a terminal.
- [ ] Only the fictional messages above are used; no real numbers, names or messages.
- [ ] Recorded segments, matching the script:
  1. landing and pause motion;
  2. admin sign-in;
  3. Overview and System showing *Disabled*;
  4. Analyze SMS submission and receipt;
  5. the incident detail;
  6. sign-out and viewer refusal.
- [ ] Optional 20 s extra clip: the "Too many requests" countdown, or a terminal running `npm run verify` and the pytest summaries, as evidence.
- [ ] Review the recording for leaked secrets (terminal history, `.env` contents, tokens) before sharing.
- [ ] Export as MP4 (H.264). Keep a copy on local disk and one on a USB drive or cloud folder; test playback offline.
- [ ] Note in the submission that the video shows a **local controlled demo**, not a deployment.

## Claims to avoid

- "Detects fraud with N% accuracy." No evaluation result exists.
- "Live telecom" or "deployed." It is local only, with fictional data.
- "AI decides." A person decides; analysis is evidence only.
- "Voice and call fraud detection." Postponed (M5/M6); not in this release.
