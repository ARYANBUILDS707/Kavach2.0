# KAVACH Frontend MVP-1 Implementation Plan

Prepared 9 November 2026 on `backend` for the owner's review; **approved 9 Nov 2026**: D09 tokens, the lean stack, `openapi-typescript`, and copying the OpenAPI file with its source commit. **Plan only:** no frontend code or package exists yet, and nothing here is installed. Exact F1 setup: section 14. Work starts on the `frontend` branch after the owner switches to it (MASTER_DEVELOPMENT_PLAN.md "SMS MVP-1", items MVP-F1 to MVP-F3).

Sources of truth, in order: [API.md](API.md) "SMS MVP-1 contract" (wire shapes), `backend/contract/openapi.json` (the generated, pinned OpenAPI document), [DESIGN.md](DESIGN.md) (tokens, components, states), [ARCHITECTURE.md](ARCHITECTURE.md) (stack and folders), [AGENTS.md](../AGENTS.md). Where this plan and those documents disagree, they win.

## 1. Scope

| In MVP-1 | Not in MVP-1 |
| --- | --- |
| Sign in and sign out; session restore on reload | Review form and history (postponed, C-12 B) |
| Overview: model readiness and latest SMS incidents | Live updates over `/stream` (postponed) |
| SMS incident history with filters and paging | Call or voice views, correlation, pairs, fusion |
| Incident detail with stage evidence and uncalibrated model output | Simulator scenario playback |
| System page: model status and demo limitations | Any account management or signup |
| `/analyze` admin page, **only after MVP-B4 exists in the backend** | Any API not in API.md |

## 2. Preconditions and decisions for the owner

1. **D09** (DESIGN.md tokens, English-first): **approved 9 Nov 2026.**
2. **Packages:** the stack below is **approved (9 Nov 2026)**; exact versions are in section 14.2.

   | Package | Purpose | Group |
   | --- | --- | --- |
   | `react`, `react-dom` | UI | runtime |
   | `react-router` | Routes | runtime |
   | `vite`, `@vitejs/plugin-react`, `typescript` | Build and strict type-check | dev |
   | `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom` | Unit and component tests | dev |
   | `@playwright/test` | Browser journeys against the real backend | dev |
   | `eslint`, `typescript-eslint`, `eslint-plugin-react-hooks` | Lint | dev |
   | `openapi-typescript` (**proposed**) | Generates TypeScript types from the pinned OpenAPI file; no runtime code | dev |
   | `@axe-core/playwright` (**proposed**) | Automated accessibility checks in journeys | dev |

   No UI kit, CSS framework, chart library, state library, data-fetching library or date library: native controls, CSS variables and small hooks cover MVP-1.
3. **Contract file on `frontend`:** **approved.** The owner copies `backend/contract/openapi.json` to `frontend/contract/openapi.json` with `frontend/contract/SOURCE.md` recording the source commit and SHA-256 (section 14.4). A CI check fails if the generated types are stale.
4. **Node version:** 24.16.0 (Node 24 LTS, the version installed locally), pinned in `.nvmrc` and `engines`.

## 3. Directory structure (ARCHITECTURE.md)

```text
frontend/
  index.html
  package.json, package-lock.json, tsconfig.json, vite.config.ts, eslint.config.js, .nvmrc
  contract/openapi.json            copied from backend/contract (owner)
  src/
    main.tsx
    app/                           AppRouter, AppShell, SessionProvider, RequireSession, RequireRole
    lib/api/                       client.ts, errors.ts, types.ts (generated + named aliases), endpoints.ts
    lib/                           time.ts (local + exact UTC), ids.ts (crypto.randomUUID), polling.ts
    components/                    shared accessible components (section 7)
    features/auth/                 LoginPage, useSession
    features/overview/             OverviewPage
    features/incidents/            IncidentListPage, IncidentDetailPage, filters.ts, hooks
    features/system/               SystemPage, useModelStatus
    features/analyze/              created only in MVP-F3 (after MVP-B4)
    styles/                        tokens.css (DESIGN.md), base.css
  tests/e2e/                       Playwright journeys (real backend)
```

