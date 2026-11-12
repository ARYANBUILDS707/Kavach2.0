# KAVACH Git Workflow

## Status

Procedure document, prepared 31 October 2026 and updated the same day with the owner's final integration policy; **integration policy revised by the owner on 9 November 2026 (SMS MVP-1 first, MASTER_DEVELOPMENT_PLAN.md C-12)**. The four branches below exist locally and on `origin`. **GitHub branch protection, rulesets and the default branch (`main`) have not been configured or changed.**

Owner decisions recorded here:

- `main` stays the stable release branch for validated releases.
- `backend` carries backend milestones; `frontend` carries frontend development independently.
- **First integration (9 Nov 2026, supersedes "one backend PR after M7a"):** the accepted backend MVP-1 and the accepted frontend MVP-1 are integrated into `dev` after **joint acceptance** ([INTEGRATION_PLAN.md](INTEGRATION_PLAN.md) "SMS MVP-1 joint acceptance"), through one owner-controlled `backend` → `dev` PR and one `frontend` → `dev` PR. M5 and M6 are not required first. There is still **no** per-milestone PR into `dev`.
- After MVP-1, postponed work continues on `backend` and `frontend` and reaches `dev` through further owner-controlled PRs with their own acceptance evidence.
- **The user performs every Git mutation**: staging, commits, pushes, merges, branch switches and pull requests. Agents run read-only Git commands only.
- `dev` is *intended* to become the GitHub default branch (not yet applied). `main` and `dev` are to be protected once CI is configured (not yet applied).
- Short-lived `feature/*` branches were allowed by an earlier decision; they are not used for MVP-1 work and must never bypass the joint-acceptance integration pull requests.

CI (`.github/workflows/backend-ci.yml`, M1.1) runs on pushes to `backend`, `dev` and `main` and on pull requests targeting `dev` and `main`. See "CI gates" for its verification status.

## Branches

| Branch | Purpose | Who changes it |
| --- | --- | --- |
| `main` | Stable, validated releases only | Release PR from `dev`, created and merged by the user |
| `dev` | Integration branch | The MVP-1 `backend` → `dev` and `frontend` → `dev` PRs after joint acceptance; later owner-controlled PRs for postponed work |
| `backend` | Backend milestones (dependencies, CI, persistence, auth, ingestion, models, MVP-1 incident reads; later correlation and review APIs) | Direct commits by the user |
| `frontend` | Independent React/TypeScript development (MVP-1 UI, then M7b remainder) | Direct commits by the user |
| `feature/<milestone>-<topic>` | Optional short-lived branch at the owner's discretion; not used for MVP-1 work | The user |

The directories `backend/` and `frontend/` are separate from the branches of the same name. Nothing is pushed directly to `main` or `dev`; they change only through pull requests.

## Flow

```text
backend   (M1.1 → … → M4-I.2 → MVP-1 backend, direct commits, CI on every push) ──┐
                                                          joint MVP-1 acceptance ├──► dev ── release PR ──► main ── tag
frontend  (MVP-1 UI, independent, direct commits, CI once it exists) ───────────┘
later: M5, M6, reviews, M7 advanced, M8–M11 ── further owner-controlled PRs ──► dev
```

### Milestones on `backend` (and, the same way, on `frontend`)

1. Work on `backend` only. Each milestone is implemented, verified and reported against [DEFINITION_OF_DONE.md](DEFINITION_OF_DONE.md) and its acceptance criteria in [MASTER_DEVELOPMENT_PLAN.md](MASTER_DEVELOPMENT_PLAN.md).
2. The owner reviews the milestone report and the `git diff`, then the user commits and pushes to `backend`.
3. The push triggers CI. A milestone is complete only when its acceptance criteria are evidenced **and** CI is green on the pushed commit.
4. There is no pull request into `dev` at the end of a milestone. The next backend milestone builds on `backend` directly.
5. If `dev` changes while backend work is in progress (for example a documentation fix), the user merges `dev` into `backend` (no rebase, no force-push) and the checks are re-run.

### First integration PRs: SMS MVP-1 (approved 9 Nov 2026)

Opened by the user, one from `backend` and one from `frontend` into `dev`, only after **joint MVP-1 acceptance** ([INTEGRATION_PLAN.md](INTEGRATION_PLAN.md)). M5, M6, reviews and the advanced M7 features are not required. Required before the user merges them:

- Every MVP-1 row in [MILESTONE_TRACKER.md](MILESTONE_TRACKER.md) is `complete (verified)` with its report, and the M4-Q model decision is recorded (worker enabled only under C-12 D).
- The joint acceptance run on both PR heads, with exact commands and results, in the integration report.
- CI green on both PRs (the frontend job is added to CI with the frontend scaffold).
- `dev` merged into each branch first if `dev` has moved, with checks re-run.
- `git diff dev...backend` and `git diff dev...frontend` reviewed for secrets, private data, datasets, model binaries, review sheets and accidental files; migrations reviewed separately; no destructive migration without explicit authorization and a recovery plan.
- No unresolved critical or high finding; review by someone other than the author, or an explicit owner waiver recorded in the PR.
- Owner approval recorded in each PR.

Merge order: `backend` first, then `frontend`, so `dev` never holds a UI without its API. Use merge commits (not squash, not rebase) so milestone history is kept intact on `dev`.

