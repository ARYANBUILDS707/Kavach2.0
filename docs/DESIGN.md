# KAVACH Design and UX Specification

## Authority and direction

Follow [PRD.md](PRD.md). D09 left the visual identity open; on 9 Nov 2026 the owner approved a visual language adapted from their Srujana reference site (srujanacu.in): warm paper and ink, thick ink outlines, hard offset shadows, pill controls, rounded cards, bright accent fills, tight display type and a monospace voice for labels and numbers. [`frontend/src/styles/tokens.css`](../frontend/src/styles/tokens.css) holds the exact values and is authoritative for them; this document records the same values and the rules for using them.

The identity is expressive, but the evidence rules do not change: readable timelines, honest uncertainty and text-first status. No animated risk meters, gauges, probability bars or colour scales for model output; accent colour never encodes a risk judgement on its own. Large colour tiles are allowed only for record counts that come from loaded API data and say what they count.

The persistent header identifies KAVACH, the active environment, the user's role, and pipeline status. A visible “Controlled demonstration” label distinguishes simulated data. “Critical” means review urgency, not proof of fraud or permission to intervene.

## Color tokens

Light is the default; dark follows the system preference unless the in-page toggle chooses otherwise. The toggle keeps the choice in memory only (no browser storage), so a reload returns to the system preference.

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| Paper (canvas) | `#F5F0E6` | `#15130F` | Page background |
| Paper 2 | `#ECE4D3` | `#211E19` | Quiet panels, table header, empty states, unknown badge |
| Paper 3 | `#E2D8C3` | `#302B24` | Pressed and hover fills |
| Card (surface) | `#FBF8F1` | `#1D1A16` | Cards, fields, tables |
| Ink (text primary) | `#17140F` | `#F3EDE1` | Headings, body, primary button fill |
| Ink 2 (text secondary) | `#4E473C` | `#B9B0A0` | Supporting text, labels |
| Line (control border) | `#17140F` | `#CFC6B6` | Card, field and button outlines |
| Rule (subtle border) | ink at 14% | cream at 15% | Row and list separators |
| Shade | `#17140F` | `#000000` | Hard offset shadows |
| Link | `#1F45D9` | `#9DB0FF` | Inline links |
| Focus | `#2E5BFF` | `#8FA6FF` | 3 px focus outline; 4 px focus ring on fields |
| Info | `#1F2D6B` on `#DCE5FF` | `#D5DDFF` on `#1D2552` | Information banners |

Accents keep their hue in both themes and always carry fixed text colours: ink `#17140F` on saffron `#FF5B1F`, mint `#19B47E`, sun `#FFC83D` and pink `#FF9BBB`; cream `#F5F0E6` on blue `#2E5BFF`. Accents are decoration and grouping (summary tiles, landing cards, highlights, the timeline node), never a risk signal on their own.

| Status pair | Light (text on fill) | Dark (text on fill) | Use |
| --- | --- | --- | --- |
| Low · complete · ready | `#0B5C40` on `#D3F2E4` | `#8FF0C8` on `#12372A` | Low tier, completed analysis, model ready |
| Medium · partial · starting | `#5C4300` on `#FFF1C9` | `#FFDC85` on `#3A2F12` | Medium tier, partial analysis, model starting |
| High | `#7A2606` on `#FFE0D1` | `#FFC09B` on `#3D2314` | High tier |
| Critical/error · unavailable model | `#6B1A0E` on `#FFD9CF` | `#FFB7A3` on `#3B1A12` | Critical tier, actual failures, model unavailable |
| Unknown · analysis unavailable · disabled | ink on Paper 2, dashed outline | same | Missing assessment or stage, model disabled |

Always pair color with text and, where useful, a simple icon. A risk badge and a processing-error banner must have different labels and placement. Unknown and unavailable use a dashed outline so absence reads differently from a result. Verify contrast in implementation (automated checks run on every page in both themes). Do not encode unknown as green or zero.

## Typography

Three self-hosted typefaces, served from `frontend/public/fonts/` (latin subset, `woff2`) so no visitor request reaches a third-party font service. All three are under the SIL Open Font License 1.1; the licence texts ship beside the files (`OFL-*.txt`). Sources, versions and SHA-256 hashes are recorded in [ASSET_PROVENANCE.md](ASSET_PROVENANCE.md).

| Role | Family | Weights | Use |
| --- | --- | --- | --- |
| Display | Bricolage Grotesque (variable, optical size) | 400–800, headings at 800 | Headings, summary numbers, wordmark |
| Body | Instrument Sans (variable) | 400–700 | Prose, labels, buttons (700) |
| Mono | JetBrains Mono (variable) | 500–700 | Eyebrow labels, table headers, IDs, timestamps in metadata, policy score |