Test doubles live only under `src/**/__tests__` and `tests/`, never imported by runtime code. A build check rejects any import of a test path.

## 4. Routes

| Path | Access | Page | Notes |
| --- | --- | --- | --- |
| `/login` | Public | LoginPage | Redirects to `/` if a session exists. `?next=` accepts only an internal path matching a known route |
| `/` | Any role | OverviewPage | Model status card plus the 10 newest SMS incidents |
| `/incidents` | Any role | IncidentListPage | Always sends `channel=sms`. Filters `tier`, `from`, `to` live in the URL; the cursor stays in memory |
| `/incidents/:incidentId` | Any role | IncidentDetailPage | The back link restores list filters from the URL |
| `/system` | Any role | SystemPage | Model state, version, score semantics, retention and limitation text |
| `/analyze` | Admin | AnalyzePage | **Not registered and not in navigation until MVP-B4 is implemented** |
| `*` | Any | NotFoundPage | |

The server is authoritative for every permission; route guards are convenience only. The URL never carries message text, tokens or credentials. Incident IDs and filter values are allowed.

## 5. Authentication flow

1. **App start:** `GET /api/v1/auth/session`.
   - 200: store `{user, expires_at, csrf_token}` in React state (memory only).
   - 401: show `/login`.
   - 429 or 503: show the "Sign-in service unavailable" state with a retry action, and don't redirect.
2. **Sign in:** `POST /api/v1/auth/login` with `{username, password}`, `credentials: "same-origin"`, `Content-Type: application/json`. The browser sends `Origin`; the client never sets it.
   - 200: store the session as above, clear the password field from state, navigate to `next` or `/`.
   - 401 `INVALID_CREDENTIALS`: generic "Username or password is incorrect"; never reveal which.
   - 429: "Too many attempts", with the `Retry-After` countdown; the submit stays disabled until it ends.
   - 503: "Sign-in is temporarily unavailable". This is also the Redis-down case: the client never retries automatically.
   - 403 `CSRF_REJECTED`: "This page must be opened from the configured address" (a deployment error).
3. **CSRF:** every mutation (logout now, admin submission later) sends `X-CSRF-Token` from memory. After a reload the token comes back from `GET /auth/session`. It is never written to storage.
4. **Expiry:** any 401 `SESSION_EXPIRED` from any request clears the session and every cached incident or model value from memory, then navigates to `/login?next=<current path>`. A banner warns at five minutes before `expires_at` that the user will be signed out at the absolute limit.
5. **Sign out:** `POST /api/v1/auth/logout` with `X-CSRF-Token`. On 204, or on any 401, clear memory and go to `/login`. A failed logout (503) says the session may still be active and offers a retry.
6. **Never:** an `Authorization` header, an ingestion key, `localStorage`, `sessionStorage` or IndexedDB for any session, evidence or form value. The client sends exactly one credential type: the cookie, set by the server as HttpOnly.

## 6. API layer

### 6.1 Client rules (`lib/api/client.ts`)

- One `request<T>(method, path, {query, body, signal})` function. Relative URLs only (`/api/v1/...`) and `credentials: "same-origin"`. JSON bodies only. A timeout via `AbortController`: 15 s for reads, 35 s for the future submission, matching the 30 s server deadline. Parsing is bounded: a non-JSON body becomes an `ApiError` with code `UNEXPECTED_RESPONSE`.
- Errors become `ApiError {status, code, message, requestId, retryAfterSeconds}`. The server's `message` is shown only for codes in the mapping table (section 9). The request ID is always shown as copyable text.
- **429 budget guard:** the server allows 120 reads per minute per user, shared by every tab. When any 429 arrives, a global "paused until" timestamp stops all polling and automatic refetches until `Retry-After` has passed. User-triggered reads are disabled with a countdown.
- **Retries:** reads are retried only on network failure or 503, at most twice, with jittered backoff (1 s, then 3 s), and never after a 429. Mutations are never retried automatically; the future submission reuses its `ui-` event ID for a manual retry.
- **Dependency injection for tests:** `createClient(fetchImpl)` takes the fetch function; tests pass a fake, and runtime passes `window.fetch`.