### Release

Release PRs go from `dev` to `main` only after [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) passes, with a green CI run on the exact release commit and owner approval. The user creates and merges the PR and creates the tag.

## Authorization rules

- **The user performs all Git mutations** (add, commit, push, merge, branch switch, tag, pull requests) and all deployments. Agents use read-only Git commands (`status`, `diff`, `log`, `show`, `branch`, `ls-remote`) only.
- Never force-push (`--force`, `--force-with-lease`) to `main`, `dev`, `backend` or `frontend`.
- Never rewrite published history, `reset --hard` shared work, or delete protected branches.
- Inspect `git status` and `git diff` before every commit. Do not stage secrets, `.env` files, model binaries, audio, datasets, `.venv`, caches or lockfiles that were not intentionally generated.
- Preserve `docs/CONNECTION_TEST.md` and other unrelated files.

## Commit and PR conventions

- Commit subject in imperative, scoped form consistent with history (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`, `ci:`). One logical change per commit; prefix milestone work with the milestone in the body.
- Keep a commit body for the why, risks and the verification commands run.
- Milestone evidence on `backend` lives in the milestone report (and the commit body); the integration and release PR descriptions summarize every included milestone, list changed areas, and paste exact verification commands and results ([DEFINITION_OF_DONE.md](DEFINITION_OF_DONE.md)).
- Contract changes (API, schema, policy values) are committed together with their source-of-truth document updates.

## CI gates

`.github/workflows/backend-ci.yml` (M1.1) verifies the lockfile, installs from it with `--locked`, and runs pytest, Ruff lint and Ruff format check. Triggers: pushes to `backend`, `dev`, `main`; pull requests into `dev`, `main`. Commit `c8c2ec7` on `backend` added the workflow before `backend` was a push trigger, so **no GitHub Actions run has happened yet**; the first run will be the push that adds the `backend` trigger. Do not describe CI as passing until a green run exists.

For each backend milestone, the gate is a green CI run on the pushed `backend` commit plus the local evidence in the milestone report:

```sh
backend/.venv/bin/python -m pytest backend/tests
backend/.venv/bin/python -m ruff check backend
backend/.venv/bin/python -m ruff format --check backend
```

The `uv run --project backend --locked` forms in CONTRIBUTING.md match CI exactly; prefer them once `backend/.venv` has been deliberately synced to the lockfile. Frontend commands are added when the frontend exists; PostgreSQL/Redis integration commands are added when those milestones land. A local run is evidence, not a substitute for CI; mark checks that could not run as "not run".

## GitHub settings (decided in principle, not applied)

- `dev` is intended to become the default branch. **The setting has not been changed.**
- `main` and `dev` are to be protected **after CI is configured**: require a pull request and at least one approval, require the CI status checks, block force-pushes and deletions, and require branches up to date before merging into `main`. **No protection has been applied.**
- Applying either needs the owner's explicit go-ahead at the time; the earlier decision in principle is not that go-ahead.

## Rollback procedures

Order of preference, least destructive first. All are non-force operations.

1. **Bad commit pushed to `backend`:** the user commits a `git revert <sha>` on `backend` and pushes; CI re-runs. History stays intact.
2. **Bad commit already merged into `dev` or `main`:** the user creates a revert on a branch and opens a PR. For a merge commit use `git revert -m 1 <merge-sha>`. Record the reason in the PR.
3. **Bad release:** revert the release merge on `main` via PR, or release the previous tag again by deploying that tag. Tags are never moved or deleted; publish a new patch tag.
4. **Bad migration:** prefer a forward repair migration. Do not drop data or downgrade destructively. Restore data only via the approved recovery procedure with the data-loss impact stated ([DEPLOYMENT.md](DEPLOYMENT.md), [MONITORING_MAINTENANCE.md](MONITORING_MAINTENANCE.md)). Application rollback must be schema-compatible with the migrated database.
5. **Uncommitted local mistake:** inspect with `git diff`, then the user restores only the specific file (`git restore <path>`) after confirming nothing else is lost. Never `git reset --hard` or `git clean -fd` without the owner's explicit instruction.
6. **Wrong branch commit (not pushed):** create a branch at the commit, then move the original branch back only with owner approval; if already pushed, use a revert PR instead of rewriting.

Never use force-push to undo a pushed change on a protected branch.

## Open decisions

- When to apply the default-branch change and the branch protection for `main` and `dev` (after the first green CI run, on the owner's instruction). Whether `backend` also gets protection (for example blocking force-pushes) is undecided.
- ~~When and how `frontend` integrates into `dev`~~ and ~~how later work reaches `dev`~~: **decided 9 Nov 2026** (MVP-1 joint acceptance, then further owner-controlled PRs from `backend`/`frontend`). Whether later work may also use `feature/*` branches from `dev` stays open.
- Which merge method to configure in GitHub (merge commit recommended for the integration and release PRs).
- Required reviewer count and who reviews while there is a single maintainer (an owner waiver must then be recorded per PR).

## Bounded owner exception — 13 November 2026

For `feature/public-live-analyzer`, the owner's explicit handoff instruction authorizes the agent
to preserve/finish the existing work, commit it, push that branch and open a PR into `dev`.
This is not authorization to merge, change `main`, deploy, rewrite history or alter other worktrees.
