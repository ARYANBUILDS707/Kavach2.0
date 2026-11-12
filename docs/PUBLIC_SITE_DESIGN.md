# Login-Free Public Site (decision C-14)

On 13 Nov 2026 the owner decided that KAVACH must work as an openly accessible website: visitors open it directly, with no sign-up, no account and no login. This document records what depended on authentication, the design that replaces it for visitors, and what stays protected. It adds no AI feature and no voice feature.

## What visitors get

| Address | What it is | API calls |
| --- | --- | --- |
| `/` | Home page: what KAVACH is, how it treats evidence, release status, FAQ | none |
| `/examples` | Nine fictional messages with the answer the pinned model **recorded** for each | none |
| `/robots.txt` | Disallows `/admin` and `/api/` for crawlers (hygiene, not security) | none |

There is no sign-in, sign-up or account link anywhere on the public pages, no input box, and no cookie. Old addresses: `/welcome` redirects to `/`; `/login` redirects to the operator sign-in.

## What depended on authentication (audit)

**Frontend.** Every real page sat behind `RequireSession`, and `SessionProvider` wrapped the whole app, so even the public landing page called `GET /auth/session` on load. Only `/login` and `/welcome` were public.

**Backend** (unchanged by this work):

| Route | Who may call it |
| --- | --- |
| `GET /health`, `GET /api/v1/health` | anyone: liveness only, no configuration |
| `POST /api/v1/auth/login` | anyone may *attempt*; wrong credentials get 401; throttled per IP and username with a shared Redis counter that fails closed |
| `GET /api/v1/auth/session`, `POST /api/v1/auth/logout` | a session (logout also needs the exact Origin) |
| `GET /api/v1/incidents`, `GET /api/v1/incidents/{id}` | a dashboard session (viewer, analyst or admin); API keys refused |
| `GET /api/v1/system/models` | a dashboard session |
| `GET /api/v1/simulator/scenarios` | an admin session |
| `POST /api/v1/events/sms`, `POST /api/v1/events/call` | an admin session with CSRF and Origin, or an ingestion key |
| `GET /api/v1/events/{id}` | an ingestion key (own source only) |
| `/docs`, `/openapi.json` | development and test only; off when `APP_ENV=pilot` |

## Design

1. **The public site is static and talks to no API.** The incident dashboard is private operational data, so the public view is not "the dashboard with fewer permissions". It is a different thing: fixed, fictional examples bundled into the page. There is therefore no anonymous data endpoint to protect, rate-limit or leak.
2. **The operator console moves under `/admin`** (`/admin/login`, `/admin`, `/admin/incidents`, `/admin/system`, `/admin/analyze`) and nothing public links to it. Sign-in, sessions, CSRF, Origin checks and roles are unchanged and still enforced by the server on every request. The session is looked up only inside `/admin`, so a public visit never contacts the API.
3. **No authorization was disabled or loosened.** Anonymous visitors still cannot read or modify stored incidents, evidence or sessions, and no one is given Admin permissions.
4. **Examples are real model output, never hand-typed.** `frontend/src/features/public/examples.json` is re-recorded from real inference by `backend/tests/test_public_examples.py`. The page shows the recording date and the exact model version, and calls the results "recorded examples, not live analysis".

Re-recording (local, offline, needs the model environment and verified artifacts):

```sh
KAVACH_WRITE_PUBLIC_EXAMPLES=1 sandbox-exec -p '(version 1)(allow default)(deny network-outbound (remote ip))' \
  uv run --offline --project backend --locked pytest backend/tests/test_public_examples.py -m model
```

A CI-safe test checks the file's shape (fictional text, `.example` links only, the pinned model revision, internally consistent scores). The `-m model` test checks that real inference still equals the recording.

## What is not exposed

- **Private incidents, evidence and sessions:** unreachable without a valid session. `test_anonymous_access.py` enumerates every route the production app registers and requires each to be on a short reviewed allowlist or to refuse an anonymous caller. A new route fails that test until someone classifies it (it already caught `GET /api/v1/events/{id}` on its first run). A mutation probe confirmed it catches a protected route made anonymous.
- **Administrative endpoints:** the same inventory; plus no CORS headers are ever sent, so another website's scripts cannot read the API from a visitor's browser.
- **Secrets and raw messages:** nothing in the frontend bundle (the bundle scan still runs in CI); the public pages contain only the fictional examples; logs carry operational events only.
- **Crawlers:** `robots.txt` disallows `/admin` and `/api/`, and the console pages carry `noindex, nofollow`. This is a hint, not protection.

## Abuse and rate controls

There is no new application-level anonymous rate limiter, because there is no anonymous data endpoint to limit. Instead:

- **Public pages** are static files. The only abusable resource is bandwidth, which belongs at the hosting edge (CDN or reverse proxy). Suggested starting point, to be tuned: a per-IP request limit on HTML, long cache lifetimes on hashed assets, and a connection limit.
- **The API's anonymous surface** is only health, login attempts and 401 refusals. Login is already throttled per IP and username and fails closed when Redis is unavailable. After sign-in, reads are limited to 120 per minute per user.
- **Strongest control:** do not expose `/api` and `/admin` on the public hostname at all unless needed. Serve the operator console from an IP-allowlisted or VPN-only host (a different `APP_ORIGIN`), and keep the public host to static files.
- If any anonymous endpoint is ever added, it must be classified in the inventory test and given its own limit before merging. See [PUBLIC_ANALYZER_PROPOSAL.md](PUBLIC_ANALYZER_PROPOSAL.md).

## The model on a hosted service

- **Disabled by default** everywhere.
- **Experimental inference cannot be enabled on a hosted service.** The C-13 gate refuses `SMS_WORKER_ENABLED` unless `APP_ENV=development` with a loopback origin, and a hosted deployment uses `APP_ENV=pilot` with an HTTPS origin.
- **The examples are not inference.** They are a recording; nothing runs when a visitor opens the page.
- **A real public analyzer is not authorized.** C-13 covers local, fictional-data use only. A separate proposal (C-15, not approved) is in [PUBLIC_ANALYZER_PROPOSAL.md](PUBLIC_ANALYZER_PROPOSAL.md).

## Hosting requirements (guidance only; nothing was deployed)

- Serve `frontend/dist` as static files over HTTPS with security headers. A starting CSP is `default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; frame-ancestors 'none'` (the site loads nothing from third parties; styles are inline in some components).
- If the API is reachable at all, run it with `APP_ENV=pilot`, an HTTPS `APP_ORIGIN`, all authentication settings, private PostgreSQL and Redis, and `/docs` off (automatic in `pilot`).
- Same-origin routing: `/api/v1` proxied to the backend, `/admin` served by the same static app. The session cookie is `__Host-` prefixed, `Secure`, `HttpOnly`, `SameSite=Lax` on HTTPS.
- Packaging, TLS termination, monitoring and a hosting decision (D10) remain milestone M11. No deployment infrastructure was added here.

## Local use and compatibility

- Console users sign in at `/admin/login`; every console page, role rule and API contract is unchanged. The 82 console unit tests passed with only their paths updated.
- `scripts/kavach-demo.sh` and the demo documents now point to the public site for visitors and `/admin` for operators.
- `frontend/tests/e2e/origin.ts` lets the browser tests run when the app is served on a port other than 5173 (`KAVACH_E2E_ORIGIN`).

## Verification

See the pull request for the commands and results. Remaining limitations: no deployment exists; the examples are nine hand-written messages and say nothing about accuracy; edge rate limits are guidance until a host is chosen.