### 6.2 Types (`lib/api/types.ts`)

They are generated from `contract/openapi.json` by `openapi-typescript` (proposed), with named aliases on top. If that package is not approved, the same interfaces are hand-written and a Vitest contract test compares each interface's key list with the OpenAPI schema properties. Exact MVP-1 shapes:

```ts
type Role = "viewer" | "analyst" | "admin";
type Tier = "unknown" | "low" | "medium" | "high" | "critical";
type AnalysisStatus = "complete" | "partial" | "unavailable";

interface Envelope<T> { data: T; request_id: string }
interface ErrorEnvelope { error: { code: string; message: string }; request_id: string }

interface SessionData {
  user: { id: string; display_name: string; role: Role };
  expires_at: string;            // RFC 3339 UTC
  csrf_token: string;            // memory only
}

interface SmsModelStatus {
  state: "disabled" | "starting" | "ready" | "unavailable";
  detail: string;                // supervisor code, e.g. "circuit_open"
  reason: string | null;         // safe failure code
  model_version: string | null;
  score_semantics: "uncalibrated_softmax";
  validated_on_kavach_data: false;
}
interface ModelsData { sms_classifier: SmsModelStatus }

interface IncidentSummary {
  id: string;
  kind: "standalone" | "pair";
  occurred_at: string;
  tier: Tier;
  final_score: number | null;    // always null in MVP-1
  analysis_status: AnalysisStatus;
  current_revision: number;
  version: number;
  latest_review: null;           // reviews postponed
  updated_at: string;
}
interface IncidentPage { data: IncidentSummary[]; page: { next_cursor: string | null; has_more: boolean }; request_id: string }

interface ModelOutput {
  labels: Record<string, number>;   // native legitimate/spam/fraud, 4 decimals, NOT probabilities
  top_label: string;
  score_semantics: "uncalibrated_softmax";
  truncated: boolean;
}
interface Stage {
  status: "complete" | "unavailable";
  reason: string | null;
  duration_ms: number;
  model_output: ModelOutput | null;
}
type StageName = "sms_classifier" | "transcription" | "voice_intent" | "synthesis";
interface IncidentEvent {
  id: string;
  channel: "sms" | "call";
  occurred_at: string;           // event time
  received_at: string;           // arrival time, shown separately
  analysis_status: AnalysisStatus;
  processing_ms: number;
  sms_score: number | null;      // always null in MVP-1
  reason_codes: string[];
  stages: Partial<Record<StageName, Stage>>;
  model_versions: Record<string, string>;
}
interface Assessment {
  revision: number; tier: Tier;
  base_score: number | null; fusion_score: number | null; final_score: number | null;
  analysis_status: AnalysisStatus; policy_version: string;
  model_versions: Record<string, string>; created_at: string;
}
interface IncidentDetail extends IncidentSummary {
  events: IncidentEvent[];
  assessment: Assessment;
  related_incident_ids: string[];
  reviews: { items: []; page: { next_cursor: null; has_more: false } };
}

interface IncidentListParams {
  limit?: number;                 // 1–100, default 25
  cursor?: string;
  channel?: "sms" | "call";       // the UI always sends "sms"
  kind?: "standalone" | "pair";
  tier?: Tier;
  from?: string;                  // RFC 3339 with offset, inclusive
  to?: string;                    // exclusive; from < to
  // review_status is NOT supported: the server returns 422
}
```

The submission receipt type is added in MVP-F3 from the implemented MVP-B4 OpenAPI, not before.

### 6.3 Endpoints used (`lib/api/endpoints.ts`)

| Function | Call | Counts toward the read limit |
| --- | --- | --- |
| `getSession()` | `GET /api/v1/auth/session` | yes |
| `login(username, password)` | `POST /api/v1/auth/login` | no |
| `logout(csrf)` | `POST /api/v1/auth/logout` | no |
| `getModels()` | `GET /api/v1/system/models` | yes |
| `listIncidents(params)` | `GET /api/v1/incidents` | yes |
| `getIncident(id)` | `GET /api/v1/incidents/{id}` | yes |