Scale: body 16 px / 1.55; metadata 14 px / 1.45; eyebrow 12 px mono, uppercase, +0.1 em tracking; section title `clamp(1.4rem, 1.1rem + 1.2vw, 1.9rem)` / 1.05; page title `clamp(2.3rem, 1.6rem + 3.6vw, 4rem)` / 0.95; landing hero `clamp(2.8rem, 1.4rem + 6.4vw, 6rem)` / 0.92. Display headings use −0.035 em tracking (hero −0.045 em) and balanced wrapping. Keep body prose within about 72 characters per line. IDs use the mono face with tabular numerals and wrap safely; never hide the only available identification behind truncation.

Display scores as `0.73` with the signal name and availability. Label final values “Policy risk score,” not “73% probability of fraud.” Show “Not available” for null. Dates include timezone; use the viewer's local display with an accessible exact UTC value. Label event time separately from received time.

## Spacing and layout

Spacing scale 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 96 px. Page gutter 16 px on phones, 24 px from 700 px, 32 px from 1100 px. Content maximum width 1160 px, centered. Header minimum height 64 px; it is sticky with a translucent paper background. Form content maximum width 640 px; the sign-in card maximum width 480 px.

Shape: cards use a 2.5 px line border, 22 px radius and a hard `0 4px 0` shade shadow (6 px when lifted); controls use a 2 px line border; buttons and badges are pills; fields use a 12 px radius. Buttons, fields and navigation pills are at least 40–48 px tall (44 px minimum touch target except compact header pills at 40 px). Tables may use 48 px rows on desktop. Layout follows content; avoid fixed panel heights that clip evidence. Desktop incident detail uses about 1.7 : 1 evidence to assessment, with the assessment column sticky; below 1024 px stack evidence, assessment, then related incidents.

## Reusable components

| Component | Contract |
| --- | --- |
| App shell | Sticky header: wordmark (to Overview), environment label, navigation pills, model status pill, user and role, theme toggle, sign-out; skip link; main landmark; compact footer |
| Wordmark | One-stroke shield mark with a saffron point beside “KAVACH”; decorative SVG hidden from assistive technology |
| Page header | Mono eyebrow, display h1 whose accessible name is the plain title, optional lead, relevant actions only |
| Section heading | Optional eyebrow and h2 |
| Card | Surface, line border, 22 px radius, hard shadow; `card-interactive` lifts on hover only where the card is a destination |
| Risk badge | Enum label including unknown; pill; no animation |
| Status pill / badge | Text label with a dot; model state links to System |
| Signal summary | Signal name, nullable score, model version, duration and missing reason |
| Availability banner | Scope, impact, last known time, recovery action |
| Incident table | Semantic headers, explicit row links, stable ordering, pagination; mono uppercase headers; becomes labelled cards below 768 px |
| Evidence timeline | Events on a dashed rule with a node per event; event/arrival times, channel, structured reasons, related incident links |
| Facts list | Label/value rows separated by rules; stacks label above value below 600 px |
| Link evidence | Subscriber match, event-time delta, contextual eligibility and uncertainty |
| Review form/history | Decision, optional note, revision-aware save, attributable history |
| Field | Persistent label, hint, required marker, associated validation message; focus ring |
| Button | Primary (ink fill, saffron on hover), secondary (outline, ink fill on hover), destructive only for real destructive operations; pending label; scales to 0.97 when pressed |
| Theme toggle | Round outlined button; in-memory choice only |
| Empty/error state | Clear cause, preserved context, one relevant recovery action; empty states use a dashed border on a dot grid |
| Status announcement | Polite live region for saves and refreshes; no repeated feed noise |
| Site footer | Full version on public pages; one line inside the app |

Reuse native controls first. Introduce a component dependency only when it solves a tested accessibility need. Tooltips supplement visible labels; never place essential evidence only in hover content.

## Navigation and forms

Primary destinations: Overview, Incidents, System, and Analyze SMS for admins only. The wordmark returns to the console Overview. The console lives under `/admin` and is not linked from the public site, which has its own header (About, Platform, Capabilities, Status and an Examples button) and no sign-in or sign-up link. Detail view includes a back link preserving feed filters in the URL. Sign-out is in the header; below 1200 px the navigation and tools fold behind a Menu disclosure that closes on navigation or Escape. From 1200 px the header is one fixed-height row: navigation does not wrap and a long display name is shortened at 24 characters with the full name as its tooltip (the role label always shows), so the sticky detail assessment column is never covered. No navigation item implies unavailable features. The public pages are `/` (the product page) and `/examples` (recorded examples): no session, no API requests, no sign-up and no cookies. The operator sign-in is `/admin/login`; it links back to the public site, and the public site never links to it. Decision C-14; see [PUBLIC_SITE_DESIGN.md](PUBLIC_SITE_DESIGN.md).

Use visible labels, clear constraints before submission, and inline errors after interaction. Server validation remains authoritative. Do not echo passwords or raw communications in error text. Simulator SMS input is transient and explicitly synthetic-only; call choice is an allowlisted sample selector, not an upload control. Review notes warn against including phone numbers, OTPs, or raw transcripts.

Keep review submission disabled while saving, show “Saving review…”, and announce success only after durable confirmation. On conflict, retain the draft, refetch history, and ask the analyst to compare before retrying. Do not automatically resubmit against a new revision. No localStorage persistence of evidence or form drafts.

