# KAVACH Design and UX Specification

## Authority and direction

Follow [PRD.md](PRD.md). This is a proposed design under D09; the source handbook specifies dashboard evidence but no visual identity. Build a calm investigation workspace with readable timelines, compact tables, and explicit uncertainty. Prioritize evidence over decorative charts. Avoid gradients, glass panels, glowing threat maps, oversized metric cards, and animated risk meters.

The persistent header identifies KAVACH, the active environment, the user's role, and pipeline status. A visible “Controlled demonstration” label distinguishes simulated data. “Critical” means review urgency, not proof of fraud or permission to intervene.

## Color tokens

| Token | Value | Use |
| --- | --- | --- |
| Canvas | `#F5F7F9` | Application background |
| Surface | `#FFFFFF` | Main content and fields |
| Text primary | `#17212B` | Headings and body |
| Text secondary | `#475569` | Supporting information |
| Border subtle | `#CBD5E1` | Nonessential separators |
| Border control | `#64748B` | Interactive field outlines |
| Action | `#174EA6` | Primary buttons and links |
| Action hover | `#123D82` | Hover state |
| Focus | `#1D4ED8` | Visible outer focus ring |
| Low | `#166534` on `#F0FDF4` | Low risk text badge |
| Medium | `#854D0E` on `#FEFCE8` | Medium risk text badge |
| High | `#9A3412` on `#FFF7ED` | High risk text badge |
| Critical/error | `#991B1B` on `#FEF2F2` | Critical badge or actual failure message |
| Unknown | `#475569` on `#F1F5F9` | Missing assessment |

Always pair color with text and, where useful, a simple icon. A risk badge and a processing-error banner must have different labels and placement. Verify contrast in implementation; use control borders rather than subtle separators wherever boundary contrast is necessary. Do not encode unknown as green or zero.

## Typography

Use the operating system sans-serif stack; no external font service. Body 16 px/24 px; compact metadata 14 px/20 px; page title 28 px/36 px; section title 20 px/28 px; component title 16 px/24 px semibold. Use 400/600 weights. IDs and timestamps may use a system monospace face with tabular numerals. Keep body prose within 75 characters per line. Wrap long identifiers safely; never hide the only available identification behind truncation.

Display scores as `0.73` with the signal name and availability. Label final values “Policy risk score,” not “73% probability of fraud.” Show “Not available” for null. Dates include timezone; use the viewer's local display with an accessible exact UTC value. Label event time separately from received time.

## Spacing and layout

Use the spacing scale 4, 8, 12, 16, 24, 32, 48 px. Desktop content padding 32 px; tablet 24 px; phone 16 px. Header minimum height 64 px. Content maximum width 1440 px, centered. Sidebar 224 px at widths ≥1024 px; below this use an accessible navigation disclosure. Form content maximum width 640 px; login maximum width 400 px.

Use 8 px component radius, 1 px borders, and shadows only for floating overlays. Buttons/inputs have at least 44 px touch targets. Tables may use 48 px rows on desktop. Layout follows content; avoid fixed panel heights that clip evidence. Desktop incident detail uses approximately two-thirds evidence and one-third review; below 1024 px stack evidence, assessment, then review.

## Reusable components

| Component | Contract |
| --- | --- |
| App shell | Environment/role/status header, navigation, skip link, main landmark |
| Page header | Title, brief context, relevant actions only |
| Risk badge | Enum label including unknown; no animation |
| Signal summary | Signal name, nullable score, model version, duration and missing reason |
| Availability banner | Scope, impact, last known time, recovery action |
| Incident table | Semantic headers, explicit row links, stable ordering, pagination |
| Evidence timeline | Event/arrival times, channel, structured reasons, related incident links |
| Link evidence | Subscriber match, event-time delta, contextual eligibility and uncertainty |
| Review form/history | Decision, optional note, revision-aware save, attributable history |
| Field | Persistent label, hint, required marker, associated validation message |
| Button | Primary, secondary, destructive only for real destructive operations; pending label |
| Empty/error state | Clear cause, preserved context, one relevant recovery action |
| Status announcement | Polite live region for saves and refreshes; no repeated feed noise |

Reuse native controls first. Introduce a component dependency only when it solves a tested accessibility need. Tooltips supplement visible labels; never place essential evidence only in hover content.

## Navigation and forms

Primary destinations: Incidents, Simulator for admins, System. Logo returns to Incidents. Detail view includes a back link preserving feed filters in the URL. Logout is available from the user menu. No navigation item implies unavailable features.

Use visible labels, clear constraints before submission, and inline errors after interaction. Server validation remains authoritative. Do not echo passwords or raw communications in error text. Simulator SMS input is transient and explicitly synthetic-only; call choice is an allowlisted sample selector, not an upload control. Review notes warn against including phone numbers, OTPs, or raw transcripts.

Keep review submission disabled while saving, show “Saving review…”, and announce success only after durable confirmation. On conflict, retain the draft, refetch history, and ask the analyst to compare before retrying. Do not automatically resubmit against a new revision. No localStorage persistence of evidence or form drafts.

## Page layouts

### Sign in

Single centered form, environment label, username/password, submit action, generic credential error. No public signup/reset flow. State that account access is provided by the deployment operator. Expiry redirects here without exposing evidence in the URL.

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

Use 120–180 ms color/opacity transitions only. No animated counters, auto-playing audio, flickering alerts, or auto-scrolling feeds. Respect reduced-motion preferences. Dialogs, if necessary, manage focus and return it to the trigger; inline errors are preferred for routine failures.

Target WCAG 2.2 AA: semantic landmarks/headings/tables, keyboard access, visible focus, no keyboard traps, 4.5:1 normal text contrast, 3:1 relevant non-text contrast, labeled controls, descriptive link names, 200% zoom, reflow at 320 CSS px, and textual errors linked to controls. Test with keyboard and a screen reader in addition to automated checks.

At 320–767 px, use stacked filter fields and incident summaries that preserve all essential fields and a clear detail link. Horizontal scrolling is allowed for genuinely tabular evidence only within a labeled region. At 768–1023 px use compact navigation and single-column detail; ≥1024 px use sidebar and split detail. Never hide risk, uncertainty, review result, or save controls because of viewport width.
