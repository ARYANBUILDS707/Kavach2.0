# KAVACH Release Checklist

A release is a PR from `dev` to `main` followed by an annotated tag, each requiring explicit owner approval ([GIT_WORKFLOW.md](GIT_WORKFLOW.md)). This is a blank procedure: copy it into the release report and mark every line `pass`, `fail` or `not run` with evidence (command and output, or reason). Do not tick a box from memory. Do not mark the procedure itself complete in this file.

Release scope (choose one and state it in the report): **local demo**, **research host**, or **authorized pilot**. A pilot additionally needs D10, legal/privacy review and operating authority, which are outside engineering sign-off.

## 1. Preconditions

- [ ] All milestones intended for the release are `complete (verified)` in [MILESTONE_TRACKER.md](MILESTONE_TRACKER.md).
- [ ] Open critical/high findings: none. Open medium/low findings listed with follow-ups.
- [ ] Relevant decisions (D01–D10) recorded as approved for this release scope.
- [ ] `dev` contains only reviewed, merged PRs (no direct pushes); working tree clean; release commit identified (full hash).
- [ ] Branch protection for `main` and `dev` applied by then (it is decided in principle, not yet applied); if not, state that explicitly.

## 2. Reproducibility

- [ ] `backend/uv.lock` (M1.1) and frontend lockfile committed; installs use the locked forms.
- [ ] Clean-clone install in a new directory succeeds (record commands and versions).
- [ ] Pinned versions match installed versions (including Ruff).
- [ ] No model binaries, credentials, datasets, audio or `.env` in Git (`git ls-files` inspected).

## 3. Quality gates on the release commit

- [ ] CI (minimal pytest + Ruff from M1.1, extended in M11) green on the exact commit (link). Historical local results do not substitute.
- [ ] Backend: pytest, Ruff check, Ruff format check. Frontend: type-check, tests, production build. Record counts.
- [ ] Integration tests against real PostgreSQL and Redis pass (constraints, races, rollback).
- [ ] Real-artifact smoke tests pass for each shipped model; missing-artifact behavior verified.
- [ ] Critical browser journeys pass: login, triage, evidence, review, degraded status, simulator permissions.
- [ ] Accessibility checks run or marked not run (320/768/1024/1440 px, 200% zoom, keyboard, screen reader).

## 4. Security and privacy

- [ ] SECURITY_AUDIT.md procedure executed; report attached.
- [ ] Role/endpoint matrix, source-scope, CSRF/Origin, session expiry/revocation verified.
- [ ] Privacy scan of database, Redis, logs, errors and browser storage: no raw messages, transcripts, audio, secrets.
- [ ] Dependency advisories checked for pinned packages; model and dataset licenses and provenance recorded.
- [ ] Audit HMAC verification run; limits of the integrity claim stated.

## 5. Evaluation honesty

- [ ] Evaluation report attached with denominators, intervals, split definition and provenance.
- [ ] README, UI and demo script contain no performance claim beyond that report; V4 figures labeled historical.
- [ ] Unevaluated languages/speakers/campaigns labeled; fusion marked experimental if no improvement was shown.

## 6. Data and migrations

- [ ] Migrations reviewed; fresh and upgrade paths tested; no destructive step.
- [ ] Backup taken before migrating any retained data; restore drill result recorded (required for pilot).
- [ ] Retention jobs verified, including circular-FK cleanup; backup-retention caveat documented.

## 7. Deployment (scope-dependent)

- [ ] Compose (or approved target) builds from the release commit; data ports private; model mounts read-only; secrets via environment/secret storage, not images.
- [ ] Migrations run once before traffic; health shows liveness and authenticated readiness; missing models prevent a "ready" claim.
- [ ] Synthetic end-to-end smoke test: login, ingest, incident detail, review, logout.
- [ ] Monitoring/alert and log-hygiene checks from MONITORING_MAINTENANCE.md for the scope.
- [ ] Rollback procedure rehearsed: previous tag deployable; schema-compatible.

## 8. Release execution (only with approval)

- [ ] Release PR `dev` → `main` created; description lists changes, risks, verification, limitations.
- [ ] Owner approval recorded.
- [ ] Merge commit created; no force-push.
- [ ] Annotated tag created on the merge commit (`vMAJOR.MINOR.PATCH`); tag never moved afterward.
- [ ] Release notes published, stating scope, verified capabilities and known limitations.
- [ ] `dev` merged back or confirmed in sync with `main`.

## 9. Report

State release scope, commit and tag, URL if any (otherwise "not deployed"), commands with actual results, variable names without values, migrations applied, backup/restore status, rollback plan, open risks and manual blockers. Separate a successful local demo from any claim about production or pilot readiness.