## Page layouts

### Sign in

A brand panel beside a single form card (stacked on phones): environment label, username/password, submit action, generic credential error, and a link to the public product page. No public signup/reset flow. State that account access is provided by the deployment operator. Expiry redirects here without exposing evidence in the URL.

### Incident feed

Page title and live/stale indicator; filter row; result count labeled incident records; semantic table with event time, incident ID, kind, tier, analysis status, latest review and open action. Explain that pair and standalone records can share evidence. Default newest event time first. New arrivals show “New updates available” while the analyst is reading; refresh does not move keyboard focus or reorder rows underneath interaction.

### Incident detail

Header shows ID, kind, risk tier, review state and assessment revision. Evidence timeline comes first, followed by independent signals and the pair explanation where applicable. Show structured excerpts only if explicitly approved later; MVP has no raw transcript/audio playback. Review form and history appear beside or below evidence. If reviewed assessment is older than the current revision, display “Evidence updated since this review.”

### Simulator

Explain the scenario and expected qualitative behavior; select a scenario/sample; submit events; show individual receipts and related incident links. Handle partial scenario success without resending completed events with new IDs. Clearly distinguish expected behavior from actual model output.

### System

Show dependency/model states, versions, last check, and actionable degradation reasons. Show raw-data retention policy and demo limitations as brief text. Do not expose configuration secrets, filesystem paths, provider credentials, or detailed stack traces.

## State system

| Situation | Required presentation |
| --- | --- |
| Initial load | Stable skeleton/region-level pending text; mark busy |
| Background refresh | Preserve prior content; show last updated timestamp |
| Empty feed | Explain no events; admin gets simulator link |
| No filter matches | Preserve filters; offer clear filters |
| No reviews | “No analyst review yet”; form if authorized |
| Partial analysis | Available scores plus named missing stages and impact |
| WebSocket disconnected | “Live updates paused”; polling/retry state and last refresh |
| API failure | Safe message, retry action, request ID; retain stale data with label |
| Unauthorized/forbidden | Login or access explanation; remove protected data from memory |
| Missing/expired incident | “Incident unavailable or expired”; back to feed |
| Rate limited | Retry-after guidance; prevent rapid repeated submission |

## Interaction and accessibility

Motion is short and physical: buttons scale to 0.97 when pressed, destination cards lift and tilt slightly on hover, the accordion marker rotates, and pages fade in over about 360 ms using the reference easing curves. On the public page only: a slowly scrolling ticker band (pauses on hover, decorative and hidden from assistive technology), a gently floating hero mark, a pulsing status dot, and scroll reveals done with CSS view timelines that finish while a section is still entering. The three continuous animations (ticker, hero mark, status dot) are governed together by one "Pause motion" button in the hero, placed before the ticker in reading order (WCAG 2.2.2). It is a standard secondary button, reachable with Tab and operated with Enter, Space or a click. Activating it pauses all three where they are and relabels it "Resume motion"; activating it again resumes them. Because the visible label carries the state, the button is not also marked `aria-pressed`. The choice lasts for the visit only, in memory with no browser storage, and does not affect scrolling, links or the ticker's own hover pause. Scroll reveals finish while entering and are not continuous, so the control does not govern them. No animated counters, gauges or risk meters, auto-playing audio, flickering alerts, or auto-scrolling feeds. Under reduced motion every animation and transition is off and all content is shown; nothing moves, so the motion control is not shown. Dialogs, if necessary, manage focus and return it to the trigger; inline errors are preferred for routine failures.

Target WCAG 2.2 AA: semantic landmarks/headings/tables, keyboard access, visible focus, no keyboard traps, 4.5:1 normal text contrast, 3:1 relevant non-text contrast, labeled controls, descriptive link names, 200% zoom, reflow at 320 CSS px, and textual errors linked to controls. Test with keyboard and a screen reader in addition to automated checks.

At 320–767 px, use stacked filter fields and incident summaries that preserve all essential fields and a clear detail link. Horizontal scrolling is allowed for genuinely tabular evidence only within a labeled region. Below 1200 px the header uses the Menu disclosure; at 768–1023 px detail is single-column; ≥1024 px detail is split. Never hide risk, uncertainty, review result, or save controls because of viewport width.

## Local public analyzer — 13 November 2026

`/analyze` sits outside the session provider and uses existing public header, footer, button,
field and card styles. It checks only the anonymous availability endpoint. The form stays disabled
when hosting is not authorized; local fictional tests can submit without login. Pending submissions
cannot be repeated; editing clears stale results; success clears text; errors retain the in-memory
draft. No cookies, browser storage, text in URLs, automatic retries or score gauges. Predictions
are labeled experimental/unvalidated, with truncation and stage/total timing. “Legitimate” never
means safe. Hosted inference remains unavailable until C-15 and launch checks pass.

Public scroll reveals translate content while preserving full opacity, so stopping mid-scroll
never leaves readable text below its required contrast. Time-based page entrances are unchanged.