### 6.4 Read budget (120 per minute per user)

| Source | Rate |
| --- | --- |
| Model status poll (overview, system, header), only while the tab is visible | every 30 s: 2 per minute |
| List auto-refresh, only while visible and only on page 1 | every 30 s: 2 per minute |
| Session check | on load and on window focus at most once per minute |
| User navigation and "Load more" | on demand |

Polling is shared across components (one timer per resource) and stops in hidden tabs. Several tabs share one budget, and the 429 guard covers the overflow.

## 7. Shared components (DESIGN.md "Reusable components")

| Component | Contract |
| --- | --- |
| `AppShell` | Skip link, header (KAVACH, environment label, "Controlled demonstration", user's display name and role, model status pill, sign-out), sidebar navigation at 1024 px and wider, disclosure navigation below; `<main>` landmark |
| `PageHeader` | Title, context line, page actions only |
| `RiskBadge` | Text label for every tier, including "Unknown"; DESIGN.md token colours; never green for unknown |
| `StatusBadge` | `complete`, `partial` or `unavailable`, with text |
| `ModelStatePill` | `ready`, `starting`, `disabled` or `unavailable`, with text; links to `/system` |
| `ModelOutputPanel` | Section 8 rules |
| `StageList` | Each stage: name, status, reason code with human text, duration; unavailable stages named with their impact |
| `IncidentTable` | Semantic table (time, incident ID, status, tier, open link); stable order; stacked summaries below 768 px |
| `FilterBar` | Tier select, from/to datetime fields with timezone hint, Apply and Clear; URL-synchronised |
| `LoadMore` | Cursor paging button; announces "N more incidents loaded" politely |
| `Timestamp` | Local time with timezone and the exact UTC value accessible; event time and received time labelled separately |
| `CopyableId` | Monospace ID or request ID with a copy button |
| `Field`, `Button` | Persistent label, hint, inline error; 44 px targets; pending label |
| `AvailabilityBanner` | Scope, impact, last successful time, recovery action |
| `StateView` | One component for loading, empty, error, unavailable, forbidden, not-found and rate-limited (section 9) |
| `LiveRegion` | Polite announcements for refreshes and errors; no repeated noise |

## 8. Evidence display rules (non-negotiable)

- `ModelOutputPanel` heading: "Model output (uncalibrated)". Body text: "Native scores from the pinned experimental model. They are not probabilities, not a risk score, and the model is not validated on KAVACH data."
- It shows the three labels as a table with values to 4 decimals and the model's top label as text. There is no percentage, bar, gauge, colour scale or ranking colour.
- `truncated: true` adds "The message was longer than the model reads; only the first part was scored."
- The tier always shows as "Unknown: no calibrated signal". `final_score`, `sms_score`, `base_score` and `fusion_score` show "Not available"; never `0` and never "safe".
- A stage with `model_output: null` shows its reason:
  - `model_not_deployed`: "Model not enabled"
  - `model_unverified`: "Model files failed verification"
  - `worker_unavailable`: "Model worker unavailable"
  - `inference_timeout`: "Model timed out"
  - `worker_crashed`: "Model worker stopped"
  - `invalid_model_output`: "Model returned an invalid result"
  - `deadline_exhausted`: "Request deadline reached"
  - `audio_not_provided`: "No audio provided"
  - anything else: "Unavailable (`<code>`)"
- No message text exists to show: the detail page states "Message text is not retained (7-day evidence retention, no raw content)".
- `/system` shows `validated_on_kavach_data: false` as "Not validated on KAVACH data", next to readiness: "Ready means the model loaded and passed its self-test; it says nothing about accuracy".
- If the M4-Q decision is CONDITIONAL and the owner enables the model, the named shortfalls are shown on `/system` and in `ModelOutputPanel` (text supplied with the decision record, MVP-B2).

## 9. Error and state mapping

| Response | Presentation | Action |
| --- | --- | --- |
| Loading (first) | Region skeleton plus "Loading…", `aria-busy` | — |
| Background refresh | Keep content; "Last updated hh:mm" | — |
| Empty history | "No SMS incidents in the last 7 days." Admins get a hint once `/analyze` exists | — |
| No filter matches | Keep filters; "No incidents match these filters" | Clear filters |
| 400 `INVALID_CURSOR` | "The list changed; reload from the start" | Restart list |
| 401 `SESSION_EXPIRED` | Clear memory; go to login | Sign in |
| 401 `MIXED_CREDENTIALS` | Treated as a client bug: generic error with request ID | Reload |
| 403 `FORBIDDEN` | "You don't have access to this page" (no protected data rendered) | Back to overview |
| 403 `CSRF_REJECTED` | "Request blocked for safety; reload the page" | Reload |
| 404 `NOT_FOUND` (detail) | "Incident unavailable or expired" | Back to history |
| 422 `VALIDATION_ERROR` | Inline field errors from client validation; the server message as fallback | Fix the filter |
| 429 `RATE_LIMITED` | "Too many requests; resuming in N s"; polling paused | Automatic after `Retry-After` |
| 503 `DEPENDENCY_UNAVAILABLE` | `AvailabilityBanner`: "Service temporarily unavailable"; keep stale data labelled "may be out of date" | Retry |
| 500 `INTERNAL_ERROR` or unexpected | "Something went wrong", request ID | Retry |
| Network failure or timeout | "Can't reach the server"; keep stale data | Retry |
| Model `disabled` | "SMS model not enabled. Incidents are stored with analysis unavailable." | — |
| Model `starting` | "SMS model starting" | — |
| Model `unavailable` | "SMS model unavailable" plus the reason text | — |

Client-side validation mirrors the server rules: tier enum; `from` and `to` need a timezone; `from` before `to`. The server stays authoritative.

## 10. Security and privacy rules for the frontend

- No raw communications, tokens or credentials in storage, URLs, logs, analytics or error reports. No `console.log` of responses in production code (lint rule).
- No `dangerouslySetInnerHTML`. Every value renders as text through React.
- Same-origin only: no CORS, no absolute API URLs, no third-party requests, fonts or CDNs. A Content Security Policy is planned for the serving proxy (M11); the app must work under `default-src 'self'`.
- Development uses the Vite proxy (`/api` → FastAPI) on the origin set in `APP_ORIGIN`, so cookies and the Origin check behave as in deployment.
- On sign-out or 401, every cached incident and model value is dropped from memory.
- `/analyze` (MVP-F3): the text field is component state only. It is cleared after a receipt and never put in the URL, storage or logs. The `event_id` is `ui-` plus `crypto.randomUUID()` (never `Math.random`), generated once per submission and reused for a manual retry. The `subscriber_token` is `ui-sub-` plus a random value. The form explains it is for synthetic messages only.

## 11. Test strategy

| Layer | Tool | What it proves |
| --- | --- | --- |
| Type-check | `tsc --noEmit` (strict, `noUncheckedIndexedAccess`) | Contract types used correctly; no `any` without a comment |
| Contract | Generated types are not stale against `contract/openapi.json` (CI regenerates and diffs); or the hand-written key comparison | Frontend shapes equal backend shapes |
| Unit | Vitest | API client: error parsing, request-ID capture, `Retry-After` handling, 429 pause, no retry on 429 or mutations, timeout. Filter URL encoding and decoding. Timestamp formatting with timezone. `ui-` ID format and uniqueness |
| Component | Vitest + Testing Library + jsdom; fake `fetch` injected | Every row of the section 9 table renders its state; `ModelOutputPanel` shows no percentage or colour scale and states the uncalibrated wording; unknown tier never shows a score; route guards; focus stays put on refresh; live-region announcements |
| Privacy | Vitest | After each journey, `localStorage`, `sessionStorage` and `document.cookie` (HttpOnly not visible) hold nothing; no response body is ever logged |
| Build | `vite build` plus a scan script | The bundle has no `kvk_`, no `Authorization`, no test-double module and no absolute API origin |
| Browser journeys | Playwright against the **real** backend, PostgreSQL and Redis (no mocks), for joint acceptance | Login, expiry, logout; viewer, analyst and admin; history paging and filters; detail with model disabled; degraded states (Redis down → 503 banner, read limit → 429); 404; keyboard-only path; axe checks |
| Accessibility | axe in Playwright plus a manual keyboard and screen-reader pass | WCAG 2.2 AA items in DESIGN.md; 320 px reflow; 200% zoom |
| CI | A new frontend job: install from the lockfile, lint, type-check, unit and component tests, build, bundle scan | Every push to `frontend` |

Fixtures used in component tests are clearly synthetic, live only under test paths, and use the documented shapes. They never stand in for model output at runtime.

## 12. Milestones

| ID | Deliverable | Acceptance |
| --- | --- | --- |
| MVP-F1 | Scaffold, lockfile, CI job, tokens, API client and types, `AppShell`, `StateView`, login, logout, session restore, route guards | Type-check, lint, tests and build pass; login journey against the real backend; no storage use |
| MVP-F2 | Overview, SMS history (filters, paging), incident detail, system page, every section 9 state | Component tests for every state; Playwright: viewer reads history and detail; degraded banners shown with real Redis down and model disabled |
| MVP-F3 | `/analyze` (admin), **after MVP-B4 is implemented and its OpenAPI is pinned** | Admin submits a synthetic SMS and opens its incident; viewer and analyst get no route and the server returns 403; retry reuses the ID; text never persists |
| MVP-J | Joint acceptance with the backend | INTEGRATION_PLAN.md checklist |

## 13. Open items

- The "Controlled demonstration" and environment label text, and the user-facing reason strings in section 8, are proposals for owner review.
- Which docs reach `frontend` (section 14.4, item 3).

## 14. MVP-F1 exact setup (for the owner's review; nothing installed)

### 14.1 What the `frontend` branch has today

`origin/frontend` is at `754a22a`, the first commit. Its `docs/API.md` predates the MVP-1 contract. It has no workflow file (only `.github/workflows/.gitkeep`) and an empty `frontend/` (`.gitkeep`). Its `.gitignore` already ignores `node_modules/`, `dist/`, `build/`, `coverage/`, `playwright-report/`, `test-results/` and `.env*`.

### 14.2 Exact versions

Rules used:
- the newest stable release published **before 26 October 2026**, at least 14 days before this plan
- mutually compatible peer and engine ranges on Node 24.16.0
- not deprecated
- no OSV advisory on 9 Nov 2026 (OSV batch query of the direct packages)
- no install script in any direct package

Transitive packages are checked with `npm audit` once the lockfile exists.

| Package | Version | Licence | Why this version |
| --- | --- | --- | --- |
| react / react-dom | 19.3.1 | MIT | Latest 19.x |
| react-router | 8.5.0 | MIT | 8.5.1 is under 14 days old |
| vite | 8.3.5 | MIT | 8.3.6 is under 14 days old |
| @vitejs/plugin-react | 6.1.2 | MIT | 6.2.x is under 14 days old; peer `vite ^8` |
| typescript | **5.9.3** | Apache-2.0 | `typescript-eslint` needs `<6.1` and `openapi-typescript` needs `^5.x`, so 6.x and 7.x are excluded |
| vitest | 5.0.5 | MIT | Peer `vite ^8`; 5.1.0 is under 14 days old |
| jsdom | 30.1.3 | MIT | 31.0.0 is under 14 days old; needs Node `^24.15` |
| @testing-library/react | 16.3.3 | MIT | |
| @testing-library/dom | 10.4.2 | MIT | Peer of the two packages above and below |
| @testing-library/user-event | 14.6.8 | MIT | |
| @testing-library/jest-dom | 7.0.1 | MIT | Peer `vitest >=0.32` |
| @playwright/test | 1.64.1 | Apache-2.0 | 1.65.0 is under 14 days old |
| @axe-core/playwright | 4.14.0 | **MPL-2.0** | Dev-only; weak copyleft, never bundled |
| eslint | 10.13.0 | MIT | 10.14.0 is under 14 days old |
| @eslint/js | 10.0.1 | MIT | Peer `eslint ^10` |
| typescript-eslint | 8.72.0 | MIT | Peer `eslint ^10`, `typescript <6.1` |
| eslint-plugin-react-hooks | 7.1.1 | MIT | |
| globals | 17.13.0 | MIT | |
| openapi-typescript | 7.13.0 | MIT | Has `--check` (verified in its packaged CLI source) |
| @types/react / @types/react-dom | 19.3.0 | MIT | |
| @types/node | 24.19.2 | MIT | Matches Node 24 |

### 14.3 Files Claude writes (after the owner switches to `frontend` and authorizes F1)

**`frontend/package.json`**

```json
{
  "name": "kavach-frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "engines": { "node": ">=24.15.0 <25" },
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "typecheck": "tsc --noEmit",
    "lint": "eslint . --max-warnings=0",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:e2e": "playwright test",
    "api:types": "openapi-typescript contract/openapi.json --output src/lib/api/schema.d.ts",
    "api:check": "openapi-typescript contract/openapi.json --output src/lib/api/schema.d.ts --check",
    "scan:bundle": "node scripts/scan-bundle.mjs",
    "verify": "npm run api:check && npm run lint && npm run typecheck && npm test && npm run build && npm run scan:bundle"
  },
  "dependencies": {
    "react": "19.3.1",
    "react-dom": "19.3.1",
    "react-router": "8.5.0"
  },
  "devDependencies": {
    "@axe-core/playwright": "4.14.0",
    "@eslint/js": "10.0.1",
    "@playwright/test": "1.64.1",
    "@testing-library/dom": "10.4.2",
    "@testing-library/jest-dom": "7.0.1",
    "@testing-library/react": "16.3.3",
    "@testing-library/user-event": "14.6.8",
    "@types/node": "24.19.2",
    "@types/react": "19.3.0",
    "@types/react-dom": "19.3.0",
    "@vitejs/plugin-react": "6.1.2",
    "eslint": "10.13.0",
    "eslint-plugin-react-hooks": "7.1.1",
    "globals": "17.13.0",
    "jsdom": "30.1.3",
    "openapi-typescript": "7.13.0",
    "typescript": "5.9.3",
    "typescript-eslint": "8.72.0",
    "vite": "8.3.5",
    "vitest": "5.0.5"
  }
}
```

**`frontend/.npmrc`**: exact saves, engine enforcement, no lifecycle scripts (no direct package needs one; a transitive one that does is reported, not silently allowed):

```ini
save-exact=true
engine-strict=true
ignore-scripts=true
fund=false
```

**`frontend/.nvmrc`**: `24.16.0`

**`frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "types": ["vite/client"],
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "noImplicitOverride": true,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "useDefineForClassFields": true,
    "skipLibCheck": true,
    "noEmit": true
  },
  "include": ["src", "tests", "scripts", "vite.config.ts", "playwright.config.ts"]
}
```

**`frontend/vite.config.ts`**: same-origin development through the proxy. `Origin` passes through unchanged (`changeOrigin: false`), so the backend's exact `APP_ORIGIN` check behaves as in deployment.

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const api = { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } };

export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy: api },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true, proxy: api },
  build: { sourcemap: false },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
    restoreMocks: true,
  },
});
```

**`frontend/eslint.config.js`**: `@eslint/js` recommended, `typescript-eslint` `strictTypeChecked`, `react-hooks` recommended, browser globals, plus project rules:
- `no-console: error`
- `@typescript-eslint/no-explicit-any: error`
- `no-restricted-globals` for `localStorage`, `sessionStorage` and `indexedDB`
- `no-restricted-syntax` for any `dangerouslySetInnerHTML` JSX attribute and any `Math.random` call
- `no-restricted-imports` so runtime files cannot import `**/__tests__/**`, `src/test/**` or `tests/**`

**`frontend/playwright.config.ts`**: Chromium only for MVP-1, `baseURL: "http://127.0.0.1:5173"`, `webServer` running `npm run dev`. The **real backend is started separately** (section 14.5); Playwright never mocks the API.

**`frontend/scripts/scan-bundle.mjs`**: fails if `dist/` contains `kvk_`, `Authorization`, `Bearer `, `localStorage`, `sessionStorage`, `http://` or `https://` absolute API origins, or any test module path.

**`frontend/index.html`, `src/main.tsx`, `src/app/*`, `src/lib/api/*`, `src/components/*`, `src/styles/tokens.css` (DESIGN.md values), `src/test/setup.ts`** (imports `@testing-library/jest-dom/vitest`): as in sections 3–7.

**`.github/workflows/frontend-ci.yml`** (proposed): on push to `frontend` and pull requests into `dev` and `main` touching `frontend/**`; `contents: read`, no secrets, no persisted credentials, SHA-pinned actions, 15-minute timeout:
- `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1` (the same pin as backend CI)
- `actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1  # v7.1.0` with `node-version-file: frontend/.nvmrc` and the npm cache keyed on `frontend/package-lock.json`
- steps: `npm ci`, `npm audit --audit-level=high`, `npm run verify`

Playwright journeys are not in this job: they need the real backend stack and run at joint acceptance.

### 14.4 Contract and docs transfer

1. On `backend`, after the owner commits the current work: note the commit hash `<B>`.
2. On `frontend`, the owner (or Claude, on instruction) writes the file from Git, not from a working copy:

   ```sh
   git show <B>:backend/contract/openapi.json > frontend/contract/openapi.json
   shasum -a 256 frontend/contract/openapi.json
   ```

   `frontend/contract/SOURCE.md` records `<B>`, the date and that SHA-256. Recopy after every approved backend contract change (next: MVP-B4).
3. **Docs (decision):** `frontend` has the old `docs/API.md`. Recommended: copy only `docs/FRONTEND_MVP1_PLAN.md` from `<B>` the same way, and read API.md through `git show <B>:docs/API.md`. Copying API.md itself would create a second copy that can drift and conflict at the `dev` merge.

### 14.5 Initial commands, in order

| Step | Who | Command (from the repository root unless noted) |
| --- | --- | --- |
| 1 | Owner | Commit the backend work; `git switch frontend` |
| 2 | Owner or Claude | Contract and plan transfer (14.4) |
| 3 | Claude | Write the files in 14.3 (no `npm create`: no template clutter) |
| 4 | Claude, after approval | `cd frontend && fnm use` (reads `.nvmrc`; `node --version` must print v24.16.0) |
| 5 | Claude, after approval | `npm install` (exact versions from `package.json`; creates `package-lock.json`) |
| 6 | Claude | `npm audit --audit-level=high` (report any finding; no `audit fix --force`) |
| 7 | Claude, after approval | `npx playwright install chromium` (downloads the browser binary, about 150 MB, into the user cache; not into Git) |
| 8 | Claude | `npm run api:types`, then `npm run verify` |
| 9 | Claude | Report: files, exact command outputs, lockfile package count, audit result |
| 10 | Owner | Review; commit `frontend/` (including `package-lock.json` and the generated `src/lib/api/schema.d.ts`) and the workflow; push; first CI run |

**Local run for journeys** (joint acceptance; from `backend/` with the dev services):

```sh
APP_ENV=development APP_ORIGIN=http://127.0.0.1:5173 <other required settings from .env> \
  uv run --project . --locked uvicorn kavach.main:create_app --factory \
  --host 127.0.0.1 --port 8000 --no-proxy-headers
```

`APP_ORIGIN=http://127.0.0.1:5173` with `APP_ENV=development` selects the documented non-Secure loopback cookie `kavach_dev_session`. Every request reaches the backend from the proxy at 127.0.0.1, so all local users share the login IP ceiling. That is acceptable for development only; deployment uses a real reverse proxy with `--forwarded-allow-ips` (README).

### 14.6 F1 acceptance

- `npm run verify` passes: types fresh, lint clean, strict type-check, unit and component tests, build, bundle scan.
- `npm audit` has no high or critical finding, or any finding is reported with a decision.
- Against the real local backend: sign in, reload (session restored from `GET /auth/session`), sign out. The browser shows no storage use (DevTools check plus the privacy test).
- Every `StateView` variant has a component test.
- The report lists exact commands and results; anything not run is marked "not run" with the reason.
